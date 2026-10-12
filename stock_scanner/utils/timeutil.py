"""Tiện ích thời gian theo múi giờ Việt Nam (UTC+7, không có DST)."""
from datetime import datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))
# Phiên giao dịch HOSE kết thúc lúc 15:00 (ATC 14:30–14:45, nghỉ trước 15:00).
# WHY: nến ngày chỉ "đóng" sau mốc này; trước đó nến của hôm nay là nến CHƯA HOÀN CHỈNH.
MARKET_CLOSE_HOUR = 15


def now_vn() -> datetime:
    """Giờ hiện tại theo Việt Nam (naive-aware đều được, ở đây trả về aware)."""
    return datetime.now(VN_TZ)


def session_close(day) -> datetime:
    """Thời điểm đóng cửa của một ngày giao dịch (aware, giờ VN)."""
    d = day if isinstance(day, datetime) else datetime(day.year, day.month, day.day)
    return datetime(d.year, d.month, d.day, MARKET_CLOSE_HOUR, 0, tzinfo=VN_TZ)


def is_intraday_now(last_row_date) -> bool:
    """True nếu dòng cuối cùng là hôm nay và thị trường chưa đóng cửa (nến chưa hoàn chỉnh)."""
    n = now_vn()
    return (last_row_date == n.date()) and (n < session_close(n))
