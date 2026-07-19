"""本地 OCR 识别引擎（design/03 §8、design/04 §4）：PaddleOCR 提文本 → matcher 打分。

PaddleOCR/paddlepaddle 属可选依赖（pyproject [ocr]）：未安装时 available() 为 False，
识别链跳过本引擎直接手动兜底。模型首次使用自动下载；Docker 构建期可用
`python -m app.recognize.local_ocr --warmup` 预下载进镜像（离线可用）。
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

from ..data_loader import CardLibrary
from .matcher import match_cards

OCR_TIMEOUT_S = 8.0  # NFR-3：本地识别 <8s，超时自动降级


def available() -> bool:
    try:
        import paddleocr  # noqa: F401
        import rapidfuzz  # noqa: F401
        return True
    except ImportError:
        return False


class LocalOCRRecognizer:
    """PaddleOCR 单例惰性初始化；Semaphore(1) 串行化，防多人同时扫描打爆 CPU。"""

    name = "local"

    def __init__(self):
        self._engine = None
        self._init_lock = threading.Lock()
        self._sem = asyncio.Semaphore(1)

    def _get_engine(self):
        with self._init_lock:
            if self._engine is None:
                # 跳过联网源检查：局域网/离线环境下否则每次初始化都等超时
                os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
                from paddleocr import PaddleOCR
                try:  # PaddleOCR 3.x：产线式参数
                    # 实测（Windows CPU，实拍整卡）：mobile 模型 + mkldnn ≈4s/帧，
                    # 满足 NFR-3 <8s；textline 方向分类 +1.2s/帧，扫描时卡面朝上，关闭。
                    # ⚠️ paddlepaddle 须 <3.1：3.1+ 在 CPU 开 mkldnn 会触发
                    # ConvertPirAttribute2RuntimeAttribute NotImplementedError。
                    self._engine = PaddleOCR(
                        lang="ch",
                        text_detection_model_name="PP-OCRv5_mobile_det",
                        text_recognition_model_name="PP-OCRv5_mobile_rec",
                        use_doc_orientation_classify=True,  # 卡面可能横竖拍
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                        enable_mkldnn=True,
                    )
                except TypeError:  # PaddleOCR 2.x
                    self._engine = PaddleOCR(lang="ch", use_angle_cls=True,
                                             show_log=False)
            return self._engine

    def warm(self) -> None:
        """预热：加载模型并跑一次空白推理（阻塞，调用方自行放线程池）。
        服务启动时预热后，玩家第一帧扫描就不会撞上模型加载导致的超时降级。"""
        import cv2
        import numpy as np
        blank = np.full((64, 256, 3), 255, dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", blank)
        self._ocr_text(buf.tobytes())

    def _ocr_items(self, image: bytes) -> list[tuple[str, tuple[float, float, float, float]]]:
        """OCR 出 (文本, 外接矩形 x0,y0,x1,y1) 列表。

        坐标用于把"左标签右数值"两栏布局的碎块聚回物理行（prefill.merge_rows）；
        个别引擎版本拿不到坐标时用递增 y 的合成框占位，各块独立成行。
        """
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []
        # 长边压到 960：卡面文字足够清晰，且单帧耗时可控（实测 ≈4s）
        h, w = img.shape[:2]
        if max(h, w) > 960:
            scale = 960 / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))
        engine = self._get_engine()
        items: list[tuple[str, tuple[float, float, float, float]]] = []

        def rect_of(poly) -> tuple[float, float, float, float]:
            xs = [float(p[0]) for p in poly]
            ys = [float(p[1]) for p in poly]
            return (min(xs), min(ys), max(xs), max(ys))

        if hasattr(engine, "predict"):  # 3.x
            for res in engine.predict(input=img):
                data = res if isinstance(res, dict) else getattr(res, "json", {})
                if isinstance(data.get("res"), dict):
                    data = data["res"]
                texts = data.get("rec_texts") or []
                boxes = data.get("rec_boxes")
                polys = data.get("rec_polys")
                if polys is None or not len(polys):
                    polys = data.get("dt_polys")
                for i, t in enumerate(texts):
                    if not t:
                        continue
                    if boxes is not None and i < len(boxes):
                        b = boxes[i]
                        rect = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
                    elif polys is not None and i < len(polys):
                        rect = rect_of(polys[i])
                    else:
                        y = float(len(items)) * 100
                        rect = (0.0, y, 10.0, y + 10.0)
                    items.append((t, rect))
        else:  # 2.x：item = [四点框, (文本, 置信度)]
            for page in engine.ocr(img, cls=True) or []:
                for item in page or []:
                    items.append((item[1][0], rect_of(item[0])))
        return items

    def _ocr_text(self, image: bytes) -> str:
        return "\n".join(t for t, _ in self._ocr_items(image))

    async def recognize(self, image: bytes, deck_hint: str | None,
                        lib: CardLibrary):
        from .base import Candidate
        cards = lib.by_deck(deck_hint) if deck_hint else list(lib.cards.values())
        if not cards:
            return []
        async with self._sem:
            loop = asyncio.get_running_loop()
            text = await asyncio.wait_for(
                loop.run_in_executor(None, self._ocr_text, image),
                timeout=OCR_TIMEOUT_S)
        return [Candidate(card_id=m.card_id, title=m.title, score=m.score,
                          engine=self.name)
                for m in match_cards(text, cards)]

    def extract_items(self, image: bytes) -> list[tuple[str, tuple[float, float, float, float]]]:
        """录入工具 OCR 预填用：同步返回 (文本, 框) 列表（调用方自行放线程池）。"""
        return self._ocr_items(image)


def warmup() -> None:  # pragma: no cover - 仅构建期使用
    """触发模型下载与一次推理，把模型烤进 Docker 镜像。"""
    t0 = time.time()
    LocalOCRRecognizer().warm()
    print(f"warmup ok in {time.time() - t0:.1f}s")


if __name__ == "__main__":  # pragma: no cover
    import sys
    if "--warmup" in sys.argv:
        warmup()
