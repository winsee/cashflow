# 08 · 浏览器端 OCR 方案（云端扫描识别）

> 状态：**待开发**。可行性已用真实卡面实测验证（见 §2），架构与实现路径已定，
> 未写一行实现代码。本文是新会话的开发起点。

## 1. 为什么要做

服务端 PaddleOCR 在小内存云主机上跑不动，这是实测结论不是推测：

| 阶段 | 进程 RSS | cgroup 用量 |
| --- | --- | --- |
| 预热完成、还没识别 | 528 MB | 633 MB |
| 跑完 1 帧 | 665 MB | 783 MB |
| 跑完 2 帧 | 767 MB | 884 MB |

`docker run -m 512m` 模拟 Render Free：预热能过（cgroup 只记 291MB，模型文件页可回收），
**一跑真实识别就 `OOMKilled=true exit 137`**，容器直接死。手机端表现为扫描永远「未识别到」，
服务反复重启，无持久盘时房间存档一起清空。

因此镜像已改为默认不装 PaddleOCR（`WITH_OCR=0`，压缩 519MB → 62MB），云端扫描目前**不可用**，
识别接口返回 `unavailable`，手机端提示转手动检索。要在云端恢复扫描，只有把识别搬到手机上。

顺带一提：容器里一帧要 3.4s（Windows 原生 2.5s），Render Free 的共享 CPU 只会更慢——
就算内存够，8s 超时也悬。这条路没有调参空间。

## 2. 可行性验证（已完成，数据可信）

用 tesseract.js 7.0.0 识别 [build/cards_cropped/小生意/](../build/cards_cropped/) 下的实拍图，
输出直接喂给服务端现有的 [matcher.match_cards](../server/app/recognize/matcher.py)：

```
✓ sd-001 (869ms) → sd-001:1.00  sd-011:1.00  sd-044:0.90
✓ sd-002 (756ms) → sd-002:1.00  sd-005:0.89  sd-045:0.83
✓ sd-003 (585ms) → sd-003:1.00  sd-022:0.85  sd-040:0.85
✓ sd-006 (984ms) → sd-015:0.89  sd-031:0.89  sd-051:0.83   ← 同标题重复卡组
✓ sd-008 (864ms) → sd-008:1.00  sd-012:0.80  sd-020:0.80
✓ sd-011 (844ms) → sd-001:1.00  sd-011:1.00  sd-044:0.90
✓ sd-020 (699ms) → sd-020:1.00  sd-040:0.90  sd-008:0.86
✓ sd-044 (571ms) → sd-044:1.00  sd-022:0.90  sd-014:0.86
命中 8/8
```

识别原文样例：`优先股一一2BIG电力公司国内占主导地位的电力公司的高投资收益率优先股。国家公用…`
——破折号被认成「一一」，但 matcher 的模糊匹配根本不在乎。**股票代码（2BIG / MYT4U / ON2U /
OK4U）用 `chi_sim` 单语言包就能认出来**，不需要额外加载 `eng`（省 4MB 和一次加载）。

关键判断：这是**封闭集匹配**，不是通用 OCR。只要认出标题的一部分字和几个数字，
matcher 的 `0.6×标题相似 + 0.3×数字命中 + 0.1×代码命中` 就足以定位到具体是哪张卡。
对 OCR 质量的要求比"准确转录卡面"低一个量级。

三个决定性数字：

| | 浏览器 tesseract.js | 服务端 PaddleOCR（容器内） |
| --- | --- | --- |
| 单帧耗时 | 0.6–1.0s | 3.4s |
| 服务端内存开销 | 0（只做字符串打分） | 767MB，512MB 下 OOM |
| 首次下载 | wasm 2.7MB + 中文包 2.4MB | — |

### ⚠️ 验证的边界（别把结论放大）

上面测的是 `build/cards_cropped/` 里**裁剪好的正面图**，不是手机随手拍的取景帧。
真实场景有透视、抖动模糊、反光、部分遮挡，命中率一定会降。**开发第一步就是把
真机取景帧的命中率测出来**（见 §6），不要跳过。

## 3. 方案

```
手机浏览器                                        服务端
┌──────────────────────────┐              ┌─────────────────────┐
│ getUserMedia 取景         │              │                     │
│   ↓ 裁扫描框区域          │              │                     │
│ tesseract.js (WASM)      │  文本(JSON)  │ match_cards 打分     │
│   ↓ 文本                 │ ───────────> │   ↓                 │
│ 显示 Top-3 候选，玩家点选 │ <─────────── │ Top-3 候选 + reason  │
└──────────────────────────┘              └─────────────────────┘
                                           零 OCR 内存开销
```

### 3.1 服务端：新增 `POST /api/rooms/{code}/recognize-text`

写在 [server/app/main.py](../server/app/main.py) 现有 `recognize` 端点（约 181 行）旁边，
照它的形状写，约 30 行：

```python
class RecognizeTextBody(BaseModel):
    text: str = Field(max_length=4000)      # 限长：公网端点，别让人塞大文本
    deckHint: str | None = None
    clientMs: int = 0                        # 手机端 OCR 耗时，进统计

@app.post("/api/rooms/{code}/recognize-text")
async def recognize_text(code: str, body: RecognizeTextBody):
    ...
    cards = lib.by_deck(body.deckHint) if body.deckHint else list(lib.cards.values())
    matches = match_cards(body.text, cards)
    # engine="browser"，复用 add_recog_stat → /api/stats/recognition 能直接对比
    # browser 与 local 两条引擎的 Top-3 命中率（FR-28）
```

- `reason` 沿用 [RecognizeOutcome](../server/app/recognize/base.py) 的取值：有候选 `ok`、
  文本非空但没匹配上 `no_match`、文本为空 `no_text`。这条路不会有 `timeout` / `unavailable`
- `recognitionId` 照旧返回，前端确认选卡后仍打 `/api/recognize/{id}/chosen`（FR-28 命中率统计）
- **纯字符串计算，不引任何新依赖**，服务端内存开销可以忽略

### 3.2 前端：[web/src/components/CardPicker.vue](../web/src/components/CardPicker.vue)

现在的 `scanLoop` 是「抓帧 → POST 图片 → 等服务端」，改成「抓帧 → 裁剪 → 本地 OCR → POST 文本」。

- **动态 import**：`const { createWorker } = await import('tesseract.js')`，不点扫描不下载
- **worker 复用**：`createWorker('chi_sim', ...)` 只建一次，多帧复用，`onBeforeUnmount` 里
  `terminate()`。每帧新建 worker 会重复加载 2.4MB 模型，必卡死
- **裁剪扫描框区域再 OCR**：`.scan-frame` 是 `inset: 12% 18%`（见组件 style），按同样比例从
  canvas 裁出来。整帧送进去会把桌面、其他卡的文字一起认进来，拉低匹配分
- **串行**：一帧识别没完不抓下一帧。本地 OCR 后不再需要原来那个 1200ms 的服务器保护间隔，
  但手机发热/耗电要控，建议识别完直接下一帧、不额外 sleep
- **首次提示**：第一次点扫描要下 ~5MB，给一句「首次使用需下载识别模型（约 5MB）」，
  别让人以为卡死了
- **降级链**：浏览器 OCR 不可用（WASM 加载失败/旧机型）→ 回落现有 `/recognize`
  （服务端，`WITH_OCR=1` 的局域网部署才有）→ 手动检索。现有的 reason 分支文案和
  「硬失败连续 3 次停扫」逻辑照旧复用

### 3.3 资源自托管（离线要求，不能漏）

项目要求局域网/离线可用，**不能依赖 jsDelivr CDN**。三个文件放进 `web/public/tesseract/`
（vite 会原样拷进 `dist/`，随镜像交付）：

| 文件 | 体积 | 来源 |
| --- | --- | --- |
| `worker.min.js` | 0.1 MB | `node_modules/tesseract.js/dist/` |
| `tesseract-core-simd-lstm.wasm` | 2.7 MB | `node_modules/tesseract.js-core/` |
| `chi_sim.traineddata.gz` | ~1.9 MB | tessdata_fast |

`createWorker` 里显式指定 `workerPath` / `corePath` / `langPath` 指向 `/tesseract/`。
traineddata 会被 tesseract.js 自动缓存进 IndexedDB，只下一次。

注意：`web/public/` 现在只有 `manifest.webmanifest`，项目**有 PWA manifest 但没有
service worker**（`package.json` 里没有 vite-plugin-pwa）。所以这几个文件靠浏览器 HTTP 缓存，
没有离线预缓存机制——这不影响功能，但别在文档里宣称"PWA 离线可用"。

## 4. 明确不做

- **不动服务端 PaddleOCR**：[local_ocr.py](../server/app/recognize/local_ocr.py) 与
  `WITH_OCR=1` 构建原样保留，内存充裕的局域网部署仍走它（更准）。两条引擎并存，
  靠 `/api/stats/recognition` 的 engine 维度对比效果
- **不改卡库、不改 matcher 的评分公式**（阈值可调，见 §5）
- **不做云端 OCR API**（design/03 §8 里预留的 CloudRecognizer 继续留空）
- **不改任何记账逻辑**：识别只用来定位"是哪张卡"，数值一律取自卡库，玩家点选确认才入账

## 5. 已知风险与需要现场判断的点

1. **真机取景帧质量**（最大不确定性）。缓解顺序：裁剪扫描框 → 若仍不够，加连续两帧
   同一候选才提升置信 → 若还不够，考虑上采样/灰度化预处理
2. **`CONFIDENCE_FLOOR = 0.55` 可能需要重新标定**（[matcher.py:34](../server/app/recognize/matcher.py#L34)）。
   浏览器 OCR 的错字率高于 PaddleOCR，阈值可能要降。**但不要为了提高命中率降到很低**——
   误配一张卡比没认出来更糟，玩家可能不核对就点了
3. **同名多版本卡靠数字区分**，数字认错一位会选错版本。服务端方案有同样风险，
   靠 Top-3 候选 + 玩家确认兜底，别做成自动入账
4. **老机型可能 2–3s/帧**。识别期间要有明确的进行中反馈，且手动检索入口全程可用
5. **卡面反光**是实体卡的老问题，扫描框提示语可以引导玩家避开顶灯

## 6. 验收标准

按顺序做，前两条不过就别往下写 UI：

1. **离线命中率脚本**（先做这个，最便宜的证伪）：对 `build/cards_cropped/` 下全部 194 张
   实拍图跑 tesseract → matcher，报告 Top-1 / Top-3 命中率。**Top-3 ≥ 90% 才继续**。
   ground truth：裁剪图编号与卡 id 同序（`小生意/1.jpg` ↔ `sd-001`，已验证）；
   同标题重复卡组按标题判命中
2. **真机取景帧**：手机对着实体卡扫，至少 10 张不同卡，Top-3 命中 ≥ 80%。
   这一步的数字才是真的，裁剪图的 8/8 只是上限
3. **服务端单测**（写进 [server/tests/test_m3.py](../server/tests/test_m3.py)）：
   `recognize-text` 返回候选与 reason、写入 recog_stat（engine=browser）、
   空文本 → `no_text`、无关文本 → `no_match`、超长文本被拒
4. **回归**：`server\.venv\Scripts\python.exe -m pytest` 保持 405 passed / 1 skipped 不掉
5. **端到端**：云端（Render Free，62MB 精简镜像）扫一张卡能入账，
   `/api/health` 的 `memory.rssMb` 全程无明显增长

## 7. 开工前的上下文

- **代码位置**：分支 `fix/cloud-ocr-diagnostics`（2 个 commit，尚未合并 main）。
  它包含了本方案要复用的 reason 机制和诊断端点
- **诊断工具**（排障时用，本方案不依赖）：
  `GET /api/health`、`POST /api/health/ocr-probe`，用法见 [README](../README.md)「扫描识别排障」
- **实测环境**：开发机 Windows 11 + `server\.venv`（Python 3.12，装了 paddleocr 可作对照基准）；
  tesseract.js 验证时装在临时目录，仓库里没有留下 spike 代码，需要重跑就照 §2 重写（15 行）
- **相关设计**：[design/04 §4](04-卡牌数据模型与识别方案.md) 的识别管线一节仍然有效
  （封闭集匹配的原始设计），卡牌数据部分已被 [design/06](06-卡牌数字化结果与设计修订.md) 取代
