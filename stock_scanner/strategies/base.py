"""
Khung chung cho 7 strategy.

Mỗi strategy là một "bộ não" ĐỘC LẬP: nhận cùng một ScanContext (dữ liệu + cấu hình) nhưng tự
diễn giải theo logic của notebook gốc và trả về StrategyResult.

Quy ước quan trọng:
  * `native_signal`  = nhãn GỐC của notebook, KHÔNG BAO GIỜ bị sửa.
  * `signal`         = nhãn CHUẨN HOÁ chỉ để hiển thị ma trận/đồng thuận (mapping ghi rõ trong từng strategy).
  * Field nào notebook không có thì để None — KHÔNG tự tạo logic thay thế.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Tập nhãn chuẩn hoá (dùng cho Matrix/Consensus).
STRONG_BUY, BUY, WATCH, NONE = "STRONG_BUY", "BUY", "WATCH", "NONE"
REDUCE, EXIT, FILTERED, NO_DATA, ERROR, UNSUPPORTED = "REDUCE", "EXIT", "FILTERED", "NO_DATA", "ERROR", "UNSUPPORTED"
SHORT = {STRONG_BUY: "SB", BUY: "B", WATCH: "W", NONE: "N", REDUCE: "R", EXIT: "X",
         FILTERED: "F", NO_DATA: "–", ERROR: "E", UNSUPPORTED: "U"}
BULLISH = {STRONG_BUY, BUY}
BEARISH = {REDUCE, EXIT}
ACTIVE = {STRONG_BUY, BUY, WATCH, NONE, REDUCE, EXIT}   # có tham gia đồng thuận (đã có đánh giá thật)


@dataclass
class StrategyInfo:
    sid: str                 # "S1"…"S7"
    name: str
    family: str              # A/B/C/D — dòng dõi code (xem audit), dùng để tránh đếm đôi
    notebook: str
    supports_hold: bool = True
    note: str = ""


@dataclass
class StrategyResult:
    sid: str
    symbol: str
    status: str = "OK"                       # OK | FILTERED | NO_DATA | ERROR | UNSUPPORTED
    mode: str = "swing"
    native_signal: str = "—"
    signal: str = NO_DATA
    score: Optional[float] = None
    score_scale: int = 10
    price: Optional[float] = None
    setup: str = ""
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None      # T1
    take_profit_2: Optional[float] = None    # T2 (nếu notebook có)
    risk_reward: Optional[float] = None
    rr_basis: str = ""                       # "T1" | "T2" | "" — R:R tính theo target nào (audit B4)
    sl_pct: Optional[float] = None           # chỉ S7 (notebook chỉ cho %)
    tp_pct: Optional[float] = None
    holder_advice: str = ""                  # lời khuyên cho người ĐANG giữ (trục riêng, không phải tín hiệu mua)
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    passed_conditions: List[str] = field(default_factory=list)   # chỉ trình bày lại `_positives` của notebook
    failed_conditions: List[str] = field(default_factory=list)   # filter cứng của notebook
    legacy_notes: List[str] = field(default_factory=list)        # bug/khác biệt (mã B1…B17) áp dụng
    extra: Dict[str, Any] = field(default_factory=dict)          # toàn bộ output gốc để đối chiếu

    @property
    def score_pct(self) -> Optional[float]:
        """Điểm quy về 0–100 CHỈ để so sánh hiển thị (không thay đổi điểm gốc)."""
        if self.score is None:
            return None
        return float(self.score) / self.score_scale * 100.0


@dataclass
class ScanContext:
    """Những thứ mọi strategy cần: store dữ liệu, mode, tham số người dùng, cờ vá lỗi."""
    store: Any
    mode: str = "swing"                       # "swing" | "hold"
    capital: float = 100_000_000
    overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)   # {"S1": {"min_score_swing": 5.5}, ...}
    patches: Dict[str, bool] = field(default_factory=dict)               # xem config/legacy_flags.py
    avg_cost: Optional[float] = None


class BaseStrategy:
    info: StrategyInfo

    def default_config(self) -> Dict[str, Any]:
        """Default của notebook (để UI hiển thị và cho phép chỉnh)."""
        return {}

    def prepare(self, ctx: ScanContext) -> Any:
        """Tính phần dùng chung cho cả lượt quét (regime, benchmark...). Có thể raise -> toàn strategy ERROR."""
        return None

    def run_symbol(self, symbol: str, prep: Any, ctx: ScanContext) -> StrategyResult:
        raise NotImplementedError

    def prep_summary(self, prep: Any) -> Dict[str, Any]:
        """Thông tin regime/context để Dashboard hiển thị."""
        return {}
