# 08 · 浏览器端 OCR（云端扫描识别）

> 状态：**已实现**（2026-07-25）。离线验收已过（§6.1：194 张实拍图，严格 Top-3 97.9%），
> 真实浏览器冒烟已过（§6.3）。**剩真机取景帧与云端端到端两项要人在现场做**（§6.2、§6.5）。

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

因此镜像已改为默认不装 PaddleOCR（`WITH_OCR=0`，压缩 519MB → 62MB）。要在云端恢复扫描，
只有把识别搬到手机上。

顺带一提：容器里一帧要 3.4s（Windows 原生 2.5s），Render Free 的共享 CPU 只会更慢——
就算内存够，8s 超时也悬。这条路没有调参空间。

## 2. 可行性验证（开发前做的预研）

用 tesseract.js 识别 [build/cards_cropped/小生意/](../build/cards_cropped/) 下 8 张实拍图，
输出喂给服务端现有的 [matcher.match_cards](../server/app/recognize/matcher.py)，8/8 命中。

识别原文样例：`优先股一一2BIG电力公司国内占主导地位的电力公司的高投资收益率优先股。国家公用…`
——破折号被认成「一一」，但 matcher 的模糊匹配根本不在乎。**股票代码（2BIG / MYT4U / ON2U /
OK4U）用 `chi_sim` 单语言包就能认出来**，不需要额外加载 `eng`。

关键判断：这是**封闭集匹配**，不是通用 OCR。只要认出标题的一部分字和几个数字，
matcher 的 `0.6×标题相似 + 0.3×数字命中 + 0.1×代码命中` 就足以定位到具体是哪张卡。
对 OCR 质量的要求比"准确转录卡面"低一个量级。

正式开发时把这 8 张扩到了全部 194 张，结论见 §6.1。

## 3. 实现

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

### 3.1 服务端：`POST /api/rooms/{code}/recognize-text`

[main.py](../server/app/main.py) 里 `recognize` 端点旁边，纯字符串计算，不引任何新依赖：

- 请求 `{text (≤4000), deckHint?, clientMs}`，响应与 `/recognize` **形状完全一致**
  （`candidates` / `engine` / `reason` / `recognitionId` / `durationMs`），前端两条路共用一套渲染
- `reason` 沿用 [RecognizeOutcome](../server/app/recognize/base.py) 的取值：`ok` / `no_match` /
  `no_text`。这条路不会有 `timeout` / `unavailable`——识别已经在手机上跑完了
- `engine="browser"` 进 `add_recog_stat`，`durationMs` 记的是**手机端 OCR 耗时**，
  `/api/stats/recognition` 上才能和服务端引擎横向比（FR-28）
- 玩家确认选卡后照旧打 `/api/recognize/{id}/chosen`

### 3.2 前端

[web/src/ocr.ts](../web/src/ocr.ts)（新增）封装 worker 生命周期与取景帧裁剪，
[CardPicker.vue](../web/src/components/CardPicker.vue) 只管流程：

- **动态 import**：`await import('tesseract.js')`，不点扫描不下载（构建产物里是独立的
  15.8KB chunk，主包只留路径字符串）
- **worker 复用**：整个组件生命周期只建一次，`onBeforeUnmount` 里 `terminate()`。
  每帧新建会重复加载 1.7MB 语言包
- **裁剪扫描框区域再 OCR**：整帧送进去会把桌面、旁边的卡一起认进来，拉低匹配分。
  video 是 `object-fit: cover`，得先按 cover 还原出「可见区」再按 inset 取框，
  直接对 `videoWidth` 取百分比会框偏。`.scan-frame` 的 inset 与 `SCAN_INSET` 必须同步改
- **串行**：一帧没识别完不抓下一帧。认出候选后停 800ms 让玩家看清（顺带省电），
  没认出立刻扫下一帧；走服务端识别时保留原来的 1.2s 保护间隔
- **进行中反馈**：实测一帧 1~3s，扫描框上的状态行带一个脉冲小圆点，
  否则玩家会以为卡死了、一直挪卡反而更认不出
- **首次提示**：第一次点扫描要下 ~5MB，状态行显示「首次使用需下载识别模型（约 5MB）」；
  下载与「请求摄像头权限」并行发起
- **降级链**：浏览器 OCR（WASM 起不来就一次性标记不可用）→ 服务端 `/recognize`
  （`WITH_OCR=1` 的局域网部署才有）→ 手动检索。原有的 reason 文案与「硬失败连续 3 次停扫」
  逻辑照旧复用
- **拍照兜底也走本机识别**：非安全上下文（http 局域网）没有 `getUserMedia`，但浏览器 OCR
  照常能跑，拍照这条路因此也能识别，不再只能手动检索

### 3.3 资源自托管（离线要求）

项目要求局域网/离线可用，**不能依赖 jsDelivr CDN**。
[web/scripts/sync-tesseract-assets.mjs](../web/scripts/sync-tesseract-assets.mjs) 在
`npm run build`/`dev` 前（`prebuild`/`predev` 钩子）从 node_modules 拷进 `web/public/tesseract/`，
vite 原样打进 `dist/`，随镜像交付：

| 文件 | 体积 | 说明 |
| --- | --- | --- |
| `worker.min.js` | 0.1 MB | tesseract.js/dist |
| `tesseract-core-relaxedsimd-lstm.wasm.js` | 3.9 MB | 浏览器按 SIMD 支持三选一，**只下一个** |
| `tesseract-core-simd-lstm.wasm.js` | 3.9 MB | 同上（wasm 以 base64 内嵌，所以比 .wasm 大 36%） |
| `tesseract-core-lstm.wasm.js` | 3.9 MB | 同上，给 2021 年前的老机型（iOS 15 等无 SIMD） |
| `chi_sim.traineddata.gz` | 1.7 MB | `@tesseract.js-data/chi_sim` 的 `4.0.0_best_int`，**别换成同目录 20MB 的 `4.0.0`** |

合计 12.9MB 进镜像，手机首次下载约 5.6MB（一个 core + 语言包），之后走 HTTP 缓存 /
IndexedDB（traineddata 由 tesseract.js 自动缓存）。**这几个文件不进 git**（.gitignore），
构建时从 node_modules 生成。

注意：项目**有 PWA manifest 但没有 service worker**，所以这几个文件靠浏览器 HTTP 缓存，
没有离线预缓存机制——不影响功能，但别宣称"PWA 离线可用"。

### 3.4 顺带修掉的两个 matcher 缺陷

不是"改评分公式"（权重没动），是 `normalize` 与数字命中判定的 bug，两条识别路线通吃。
没有它们，同标题不同价的卡（大买卖里成堆）只能靠标题瞎猜：

1. **千分位只认了逗号**。实拍卡面 OCR 出来的 `220,000` 有七八种形态，最常见的恰恰是
   `220, 000`（逗号后带空格，194 张里 140 处），还有 `220 000`、`220.000`。
   结果是"成本/首付/贷款"这些关键数字**一个都对不上**。
   → 大买卖严格 Top-3 71.4% → 100%
2. **数字用子串判命中**：`2,000` 会命中在 `220,000` 里，一张写着 $2,000 的
   《下水管破裂》就靠这个在一段全是 $220,000 的文本上拿到 1.00 分，把正主挤到第二。
   → 改成"前后不许再挨着数字"，大买卖严格 Top-1 90.5% → 100%

## 4. 明确不做

- **不动服务端 PaddleOCR**：[local_ocr.py](../server/app/recognize/local_ocr.py) 与
  `WITH_OCR=1` 构建原样保留，内存充裕的局域网部署仍可走它。两条引擎并存，
  靠 `/api/stats/recognition` 的 engine 维度对比效果
- **不改卡库、不改 matcher 的评分权重**（§3.4 修的是命中判定的 bug，不是权重）
- **不做云端 OCR API**（design/03 §8 里预留的 CloudRecognizer 继续留空）
- **不改任何记账逻辑**：识别只用来定位"是哪张卡"，数值一律取自卡库，玩家点选确认才入账

## 5. 已知风险

1. **真机取景帧质量**（最大不确定性，§6.2 还没做）。缓解手段按顺序：已做裁剪扫描框；
   若不够，加"连续两帧同一候选才提升置信"；再不够上灰度化/二值化预处理
2. **`CONFIDENCE_FLOOR = 0.55` 暂不动**（[matcher.py](../server/app/recognize/matcher.py)）。
   194 张离线样本里只有 4 张职业卡没过阈值，没有降阈值的理由。真机测下来若普遍差一点点
   再标定，**但别为了提高命中率降到很低**——误配一张卡比没认出来更糟
3. **同名多版本卡靠数字区分**：§3.4 修完后离线样本上四个游戏牌堆严格 Top-1 都 ≥95%，
   但真机模糊时数字最先糊。**永远靠 Top-3 候选 + 玩家确认兜底，绝不自动入账**
4. **一帧 1~3s**（headless Edge 实测 1.3~2.1s/整卡，手机裁剪后区域更小但 CPU 更弱）。
   比预研时按 Node 估的 0.6~1.0s 慢，已加进行中反馈；手动检索入口全程可用
5. **职业卡识别率低**（12 张里 4 张认不出，标题就三两个字、卡面全是表格）。
   对局中不影响：职业卡是开局从列表里选的，不走扫描
6. **卡面反光**是实体卡的老问题，扫描框提示语可以引导玩家避开顶灯

## 6. 验收

### 6.1 离线命中率 ✅

`npm run ocr-bench`（194 张实拍图 → 文本）+
`server\.venv\Scripts\python.exe tools/eval_browser_ocr.py`（文本 → matcher 打分）：

| 牌堆 | 张数 | 严格 Top-1 | 严格 Top-3 |
| --- | --- | --- | --- |
| 大买卖 | 42 | 100.0% | 100.0% |
| 额外支出 | 42 | 95.2% | 100.0% |
| 市场风云 | 42 | 59.5% | 100.0% |
| 小生意 | 56 | 98.2% | 100.0% |
| 职业卡 | 12 | 66.7% | 66.7% |
| **合计** | **194** | **87.6%** | **97.9%** |

「严格」= 命中的必须是这张卡本身或与它 `key` 相同的重复卡。**四个游戏牌堆严格 Top-3
全部 100%**，未命中的 4 张全是职业卡（不走扫描）。市场风云 Top-1 低但 Top-3 满分是正常的
——它标题短、同标题多，本来就靠玩家在三个候选里点。
OCR 耗时中位 656ms（Node，整卡图）。

无 rapidfuzz（云端精简镜像的实际情况，matcher 退到 difflib）跑出来数字完全一致，
**云端不需要为匹配质量加依赖**。

### 6.2 真机取景帧 ⬜ 待现场做

手机对着实体卡扫，至少 10 张不同卡，Top-3 命中 ≥ 80%。
**这一步的数字才是真的**，裁剪图的 97.9% 只是上限。

### 6.3 真实浏览器冒烟 ✅

`npm run ocr-smoke`（puppeteer-core 驱动系统已装的 Edge/Chrome，不下载浏览器）：
加载 `/tesseract/` 下的自托管资源 → 跑 WASM → 识别实拍卡面出中文文本。
专治「自托管路径写错 → 手机上只显示『本机识别不可用』然后默默降级」这类问题。
实测：引擎加载 872ms，连续 3 帧 1837/2074/1318ms，取的是 `relaxedsimd-lstm` 变体。

### 6.4 服务端单测与回归 ✅

`server\.venv\Scripts\python.exe -m pytest` → **413 passed / 1 skipped**（原 405 + 新增 8）。
新增覆盖：`recognize-text` 的候选/reason/统计（engine=browser）/空文本/无关文本/超长文本被拒/
无 deckHint 全库检索，以及 §3.4 两个 matcher 缺陷的回归。

### 6.5 云端端到端 ⬜ 待部署验证

Render Free（精简镜像）扫一张卡能入账，`/api/health` 的 `memory.rssMb` 全程无明显增长。
镜像因自托管资源变大约 13MB（未压缩）。

## 7. 相关

- **诊断端点**：`GET /api/health`、`POST /api/health/ocr-probe`（服务端 OCR 用），
  用法见 [README](../README.md)「扫描识别排障」
- **相关设计**：[design/04 §4](04-卡牌数据模型与识别方案.md) 的识别管线一节仍然有效
  （封闭集匹配的原始设计），卡牌数据部分已被 [design/06](06-卡牌数字化结果与设计修订.md) 取代
