# -*- coding: utf-8 -*-
"""统一选卡列表的 title 显示规则（2026-07-22，与房主讨论定案）。

背景：`title` 字段本是编者为区分同 raw.title 卡手工拟定的显示名，历史上格式很不
统一——有时写成本、有时写现金流、有时写卡面场景词（"低利率""离婚""急需现金"…），
同一分组内混用，容易让人以为是同一张卡（如 sd-002/sd-005 都是「待售公寓——2室1厅」
成本都是 $40,000，但只有一张标题里带了现金流）。

讨论结论：title 一律等于 raw.title，不再加括号消歧；区分职责完全交给选卡列表下方
的小字（web/src/cardinfo.ts 的 keyNumbers()，已同步改造为按 subtype 补全必要字段，
包括之前只活在标题括号里、raw.title 又没提到的真实信息——资产类型/企业细分类型/
目标资产/限定条件等）。

副作用之一：像"股票——MYT4U电子公司"这类价格相同、连分红/收益率都相同的两张卡，
去括号后标题和小字会完全一样——这是有意为之：两张卡数值上就是等价的，选哪张结算
结果都相同，场景词（"低利率"）本身不携带任何影响结算的信息。

同时给 7 张之前没有 businessKind 的企业卡补上具体细分类型（原先只活在 title 括号
里的"投币电话厂""旧车出租"这类描述），使其归口到 schema 里"企业细分类型"这个已有
字段，而不是塞进受市场卡匹配用的 assetType（那是受控词表，一组企业共享同一个值，
改了会破坏 mk-025/mk-033/mk-035 的匹配逻辑）。

用法：python tools/normalize_card_titles.py [--dry-run]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "server" / "data" / "cards"
FILES = ["small_deal.json", "big_deal.json", "market.json", "doodad.json", "professions.json"]

dry = "--dry-run" in sys.argv

# 之前只体现在 title 括号里的企业细分类型，回填到 businessKind（不影响任何现有匹配，
# 只是让这几张卡的数据和其它已有 businessKind 的卡一样完整）
BUSINESS_KIND_BACKFILL = {
    "bd-004": "录像机和弹子球机",
    "bd-007": "旧车出租",
    "bd-010": "投币电话厂",
    "bd-016": "自动洗衣店",
    "bd-022": "医生诊所",
    "bd-030": "比萨饼连锁店",
    "bd-034": "三明治商店",
}


def process(fname: str) -> tuple[list[str], list[str]]:
    path = CARDS / fname
    data = json.loads(path.read_text(encoding="utf-8"))
    title_changes = []
    kind_changes = []

    for c in data:
        old_title = c["title"]
        new_title = c["raw"]["title"]
        if new_title != old_title:
            title_changes.append(f"{c['id']}: 『{old_title}』 → 『{new_title}』")
            c["title"] = new_title

        if c["id"] in BUSINESS_KIND_BACKFILL:
            kind = BUSINESS_KIND_BACKFILL[c["id"]]
            if c["data"].get("businessKind") != kind:
                kind_changes.append(f"{c['id']}: businessKind → 「{kind}」")
                c["data"]["businessKind"] = kind

    if (title_changes or kind_changes) and not dry:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return title_changes, kind_changes


def main() -> int:
    print(f"{'预演' if dry else '执行'}：title 统一为 raw.title + businessKind 补全\n")
    total_title = total_kind = 0
    for fname in FILES:
        title_changes, kind_changes = process(fname)
        if title_changes or kind_changes:
            print(f"== {fname}（title {len(title_changes)} 处，businessKind {len(kind_changes)} 处）==")
            for line in title_changes:
                print("  [title]", line)
            for line in kind_changes:
                print("  [kind] ", line)
        total_title += len(title_changes)
        total_kind += len(kind_changes)
    print(f"\n合计：title {total_title} 处，businessKind {total_kind} 处")
    if dry:
        print("（预演，未写入。去掉 --dry-run 执行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
