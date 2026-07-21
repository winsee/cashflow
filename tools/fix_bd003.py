# -*- coding: utf-8 -*-
"""修回归 bug：bd-003 的 targetAssetType 在「8室公寓→公寓+rooms」改名时被漏掉。

改名后全库已无「8室公寓」这个 assetType，bd-003 永远匹配不上，卡失效。
改为 targetAssetType=公寓 + targetRooms=8。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "server" / "data" / "cards"
p = CARDS / "big_deal.json"

cards = json.loads(p.read_text(encoding="utf-8"))
for c in cards:
    if c["id"] == "bd-003":
        d = c["data"]
        assert d["targetAssetType"] == "8室公寓", d
        d["targetAssetType"] = "公寓"
        d["targetRooms"] = 8
        print(f"bd-003 → targetAssetType=公寓, targetRooms=8")
p.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
