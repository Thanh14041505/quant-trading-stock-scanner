"""
Gom các tham số TRÙNG TÊN giữa nhiều strategy thành một mục "dùng chung" trên sidebar, để chỉnh một lần
áp dụng cho tất cả — thay vì phải mở từng strategy để sửa từng cái dù chúng cùng ý nghĩa/giá trị.

QUAN TRỌNG (đọc trước khi dùng): hai strategy có thể dùng CÙNG TÊN tham số nhưng ĐỊNH NGHĨA/ĐƠN VỊ GỐC
khác nhau (xem audit B9–B12, ví dụ `lookback_short` là NGÀY LỊCH ở S1–S4 nhưng là SỐ PHIÊN ở S5–S6).
Gom theo tên là lựa chọn của bạn (bạn đã tự đồng bộ các giá trị này) — việc gom này chỉ giúp SỬA NHANH,
nó không thay đổi cách mỗi strategy DIỄN GIẢI con số đó. Sidebar vẫn hiện rõ default GỐC của từng
strategy để bạn biết mình đang ghi đè gì.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any, Dict, List, Tuple

# Nhóm theo từ khoá xuất hiện trong TÊN tham số, xét theo thứ tự ưu tiên trên xuống (khớp nhóm đầu tiên).
# Thêm nhóm/từ khoá mới tại đây nếu sau này có Strategy 9, 10… với tên tham số mới.
GROUPS: List[Tuple[str, List[str]]] = [
    ("📊 Dữ liệu & thanh khoản", ["lookback_short", "lookback_long", "lookback_weekly",
                                  "min_avg_vol", "min_avg_val", "min_history", "delay_sec"]),
    ("🎯 Ngưỡng điểm & tín hiệu", ["min_score", "min_rr", "buy_score", "strong_buy_score", "watch_score",
                                  "reduce_score", "min_profit_pct", "min_tp_pct", "min_atr_pct", "exit_risk",
                                  "require_market_confirmation", "allow_new_long_in_bear", "min_p_tp", "strong_p_tp"]),
    ("💰 Entry / Risk / Sizing", ["entry_", "risk_per_trade", "kelly_fraction", "max_position_pct",
                                  "partial_tp_pct", "atr_sl", "rr_target"]),
    ("☁️ Ichimoku & Dao Găm", ["ichi_", "dao_gam"]),
    ("📦 Volume Profile & Squeeze", ["vp_bins", "bb_", "squeeze"]),
    ("🩸 VSA / Dry-up / Win-rate", ["dryup", "wr_base", "wr_"]),
    ("📈 DMI / Aroon / MA / Trend", ["dmi_", "aroon", "ma_", "adx_"]),
    ("🧮 Hệ số chấm điểm nội bộ", ["sc_", "_score_offset", "_score_scale", "score_offset", "score_scale",
                                   "_scale", "_shift", "_base", "_bonus", "_mult", "cmf_score", "ema_score",
                                   "vol_score", "obv_slope", "macd_", "div_", "hidden_acc", "stoch_"]),
    ("🔧 Khác", []),  # mọi tham số còn lại rơi vào đây
]


def _group_of(name: str) -> str:
    low = name.lower()
    for label, keywords in GROUPS:
        if not keywords:  # nhóm "Khác" luôn khớp cuối cùng
            return label
        if any(kw in low for kw in keywords):
            return label
    return GROUPS[-1][0]


def build_shared_groups(defaults_by_sid: Dict[str, Dict[str, Any]]) -> Dict[str, List[Tuple[str, Dict[str, Any]]]]:
    """
    defaults_by_sid: {sid: {param_name: default_value}} — thường là default_config() của các strategy ĐANG CHỌN.
    Trả về: {group_label: [(param_name, {sid: default_value_gốc}), ...]} — CHỈ gồm tham số xuất hiện ở >= 2 strategy.
    Tham số chỉ có ở 1 strategy KHÔNG nằm trong đây — vẫn sửa ở mục "Tham số riêng từng Strategy" như cũ.
    """
    occ: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for sid, params in defaults_by_sid.items():
        for name, val in params.items():
            occ[name][sid] = val
    grouped: Dict[str, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
    for name, by_sid in occ.items():
        if len(by_sid) >= 2:
            grouped[_group_of(name)].append((name, by_sid))
    for label in grouped:
        grouped[label].sort(key=lambda t: t[0])
    return dict(grouped)


def representative_default(by_sid: Dict[str, Any]):
    """Giá trị đại diện hiển thị ban đầu cho widget dùng chung: lấy theo sid nhỏ nhất (S1 trước S2 trước...)."""
    sid = min(by_sid, key=lambda s: (len(s), s))
    return by_sid[sid]
