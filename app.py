"""
Unified 7-Strategy Stock Scanner — Streamlit entry point.

Chạy local:  streamlit run app.py
Kiến trúc :  Vnstock -> Cache (RAM + parquet) -> 7 strategy độc lập -> Meta/Consensus -> UI
(Xem README.md và docs/audit_7_notebooks.md.)
"""
import warnings
import streamlit as st

warnings.filterwarnings("ignore")
st.set_page_config(page_title="7-Strategy Stock Scanner", page_icon="📈", layout="wide")

from ui.sidebar import render_sidebar, get_store           # noqa: E402
from ui import pages                                       # noqa: E402
from engine.runner import run_scan                         # noqa: E402

st.title("📈 7-Strategy Stock Scanner — thị trường Việt Nam")
cfg = render_sidebar()
store = get_store("demo" if cfg["demo"] else "vnstock", cfg["key_hash"], cfg["key"])

if cfg["demo"]:
    st.warning("🧪 ĐANG DÙNG DỮ LIỆU GIẢ LẬP — kết quả KHÔNG phản ánh thị trường thật.")

run = st.sidebar.button("▶️ QUÉT", type="primary", width="stretch")
if st.sidebar.button("🗑️ Xoá cache dữ liệu", width="stretch"):
    store._mem.clear(); store._meta.clear()
    import shutil, os
    if store.use_disk and os.path.isdir(store.cache_dir):
        shutil.rmtree(store.cache_dir, ignore_errors=True); os.makedirs(store.cache_dir, exist_ok=True)
    st.session_state.pop("scan", None)
    st.sidebar.success("Đã xoá cache.")

if run:
    if not cfg["sids"] or not cfg["symbols"]:
        st.error("Cần chọn ít nhất 1 strategy và 1 mã.")
    else:
        bar = st.progress(0.0, text="Đang bắt đầu…")
        def on_progress(stage, i, n, msg):
            frac = {"benchmark": 0.02, "fetch": 0.05 + 0.45 * (i / max(n, 1)),
                    "strategy": 0.5 + 0.45 * (i / max(n, 1)), "symbols": None, "done": 1.0}.get(stage)
            text = {"benchmark": "Nạp VNINDEX…", "fetch": f"Tải dữ liệu {i}/{n} ({msg})",
                    "strategy": f"Chạy {msg}…", "symbols": f"{msg} ({i}/{n})", "done": "Hoàn tất"}.get(stage, stage)
            if frac is not None:
                bar.progress(min(frac, 1.0), text=text)
        try:
            st.session_state["scan"] = run_scan(
                store, cfg["symbols"], cfg["sids"], mode=cfg["mode"], capital=cfg["capital"],
                overrides=cfg["overrides"], patches=cfg["patches"], workers=cfg["workers"],
                delay=cfg["delay"], progress=on_progress)
            st.session_state["scan_demo"] = cfg["demo"]
        except Exception as e:  # noqa: BLE001 — lỗi nặng (vd. không tải được VNINDEX) hiển thị rõ, không crash app
            st.error(f"Không thể hoàn tất lượt quét: {type(e).__name__}: {e}")
        bar.empty()

scan = st.session_state.get("scan")
tabs = st.tabs(["📊 Dashboard", "🔎 Scanner", "📌 Chi tiết mã", "🧮 Strategy Matrix", "🛠️ Cảnh báo & bản vá"])
if scan is None:
    with tabs[0]:
        st.info("Chọn cấu hình ở sidebar rồi bấm **▶️ QUÉT**. Lần quét đầu tiên với ~240 mã có thể mất vài phút vì phải tải dữ liệu; "
                "các lần sau dùng cache theo phiên giao dịch.")
    with tabs[4]:
        pages.audit_page(None)
else:
    if st.session_state.get("scan_demo"):
        st.warning("🧪 Kết quả hiển thị đang là từ dữ liệu GIẢ LẬP.")
    with tabs[0]: pages.dashboard(scan, store, cfg["demo"])
    with tabs[1]: pages.scanner(scan, store)
    with tabs[2]: pages.detail(scan, store)
    with tabs[3]: pages.matrix(scan)
    with tabs[4]: pages.audit_page(scan)
