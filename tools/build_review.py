# -*- coding: utf-8 -*-
"""生成人工核对页：左边实体卡照片，右边数字资产，逐张比对。

用法：python tools/build_review.py  →  build/review/index.html（双击打开）

核对进度记在浏览器 localStorage，可分次做完；导出按钮生成 review-result.json，
标了"有误"的卡连同备注一起导出，据此回改 server/data/cards/*.json。
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "server" / "data" / "cards"
CROPS = ROOT / "build" / "cards_cropped"
OUT = ROOT / "build" / "review"

DECKS = [
    ("小生意", "small_deal.json"),
    ("大买卖", "big_deal.json"),
    ("市场风云", "market.json"),
    ("额外支出", "doodad.json"),
    ("职业卡", "professions.json"),
]


def esc(s) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def render_raw(raw: dict) -> str:
    """把 raw 还原成接近卡面的排版，便于逐字比对。"""
    h = [f'<div class="rt">{esc(raw["title"])}</div>']
    if raw.get("subtitle"):
        h.append(f'<div class="rs">{esc(raw["subtitle"])}</div>')
    for p in raw.get("body", []):
        h.append(f'<p class="rb">{esc(p)}</p>')
    if raw.get("fields"):
        h.append('<div class="rf">')
        for f in raw["fields"]:
            v = f' <b>{esc(f["value"])}</b>' if f["value"] else ""
            h.append(f'<div><span>{esc(f["label"])}</span>{v}</div>')
        h.append("</div>")
    for g in raw.get("groups", []):
        h.append(f'<div class="rg"><div class="rgn">{esc(g["name"])}</div>')
        for r in g["rows"]:
            h.append(f'<div class="rgr"><span>{esc(r["label"])}</span><b>{esc(r["value"])}</b></div>')
        h.append("</div>")
    for n in raw.get("notes", []):
        h.append(f'<p class="rn">{esc(n)}</p>')
    return "\n".join(h)


def render_card(c: dict, deck_dir: str) -> str:
    img = f'img/{deck_dir}/{c["source"]["sheetNo"]}.jpg'
    data = json.dumps(c["data"], ensure_ascii=False, indent=2)
    badges = [f'<span class="b">{esc(c["subtype"])}</span>']
    if c.get("duplicateOf"):
        badges.append(f'<span class="b dup">与 {esc(c["duplicateOf"])} 相同</span>')
    return f"""
<section class="card" id="{esc(c['id'])}" data-deck="{esc(deck_dir)}">
  <header>
    <span class="id">{esc(c['id'])}</span>
    <span class="t">{esc(c['title'])}</span>
    {' '.join(badges)}
    <span class="mark" data-id="{esc(c['id'])}">
      <button class="ok"  title="核对无误">✓ 无误</button>
      <button class="bad" title="有出入">✗ 有误</button>
      <input class="note" placeholder="备注（哪个字段不对）">
    </span>
  </header>
  <div class="body">
    <div class="left"><img loading="lazy" src="{img}" alt="{esc(c['id'])}"></div>
    <div class="right">
      <div class="pane">
        <h4>卡面原文 raw <em>（逐字核对）</em></h4>
        <div class="rawbox">{render_raw(c['raw'])}</div>
      </div>
      <div class="pane">
        <h4>结构化数值 data <em>（引擎取数）</em></h4>
        <pre>{esc(data)}</pre>
      </div>
    </div>
  </div>
</section>"""


CSS = """
*{box-sizing:border-box}
body{margin:0;font:14px/1.6 system-ui,"Microsoft YaHei",sans-serif;background:#f4f4f6;color:#1a1a1a}
#top{position:sticky;top:0;z-index:9;background:#fff;border-bottom:1px solid #d8d8de;
     padding:10px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;
     box-shadow:0 1px 4px rgba(0,0,0,.06)}
#top h1{font-size:16px;margin:0 8px 0 0}
#top button.f{border:1px solid #c8c8d0;background:#fff;border-radius:6px;padding:5px 12px;cursor:pointer}
#top button.f.on{background:#2d5bd7;color:#fff;border-color:#2d5bd7}
#stat{margin-left:auto;font-variant-numeric:tabular-nums;color:#555}
#stat b{color:#111}
.card{background:#fff;margin:14px;border-radius:10px;border:1px solid #e0e0e6;overflow:hidden}
.card.done{border-color:#3a9a52}
.card.err{border-color:#cc3a3a;background:#fffafa}
.card>header{display:flex;gap:10px;align-items:center;padding:9px 14px;
             background:#fafafc;border-bottom:1px solid #ececf0;flex-wrap:wrap}
.id{font-family:ui-monospace,Consolas,monospace;color:#666;font-size:13px}
.t{font-weight:600}
.b{font-size:11px;background:#e8ecf8;color:#3352a8;border-radius:4px;padding:2px 7px}
.b.dup{background:#f6ecd8;color:#8a6414}
.mark{margin-left:auto;display:flex;gap:6px;align-items:center}
.mark button{border:1px solid #c8c8d0;background:#fff;border-radius:6px;padding:4px 10px;cursor:pointer}
.mark button.ok.on{background:#3a9a52;color:#fff;border-color:#3a9a52}
.mark button.bad.on{background:#cc3a3a;color:#fff;border-color:#cc3a3a}
.mark .note{border:1px solid #d5d5dd;border-radius:6px;padding:4px 8px;width:230px;display:none}
.card.err .note{display:block}
.body{display:grid;grid-template-columns:minmax(320px,1fr) minmax(340px,1fr);gap:14px;padding:14px}
.left img{width:100%;border-radius:8px;border:1px solid #e4e4ea;background:#fff}
.right{display:flex;flex-direction:column;gap:12px;min-width:0}
.pane h4{margin:0 0 6px;font-size:12px;color:#666;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.pane h4 em{font-style:normal;text-transform:none;letter-spacing:0;color:#999;font-weight:400}
.rawbox{border:1px solid #e4e4ea;border-radius:8px;padding:12px 14px;background:#fcfcfd}
.rt{font-size:17px;font-weight:700;text-align:center;margin-bottom:2px}
.rs{text-align:center;color:#777;font-size:12px;margin-bottom:6px}
.rb{margin:6px 0;text-indent:2em}
.rf{margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:3px 16px;
    border-top:1px dashed #ddd;padding-top:8px}
.rf span{color:#666}
.rg{margin-top:8px;border-top:1px dashed #ddd;padding-top:6px}
.rgn{font-weight:600;color:#444;margin-bottom:3px}
.rgr{display:flex;justify-content:space-between;gap:12px;padding:1px 0}
.rgr span{color:#666}
.rn{color:#888;font-size:12px;margin:6px 0 0}
pre{margin:0;background:#1e1e26;color:#dcdce4;border-radius:8px;padding:12px;
    overflow-x:auto;font:12px/1.55 ui-monospace,Consolas,monospace}
@media(max-width:980px){.body{grid-template-columns:1fr}}
"""

JS = """
const K='cf-review-v1';
const S=JSON.parse(localStorage.getItem(K)||'{}');
function paint(){
  let ok=0,bad=0;
  document.querySelectorAll('.card').forEach(c=>{
    const s=S[c.id]||{};
    c.classList.toggle('done',s.v==='ok');
    c.classList.toggle('err',s.v==='bad');
    c.querySelector('.ok').classList.toggle('on',s.v==='ok');
    c.querySelector('.bad').classList.toggle('on',s.v==='bad');
    c.querySelector('.note').value=s.note||'';
    if(s.v==='ok')ok++; if(s.v==='bad')bad++;
  });
  const n=document.querySelectorAll('.card').length;
  stat.innerHTML=`已核对 <b>${ok+bad}</b>/${n} · 无误 <b>${ok}</b> · 有误 <b>${bad}</b> · 未核对 <b>${n-ok-bad}</b>`;
}
function save(){localStorage.setItem(K,JSON.stringify(S));paint()}
document.addEventListener('click',e=>{
  const b=e.target.closest('.mark button'); if(!b)return;
  const id=b.closest('.mark').dataset.id, v=b.classList.contains('ok')?'ok':'bad';
  S[id]=S[id]||{}; S[id].v = S[id].v===v ? null : v; save();
  if(S[id].v==='bad') b.closest('.card').querySelector('.note').focus();
});
document.addEventListener('input',e=>{
  if(!e.target.classList.contains('note'))return;
  const id=e.target.closest('.mark').dataset.id;
  S[id]=S[id]||{}; S[id].note=e.target.value;
  localStorage.setItem(K,JSON.stringify(S));
});
document.querySelectorAll('#top button.f').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('#top button.f').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  const d=b.dataset.deck;
  document.querySelectorAll('.card').forEach(c=>{
    c.style.display = (!d||c.dataset.deck===d) ? '' : 'none';
  });
});
document.getElementById('hideOk').onclick=function(){
  this.classList.toggle('on');
  const h=this.classList.contains('on');
  document.querySelectorAll('.card.done').forEach(c=>c.style.display=h?'none':'');
};
document.getElementById('exp').onclick=()=>{
  const rows=Object.entries(S).filter(([,v])=>v&&v.v).map(([id,v])=>({id,verdict:v.v,note:v.note||''}));
  const blob=new Blob([JSON.stringify({checkedAt:new Date().toISOString(),rows},null,2)],
                      {type:'application/json'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download='review-result.json'; a.click();
};
paint();
"""


def main() -> int:
    if not CROPS.is_dir():
        print("请先运行 python tools/crop_cards.py 生成裁剪图")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "img").exists():
        shutil.rmtree(OUT / "img")
    shutil.copytree(CROPS, OUT / "img")

    sections, tabs, total = [], ['<button class="f on">全部</button>'], 0
    for deck_dir, fname in DECKS:
        cards = json.loads((CARDS / fname).read_text(encoding="utf-8"))
        total += len(cards)
        tabs.append(f'<button class="f" data-deck="{deck_dir}">{deck_dir} {len(cards)}</button>')
        sections += [render_card(c, deck_dir) for c in cards]

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>卡牌数字资产人工核对（{total} 张）</title><style>{CSS}</style></head>
<body>
<div id="top">
  <h1>卡牌核对</h1>
  {' '.join(tabs)}
  <button class="f" id="hideOk">隐藏已核对</button>
  <button class="f" id="exp">导出结果</button>
  <span id="stat"></span>
</div>
{''.join(sections)}
<script>{JS}</script>
</body></html>"""
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"已生成 {OUT / 'index.html'}（{total} 张）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
