"""
Adapter chạy các engine notebook GỐC (S1–S6) bên trong app.

Ý tưởng cốt lõi: code notebook được chạy NGUYÊN VĂN; chỉ thay 2 thứ ở rìa:
  1. DataLayer: nguồn dữ liệu chuyển từ gọi API trực tiếp sang OHLCVStore (cache, 1 lần/mã),
     nhưng vẫn dùng lại chính hàm `_clean` + logic cắt cửa sổ của notebook (nên hiệu ứng ffill/bfill,
     lookback tính theo ngày lịch/số dòng... giữ y hệt — xem audit B11, L3).
  2. `datetime.today()` được "đóng băng" ở ngày phiên hoàn chỉnh gần nhất (as_of) để cửa sổ dữ liệu
     tái lập được và không phụ thuộc giờ chạy.
Vòng lặp scan (`QuantEngine.run`) của notebook được thay bằng runner của app; phần khởi tạo
(regime -> weights -> min_score -> df_vni) được sao đúng thứ tự trong `prepare`.
"""
from __future__ import annotations
import contextlib, dataclasses, importlib, io, traceback
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from .base import (BaseStrategy, ScanContext, StrategyResult, NO_DATA, ERROR)
from data.store import DataError, BENCHMARK


def frozen_datetime(as_of):
    """Lớp datetime có today()/now() cố định ở as_of (thay cho `datetime` trong module legacy)."""
    y, m, d = as_of.year, as_of.month, as_of.day

    class FrozenDT(datetime):
        @classmethod
        def today(cls):
            return cls(y, m, d)

        @classmethod
        def now(cls, tz=None):
            return cls(y, m, d, 15, 0)
    return FrozenDT


def make_store_datalayer(mod, store, true_ma200: bool):
    """Sinh subclass DataLayer của notebook, lấy dữ liệu từ store thay vì gọi API."""
    class StoreDataLayer(mod.DataLayer):
        def _slice(self, sym, start, end):
            try:
                raw = store.get_raw(sym)
            except DataError:
                return None
            t = pd.to_datetime(raw["time"])
            out = raw[(t >= pd.Timestamp(start)) & (t <= pd.Timestamp(end))]
            out = out.drop(columns=["_src"], errors="ignore")
            return out.reset_index(drop=True) if len(out) else None

        # S1–S4 gọi _v4/_v3 theo từng source; S5/S6 gọi _fetch_v4. Ghi đè cả ba, cùng trỏ vào store.
        def _v4(self, sym, start, end, src):
            return self._slice(sym, start, end)

        def _v3(self, sym, start, end, src):
            return None

        def _fetch_v4(self, sym, start, end, src):
            return self._slice(sym, start, end)

        def fetch(self, symbol, days):
            # PATCH B1 (mặc định TẮT): RegimeEngine gốc gọi fetch("VNINDEX", days=60) nên MA200 không bao giờ tồn tại.
            if true_ma200 and symbol == BENCHMARK and days == 60:
                days = 400
            return super().fetch(symbol, days)

    return StoreDataLayer


class LegacyEngineStrategy(BaseStrategy):
    """Lớp cơ sở cho S1–S6: bọc QuantEngine của notebook."""
    module_path: str = ""
    weights_fn: str = "get_dynamic_weights"
    min_score_fn: str = "get_min_score"
    uses_wr_mult: bool = True
    cfg_defaults: Dict[str, Any] = {}          # khác biệt có chủ đích so với QuantConfig (vd. B6 cho S3/S4)

    def module(self):
        return importlib.import_module(self.module_path)

    # ── cấu hình ─────────────────────────────────────────────────────────────
    def default_config(self) -> Dict[str, Any]:
        mod = self.module()
        cfg = mod.QuantConfig(**self.cfg_defaults)
        d = dataclasses.asdict(cfg)
        return {k: v for k, v in d.items() if isinstance(v, (int, float, bool)) and k != "capital"}

    def build_cfg(self, ctx: ScanContext):
        mod = self.module()
        cfg = mod.QuantConfig(**self.cfg_defaults)
        for k, v in ctx.overrides.get(self.info.sid, {}).items():
            if hasattr(cfg, k):
                setattr(cfg, k, type(getattr(cfg, k))(v))
        cfg.capital = ctx.capital
        return cfg

    def before_engine(self, mod, cfg, ctx: ScanContext) -> None:
        """Hook cho vá lỗi riêng (vd. S3 Hold)."""

    # ── vòng đời ─────────────────────────────────────────────────────────────
    def prepare(self, ctx: ScanContext):
        mod = self.module()
        as_of = ctx.store.latest_session()
        if as_of is None:
            raise DataError("Chưa xác định được phiên giao dịch gần nhất (thiếu VNINDEX)")
        mod.datetime = frozen_datetime(as_of)
        cfg = self.build_cfg(ctx)
        self.before_engine(mod, cfg, ctx)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            engine = mod.QuantEngine(capital=ctx.capital, cfg=cfg)
            DL = make_store_datalayer(mod, ctx.store, bool(ctx.patches.get("regime_true_ma200", False)))
            dl = DL(cfg)
            engine.dl = dl
            engine.regime.dl = dl          # RegimeEngine giữ tham chiếu DataLayer riêng -> phải thay cả hai
            rctx = engine.regime.detect()
            weights = getattr(engine.regime, self.weights_fn)()
            min_score = getattr(engine.regime, self.min_score_fn)(ctx.mode, cfg)
            df_vni = dl.fetch(BENCHMARK, cfg.lookback_short)
        return dict(engine=engine, cfg=cfg, weights=weights, r_mult=rctx["score_mult"],
                    wr_mult=rctx.get("wr_mult", 1.0), min_score=min_score, df_vni=df_vni,
                    regime=rctx, log=buf.getvalue())

    def prep_summary(self, prep) -> Dict[str, Any]:
        r = prep["regime"]
        return {"regime": str(r.get("regime", "?")).upper(), "label": r.get("label", ""),
                "score_mult": r.get("score_mult"), "min_score": prep["min_score"],
                "vnindex": r.get("vnindex"), "mom5": r.get("mom5"), "atr_pct": r.get("atr_pct")}

    def call_pipeline(self, prep, symbol: str, ctx: ScanContext):
        eng = prep["engine"]
        if self.uses_wr_mult:
            return eng.run_pipeline(symbol, prep["df_vni"], ctx.mode, prep["weights"], prep["r_mult"],
                                    prep["min_score"], prep["wr_mult"])
        return eng.run_pipeline(symbol, prep["df_vni"], ctx.mode, prep["weights"], prep["r_mult"],
                                prep["min_score"], ctx.avg_cost)

    def run_symbol(self, symbol: str, prep, ctx: ScanContext) -> StrategyResult:
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rec = self.call_pipeline(prep, symbol, ctx)
            if rec is None:
                return StrategyResult(self.info.sid, symbol, "NO_DATA", ctx.mode, "—", NO_DATA,
                                      warnings=["Thiếu dữ liệu / không đủ lịch sử theo yêu cầu tối thiểu của notebook"])
            res = self.map_result(rec, symbol, ctx)
            res.extra["_stdout"] = buf.getvalue()[-500:]
            return res
        except Exception as e:  # noqa: BLE001 — một mã lỗi không được làm sập cả scan
            return StrategyResult(self.info.sid, symbol, "ERROR", ctx.mode, "—", ERROR,
                                  warnings=[f"{type(e).__name__}: {str(e)[:200]}"],
                                  extra={"traceback": traceback.format_exc()[-1500:]})

    def map_result(self, rec: dict, symbol: str, ctx: ScanContext) -> StrategyResult:
        raise NotImplementedError
