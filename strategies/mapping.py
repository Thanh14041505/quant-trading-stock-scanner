"""Hàm phụ trợ ánh xạ output gốc (dict tiếng Việt) -> StrategyResult. Chỉ TRÌNH BÀY LẠI, không tính lại logic."""
from __future__ import annotations
import re
from typing import Any, List, Optional


def to_float(x: Any) -> Optional[float]:
    """'12.34' / 12.34 / '1:2.0' / '5.1%' -> float; không đọc được -> None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return None if x != x else float(x)
    m = re.findall(r"-?\d+(?:\.\d+)?", str(x).replace(",", ""))
    if not m:
        return None
    return float(m[-1]) if str(x).startswith("1:") else float(m[0])


def split_list(x: Any, sep: str = "|") -> List[str]:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [str(i) for i in x if str(i).strip()]
    return [p.strip() for p in str(x).split(sep) if p.strip() and p.strip() != "—"]


def clean(d: dict) -> dict:
    """Bản sao output gốc an toàn để JSON/hiển thị (giữ nguyên khóa gốc)."""
    import numpy as np
    out = {}
    for k, v in d.items():
        if isinstance(v, np.generic):
            v = v.item()
        try:
            out[k] = v if isinstance(v, (str, int, float, bool, list, dict, type(None))) else str(v)
        except Exception:
            out[k] = str(v)
    return out
