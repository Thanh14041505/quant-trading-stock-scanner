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
from ui import theme                                        # noqa: E402
from engine.excel_export import export_bytes               # noqa: E402

st.title("📈 7-Strategy Stock Scanner — thị trường Việt Nam")
cfg = render_sidebar()
theme.apply(cfg["dark"])
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
        last = [0.0]
        def on_progress(stage, i, n, msg):
            n = max(n, 1)
            frac = {"benchmark": 0.02, "fetch": 0.05 + 0.35 * i / n, "fund": 0.40 + 0.10 * i / n,
                    "strategy": None, "symbols": 0.50 + 0.48 * i / n, "done": 1.0}.get(stage)
            text = {"benchmark": "Nạp VNINDEX…", "fetch": f"Tải dữ liệu giá {i}/{n} ({msg})",
                    "fund": f"Tải Fundamental {i}/{n} ({msg})", "strategy": f"Khởi tạo {msg}…",
                    "symbols": f"Chạy strategy: {msg} — {i}/{n}", "done": "Hoàn tất"}.get(stage, stage)
            last[0] = max(last[0], frac if frac is not None else last[0])   # thanh tiến độ không bao giờ lùi
            bar.progress(min(last[0], 1.0), text=text)
        try:
            scan_result = run_scan(
                store, cfg["symbols"], cfg["sids"], mode=cfg["mode"], capital=cfg["capital"],
                overrides=cfg["overrides"], patches=cfg["patches"], workers=cfg["workers"],
                delay=cfg["delay"], progress=on_progress)
            st.session_state["scan"] = scan_result
            st.session_state["scan_demo"] = cfg["demo"]
            bar.progress(1.0, text="Đang tạo file Excel…")
            try:
                st.session_state["scan_xlsx"] = export_bytes(scan_result)
            except Exception as e:  # noqa: BLE001 — lỗi tạo Excel không được làm mất kết quả quét vừa chạy
                st.session_state["scan_xlsx"] = None
                st.session_state["scan_xlsx_err"] = f"{type(e).__name__}: {e}"
            else:
                st.session_state.pop("scan_xlsx_err", None)
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
    xlsx = st.session_state.get("scan_xlsx")
    if xlsx:
        st.sidebar.download_button(
            "📥 Xuất Excel (mỗi strategy 1 sheet)", data=xlsx, file_name=f"scan_{scan.as_of}_{scan.mode}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    elif st.session_state.get("scan_xlsx_err"):
        st.sidebar.error(f"Không tạo được file Excel: {st.session_state['scan_xlsx_err']}")
    include_ai = cfg["patches"].get("include_ai_in_consensus", False)
    with tabs[0]: pages.dashboard(scan, store, cfg["demo"])
    with tabs[1]: pages.scanner(scan, store, include_ai)
    with tabs[2]: pages.detail(scan, store, cfg["dark"])
    with tabs[3]: pages.matrix(scan)
    with tabs[4]: pages.audit_page(scan)
