"""Smoke test offline: chạy cả 7 strategy trên dữ liệu GIẢ LẬP để bắt lỗi import/adapter (không xác nhận đúng sai trading)."""
import sys, os, warnings
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
warnings.filterwarnings("ignore")
from data.demo import DemoProvider
from data.store import OHLCVStore
from engine.runner import run_scan
from engine.tables import scanner_df, matrix_df

mode = sys.argv[1] if len(sys.argv) > 1 else "swing"
store = OHLCVStore(DemoProvider(end="2026-09-18"), use_disk=False, drop_incomplete_today=False)
syms = ["FPT", "VCB", "HPG", "SSI", "MWG", "VNM"]
scan = run_scan(store, syms, ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"], mode=mode,
                overrides={"S5": {"use_fundamental": False}, "S6": {"use_fundamental": False}},
                patches={"drop_incomplete_candle": False}, workers=1, delay=0)
print("as_of:", scan.as_of, "| timings:", {k: round(v, 1) for k, v in scan.timings.items()})
for sid, p in scan.prep.items():
    print(sid, p)
print(matrix_df(scan).to_string())
bad = [(s, sid, r.status, r.warnings[:1]) for s, d in scan.results.items() for sid, r in d.items() if r.status in ("ERROR",)]
print("ERRORS:", bad[:12], len(bad))
