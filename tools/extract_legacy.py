"""
Công cụ DEV: trích code production từ các notebook gốc sang strategies/_legacy/*.py

WHY (vì sao không viết lại tay):
    Yêu cầu số 1 của dự án là giữ NGUYÊN logic notebook. Cách an toàn nhất là
    KHÔNG gõ lại mà sao chép nguyên văn từng cell production (byte-for-byte),
    rồi chỉ bọc bằng adapter mỏng. Mọi khác biệt (bug, threshold...) nhờ đó được
    giữ đúng như notebook và có thể kiểm chứng bằng hash (tools/verify_extraction.py).

Cách dùng:
    python tools/extract_legacy.py --notebooks /đường/dẫn/thư_mục_chứa_notebook
"""
import argparse, hashlib, json, os

# Chọn cell theo index (code cell). Cell bị loại: cài đặt/register_user (chứa API key),
# `__main__`, backtest/research không thuộc production, và cell `len(VN100)` (NameError ở S3).
SPECS = {
    "s01": dict(nb="Tool_CK_Claude_v1.ipynb", cells=list(range(2, 20)),
                note="S1 — VN Quant Engine v5.5 (Ichimoku đa khung + T+ >= 9%). Loại: cell 0,1 (pip/register_user), 20 (__main__)."),
    "s02": dict(nb="Tool_CK_Claude_v1_1.ipynb", cells=list(range(2, 22)),
                note="S2 — v5.7 (S1 + Composite RSI Divergence + DivergenceAdvisor). Loại: 0,1, 22 (__main__), 23 (Backtester), 24 (divergence_study)."),
    "s03": dict(nb="Tool_CK_Grok_v2.ipynb", cells=[2, 3] + list(range(5, 19)),
                note="S3 — T+2.5 Swing v5.3. Loại: 0,1, 4 (len(VN100) -> NameError), 19 (TPlusQuantEngine, xem B6), 20 (__main__)."),
    "s04": dict(nb="Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb", cells=[2, 3, 4] + list(range(6, 21)),
                note="S4 — v5.6 (S3 + RSI/Composite Divergence). Loại: 0,1, 5 (len(VN100)), 21 (TPlusQuantEngine, xem B6), 22 (__main__), 23 (markdown)."),
    "s05": dict(nb="Tool_CK_Grok_v2_PR016.ipynb", cells=list(range(2, 22)),
                note="S5 — v8 (PR016). Loại: 0,1, 22 (__main__). Giữ cell 20 (BacktestEngine) vì QuantEngine.__init__ khởi tạo nó; KHÔNG dùng trong scan."),
    "s06": dict(nb="Tool_CK_Grok_v2_PR016_enhanced_v2.ipynb", cells=list(range(2, 22)),
                note="S6 — v8+ (PR016 enhanced, hidden divergence). Loại: 0,1, 22 (__main__)."),
}

HEADER = '''# -*- coding: utf-8 -*-
# ╔════════════════════════════════════════════════════════════════════════╗
# ║  FILE SINH TỰ ĐỘNG — KHÔNG SỬA TAY                                      ║
# ║  Sinh bởi tools/extract_legacy.py; nội dung các cell là NGUYÊN VĂN.     ║
# ╚════════════════════════════════════════════════════════════════════════╝
# Source Notebook : {nb}
# Section         : Production scanner (QuantEngine.run_pipeline và các engine phụ thuộc)
# Cells được giữ  : {cells}
# Ghi chú         : {note}
# Lý do giữ nguyên: dự án ưu tiên "bảo toàn logic notebook" (bug, ngưỡng, thứ tự tính toán).
#                   Mọi vá lỗi nằm ở lớp adapter (strategies/strategy_XX.py), KHÔNG ở file này.
'''

def cell_src(cell):
    s = cell["source"]
    return "".join(s) if isinstance(s, list) else s

def build(nb_dir, out_dir):
    manifest = {}
    for key, spec in SPECS.items():
        nb = json.load(open(os.path.join(nb_dir, spec["nb"]), encoding="utf-8"))
        parts = [HEADER.format(nb=spec["nb"], cells=spec["cells"], note=spec["note"])]
        hashes = {}
        for idx in spec["cells"]:
            c = nb["cells"][idx]
            assert c["cell_type"] == "code", (key, idx)
            src = cell_src(c)
            hashes[idx] = hashlib.sha256(src.encode("utf-8")).hexdigest()
            parts.append(f"\n\n# ═════ [source cell {idx}] {spec['nb']} ═════\n{src}\n")
        out = os.path.join(out_dir, f"{key}_legacy.py")
        open(out, "w", encoding="utf-8").write("".join(parts))
        manifest[key] = dict(notebook=spec["nb"], cells=hashes)
        print(f"{key}: {len(spec['cells'])} cells -> {out}")
    manifest["s07"] = build_s07(nb_dir, out_dir)
    json.dump(manifest, open(os.path.join(out_dir, "MANIFEST.json"), "w"), indent=1)

# ─────────────────────────────────────────────────────────────────────────────
# S7: Phase 13 là các hàm module-level trộn với code Colab (Google Drive, MarketDataStore,
# print, monkey-patch...). Vì vậy trích THEO TÊN bằng AST: chỉ lấy đúng các hàm/hằng số
# production; mỗi đoạn vẫn là source nguyên văn (ast.get_source_segment).
S7_NB = "Tool_CK_Claude_ChatGPT_v3_ProductionDailyScanner.ipynb"
S7_PICK = {
    115: dict(assign=["MY_STOCKS", "BENCHMARK_SYMBOL", "LOOKBACK_DAYS", "SCAN_CFG", "VERBOSE_SCAN"]),
    116: dict(funcs=["_production_clean"]),
    117: dict(funcs=["_safe_num", "build_scanner_features"]),
    118: dict(funcs=["detect_market_regime"]),
    119: dict(funcs=["_clip_score", "score_stock_snapshot", "classify_signal"]),
    120: dict(funcs=["_get_live_probability", "combine_probability_and_score"]),
    121: dict(funcs=["scan_one_symbol"]),
    124: dict(funcs=["normalize_ohlcv"]),
}
S7_HEADER = '''# -*- coding: utf-8 -*-
# ╔════════════════════════════════════════════════════════════════════════╗
# ║  FILE SINH TỰ ĐỘNG — KHÔNG SỬA TAY (tools/extract_legacy.py)            ║
# ╚════════════════════════════════════════════════════════════════════════╝
# Source Notebook : {nb}
# Section         : PHASE 13 — DAILY LIVE / EOD STOCK SCANNER (Production)
# Trích theo tên  : hàm/hằng số production của Phase 13.0–13.6 + hotfix normalize_ohlcv.
# Không trích     : MarketDataStore/Drive cache (thay bằng data/store.py), Phase 2–12 (Research),
#                   print_daily_report/save_daily_report, scan_watchlist (runner của app thay thế).
# Điểm cần biết   : `_call_data_layer` KHÔNG có ở đây — adapter strategy_07.py gắn vào lúc chạy
#                   (scan_one_symbol tra cứu tên này trong global của module).
import ast  # noqa: F401
import numpy as np
import pandas as pd
'''

def build_s07(nb_dir, out_dir):
    import ast
    nb = json.load(open(os.path.join(nb_dir, S7_NB), encoding="utf-8"))
    parts, hashes = [S7_HEADER.format(nb=S7_NB)], {}
    for idx, pick in S7_PICK.items():
        src = cell_src(nb["cells"][idx])
        tree = ast.parse(src)
        want_f, want_a = set(pick.get("funcs", [])), set(pick.get("assign", []))
        for node in tree.body:
            name = None
            if isinstance(node, ast.FunctionDef) and node.name in want_f:
                name = node.name
            elif isinstance(node, ast.Assign) and any(getattr(t, "id", None) in want_a for t in node.targets):
                name = node.targets[0].id
            if name:
                seg = ast.get_source_segment(src, node)
                hashes[f"{idx}:{name}"] = hashlib.sha256(seg.encode("utf-8")).hexdigest()
                parts.append(f"\n\n# ═════ [cell {idx}] {name} ═════\n{seg}\n")
    out = os.path.join(out_dir, "s07_legacy.py")
    open(out, "w", encoding="utf-8").write("".join(parts))
    print(f"s07: {len(hashes)} objects -> {out}")
    return dict(notebook=S7_NB, objects=hashes)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--notebooks", required=True)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "strategies", "_legacy"))
    a = ap.parse_args()
    build(a.notebooks, a.out)
