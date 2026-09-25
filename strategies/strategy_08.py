"""
S8 — Claude AI Technical Read   [Dòng E — KHÔNG thuộc 7 notebook gốc]

Đây là "bộ não" thứ 8 mà bạn (Thanh) đã thiết kế chỗ trống cho nó ngay từ đầu ở mục 12 của prompt gốc
("Thiết kế để sau này có thể thêm Strategy 8, 9…"). Toàn bộ logic bên dưới do trợ lý AI tự viết —
KHÔNG trích từ notebook nào, nên KHÔNG chịu ràng buộc "giữ nguyên bug/threshold" như S1–S7.

MỤC ĐÍCH: một góc nhìn phân tích kỹ thuật độc lập, đơn giản, minh bạch — để đối chiếu/tham khảo bên cạnh
7 strategy gốc, KHÔNG PHẢI khuyến nghị đầu tư. Vì lý do này:
  * family = "E" và mặc định KHÔNG được tính vào đồng thuận (Bull/Families) của 7 notebook — xem
    engine/consensus.py + sidebar (người dùng có thể bật "Tính S8 vào đồng thuận" nếu muốn).
  * Mọi output đều gắn nhãn "S8 · AI" để không lẫn với số liệu gốc của notebook.

PHƯƠNG PHÁP (toàn bộ đều nhân quả — chỉ dùng dữ liệu tại/trước ngày quét, không có future bar):
  Trend (30đ)     : giá vs EMA20/50/200 (đúng thứ tự tăng dần = tăng), độ dốc EMA50 10 phiên gần nhất.
  Momentum (25đ)  : RSI14 (Wilder), MACD (12,26,9) histogram & hướng, Stochastic %K/%D 14.
  Dòng tiền (20đ) : CMF20, độ dốc OBV 20 phiên, volume ratio (phiên gần nhất / TB 20 phiên).
  Cấu trúc (15đ)  : ATR% (biến động), vị trí trong dải Bollinger 20 phiên, khoảng cách tới đỉnh/đáy 60 phiên.
  Sức mạnh (10đ)  : hiệu suất 60 phiên của mã so với VNINDEX (RS).
  Regime VNINDEX  : bull/sideways/bear tự tính (EMA50/200 + độ dốc) — nhân điểm tổng ±10%, KHÔNG dùng lại
                    RegimeEngine của S1–S6 (đó là code notebook, S8 phải độc lập).

Entry/SL/TP CỐ Ý đơn giản (khác triết lý "nhiều mức ưu tiên" của notebook, để dễ kiểm chứng bằng mắt):
  Entry = giá đóng cửa gần nhất. SL = mức GẦN HƠN giữa (đáy 20 phiên) và (entry − 1.2×ATR14), nhưng không xa quá
  2.5×ATR. TP = entry + 2.0×risk, trừ khi có đỉnh 60 phiên gần hơn phía trên (thì lấy đỉnh đó × 0.99) — không có
  chuyện ép target tối thiểu +9% như một số notebook (audit B3).
"""
from __future__ import annotations
from typing import Any, Dict, Optional
import numpy as np
import pandas as pd

from .base import (BaseStrategy, StrategyInfo, StrategyResult, ScanContext,
                   STRONG_BUY, BUY, WATCH, NONE, REDUCE, EXIT, FILTERED, NO_DATA, ERROR)
from data.store import DataError, BENCHMARK

AI_DISCLAIMER = ("Đây là bộ đọc kỹ thuật độc lập do trợ lý AI tự viết (không phải một trong 7 notebook gốc). "
                  "Chỉ mang tính tham khảo, KHÔNG PHẢI khuyến nghị đầu tư — tự chịu trách nhiệm với quyết định của bạn.")


# ───────────────────────── indicator thuần (nhân quả, không nhìn tương lai) ─────────────────────────
def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def _rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _macd(close: pd.Series):
    macd_line = _ema(close, 12) - _ema(close, 26)
    signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    return macd_line, signal, macd_line - signal


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mfv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng * df["volume"]
    return mfv.rolling(period).sum() / df["volume"].rolling(period).sum()


def _stoch(df: pd.DataFrame, period: int = 14, smooth: int = 3):
    ll, hh = df["low"].rolling(period).min(), df["high"].rolling(period).max()
    k = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    return k.rolling(smooth).mean(), k.rolling(smooth).mean().rolling(smooth).mean()


def _clip01(x: float, lo: float, hi: float) -> float:
    """Quy x về [0,1] tuyến tính trong [lo,hi], kẹp hai đầu — dùng để chuyển chỉ báo thô thành điểm con."""
    if pd.isna(x):
        return 0.5
    return float(np.clip((x - lo) / (hi - lo), 0.0, 1.0))


def _regime(vni: pd.DataFrame) -> Dict[str, Any]:
    c = vni["close"]
    e50, e200 = _ema(c, 50), _ema(c, 200)
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


class Strategy08(BaseStrategy):
    info = StrategyInfo("S8", "Claude AI Technical Read", "E",
                        "(không có — engine riêng của trợ lý AI, không thuộc notebook nào)",
                        True, "Tham khảo, KHÔNG tính vào đồng thuận 7-notebook theo mặc định")

    DEFAULTS = dict(
        min_history_rows=120, min_avg_value_20d=8_000_000,     # lọc thanh khoản; ĐƠN VỊ THEO API GỐC như S1–S6 (không quy đổi VND như S7)
        strong_buy_score=78.0, buy_score=65.0, watch_score=50.0,
        reduce_score=35.0,                                          # < ngưỡng này + downtrend -> REDUCE/EXIT
        rr_target=2.0, atr_sl_mult=1.2, atr_sl_cap=2.5, swing_lookback=20, resistance_lookback=60,
    )

    def default_config(self) -> Dict[str, Any]:
        return dict(self.DEFAULTS)

    def prepare(self, ctx: ScanContext):
        as_of = ctx.store.latest_session()
        if as_of is None:
            raise DataError("Chưa xác định được phiên giao dịch gần nhất (thiếu VNINDEX)")
        vni = ctx.store.get_raw(BENCHMARK).drop(columns=["_src"], errors="ignore")
        vni["time"] = pd.to_datetime(vni["time"])
        vni = vni.sort_values("time").reset_index(drop=True)
        if len(vni) < 60:
            raise DataError(f"VNINDEX chỉ có {len(vni)} phiên — cần ≥ 60 để tính regime/RS")
        reg = _regime(vni)
        vni["ret60"] = vni["close"] / vni["close"].shift(60) - 1
        cfg = dict(self.DEFAULTS)
        for k, v in ctx.overrides.get("S8", {}).items():
            if k in cfg:
                cfg[k] = type(cfg[k])(v)
        return dict(vni=vni, regime=reg, cfg=cfg, as_of=as_of)

    def prep_summary(self, prep) -> Dict[str, Any]:
        r = prep["regime"]
        return {"regime": r["regime"], "label": f"EMA50 slope 10 phiên: {r['slope10_pct']:+.2f}%",
                "score_mult": r["mult"], "min_score": None, "vnindex": None}

    def run_symbol(self, symbol: str, prep, ctx: ScanContext) -> StrategyResult:
        cfg = prep["cfg"]
        try:
            df = ctx.store.get_raw(symbol).drop(columns=["_src"], errors="ignore")
        except DataError as e:
            return StrategyResult("S8", symbol, "NO_DATA", ctx.mode, "—", NO_DATA, warnings=[f"API: {str(e)[:160]}"])
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time").reset_index(drop=True)
        if len(df) < cfg["min_history_rows"]:
            return StrategyResult("S8", symbol, "FILTERED", ctx.mode, "Thiếu lịch sử", FILTERED,
                                  failed_conditions=[f"Chỉ có {len(df)} phiên (<{cfg['min_history_rows']})"],
                                  legacy_notes=[AI_DISCLAIMER])
        avg_val20 = (df["close"] * df["volume"]).tail(20).mean()
        if avg_val20 < cfg["min_avg_value_20d"]:
            return StrategyResult("S8", symbol, "FILTERED", ctx.mode, "Thanh khoản thấp", FILTERED,
                                  price=float(df["close"].iloc[-1]),
                                  failed_conditions=[f"Giá trị GD TB 20 phiên {avg_val20:,.0f} < ngưỡng {cfg['min_avg_value_20d']:,.0f}"],
                                  legacy_notes=[AI_DISCLAIMER])
        try:
            return self._score(symbol, df, prep, ctx, cfg)
        except Exception as e:  # noqa: BLE001 — 1 mã lỗi không được làm sập cả strategy
            return StrategyResult("S8", symbol, "ERROR", ctx.mode, "—", ERROR,
                                  warnings=[f"{type(e).__name__}: {str(e)[:200]}"], legacy_notes=[AI_DISCLAIMER])

    def _score(self, symbol, df, prep, ctx, cfg) -> StrategyResult:
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        e20, e50, e200 = _ema(c, 20), _ema(c, 50), _ema(c, 200)
        rsi = _rsi_wilder(c, 14)
        macd_line, macd_sig, macd_hist = _macd(c)
        atr = _atr(df, 14)
        cmf = _cmf(df, 20)
        obv = v.where(c.diff() > 0, -v.where(c.diff() < 0, 0)).cumsum()
        k, d = _stoch(df, 14, 3)
        mid = c.rolling(20).mean()
        std = c.rolling(20).std()
        bb_pos = (c - (mid - 2 * std)) / (4 * std).replace(0, np.nan)         # 0=đáy dải, 1=đỉnh dải
        swing_low = l.rolling(cfg["swing_lookback"]).min()
        swing_high20 = h.rolling(cfg["swing_lookback"]).max()
        res60 = h.rolling(cfg["resistance_lookback"]).max()

        price = float(c.iloc[-1])
        has200 = pd.notna(e200.iloc[-1])
        trend_align = int(c.iloc[-1] > e20.iloc[-1]) + int(e20.iloc[-1] > e50.iloc[-1]) + \
                      (int(e50.iloc[-1] > e200.iloc[-1]) if has200 else 1)
        ema50_slope10 = (e50.iloc[-1] / e50.iloc[-11] - 1) * 100 if len(e50) > 11 and pd.notna(e50.iloc[-11]) else 0.0
        trend_sub = 30 * (0.6 * _clip01(trend_align, 0, 3) + 0.4 * _clip01(ema50_slope10, -3, 3))

        mom_sub = 25 * np.mean([_clip01(rsi.iloc[-1], 35, 70),
                                _clip01(float(macd_hist.iloc[-1]), -abs(price) * 0.01, abs(price) * 0.01),
                                _clip01(float(k.iloc[-1] - d.iloc[-1]), -10, 10)])

        obv_slope20 = (obv.iloc[-1] - obv.iloc[-21]) if len(obv) > 21 else 0.0
        obv_norm = obv_slope20 / (v.tail(20).mean() * 20 + 1e-9)
        vol_ratio = v.iloc[-1] / v.tail(20).mean() if v.tail(20).mean() else 1.0
        flow_sub = 20 * np.mean([_clip01(float(cmf.iloc[-1]), -0.15, 0.15),
                                 _clip01(obv_norm, -1, 1), _clip01(vol_ratio, 0.5, 2.0)])

        atr_pct = float(atr.iloc[-1] / price * 100) if price else 0.0
        struct_sub = 15 * np.mean([_clip01(float(bb_pos.iloc[-1]), 0.15, 0.85),
                                   1 - _clip01(atr_pct, 1.5, 6.0),
                                   _clip01((price - swing_low.iloc[-1]) / price * 100, 0, 8)])

        rs = float(df["close"].iloc[-1] / df["close"].iloc[-61] - 1) if len(df) > 61 else 0.0
        rs_vni = float(prep["vni"]["ret60"].iloc[-1]) if pd.notna(prep["vni"]["ret60"].iloc[-1]) else 0.0
        rs_sub = 10 * _clip01(rs - rs_vni, -0.15, 0.15)

        raw_score = trend_sub + mom_sub + flow_sub + struct_sub + rs_sub
        score = float(np.clip(raw_score * prep["regime"]["mult"], 0, 100))

        uptrend = trend_align >= 2 and price > e50.iloc[-1]
        if score >= cfg["strong_buy_score"] and uptrend:
            sig, native = STRONG_BUY, "MUA MẠNH (AI)"
        elif score >= cfg["buy_score"] and uptrend:
            sig, native = BUY, "MUA (AI)"
        elif score >= cfg["watch_score"]:
            sig, native = WATCH, "THEO DÕI (AI)"
        elif score <= cfg["reduce_score"] and not uptrend and rsi.iloc[-1] < 45:
            sig, native = (EXIT, "TRÁNH/THOÁT (AI)") if score <= cfg["reduce_score"] - 10 else (REDUCE, "GIẢM TỶ TRỌNG (AI)")
        else:
            sig, native = NONE, "KHÔNG RÕ XU HƯỚNG (AI)"

        entry = price
        sl_struct = float(swing_low.iloc[-1])
        sl_atr = entry - cfg["atr_sl_mult"] * float(atr.iloc[-1])
        sl = max(sl_struct, sl_atr) if sl_struct < entry else sl_atr
        sl = max(sl, entry - cfg["atr_sl_cap"] * float(atr.iloc[-1]))           # không để SL quá xa
        sl = min(sl, entry - 0.1 * float(atr.iloc[-1]))                        # đảm bảo SL luôn < entry
        risk = entry - sl
        tp_by_rr = entry + cfg["rr_target"] * risk
        res = float(res60.iloc[-1])
        tp = min(tp_by_rr, res * 0.99) if (res > entry * 1.01) else tp_by_rr
        rr = (tp - entry) / risk if risk > 0 else None

        reasons, warns = [], []
        if trend_align == 3: reasons.append(f"Giá > EMA20 > EMA50 > EMA200 (đồng thuận tăng, độ dốc EMA50 {ema50_slope10:+.1f}%/10 phiên)")
        elif trend_align <= 1: warns.append("Cấu trúc EMA chưa đồng thuận tăng")
        if rsi.iloc[-1] >= 70: warns.append(f"RSI14={rsi.iloc[-1]:.0f} — vùng quá mua")
        elif rsi.iloc[-1] <= 30: warns.append(f"RSI14={rsi.iloc[-1]:.0f} — vùng quá bán")
        if macd_hist.iloc[-1] > 0 and macd_hist.iloc[-2] <= 0: reasons.append("MACD histogram vừa chuyển dương")
        if cmf.iloc[-1] > 0.05: reasons.append(f"CMF20={cmf.iloc[-1]:.2f} — dòng tiền vào")
        elif cmf.iloc[-1] < -0.05: warns.append(f"CMF20={cmf.iloc[-1]:.2f} — dòng tiền ra")
        if vol_ratio >= 1.5: reasons.append(f"Khối lượng phiên gần nhất gấp {vol_ratio:.1f}× TB20")
        if rs - rs_vni > 0.05: reasons.append(f"Mạnh hơn VNINDEX {((rs - rs_vni) * 100):.1f} điểm % (60 phiên)")
        elif rs - rs_vni < -0.05: warns.append(f"Yếu hơn VNINDEX {((rs_vni - rs) * 100):.1f} điểm %  (60 phiên)")
        if atr_pct > 6: warns.append(f"ATR%={atr_pct:.1f}% — biến động rất cao, cân nhắc giảm khối lượng vị thế")

        return StrategyResult(
            sid="S8", symbol=symbol, status="OK", mode=ctx.mode, native_signal=native, signal=sig,
            score=round(score, 1), score_scale=100, price=price,
            setup=f"Trend {trend_sub:.0f}/30 · Mom {mom_sub:.0f}/25 · Flow {flow_sub:.0f}/20 · Struct {struct_sub:.0f}/15 · RS {rs_sub:.0f}/10",
            entry=entry, stop_loss=sl, take_profit=tp, risk_reward=rr, rr_basis="TP (AI, 2R hoặc kháng cự 60 phiên)",
            reasons=reasons, warnings=warns, passed_conditions=reasons, failed_conditions=[],
            legacy_notes=[AI_DISCLAIMER, f"Regime VNINDEX (tự tính, độc lập với S1–S6): {prep['regime']['regime']}"],
            extra={"score_breakdown": {"trend": round(trend_sub, 1), "momentum": round(mom_sub, 1),
                                       "flow": round(flow_sub, 1), "structure": round(struct_sub, 1), "rs": round(rs_sub, 1)},
                   "rsi14": round(float(rsi.iloc[-1]), 1), "atr_pct": round(atr_pct, 2),
                   "vol_ratio_20d": round(float(vol_ratio), 2), "regime_mult": prep["regime"]["mult"]})
