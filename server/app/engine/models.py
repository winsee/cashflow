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


class Phase(StrEnum):
    RAT_RACE = "RAT_RACE"
    FAST_TRACK = "FAST_TRACK"
    OUT = "OUT"


class StockHolding(BaseModel):
    symbol: str
    shares: int
    cost_per_share: int
    dividend_per_share: int = 0


class RealEstate(BaseModel):
    id: str                 # 房间内唯一资产 id
    card_id: str
    asset_type: str         # "3室2厅" 等，市场卡匹配用
    name: str
    cost: int
    down_payment: int
    mortgage: int           # 对应负债·房地产抵押贷款
    cashflow: int           # 损益表·房地产收入行


class OwnedBusiness(BaseModel):
    id: str
    card_id: str
    asset_type: str = "企业"
    name: str
    cost: int
    down_payment: int
    mortgage: int = 0
    cashflow: int


class ExtraLiability(BaseModel):
    """卡牌新增负债行 + 周期支出行（如游艇：负债 17,000 / 月供 340）。"""
    id: str
    name: str
    amount: int
    monthly: int


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

    charity_turns: int = 0       # 老鼠赛跑 0..3
    charity_just_donated: bool = False   # 捐款当轮不消耗慈善轮数
    skip_turns: int = 0          # 0..3
    dream_id: str | None = None
    in_bankruptcy: bool = False
    fasttrack: FastTrackState = Field(default_factory=FastTrackState)


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
