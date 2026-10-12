"""
OHLCVStore — cache 2 tầng (RAM + parquet trên đĩa) cho dữ liệu OHLCV thô.

Luồng dữ liệu (theo yêu cầu số 7 của dự án):
    API -> Cache -> Market Data -> (adapter từng strategy) -> Strategy

Nguyên tắc:
  * MỖI mã chỉ gọi API MỘT lần với lookback tối đa (đủ cho mọi strategy), sau đó mỗi strategy
    tự cắt lát theo cửa sổ hiệu dụng của notebook gốc (xem strategies/legacy_adapter.py).
  * Cache hợp lệ khi được tải SAU thời điểm đóng cửa của phiên giao dịch hoàn chỉnh gần nhất
    (không dùng TTL cứng) -> chạy lại nhiều lần trong ngày không gọi API lại.
  * `as_of`: bỏ mọi dòng SAU phiên hoàn chỉnh gần nhất => loại nến chưa đóng của hôm nay (L4).
"""
from __future__ import annotations
import json, os, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Callable, Dict, Iterable, Optional
import pandas as pd

from utils.timeutil import now_vn, session_close, VN_TZ

# Lookback tối đa cần cho mọi strategy: S5/S6 lookback_weekly=800, S3/S4 lookback_long=750 (ngày lịch).
MAX_LOOKBACK_DAYS = 820
BENCHMARK = "VNINDEX"


class DataError(RuntimeError):
    pass


class OHLCVStore:
    def __init__(self, provider, cache_dir: str = ".cache/ohlcv", use_disk: bool = True,
                 drop_incomplete_today: bool = True):
        self.provider = provider
        self.cache_dir = cache_dir
        self.use_disk = use_disk
        self.drop_incomplete_today = drop_incomplete_today
        self._mem: Dict[str, pd.DataFrame] = {}
        self._meta: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self.stats = dict(mem_hit=0, disk_hit=0, api=0, fail=0)
        self.errors: Dict[str, str] = {}
        self._latest_session: Optional[datetime.date] = None
        if use_disk:
            os.makedirs(cache_dir, exist_ok=True)
            self._load_meta()

    # ───────────────────────── meta / đường dẫn ─────────────────────────
    def _p(self, sym): return os.path.join(self.cache_dir, f"{sym}.parquet")
    def _meta_path(self): return os.path.join(self.cache_dir, "_meta.json")

    def _load_meta(self):
        try:
            self._meta = json.load(open(self._meta_path()))
        except Exception:
            self._meta = {}

    def _save_meta(self):
        if not self.use_disk:
            return
        try:
            json.dump(self._meta, open(self._meta_path(), "w"))
        except Exception:
            pass

    # ───────────────────────── phiên giao dịch hoàn chỉnh ─────────────────────────
    @staticmethod
    def _latest_completed(df: pd.DataFrame, drop_incomplete: bool) -> Optional[datetime.date]:
        """Ngày phiên hoàn chỉnh gần nhất trong df (bỏ hôm nay nếu thị trường chưa đóng cửa)."""
        days = sorted(pd.to_datetime(df["time"]).dt.normalize().dt.date.unique())
        if not days:
            return None
        n = now_vn()
        if drop_incomplete and days[-1] == n.date() and n < session_close(n):
            days = days[:-1]
        return days[-1] if days else None

    def latest_session(self) -> Optional[datetime.date]:
        """Phiên giao dịch hoàn chỉnh gần nhất theo VNINDEX (gọi sau khi đã nạp benchmark)."""
        return self._latest_session

    def set_as_of(self, d) -> None:
        self._latest_session = d

    def _fresh(self, sym: str) -> bool:
        m = self._meta.get(sym)
        if not m or self._latest_session is None:
            return False
        fetched = datetime.fromisoformat(m["fetched_at"])
        return fetched >= session_close(self._latest_session)

    # ───────────────────────── truy cập ─────────────────────────
    def _download(self, sym: str) -> pd.DataFrame:
        end = (now_vn().date() + timedelta(days=1)).strftime("%Y-%m-%d")
        start = (now_vn().date() - timedelta(days=MAX_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        df = self.provider.fetch(sym, start, end)
        self.stats["api"] += 1
        return df

    def _ensure(self, sym: str, force: bool = False) -> pd.DataFrame:
        with self._lock:
            if not force and sym in self._mem and (self._latest_session is None or self._fresh(sym)):
                self.stats["mem_hit"] += 1
                return self._mem[sym]
            if not force and self.use_disk and os.path.exists(self._p(sym)) and self._fresh(sym):
                try:
                    df = pd.read_parquet(self._p(sym))
                    self._mem[sym] = df
                    self.stats["disk_hit"] += 1
                    return df
                except Exception:
                    pass
        try:
            df = self._download(sym)
        except Exception as e:  # noqa: BLE001
            self.stats["fail"] += 1
            self.errors[sym] = str(e)
            raise DataError(str(e)) from e
        with self._lock:
            self._mem[sym] = df
            self._meta[sym] = {"fetched_at": now_vn().isoformat()}
            if self.use_disk:
                try:
                    df.to_parquet(self._p(sym))
                except Exception:
                    pass
        return df

    def load_benchmark(self) -> None:
        """Nạp VNINDEX trước và xác định phiên hoàn chỉnh gần nhất (as_of chung cho cả scan).

        Benchmark được làm mới nếu cache cũ hơn 10 phút, vì nó quyết định as_of của mọi mã khác.
        """
        m = self._meta.get(BENCHMARK)
        recent = bool(m) and (now_vn() - datetime.fromisoformat(m["fetched_at"])).total_seconds() < 600
        if recent and BENCHMARK in self._mem:
            bench = self._mem[BENCHMARK]
        elif recent and self.use_disk and os.path.exists(self._p(BENCHMARK)):
            bench = pd.read_parquet(self._p(BENCHMARK)); self._mem[BENCHMARK] = bench
        else:
            bench = self._ensure(BENCHMARK, force=True)
        self._latest_session = self._latest_completed(bench, self.drop_incomplete_today)
        self._save_meta()

    def get_raw(self, sym: str) -> pd.DataFrame:
        """Bản thô đã cắt tới as_of (không có nến chưa đóng), bản sao — an toàn để chỉnh sửa."""
        df = self._ensure(sym)
        if self._latest_session is not None:
            t = pd.to_datetime(df["time"]).dt.normalize().dt.date
            df = df[t <= self._latest_session]
        return df.copy()

    def prefetch(self, symbols: Iterable[str], workers: int = 2, delay: float = 0.3,
                 progress: Optional[Callable[[int, int, str], None]] = None) -> None:
        """Tải song song (ít luồng để tôn trọng rate-limit). Lỗi từng mã không làm dừng scan."""
        syms = [s for s in dict.fromkeys(symbols) if s != BENCHMARK]
        done = 0

        def work(s):
            try:
                self._ensure(s)
            except DataError:
                pass
            if delay:
                time.sleep(delay)
            return s

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = [ex.submit(work, s) for s in syms]
            for f in as_completed(futs):
                done += 1
                if progress:
                    progress(done, len(syms), f.result())
        self._save_meta()
