"""
Provider dữ liệu: lấy OHLCV thô từ vnstock (Quote API), thử lần lượt KBS -> VCI.

WHY giữ dữ liệu "thô" (đúng như API trả về):
    Các notebook gốc KHÔNG đồng nhất về đơn vị giá (xem audit B9): S1–S6 dùng số liệu như API trả về,
    S7 quy đổi KBS (nghìn đồng) sang VND. Vì vậy lớp data chỉ lưu bản thô + tên nguồn; việc quy đổi
    thuộc về adapter của từng strategy.
"""
from __future__ import annotations
import time
from typing import Optional, Sequence
import pandas as pd


class ProviderError(RuntimeError):
    """Lỗi khi không lấy được dữ liệu từ bất kỳ nguồn nào."""


class VnstockProvider:
    def __init__(self, api_key: Optional[str] = None, sources: Sequence[str] = ("KBS", "VCI"),
                 retries: int = 3, backoff: float = 1.0):
        self.sources, self.retries, self.backoff = tuple(sources), retries, backoff
        if api_key:
            # API key chỉ nằm trong bộ nhớ tiến trình; app KHÔNG ghi key ra đĩa/log.
            # (Lưu ý: chính thư viện vnstock/vnai có thể tự lưu key vào thư mục home của máy chạy.)
            ok = False
            try:
                from vnstock import register_user
                ok = bool(register_user(api_key))
            except Exception:
                ok = False
            if not ok:                      # vnstock 4.x cũng có đường đăng ký qua vnai
                try:
                    import vnai
                    vnai.setup_api_key(api_key)
                except Exception:
                    pass                    # lỗi xác thực (nếu có) sẽ hiện ở lần gọi Quote

    def fetch(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        last_err = None
        for attempt in range(self.retries):
            for src in self.sources:
                try:
                    from vnstock import Quote
                    q = Quote(symbol=symbol, source=src)
                    try:
                        df = q.history(start=start, end=end, interval="1D")
                    except TypeError:            # một số phiên bản đặt tên tham số khác
                        df = q.history(start_date=start, end_date=end, interval="1D")
                    if df is not None and not df.empty:
                        df = df.copy()
                        df["_src"] = src
                        return df
                    last_err = RuntimeError(f"{src}: dữ liệu rỗng")
                except Exception as e:  # noqa: BLE001 — cố ý bắt rộng: 1 nguồn lỗi -> thử nguồn khác
                    last_err = e
            if attempt < self.retries - 1:
                time.sleep(self.backoff * (2 ** attempt))
        raise ProviderError(f"{symbol}: không lấy được dữ liệu ({last_err!r})")
