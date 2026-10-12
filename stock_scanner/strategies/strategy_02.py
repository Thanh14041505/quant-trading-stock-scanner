"""
S2 — VN Quant Engine v5.7 (S1 + Composite RSI Divergence + Dao Găm advisor)   [Dòng A]

# Source Notebook : Tool_CK_Claude_v1_1.ipynb
# Section         : Production scanner — QuantEngine.run_pipeline (Cell 1–13 + 5e + 10c)
# Production logic: strategies/_legacy/s02_legacy.py (nguyên văn).

Khác S1: `cd_replace_legacy_rsi_div=True` (mặc định) GHI ĐÈ rsi_bull/bear_div cũ bằng phân kỳ Composite
=> Scoring/Entry/Levels nhận đầu vào khác S1 dù code Scoring giống hệt. Vì vậy S2 vẫn là một strategy riêng.
Ánh xạ tín hiệu: giống S1 (new_buy_tag sau khi DivergenceAdvisor.adjust_buy_tag điều chỉnh).
Backtester và divergence_study của notebook KHÔNG thuộc production nên không được port.
"""
from .base import StrategyInfo
from .legacy_adapter import LegacyEngineStrategy
from .strategy_01 import map_family_a


class Strategy02(LegacyEngineStrategy):
    info = StrategyInfo("S2", "VN Quant Engine v5.7", "A", "Tool_CK_Claude_v1_1.ipynb", True,
                        "S1 + phân kỳ RSI-Composite + Dao Găm D/W/M")
    module_path = "strategies._legacy.s02_legacy"

    def map_result(self, rec, symbol, ctx):
        return map_family_a("S2", rec, symbol, ctx)
