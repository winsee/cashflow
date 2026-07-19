"""识别适配层（design/03 §8、FR-26/30）。

已实现：LocalOCRRecognizer（服务器本地 PaddleOCR，依赖装了才启用）、
ManualRecognizer（返回空候选 → 前端转手动检索）；CloudRecognizer 仅预留接口。
降级链默认：Local → Manual；`CASHFLOW_OCR=off` 可禁用本地 OCR。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from ..data_loader import CardLibrary


@dataclass
class Candidate:
    card_id: str
    title: str
    score: float
    engine: str


class CardRecognizer(Protocol):
    name: str

    async def recognize(self, image: bytes, deck_hint: str | None,
                        lib: CardLibrary) -> list[Candidate]: ...


class ManualRecognizer:
    """无识别：空候选，前端展示手动检索列表（永远可用的兜底）。"""
    name = "manual"

    async def recognize(self, image: bytes, deck_hint: str | None,
                        lib: CardLibrary) -> list[Candidate]:
        return []


class RecognizerChain:
    """失败/空结果自动降级到下一引擎；全程记录 engine 供 FR-28 统计。"""

    def __init__(self, engines: list[CardRecognizer]):
        self.engines = engines

    async def recognize(self, image: bytes, deck_hint: str | None,
                        lib: CardLibrary) -> tuple[list[Candidate], str]:
        for eng in self.engines:
            try:
                cands = await eng.recognize(image, deck_hint, lib)
            except Exception:
                continue
            if cands:
                return cands, eng.name
        return [], "manual"


def default_chain() -> RecognizerChain:
    engines: list[CardRecognizer] = []
    if os.environ.get("CASHFLOW_OCR", "auto") != "off":
        from . import local_ocr
        if local_ocr.available():
            engines.append(local_ocr.LocalOCRRecognizer())
    engines.append(ManualRecognizer())
    return RecognizerChain(engines)
