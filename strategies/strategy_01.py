"""
S1 — VN Quant Engine v5.5 (Ichimoku đa khung + T+ target >= 9%)   [Dòng A]

# Source Notebook : Tool_CK_Claude_v1.ipynb
# Section         : Production scanner — QuantEngine.run_pipeline (Cell 1–13 của notebook)
# Production logic: strategies/_legacy/s01_legacy.py (nguyên văn); file này chỉ là adapter.

Triết lý (theo notebook): chấm điểm 0–10 nhiều indicator có trọng số, điều chỉnh theo regime VNINDEX;
dòng tiền VSA + Ichimoku D/W/M; hai chế độ swing (T+) / hold; lọc rủi ro cứng trước, điểm sau.

Ánh xạ tín hiệu (CHỈ để hiển thị/đồng thuận — nhãn gốc luôn được giữ ở native_signal):
    "Khuyến nghị Mua Mới" (new_buy_tag) = 🟢 MUA -> BUY (STRONG_BUY nếu verdict có "MẠNH")
                                          🟡 QUAN SÁT -> WATCH,  ❌ BỎ QUA -> NONE
    verdict "🚫 BỊ LỌC" -> FILTERED
WHY dùng new_buy_tag: đây là nhãn CUỐI của notebook cho quyết định mở vị thế mới và đã gộp `_ok`
(hard filter + min_score theo regime + R:R) — không phải tự tôi chế ra điều kiện.
"""
from __future__ import annotations
from .base import StrategyInfo, StrategyResult, STRONG_BUY, BUY, WATCH, NONE, FILTERED
from .legacy_adapter import LegacyEngineStrategy
from .mapping import to_float, split_list, clean
from config.legacy_flags import LEGACY_NOTES


def map_family_a(sid: str, rec: dict, symbol: str, ctx) -> StrategyResult:
    """Dùng chung cho S1 và S2 (cùng cấu trúc output)."""
    verdict, tag = str(rec.get("Tín hiệu", "")), str(rec.get("Khuyến nghị Mua Mới", ""))
    if "BỊ LỌC" in verdict:
        sig = FILTERED
    elif tag.startswith("🟢"):
        sig = STRONG_BUY if "MẠNH" in verdict else BUY
    elif tag.startswith("🟡"):
        sig = WATCH
    else:
        sig = NONE
    swing = ctx.mode == "swing"
    warnings = []
    action = str(rec.get("Action", ""))
    if action and not action.startswith("✅"):
        warnings.append(action)
    if rec.get("_atr_low"):
        warnings.append("ATR% thấp hơn min_atr_pct — biên độ hẹp cho T+")
    for k in ("PK RSI (Composite)", "Cảnh báo DG", "Theo dõi PK/DG"):     # chỉ có ở S2
        v = str(rec.get(k, "—"))
        if v not in ("—", ""):
            warnings.append(f"{k}: {v}")
    notes = [LEGACY_NOTES["B1"], "B2: `_ok` dùng min_rr=1.5 nhưng chuỗi Action dùng min_rr_swing=2.0.",
             LEGACY_NOTES["B3"], LEGACY_NOTES["B4"].format(basis="T2 = (T2 − entry)/risk"), LEGACY_NOTES["B16"]]
    return StrategyResult(
        sid=sid, symbol=symbol, status="FILTERED" if sig == FILTERED else "OK", mode=ctx.mode,
        native_signal=f"{verdict} | {tag}", signal=sig,
        score=to_float(rec.get("Score")), score_scale=10, price=to_float(rec.get("Giá")),
        setup=f"{rec.get('Entry zone', '')} · {rec.get('Khuyến nghị', '')}",
        entry=rec.get("_entry_raw"), stop_loss=rec.get("_sl_raw"),
        take_profit=rec.get("_tp1_raw"), take_profit_2=rec.get("_tp2_raw"),
        risk_reward=to_float(rec.get("T+ R:R" if swing else "Hold R:R")), rr_basis="T2",
        holder_advice=f"{rec.get('Khuyến nghị Hold', '')} — {rec.get('Lý do Hold', '')}".strip(" —"),
        reasons=split_list(rec.get("_positives")), warnings=warnings,
        passed_conditions=split_list(rec.get("_positives")),      # chỉ trình bày lại sub-score >= 6.5 do notebook tự in
        failed_conditions=split_list(rec.get("Lý do")),
        legacy_notes=notes, extra=clean(rec))


class Strategy01(LegacyEngineStrategy):
    info = StrategyInfo("S1", "VN Quant Engine v5.5", "A", "Tool_CK_Claude_v1.ipynb", True,
                        "Ichimoku đa khung + VSA + DMI/Aroon; R:R theo T2")
    module_path = "strategies._legacy.s01_legacy"

    def map_result(self, rec, symbol, ctx):
        return map_family_a("S1", rec, symbol, ctx)
