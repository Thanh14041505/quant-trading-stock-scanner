"""
S3 — VN Quant T+2.5 Swing Engine v5.3 (VSA + Volume Profile + Ichimoku ITP)   [Dòng B]

# Source Notebook : Tool_CK_Grok_v2.ipynb
# Section         : Production scanner — QuantEngine.run_pipeline (Cell 1–12)
# Production logic: strategies/_legacy/s03_legacy.py (nguyên văn).

Triết lý: chỉ mua T+ khi dòng tiền VSA tích cực và Ichimoku ITP (Trịnh Phát) cho target >= 9%, cắt lỗ <= 5%.

Ánh xạ tín hiệu (chỉ để hiển thị):
    _ok & verdict "MẠNH" -> STRONG_BUY;  _ok & "XEM XÉT" -> BUY
    verdict cao/THEO DÕI nhưng !_ok -> WATCH (kèm cảnh báo: chưa đạt R:R hoặc min_score theo regime)
    "YẾU"/"BỎ QUA" -> NONE;  "BỊ LỌC" -> FILTERED
WHY cần `_ok`: ở S3/S4 verdict chỉ dựa trên điểm; R:R gate và min_score theo regime nằm ở `_ok` (audit mục 2).

B6 (TPlusQuantEngine): hiệu lực THỰC của bản gốc là min_score_swing=6.2 và risk 1% (0.8% không tới PositionSizer),
nên cfg_defaults chỉ đặt min_score_swing=6.2 — khớp hành vi thực tế của notebook.
B5: S3 gốc thiếu min_score_hold/min_rr_hold -> mode Hold bị AttributeError; mặc định bổ sung giá trị của S4 (bật/tắt trong UI).
"""
from __future__ import annotations
from .base import StrategyInfo, StrategyResult, STRONG_BUY, BUY, WATCH, NONE, FILTERED
from .legacy_adapter import LegacyEngineStrategy
from .mapping import to_float, split_list, clean
from config.legacy_flags import LEGACY_NOTES


def map_family_b(sid: str, rec: dict, symbol: str, ctx) -> StrategyResult:
    """Dùng chung cho S3 và S4."""
    verdict, ok = str(rec.get("Tín hiệu", "")), bool(rec.get("_ok"))
    high = ("MẠNH" in verdict) or ("XEM XÉT" in verdict)
    warnings = []
    if "BỊ LỌC" in verdict:
        sig = FILTERED
    elif ok and "MẠNH" in verdict:
        sig = STRONG_BUY
    elif ok and "XEM XÉT" in verdict:
        sig = BUY
    elif high or "THEO DÕI" in verdict:
        sig = WATCH
        if high:
            warnings.append("Điểm đủ cao nhưng `_ok`=False (chưa đạt R:R hoặc min_score theo regime)")
    else:
        sig = NONE
    swing = ctx.mode == "swing"
    action = str(rec.get("Action", ""))
    # R:R của nhánh ITP tính theo T1; nhánh legacy (không có dữ liệu ITP) tính theo T2 (audit B4).
    itp_branch = swing and ("VSA+ITP" in action or "Chưa đạt chuẩn" in action)
    basis = "T1" if itp_branch else "T2"
    if action and not action.startswith("✅") and "SIÊU PHẨM" not in action:
        warnings.append(action)
    notes = [LEGACY_NOTES["B1"], LEGACY_NOTES["B3"] + " (S3/S4: nâng lên entry×1.095 nếu lãi < 9%)",
             LEGACY_NOTES["B4"].format(basis=f"{basis}"), LEGACY_NOTES["B6"], LEGACY_NOTES["B16"]]
    return StrategyResult(
        sid=sid, symbol=symbol, status="FILTERED" if sig == FILTERED else "OK", mode=ctx.mode,
        native_signal=f"{verdict} | {action}", signal=sig,
        score=to_float(rec.get("Score")), score_scale=10, price=to_float(rec.get("Giá")),
        setup=f"{rec.get('Entry zone', '')} · {rec.get('Khuyến nghị', '')}",
        entry=to_float(rec.get("Entry")),
        stop_loss=to_float(rec.get("SL T+" if swing else "SL Hold")),
        take_profit=to_float(rec.get("T+ T1" if swing else "Hold T1")),
        take_profit_2=to_float(rec.get("T+ T2" if swing else "Hold T2")),
        risk_reward=to_float(rec.get("T+ R:R" if swing else "Hold R:R")), rr_basis=basis,
        holder_advice=f"{rec.get('Holder Action', '')} — {rec.get('Holder Reason', '')}".strip(" —"),
        reasons=split_list(rec.get("_positives")), warnings=warnings,
        passed_conditions=split_list(rec.get("_positives")),
        failed_conditions=split_list(rec.get("Lý do")),
        legacy_notes=notes, extra=clean(rec))


class Strategy03(LegacyEngineStrategy):
    info = StrategyInfo("S3", "T+2.5 Swing v5.3 (VSA + ITP)", "B", "Tool_CK_Grok_v2.ipynb", True,
                        "Swing 3–10 ngày; Hold cần patch B5")
    module_path = "strategies._legacy.s03_legacy"
    uses_wr_mult = True
    cfg_defaults = {"min_score_swing": 6.2}          # B6 — xem docstring

    def before_engine(self, mod, cfg, ctx):
        if ctx.mode == "hold" and ctx.patches.get("s3_hold_cfg", True):
            for k, v in (("min_score_hold", 6.3), ("min_rr_hold", 3.0)):      # B5: giá trị của S4
                if not hasattr(cfg, k):
                    setattr(cfg, k, v)

    def map_result(self, rec, symbol, ctx):
        return map_family_b("S3", rec, symbol, ctx)
