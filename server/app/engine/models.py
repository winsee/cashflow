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
    """分期收款挂账（mk-029 妹夫买房，design/06 §6.4）。

    成交时移交房产、不收首付，卖方月现金流 −$500；每个结算日计一个月，
    满 200 个月时现金流恢复并一次性入账 $100,000。
    months_elapsed 追平 duration_months 即视为结清（不再计入月现金流）。
    """
    id: str
    card_id: str
    name: str
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


class ActiveCard(BaseModel):
    """当前生效的抽卡（机会卡在抽卡人结束回合时失效，⚠️ADAPT design/02 §5）。"""
    card_id: str
    deck: str
    subtype: str
    drawer_id: str
    resolved: bool = False       # 抽卡人已做主决策（买/过/转卖/付款）


class Prompt(BaseModel):
    """需特定玩家决策的推送（市场卖出、转账确认、转卖确认）。"""
    id: str
    kind: str                    # MARKET_SELL | TRANSFER_CONFIRM | RESELL_CONFIRM
    target_player_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RoomSettings(BaseModel):
    max_players: int = 6
    name: str = "现金流对局"


class RoomState(BaseModel):
    status: RoomStatus = RoomStatus.LOBBY
    settings: RoomSettings = Field(default_factory=RoomSettings)
    players: dict[str, PlayerState] = Field(default_factory=dict)
    turn_order: list[str] = Field(default_factory=list)
    turn_index: int = 0
    turn_count: int = 1          # 第几轮（回到首位玩家 +1）
    turn_square_used: bool = False   # 本回合已声明停留格事件（每回合只停一格）
    turn_payday_used: bool = False   # 本回合已结算银行结算日/现金流量日
    active_card: ActiveCard | None = None
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
