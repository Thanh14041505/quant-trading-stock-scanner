"""
Runner: điều phối cả lượt quét.

Thứ tự (theo yêu cầu số 7): API -> Cache -> Market Data -> 7 Strategy -> Consensus.
Cách ly lỗi: lỗi ở một mã HOẶC một strategy chỉ tạo ra kết quả ERROR/NO_DATA cho đúng ô đó — không làm sập scan.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from data.store import OHLCVStore, BENCHMARK
from strategies.base import ScanContext, StrategyResult, ERROR, NO_DATA
from strategies.registry import REGISTRY
from engine.consensus import Consensus, compute_consensus


@dataclass
class ScanResult:
    as_of: Optional[Any] = None
    mode: str = "swing"
    symbols: List[str] = field(default_factory=list)
    sids: List[str] = field(default_factory=list)
    results: Dict[str, Dict[str, StrategyResult]] = field(default_factory=dict)     # symbol -> sid -> result
    consensus: Dict[str, Consensus] = field(default_factory=dict)
    prep: Dict[str, Dict[str, Any]] = field(default_factory=dict)                   # sid -> summary hoặc {"error": ...}
    timings: Dict[str, float] = field(default_factory=dict)
    data_stats: Dict[str, int] = field(default_factory=dict)
    fetch_errors: Dict[str, str] = field(default_factory=dict)
    patches: Dict[str, bool] = field(default_factory=dict)
    n_symbols_ok_data: int = 0


def run_scan(store: OHLCVStore, symbols: List[str], sids: List[str], mode: str = "swing",
             capital: float = 100_000_000, overrides: Optional[dict] = None, patches: Optional[dict] = None,
             avg_cost: Optional[float] = None, workers: int = 2, delay: float = 0.3,
             progress: Optional[Callable[[str, int, int, str], None]] = None) -> ScanResult:
    P = lambda stage, i, n, msg="": progress(stage, i, n, msg) if progress else None   # noqa: E731
    t0 = time.time()
    symbols = [s.strip().upper() for s in dict.fromkeys(symbols) if s.strip()]
    out = ScanResult(mode=mode, symbols=symbols, sids=list(sids), patches=dict(patches or {}))

    store.drop_incomplete_today = bool((patches or {}).get("drop_incomplete_candle", True))
    P("benchmark", 0, 1, BENCHMARK)
    store.load_benchmark()
    out.as_of = store.latest_session()
    store.prefetch(symbols, workers=workers, delay=delay,
                   progress=lambda i, n, s: P("fetch", i, n, s))
    out.timings["fetch"] = time.time() - t0
    out.data_stats, out.fetch_errors = dict(store.stats), dict(store.errors)
    out.n_symbols_ok_data = sum(1 for s in symbols if s not in store.errors)

    ctx = ScanContext(store=store, mode=mode, capital=capital, overrides=overrides or {},
                      patches=patches or {}, avg_cost=avg_cost)
    for s in symbols:
        out.results[s] = {}
    for k, sid in enumerate(sids):
        strat = REGISTRY[sid]
        t1 = time.time()
        P("strategy", k, len(sids), sid)
        try:
            prep = strat.prepare(ctx)
            out.prep[sid] = strat.prep_summary(prep)
        except Exception as e:  # noqa: BLE001 — strategy không khởi tạo được -> ERROR cho mọi mã, các strategy khác vẫn chạy
            out.prep[sid] = {"error": f"{type(e).__name__}: {str(e)[:250]}"}
            for s in symbols:
                out.results[s][sid] = StrategyResult(sid, s, "ERROR", mode, "—", ERROR,
                                                     warnings=[f"Strategy không khởi tạo được: {out.prep[sid]['error']}"])
            out.timings[sid] = time.time() - t1
            continue
        for i, s in enumerate(symbols):
            if s in store.errors:
                out.results[s][sid] = StrategyResult(sid, s, "NO_DATA", mode, "—", NO_DATA,
                                                     warnings=[f"API: {store.errors[s][:160]}"])
            else:
                out.results[s][sid] = strat.run_symbol(s, prep, ctx)
            if i % 10 == 0:
                P("symbols", i, len(symbols), f"{sid}:{s}")
        out.timings[sid] = time.time() - t1

    fam = {sid: REGISTRY[sid].info.family for sid in sids}
    for s in symbols:
        out.consensus[s] = compute_consensus(s, out.results[s], fam)
    out.timings["total"] = time.time() - t0
    P("done", 1, 1, "")
    return out
