"""
S4 — VN Quant Engine v5.6 (S3 + RSI/Composite Index Divergence D1/W1/M1)   [Dòng B]

# Source Notebook : Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb
# Section         : Production scanner — QuantEngine.run_pipeline (Cell 1–13, gồm 4B RSIDivergenceEngine)
# Production logic: strategies/_legacy/s04_legacy.py (nguyên văn).

Khác S3: sub-score `rsi_divergence` (weight 8), pivot xác nhận sau lbR=5 phiên (chủ đích tránh look-ahead),
divergence_advice, validate_quant_config (nên Hold chạy được). Ánh xạ tín hiệu: giống S3.
"""
from .base import StrategyInfo
from .legacy_adapter import LegacyEngineStrategy
from .strategy_03 import map_family_b


class Strategy04(LegacyEngineStrategy):
    info = StrategyInfo("S4", "v5.6 RSI Divergence + Dao Găm", "B",
                        "Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb", True,
                        "S3 + phân kỳ Composite Index D1/W1/M1")
    module_path = "strategies._legacy.s04_legacy"
    cfg_defaults = {"min_score_swing": 6.2}          # B6 (xem strategy_03)

    def map_result(self, rec, symbol, ctx):
        return map_family_b("S4", rec, symbol, ctx)
