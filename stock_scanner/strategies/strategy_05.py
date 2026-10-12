"""
S5 — VN Quant Engine v8 (PR016): Ichimoku D/W/M là trục chính, target theo kháng cự kỹ thuật   [Dòng C]

# Source Notebook : Tool_CK_Grok_v2_PR016.ipynb
# Section         : Production scanner — QuantEngine.run_pipeline (Cell 1–19)
# Production logic: strategies/_legacy/s05_legacy.py (nguyên văn). BacktestEngine (cell 20) chỉ được giữ vì
#                   QuantEngine.__init__ khởi tạo nó; app KHÔNG chạy backtest.

Không có VSA/DMI/WinRateEstimator. `verdict` đã gộp `ok` (passed ∧ score ≥ min_score(regime) ∧ R:R ≥ 1.5 ∧ T1% ≥ 9)
nên ánh xạ trực tiếp:  🔥/💎 -> STRONG_BUY,  ✅ -> BUY,  👀 -> WATCH,  ❌ -> NONE,  🚫 -> FILTERED.
`use_fundamental=True` (default notebook) gọi thêm API báo cáo tài chính mỗi mã; chỉ ảnh hưởng rs_score ở mode Hold.
"""
from __future__ import annotations
from .base import StrategyInfo, StrategyResult, STRONG_BUY, BUY, WATCH, NONE, FILTERED
from .legacy_adapter import LegacyEngineStrategy
from .mapping import to_float, split_list, clean
from config.legacy_flags import LEGACY_NOTES
from data import fundamentals


def map_family_c(sid: str, rec: dict, symbol: str, ctx) -> StrategyResult:
    """Dùng chung cho S5 và S6."""
    verdict = str(rec.get("Tín hiệu", ""))
    if "BỊ LỌC" in verdict:
        sig = FILTERED
    elif "🔥" in verdict or "💎" in verdict:
        sig = STRONG_BUY
    elif "✅" in verdict:
        sig = BUY
    elif "👀" in verdict:
        sig = WATCH
    else:
        sig = NONE
    swing = ctx.mode == "swing"
    warnings = []
    for k in ("_bear_div_warn", "DG Gợi Ý", "Trạng Thái MA"):
        v = str(rec.get(k, "") or "")
        if v and v != "—" and not v.startswith("🟢"):
            warnings.append(v)
    if not swing:
        warnings.append("Mode Hold: notebook chỉ trả SL của lệnh swing (không có SL hold riêng trong output).")
    fa_missing = (not swing) and str(rec.get("_fa_note", "")) == "—"
    if fa_missing:
        warnings.append("Không lấy được Fundamental (lỗi/hết thời gian API) → dùng điểm trung tính 5.0 (ảnh hưởng rs_score ở mode Hold)")
    notes = [LEGACY_NOTES["B1"], LEGACY_NOTES["B3"] + " (S5/S6: nếu không có kháng cự ≥ 9% thì lấy kháng cự xa nhất hoặc entry×1.09–1.11)",
             LEGACY_NOTES["B4"].format(basis="T1 = (T1 − entry)/risk"), LEGACY_NOTES["B16"]]
    if swing and not ctx.patches.get("fundamental_in_swing", False):
        notes.append("P1: mode Swing không tải Fundamental (cột FA Score = 5.0 trung tính); điểm Fundamental chỉ ảnh hưởng score ở mode Hold.")
    return StrategyResult(
        sid=sid, symbol=symbol, status="FILTERED" if sig == FILTERED else "OK", mode=ctx.mode,
        native_signal=verdict, signal=sig,
        score=to_float(rec.get("Score")), score_scale=10, price=to_float(rec.get("Giá")),
        setup=f"{rec.get('Entry Zone', '')} · {rec.get('Horizon', '')}",
        entry=to_float(rec.get("Entry")), stop_loss=to_float(rec.get("SL")),
        take_profit=to_float(rec.get("T+ T1" if swing else "Hold T1")),
        take_profit_2=to_float(rec.get("T+ T2" if swing else "Hold T2")),
        risk_reward=to_float(rec.get("T+ R:R" if swing else "Hold R:R")), rr_basis="T1",
        holder_advice=f"{rec.get('Khuyến Nghị Hold', '')} — {rec.get('Lý Do Hold', '')}".strip(" —"),
        reasons=split_list(rec.get("_positives")) + ([f"Ichimoku: {rec.get('Ichimoku')}"] if rec.get("Ichimoku") else []),
        warnings=warnings, passed_conditions=split_list(rec.get("_positives")),
        failed_conditions=split_list(rec.get("Lý do")), legacy_notes=notes, extra=clean(rec))


class Strategy05(LegacyEngineStrategy):
    info = StrategyInfo("S5", "VN Quant Engine v8 (PR016)", "C", "Tool_CK_Grok_v2_PR016.ipynb", True,
                        "Ichimoku D/W/M + Dao Găm; target theo kháng cự; R:R theo T1")
    module_path = "strategies._legacy.s05_legacy"
    weights_fn, min_score_fn, uses_wr_mult = "dynamic_weights", "min_score", False

    def prepare(self, ctx):
        prep = super().prepare(ctx)
        # Không cho notebook gọi API Fundamental trong vòng lặp scan (nguyên nhân chậm) — xem data/fundamentals.py
        fundamentals.install_cache(prep["engine"], ctx.mode, ctx.patches.get("fundamental_in_swing", False))
        return prep

    def map_result(self, rec, symbol, ctx):
        return map_family_c("S5", rec, symbol, ctx)
