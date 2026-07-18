"""引擎错误：code 供前端分支（如现金不足引导贷款），message 为中文提示。"""
from __future__ import annotations


class EngineError(Exception):
    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra
