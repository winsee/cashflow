"""棋盘排布数据的回归：快车道 48 格的顺序是实物核实过的，改错了要当场炸。"""
from __future__ import annotations

from ...data_loader import FT_SPECIAL_SQUARES


def test_ft_squares_是连续的_48_格(lib):
    assert len(lib.ft_squares) == 48


def test_ft_每个企业和梦想恰好占一格(lib):
    refs = lib.ft_squares
    for sid in [*lib.ft_businesses, *lib.ft_dreams]:
        assert refs.count(sid) == 1, f"{sid} 被引用 {refs.count(sid)} 次"
    assert len([r for r in refs if r.startswith("ft-b-")]) == 18
    assert len([r for r in refs if r.startswith("ft-d-")]) == 23


def test_ft_特殊格只认那五种(lib):
    specials = [r for r in lib.ft_squares if r.startswith("ft-s-")]
    assert set(specials) <= FT_SPECIAL_SQUARES
    # 实物核实：现金流量日 3 个（不是 design/05 v0.1 记的 4 个），其余各 1 个
    assert specials.count("ft-s-cashflow-day") == 3
    for one in ("ft-s-charity", "ft-s-tax-audit", "ft-s-divorce", "ft-s-lawsuit"):
        assert specials.count(one) == 1


def test_ft_入口格与内绕段的接缝(lib):
    # 「在此进入」箭头指向的第 1 格，和内绕段拐出去的接缝——排布一旦被整体旋转就会在这里露馅
    assert lib.ft_squares[0] == "ft-d-forest"
    assert lib.ft_squares[13] == "ft-b-goldmine"     # 第 14 格：内绕段末端
    assert lib.ft_squares[14] == "ft-d-fishing"      # 第 15 格：拐上外缘底边
    assert lib.ft_squares[47] == "ft-s-lawsuit"      # 第 48 格：接回第 1 格


def test_内圈仍是_24_格(lib):
    assert len(lib.rat_race_squares) == 24


def test_内圈构成与实物一致(lib):
    types = [s.type for s in lib.rat_race_squares]
    assert types.count("OPPORTUNITY") == 12
    for one in ("PAYDAY", "MARKET", "DOODAD"):
        assert types.count(one) == 3, one
    for one in ("CHARITY", "CHILD", "UNEMPLOYMENT"):
        assert types.count(one) == 1, one


def test_内圈起点附近的顺序(lib):
    # 顺序只能靠人对实物核（2026-08-08 已核）；这里钉住几个锚点，
    # 排布被整体旋转或错位一格会在这里露馅
    sq = lib.rat_race_squares
    assert sq[0].id == "rr-01" and sq[0].type == "OPPORTUNITY"
    assert sq[3].type == "CHARITY"          # 第 4 格：慈善事业
    assert sq[5].type == "PAYDAY"           # 第 6 格：第一个银行结算日
    assert sq[11].type == "CHILD"           # 第 12 格：孩子
    assert sq[19].type == "UNEMPLOYMENT"    # 第 20 格：失业
    assert sq[23].type == "MARKET"          # 第 24 格：接回第 1 格


def test_内圈显示名由_type_推出(lib):
    assert lib.rat_race_squares[5].name == "银行结算日"
