"""
Chỗ dành cho indicator/engine dùng chung ĐÃ CHỨNG MINH GIỐNG HỆT giữa các notebook
(theo audit: VSAEngine, VolumeDryupDetector, luật Regime, PositionSizer của S1–S4).

Hiện tại để TRỐNG có chủ đích: mỗi strategy chạy engine gốc nguyên văn (strategies/_legacy/*), nên không cần
trùng lặp/tách code. Chỉ thêm module vào đây khi CÓ test golden chứng minh hai bản cho kết quả y hệt —
KHÔNG gộp RSI/RS/ATR (khác công thức giữa các notebook, xem audit B10–B12).
"""
