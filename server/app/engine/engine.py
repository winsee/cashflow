"""规则引擎核心（design/02 全文对照实现）。

两个纯函数：
- decide(state, actor_id, action_type, payload, lib) -> list[Event]
  校验行动合法性，产出携带全部结算数值的事件（回放不依赖卡库）。
- apply(state, event) -> RoomState
  唯一的状态变更途径；state = reduce(initial, events)。

Event = {"type": str, "payload": dict}。金额一律非负整数美元。
"""
from __future__ import annotations

import uuid
from typing import Any

from ..data_loader import CardLibrary
from . import formulas as F
from .errors import EngineError
from .models import (
    ActiveCard, ExtraLiability, FastTrackHolding, OwnedBusiness, Phase,
    PlayerState, Prompt, RealEstate, RoomState, RoomStatus, StockHolding,
)

Event = dict[str, Any]

# 玩家主动操作被禁止的场合校验辅助 --------------------------------------------


def _require_playing(state: RoomState) -> None:
    if state.status != RoomStatus.PLAYING:
        raise EngineError("NOT_PLAYING", "对局未开始或已结束")


def _get_player(state: RoomState, pid: str) -> PlayerState:
    p = state.players.get(pid)
    if p is None:
        raise EngineError("NO_PLAYER", "玩家不存在")
    return p


def _require_current(state: RoomState, pid: str) -> PlayerState:
    _require_playing(state)
    p = _get_player(state, pid)
    if state.current_player_id != pid:
        raise EngineError("NOT_YOUR_TURN", "现在不是你的回合")
    if p.phase == Phase.OUT:
        raise EngineError("PLAYER_OUT", "已出局")
    return p


def _require_cash(p: PlayerState, amount: int, loan_hint: bool = True) -> None:
    if p.cash < amount:
        shortfall = amount - p.cash
        raise EngineError(
            "NEED_CASH",
            f"现金不足，还差 ${shortfall:,}" + ("，可先向银行贷款补差" if loan_hint else ""),
            shortfall=shortfall,
        )


def _require_no_bankruptcy(p: PlayerState) -> None:
    if p.in_bankruptcy:
        raise EngineError("IN_BANKRUPTCY", "破产流程中，只能执行破产清算操作")


def _ev(etype: str, **payload) -> Event:
    return {"type": etype, "payload": payload}


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ============================================================ decide

def decide(state: RoomState, actor_id: str | None, action_type: str,
           payload: dict[str, Any], lib: CardLibrary) -> list[Event]:
    handler = _HANDLERS.get(action_type)
    if handler is None:
        raise EngineError("UNKNOWN_ACTION", f"未知操作: {action_type}")
    return handler(state, actor_id, payload or {}, lib)


# ---------- 大厅 / 开局（design/02 §4） ----------

def _d_join(state: RoomState, actor_id, p, lib) -> list[Event]:
    if state.status != RoomStatus.LOBBY:
        raise EngineError("GAME_STARTED", "对局已开始，无法加入")
    if len(state.players) >= state.settings.max_players:
        raise EngineError("ROOM_FULL", "房间已满")
    nickname = str(p.get("nickname", "")).strip()
    if not nickname:
        raise EngineError("BAD_NICKNAME", "昵称不能为空")
    if any(pl.nickname == nickname for pl in state.players.values()):
        raise EngineError("NICKNAME_TAKEN", "昵称已被使用")
    return [_ev("PLAYER_JOINED", player_id=p["player_id"], nickname=nickname,
                is_host=bool(p.get("is_host", False)), seat=len(state.players))]


def _d_select_profession(state, actor_id, p, lib) -> list[Event]:
    if state.status not in (RoomStatus.LOBBY, RoomStatus.SETUP):
        raise EngineError("GAME_STARTED", "对局已开始，不能换职业")
    player = _get_player(state, actor_id)
    card = lib.get(p["professionId"])
    if card.deck != "PROFESSION":
        raise EngineError("BAD_CARD", "所选卡不是职业卡")
    return [_ev("PROFESSION_SELECTED", player_id=player.id,
                profession_id=card.id, title=card.title, data=card.data)]


def _d_select_dream(state, actor_id, p, lib) -> list[Event]:
    if state.status not in (RoomStatus.LOBBY, RoomStatus.SETUP):
        raise EngineError("GAME_STARTED", "对局已开始，不能换梦想")
    player = _get_player(state, actor_id)
    dream = lib.get_ft_dream(p["dreamId"])
    return [_ev("DREAM_SELECTED", player_id=player.id, dream_id=dream.id, name=dream.name)]


def _d_set_turn_order(state, actor_id, p, lib) -> list[Event]:
    host = _get_player(state, actor_id)
    if not host.is_host:
        raise EngineError("NOT_HOST", "只有房主能排定回合顺序")
    order = list(p["order"])
    if sorted(order) != sorted(state.players.keys()):
        raise EngineError("BAD_ORDER", "顺序必须恰好包含全部玩家")
    return [_ev("TURN_ORDER_SET", order=order)]


def _d_start_game(state, actor_id, p, lib) -> list[Event]:
    host = _get_player(state, actor_id)
    if not host.is_host:
        raise EngineError("NOT_HOST", "只有房主能开始对局")
    if state.status not in (RoomStatus.LOBBY, RoomStatus.SETUP):
        raise EngineError("GAME_STARTED", "对局已开始")
    if len(state.players) < 2:
        raise EngineError("NOT_ENOUGH_PLAYERS", "至少 2 名玩家")
    if not state.turn_order:
        raise EngineError("NO_ORDER", "请先线下掷骰并排定回合顺序")
    missing = [pl.nickname for pl in state.players.values() if not pl.profession_id]
    if missing:
        raise EngineError("NO_PROFESSION", f"尚未选职业：{'、'.join(missing)}")
    no_dream = [pl.nickname for pl in state.players.values() if not pl.dream_id]
    if no_dream:
        raise EngineError("NO_DREAM", f"尚未选择梦想：{'、'.join(no_dream)}")
    # 发钱：现金 = 月现金流 + 储蓄；随后储蓄清零（P.2）
    grants = {}
    for pid, pl in state.players.items():
        grants[pid] = F.monthly_cashflow(pl) + pl.savings
    return [_ev("GAME_STARTED", grants=grants)]


# ---------- 回合（design/02 §5） ----------

def _d_end_turn(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    ac = state.active_card
    if ac and not ac.resolved and ac.subtype in (
            "LOSS_EVENT", "EXPENSE_EVENT", "CASH", "CREDIT_OPTION", "INSTALLMENT", "STOCK_EVENT"):
        raise EngineError("CARD_UNRESOLVED", "本回合的强制卡牌尚未结算，不能结束回合")
    return [_ev("TURN_ENDED", player_id=player.id)]


def _d_payday(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    if player.phase != Phase.RAT_RACE:
        raise EngineError("WRONG_PHASE", "快车道请用现金流量日收款")
    times = int(p.get("times", 1))
    if times < 1 or times > 3:
        raise EngineError("BAD_TIMES", "结算次数须为 1–3")
    cf = F.monthly_cashflow(player)
    if player.cash + cf * times < 0:
        raise EngineError(
            "NEED_LOAN_OR_BANKRUPTCY",
            f"月现金流为 ${cf:,}，现金不足以支付，请先贷款或进入破产流程",
            shortfall=-(player.cash + cf * times),
        )
    return [_ev("PAYDAY", player_id=player.id, cashflow=cf, times=times)]


# ---------- 抽卡与卡牌效果（design/02 §6） ----------

_OPPORTUNITY_DECKS = ("SMALL_DEAL", "BIG_DEAL")


def _d_draw_card(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    if player.phase != Phase.RAT_RACE:
        raise EngineError("WRONG_PHASE", "快车道阶段不抽内圈卡")
    if state.active_card and not state.active_card.resolved:
        raise EngineError("CARD_ACTIVE", "上一张卡尚未处理完")
    card = lib.get(p["cardId"])
    if card.deck not in (*_OPPORTUNITY_DECKS, "MARKET", "DOODAD"):
        raise EngineError("BAD_CARD", "不是可抽的牌叠")
    events = [_ev("CARD_DRAWN", player_id=player.id, card_id=card.id,
                  deck=card.deck, subtype=card.subtype, title=card.title)]

    if card.deck == "MARKET":
        events += _market_events(state, player, card)
    return events


def _market_events(state: RoomState, drawer: PlayerState, card) -> list[Event]:
    """市场风云：按 targetAssetType 找出受影响玩家（design/02 §6.3）。"""
    d = card.data
    target = d.get("targetAssetType", "")
    events: list[Event] = []
    if card.subtype in ("BUYER_OFFER", "MULTIPLE_OFFER"):
        for pl in state.players.values():
            if pl.phase != Phase.RAT_RACE:
                continue
            for asset in [*pl.real_estates, *pl.businesses]:
                if asset.asset_type == target:
                    price = (d["pricePerUnit"] if card.subtype == "BUYER_OFFER"
                             else int(asset.cost * d["multiple"]))
                    events.append(_ev(
                        "MARKET_PROMPTED", prompt_id=_new_id(), player_id=pl.id,
                        asset_id=asset.id, asset_name=asset.name, price=price,
                        mortgage=asset.mortgage, card_id=card.id))
        if not events:
            events.append(_ev("CARD_RESOLVED", card_id=card.id, note="无人持有相关资产"))
    elif card.subtype == "ECONOMY_EVENT":
        if d.get("kind") == "FORCED_SURRENDER":
            for pl in state.players.values():
                if pl.phase != Phase.RAT_RACE:
                    continue
                ids = [a.id for a in [*pl.real_estates, *pl.businesses] if a.asset_type == target]
                if ids:
                    events.append(_ev("ASSETS_SURRENDERED", player_id=pl.id,
                                      asset_ids=ids, card_id=card.id))
        events.append(_ev("CARD_RESOLVED", card_id=card.id))
    return events


def _active_card_or_err(state: RoomState, actor_id: str) -> tuple[ActiveCard, PlayerState]:
    ac = state.active_card
    if ac is None or ac.resolved:
        raise EngineError("NO_ACTIVE_CARD", "当前没有待处理的卡")
    if ac.drawer_id != actor_id:
        raise EngineError("NOT_DRAWER", "只有抽卡人能做这个决定")
    return ac, _get_player(state, actor_id)


def _d_card_decision(state, actor_id, p, lib) -> list[Event]:
    ac, player = _active_card_or_err(state, actor_id)
    _require_no_bankruptcy(player)
    card = lib.get(ac.card_id)
    decision = p.get("decision")
    d = card.data

    if ac.subtype in ("REALESTATE", "BUSINESS"):
        if decision == "pass":
            return [_ev("CARD_PASSED", player_id=player.id, card_id=card.id)]
        if decision == "buy":
            _require_cash(player, d["downPayment"])
            return [_asset_bought_event(player.id, card)]
        if decision == "resell":
            to_id = p["toPlayerId"]
            fee = int(p.get("price", 0))
            if to_id == player.id or to_id not in state.players:
                raise EngineError("BAD_TARGET", "转卖对象无效")
            if fee < 0:
                raise EngineError("BAD_AMOUNT", "转让费不能为负")
            return [_ev("RESELL_OFFERED", prompt_id=_new_id(), card_id=card.id,
                        from_player_id=player.id, to_player_id=to_id, fee=fee,
                        down_payment=d["downPayment"], title=card.title)]
        raise EngineError("BAD_DECISION", "该卡只能 买 / 放弃 / 转卖")

    if ac.subtype == "STOCK_OFFER":
        if decision == "pass":
            return [_ev("CARD_PASSED", player_id=player.id, card_id=card.id)]
        raise EngineError("BAD_DECISION", "股票卡用 买入/卖出 操作，或放弃")

    if ac.subtype == "STOCK_EVENT":
        num, den = (int(x) for x in d["ratio"].split(":"))
        return [_ev("SHARES_ADJUSTED", card_id=card.id, symbol=d["symbol"],
                    ratio_num=num, ratio_den=den)]

    if ac.subtype == "LOSS_EVENT":
        amount = d["amount"] if _condition_met(player, d.get("condition")) else 0
        _require_cash(player, amount)
        return [_ev("LOSS_PAID", player_id=player.id, card_id=card.id, amount=amount)]

    if ac.subtype == "EXPENSE_EVENT":
        units = sum(1 for a in player.real_estates if a.asset_type == d["targetAssetType"])
        amount = units * d["amountPerUnit"]
        _require_cash(player, amount)
        return [_ev("EXPENSE_EVENT_PAID", player_id=player.id, card_id=card.id,
                    amount=amount, units=units)]

    if ac.subtype == "CASH":
        amount = d["amount"] if _condition_met(player, d.get("condition")) else 0
        _require_cash(player, amount)
        return [_ev("DOODAD_PAID", player_id=player.id, card_id=card.id,
                    amount=amount, method="cash")]

    if ac.subtype == "CREDIT_OPTION":
        if decision == "credit":
            return [_ev("DOODAD_PAID", player_id=player.id, card_id=card.id,
                        amount=0, method="credit", credit_amount=d["amount"],
                        credit_monthly=d["creditMonthly"], title=card.title)]
        _require_cash(player, d["amount"])
        return [_ev("DOODAD_PAID", player_id=player.id, card_id=card.id,
                    amount=d["amount"], method="cash")]

    if ac.subtype == "INSTALLMENT":
        _require_cash(player, d["downPayment"])
        return [_ev("INSTALLMENT_ADDED", player_id=player.id, card_id=card.id,
                    down_payment=d["downPayment"], liability=d["liability"],
                    liability_name=d["liabilityName"], monthly=d["monthly"],
                    liability_id=_new_id())]

    raise EngineError("BAD_CARD", f"未支持的卡类型: {ac.subtype}")


def _condition_met(p: PlayerState, condition: str | None) -> bool:
    if not condition:
        return True
    if condition == "hasChildren":
        return p.child_count > 0
    if condition == "hasRentalProperty":
        return len(p.real_estates) > 0
    raise EngineError("BAD_CONDITION", f"未知条件: {condition}")


def _asset_bought_event(player_id: str, card) -> Event:
    d = card.data
    return _ev("ASSET_BOUGHT", player_id=player_id, card_id=card.id,
               asset_id=_new_id(), kind="REALESTATE" if card.subtype == "REALESTATE" else "BUSINESS",
               asset_type=d.get("assetType", "企业"), name=card.title,
               cost=d["cost"], down_payment=d["downPayment"],
               mortgage=d.get("mortgage", 0), cashflow=d["cashflow"])


def _d_resell_confirm(state, actor_id, p, lib) -> list[Event]:
    prompt = _find_prompt(state, p["promptId"], actor_id, "RESELL_CONFIRM")
    pd = prompt.payload
    if not p.get("accept"):
        return [_ev("RESELL_REJECTED", prompt_id=prompt.id,
                    from_player_id=pd["from_player_id"], to_player_id=actor_id)]
    buyer = _get_player(state, actor_id)
    card = lib.get(pd["card_id"])
    _require_cash(buyer, pd["fee"] + card.data["downPayment"])
    return [_ev("RESELL_CONFIRMED", prompt_id=prompt.id, card_id=card.id,
                from_player_id=pd["from_player_id"], to_player_id=actor_id,
                fee=pd["fee"]),
            _asset_bought_event(actor_id, card)]


# ---------- 股票（design/02 §6.2） ----------

def _stock_card(state: RoomState, lib) -> tuple[ActiveCard, dict]:
    ac = state.active_card
    if ac is None or ac.subtype != "STOCK_OFFER" or ac.resolved:
        raise EngineError("NO_STOCK_WINDOW", "当前没有生效的股票报价")
    return ac, lib.get(ac.card_id).data


def _d_stock_buy(state, actor_id, p, lib) -> list[Event]:
    ac, d = _stock_card(state, lib)
    if ac.drawer_id != actor_id:
        raise EngineError("NOT_DRAWER", "只有抽卡人能按今日价格买入")
    player = _get_player(state, actor_id)
    _require_no_bankruptcy(player)
    qty = int(p["qty"])
    if qty <= 0:
        raise EngineError("BAD_AMOUNT", "股数须为正整数")
    cost = qty * d["price"]
    _require_cash(player, cost)
    return [_ev("STOCK_BOUGHT", player_id=actor_id, card_id=ac.card_id,
                symbol=d["symbol"], qty=qty, price=d["price"],
                dividend_per_share=d.get("dividendPerShare", 0), cost=cost)]


def _d_stock_sell(state, actor_id, p, lib) -> list[Event]:
    ac, d = _stock_card(state, lib)
    player = _get_player(state, actor_id)
    _require_no_bankruptcy(player)
    if player.phase != Phase.RAT_RACE:
        raise EngineError("WRONG_PHASE", "只有老鼠赛跑阶段的玩家可交易")
    qty = int(p["qty"])
    held = sum(s.shares for s in player.stocks if s.symbol == d["symbol"])
    if qty <= 0 or qty > held:
        raise EngineError("BAD_AMOUNT", f"持有 {held} 股，无法卖出 {qty} 股")
    return [_ev("STOCK_SOLD", player_id=actor_id, card_id=ac.card_id,
                symbol=d["symbol"], qty=qty, price=d["price"], proceeds=qty * d["price"])]


# ---------- 市场卖出决策 ----------

def _find_prompt(state: RoomState, prompt_id: str, actor_id: str, kind: str) -> Prompt:
    for pr in state.prompts:
        if pr.id == prompt_id:
            if pr.target_player_id != actor_id:
                raise EngineError("NOT_TARGET", "这个决策不属于你")
            if pr.kind != kind:
                raise EngineError("BAD_PROMPT", "决策类型不匹配")
            return pr
    raise EngineError("NO_PROMPT", "该决策已过期或不存在")


def _d_market_sell(state, actor_id, p, lib) -> list[Event]:
    prompt = _find_prompt(state, p["promptId"], actor_id, "MARKET_SELL")
    player = _get_player(state, actor_id)
    _require_no_bankruptcy(player)
    pd = prompt.payload
    if not p.get("accept"):
        return [_ev("MARKET_DECLINED", prompt_id=prompt.id, player_id=actor_id)]
    # 收益 = 卖价 − 抵押贷款；为负时向银行付差额（design/02 §6.1）
    net = pd["price"] - pd["mortgage"]
    if net < 0:
        _require_cash(player, -net)
    return [_ev("MARKET_SOLD", prompt_id=prompt.id, player_id=actor_id,
                asset_id=pd["asset_id"], price=pd["price"], mortgage=pd["mortgage"],
                net=net, card_id=pd["card_id"])]


# ---------- 银行操作（design/02 §7） ----------

def _d_take_loan(state, actor_id, p, lib) -> list[Event]:
    _require_playing(state)
    player = _get_player(state, actor_id)
    _require_no_bankruptcy(player)
    if player.phase == Phase.OUT:
        raise EngineError("PLAYER_OUT", "已出局")
    if player.phase == Phase.FAST_TRACK:
        raise EngineError("NO_FT_LOAN", "快车道无银行贷款（P.5）")
    amount = int(p["amount"])
    if amount <= 0 or amount % 1000 != 0:
        raise EngineError("BAD_AMOUNT", "贷款须为 $1,000 的正整数倍")
    return [_ev("LOAN_TAKEN", player_id=player.id, amount=amount)]


def _d_repay_loan(state, actor_id, p, lib) -> list[Event]:
    # 破产流程第2步“所得偿付债务”依赖还款，故不禁止破产中还款（design/02 §8）
    _require_playing(state)
    player = _get_player(state, actor_id)
    amount = int(p["amount"])
    if amount <= 0 or amount % 1000 != 0:
        raise EngineError("BAD_AMOUNT", "还款须为 $1,000 的正整数倍")
    if amount > player.liabilities.bank_loan:
        raise EngineError("BAD_AMOUNT", "超过银行贷款余额")
    _require_cash(player, amount, loan_hint=False)
    return [_ev("LOAN_REPAID", player_id=player.id, amount=amount)]


_PAYOFF_MAP = {
    # liabilityId -> (负债字段, 支出字段)
    "mortgage": ("mortgage", "mortgage_payment"),
    "school_loan": ("school_loan", "school_loan_payment"),
    "car_loan": ("car_loan", "car_loan_payment"),
    "credit_card": ("credit_card", "credit_card_payment"),
    "extra": ("extra", "extra_expenses"),
}


def _d_pay_off_debt(state, actor_id, p, lib) -> list[Event]:
    # 破产清偿也走本入口，故不设 _require_no_bankruptcy
    player = _require_current(state, actor_id)
    lid = p["liabilityId"]
    if lid in _PAYOFF_MAP:
        liab_field, _ = _PAYOFF_MAP[lid]
        amount = getattr(player.liabilities, liab_field)
    else:
        row = next((l for l in player.extra_liabilities if l.id == lid), None)
        if row is None:
            raise EngineError("NO_LIABILITY", "负债项不存在或不可清偿（税金/其他/孩子支出为长期支出）")
        amount = row.amount
    if amount <= 0:
        raise EngineError("NO_LIABILITY", "该负债已为零")
    _require_cash(player, amount, loan_hint=False)   # 清偿须一次性全额（P.4）
    return [_ev("DEBT_PAID_OFF", player_id=player.id, liability_id=lid, amount=amount)]


# ---------- 棋盘事件（design/02 §5） ----------

def _d_add_child(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    if player.child_count >= 3:
        return [_ev("CHILD_NOOP", player_id=player.id)]   # 满 3 无效果（P.4）
    return [_ev("CHILD_ADDED", player_id=player.id)]


def _d_charity(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    amount = (F.total_income(player) + 5) // 10   # 总收入×10%，四舍五入到美元
    _require_cash(player, amount)
    return [_ev("CHARITY_DONATED", player_id=player.id, amount=amount)]


def _d_unemployment(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    amount = F.total_expenses(player)
    _require_cash(player, amount)
    return [_ev("UNEMPLOYMENT_HIT", player_id=player.id, amount=amount)]


# ---------- 玩家间交易（design/02 §6.5） ----------

def _d_transfer_request(state, actor_id, p, lib) -> list[Event]:
    _require_playing(state)
    player = _get_player(state, actor_id)
    _require_no_bankruptcy(player)
    to_id = p["toPlayerId"]
    if to_id == actor_id or to_id not in state.players:
        raise EngineError("BAD_TARGET", "转账对象无效")
    amount = int(p["amount"])
    if amount <= 0:
        raise EngineError("BAD_AMOUNT", "金额须为正整数")
    return [_ev("TRANSFER_REQUESTED", prompt_id=_new_id(), from_player_id=actor_id,
                to_player_id=to_id, amount=amount, reason=str(p.get("reason", "")))]


def _d_transfer_confirm(state, actor_id, p, lib) -> list[Event]:
    prompt = _find_prompt(state, p["promptId"], actor_id, "TRANSFER_CONFIRM")
    pd = prompt.payload
    if not p.get("accept"):
        return [_ev("TRANSFER_REJECTED", prompt_id=prompt.id)]
    payer = _get_player(state, pd["from_player_id"])
    _require_cash(payer, pd["amount"], loan_hint=False)
    return [_ev("TRANSFER_COMPLETED", prompt_id=prompt.id,
                from_player_id=pd["from_player_id"], to_player_id=actor_id,
                amount=pd["amount"], reason=pd.get("reason", ""))]


# ---------- 破产（design/02 §8） ----------

def _d_bankruptcy_start(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    cf = F.monthly_cashflow(player)
    if cf >= 0 or player.cash + cf >= 0:
        raise EngineError("NOT_BANKRUPT", "未满足破产条件（月现金流为负且现金不足支付）")
    return [_ev("BANKRUPTCY_STARTED", player_id=player.id)]


def _d_bankruptcy_sell(state, actor_id, p, lib) -> list[Event]:
    _require_playing(state)
    player = _get_player(state, actor_id)
    if not player.in_bankruptcy:
        raise EngineError("NOT_IN_BANKRUPTCY", "不在破产流程中")
    aid = p["assetId"]
    for a in player.real_estates:
        if a.id == aid:
            return [_ev("BANKRUPTCY_ASSET_SOLD", player_id=player.id, asset_id=aid,
                        kind="REALESTATE", proceeds=a.down_payment // 2)]
    for a in player.businesses:
        if a.id == aid:
            return [_ev("BANKRUPTCY_ASSET_SOLD", player_id=player.id, asset_id=aid,
                        kind="BUSINESS", proceeds=a.down_payment // 2)]
    if aid.startswith("stock:"):
        symbol = aid.split(":", 1)[1]
        basis = sum(s.shares * s.cost_per_share for s in player.stocks if s.symbol == symbol)
        if basis > 0:
            return [_ev("BANKRUPTCY_ASSET_SOLD", player_id=player.id, asset_id=aid,
                        kind="STOCK", symbol=symbol, proceeds=basis // 2)]
    raise EngineError("NO_ASSET", "资产不存在")


def _d_bankruptcy_resolve(state, actor_id, p, lib) -> list[Event]:
    _require_playing(state)
    player = _get_player(state, actor_id)
    if not player.in_bankruptcy:
        raise EngineError("NOT_IN_BANKRUPTCY", "不在破产流程中")
    cf = F.monthly_cashflow(player)
    has_assets = bool(player.real_estates or player.businesses or player.stocks)
    if cf < 0 and has_assets:
        raise EngineError("MUST_SELL_MORE", "月现金流仍为负，须继续以首期 50% 向银行变卖资产")
    return [_ev("BANKRUPTCY_RESOLVED", player_id=player.id)]


# ---------- 快车道（design/02 §9–§11） ----------

def _require_ft(state: RoomState, pid: str) -> PlayerState:
    _require_playing(state)
    p = _get_player(state, pid)
    if p.phase != Phase.FAST_TRACK:
        raise EngineError("WRONG_PHASE", "不在快车道阶段")
    return p


def _d_enter_fasttrack(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    if player.phase != Phase.RAT_RACE:
        raise EngineError("WRONG_PHASE", "已在快车道")
    passive = F.passive_income(player)
    if passive <= F.total_expenses(player):
        raise EngineError("NOT_ELIGIBLE", "尚未达成 非工资收入 > 总支出")
    initial = F.fasttrack_initial_income(passive)
    return [_ev("ENTERED_FASTTRACK", player_id=player.id, passive_income=passive,
                initial_income=initial, cash_returned=player.cash)]


def _d_ft_payday(state, actor_id, p, lib) -> list[Event]:
    player = _require_ft(state, actor_id)
    times = int(p.get("times", 1))
    if times < 1 or times > 4:
        raise EngineError("BAD_TIMES", "收款次数须为 1–4")
    return [_ev("FT_PAYDAY", player_id=player.id,
                amount=player.fasttrack.current_income * times, times=times)]


def _d_ft_buy_business(state, actor_id, p, lib) -> list[Event]:
    player = _require_ft(state, actor_id)
    sq = lib.get_ft_business(p["squareId"])
    if sq.id in state.ft_sold_squares:
        raise EngineError("SQUARE_SOLD", "该企业已被其他玩家买断")
    _require_cash(player, sq.down_payment, loan_hint=False)
    if sq.dice_rule:
        roll = int(p.get("diceRoll", 0))
        if roll < 1 or roll > 6:
            raise EngineError("NEED_DICE", "该格需要线下掷 1 粒骰子并录入点数")
        success = roll >= sq.dice_rule["threshold"]
        return [_ev("FT_BUSINESS_BOUGHT", player_id=player.id, square_id=sq.id,
                    name=sq.name, down_payment=sq.down_payment, dice_roll=roll,
                    success=success,
                    cashflow=sq.dice_rule.get("successCashflow", 0) if success else 0,
                    lump_sum=sq.dice_rule.get("lumpSum", 0) if success else 0)]
    return [_ev("FT_BUSINESS_BOUGHT", player_id=player.id, square_id=sq.id,
                name=sq.name, down_payment=sq.down_payment, success=True,
                cashflow=sq.cashflow, lump_sum=0)]


def _dream_price(state: RoomState, dream) -> int:
    bumps = state.dream_price_bumps.get(dream.id, 0)
    return dream.price * (1 + bumps)


def _d_ft_buy_dream(state, actor_id, p, lib) -> list[Event]:
    player = _require_ft(state, actor_id)
    dream = lib.get_ft_dream(p["squareId"])
    if player.dream_id != dream.id:
        raise EngineError("NOT_YOUR_DREAM", "只能购买自己选定的梦想（他人梦想可双倍加价）")
    price = _dream_price(state, dream)
    _require_cash(player, price, loan_hint=False)
    return [_ev("FT_DREAM_BOUGHT", player_id=player.id, square_id=dream.id,
                name=dream.name, price=price)]


def _d_ft_double_dream(state, actor_id, p, lib) -> list[Event]:
    player = _require_ft(state, actor_id)
    dream = lib.get_ft_dream(p["squareId"])
    if player.dream_id == dream.id:
        raise EngineError("OWN_DREAM", "这是你自己的梦想，直接购买即可")
    if not any(pl.dream_id == dream.id for pl in state.players.values()):
        raise EngineError("NOT_CHOSEN", "该梦想不属于任何玩家，无需加价")
    price = _dream_price(state, dream)
    _require_cash(player, price, loan_hint=False)
    return [_ev("FT_DREAM_DOUBLED", player_id=player.id, square_id=dream.id,
                name=dream.name, price_paid=price, base_price=dream.price)]


def _d_ft_charity(state, actor_id, p, lib) -> list[Event]:
    player = _require_ft(state, actor_id)
    _require_cash(player, lib.ft_charity_cost, loan_hint=False)
    return [_ev("FT_CHARITY_DONATED", player_id=player.id, amount=lib.ft_charity_cost)]


def _d_ft_cash_hit(kind: str, factor_desc: str):
    def handler(state, actor_id, p, lib) -> list[Event]:
        player = _require_ft(state, actor_id)
        if kind == "DIVORCE":
            amount = player.cash
        else:
            amount = player.cash // 2
        return [_ev("FT_CASH_HIT", player_id=player.id, kind=kind, amount=amount)]
    return handler


# ---------- 房主 ----------

def _d_host_adjust(state, actor_id, p, lib) -> list[Event]:
    host = _get_player(state, actor_id)
    if not host.is_host:
        raise EngineError("NOT_HOST", "只有房主能调账")
    target = _get_player(state, p["playerId"])
    delta = int(p["delta"])
    if target.cash + delta < 0:
        raise EngineError("BAD_AMOUNT", "调整后现金不能为负")
    return [_ev("HOST_ADJUSTED", player_id=target.id, delta=delta,
                reason=str(p.get("reason", "")))]


_HANDLERS = {
    "JOIN": _d_join,
    "SELECT_PROFESSION": _d_select_profession,
    "SELECT_DREAM": _d_select_dream,
    "SET_TURN_ORDER": _d_set_turn_order,
    "START_GAME": _d_start_game,
    "END_TURN": _d_end_turn,
    "PAYDAY": _d_payday,
    "DRAW_CARD": _d_draw_card,
    "CARD_DECISION": _d_card_decision,
    "RESELL_CONFIRM": _d_resell_confirm,
    "STOCK_BUY": _d_stock_buy,
    "STOCK_SELL": _d_stock_sell,
    "MARKET_SELL": _d_market_sell,
    "TAKE_LOAN": _d_take_loan,
    "REPAY_LOAN": _d_repay_loan,
    "PAY_OFF_DEBT": _d_pay_off_debt,
    "ADD_CHILD": _d_add_child,
    "CHARITY": _d_charity,
    "UNEMPLOYMENT": _d_unemployment,
    "TRANSFER_REQUEST": _d_transfer_request,
    "TRANSFER_CONFIRM": _d_transfer_confirm,
    "BANKRUPTCY_START": _d_bankruptcy_start,
    "BANKRUPTCY_SELL_ASSET": _d_bankruptcy_sell,
    "BANKRUPTCY_RESOLVE": _d_bankruptcy_resolve,
    "ENTER_FASTTRACK": _d_enter_fasttrack,
    "FT_PAYDAY": _d_ft_payday,
    "FT_BUY_BUSINESS": _d_ft_buy_business,
    "FT_BUY_DREAM": _d_ft_buy_dream,
    "FT_DOUBLE_DREAM": _d_ft_double_dream,
    "FT_CHARITY": _d_ft_charity,
    "FT_TAX_AUDIT": _d_ft_cash_hit("TAX_AUDIT", "半额"),
    "FT_DIVORCE": _d_ft_cash_hit("DIVORCE", "全额"),
    "FT_LAWSUIT": _d_ft_cash_hit("LAWSUIT", "半额"),
    "HOST_ADJUST": _d_host_adjust,
}


# ============================================================ apply

def apply(state: RoomState, event: Event) -> RoomState:
    s = state.model_copy(deep=True)
    handler = _APPLIERS.get(event["type"])
    if handler is None:
        raise EngineError("UNKNOWN_EVENT", f"未知事件: {event['type']}")
    handler(s, event.get("payload", {}))
    return s


def _a_player_joined(s: RoomState, p) -> None:
    s.players[p["player_id"]] = PlayerState(
        id=p["player_id"], nickname=p["nickname"], is_host=p["is_host"], seat=p["seat"])


def _a_profession_selected(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    d = p["data"]
    pl.profession_id = p["profession_id"]
    pl.profession_title = p["title"]
    pl.salary = d["salary"]
    pl.taxes = d["taxes"]
    pl.mortgage_payment = d["mortgagePayment"]
    pl.school_loan_payment = d["schoolLoanPayment"]
    pl.car_loan_payment = d["carLoanPayment"]
    pl.credit_card_payment = d["creditCardPayment"]
    pl.extra_expenses = d["extraExpenses"]
    pl.other_expenses = d["otherExpenses"]
    pl.per_child_expense = d["perChildExpense"]
    pl.savings = d["savings"]
    liab = d["liabilities"]
    pl.liabilities.mortgage = liab["mortgage"]
    pl.liabilities.school_loan = liab["schoolLoan"]
    pl.liabilities.car_loan = liab["carLoan"]
    pl.liabilities.credit_card = liab["creditCard"]
    pl.liabilities.extra = liab["extra"]
    # 初始约束：无银行贷款、无孩子（P.2）
    pl.liabilities.bank_loan = 0
    pl.child_count = 0
    pl.cash = 0


def _a_dream_selected(s: RoomState, p) -> None:
    s.players[p["player_id"]].dream_id = p["dream_id"]


def _a_turn_order_set(s: RoomState, p) -> None:
    s.turn_order = list(p["order"])
    if s.status == RoomStatus.LOBBY:
        s.status = RoomStatus.SETUP
    for i, pid in enumerate(s.turn_order):
        s.players[pid].seat = i


def _a_game_started(s: RoomState, p) -> None:
    for pid, grant in p["grants"].items():
        pl = s.players[pid]
        pl.cash = grant          # 现金 = 月现金流 + 储蓄
        pl.savings = 0           # 随后注销储蓄（P.2）
    s.status = RoomStatus.PLAYING
    s.turn_index = 0
    s.turn_count = 1


def _a_turn_ended(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    # 慈善轮数倒计时（捐款当轮不消耗）
    if pl.charity_turns > 0 and not getattr(pl, "charity_just_donated", False):
        pl.charity_turns -= 1
    pl.charity_just_donated = False
    # 机会卡失效（⚠️ADAPT：抽卡人结束回合时失效），其市场/转卖窗口一并关闭
    s.active_card = None
    s.prompts = [pr for pr in s.prompts if pr.kind == "TRANSFER_CONFIRM"]
    # 推进回合指针，自动跳过 OUT 与停赛玩家
    n = len(s.turn_order)
    for _ in range(n * 3 + 1):
        s.turn_index += 1
        if s.turn_index >= n:
            s.turn_index = 0
            s.turn_count += 1
        nxt = s.players[s.turn_order[s.turn_index]]
        if nxt.phase == Phase.OUT:
            continue
        if nxt.skip_turns > 0:
            nxt.skip_turns -= 1
            continue
        break


def _a_payday(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash += p["cashflow"] * p["times"]


def _a_card_drawn(s: RoomState, p) -> None:
    resolved = p["deck"] == "MARKET"   # 市场卡的效果在伴随事件中完成
    s.active_card = ActiveCard(card_id=p["card_id"], deck=p["deck"],
                               subtype=p["subtype"], drawer_id=p["player_id"],
                               resolved=resolved)


def _a_card_resolved(s: RoomState, p) -> None:
    if s.active_card and s.active_card.card_id == p["card_id"]:
        s.active_card.resolved = True


def _a_card_passed(s: RoomState, p) -> None:
    if s.active_card:
        s.active_card.resolved = True


def _mark_resolved(s: RoomState) -> None:
    if s.active_card:
        s.active_card.resolved = True


def _a_asset_bought(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["down_payment"]
    if p["kind"] == "REALESTATE":
        pl.real_estates.append(RealEstate(
            id=p["asset_id"], card_id=p["card_id"], asset_type=p["asset_type"],
            name=p["name"], cost=p["cost"], down_payment=p["down_payment"],
            mortgage=p["mortgage"], cashflow=p["cashflow"]))
    else:
        pl.businesses.append(OwnedBusiness(
            id=p["asset_id"], card_id=p["card_id"], asset_type=p["asset_type"],
            name=p["name"], cost=p["cost"], down_payment=p["down_payment"],
            mortgage=p["mortgage"], cashflow=p["cashflow"]))
    if s.active_card and s.active_card.card_id == p["card_id"]:
        s.active_card.resolved = True


def _a_resell_offered(s: RoomState, p) -> None:
    s.prompts.append(Prompt(id=p["prompt_id"], kind="RESELL_CONFIRM",
                            target_player_id=p["to_player_id"], payload=dict(p)))
    _mark_resolved(s)    # 抽卡人已做出决策；买家确认走 prompt


def _remove_prompt(s: RoomState, prompt_id: str) -> None:
    s.prompts = [pr for pr in s.prompts if pr.id != prompt_id]


def _a_resell_confirmed(s: RoomState, p) -> None:
    _remove_prompt(s, p["prompt_id"])
    buyer = s.players[p["to_player_id"]]
    seller = s.players[p["from_player_id"]]
    buyer.cash -= p["fee"]
    seller.cash += p["fee"]
    # 资产入账由紧随的 ASSET_BOUGHT 事件完成


def _a_resell_rejected(s: RoomState, p) -> None:
    _remove_prompt(s, p["prompt_id"])


def _a_stock_bought(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["cost"]
    for h in pl.stocks:
        if h.symbol == p["symbol"] and h.cost_per_share == p["price"]:
            h.shares += p["qty"]
            break
    else:
        pl.stocks.append(StockHolding(symbol=p["symbol"], shares=p["qty"],
                                      cost_per_share=p["price"],
                                      dividend_per_share=p["dividend_per_share"]))


def _a_stock_sold(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash += p["proceeds"]
    remaining = p["qty"]
    kept = []
    for h in pl.stocks:
        if h.symbol == p["symbol"] and remaining > 0:
            take = min(h.shares, remaining)
            h.shares -= take
            remaining -= take
        if h.shares > 0:
            kept.append(h)
    pl.stocks = kept


def _a_shares_adjusted(s: RoomState, p) -> None:
    num, den = p["ratio_num"], p["ratio_den"]   # "2:1" → 每2股并1股
    for pl in s.players.values():
        kept = []
        for h in pl.stocks:
            if h.symbol == p["symbol"]:
                h.shares = h.shares * den // num
            if h.shares > 0:
                kept.append(h)
        pl.stocks = kept
    _mark_resolved(s)


def _a_loss_paid(s: RoomState, p) -> None:
    s.players[p["player_id"]].cash -= p["amount"]
    _mark_resolved(s)


def _a_expense_event_paid(s: RoomState, p) -> None:
    s.players[p["player_id"]].cash -= p["amount"]
    _mark_resolved(s)


def _a_doodad_paid(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    if p["method"] == "credit":
        pl.liabilities.credit_card += p["credit_amount"]
        pl.credit_card_payment += p["credit_monthly"]
    else:
        pl.cash -= p["amount"]
    _mark_resolved(s)


def _a_installment_added(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["down_payment"]
    pl.extra_liabilities.append(ExtraLiability(
        id=p["liability_id"], name=p["liability_name"],
        amount=p["liability"], monthly=p["monthly"]))
    _mark_resolved(s)


def _a_market_prompted(s: RoomState, p) -> None:
    s.prompts.append(Prompt(id=p["prompt_id"], kind="MARKET_SELL",
                            target_player_id=p["player_id"], payload=dict(p)))


def _remove_asset(pl: PlayerState, asset_id: str) -> None:
    pl.real_estates = [a for a in pl.real_estates if a.id != asset_id]
    pl.businesses = [a for a in pl.businesses if a.id != asset_id]


def _a_market_sold(s: RoomState, p) -> None:
    _remove_prompt(s, p["prompt_id"])
    pl = s.players[p["player_id"]]
    pl.cash += p["net"]                    # 卖价−抵押；为负即向银行付差额
    _remove_asset(pl, p["asset_id"])


def _a_market_declined(s: RoomState, p) -> None:
    _remove_prompt(s, p["prompt_id"])


def _a_assets_surrendered(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    for aid in p["asset_ids"]:
        _remove_asset(pl, aid)


def _a_loan_taken(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.liabilities.bank_loan += p["amount"]
    pl.cash += p["amount"]


def _a_loan_repaid(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.liabilities.bank_loan -= p["amount"]
    pl.cash -= p["amount"]


def _a_debt_paid_off(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    lid = p["liability_id"]
    pl.cash -= p["amount"]
    if lid in _PAYOFF_MAP:
        liab_field, exp_field = _PAYOFF_MAP[lid]
        setattr(pl.liabilities, liab_field, 0)
        setattr(pl, exp_field, 0)
    else:
        pl.extra_liabilities = [l for l in pl.extra_liabilities if l.id != lid]


def _a_child_added(s: RoomState, p) -> None:
    s.players[p["player_id"]].child_count += 1


def _a_child_noop(s: RoomState, p) -> None:
    pass


def _a_charity_donated(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["amount"]
    pl.charity_turns = 3
    pl.charity_just_donated = True


def _a_unemployment_hit(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["amount"]
    pl.skip_turns = 2
    pl.charity_turns = 0    # 失业清除慈善状态（P.4）
    pl.charity_just_donated = False


def _a_transfer_requested(s: RoomState, p) -> None:
    s.prompts.append(Prompt(id=p["prompt_id"], kind="TRANSFER_CONFIRM",
                            target_player_id=p["to_player_id"], payload=dict(p)))


def _a_transfer_completed(s: RoomState, p) -> None:
    _remove_prompt(s, p["prompt_id"])
    s.players[p["from_player_id"]].cash -= p["amount"]
    s.players[p["to_player_id"]].cash += p["amount"]


def _a_transfer_rejected(s: RoomState, p) -> None:
    _remove_prompt(s, p["prompt_id"])


def _a_bankruptcy_started(s: RoomState, p) -> None:
    s.players[p["player_id"]].in_bankruptcy = True


def _a_bankruptcy_asset_sold(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash += p["proceeds"]
    if p["kind"] == "STOCK":
        pl.stocks = [h for h in pl.stocks if h.symbol != p["symbol"]]
    else:
        _remove_asset(pl, p["asset_id"])     # 对应抵押负债一并注销（随资产行删除）


def _a_bankruptcy_resolved(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    if F.monthly_cashflow(pl) >= 0:
        pl.in_bankruptcy = False
        pl.skip_turns = 3
        return
    # 卖光资产仍为负：注销 购车/信用卡/额外负债 各50% 及对应支出的50%（P.5）
    pl.liabilities.car_loan //= 2
    pl.liabilities.credit_card //= 2
    pl.liabilities.extra //= 2
    pl.car_loan_payment //= 2
    pl.credit_card_payment //= 2
    pl.extra_expenses //= 2
    for l in pl.extra_liabilities:
        l.amount //= 2
        l.monthly //= 2
    if F.monthly_cashflow(pl) >= 0:
        pl.in_bankruptcy = False
        pl.skip_turns = 3
        return
    # 仍为负：出局，资产由银行回收
    pl.in_bankruptcy = False
    pl.phase = Phase.OUT
    pl.real_estates = []
    pl.businesses = []
    pl.stocks = []
    pl.cash = 0
    alive = [q for q in s.players.values() if q.phase != Phase.OUT]
    if len(alive) == 1:
        s.status = RoomStatus.FINISHED
        s.winner_id = alive[0].id


def _a_entered_fasttrack(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.phase = Phase.FAST_TRACK
    pl.cash = 0                                  # 现金交回银行（按说明书）
    pl.fasttrack.initial_income = p["initial_income"]
    pl.fasttrack.current_income = p["initial_income"]


def _a_ft_payday(s: RoomState, p) -> None:
    s.players[p["player_id"]].cash += p["amount"]


def _check_income_victory(s: RoomState, pl: PlayerState) -> None:
    ft = pl.fasttrack
    if ft.current_income - ft.initial_income >= 50_000:
        s.status = RoomStatus.FINISHED
        s.winner_id = pl.id


def _a_ft_business_bought(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["down_payment"]
    if p["success"]:
        s.ft_sold_squares.append(p["square_id"])   # 独占；掷骰格成功前保持开放
        if p.get("lump_sum"):
            pl.cash += p["lump_sum"]               # 一次性现金收益，不计入胜利进度
        if p.get("cashflow"):
            pl.fasttrack.businesses.append(FastTrackHolding(
                square_id=p["square_id"], name=p["name"], cashflow=p["cashflow"]))
            pl.fasttrack.current_income += p["cashflow"]
            _check_income_victory(s, pl)


def _a_ft_dream_bought(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["price"]
    s.status = RoomStatus.FINISHED
    s.winner_id = pl.id


def _a_ft_dream_doubled(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["price_paid"]
    s.dream_price_bumps[p["square_id"]] = s.dream_price_bumps.get(p["square_id"], 0) + 1


def _a_ft_charity_donated(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["amount"]
    pl.fasttrack.charity_forever = True


def _a_ft_cash_hit(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    if p["kind"] == "DIVORCE":
        pl.cash = 0
    else:
        pl.cash -= p["amount"]


def _a_host_adjusted(s: RoomState, p) -> None:
    s.players[p["player_id"]].cash += p["delta"]


_APPLIERS = {
    "PLAYER_JOINED": _a_player_joined,
    "PROFESSION_SELECTED": _a_profession_selected,
    "DREAM_SELECTED": _a_dream_selected,
    "TURN_ORDER_SET": _a_turn_order_set,
    "GAME_STARTED": _a_game_started,
    "TURN_ENDED": _a_turn_ended,
    "PAYDAY": _a_payday,
    "CARD_DRAWN": _a_card_drawn,
    "CARD_RESOLVED": _a_card_resolved,
    "CARD_PASSED": _a_card_passed,
    "ASSET_BOUGHT": _a_asset_bought,
    "RESELL_OFFERED": _a_resell_offered,
    "RESELL_CONFIRMED": _a_resell_confirmed,
    "RESELL_REJECTED": _a_resell_rejected,
    "STOCK_BOUGHT": _a_stock_bought,
    "STOCK_SOLD": _a_stock_sold,
    "SHARES_ADJUSTED": _a_shares_adjusted,
    "LOSS_PAID": _a_loss_paid,
    "EXPENSE_EVENT_PAID": _a_expense_event_paid,
    "DOODAD_PAID": _a_doodad_paid,
    "INSTALLMENT_ADDED": _a_installment_added,
    "MARKET_PROMPTED": _a_market_prompted,
    "MARKET_SOLD": _a_market_sold,
    "MARKET_DECLINED": _a_market_declined,
    "ASSETS_SURRENDERED": _a_assets_surrendered,
    "LOAN_TAKEN": _a_loan_taken,
    "LOAN_REPAID": _a_loan_repaid,
    "DEBT_PAID_OFF": _a_debt_paid_off,
    "CHILD_ADDED": _a_child_added,
    "CHILD_NOOP": _a_child_noop,
    "CHARITY_DONATED": _a_charity_donated,
    "UNEMPLOYMENT_HIT": _a_unemployment_hit,
    "TRANSFER_REQUESTED": _a_transfer_requested,
    "TRANSFER_COMPLETED": _a_transfer_completed,
    "TRANSFER_REJECTED": _a_transfer_rejected,
    "BANKRUPTCY_STARTED": _a_bankruptcy_started,
    "BANKRUPTCY_ASSET_SOLD": _a_bankruptcy_asset_sold,
    "BANKRUPTCY_RESOLVED": _a_bankruptcy_resolved,
    "ENTERED_FASTTRACK": _a_entered_fasttrack,
    "FT_PAYDAY": _a_ft_payday,
    "FT_BUSINESS_BOUGHT": _a_ft_business_bought,
    "FT_DREAM_BOUGHT": _a_ft_dream_bought,
    "FT_DREAM_DOUBLED": _a_ft_dream_doubled,
    "FT_CHARITY_DONATED": _a_ft_charity_donated,
    "FT_CASH_HIT": _a_ft_cash_hit,
    "HOST_ADJUSTED": _a_host_adjusted,
}


def replay(events: list[Event], initial: RoomState | None = None) -> RoomState:
    """state = reduce(初始, 事件流)。跳过被撤销的事件由存储层负责过滤。"""
    state = initial or RoomState()
    for ev in events:
        state = apply(state, ev)
    return state
