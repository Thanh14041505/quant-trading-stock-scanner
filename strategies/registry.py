"""Đăng ký strategy. Thêm Strategy 8, 9…: tạo strategy_08.py rồi thêm 1 dòng vào REGISTRY (xem README)."""
from __future__ import annotations
from typing import Dict
from .base import BaseStrategy
from .strategy_01 import Strategy01
from .strategy_02 import Strategy02
from .strategy_03 import Strategy03
from .strategy_04 import Strategy04
from .strategy_05 import Strategy05
from .strategy_06 import Strategy06
from .strategy_07 import Strategy07

REGISTRY: Dict[str, BaseStrategy] = {
    s.info.sid: s for s in (Strategy01(), Strategy02(), Strategy03(), Strategy04(),
                            Strategy05(), Strategy06(), Strategy07())
}
