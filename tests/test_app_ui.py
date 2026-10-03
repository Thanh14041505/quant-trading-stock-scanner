"""Chạy app headless bằng streamlit.testing (AppTest): chế độ demo, có bật Dark mode + S8/P3 + tham số
dùng chung + nút Xuất Excel, ở cả 2 mode."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")


def run_once(mode_label: str, dark: bool, include_ai: bool):
    at = AppTest.from_file(APP, default_timeout=240)
    at.run(); assert not at.exception, at.exception
    [c for c in at.sidebar.checkbox if "GIẢ LẬP" in c.label][0].check(); at.run()
    if dark:
        [t for t in at.sidebar.toggle if "Dark mode" in t.label][0].set_value(True); at.run()
    [r for r in at.sidebar.radio if "Mode giao dịch" in r.label][0].set_value(mode_label); at.run()
    n = [w for w in at.sidebar.number_input if "N mã đầu" in w.label][0]; n.set_value(8); at.run()
    for cb in at.sidebar.checkbox:
        if cb.key in ("p_S5_use_fundamental", "p_S6_use_fundamental"):
            cb.uncheck()
    vp = [w for w in at.sidebar.number_input if w.label == "vp_bins"]   # tham số dùng chung
    if vp:
        vp[0].set_value(40)
    if include_ai:
        [c for c in at.sidebar.checkbox if "P3" in c.label][0].check()
    at.run()
    [b for b in at.sidebar.button if "QUÉT" in b.label][0].click()
    at.run()
    assert not at.exception, at.exception
    dl = [b for b in at.sidebar.download_button if "Xuất Excel" in b.label]
    assert len(dl) == 1, "Nút Xuất Excel không xuất hiện sau khi quét xong"
    print(f"[{mode_label} dark={dark} ai={include_ai}] tabs:{len(at.tabs)} df:{len(at.dataframe)} "
         f"err:{len(at.error)} warn:{len(at.warning)} download_btn:{len(dl)}")
    for e in at.error:
        print("  ERR:", e.value[:200])


for dark in (False, True):
    for ai in (False, True):
        run_once("Swing T+", dark, ai)
run_once("Hold", False, False)
print("ALL OK")
