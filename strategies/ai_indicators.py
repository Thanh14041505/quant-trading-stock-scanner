"""
Chỉ báo nhân quả dùng chung giữa S8 (AI Technical Read) và S9 (AI SMC Structure Read).

Tách riêng để S8/S9 không lặp code — ĐÂY VẪN LÀ CODE CỦA TRỢ LÝ AI (không phải trích từ notebook nào),
nên nằm trong `strategies/`, KHÔNG nằm trong `indicators/shared_verified/` (chỗ đó dành riêng cho code
đã CHỨNG MINH giống hệt notebook — xem docstring của thư mục đó).

Mọi hàm chỉ dùng dữ liệu tại/trước thời điểm hiện tại (không có `shift(-n)`, không `center=True`).
"""
from __future__ import annotations
from typing import Any, Dict
import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series):
    macd_line = ema(close, 12) - ema(close, 26)
    signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    return macd_line, signal, macd_line - signal


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mfv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng * df["volume"]
    return mfv.rolling(period).sum() / df["volume"].rolling(period).sum()


def stoch(df: pd.DataFrame, period: int = 14, smooth: int = 3):
    ll, hh = df["low"].rolling(period).min(), df["high"].rolling(period).max()
    k = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    return k.rolling(smooth).mean(), k.rolling(smooth).mean().rolling(smooth).mean()


def clip01(x: float, lo: float, hi: float) -> float:
    """Quy x về [0,1] tuyến tính trong [lo,hi], kẹp hai đầu — dùng để chuyển chỉ báo thô thành điểm con."""
    if pd.isna(x):
        return 0.5
    return float(np.clip((x - lo) / (hi - lo), 0.0, 1.0))


def vnindex_regime(vni: pd.DataFrame) -> Dict[str, Any]:
    """Regime đơn giản tự tính từ VNINDEX (EMA50/200 + độ dốc) — KHÔNG dùng lại RegimeEngine của notebook."""
    c = vni["close"]
    e50, e200 = ema(c, 50), ema(c, 200)
    slope10 = (e50.iloc[-1] / e50.iloc[-11] - 1) * 100 if len(e50) > 11 and pd.notna(e50.iloc[-11]) else 0.0
    above50, above200 = c.iloc[-1] > e50.iloc[-1], (pd.notna(e200.iloc[-1]) and c.iloc[-1] > e200.iloc[-1])
    pts = int(above50) + int(above200) + int(slope10 > 0.3) + int(slope10 > -0.3) - int(slope10 < -0.3)
    if pts >= 3 and above50:
        label, mult = "BULL", 1.10
    elif pts <= 0 and not above50:
        label, mult = "BEAR", 0.85
    else:
        label, mult = "SIDEWAYS", 1.00
    return {"regime": label, "mult": mult, "slope10_pct": round(slope10, 2),
            "above_ema50": bool(above50), "above_ema200": bool(above200) if pd.notna(e200.iloc[-1]) else None}
