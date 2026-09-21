"""Chạy app headless bằng streamlit.testing (AppTest) ở chế độ demo để bắt lỗi UI."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from streamlit.testing.v1 import AppTest

at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "..", "app.py"), default_timeout=180)
at.run()
assert not at.exception, at.exception
# bật demo, giới hạn 8 mã, tắt fundamental S5/S6 để không gọi mạng
[c for c in at.sidebar.checkbox if "GIẢ LẬP" in c.label][0].check()
at.run()
n = [w for w in at.sidebar.number_input if "N mã đầu" in w.label][0]
n.set_value(8)
at.run()
for cb in at.sidebar.checkbox:
    if cb.key in ("p_S5_use_fundamental", "p_S6_use_fundamental"):
        cb.uncheck()
at.run()
[b for b in at.sidebar.button if "QUÉT" in b.label][0].click()
at.run()
assert not at.exception, at.exception
print("tabs:", len(at.tabs), "| dataframes:", len(at.dataframe), "| errors:", len(at.error), "| warnings:", len(at.warning))
for e in at.error: print("ERR:", e.value[:200])
