"""
Giới hạn tốc độ gọi API vnstock (dùng chung cho tải giá và tải Fundamental).

VÌ SAO CẦN:
    vnstock giới hạn số request/phút theo gói (Khách ≈ 20, Community có API key ≈ 60, Sponsor 180–600).
    Khi chạm trần, thư viện KHÔNG ném Exception mà ném `SystemExit("Rate limit exceeded.")` — loại BaseException,
    các `except Exception` không bắt được, và nó có thể dừng cả lượt quét/ứng dụng.
    Cách xử lý: (1) chủ động không vượt trần bằng cửa sổ trượt 60 giây; (2) nếu vẫn dính SystemExit thì bắt, chờ, thử lại.
"""
from __future__ import annotations
import collections, threading, time

RATE_WAIT = 26.0          # vnstock báo "chờ ~24 giây" khi chạm trần
_lock = threading.Lock()
_calls: "collections.deque[float]" = collections.deque()
_rpm = 18                 # mặc định an toàn cho gói Khách; sidebar sẽ đặt lại theo gói của bạn


def configure(rpm: int) -> None:
    global _rpm
    _rpm = max(1, int(rpm))


def acquire() -> None:
    """Chặn cho tới khi được phép gọi thêm 1 request (cửa sổ trượt 60 giây, an toàn khi nhiều luồng)."""
    while True:
        with _lock:
            now = time.time()
            while _calls and now - _calls[0] >= 60:
                _calls.popleft()
            if len(_calls) < _rpm:
                _calls.append(now)
                return
            wait = 60 - (now - _calls[0])
        time.sleep(max(0.05, wait))
