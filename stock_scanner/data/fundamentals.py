"""
Cache + prefetch điểm Fundamental (P/E, ROE…) cho S5/S6.

VÌ SAO CẦN (nguyên nhân app chạy rất lâu ở S5):
    FundamentalEngine của notebook gọi API báo cáo tài chính (Fundamental().equity(mã).ratio()) cho TỪNG mã,
    tuần tự, và mỗi engine có cache riêng -> ~240 request cho S5, rồi lặp lại ~240 request cho S6, mỗi lần quét.
    Trong khi đó ở mode Swing điểm này KHÔNG ảnh hưởng score/tín hiệu (chỉ hiện ở cột "FA Score").

Cách xử lý:
    1. Cache dùng chung toàn app (S5 và S6 dùng chung, sống qua các lần quét, TTL 24h; lỗi chỉ nhớ 10 phút).
    2. Mode Swing: không gọi API (dùng điểm trung tính 5.0 như notebook khi lỗi) — trừ khi bật patch `fundamental_in_swing`.
    3. Mode Hold: tải TRƯỚC, song song (ít luồng) và có giới hạn thời gian; vòng lặp chấm điểm KHÔNG bao giờ gọi mạng.
"""
from __future__ import annotations
import importlib, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FTimeout
from data import ratelimit
from typing import Callable, Dict, Iterable, Optional

NEUTRAL = (5.0, "—")          # đúng giá trị notebook trả về khi không lấy được dữ liệu
TTL_OK, TTL_FAIL = 24 * 3600, 10 * 60
_CACHE: Dict[str, tuple] = {}
_LOCK = threading.Lock()
_TLS = threading.local()


def get(symbol: str):
    """Trả về (score, note) còn hạn trong cache, hoặc None."""
    with _LOCK:
        item = _CACHE.get(symbol)
    if not item:
        return None
    ts, res, ttl = item
    return res if (time.time() - ts) <= ttl else None


def _put(symbol: str, res) -> None:
    res = tuple(res)
    ttl = TTL_FAIL if res == NEUTRAL else TTL_OK      # NEUTRAL thường là lỗi/rate-limit -> thử lại sớm hơn
    with _LOCK:
        _CACHE[symbol] = (time.time(), res, ttl)


def _engine():
    """Mỗi luồng một FundamentalEngine gốc (không chia sẻ đối tượng Fundamental() giữa các luồng)."""
    eng = getattr(_TLS, "eng", None)
    if eng is None:
        mod = importlib.import_module("strategies._legacy.s05_legacy")
        eng = _TLS.eng = mod.FundamentalEngine()
    return eng


def _fetch(symbol: str, delay: float) -> str:
    ratelimit.acquire()                       # dùng chung hạn mức request/phút với tải giá
    try:
        res = _engine().score(symbol)
    except SystemExit:                        # vnstock ném SystemExit khi chạm rate limit -> coi như chưa có, chờ rồi đi tiếp
        res = NEUTRAL
        time.sleep(ratelimit.RATE_WAIT)
    _put(symbol, res)
    if delay:
        time.sleep(delay)
    return symbol


def prefetch_fundamentals(symbols: Iterable[str], workers: int = 2, delay: float = 0.3, max_seconds: float = 240,
                          progress: Optional[Callable[[int, int, str], None]] = None) -> dict:
    """Tải Fundamental cho các mã chưa có trong cache. Quá `max_seconds` thì bỏ phần còn lại (không treo app)."""
    syms = list(dict.fromkeys(symbols))
    todo = [s for s in syms if get(s) is None]
    done = 0
    if todo:
        ex = ThreadPoolExecutor(max_workers=max(1, workers))
        futs = [ex.submit(_fetch, s, delay) for s in todo]
        try:
            for f in as_completed(futs, timeout=max_seconds):
                done += 1
                if progress:
                    progress(done, len(todo), f.result())
        except (FTimeout, TimeoutError):
            pass
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
    missing = sum(1 for s in syms if get(s) in (None, NEUTRAL))
    return {"total": len(syms), "fetched_now": done, "missing": missing, "timed_out": done < len(todo)}


def install_cache(engine, mode: str, fundamental_in_swing: bool = False) -> None:
    """Thay `engine.fa.score` bằng bản chỉ đọc cache (không bao giờ gọi mạng trong vòng lặp scan)."""
    def score(symbol: str):
        if mode == "swing" and not fundamental_in_swing:
            return NEUTRAL
        return get(symbol) or NEUTRAL
    engine.fa.score = score
