"""
Resample OHLCV ngày -> Tuần/Tháng để phân tích SMC trên khung lớn (theo yêu cầu: "nhìn tổng thể đồ thị
rộng rộng xíu, đừng tính SMC mấy đoạn nhỏ nhỏ" — khung ngày dễ nhiễu bởi dao động vài phiên; khung
Tuần/Tháng mới phản ánh đúng cấu trúc "tổ chức" đang tích luỹ/phân phối).

Resample chuẩn OHLC (open=đầu kỳ, high=max, low=min, close=cuối kỳ, volume=tổng), nhân quả tuyệt đối
(chỉ gộp các nến NGÀY đã có, không có thông tin tương lai). Nến của kỳ hiện tại (tuần/tháng CHƯA kết
thúc) vẫn được giữ lại — nó chỉ dùng dữ liệu THỰC đã có tới hôm nay, không phải nhìn trước; cơ chế xác
nhận swing (cần `right` nến sau) trong `smc.py` tự động không bao giờ biến nến chưa đóng này thành một
swing đã xác nhận, nên không cần cắt bỏ thủ công.
"""
from __future__ import annotations
import pandas as pd

_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """df cần cột 'time' (datetime) + open/high/low/close/volume, đã sắp tăng dần. rule: 'W-FRI' (tuần,
    kết thúc thứ Sáu — đúng lịch giao dịch VN) hoặc 'ME' (tháng)."""
    x = df.set_index("time").resample(rule, label="right", closed="right").agg(_AGG).dropna(subset=["close"])
    x = x.reset_index()
    return x
