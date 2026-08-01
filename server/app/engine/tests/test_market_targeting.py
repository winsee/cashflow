"""求购要约的投放范围：**只有真正持有匹配资产的人才收到 prompt**。

试玩反馈「我没有这类资产也弹出了要我选择的窗口」。引擎这侧的答案必须是硬的：
非持有者一条 `MARKET_PROMPTED` 都不该产出——弹层拿不到 prompt 就弹不出来。

注意求购卡说的是资产**类别**，命中手上任何一项同类资产都会推要约，这是规则不是 bug；
所以这里既钉「不该推的一条都别推」，也钉「该推的一条都别漏」。
"""
from __future__ import annotations

from ..models import InstallmentReceivable, OwnedBusiness, RealEstate


def _give(duo, pid, **kw):
    kind = kw.pop("kind", "REALESTATE")
    base = dict(id=kw.pop("id", f"a-{pid}-{len(duo.player(pid).real_estates)}"),
                card_id="x", cost=0, down_payment=0, mortgage=0, cashflow=0)
    base.update(kw)
    asset = (RealEstate(**base) if kind == "REALESTATE" else OwnedBusiness(**base))
    target = (duo.player(pid).real_estates if kind == "REALESTATE"
              else duo.player(pid).businesses)
    target.append(asset)
    return asset


def _prompted(duo, pid=None):
    return [p for p in duo.state.prompts
            if p.kind == "MARKET_SELL" and (pid is None or p.target_player_id == pid)]


def test_no_assets_at_all_gets_no_prompt(duo):
    """名下空空的人不该收到任何要约（抽卡人自己也一样）。"""
    duo.act("A", "DRAW_CARD", cardId="mk-020")
    assert _prompted(duo) == []


def test_other_asset_type_gets_no_prompt(duo):
    """持有的是「3室2厅」，求购的是「公寓」——类别不同，不推。"""
    _give(duo, "B", id="h1", asset_type="3室2厅", name="3室2厅 学院路",
          cost=65000, down_payment=6500, mortgage=58500, cashflow=380)
    duo.act("A", "DRAW_CARD", cardId="mk-020")
    assert _prompted(duo) == []


def test_business_kind_mismatch_gets_no_prompt(duo):
    """mk-035 只收「汽车清洗公司」：别的企业类型一条都不推。"""
    _give(duo, "B", kind="BUSINESS", id="biz1", asset_type="自建企业",
          business_kind="小型机械公司", name="小型机械公司", units=1,
          cost=60000, down_payment=20000, mortgage=40000, cashflow=1200)
    duo.act("A", "DRAW_CARD", cardId="mk-035")
    assert _prompted(duo) == []


def test_both_conditions_required(duo):
    """mk-025 要求 assetType=自建企业 **且** businessKind=小型机械公司，缺一不推。"""
    _give(duo, "B", kind="BUSINESS", id="biz-kind-only", asset_type="企业",
          business_kind="小型机械公司", name="别人家的小型机械公司", units=1,
          cost=60000, down_payment=20000, mortgage=40000, cashflow=1200)
    duo.act("A", "DRAW_CARD", cardId="mk-025")
    assert _prompted(duo) == []


def test_frozen_asset_gets_no_prompt(duo):
    """分期收款中的房子已不在市场上（design/06 §6.4），不该再被求购。"""
    a = _give(duo, "B", id="apt-frozen", asset_type="公寓", rooms=2, name="2室公寓 中山路",
              cost=60000, down_payment=6000, mortgage=54000, cashflow=450)
    duo.player("B").installment_receivables.append(InstallmentReceivable(
        id="r1", card_id="mk-029", name=a.name, asset_id=a.id,
        total_price=100000, monthly_delta=-500, duration_months=200))
    duo.act("A", "DRAW_CARD", cardId="mk-020")
    assert _prompted(duo) == []


def test_only_holders_prompted_one_per_asset(duo):
    """该推的一条不漏、不该推的一条不多：B 两套命中各一条，A 那套不同类零条。"""
    _give(duo, "B", id="apt-a", asset_type="公寓", rooms=2, name="2室公寓 学院路",
          cost=60000, down_payment=6000, mortgage=54000, cashflow=450)
    _give(duo, "B", id="apt-b", asset_type="公寓", rooms=4, name="4室公寓 江畔",
          cost=120000, down_payment=12000, mortgage=108000, cashflow=800)
    _give(duo, "A", id="h-a", asset_type="3室2厅", name="3室2厅",
          cost=65000, down_payment=6500, mortgage=58500, cashflow=380)

    duo.act("A", "DRAW_CARD", cardId="mk-020")
    assert len(_prompted(duo, "B")) == 2
    assert _prompted(duo, "A") == []
    assert {p.payload["asset_id"] for p in _prompted(duo, "B")} == {"apt-a", "apt-b"}
