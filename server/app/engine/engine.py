"""规则引擎核心（design/02 全文对照实现）。

两个纯函数：
- decide(state, actor_id, action_type, payload, lib) -> list[Event]
  校验行动合法性，产出携带全部结算数值的事件（回放不依赖卡库）。
- apply(state, event) -> RoomState
  唯一的状态变更途径；state = reduce(initial, events)。

Event = {"type": str, "payload": dict}。金额一律非负整数美元。
"""
from __future__ import annotations

import random
import uuid
from typing import Any

from ..data_loader import CardLibrary
from . import formulas as F
from .errors import EngineError
from .models import (
    ActiveCard, ExtraLiability, FastTrackHolding, GameMode, InstallmentReceivable,
    Landing, OwnedBusiness, Phase, PlayerState, Prompt, RealEstate, RoomState,
    RoomStatus, StockHolding,
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


def _require_square_free(state: RoomState) -> None:
    # 实体规则每回合掷骰只停一个格（design/02 §5）
    if state.turn_square_used:
        raise EngineError("SQUARE_USED", "本回合已声明过停留格事件；如录错请房主在日志中撤销")


def _require_payday_free(state: RoomState, hint: str) -> None:
    if state.turn_payday_used:
        raise EngineError("PAYDAY_DONE", f"本回合已结算过（经过多次请用次数 {hint} 一并结算）")


def is_online(state: RoomState) -> bool:
    """纯线上模式？两种模式在引擎里只以「前置校验」的形态分叉（change D5）。"""
    return state.mode is GameMode.ONLINE


def _reject_online(state: RoomState, code: str, message: str) -> None:
    """纯线上模式下关掉「由玩家声明线下发生了什么」的入口（change D10）。

    前端隐藏挡不住直接发请求，公平性只能焊在服务端。
    """
    if is_online(state):
        raise EngineError(code, message)


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

def _d_set_room_mode(state: RoomState, actor_id, p, lib) -> list[Event]:
    """建房时写下对局模式，作为事件流的第一条（change D1）。

    模式必须进事件流：_revert 从空 RoomState() 重放，只存 DB 的话第一次撤销
    就会把纯线上房间打回线下房间。房间一旦有人（含房主）就不再受理，
    这也就是「建好之后谁都改不了」这条规则的落点。
    """
    if state.players or state.status != RoomStatus.LOBBY:
        raise EngineError("MODE_LOCKED", "对局模式在建房时选定，不可更改")
    mode = str(p.get("mode") or GameMode.OFFLINE_ASSIST.value)
    if mode not in tuple(GameMode):
        raise EngineError("BAD_MODE", f"未知对局模式: {mode}")
    return [_ev("ROOM_MODE_SET", mode=mode)]


def _d_join(state: RoomState, actor_id, p, lib) -> list[Event]:
    if state.status not in (RoomStatus.LOBBY, RoomStatus.SETUP):
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
    if is_online(state):
        # 说明书 P.2 步骤 4 写的是「抽」一张职业卡，不是挑（change D14）：
        # 12 张卡工资相差 8 倍，让人自选等于开局就把平衡拆了。
        # 时机与位置不变（还在准备页、还由玩家自己触发），只把「挑」换成服务端随机发。
        if player.profession_id:
            raise EngineError("PROFESSION_DRAWN", "职业卡已经抽过了，不能重抽")
        card = _draw_profession(state, player, lib)
        return [_ev("PROFESSION_SELECTED", player_id=player.id,
                    profession_id=card.id, title=card.title, data=card.data)]
    card = lib.get(p["professionId"])
    if card.deck != "PROFESSION":
        raise EngineError("BAD_CARD", "所选卡不是职业卡")
    for other in state.players.values():
        if other.id != player.id and other.profession_id == card.id:
            raise EngineError("PROFESSION_TAKEN", f"该职业已被 {other.nickname} 选择")
    return [_ev("PROFESSION_SELECTED", player_id=player.id,
                profession_id=card.id, title=card.title, data=card.data)]


def _draw_profession(state: RoomState, player: PlayerState, lib: CardLibrary):
    """从尚未被占用的职业里随机抽一张（change D14）。

    随机源用 decide 阶段的 RNG（同 _dice_gamble_event）：摇一次、结果写进事件，
    重放不再摇。职业卡不走牌堆模型——一人一张、不弃牌、不洗回，建一副堆只是
    把简单事情复杂化。按 id 排序只为让种子固定时的抽取可复现。
    """
    taken = {pl.profession_id for pl in state.players.values() if pl.profession_id}
    pool = sorted((c for c in lib.by_deck("PROFESSION") if c.id not in taken),
                  key=lambda c: c.id)
    if not pool:
        raise EngineError("NO_PROFESSION_LEFT", "职业卡已发完")
    return _dice_rng.choice(pool)


def _d_select_dream(state, actor_id, p, lib) -> list[Event]:
    if state.status not in (RoomStatus.LOBBY, RoomStatus.SETUP):
        raise EngineError("GAME_STARTED", "对局已开始，不能换梦想")
    player = _get_player(state, actor_id)
    dream = lib.get_ft_dream(p["dreamId"])
    for other in state.players.values():
        if other.id != player.id and other.dream_id == dream.id:
            raise EngineError("DREAM_TAKEN", f"该梦想已被 {other.nickname} 选择")
    return [_ev("DREAM_SELECTED", player_id=player.id, dream_id=dream.id, name=dream.name)]


def _d_set_turn_order(state, actor_id, p, lib) -> list[Event]:
    _reject_online(state, "ONLINE_AUTO_ORDER", "纯线上模式的回合顺序由服务端开局掷骰排定")
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
    online = is_online(state)
    if not online and not state.turn_order:
        raise EngineError("NO_ORDER", "请先线下掷骰并排定回合顺序")
    missing = [pl.nickname for pl in state.players.values() if not pl.profession_id]
    if missing:
        raise EngineError("NO_PROFESSION", f"尚未选职业：{'、'.join(missing)}")
    no_dream = [pl.nickname for pl in state.players.values() if not pl.dream_id]
    if no_dream:
        raise EngineError("NO_DREAM", f"尚未选择梦想：{'、'.join(no_dream)}")
    events: list[Event] = []
    if online:
        # 说明书 P.2「开始游戏」1：每人掷骰、点数最大者先行。纯线上的骰子在服务端，
        # 所以顺序也归服务端排（change D15）——房主手排本身是一次「声明线下发生了什么」。
        order, rolls = _roll_turn_order(state)
        if not order:
            raise EngineError("NO_ORDER", "无法排定回合顺序")
        events.append(_ev("TURN_ORDER_SET", order=order, rolls=rolls))
        events.append(_ev("DECKS_SHUFFLED",
                          orders={d: _shuffled(ids)
                                  for d, ids in _build_decks(lib).items()}))
    # 发钱：现金 = 月现金流 + 储蓄；随后储蓄清零（P.2）
    grants = {}
    for pid, pl in state.players.items():
        grants[pid] = F.monthly_cashflow(pl) + pl.savings
    events.append(_ev("GAME_STARTED", grants=grants))
    return events


def _roll_turn_order(state: RoomState) -> tuple[list[str], list[dict[str, int]]]:
    """替全员各摇一次骰，点数降序排；平局者之间重摇直到分出先后（change D15）。

    返回 (顺序, 每一轮的点数)。点数随 TURN_ORDER_SET 一并入事件流，纯作审计与呈现，
    `_a_turn_order_set` 只读 order，一行不用改。
    """
    rounds: list[dict[str, int]] = []

    def resolve(group: list[str], depth: int) -> list[str]:
        if len(group) == 1:
            return list(group)
        if depth >= 20:
            # 连摇 20 轮还全平只存在于理论上；兜底按座位定，免得递归下不去
            return sorted(group, key=lambda pid: state.players[pid].seat)
        roll = {pid: _dice_rng.randint(1, 6) for pid in group}
        rounds.append(roll)
        buckets: dict[int, list[str]] = {}
        for pid, v in roll.items():
            buckets.setdefault(v, []).append(pid)
        out: list[str] = []
        for v in sorted(buckets, reverse=True):
            out.extend(resolve(buckets[v], depth + 1))
        return out

    return resolve(list(state.players), 0), rounds


# ---------- 回合（design/02 §5） ----------

def _d_end_turn(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    ac = state.active_card
    if ac and not ac.resolved and ac.subtype in (
            "EXPENSE_EVENT", "CASH", "CREDIT_OPTION", "INSTALLMENT", "STOCK_EVENT"):
        raise EngineError("CARD_UNRESOLVED", "本回合的强制卡牌尚未结算，不能结束回合")
    lg = state.landing
    if is_online(state) and lg is not None and not lg.resolved \
            and lg.type in _MUST_RESOLVE_LANDINGS:
        # 闸门只对「必须做」的格子落下（change D5）：捐不捐、买不买本来就是玩家的选择，
        # 不做也是一种做法，不该逼人先点一次「不捐」才准结束回合。
        raise EngineError(
            "LANDING_UNRESOLVED",
            "停在机会格必须抽一张牌" if lg.type == "OPPORTUNITY"
            else "失业这一格必须支付一次总支出（现金不够可先向银行贷款）")
    return [_ev("TURN_ENDED", player_id=player.id)]


def _d_payday(state, actor_id, p, lib) -> list[Event]:
    _reject_online(state, "ONLINE_AUTO_PAYDAY", "纯线上模式的银行结算日在走格时自动结算")
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    if player.phase != Phase.RAT_RACE:
        raise EngineError("WRONG_PHASE", "快车道请用现金流量日收款")
    _require_payday_free(state, "1–3")
    times = int(p.get("times", 1))
    if times < 1 or times > 3:
        raise EngineError("BAD_TIMES", "结算次数须为 1–3")
    return payday_events(player, times)


def payday_events(player: PlayerState, times: int = 1) -> list[Event]:
    """一次（或连续几次）银行结算日的账（design/02 §5）。

    动作层的单回合锁 `_require_payday_free` 留在 `_d_payday` 里——纯线上模式下
    一次移动可能经过两个结算格，那条锁不适用，但算钱这一份两种模式共用（change D4），
    说明书示例数值回归因此自动覆盖两种模式。
    """
    cf = F.monthly_cashflow(player)
    # P.5：月现金流为负且手头现金不足以支付到期款项 —— 这是破产「判定」，不是二选一，
    # 也不给「先去贷款」的出口，否则玩家可以靠无限贷款把负现金流永远拖下去。
    # 一并结算多个月时逐月判：付得起的月份照付，第一个付不出的月份触发破产。
    payable = 0
    while payable < times and player.cash + cf * (payable + 1) >= 0:
        payable += 1
    if payable == times:
        return [_ev("PAYDAY", player_id=player.id, cashflow=cf, times=times)]
    evs: list[Event] = []
    if payable:
        evs.append(_ev("PAYDAY", player_id=player.id, cashflow=cf, times=payable))
    evs.append(_ev("PAYDAY_UNPAYABLE", player_id=player.id, cashflow=cf,
                   month=payable + 1, of_times=times,
                   shortfall=-(player.cash + cf * (payable + 1))))
    evs.append(_ev("BANKRUPTCY_STARTED", player_id=player.id))
    return evs


# ---------- 掷骰与移动（纯线上模式，change D4/D5） ----------

_SETTLEMENT_TYPES = frozenset({"PAYDAY", "FT_PAYDAY"})

# 停在这些格上还欠玩家一个决定；其余格子落点即结算完毕
_CHOICE_LANDINGS = frozenset({
    "OPPORTUNITY", "CHARITY", "FT_BUSINESS", "FT_DREAM", "FT_CHARITY"})

# 未处理时不许结束回合的格子（change D5 那张表）：说明书规定停在机会格就要抽一张，
# 不是可选项；失业是必付的，付不出得先向银行贷款。慈善与快车道绿粉格本就可做可不做。
_MUST_RESOLVE_LANDINGS = frozenset({"OPPORTUNITY", "UNEMPLOYMENT"})

_FT_SPECIAL_TYPES = {
    "ft-s-charity": "FT_CHARITY",
    "ft-s-cashflow-day": "FT_PAYDAY",
    "ft-s-tax-audit": "FT_TAX_AUDIT",
    "ft-s-divorce": "FT_DIVORCE",
    "ft-s-lawsuit": "FT_LAWSUIT",
}


def _ft_square_type(ref: str) -> str:
    """快车道格子的类型由 ref 前缀给出（change D6：能推出的不存）。"""
    if ref.startswith("ft-b-"):
        return "FT_BUSINESS"
    if ref.startswith("ft-d-"):
        return "FT_DREAM"
    try:
        return _FT_SPECIAL_TYPES[ref]
    except KeyError:
        raise EngineError("BAD_SQUARE", f"未知快车道格: {ref}") from None


def _square_at(player: PlayerState, index: int, lib: CardLibrary) -> tuple[str, str, str]:
    """(track, type, ref_id)——取哪条轨由 phase 决定，不另存一份（change D3）。"""
    if player.phase is Phase.FAST_TRACK:
        ref = lib.ft_square_ref(index)
        return "FAST_TRACK", _ft_square_type(ref), ref
    sq = lib.rr_square(index)
    return "RAT_RACE", sq.type, sq.id


def _track_of(player: PlayerState) -> str:
    return "FAST_TRACK" if player.phase is Phase.FAST_TRACK else "RAT_RACE"


def _position_of(player: PlayerState) -> int:
    return player.ft_position if player.phase is Phase.FAST_TRACK else player.rr_position


def dice_limits(player: PlayerState) -> tuple[int, int]:
    """(默认粒数, 本赛道允许的最大粒数)。

    两条赛道的慈善不是同一种权利：老鼠赛跑捐款后 3 轮内可掷 1–2 粒（P.4），
    快车道捐款后**永久**可掷 1–3 粒（P.6）。所以校验必须读 phase，
    不能图省事写成一个 `1 <= n <= 3`。
    """
    if player.phase is Phase.FAST_TRACK:
        return 2, (3 if player.fasttrack.charity_forever else 2)
    return 1, (2 if player.charity_turns > 0 else 1)


def _settlement_events(state: RoomState, player_id: str, track: str) -> list[Event]:
    """经过（或停在）一个结算格的账。两条赛道各走各的既有事件。"""
    player = state.player(player_id)
    if track == "FAST_TRACK":
        return [_ev("FT_PAYDAY", player_id=player_id,
                    amount=player.fasttrack.current_income, times=1)]
    return payday_events(player, 1)


def _landing_events(state: RoomState, player_id: str, ltype: str, ref: str,
                    lib: CardLibrary) -> list[Event]:
    """落点自动派发（change D5）：复用既有动作的事件产出，不另写一套效果。

    选择格（机会/慈善/绿格/粉格）返回空——那里等的是玩家的决定。
    """
    player = state.player(player_id)
    if ltype in _SETTLEMENT_TYPES:
        return [_ev("LANDING_RESOLVED", note="")]        # 结算已在走格时完成
    if ltype in ("MARKET", "DOODAD"):
        return _draw_from_deck(state, player, ltype, lib)
    if ltype == "CHILD":
        return _d_add_child(state, player_id, {}, lib)
    if ltype == "UNEMPLOYMENT":
        try:
            return _d_unemployment(state, player_id, {}, lib)
        except EngineError as exc:
            if exc.code != "NEED_CASH":
                raise
            # 付不出：落点保持未决，玩家先向银行贷款再自己付。掷骰已成事实，
            # 不能因为现金不够就把整次移动回滚掉。
            return []
    if ltype in ("FT_TAX_AUDIT", "FT_DIVORCE", "FT_LAWSUIT"):
        return _HANDLERS[ltype](state, player_id, {}, lib)
    if ltype == "FT_BUSINESS" and ref in state.ft_sold_squares:
        return [_ev("LANDING_RESOLVED", note="该企业已被其他玩家买断，本格无事发生")]
    return []


def _d_roll_dice(state: RoomState, actor_id, p, lib) -> list[Event]:
    """一次掷骰产出一整串事件（change D4）：

        DICE_ROLLED → （逐格前进，每经过一个结算格）PAYDAY / FT_PAYDAY
                    → PLAYER_MOVED → （落点是自动格时）落点自身的事件

    事件粒度这么切，撤销一次掷骰就是撤掉这一整串（rooms.py 的 `_dice_batch`）。
    """
    if not is_online(state):
        raise EngineError("OFFLINE_DICE", "线下辅助模式请掷桌上的实体骰子")
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    if player.phase not in (Phase.RAT_RACE, Phase.FAST_TRACK):
        raise EngineError("WRONG_PHASE", "当前阶段不能掷骰")
    if player.skip_turns > 0:
        raise EngineError("SKIPPING", "停赛中，本回合不能掷骰")
    if state.turn_dice_used:
        raise EngineError("DICE_USED", "本回合已经掷过骰了")
    default_n, max_n = dice_limits(player)
    raw = p.get("diceCount")
    count = default_n if raw is None else int(raw)   # 缺省才用默认值；0 是非法值不是缺省
    if count < 1 or count > max_n:
        raise EngineError("BAD_DICE_COUNT", f"本回合可掷 1–{max_n} 粒骰")
    # 服务端摇、点数写进事件流：客户端自带的点数一律忽略（同 _dice_gamble_event）
    rolls = [_dice_rng.randint(1, 6) for _ in range(count)]
    total = sum(rolls)

    events: list[Event] = []
    working = state

    def emit(evs: list[Event]) -> None:
        nonlocal working
        for ev in evs:
            events.append(ev)
            working = apply(working, ev)

    emit([_ev("DICE_ROLLED", player_id=player.id, rolls=rolls,
              dice_count=count, total=total)])

    track = _track_of(player)
    size = lib.ft_size if track == "FAST_TRACK" else lib.rr_size
    start = _position_of(player)
    pos, path, bankrupt = start, [], False
    for _ in range(total):
        pos = pos % size + 1          # 0（起点/入口标记）走 1 步即第 1 格
        path.append(pos)
        _, stype, _ref = _square_at(working.player(player.id), pos, lib)
        if stype in _SETTLEMENT_TYPES:
            emit(_settlement_events(working, player.id, track))
            if working.player(player.id).in_bankruptcy:
                # 付不出到期款项：移动就地终止，棋子停在这个结算格。
                # 人已经进清算了，再走一格触发一张卡毫无意义。
                bankrupt = True
                break

    to = path[-1] if path else start
    _, ltype, ref = _square_at(working.player(player.id), to, lib) if path \
        else (track, "", "")
    emit([{"type": "PLAYER_MOVED",
           "payload": {"player_id": player.id, "track": track, "from": start,
                       "to": to, "path": path,
                       "landing": {"track": track, "index": to,
                                   "type": ltype, "ref_id": ref}}}])
    if bankrupt:
        emit([_ev("LANDING_RESOLVED", note="付不出到期款项，进入破产清算")])
    elif path:
        emit(_landing_events(working, player.id, ltype, ref, lib))
    return events


def _require_landing(state: RoomState, *types: str, ref_id: str | None = None) -> None:
    """纯线上模式下：你确实停在这一格，且这一格还欠你一个决定（change D5）。

    线下模式跳过——那边玩家本来就是自己声明停在哪一格的。
    """
    if not is_online(state):
        return
    lg = state.landing
    if lg is None or lg.resolved or lg.type not in types:
        raise EngineError("WRONG_SQUARE", "你没有停在这一格，或这一格已经处理过了")
    if ref_id is not None and lg.ref_id != ref_id:
        raise EngineError("WRONG_SQUARE", "你停的不是这一格")


def _d_choose_deal_size(state: RoomState, actor_id, p, lib) -> list[Event]:
    """停在机会格：先选小生意还是大买卖，再从对应牌堆发牌（change D5）。"""
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    _require_landing(state, "OPPORTUNITY")
    if state.active_card and not state.active_card.resolved:
        raise EngineError("CARD_ACTIVE", "上一张卡尚未处理完")
    deck = {"SMALL": "SMALL_DEAL", "BIG": "BIG_DEAL"}.get(str(p.get("size", "")).upper())
    if deck is None:
        raise EngineError("BAD_DEAL_SIZE", "只能选「小生意」或「大买卖」")
    return _draw_from_deck(state, player, deck, lib)


# ---------- 抽卡与卡牌效果（design/02 §6） ----------

_OPPORTUNITY_DECKS = ("SMALL_DEAL", "BIG_DEAL")


def _d_draw_card(state, actor_id, p, lib) -> list[Event]:
    if is_online(state) and p.get("cardId"):
        # 牌只能从服务端牌堆按顺序发（change D2/D10）：客户端指定卡 id 就是作弊入口
        raise EngineError("ONLINE_DECK_ONLY", "纯线上模式的牌由服务端发放，不能指定卡牌")
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    if player.phase != Phase.RAT_RACE:
        raise EngineError("WRONG_PHASE", "快车道阶段不抽内圈卡")
    _require_square_free(state)
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


# 纯线上模式的四副牌（职业卡不在此列：一人一张、不弃牌、不洗回，见 D14）
DECK_NAMES = ("SMALL_DEAL", "BIG_DEAL", "MARKET", "DOODAD")


def _build_decks(lib: CardLibrary) -> dict[str, list[str]]:
    """按卡库实际张数建四副堆（change D2）。

    重复卡各自作为独立一张入堆——实体牌堆里本来就有 9 组共 20 张完全相同的卡，
    张数直接决定抽牌概率，按 key 去重就把牌堆改了。
    """
    return {deck: [c.id for c in lib.by_deck(deck)] for deck in DECK_NAMES}


def _shuffled(card_ids: list[str]) -> list[str]:
    """洗牌在 decide 阶段摇出，整串写进事件 payload：事件里写结果不写过程。"""
    out = list(card_ids)
    _dice_rng.shuffle(out)
    return out


def _draw_from_deck(state: RoomState, player: PlayerState, deck: str,
                    lib: CardLibrary) -> list[Event]:
    """从牌堆顶发一张（change D2）。牌堆取空先洗回弃牌堆。

    落点派发与 CHOOSE_DEAL_SIZE 共用这一份；线下模式的 _d_draw_card 走原路径不变。
    """
    if deck not in state.decks:
        raise EngineError("NO_DECK", f"牌堆不存在: {deck}")
    events: list[Event] = []
    pile = state.decks[deck]
    if not pile:
        discard = state.discards.get(deck) or []
        if not discard:
            raise EngineError("DECK_EMPTY", f"{deck} 的牌堆与弃牌堆同时为空")
        pile = _shuffled(discard)
        events.append(_ev("DECK_RESHUFFLED", deck=deck, order=pile))
    card = lib.get(pile[0])
    events.append(_ev("CARD_DRAWN", player_id=player.id, card_id=card.id,
                      deck=card.deck, subtype=card.subtype, title=card.title))
    if card.deck == "MARKET":
        events += _market_events(state, player, card)
    return events


_SELL_OFFER_SUBTYPES = ("BUYER_OFFER", "MULTIPLE_OFFER", "PREMIUM_OFFER", "INSTALLMENT_SALE")


def _asset_matches(asset, d: dict) -> bool:
    """求购卡是否指向该资产（design/06 §6.2、§6.5）。

    targetAssetType 与 targetBusinessKind 二选一必填，两者都给时须同时满足
    （mk-025 只收「自建企业」名下的小型机械公司）；只给 targetBusinessKind 时
    按企业类型跨 assetType 匹配（mk-035 同时命中洗车店与自动化企业）。
    """
    target_type = d.get("targetAssetType")
    target_kind = d.get("targetBusinessKind")
    if target_type is not None and asset.asset_type != target_type:
        return False
    if target_kind is not None and asset.business_kind != target_kind:
        return False
    if target_type is None and target_kind is None:
        return False
    min_units = d.get("minUnits")
    if min_units is not None and (asset.units or 1) < min_units:
        return False
    return _asset_condition_met(asset, d.get("assetCondition"))


def _offer_price(subtype: str, d: dict, asset) -> int:
    """求购卡对该资产的成交价。

    ⚠️ 三种计价基准算错最大差 13 倍（design/07 §2.4）：
    同一张 8 室公寓，PER_UNIT $25,000 只值 2.5 万，PER_ROOM $40,000 值 32 万。
    """
    if subtype == "MULTIPLE_OFFER":
        return int(asset.cost * d["multiple"])
    if subtype == "PREMIUM_OFFER":
        return asset.cost + d["premiumOverCost"]
    if subtype == "INSTALLMENT_SALE":
        return d["totalPrice"]
    basis = d["priceBasis"]
    if basis == "PER_UNIT":
        return d["price"] * (asset.units or 1)      # 无 units = 整个资产算一份
    if basis == "PER_ROOM":
        return d["price"] * (asset.rooms or 1)
    if basis == "PER_PIECE":
        return d["price"] * (asset.quantity or 1)
    raise EngineError("BAD_PRICE_BASIS", f"未知计价基准: {basis}")


def _market_events(state: RoomState, drawer: PlayerState, card) -> list[Event]:
    """市场风云：找出受影响玩家并推送要约（design/02 §6.3）。

    ⚠️ 只推要约、绝不自动成交，也不得因「卖了会亏」而过滤或隐藏要约——
    玩家可能为套现渡过破产危机而主动贱卖（design/06 §6.5）。
    """
    d = card.data
    events: list[Event] = []

    if card.subtype in _SELL_OFFER_SUBTYPES:
        for pl in state.players.values():
            if pl.phase != Phase.RAT_RACE:
                continue
            frozen = pl.frozen_asset_ids
            for asset in pl.owned_assets:
                if asset.id in frozen or not _asset_matches(asset, d):
                    continue                          # 冻结房不在市场上，无法被求购
                events.append(_ev(
                    "MARKET_PROMPTED", prompt_id=_new_id(), player_id=pl.id,
                    asset_id=asset.id, asset_name=asset.name,
                    price=_offer_price(card.subtype, d, asset),
                    mortgage=asset.mortgage, card_id=card.id,
                    subtype=card.subtype,
                    **(_installment_terms(d) if card.subtype == "INSTALLMENT_SALE" else {})))
        if not events:
            events.append(_ev("CARD_RESOLVED", card_id=card.id, note="无人持有相关资产"))

    elif card.subtype == "CASHFLOW_MODIFIER":
        # 不转移资产，只改所有符合条件的持有者名下资产条目的月现金流
        target_ids = {}
        for pl in state.players.values():
            if pl.phase != Phase.RAT_RACE:
                continue
            if d["appliesTo"] == "DRAWER_ONLY" and pl.id != drawer.id:
                continue
            frozen = pl.frozen_asset_ids
            ids = [a.id for a in pl.owned_assets
                   if a.id not in frozen and _asset_matches(a, d)]
            if ids:
                target_ids[pl.id] = ids
        if target_ids:
            events.append(_ev("CASHFLOW_MODIFIED", card_id=card.id,
                              delta=d["cashflowDelta"], targets=target_ids))
        events.append(_ev("CARD_RESOLVED", card_id=card.id,
                          **({} if target_ids else {"note": "无人持有相关资产"})))

    elif card.subtype == "ECONOMY_EVENT":
        if d.get("kind") == "FORCED_SURRENDER":
            target = d.get("targetAssetType")
            for pl in state.players.values():
                if pl.phase != Phase.RAT_RACE:
                    continue
                frozen = pl.frozen_asset_ids
                ids = [a.id for a in pl.owned_assets
                       if a.id not in frozen and a.asset_type == target]
                if ids:                               # 冻结房免疫强制没收（Q2 裁决）
                    events.append(_ev("ASSETS_SURRENDERED", player_id=pl.id,
                                      asset_ids=ids, card_id=card.id))
        events.append(_ev("CARD_RESOLVED", card_id=card.id))
    return events


def _installment_terms(d: dict) -> dict:
    """分期收款的条款，随要约一并下发，成交事件据此挂账。"""
    return {"monthly_delta": d["monthlyCashflowDelta"],
            "duration_months": d["durationMonths"]}


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

    if ac.subtype in ("REALESTATE", "BUSINESS", "COLLECTIBLE"):
        if decision == "pass":
            return [_ev("CARD_PASSED", player_id=player.id, card_id=card.id)]
        if decision == "buy":
            _require_cash(player, d["downPayment"])
            return [_asset_bought_event(player.id, card)]
        if decision == "resell":
            return _resell_offer_events(state, player, card, p)
        raise EngineError("BAD_DECISION", "该卡只能 买 / 放弃 / 转卖")

    if ac.subtype == "DICE_GAMBLE":
        if decision == "pass":
            return [_ev("CARD_PASSED", player_id=player.id, card_id=card.id)]
        if decision == "buy":
            _require_cash(player, d["downPayment"])
            return [_dice_gamble_event(player.id, card)]
        if decision == "resell":
            return _resell_offer_events(state, player, card, p)
        raise EngineError("BAD_DECISION", "该卡只能 接受 / 放弃 / 转卖")

    if ac.subtype == "STOCK_OFFER":
        if decision == "pass":
            return [_ev("CARD_PASSED", player_id=player.id, card_id=card.id)]
        raise EngineError("BAD_DECISION", "股票卡用 买入/卖出 操作，或放弃")

    if ac.subtype == "STOCK_EVENT":
        num, den = (int(x) for x in d["ratio"].split(":"))
        return [_ev("SHARES_ADJUSTED", card_id=card.id, symbol=d["symbol"],
                    ratio_num=num, ratio_den=den)]

    if ac.subtype == "EXPENSE_EVENT":
        amount, note, units = _expense_due(player, d)
        _require_cash(player, amount)
        return [_ev("EXPENSE_EVENT_PAID", player_id=player.id, card_id=card.id,
                    amount=amount, units=units, title=card.title,
                    **({"note": note} if amount == 0 and note else {}))]

    if ac.subtype == "CASH":
        amount, note, _ = _expense_due(player, d)
        _require_cash(player, amount)
        return [_ev("DOODAD_PAID", player_id=player.id, card_id=card.id,
                    amount=amount, method="cash", title=card.title,
                    **({"note": note} if amount == 0 and note else {}))]

    if ac.subtype == "CREDIT_OPTION":
        if decision == "credit":
            return [_ev("DOODAD_PAID", player_id=player.id, card_id=card.id,
                        amount=0, method="credit", credit_amount=d["amount"],
                        credit_monthly=d["creditMonthly"], title=card.title)]
        _require_cash(player, d["amount"])
        return [_ev("DOODAD_PAID", player_id=player.id, card_id=card.id,
                    amount=d["amount"], method="cash", title=card.title)]

    if ac.subtype == "INSTALLMENT":
        _require_cash(player, d["downPayment"])
        return [_ev("INSTALLMENT_ADDED", player_id=player.id, card_id=card.id,
                    down_payment=d["downPayment"], liability=d["liability"],
                    liability_name=d["liabilityName"], monthly=d["monthly"],
                    liability_id=_new_id(), title=card.title)]

    raise EngineError("BAD_CARD", f"未支持的卡类型: {ac.subtype}")


def _payer_condition_met(p: PlayerState, condition: str | None) -> bool:
    """判定「玩家」是否够格支付（v3 的 payerCondition，区别于判定资产的 assetCondition）。"""
    if not condition:
        return True
    if condition == "hasChildren":
        return p.child_count > 0
    if condition == "hasRentalProperty":
        return len(p.real_estates) > 0
    if condition == "hasRealEstate":
        return len(p.real_estates) > 0
    raise EngineError("BAD_CONDITION", f"未知玩家条件: {condition}")


def _asset_condition_met(asset, condition: str | None) -> bool:
    """判定「资产」是否够格被求购（v3 的 assetCondition，仅 mk-032 求购旅馆用）。"""
    if not condition:
        return True
    if condition == "cashflowPositive":
        return asset.cashflow > 0
    raise EngineError("BAD_CONDITION", f"未知资产条件: {condition}")


_CONDITION_NOTES = {
    # payerCondition -> (需付说明, 豁免说明)
    "hasChildren": ("有孩子才需支付", "无孩子，无需支付"),
    "hasRentalProperty": ("有出租房产才需支付", "无出租房产，无需支付"),
    "hasRealEstate": ("有房地产才需支付", "无房地产，无需支付"),
}


def _matching_units(p: PlayerState, d: dict) -> int:
    """按 targetAssetType（+ 可选 targetRooms）数出玩家名下的相关房产套数。"""
    target = d.get("targetAssetType")
    rooms = d.get("targetRooms")
    return sum(1 for a in p.real_estates
               if a.asset_type == target and (rooms is None or a.rooms == rooms))


def _expense_due(p: PlayerState, d: dict) -> tuple[int, str, int]:
    """强制支出卡（EXPENSE_EVENT / CASH）的应付金额、中文说明、相关房产数。

    决策与预览共用，避免两处逻辑漂移。三种计量方式互斥：
    - amountPerUnit：按相关房产套数计（chargeOnce=true 时封顶一套，bd-003 卡面明示）
    - amountPerChild：按孩子数计（dd-021「为每个小孩花费 $50」）
    - amount：固定金额
    """
    cond = d.get("payerCondition")
    if not _payer_condition_met(p, cond):
        _, waived = _CONDITION_NOTES.get(
            cond, ("", f"未满足条件（{cond}），无需支付"))
        return 0, waived, 0
    require_note = _CONDITION_NOTES.get(cond, ("", ""))[0] if cond else ""

    if "amountPerUnit" in d:
        units = _matching_units(p, d)
        if units == 0:
            return 0, "无相关房产，无需支付", 0
        billed = 1 if d.get("chargeOnce") else units
        per = d["amountPerUnit"]
        note = (f"持有 {units} 套，卡面注明只付一套 × ${per:,}" if d.get("chargeOnce")
                else f"相关房产 {units} 处 × ${per:,}")
        return billed * per, note, units

    if "amountPerChild" in d:
        n = p.child_count
        return n * d["amountPerChild"], f"{n} 个小孩 × ${d['amountPerChild']:,}", 0

    return d["amount"], require_note, 0


def settlement_preview(state: RoomState, lib: CardLibrary) -> dict[str, Any] | None:
    """当前未结算强制卡的应付金额与说明，仅供前端展示；权威结算仍在 decide/apply。"""
    ac = state.active_card
    if ac is None or ac.resolved:
        return None
    player = state.players.get(ac.drawer_id)
    if player is None:
        return None
    try:
        d = lib.get(ac.card_id).data
        if ac.subtype in ("CASH", "EXPENSE_EVENT"):
            due, note, _ = _expense_due(player, d)
            return {"due": due, "note": note, "waived": due == 0}
        if ac.subtype == "DICE_GAMBLE":
            return {"due": d["downPayment"],
                    "note": (f"投入 ${d['downPayment']:,} 后掷 {d['diceCount']} 粒骰子，"
                             f"{_DICE_WIN_DESC.get(d['winCondition'], d['winCondition'])}"
                             f"可得 ${d['payout']:,}"),
                    "waived": False}
        if ac.subtype == "CREDIT_OPTION":
            return {"due": d["amount"],
                    "note": f"可改用信用卡支付（月供 +${d['creditMonthly']:,}）",
                    "waived": False}
        if ac.subtype == "INSTALLMENT":
            return {"due": d["downPayment"],
                    "note": (f"分期：{d['liabilityName']}负债 +${d['liability']:,}，"
                             f"月供 +${d['monthly']:,}"),
                    "waived": False}
    except (EngineError, KeyError):
        return None   # 预览失败不阻塞广播，结算时 decide 仍会给出明确报错
    return None       # 机会卡/股票等有独立交互面板，无需预览


def stock_offer_preview(state: RoomState, lib: CardLibrary) -> dict[str, Any] | None:
    """当前股票窗口的公开参数，供前端判断该给谁显示交易入口；权威校验仍在 decide。

    与 _stock_card 同口径：不看 resolved，窗口活到回合结束。
    """
    ac = state.active_card
    if ac is None or ac.subtype != "STOCK_OFFER":
        return None
    try:
        d = lib.get(ac.card_id).data
        return {"symbol": d["symbol"], "price": d["price"],
                "buyerScope": d.get("buyerScope", "DRAWER_ONLY")}
    except (EngineError, KeyError):
        return None


def _resell_offer_events(state: RoomState, player: PlayerState, card, p: dict) -> list[Event]:
    """把机会卡转卖给其他玩家（说明书 p8：抽卡人可把生意让给别人）。"""
    to_id = p["toPlayerId"]
    fee = int(p.get("price", 0))
    if to_id == player.id or to_id not in state.players:
        raise EngineError("BAD_TARGET", "转卖对象无效")
    if fee < 0:
        raise EngineError("BAD_AMOUNT", "转让费不能为负")
    return [_ev("RESELL_OFFERED", prompt_id=_new_id(), card_id=card.id,
                from_player_id=player.id, to_player_id=to_id, fee=fee,
                down_payment=card.data["downPayment"], title=card.title)]


# ---------- 骰子赌局（sd-013 嫂子借钱） ----------

_dice_rng = random.Random()

_DICE_WIN_DESC = {">3": "点数大于 3 时"}

_DICE_OPS = {
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b, "<": lambda a, b: a < b, "==": lambda a, b: a == b,
}


def seed_dice(seed: int | None) -> None:
    """固定骰子序列，仅供测试与复盘使用；正式对局不调用。"""
    global _dice_rng
    _dice_rng = random.Random(seed)


def _dice_win(total: int, condition: str) -> bool:
    for op, fn in _DICE_OPS.items():
        if condition.startswith(op):
            return fn(total, int(condition[len(op):]))
    raise EngineError("BAD_CONDITION", f"未知胜负条件: {condition}")


def _dice_gamble_event(player_id: str, card) -> Event:
    """服务端掷骰并把点数写进事件流：结果可重放、不可重掷（design/06 §4.1）。"""
    d = card.data
    rolls = [_dice_rng.randint(1, 6) for _ in range(d["diceCount"])]
    total = sum(rolls)
    won = _dice_win(total, d["winCondition"])
    return _ev("DICE_GAMBLE_RESOLVED", player_id=player_id, card_id=card.id,
               stake=d["downPayment"], rolls=rolls, total=total, won=won,
               payout=d["payout"] if won else 0, title=card.title)


def _asset_bought_event(player_id: str, card) -> Event:
    """买入事件携带全部结算数值与规格字段，回放不依赖卡库。

    规格字段（rooms/units/quantity/businessKind）决定日后求购卡怎么计价，
    必须随资产落库，否则按间/按套/按枚计价无从算起。
    """
    d = card.data
    spec = {k: d[src] for k, src in
            (("rooms", "rooms"), ("units", "units"), ("quantity", "quantity"),
             ("business_kind", "businessKind"), ("income_category", "incomeCategory"))
            if src in d}
    return _ev("ASSET_BOUGHT", player_id=player_id, card_id=card.id,
               asset_id=_new_id(), kind="REALESTATE" if card.subtype == "REALESTATE" else "BUSINESS",
               asset_type=d.get("assetType", "企业"), name=card.title,
               cost=d["cost"], down_payment=d["downPayment"],
               mortgage=d.get("mortgage", 0), cashflow=d["cashflow"], **spec)


def _d_resell_confirm(state, actor_id, p, lib) -> list[Event]:
    prompt = _find_prompt(state, p["promptId"], actor_id, "RESELL_CONFIRM")
    pd = prompt.payload
    if not p.get("accept"):
        return [_ev("RESELL_REJECTED", prompt_id=prompt.id,
                    from_player_id=pd["from_player_id"], to_player_id=actor_id)]
    buyer = _get_player(state, actor_id)
    card = lib.get(pd["card_id"])
    _require_cash(buyer, pd["fee"] + card.data["downPayment"])
    # 赌局转卖后由买家掷骰承担盈亏，不产生资产条目
    settle = (_dice_gamble_event(actor_id, card) if card.subtype == "DICE_GAMBLE"
              else _asset_bought_event(actor_id, card))
    return [_ev("RESELL_CONFIRMED", prompt_id=prompt.id, card_id=card.id,
                from_player_id=pd["from_player_id"], to_player_id=actor_id,
                fee=pd["fee"]),
            settle]


# ---------- 股票（design/02 §6.2） ----------

def _stock_card(state: RoomState, lib) -> tuple[ActiveCard, dict]:
    """交易窗口的有效期 = 抽卡人的整个回合（design/02 §6.2「本机会有效期内」）。

    故意不看 `ac.resolved`：抽卡人的 CARD_PASSED 只表示「我自己不买」，
    不该连带作废其他玩家（以及他本人）按今日价卖出持仓的权利。
    窗口由 TURN_ENDED 清空 active_card 时才关闭。
    """
    ac = state.active_card
    if ac is None or ac.subtype != "STOCK_OFFER":
        raise EngineError("NO_STOCK_WINDOW", "当前没有生效的股票报价")
    return ac, lib.get(ac.card_id).data


def _d_stock_buy(state, actor_id, p, lib) -> list[Event]:
    ac, d = _stock_card(state, lib)
    # buyerScope 决定买入窗口对谁开放；卖出侧一律所有人可卖（design/06 §3.3）
    if d.get("buyerScope", "DRAWER_ONLY") == "DRAWER_ONLY" and ac.drawer_id != actor_id:
        raise EngineError("NOT_DRAWER", "这张卡只有抽卡人能按此价格买入")
    player = _get_player(state, actor_id)
    _require_no_bankruptcy(player)
    if player.phase != Phase.RAT_RACE:
        raise EngineError("WRONG_PHASE", "只有老鼠赛跑阶段的玩家可交易")
    qty = int(p["qty"])
    if qty <= 0:
        raise EngineError("BAD_AMOUNT", "股数须为正整数")
    cost = qty * d["price"]
    _require_cash(player, cost)
    return [_ev("STOCK_BOUGHT", player_id=actor_id, card_id=ac.card_id,
                symbol=d["symbol"], qty=qty, price=d["price"],
                dividend_per_share=d.get("dividendPerShare", 0),
                income_category=d.get("incomeCategory", "DIVIDEND"), cost=cost)]


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

    if pd.get("subtype") == "INSTALLMENT_SALE":
        # 房子只是冻结：不收首付、不解押、不移房，成交当下不动任何现金（design/06 §6.4）。
        # 此后每月 −$500，扣满 $100,000（200 月）时才移交房产并一次性入账。
        return [_ev("INSTALLMENT_SCHEDULED", prompt_id=prompt.id, player_id=actor_id,
                    asset_id=pd["asset_id"], asset_name=pd["asset_name"],
                    card_id=pd["card_id"], receivable_id=_new_id(),
                    total_price=pd["price"], monthly_delta=pd["monthly_delta"],
                    duration_months=pd["duration_months"])]

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
    if player.phase != Phase.RAT_RACE:
        # 进快车道后老鼠赛跑的记录卡已翻面封存，那边的负债不再参与计算
        raise EngineError("WRONG_PHASE", "已进入快车道，老鼠赛跑的记录卡已翻面，不能再清偿")
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
    _require_square_free(state)
    _require_landing(state, "CHILD")
    if player.child_count >= 3:
        return [_ev("CHILD_NOOP", player_id=player.id)]   # 满 3 无效果（P.4）
    return [_ev("CHILD_ADDED", player_id=player.id)]


def _d_charity(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    _require_square_free(state)
    _require_landing(state, "CHARITY")
    amount = (F.total_income(player) + 5) // 10   # 总收入×10%，四舍五入到美元
    _require_cash(player, amount)
    return [_ev("CHARITY_DONATED", player_id=player.id, amount=amount)]


def _d_unemployment(state, actor_id, p, lib) -> list[Event]:
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
    _require_square_free(state)
    _require_landing(state, "UNEMPLOYMENT")
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
    """主动宣告破产：判定条件与 P.5 一致，但破产通常由结算日自动触发（见 _d_payday）。"""
    player = _require_current(state, actor_id)
    _require_no_bankruptcy(player)
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
    frozen = player.frozen_asset_ids
    for a in player.real_estates:
        if a.id == aid:
            if a.id in frozen:
                # 冻结房已许诺给亲戚，破产也不能单独变卖；出局时随全部资产被银行收走
                raise EngineError("ASSET_FROZEN", "该房产处于分期收款冻结中，不能变卖")
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
    # 冻结房不可变卖，故不计入「还能不能继续卖」的判定，否则只剩冻结房时会死锁
    frozen = player.frozen_asset_ids
    sellable = [a for a in player.real_estates if a.id not in frozen]
    has_sellable = bool(sellable or player.businesses or player.stocks)
    if cf < 0 and has_sellable:
        raise EngineError("MUST_SELL_MORE", "月现金流仍为负，须继续以首期 50% 向银行变卖资产")
    return [_ev("BANKRUPTCY_RESOLVED", player_id=player.id)]


# ---------- 快车道（design/02 §9–§11） ----------

def _require_ft(state: RoomState, pid: str) -> PlayerState:
    p = _require_current(state, pid)
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
    # turn_closed：本回合已经在老鼠赛跑走过一格（抽卡买资产过线当场进场）。
    # 棋子这一回合只是移到外环「在此进入」箭头，不再掷骰移动，所以快车道的停留格与
    # 现金流量日一并关闭；回合开始就进场的（上一轮被别人的卡顶过线）则一切照常。
    return [_ev("ENTERED_FASTTRACK", player_id=player.id, passive_income=passive,
                initial_income=initial, cash_returned=player.cash,
                turn_closed=state.turn_square_used, turn_count=state.turn_count,
                # 棋子落到「在此进入」箭头上：它是入口标记不是格子，下一次掷骰
                # 才踏上第 1 格（那是一个梦想格，凭空占住就错了，change D3）
                ft_position=0)]


def _d_ft_payday(state, actor_id, p, lib) -> list[Event]:
    _reject_online(state, "ONLINE_AUTO_PAYDAY", "纯线上模式的现金流量日在走格时自动结算")
    player = _require_ft(state, actor_id)
    _require_payday_free(state, "1–4")
    times = int(p.get("times", 1))
    if times < 1 or times > 4:
        raise EngineError("BAD_TIMES", "收款次数须为 1–4")
    return [_ev("FT_PAYDAY", player_id=player.id,
                amount=player.fasttrack.current_income * times, times=times)]


def _d_ft_buy_business(state, actor_id, p, lib) -> list[Event]:
    player = _require_ft(state, actor_id)
    _require_square_free(state)
    _require_landing(state, "FT_BUSINESS", ref_id=p["squareId"])
    sq = lib.get_ft_business(p["squareId"])
    if sq.id in state.ft_sold_squares:
        raise EngineError("SQUARE_SOLD", "该企业已被其他玩家买断")
    _require_cash(player, sq.down_payment, loan_hint=False)
    if sq.dice_rule:
        if is_online(state):
            # 纯线上没有实体骰子可掷：服务端摇，点数写进事件流（同 D15/D4 的做法）。
            # 客户端传来的 diceRoll 一律忽略——那是「声明线下发生了什么」的入口。
            roll = _dice_rng.randint(1, 6)
        else:
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
    _require_square_free(state)
    _require_landing(state, "FT_DREAM", ref_id=p["squareId"])
    dream = lib.get_ft_dream(p["squareId"])
    if player.dream_id != dream.id:
        raise EngineError("NOT_YOUR_DREAM", "只能购买自己选定的梦想（他人梦想可双倍加价）")
    price = _dream_price(state, dream)
    _require_cash(player, price, loan_hint=False)
    return [_ev("FT_DREAM_BOUGHT", player_id=player.id, square_id=dream.id,
                name=dream.name, price=price)]


def _d_ft_double_dream(state, actor_id, p, lib) -> list[Event]:
    player = _require_ft(state, actor_id)
    _require_square_free(state)
    _require_landing(state, "FT_DREAM", ref_id=p["squareId"])
    dream = lib.get_ft_dream(p["squareId"])
    if player.dream_id == dream.id:
        raise EngineError("OWN_DREAM", "这是你自己的梦想，直接购买即可")
    if not any(pl.dream_id == dream.id for pl in state.players.values()):
        raise EngineError("NOT_CHOSEN", "该梦想不属于任何玩家，无需加价")
    price = _dream_price(state, dream)
    _require_cash(player, price, loan_hint=False)
    return [_ev("FT_DREAM_DOUBLED", player_id=player.id, square_id=dream.id,
                name=dream.name, price_paid=price, base_price=dream.price)]


def _d_ft_claim_dream(state, actor_id, p, lib) -> list[Event]:
    player = _require_ft(state, actor_id)
    _require_square_free(state)
    _require_landing(state, "FT_DREAM", ref_id=p["squareId"])
    dream = lib.get_ft_dream(p["squareId"])
    if any(pl.dream_id == dream.id for pl in state.players.values()):
        raise EngineError("DREAM_CHOSEN", "该梦想已经有主，只能加价或（如果是你自己的）直接买下")
    price = _dream_price(state, dream)
    _require_cash(player, price, loan_hint=False)
    return [_ev("FT_DREAM_CLAIMED", player_id=player.id, square_id=dream.id,
                name=dream.name, price=price)]


def _d_ft_charity(state, actor_id, p, lib) -> list[Event]:
    player = _require_ft(state, actor_id)
    _require_square_free(state)
    _require_landing(state, "FT_CHARITY")
    _require_cash(player, lib.ft_charity_cost, loan_hint=False)
    return [_ev("FT_CHARITY_DONATED", player_id=player.id, amount=lib.ft_charity_cost)]


def _d_ft_cash_hit(kind: str, factor_desc: str):
    def handler(state, actor_id, p, lib) -> list[Event]:
        player = _require_ft(state, actor_id)
        _require_square_free(state)
        _require_landing(state, f"FT_{kind}")
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


def _require_host(state: RoomState, actor_id, what: str) -> PlayerState:
    host = _get_player(state, actor_id)
    if not host.is_host:
        raise EngineError("NOT_HOST", f"只有房主能{what}")
    return host


def _d_end_game(state, actor_id, p, lib) -> list[Event]:
    _require_host(state, actor_id, "结束对局")
    if state.status == RoomStatus.CLOSED:
        raise EngineError("ALREADY_CLOSED", "对局已结束")
    return [_ev("GAME_ENDED", reason=str(p.get("reason", "")))]


def _d_rematch(state, actor_id, p, lib) -> list[Event]:
    # 就地再来一局：同一房间重置为准备阶段，保留玩家身份/令牌，全员自动回到房间准备页重选职业。
    _require_host(state, actor_id, "再来一局")
    if state.status != RoomStatus.FINISHED:
        raise EngineError("NOT_FINISHED", "对局结束后才能再来一局")
    return [_ev("REMATCH")]


def _d_host_remove_player(state, actor_id, p, lib) -> list[Event]:
    host = _require_host(state, actor_id, "移除玩家")
    _require_playing(state)
    target = _get_player(state, p["playerId"])
    if target.id == host.id:
        raise EngineError("BAD_TARGET", "不能移除自己")
    if target.phase == Phase.OUT:
        raise EngineError("BAD_TARGET", "该玩家已退出")
    return [_ev("PLAYER_REMOVED", player_id=target.id)]


def _d_leave_game(state, actor_id, p, lib) -> list[Event]:
    if state.status not in (RoomStatus.LOBBY, RoomStatus.SETUP,
                            RoomStatus.PLAYING, RoomStatus.FINISHED):
        raise EngineError("NOT_LEAVABLE", "对局已关闭，无需退出")
    player = _get_player(state, actor_id)
    if player.phase == Phase.OUT:
        raise EngineError("ALREADY_LEFT", "你已退出对局")
    new_host_id = None
    if player.is_host:
        if state.status not in (RoomStatus.LOBBY, RoomStatus.SETUP):
            raise EngineError("HOST_CANNOT_LEAVE", "对局已开始，房主不能单独退出，请结束对局")
        others = [pl for pl in state.players.values() if pl.id != player.id]
        if others:
            new_host_id = min(others, key=lambda pl: pl.seat).id
    return [_ev("PLAYER_LEFT", player_id=player.id, nickname=player.nickname,
                new_host_id=new_host_id)]


def _d_host_end_turn(state, actor_id, p, lib) -> list[Event]:
    # 当前玩家临时离开时房主强制推进；未结算的强制卡随回合结束一并作废
    _require_host(state, actor_id, "代结束回合")
    _require_playing(state)
    if state.current_player_id is None:
        raise EngineError("NO_CURRENT", "当前没有行动中的玩家")
    return [_ev("TURN_ENDED", player_id=state.current_player_id)]


_HANDLERS = {
    "SET_ROOM_MODE": _d_set_room_mode,
    "JOIN": _d_join,
    "SELECT_PROFESSION": _d_select_profession,
    "SELECT_DREAM": _d_select_dream,
    "SET_TURN_ORDER": _d_set_turn_order,
    "START_GAME": _d_start_game,
    "END_TURN": _d_end_turn,
    "ROLL_DICE": _d_roll_dice,
    "CHOOSE_DEAL_SIZE": _d_choose_deal_size,
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
    "FT_CLAIM_DREAM": _d_ft_claim_dream,
    "FT_CHARITY": _d_ft_charity,
    "FT_TAX_AUDIT": _d_ft_cash_hit("TAX_AUDIT", "半额"),
    "FT_DIVORCE": _d_ft_cash_hit("DIVORCE", "全额"),
    "FT_LAWSUIT": _d_ft_cash_hit("LAWSUIT", "半额"),
    "HOST_ADJUST": _d_host_adjust,
    "END_GAME": _d_end_game,
    "REMATCH": _d_rematch,
    "HOST_REMOVE_PLAYER": _d_host_remove_player,
    "LEAVE_GAME": _d_leave_game,
    "HOST_END_TURN": _d_host_end_turn,
}


# ============================================================ apply

def apply(state: RoomState, event: Event) -> RoomState:
    s = state.model_copy(deep=True)
    handler = _APPLIERS.get(event["type"])
    if handler is None:
        raise EngineError("UNKNOWN_EVENT", f"未知事件: {event['type']}")
    handler(s, event.get("payload", {}))
    return s


def _use_square(s: RoomState) -> None:
    """本回合的停留格已消耗；纯线上模式下顺带把落点标记为已处理。

    落点的「处理完了没有」只有一个真相源：谁消耗了停留格，谁就把它关上。
    线下模式 landing 恒为 None，这里退化成原来那一行赋值。
    """
    s.turn_square_used = True
    if s.landing is not None:
        s.landing.resolved = True


def _a_room_mode_set(s: RoomState, p) -> None:
    s.mode = GameMode(p["mode"])


def _a_dice_rolled(s: RoomState, p) -> None:
    s.turn_dice_used = True


def _a_player_moved(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    if p["track"] == "FAST_TRACK":
        pl.ft_position = p["to"]
    else:
        pl.rr_position = p["to"]
    lg = p["landing"]
    s.landing = Landing(track=lg["track"], index=lg["index"], type=lg["type"],
                        ref_id=lg.get("ref_id") or None)


def _a_landing_resolved(s: RoomState, p) -> None:
    """落点没有后续事件可标记「处理完了」时补一条（结算格 / 已买断的绿格 / 就地破产）。"""
    _use_square(s)
    if s.landing is not None:
        s.landing.note = p.get("note", "")


def _a_player_joined(s: RoomState, p) -> None:
    # 准备阶段补位会使已排好的顺序失效；回到大厅让房主重新确认顺序。
    if s.status == RoomStatus.SETUP:
        s.turn_order = []
        s.turn_index = 0
        s.status = RoomStatus.LOBBY
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
    # 机会卡失效（⚠️ADAPT：抽卡人结束回合时失效），其市场/转卖窗口一并关闭。
    # 没做决定就结束回合的（股票窗口、房主代结束）也算这张牌用完了，一并进弃牌堆，
    # 否则那张牌会从牌堆里凭空消失、永远洗不回来。
    _discard_active(s)
    s.active_card = None
    s.prompts = [pr for pr in s.prompts if pr.kind == "TRANSFER_CONFIRM"]
    # 回合内"停留格/结算日/掷骰"标志复位，下一玩家重新计
    s.turn_square_used = False
    s.turn_payday_used = False
    s.turn_dice_used = False
    s.landing = None
    _advance_turn(s)


def _advance_turn(s: RoomState) -> None:
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
    _advance_installments(pl, p["times"])
    s.turn_payday_used = True


def _a_payday_unpayable(s: RoomState, p) -> None:
    # 付不出的这个月不结算（现金不动、分期不推进），随后的 BANKRUPTCY_STARTED 接管；
    # 说明书 P.5 的破产流程是「变卖偿债至现金流转正 + 停赛 3 轮」，没有补缴环节。
    s.turn_payday_used = True


def _advance_installments(pl: PlayerState, months: int) -> None:
    """结算日 = 过了几个月，分期收款按此计数（design/06 §6.4）。

    收齐 $100,000 那一刻：移交房产（连同房贷）、一次性入账全款。
    一次过多个结算日跨过期满时，PAYDAY 已按「持房中」的月现金流算了全部 months，
    但期满后的月份不该再有这套房的租金、也不该再扣 −$500——把这几个月多算的
    「本房租金 + monthly_delta」退回。房子移除前先读它的 cashflow。
    """
    for r in pl.installment_receivables:
        if r.settled:
            continue
        before = r.months_elapsed
        r.months_elapsed = min(before + months, r.duration_months)
        if not r.settled:
            continue                                 # 未到期：−$500 已随月现金流正确扣除
        overcharged = months - (r.months_elapsed - before)
        house = next((a for a in pl.real_estates if a.id == r.asset_id), None)
        per_month = (house.cashflow if house else 0) + r.monthly_delta
        pl.cash -= per_month * overcharged           # 退回期满后月份多算的租金与扣款
        if house is not None:
            _remove_asset(pl, r.asset_id)            # 全款收齐：房产+房贷一并移交给亲戚
        pl.cash += r.total_price                     # $100,000 到账


def _a_decks_shuffled(s: RoomState, p) -> None:
    s.decks = {deck: list(ids) for deck, ids in p["orders"].items()}
    s.discards = {deck: [] for deck in p["orders"]}


def _a_deck_reshuffled(s: RoomState, p) -> None:
    s.decks[p["deck"]] = list(p["order"])
    s.discards[p["deck"]] = []


def _a_card_drawn(s: RoomState, p) -> None:
    resolved = p["deck"] == "MARKET"   # 市场卡的效果在伴随事件中完成
    s.active_card = ActiveCard(card_id=p["card_id"], deck=p["deck"],
                               subtype=p["subtype"], drawer_id=p["player_id"],
                               resolved=resolved)
    _use_square(s)
    pile = s.decks.get(p["deck"])
    if pile and p["card_id"] in pile:
        # 发牌时取的是堆顶；这里按 id 移除而不是 pop(0)，是为了让「撤销中间一次发牌
        # 后整流重放」照样成立——后面几次发牌各自记着抽到了哪张，牌堆只需少掉那几张。
        pile.remove(p["card_id"])


def _discard_active(s: RoomState) -> None:
    """当前卡进弃牌堆。线下模式 decks 恒空，这里整个是空操作。"""
    ac = s.active_card
    if ac is None or ac.discarded or ac.deck not in s.decks:
        return
    s.discards.setdefault(ac.deck, []).append(ac.card_id)
    ac.discarded = True


def _a_card_resolved(s: RoomState, p) -> None:
    if s.active_card and s.active_card.card_id == p["card_id"]:
        s.active_card.resolved = True
        _discard_active(s)


def _a_card_passed(s: RoomState, p) -> None:
    _mark_resolved(s)


def _mark_resolved(s: RoomState) -> None:
    if s.active_card:
        s.active_card.resolved = True
        _discard_active(s)


def _a_asset_bought(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["down_payment"]
    model = RealEstate if p["kind"] == "REALESTATE" else OwnedBusiness
    target = pl.real_estates if p["kind"] == "REALESTATE" else pl.businesses
    target.append(model(
        id=p["asset_id"], card_id=p["card_id"], asset_type=p["asset_type"],
        name=p["name"], cost=p["cost"], down_payment=p["down_payment"],
        mortgage=p["mortgage"], cashflow=p["cashflow"],
        rooms=p.get("rooms"), units=p.get("units"), quantity=p.get("quantity"),
        business_kind=p.get("business_kind"), income_category=p.get("income_category")))
    if s.active_card and s.active_card.card_id == p["card_id"]:
        _mark_resolved(s)


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
        pl.stocks.append(StockHolding(
            symbol=p["symbol"], shares=p["qty"], cost_per_share=p["price"],
            dividend_per_share=p["dividend_per_share"],
            income_category=p.get("income_category", "DIVIDEND")))


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
    """并股/拆股：股数按比例增减，**总成本不变**（design/06 §3.0，该规则是固有的）。

    单价随之反向调整，否则破产清算按 shares × cost_per_share 估值会凭空少算一半。
    """
    num, den = p["ratio_num"], p["ratio_den"]   # "2:1" → 每2股并1股
    for pl in s.players.values():
        kept = []
        for h in pl.stocks:
            if h.symbol == p["symbol"]:
                total_cost = h.shares * h.cost_per_share
                h.shares = h.shares * den // num
                if h.shares > 0:
                    h.cost_per_share = total_cost // h.shares
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


def _a_installment_scheduled(s: RoomState, p) -> None:
    _remove_prompt(s, p["prompt_id"])
    pl = s.players[p["player_id"]]
    # 房子就地冻结：不动现金、不移房、不解押。冻结状态由 receivable.asset_id 派生。
    pl.installment_receivables.append(InstallmentReceivable(
        id=p["receivable_id"], card_id=p["card_id"], name=p["asset_name"],
        asset_id=p["asset_id"], total_price=p["total_price"],
        monthly_delta=p["monthly_delta"], duration_months=p["duration_months"]))


def _a_cashflow_modified(s: RoomState, p) -> None:
    """给资产条目本身改月现金流，不是改玩家总账（design/06 §4.1）。"""
    delta = p["delta"]
    for pid, asset_ids in p["targets"].items():
        pl = s.players[pid]
        for asset in pl.owned_assets:
            if asset.id in asset_ids:
                asset.cashflow += delta


def _a_dice_gamble_resolved(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["stake"]
    pl.cash += p["payout"]                 # 未中奖时 payout=0，血本无归
    _mark_resolved(s)


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
    _use_square(s)


def _a_child_noop(s: RoomState, p) -> None:
    _use_square(s)    # 满3孩无效果，但停留格已消耗


def _a_charity_donated(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["amount"]
    pl.charity_turns = 3
    pl.charity_just_donated = True
    _use_square(s)


def _a_unemployment_hit(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["amount"]
    pl.skip_turns = 2
    _use_square(s)
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
    pl.installment_receivables = []   # 冻结房与未收欠款一并被银行收走（双重亏损，Q1 裁决）
    pl.cash = 0
    alive = [q for q in s.players.values() if q.phase != Phase.OUT]
    if len(alive) == 1:
        s.status = RoomStatus.FINISHED
        s.winner_id = alive[0].id


def _a_entered_fasttrack(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.phase = Phase.FAST_TRACK
    # 老鼠赛跑的现金交回银行（按说明书），随即按 P.5「将获得 100 倍的非工资收入
    # （即您的财产）」发放一笔启动资金 —— 进入即到账，此后每次停在或经过
    # 「现金流量日」再领同样金额。
    pl.cash = p["initial_income"]
    pl.charity_turns = 0                         # 老鼠赛跑的慈善轮次不带进快车道
    pl.fasttrack.initial_income = p["initial_income"]
    pl.fasttrack.current_income = p["initial_income"]
    pl.fasttrack.entered_turn = p.get("turn_count")
    pl.ft_position = p.get("ft_position", 0)
    s.landing = None                             # 换了轨道，老鼠赛跑那一格不再有效
    if p.get("turn_closed"):
        # 本回合已在老鼠赛跑走过一格：停留格标志本就是 True（保持不动，它正是那把锁），
        # 这里把现金流量日也一并关掉 —— 启动资金刚发过，本回合不再移动，
        # 不关的话玩家能在启动资金之外再白领一笔 current_income。
        s.turn_payday_used = True


def _a_ft_payday(s: RoomState, p) -> None:
    s.players[p["player_id"]].cash += p["amount"]
    s.turn_payday_used = True


def _check_income_victory(s: RoomState, pl: PlayerState) -> None:
    ft = pl.fasttrack
    if ft.current_income - ft.initial_income >= 50_000:
        s.status = RoomStatus.FINISHED
        s.winner_id = pl.id


def _a_ft_business_bought(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["down_payment"]
    _use_square(s)
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
    _use_square(s)
    s.status = RoomStatus.FINISHED
    s.winner_id = pl.id


def _a_ft_dream_doubled(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["price_paid"]
    s.dream_price_bumps[p["square_id"]] = s.dream_price_bumps.get(p["square_id"], 0) + 1
    _use_square(s)


def _a_ft_dream_claimed(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["price"]
    _use_square(s)


def _a_ft_charity_donated(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    pl.cash -= p["amount"]
    pl.fasttrack.charity_forever = True
    _use_square(s)


def _a_ft_cash_hit(s: RoomState, p) -> None:
    pl = s.players[p["player_id"]]
    if p["kind"] == "DIVORCE":
        pl.cash = 0
    else:
        pl.cash -= p["amount"]
    _use_square(s)


def _a_host_adjusted(s: RoomState, p) -> None:
    s.players[p["player_id"]].cash += p["delta"]


def _a_host_reverted(s: RoomState, p) -> None:
    # 审计事件不改状态（design/03 §6）：撤销的实际效果 = 被撤销事件从重放流中剔除。
    # 必须注册，否则含撤销记录的事件流在试重放/重启恢复时会抛 UNKNOWN_EVENT。
    pass


def _a_player_corrected(s: RoomState, p) -> None:
    # FR-29 本人更正的审计事件，同 HOST_REVERTED 不改状态。
    pass


def _a_game_ended(s: RoomState, p) -> None:
    s.status = RoomStatus.CLOSED
    s.prompts = []
    s.active_card = None


def _mark_player_out(s: RoomState, player_id: str) -> None:
    pl = s.players[player_id]
    was_current = s.current_player_id == pl.id
    pl.phase = Phase.OUT
    pl.in_bankruptcy = False
    # 资产/现金保留原样：误点可由房主在日志中撤销恢复
    s.prompts = [pr for pr in s.prompts if pr.target_player_id != pl.id]
    if s.active_card and s.active_card.drawer_id == pl.id:
        _discard_active(s)
        s.active_card = None
    if was_current:
        s.turn_square_used = False
        s.turn_payday_used = False
        s.turn_dice_used = False
        s.landing = None
        _advance_turn(s)
    alive = [q for q in s.players.values() if q.phase != Phase.OUT]
    if len(alive) == 1 and s.status == RoomStatus.PLAYING:
        s.status = RoomStatus.FINISHED
        s.winner_id = alive[0].id


def _a_player_removed(s: RoomState, p) -> None:
    _mark_player_out(s, p["player_id"])


def _a_player_left(s: RoomState, p) -> None:
    player_id = p["player_id"]
    if s.status in (RoomStatus.LOBBY, RoomStatus.SETUP):
        # 未开局不保留空座位：释放名额、职业和梦想占用。
        s.players.pop(player_id)
        s.turn_order = [pid for pid in s.turn_order if pid != player_id]
        if s.turn_index >= len(s.turn_order):
            s.turn_index = 0
        new_host_id = p.get("new_host_id")
        if new_host_id:
            s.players[new_host_id].is_host = True
        return
    _mark_player_out(s, player_id)


def _a_rematch(s: RoomState, p) -> None:
    # 就地重开：保留「未出局玩家 + 房主」的身份（id/昵称/房主），其余（退出/被踢/破产出局）不带入；
    # 按原座位重排为 0..n，逐个重建为默认态（清空职业/梦想/现金/资产/负债/快车道/孩子/停赛）。
    survivors = sorted(
        (pl for pl in s.players.values() if pl.phase != Phase.OUT or pl.is_host),
        key=lambda pl: pl.seat)
    s.players = {
        pl.id: PlayerState(id=pl.id, nickname=pl.nickname, is_host=pl.is_host, seat=i)
        for i, pl in enumerate(survivors)
    }
    # 房间级重置（settings 保留）；回到大厅，等房主重排顺序、全员重选职业后再开。
    s.status = RoomStatus.LOBBY
    s.turn_order = []
    s.turn_index = 0
    s.turn_count = 1
    s.turn_square_used = False
    s.turn_payday_used = False
    s.turn_dice_used = False
    s.landing = None
    s.active_card = None
    s.decks = {}                 # 新一局在 START_GAME 时重新洗
    s.discards = {}
    s.prompts = []
    s.ft_sold_squares = []
    s.dream_price_bumps = {}
    s.winner_id = None


_APPLIERS = {
    "ROOM_MODE_SET": _a_room_mode_set,
    "PLAYER_JOINED": _a_player_joined,
    "PROFESSION_SELECTED": _a_profession_selected,
    "DREAM_SELECTED": _a_dream_selected,
    "TURN_ORDER_SET": _a_turn_order_set,
    "DECKS_SHUFFLED": _a_decks_shuffled,
    "DECK_RESHUFFLED": _a_deck_reshuffled,
    "GAME_STARTED": _a_game_started,
    "TURN_ENDED": _a_turn_ended,
    "DICE_ROLLED": _a_dice_rolled,
    "PLAYER_MOVED": _a_player_moved,
    "LANDING_RESOLVED": _a_landing_resolved,
    "PAYDAY": _a_payday,
    "PAYDAY_UNPAYABLE": _a_payday_unpayable,
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
    "INSTALLMENT_SCHEDULED": _a_installment_scheduled,
    "CASHFLOW_MODIFIED": _a_cashflow_modified,
    "DICE_GAMBLE_RESOLVED": _a_dice_gamble_resolved,
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
    "FT_DREAM_CLAIMED": _a_ft_dream_claimed,
    "FT_CHARITY_DONATED": _a_ft_charity_donated,
    "FT_CASH_HIT": _a_ft_cash_hit,
    "HOST_ADJUSTED": _a_host_adjusted,
    "HOST_REVERTED": _a_host_reverted,
    "PLAYER_CORRECTED": _a_player_corrected,
    "GAME_ENDED": _a_game_ended,
    "REMATCH": _a_rematch,
    "PLAYER_REMOVED": _a_player_removed,
    "PLAYER_LEFT": _a_player_left,
}


def replay(events: list[Event], initial: RoomState | None = None) -> RoomState:
    """state = reduce(初始, 事件流)。跳过被撤销的事件由存储层负责过滤。"""
    state = initial or RoomState()
    for ev in events:
        state = apply(state, ev)
    return state
