"""
Provider DỮ LIỆU GIẢ LẬP — chỉ để chạy thử giao diện/test offline.

CẢNH BÁO: đây KHÔNG phải dữ liệu thị trường. UI luôn hiện banner khi dùng provider này.
"""
from __future__ import annotations
import zlib
import numpy as np
import pandas as pd


class DemoProvider:
    is_demo = True
    def __init__(self, end: str | None = None, n_days: int = 900):
        self.end = pd.Timestamp(end).normalize() if end else pd.Timestamp.now().normalize()
        self.n_days = n_days

    def fetch(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        seed = zlib.crc32(symbol.encode()) % (2**32)          # ổn định giữa các lần chạy
        rng = np.random.default_rng(seed)
        days = pd.bdate_range(end=self.end, periods=self.n_days)
        drift = rng.normal(0.0003, 0.0004)
        vol = 0.012 if symbol != "VNINDEX" else 0.008
        ret = rng.normal(drift, vol, len(days))
        base = 1200.0 if symbol == "VNINDEX" else float(rng.uniform(12, 120))   # đơn vị "nghìn đồng"
        close = base * np.exp(np.cumsum(ret))
        open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.003, len(days)))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, len(days))))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, len(days))))
        volume = (rng.lognormal(12.5, 0.5, len(days)) * (1 + 3 * (np.abs(ret) > 2 * vol))).astype(int)
        df = pd.DataFrame({"time": days, "open": open_.round(2), "high": high.round(2),
                           "low": low.round(2), "close": close.round(2), "volume": volume})
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        df = df[(df["time"] >= s) & (df["time"] <= e)].reset_index(drop=True)
        df["_src"] = "KBS"     # giả lập đơn vị "nghìn đồng" như KBS thật, để S7 quy đổi VND đúng cách
        return df
