"""Sidebar: nguồn dữ liệu, mode, universe, strategy, tham số, bản vá."""
from __future__ import annotations
import hashlib
import streamlit as st

from config.legacy_flags import PATCHES
from config.shared_params import build_shared_groups, representative_default
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
    dark = sb.toggle("🌙 Dark mode", value=False, key="dark_mode")
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
                          format_func=lambda s: f"{s} · {REGISTRY[s].info.name}"
                          + (" [AI — tham khảo]" if REGISTRY[s].info.family == "E" else ""))
    sb.caption("**S8** là góc đọc kỹ thuật riêng của trợ lý AI (không thuộc 7 notebook gốc). "
               "Mặc định KHÔNG tính vào Consensus — bật ở mục Bản vá bên dưới nếu muốn tính chung.")
    capital = sb.number_input("Vốn (VND) — dùng cho position sizing S1–S6", min_value=1_000_000,
                              value=100_000_000, step=10_000_000)

    sb.subheader("Bản vá bug/khác biệt")
    sb.caption("Mặc định = hành vi GỐC của notebook (trừ nến chưa đóng & S3 Hold). Chi tiết: audit B*/L*.")
    patches = {}
    for k, p in PATCHES.items():
        patches[k] = sb.checkbox(f"{p['ids']} · {p['label']}", value=p["default"], help=f"{p['why']} (áp dụng: {p['strategies']})")
    patches["include_ai_in_consensus"] = sb.checkbox(
        "P3 · Tính S8 (AI) vào Consensus/Entry-SL-TP tự động của Scanner", value=False,
        help="Mặc định S8 chỉ hiển thị RIÊNG (tab Chi tiết mã, cột S8) — không gộp phiếu với 7 notebook, "
             "đúng tinh thần '7 trading brains độc lập' của yêu cầu gốc. Bật nếu bạn muốn xem AI như brain thứ 8.")

    overrides: dict = {}
    defaults_by_sid = {sid: REGISTRY[sid].default_config() for sid in sids}
    shared_groups = build_shared_groups(defaults_by_sid)

    def _widget(label, dv, key):
        if isinstance(dv, bool):
            return st.checkbox(label, value=dv, key=key)
        if isinstance(dv, int):
            return st.number_input(label, value=int(dv), step=1, key=key)
        return st.number_input(label, value=float(dv), format="%.4f", key=key)

    with sb.expander(f"🔗 Tham số DÙNG CHUNG — sửa 1 lần, áp dụng cho mọi strategy có tham số đó ({sum(len(v) for v in shared_groups.values())} tham số)"):
        st.caption("Đổi 1 ô ở đây = ghi đè cho TẤT CẢ strategy đang chọn có cùng tên tham số này, kể cả khi "
                   "default gốc của chúng khác nhau (xem caption từng ô). Muốn 1 strategy giữ giá trị khác riêng — "
                   "sửa tiếp ở mục 'Tham số riêng từng Strategy' bên dưới, nó sẽ ghi đè lại CHỈ cho strategy đó.")
        if not shared_groups:
            st.caption("Chưa có strategy nào đang chọn chia sẻ tham số trùng tên.")
        for label, items in shared_groups.items():
            with st.expander(f"{label} ({len(items)})"):
                for name, by_sid in items:
                    rep = representative_default(by_sid)
                    val = _widget(name, rep, key=f"shared_{name}")
                    applies_to = sorted(by_sid, key=lambda s: (len(s), s))
                    diff = {s: v for s, v in by_sid.items() if v != rep}
                    cap = f"Áp dụng: {', '.join(applies_to)}"
                    if diff:
                        cap += "  ·  default GỐC khác nhau: " + ", ".join(f"{s}={v}" for s, v in diff.items())
                    st.caption(cap)
                    if val != rep:
                        for s in applies_to:
                            overrides.setdefault(s, {})[name] = val

    with sb.expander("Tham số riêng từng Strategy (ghi đè thêm cho 1 strategy, ưu tiên cao hơn mục dùng chung)"):
        st.caption("Chỉ giá trị bạn ĐỔI khác default mới được áp dụng. Tham số đã sửa ở mục 'dùng chung' vẫn "
                   "hiện ở đây (có 🔗) — sửa tiếp tại đây để ghi đè riêng cho strategy này.")
        shared_names = {name for items in shared_groups.values() for name, _ in items}
        for sid in sids:
            defaults = defaults_by_sid[sid]
            with st.expander(f"{sid} · {REGISTRY[sid].info.name}"):
                for name, dv in defaults.items():
                    label = f"🔗 {name}" if name in shared_names else name
                    val = _widget(label, dv, key=f"p_{sid}_{name}")
                    if val != dv:
                        overrides.setdefault(sid, {})[name] = val

    sb.subheader("Hiệu năng / API")
    workers = sb.slider("Số luồng tải dữ liệu", 1, 6, 2, help="Tăng nếu API key cho phép; quá cao dễ bị giới hạn tốc độ.")
    delay = sb.slider("Nghỉ giữa các request (giây)", 0.0, 2.0, 0.3, 0.1)
    return dict(demo=demo, key=key, mode=mode, symbols=syms, sids=sids, capital=float(capital), patches=patches,
                overrides=overrides, workers=workers, delay=delay, dark=dark,
                key_hash=hashlib.sha256(key.encode()).hexdigest()[:8] if key else "")
