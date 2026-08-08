"""引擎状态模型（design/02 §2、§3.1；design/03 §3 state JSON）。

所有金额为非负整数美元；状态只能经 apply(state, event) 变更。
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RoomStatus(StrEnum):
    LOBBY = "LOBBY"
    SETUP = "SETUP"
    PLAYING = "PLAYING"
    FINISHED = "FINISHED"
    CLOSED = "CLOSED"        # 房主主动结束对局，房间不再恢复


class Phase(StrEnum):
    RAT_RACE = "RAT_RACE"
    FAST_TRACK = "FAST_TRACK"
    OUT = "OUT"


class GameMode(StrEnum):
    """对局模式（design/09、change add-online-board-mode D1）。

    OFFLINE_ASSIST 是默认值，升级前的房间重放出来正是它——线下辅助模式一切照旧。
    模式由建房时的 ROOM_MODE_SET 事件写入，不可更改。
    """
    OFFLINE_ASSIST = "OFFLINE_ASSIST"   # 线下辅助：实体棋盘/骰子/卡牌 + 手机记账
    ONLINE = "ONLINE"                   # 纯线上：棋盘、骰子、发牌全在服务端


class StockHolding(BaseModel):
    symbol: str
    shares: int
    cost_per_share: int
    dividend_per_share: int = 0
    income_category: str = "DIVIDEND"   # DIVIDEND | INTEREST（记录卡收入栏，说明书 p7）


class OwnedAsset(BaseModel):
    """已持有资产的共同形状（design/06 §3.2、§3.4）。

    rooms / units / quantity 三个规格字段决定求购卡的计价基准：
    同一张 8 室公寓遇 PER_UNIT $25,000 只值 2.5 万、遇 PER_ROOM $40,000 值 32 万。
    """
    id: str                 # 房间内唯一资产 id
    card_id: str
    asset_type: str         # 受控词表（"3室2厅"/"公寓"/"自建企业"…），市场卡匹配用
    name: str
    cost: int
    down_payment: int
    mortgage: int = 0
    cashflow: int = 0

    rooms: int | None = None            # 公寓房间数 2/4/8，PER_ROOM 计价
    units: int | None = None            # 公寓楼套数 12/24/60，PER_UNIT 计价与 minUnits 门槛
    quantity: int | None = None         # 收藏品枚数，PER_PIECE 计价
    business_kind: str | None = None    # 企业细分类型，跨 assetType 的指名求购匹配
    income_category: str | None = None  # REAL_ESTATE | BUSINESS，现金流记入哪一行


class RealEstate(OwnedAsset):
    """损益表·房地产收入行；mortgage 对应负债·房地产抵押贷款。"""


class OwnedBusiness(OwnedAsset):
    asset_type: str = "企业"


class ExtraLiability(BaseModel):
    """卡牌新增负债行 + 周期支出行（如游艇：负债 17,000 / 月供 340）。"""
    id: str
    name: str
    amount: int
    monthly: int


class InstallmentReceivable(BaseModel):
    """分期收款挂账（mk-029 亲戚分期买房，design/06 §6.4）。

    成交时房子**只是冻结**（仍挂资产负债表，房贷照扣、租金照收），不收首付、不解押；
    卖方每个结算日额外 −$500，累计扣满 $100,000（= 200 个月）。满期那一刻彻底移交房产
    （删房+删房贷）、一次性入账 $100,000、−$500 停止。
    asset_id 指向被冻结的那套房产，据此判定冻结、满期移房、破产收房。
    months_elapsed 追平 duration_months 即视为结清（不再计入月现金流）。
    """
    id: str
    card_id: str
    name: str
    asset_id: str               # 被冻结的房产 id（满期移交、破产收回都靠它定位）
    total_price: int
    monthly_delta: int          # 负数：收齐前卖方每月现金流反而减少
    duration_months: int
    months_elapsed: int = 0

    @property
    def settled(self) -> bool:
        return self.months_elapsed >= self.duration_months


class Liabilities(BaseModel):
    mortgage: int = 0        # 住房抵押贷款
    school_loan: int = 0
    car_loan: int = 0
    credit_card: int = 0
    extra: int = 0           # 额外负债（职业卡）
    bank_loan: int = 0


class FastTrackHolding(BaseModel):
    square_id: str
    name: str
    cashflow: int = 0        # 计入现金流量日收入增量


class FastTrackState(BaseModel):
    initial_income: int = 0      # 初始现金流量日收入
    current_income: int = 0
    businesses: list[FastTrackHolding] = Field(default_factory=list)
    charity_forever: bool = False   # 快车道慈善：永久可选 1-3 粒骰
    entered_turn: int | None = None  # 进场时的 turn_count（前端据此区分「进场当回合」）


class PlayerState(BaseModel):
    id: str
    nickname: str
    seat: int = 0
    is_host: bool = False
    phase: Phase = Phase.RAT_RACE

    # 职业（损益表固定行）
    profession_id: str | None = None
    profession_title: str = ""
    salary: int = 0
    taxes: int = 0
    mortgage_payment: int = 0
    school_loan_payment: int = 0
    car_loan_payment: int = 0
    credit_card_payment: int = 0
    extra_expenses: int = 0      # 额外支出（职业卡固定值）
    other_expenses: int = 0
    per_child_expense: int = 0
    interest_income: int = 0

    cash: int = 0
    savings: int = 0             # 仅开局用，发钱后清零
    child_count: int = 0

    stocks: list[StockHolding] = Field(default_factory=list)
    real_estates: list[RealEstate] = Field(default_factory=list)
    businesses: list[OwnedBusiness] = Field(default_factory=list)
    extra_liabilities: list[ExtraLiability] = Field(default_factory=list)
    liabilities: Liabilities = Field(default_factory=Liabilities)
    installment_receivables: list[InstallmentReceivable] = Field(default_factory=list)

    # 棋盘位置（纯线上模式，change D3）：**1-based 格索引，0 = 起点/入口标记本身**。
    # 两条轨道的第 1 格都是有效果的普通格（内圈是机会、快车道是一个梦想格），
    # 开局若置 1 就等于全场站在机会格上却不抽卡、进快车道就白占一个梦想格。
    # 取哪一个由已有的 phase 决定，不另存「在哪条轨」——那会把 phase 复制一份。
    rr_position: int = 0
    ft_position: int = 0

    charity_turns: int = 0       # 老鼠赛跑 0..3
    charity_just_donated: bool = False   # 捐款当轮不消耗慈善轮数
    skip_turns: int = 0          # 0..3
    dream_id: str | None = None
    in_bankruptcy: bool = False
    fasttrack: FastTrackState = Field(default_factory=FastTrackState)

    @property
    def owned_assets(self) -> list[OwnedAsset]:
        """房地产 + 企业的合并视图（市场卡匹配、没收、破产变卖都要遍历两者）。"""
        return [*self.real_estates, *self.businesses]

    @property
    def frozen_asset_ids(self) -> set[str]:
        """处于分期收款冻结中的房产 id（mk-029）。

        这些房子仍在 real_estates（租金/房贷照常），但对市场卡免疫、破产也不可单独变卖，
        直到分期结清。冻结状态以 receivable 为唯一真相源，不在资产上另存标志位。
        """
        return {r.asset_id for r in self.installment_receivables if not r.settled}


class ActiveCard(BaseModel):
    """当前生效的抽卡（机会卡在抽卡人结束回合时失效，⚠️ADAPT design/02 §5）。"""
    card_id: str
    deck: str
    subtype: str
    drawer_id: str
    resolved: bool = False       # 抽卡人已做主决策（买/过/转卖/付款）
    discarded: bool = False      # 已进弃牌堆（纯线上牌堆模型，防重复入弃）


class Prompt(BaseModel):
    """需特定玩家决策的推送（市场卖出、转账确认、转卖确认）。"""
    id: str
    kind: str                    # MARKET_SELL | TRANSFER_CONFIRM | RESELL_CONFIRM
    target_player_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Landing(BaseModel):
    """当前落点：「现在轮到你处理这一格」（change D5）。

    turn_square_used 只回答「本回合还能不能再停一格」，回答不了「你停在哪一格、
    还欠一个什么决定」——前端要做到「任何时刻只强调当前该做的那一步」，就得能从
    状态里读出这一步是什么。
    """
    track: str                  # RAT_RACE | FAST_TRACK
    index: int                  # 1-based 格索引
    type: str                   # 内圈七种 type，或快车道 FT_BUSINESS/FT_DREAM/FT_* 特殊格
    ref_id: str | None = None   # 内圈 rr-XX；快车道 ft-b-* / ft-d-* / ft-s-*
    resolved: bool = False      # 这一格还欠不欠玩家一个决定
    note: str = ""              # 「本格无事发生」这类说明


class RoomSettings(BaseModel):
    max_players: int = 6
    name: str = "现金流对局"


class RoomState(BaseModel):
    status: RoomStatus = RoomStatus.LOBBY
    mode: GameMode = GameMode.OFFLINE_ASSIST   # 建房时选定，此后不可更改
    settings: RoomSettings = Field(default_factory=RoomSettings)
    players: dict[str, PlayerState] = Field(default_factory=dict)
    turn_order: list[str] = Field(default_factory=list)
    turn_index: int = 0
    turn_count: int = 1          # 第几轮（回到首位玩家 +1）
    turn_square_used: bool = False   # 本回合已声明停留格事件（每回合只停一格）
    turn_payday_used: bool = False   # 本回合已结算银行结算日/现金流量日
    turn_dice_used: bool = False     # 本回合已掷过骰（纯线上模式）
    landing: Landing | None = None   # 当前落点（纯线上模式）
    active_card: ActiveCard | None = None
    # 纯线上牌堆（change D2）：[0] 是堆顶，整串由 DECKS_SHUFFLED / DECK_RESHUFFLED /
    # CARD_DRAWN 推出，所以撤销一次发牌自动把牌退回原位，不需要任何「退牌」逻辑。
    # 线下辅助模式两者恒为空 dict——那边的牌在桌上。
    decks: dict[str, list[str]] = Field(default_factory=dict)
    discards: dict[str, list[str]] = Field(default_factory=dict)
    prompts: list[Prompt] = Field(default_factory=list)
    ft_sold_squares: list[str] = Field(default_factory=list)   # 已被买断的快车道绿格
    dream_price_bumps: dict[str, int] = Field(default_factory=dict)  # square_id -> 加价次数
    winner_id: str | None = None

    @property
    def current_player_id(self) -> str | None:
        if not self.turn_order or self.status != RoomStatus.PLAYING:
            return None
        return self.turn_order[self.turn_index]

    def player(self, pid: str) -> PlayerState:
        return self.players[pid]
