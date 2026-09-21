"""
Các "bản vá" cho bug/khác biệt tìm thấy khi audit (mã B*/L* trong audit_7_notebooks.md).

CHÍNH SÁCH: mặc định = HÀNH VI GỐC của notebook (ưu tiên số 1 của dự án). Vá lỗi chỉ khi người dùng bật.
Ngoại lệ có chủ đích: PATCH_DROP_INCOMPLETE_CANDLE (L4) mặc định BẬT vì đây là yêu cầu "không look-ahead"
(nến chưa đóng là dữ liệu chưa hoàn chỉnh), và PATCH_S3_HOLD_CFG (B5) mặc định BẬT vì nếu không thì
S3 ở mode Hold sẽ crash (AttributeError) — dùng đúng giá trị mà S4 (bản kế tiếp) đã đặt.
"""

PATCHES = {
    "regime_true_ma200": dict(
        default=False, ids="B1", strategies="S1–S6",
        label="Regime dùng MA200 thật (VNINDEX 400 ngày thay vì 60)",
        why="Notebook fetch VNINDEX 60 ngày nên nhánh MA200 luôn rơi về EMA30. Bật để dùng MA200 thật.",
    ),
    "s7_strong_buy_uses_strong_buy_score": dict(
        default=False, ids="B7", strategies="S7",
        label="S7: STRONG_BUY dùng ngưỡng strong_buy_score (85) thay vì strong_p_tp×100 (65)",
        why="Ở bản gốc BUY không bao giờ xuất hiện (mọi alpha>=70 đều thành STRONG_BUY).",
    ),
    "drop_incomplete_candle": dict(
        default=True, ids="L4", strategies="S1–S7",
        label="Bỏ nến ngày hôm nay nếu thị trường chưa đóng cửa (15:00)",
        why="Tránh dùng nến chưa hoàn chỉnh. Tắt để mô phỏng đúng notebook khi chạy giữa phiên.",
    ),
    "s3_hold_cfg": dict(
        default=True, ids="B5", strategies="S3",
        label="S3 mode Hold: bổ sung min_score_hold=6.3, min_rr_hold=3.0 (giá trị của S4)",
        why="QuantConfig của S3 thiếu 2 field này nên mode Hold gốc bị AttributeError.",
    ),
}

# Cảnh báo luôn gắn vào kết quả (dù patch bật hay tắt) để người dùng biết logic gốc có điểm yếu gì.
LEGACY_NOTES = {
    "B1": "Regime gốc dùng EMA30 thay MA200 (VNINDEX chỉ 60 ngày) — ảnh hưởng weights/score multiplier/min_score.",
    "B3": "Target T1 bị nâng tối thiểu ≥ +9% theo config — R:R có thể đẹp hơn thực tế.",
    "B4": "R:R của strategy này tính theo {basis}; các strategy khác có thể tính theo target khác.",
    "B6": "TPlusQuantEngine gốc: risk_per_trade=0.8% KHÔNG tới PositionSizer; hiệu lực thực tế = min_score 6.2, risk 1%.",
    "B8": "S7 không có Entry/SL/TP tuyệt đối/R:R/sizing — chỉ có % gợi ý.",
    "B16": "Win-rate/Kelly sizing dựa trên heuristic, không phải xác suất thực nghiệm.",
}
