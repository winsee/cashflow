"""识别适配层（design/03 §8、FR-26/30）。

已实现：LocalOCRRecognizer（服务器本地 PaddleOCR，依赖装了才启用）、
ManualRecognizer（返回空候选 → 前端转手动检索）；CloudRecognizer 仅预留接口。
降级链默认：Local → Manual；`CASHFLOW_OCR=off` 可禁用本地 OCR。

**失败原因必须透传**：早期版本把异常一律 `except: continue` 吞掉，云端
（弱 CPU/小内存）超时与"真的没匹配上"在前端长得一模一样，无从排查。现在
每次识别都带回 reason，一路进 API 响应和手机屏幕。
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Protocol

from ..data_loader import CardLibrary


@dataclass
class Candidate:
    card_id: str
    title: str
    score: float
    engine: str


@dataclass
class RecognizeOutcome:
    """识别结果 + 失败归因。

    reason 取值：
    - `ok`          有候选
    - `no_match`    OCR 认出了字，但没有卡分数过 CONFIDENCE_FLOOR（识别质量问题）
    - `no_text`     OCR 跑通了但一个字都没认出（对焦/光线/取景问题）
    - `timeout`     超过 CASHFLOW_OCR_TIMEOUT（云端弱 CPU 的典型症状）
    - `unavailable` 链里没有本地引擎：依赖没装或 CASHFLOW_OCR=off
    - `error:<异常类名>` 其他异常
    """
    candidates: list[Candidate] = field(default_factory=list)
    engine: str = "manual"
    reason: str = "unavailable"
    text_len: int = 0


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

    @property
    def has_local(self) -> bool:
        return any(getattr(e, "name", "") != "manual" for e in self.engines)

    async def recognize(self, image: bytes, deck_hint: str | None,
                        lib: CardLibrary) -> RecognizeOutcome:
        reason = "no_match" if self.has_local else "unavailable"
        text_len = 0
        for eng in self.engines:
            try:
                cands = await eng.recognize(image, deck_hint, lib)
            except asyncio.TimeoutError:
                reason = "timeout"
                continue
            except Exception as exc:
                reason = f"error:{type(exc).__name__}"
                continue
            if cands:
                return RecognizeOutcome(cands, eng.name, "ok",
                                        getattr(eng, "last_text_len", 0))
            if getattr(eng, "name", "") != "manual":
                # 空候选也要分因：认出字了但没匹配上 ≠ 压根没认出字
                text_len = max(text_len, getattr(eng, "last_text_len", 0))
                reason = "no_match" if text_len else "no_text"
        return RecognizeOutcome([], "manual", reason, text_len)


def default_chain() -> RecognizerChain:
    engines: list[CardRecognizer] = []
    if os.environ.get("CASHFLOW_OCR", "auto") != "off":
        from . import local_ocr
        if local_ocr.available():
            engines.append(local_ocr.LocalOCRRecognizer())
    engines.append(ManualRecognizer())
    return RecognizerChain(engines)
