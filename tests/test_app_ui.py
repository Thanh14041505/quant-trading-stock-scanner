"""Chạy app headless bằng streamlit.testing (AppTest): chế độ demo, có bật Dark mode + S8/P3, ở cả 2 mode."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from streamlit.testing.v1 import AppTest


def run_once(mode_label: str, dark: bool, include_ai: bool):
    at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "..", "app.py"), default_timeout=180)
    at.run(); assert not at.exception, at.exception
    [c for c in at.sidebar.checkbox if "GIẢ LẬP" in c.label][0].check(); at.run()
    if dark:
        [t for t in at.sidebar.toggle if "Dark mode" in t.label][0].set_value(True); at.run()
    [r for r in at.sidebar.radio if "Mode giao dịch" in r.label][0].set_value(mode_label); at.run()
    n = [w for w in at.sidebar.number_input if "N mã đầu" in w.label][0]; n.set_value(8); at.run()
    for cb in at.sidebar.checkbox:
        if cb.key in ("p_S5_use_fundamental", "p_S6_use_fundamental"):
            cb.uncheck()
    if include_ai:
        [c for c in at.sidebar.checkbox if "P3" in c.label][0].check()
    at.run()
    [b for b in at.sidebar.button if "QUÉT" in b.label][0].click()
    at.run()
    assert not at.exception, at.exception
    print(f"[{mode_label} dark={dark} ai={include_ai}] tabs:{len(at.tabs)} df:{len(at.dataframe)} "
         f"err:{len(at.error)} warn:{len(at.warning)}")
    for e in at.error:
        print("  ERR:", e.value[:200])


for dark in (False, True):
    for ai in (False, True):
        run_once("Swing T+", dark, ai)
run_once("Hold", False, False)
print("ALL OK")
