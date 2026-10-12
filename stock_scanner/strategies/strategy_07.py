"""
S7 — Phase 13: Daily Live / EOD Stock Scanner   [Dòng D]

# Source Notebook : Tool_CK_Claude_ChatGPT_v3_ProductionDailyScanner.ipynb
# Section         : PHASE 13 — DAILY LIVE / EOD STOCK SCANNER (13.0 → 13.6 + hotfix normalize_ohlcv)
# Production logic: strategies/_legacy/s07_legacy.py (trích theo tên bằng AST, nguyên văn).

Triết lý (theo notebook): công cụ hỗ trợ quyết định, KHÔNG phải hệ thống tự động; tách regime / feature / setup /
probability / exit-risk / thanh khoản; "exit thắng buy".

Khác biệt cốt lõi so với S1–S6 (xem audit):
  * Điểm 0–100 (alpha_score), regime 5 mức từ VNINDEX, giá quy đổi VND (KBS nghìn đồng ×1000).
  * KHÔNG có Entry / SL-TP tuyệt đối / R:R / position sizing — chỉ có suggested_sl_pct / suggested_tp_pct (B8).
  * Không có mode Hold riêng: mode chọn trong UI không ảnh hưởng S7.
  * p_tp cần model đã train -> chưa có -> NaN, combined_score = alpha_score (đúng hành vi notebook khi thiếu model).
Ánh xạ tín hiệu: STRONG_BUY/BUY/WATCH/REDUCE/EXIT giữ nguyên; NO_SIGNAL -> NONE; FILTERED theo status.
"""
from __future__ import annotations
import contextlib, copy, importlib, io, traceback
from typing import Any, Dict

import pandas as pd

from .base import (BaseStrategy, StrategyInfo, StrategyResult, ScanContext, STRONG_BUY, BUY, WATCH, NONE,
                   REDUCE, EXIT, FILTERED, NO_DATA, ERROR)
from .mapping import split_list, clean
from data.store import DataError, BENCHMARK
from config.legacy_flags import LEGACY_NOTES

_SIG = {"STRONG_BUY": STRONG_BUY, "BUY": BUY, "WATCH": WATCH, "REDUCE": REDUCE, "EXIT": EXIT, "NO_SIGNAL": NONE}


def _prepare_frame(mod, store, symbol: str, as_of, window_days: int):
    """Sao đúng `_call_data_layer` của notebook: cắt [as_of+1 − max(lookback,420) ngày, as_of+1], làm sạch, chuẩn hoá."""
    try:
        raw = store.get_raw(symbol)
    except DataError as e:
        raise RuntimeError(f"Unable to load OHLCV for {symbol}: {e}") from e
    end = pd.Timestamp(as_of).normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=max(int(window_days), 420))
    t = pd.to_datetime(raw["time"])
    raw = raw[(t >= start) & (t <= end)]
    if raw.empty:
        raise RuntimeError(f"Unable to load OHLCV for {symbol}: empty window")
    src = str(raw["_src"].iloc[-1]) if "_src" in raw.columns else ""
    raw = raw.drop(columns=["_src"], errors="ignore").reset_index(drop=True)
    raw.attrs["vnstock_source"] = src          # _production_clean đọc attrs để biết có phải KBS (nhân 1000) hay không
    df = mod._production_clean(None, raw)
    if df is None or df.empty:
        raise RuntimeError(f"Unable to load OHLCV for {symbol}: clean failed")
    return mod.normalize_ohlcv(df)


class Strategy07(BaseStrategy):
    info = StrategyInfo("S7", "Phase 13 — Daily EOD Scanner", "D",
                        "Tool_CK_Claude_ChatGPT_v3_ProductionDailyScanner.ipynb", False,
                        "Alpha 0–100 + exit-risk; không có Entry/SL/TP tuyệt đối")
    module_path = "strategies._legacy.s07_legacy"

    def module(self):
        return importlib.import_module(self.module_path)

    def default_config(self) -> Dict[str, Any]:
        mod = self.module()
        d = {k: v for k, v in mod.SCAN_CFG.items() if isinstance(v, (int, float, bool))}
        d["LOOKBACK_DAYS"] = mod.LOOKBACK_DAYS
        return d

    def prepare(self, ctx: ScanContext):
        mod = self.module()
        as_of = ctx.store.latest_session()
        if as_of is None:
            raise DataError("Chưa xác định được phiên giao dịch gần nhất (thiếu VNINDEX)")
        cfg = copy.deepcopy(mod.SCAN_CFG)
        for k, v in ctx.overrides.get("S7", {}).items():
            if k == "LOOKBACK_DAYS":
                mod.LOOKBACK_DAYS = int(v)
            elif k in cfg:
                cfg[k] = type(cfg[k])(v)
        # `scan_one_symbol` gọi `_call_data_layer` như một global của module -> gắn bản dùng store.
        mod._call_data_layer = lambda symbol, lookback_days=420, as_of=None, _s=ctx.store, _m=mod: \
            _prepare_frame(_m, _s, str(symbol).upper().strip(), as_of if as_of is not None else _s.latest_session(),
                           lookback_days)
        # PATCH B7 (mặc định tắt): xem config/legacy_flags.py
        if not hasattr(mod, "_orig_classify_signal"):
            mod._orig_classify_signal = mod.classify_signal
        if ctx.patches.get("s7_strong_buy_uses_strong_buy_score", False):
            orig = mod._orig_classify_signal

            def patched(alpha_score, p_tp, exit_risk, market_regime, cfg_):
                s = orig(alpha_score, p_tp, exit_risk, market_regime, cfg_)
                return "BUY" if (s == "STRONG_BUY" and alpha_score < cfg_["strong_buy_score"]) else s
            mod.classify_signal = patched
        else:
            mod.classify_signal = mod._orig_classify_signal
        # Benchmark & regime — sao `_fetch_benchmark_until_latest` (cần >= 220 dòng cho MA200).
        bench = _prepare_frame(mod, ctx.store, BENCHMARK, as_of, mod.LOOKBACK_DAYS)
        if len(bench) < 220:
            raise DataError(f"Benchmark {BENCHMARK} chỉ có {len(bench)} dòng; cần >= 220 cho MA200/regime")
        as_of_ts = pd.Timestamp(bench["time"].max()).normalize()
        bench = bench[bench["time"] <= as_of_ts].copy()
        market = mod.detect_market_regime(bench)
        market["as_of"] = as_of_ts
        return dict(mod=mod, cfg=cfg, bench=bench, market=market, as_of=as_of_ts)

    def prep_summary(self, prep) -> Dict[str, Any]:
        m = prep["market"]
        return {"regime": m.get("regime"), "label": m.get("reason", ""), "score": m.get("score"),
                "vnindex": m.get("close"), "as_of": str(prep["as_of"].date())}

    def run_symbol(self, symbol: str, prep, ctx: ScanContext) -> StrategyResult:
        mod = prep["mod"]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                r = mod.scan_one_symbol(symbol, prep["bench"], prep["market"], cfg=prep["cfg"], as_of=prep["as_of"])
            return self.map_result(r, symbol, ctx)
        except Exception as e:  # noqa: BLE001
            return StrategyResult("S7", symbol, "ERROR", ctx.mode, "—", ERROR,
                                  warnings=[f"{type(e).__name__}: {str(e)[:200]}"],
                                  extra={"traceback": traceback.format_exc()[-1500:]})

    def map_result(self, r: dict, symbol: str, ctx: ScanContext) -> StrategyResult:
        status, native = r.get("status"), str(r.get("signal", ""))
        notes = [LEGACY_NOTES["B8"],
                 "B7: bản gốc — mọi alpha ≥ 70 đều thành STRONG_BUY (BUY không xuất hiện); strong_buy_score/min_p_tp không được dùng.",
                 "Giá S7 đã quy đổi VND (KBS nghìn đồng ×1000) — khác đơn vị S1–S6."]
        if status == "ERROR":
            err = str(r.get("error", ""))
            st, sg = ("NO_DATA", NO_DATA) if "Unable to load OHLCV" in err else ("ERROR", ERROR)
            return StrategyResult("S7", symbol, st, ctx.mode, native, sg, warnings=[err[:200]], legacy_notes=notes,
                                  extra=clean(r))
        if status == "FILTERED":
            return StrategyResult("S7", symbol, "FILTERED", ctx.mode, native, FILTERED, score_scale=100,
                                  price=r.get("last_price"), failed_conditions=[native], legacy_notes=notes, extra=clean(r))
        return StrategyResult(
            "S7", symbol, "OK", ctx.mode, native, _SIG.get(native, NONE),
            score=r.get("alpha_score"), score_scale=100, price=r.get("last_price"), setup=str(r.get("setup", "")),
            sl_pct=r.get("suggested_sl_pct"), tp_pct=r.get("suggested_tp_pct"),
            reasons=split_list(r.get("reasons"), ";"), warnings=split_list(r.get("warnings"), ";"),
            passed_conditions=split_list(r.get("reasons"), ";"), failed_conditions=[],
            legacy_notes=notes, extra=clean(r))
