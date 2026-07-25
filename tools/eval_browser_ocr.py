"""浏览器端 OCR 的离线命中率评估（design/08 §6.1）。

输入是 `web/scripts/ocr-bench.mjs` 跑出来的识别文本（build/ocr_bench/texts.json），
输出 Top-1 / Top-3 命中率 —— 打分用的是服务端**同一个** matcher，所以这里的数字
就是真实链路的上限（真机取景帧只会更差，见 §6.2）。

ground truth 取自卡库里每张卡的 `source.image`，不靠"编号同序"的约定。

两套口径都报：
- **严格**：命中的必须是这张卡本身，或与它 `key` 相同的重复卡（重复卡内容完全一样，
  选哪张都不影响记账）
- **同标题**：Top-3 里有同标题的卡就算命中（§6.1 的验收口径）。同标题≠同一张卡：
  「待售居室——3室2厅」有 50000 / 65000 / 零首付三个版本，靠数字区分，
  两个数字差得越远越说明严格口径才是该看的那个

用法（必须用 server 的 venv，要 jsonschema/rapidfuzz）：
    server\\.venv\\Scripts\\python.exe tools/eval_browser_ocr.py
    server\\.venv\\Scripts\\python.exe tools/eval_browser_ocr.py --floor 0.45 --misses
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app.data_loader import load_library  # noqa: E402
from app.recognize.matcher import CONFIDENCE_FLOOR, match_cards  # noqa: E402


def truth_from_json() -> dict[str, str]:
    """`小生意/1.jpg` → card_id。Card dataclass 没保留 source，直接读 JSON 文件。"""
    out: dict[str, str] = {}
    for f in sorted((ROOT / "server" / "data" / "cards").glob("*.json")):
        for c in json.loads(f.read_text(encoding="utf-8")):
            img = (c.get("source") or {}).get("image")
            if img:
                out["/".join(Path(img).parts[-2:])] = c["id"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts", default="build/ocr_bench/texts.json")
    ap.add_argument("--floor", type=float, default=CONFIDENCE_FLOOR)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--no-deck-hint", action="store_true",
                    help="不按牌堆过滤（全库 194 张里选），比真实链路难")
    ap.add_argument("--misses", action="store_true", help="逐条列出没命中的卡")
    args = ap.parse_args()

    payload = json.loads((ROOT / args.texts).read_text(encoding="utf-8"))
    texts = payload["results"] if "results" in payload else payload
    lib = load_library()
    img2id = truth_from_json()

    by_deck: dict[str, list[tuple[bool, bool, bool, bool]]] = defaultdict(list)
    reasons: dict[str, int] = defaultdict(int)
    misses: list[str] = []

    for img, rec in texts.items():
        card_id = img2id.get(img)
        if card_id is None:
            print(f"! 找不到 ground truth: {img}")
            continue
        truth = lib.cards[card_id]
        text = rec["text"] if isinstance(rec, dict) else rec
        pool = list(lib.cards.values()) if args.no_deck_hint else lib.by_deck(truth.deck)
        cands = match_cards(text, pool, top=args.top, floor=args.floor)

        same = {c.id for c in lib.cards.values() if c.key and c.key == truth.key}
        same.add(truth.id)
        strict3 = any(m.card_id in same for m in cands)
        strict1 = bool(cands) and cands[0].card_id in same
        title3 = any(lib.cards[m.card_id].title == truth.title for m in cands)
        title1 = bool(cands) and lib.cards[cands[0].card_id].title == truth.title
        by_deck[truth.deck].append((strict1, strict3, title1, title3))

        if not cands:
            reasons["no_text" if not text.strip() else "no_match"] += 1
        else:
            reasons["ok"] += 1
        if not strict3 and args.misses:
            top = ", ".join(f"{m.card_id}:{m.score:.2f}" for m in cands) or "无候选"
            tag = "同标题命中" if title3 else "完全没中"
            misses.append(f"  [{tag}] {img} {truth.id} 《{truth.title}》 → {top}\n"
                          f"      OCR: {text.strip()[:70].replace(chr(10), ' ')}")

    print(f"\n阈值 floor={args.floor}  牌堆提示={'关' if args.no_deck_hint else '开'}  "
          f"样本={sum(len(v) for v in by_deck.values())}")
    print(f"{'牌堆':<12}{'张数':>5}{'严格Top1':>10}{'严格Top3':>10}"
          f"{'同标题Top1':>12}{'同标题Top3':>12}")
    tot = [0, 0, 0, 0]
    n = 0
    for deck, rows in sorted(by_deck.items()):
        cols = [sum(r[i] for r in rows) for i in range(4)]
        n += len(rows)
        tot = [tot[i] + cols[i] for i in range(4)]
        print(f"{deck:<12}{len(rows):>5}" + "".join(
            f"{c / len(rows):>9.1%}" + " " * (1 if i < 2 else 3)
            for i, c in enumerate(cols)))
    print(f"{'合计':<12}{n:>5}" + "".join(
        f"{c / n:>9.1%}" + " " * (1 if i < 2 else 3) for i, c in enumerate(tot)))
    print(f"\nreason 分布: " + "  ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
    if "msMedian" in payload:
        print(f"OCR 耗时: 中位 {payload['msMedian']}ms  最慢 {payload['msMax']}ms")

    gate = tot[3] / n
    print(f"\n验收①（同标题 Top-3 ≥ 90%）：{gate:.1%} → {'通过' if gate >= 0.9 else '不通过'}")
    if misses:
        print(f"\n严格口径未命中 {len(misses)} 张（标了「同标题命中」的是选错版本的风险）：")
        print("\n".join(misses))
    return 0 if gate >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
