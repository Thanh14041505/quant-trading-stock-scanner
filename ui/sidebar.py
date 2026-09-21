"""Sidebar: nguồn dữ liệu, mode, universe, strategy, tham số, bản vá."""
from __future__ import annotations
import hashlib
import streamlit as st

from config.legacy_flags import PATCHES
from data import ratelimit
from strategies.registry import REGISTRY


def _api_key() -> str:
    """Ưu tiên: ô nhập (password) -> st.secrets -> biến môi trường. KHÔNG bao giờ ghi key ra đĩa/log."""
    typed = st.session_state.get("api_key_input", "")
    if typed:
        return typed
    try:
        return st.secrets.get("VNSTOCK_API_KEY", "")
    except Exception:
        import os
        return os.environ.get("VNSTOCK_API_KEY", "")


@st.cache_resource(show_spinner=False)
def get_store(kind: str, key_hash: str, _key: str):
    """Store sống qua các lần rerun của Streamlit (cache_resource). key_hash chỉ để tạo khoá cache, không lưu key."""
    from data.store import OHLCVStore
    if kind == "demo":
        from data.demo import DemoProvider
        return OHLCVStore(DemoProvider(), cache_dir=".cache/demo", use_disk=False)
    from data.provider import VnstockProvider
    return OHLCVStore(VnstockProvider(_key or None), cache_dir=".cache/ohlcv", use_disk=True)


def render_sidebar() -> dict:
    sb = st.sidebar
    sb.title("⚙️ Cấu hình quét")
    sb.subheader("Dữ liệu")
    demo = sb.checkbox("Dùng dữ liệu GIẢ LẬP (demo, không cần API key)", value=False,
                       help="Chỉ để xem thử giao diện. KHÔNG phải dữ liệu thị trường.")
    sb.text_input("Vnstock API Key", type="password", key="api_key_input",
                  help="Không được lưu. Có thể đặt trong st.secrets['VNSTOCK_API_KEY'] khi deploy.",
                  disabled=demo)
    key = _api_key()
    sb.caption("🔑 Key: " + ("đã có" if key else "chưa có (có thể vẫn chạy ở gói miễn phí — tuỳ giới hạn của vnstock)") if not demo else "🧪 Đang dùng dữ liệu demo")

    rpm = sb.number_input("Giới hạn request/phút (theo gói API)", min_value=5, max_value=600,
                          value=55 if key else 18, step=5, key=f"rpm_{bool(key)}", disabled=demo,
                          help="Khách ≈ 20, Community (có API key) ≈ 60, Sponsor 180–600. Đặt thấp hơn trần một chút để an toàn. "
                               "Chạm trần vnstock sẽ tự dừng ứng dụng (SystemExit).")
    ratelimit.configure(rpm)

    sb.subheader("Chế độ")
    mode_label = sb.radio("Mode giao dịch", ["Swing T+", "Hold"], horizontal=True,
                          help="Áp dụng cho S1–S6 (mỗi notebook có 2 chế độ). S7 không có mode riêng.")
    mode = "swing" if mode_label.startswith("Swing") else "hold"

    sb.subheader("Universe")
    from strategies._legacy import s07_legacy
    default_syms = list(dict.fromkeys(s07_legacy.MY_STOCKS))
    txt = sb.text_area("Danh sách mã (cách nhau bởi dấu phẩy/xuống dòng)", value=", ".join(default_syms), height=110)
    syms = [s.strip().upper() for s in txt.replace("\n", ",").split(",") if s.strip()]
    limit = sb.number_input("Chỉ quét N mã đầu (0 = tất cả)", min_value=0, max_value=len(syms) or 1, value=0, step=10)
    if limit:
        syms = syms[: int(limit)]
    sb.caption(f"{len(syms)} mã sẽ được quét")

    sb.subheader("Strategy")
    sids = sb.multiselect("Chạy các strategy", list(REGISTRY), default=list(REGISTRY),
                          format_func=lambda s: f"{s} · {REGISTRY[s].info.name}")
    capital = sb.number_input("Vốn (VND) — dùng cho position sizing S1–S6", min_value=1_000_000,
                              value=100_000_000, step=10_000_000)

    sb.subheader("Bản vá bug/khác biệt")
    sb.caption("Mặc định = hành vi GỐC của notebook (trừ nến chưa đóng & S3 Hold). Chi tiết: audit B*/L*.")
    patches = {}
    for k, p in PATCHES.items():
        patches[k] = sb.checkbox(f"{p['ids']} · {p['label']}", value=p["default"], help=f"{p['why']} (áp dụng: {p['strategies']})")

    overrides = {}
    with sb.expander("Tham số từng strategy (default = notebook)"):
        st.caption("Chỉ giá trị bạn ĐỔI khác default mới được áp dụng.")
        for sid in sids:
            defaults = REGISTRY[sid].default_config()
            with st.expander(f"{sid} · {REGISTRY[sid].info.name}"):
                for name, dv in defaults.items():
                    if isinstance(dv, bool):
                        val = st.checkbox(name, value=dv, key=f"p_{sid}_{name}")
                    elif isinstance(dv, int):
                        val = st.number_input(name, value=int(dv), step=1, key=f"p_{sid}_{name}")
                    else:
                        val = st.number_input(name, value=float(dv), format="%.4f", key=f"p_{sid}_{name}")
                    if val != dv:
                        overrides.setdefault(sid, {})[name] = val

    sb.subheader("Hiệu năng / API")
    workers = sb.slider("Số luồng tải dữ liệu", 1, 6, 2, help="Tăng nếu API key cho phép; quá cao dễ bị giới hạn tốc độ.")
    delay = sb.slider("Nghỉ giữa các request (giây)", 0.0, 2.0, 0.3, 0.1)
    return dict(demo=demo, key=key, mode=mode, symbols=syms, sids=sids, capital=float(capital), patches=patches,
                overrides=overrides, workers=workers, delay=delay,
                key_hash=hashlib.sha256(key.encode()).hexdigest()[:8] if key else "")
