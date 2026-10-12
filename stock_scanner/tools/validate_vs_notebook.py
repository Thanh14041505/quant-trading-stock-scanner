"""
Validation (Step 7): so kết quả của APP với việc CHẠY NGUYÊN notebook gốc trên CÙNG một bộ dữ liệu.

Độc lập ở đâu: phía notebook, mã gốc được exec từ chính file .ipynb và chạy `QuantEngine.run()` (S1–S6) /
`scan_watchlist()` (S7) với DataLayer/MarketDataStore GỐC; chỉ tầng API (`vnstock.Quote.history`) được thay bằng
bản trả về đúng khung dữ liệu của store. Nhờ vậy kiểm được: (1) trích code nguyên văn, (2) lớp DataLayer thay thế
+ cắt cửa sổ, (3) đóng băng `datetime.today()`, (4) adapter/mapping. So sánh MỌI cột output gốc.

Chạy offline (dữ liệu giả lập, chỉ kiểm tra tính nhất quán code):
    python tools/validate_vs_notebook.py --notebooks /path/notebooks --provider demo
Chạy với dữ liệu thật (cần API key trong biến môi trường VNSTOCK_API_KEY):
    python tools/validate_vs_notebook.py --notebooks /path/notebooks --provider vnstock --tickers FPT VCB HPG
Lưu ý: S7 gốc cần thêm `scikit-learn`? — KHÔNG: harness bỏ cell 4 (import sklearn) vì Phase 13 không dùng.
"""
import argparse, contextlib, io, json, math, os, sys, tempfile, types, warnings
warnings.filterwarnings("ignore")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from extract_legacy import SPECS, S7_NB, cell_src
from data.store import OHLCVStore
from engine.runner import run_scan
from strategies.legacy_adapter import frozen_datetime


def norm(x):
    if isinstance(x, np.generic): x = x.item()
    if isinstance(x, (pd.Timestamp,)): return str(x)
    return x

def same(a, b, tol=1e-9):
    a, b = norm(a), norm(b)
    if isinstance(a, float) and isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= tol * max(1, abs(a))
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return list(a) == list(b)
    if a is None and isinstance(b, float) and math.isnan(b): return True
    if b is None and isinstance(a, float) and math.isnan(a): return True
    return a == b

def install_fake_quote(store):
    """Thay vnstock.Quote (tầng API) bằng bản phục vụ dữ liệu từ store; chỉ trả dữ liệu khi đúng source đã tải."""
    import vnstock
    class FakeQuote:
        def __init__(self, symbol, source="KBS", **kw):
            self.symbol, self.source = symbol, str(source).upper()
        def history(self, start=None, end=None, interval="1D", start_date=None, end_date=None, **kw):
            start, end = start or start_date, end or end_date
            raw = store._mem.get(self.symbol) if self.symbol in store._mem else store._ensure(self.symbol)
            src = str(raw["_src"].iloc[-1]).upper()
            if src != self.source: raise RuntimeError(f"fake: nguồn {self.source} không có dữ liệu")
            t = pd.to_datetime(raw["time"])
            if store._latest_session is not None:
                raw = raw[t.dt.date <= store._latest_session]; t = pd.to_datetime(raw["time"])
            out = raw[(t >= pd.Timestamp(start)) & (t <= pd.Timestamp(end))].drop(columns=["_src"]).reset_index(drop=True)
            return out
    vnstock.Quote = FakeQuote
    try:
        import vnstock.api.quote as aq; aq.Quote = FakeQuote
    except Exception: pass

def run_original_s1_s6(key, nb_dir, tickers, mode, as_of, overrides):
    spec = SPECS[key]
    nb = json.load(open(os.path.join(nb_dir, spec["nb"]), encoding="utf-8"))
    ns = {"__name__": f"orig_{key}"}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for idx in spec["cells"]:
            exec(compile(cell_src(nb["cells"][idx]), f"{spec['nb']}#cell{idx}", "exec"), ns)
    ns["datetime"] = frozen_datetime(as_of)
    ns["time"] = types.SimpleNamespace(sleep=lambda *_: None, time=__import__("time").time)
    ns["_display"] = lambda *a, **k: None
    kw = dict(overrides)
    if key in ("s03", "s04"): kw.setdefault("min_score_swing", 6.2)         # B6: hiệu lực thực của TPlusQuantEngine
    cfg = ns["QuantConfig"](**kw)
    if key == "s03" and mode == "hold":                                      # B5: cùng bản vá như app
        cfg.min_score_hold, cfg.min_rr_hold = 6.3, 3.0
    with contextlib.redirect_stdout(buf):
        eng = ns["QuantEngine"](capital=100_000_000, cfg=cfg)
        df = eng.run(symbols=tickers, mode=mode)
    return df.set_index("Mã") if df is not None and not df.empty else pd.DataFrame()

def run_original_s7(nb_dir, tickers, as_of):
    nb = json.load(open(os.path.join(nb_dir, S7_NB), encoding="utf-8"))
    tmp = tempfile.mkdtemp()
    ns = {"__name__": "orig_s07", "warnings": warnings, "os": os, "time": __import__("time"), "pd": pd, "np": np,
          "Optional": __import__("typing").Optional, "dataclass": __import__("dataclasses").dataclass}
    from datetime import datetime, timedelta
    ns.update(datetime=datetime, timedelta=timedelta)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for idx in (8, 13, 115, 116, 117, 118, 119, 120, 121, 122, 124):
            src = cell_src(nb["cells"][idx]).replace('"/content/data/raw"', repr(tmp))   # chỉ đổi thư mục cache (Colab -> tmp)
            exec(compile(src, f"S7#cell{idx}", "exec"), ns)
        ns["_time"] = types.SimpleNamespace(sleep=lambda *_: None)
        ns["SCANNER_STORE"].cfg.delay_sec = 0
        res = ns["scan_watchlist"](symbols=tickers)
    return res["all"].set_index("symbol")

def compare(name, orig_row, app_extra, skip=()):
    diffs = []
    for k, v in orig_row.items():
        if k in skip or k.startswith("Unnamed"): continue
        if k not in app_extra: diffs.append((k, v, "<thiếu>")); continue
        if not same(v, app_extra[k]): diffs.append((k, v, app_extra[k]))
    return diffs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--notebooks", required=True)
    ap.add_argument("--provider", default="demo", choices=["demo", "vnstock"])
    ap.add_argument("--tickers", nargs="+", default=["FPT", "VCB", "HPG", "SSI", "MWG", "VNM"])
    ap.add_argument("--mode", default="swing", choices=["swing", "hold"])
    ap.add_argument("--strategies", nargs="+", default=["S1", "S2", "S3", "S4", "S5", "S6", "S7"])
    a = ap.parse_args()
    if a.provider == "demo":
        from data.demo import DemoProvider
        provider, drop = DemoProvider(end="2026-09-18"), False
    else:
        from data.provider import VnstockProvider
        provider, drop = VnstockProvider(os.environ.get("VNSTOCK_API_KEY")), True
    store = OHLCVStore(provider, use_disk=False, drop_incomplete_today=drop)
    store.load_benchmark(); store.prefetch(a.tickers, workers=1, delay=0)
    as_of = store.latest_session()
    install_fake_quote(store)
    over = {"S5": {"use_fundamental": False}, "S6": {"use_fundamental": False}}
    scan = run_scan(store, a.tickers, a.strategies, mode=a.mode, overrides=over,
                    patches={"drop_incomplete_candle": drop, "s3_hold_cfg": True}, workers=1, delay=0)
    print(f"as_of={as_of}  mode={a.mode}  tickers={a.tickers}\n")
    total_bad = 0
    for sid in a.strategies:
        try:
            if sid == "S7":
                orig = run_original_s7(a.notebooks, a.tickers, as_of)
                skip = {"date", "as_of"}
            else:
                orig = run_original_s1_s6(sid.lower().replace("s", "s0"), a.notebooks, a.tickers, a.mode, as_of,
                                          {"use_fundamental": False} if sid in ("S5", "S6") else {})
                skip = set()
        except Exception as e:
            print(f"{sid}: KHÔNG chạy được notebook gốc -> {type(e).__name__}: {str(e)[:200]}"); total_bad += 1; continue
        n_cmp, n_bad = 0, 0
        for t in a.tickers:
            r = scan.results[t][sid]
            if t not in orig.index:
                # Notebook gốc bỏ qua mã (thiếu dữ liệu) -> app phải báo NO_DATA
                ok = r.status in ("NO_DATA",)
                print(f"  {sid} {t}: notebook bỏ qua mã; app status={r.status}", "OK" if ok else "SAI"); n_bad += (not ok); continue
            diffs = compare(f"{sid}/{t}", orig.loc[t].to_dict(), r.extra, skip)
            n_cmp += 1
            if diffs:
                n_bad += 1
                print(f"  {sid} {t}: {len(diffs)} khác biệt, ví dụ: {diffs[:3]}")
        print(f"{sid}: so sánh {n_cmp} mã — {'KHỚP HOÀN TOÀN' if n_bad == 0 else str(n_bad) + ' mã lệch'}")
        total_bad += n_bad
    print("\nKẾT QUẢ:", "TẤT CẢ KHỚP" if total_bad == 0 else f"{total_bad} vấn đề — cần truy nguyên nhân (KHÔNG sửa để ép giống)")
    return 1 if total_bad else 0

if __name__ == "__main__":
    sys.exit(main())
