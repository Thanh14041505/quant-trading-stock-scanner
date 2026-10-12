"""
S6 — VN Quant Engine v8+ (PR016 enhanced): S5 + Hidden Divergence RSI/MACD   [Dòng C]

# Source Notebook : Tool_CK_Grok_v2_PR016_enhanced_v2.ipynb
# Section         : Production scanner — QuantEngine.run_pipeline (Cell 1–19)
# Production logic: strategies/_legacy/s06_legacy.py (nguyên văn).

Theo diff từng cell: ScoringEngine/PositionSizer/IchimokuEngine/RegimeEngine giống hệt S5; khác ở classify_horizon
(hidden divergence) và nhãn phân kỳ => Score/Tín hiệu/Entry/SL/TP nhiều khả năng trùng S5 (Consensus dùng `family` C để
không đếm đôi). Ánh xạ tín hiệu: giống S5.
"""
from .base import StrategyInfo
from .legacy_adapter import LegacyEngineStrategy
from .strategy_05 import map_family_c
from data import fundamentals


class Strategy06(LegacyEngineStrategy):
    info = StrategyInfo("S6", "VN Quant Engine v8+ (Hidden Div)", "C",
                        "Tool_CK_Grok_v2_PR016_enhanced_v2.ipynb", True,
                        "S5 + Hidden Divergence RSI/MACD")
    module_path = "strategies._legacy.s06_legacy"
    weights_fn, min_score_fn, uses_wr_mult = "dynamic_weights", "min_score", False

    def prepare(self, ctx):
        prep = super().prepare(ctx)
        fundamentals.install_cache(prep["engine"], ctx.mode, ctx.patches.get("fundamental_in_swing", False))
        return prep

    def map_result(self, rec, symbol, ctx):
        return map_family_c("S6", rec, symbol, ctx)
