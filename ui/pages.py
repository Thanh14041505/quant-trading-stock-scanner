"""Các màn hình: Dashboard, Scanner, Stock Detail, Strategy Matrix, Audit."""
from __future__ import annotations
from datetime import datetime
import pandas as pd
import streamlit as st

from engine.tables import scanner_df, matrix_df
from engine.runner import ScanResult
from strategies.base import SHORT, BULLISH
from strategies.registry import REGISTRY
from config.legacy_flags import PATCHES
from ui.charts import price_chart

SIG_COLOR = {"SB": "#166534;color:white", "B": "#86efac", "W": "#fde68a", "N": "#e5e7eb", "R": "#fdba74",
             "X": "#fca5a5", "F": "#cbd5e1", "–": "#f1f5f9", "E": "#f87171;color:white", "U": "#f1f5f9"}
LEGEND = "SB=Strong Buy · B=Buy · W=Watch · N=Không tín hiệu · R=Reduce · X=Exit · F=Bị lọc · –=Không dữ liệu · E=Lỗi"


def _style_sig(df: pd.DataFrame, cols):
    return df.style.map(lambda v: f"background-color:{SIG_COLOR.get(v, '')}" if v in SIG_COLOR else "", subset=cols)


def dashboard(scan: ScanResult, store, demo: bool):
    st.subheader("Tổng quan")
    c = st.columns(5)
    c[0].metric("Ngày quét", datetime.now().strftime("%d/%m/%Y %H:%M"))
    c[1].metric("Dữ liệu tới phiên", str(scan.as_of))
    c[2].metric("Số mã yêu cầu / có dữ liệu", f"{len(scan.symbols)} / {scan.n_symbols_ok_data}")
    c[3].metric("Mode", "Swing T+" if scan.mode == "swing" else "Hold")
    c[4].metric("Thời gian quét", f"{scan.timings.get('total', 0):.0f}s")
    if scan.fetch_errors:
        with st.expander(f"⚠️ {len(scan.fetch_errors)} mã lỗi dữ liệu (API)"):
            st.dataframe(pd.DataFrame({"Mã": list(scan.fetch_errors), "Lỗi": list(scan.fetch_errors.values())}), hide_index=True)
    st.caption(f"Cache: {scan.data_stats}")

    st.subheader("Market regime của từng strategy")
    rows = []
    for sid in scan.sids:
        p = scan.prep.get(sid, {})
        rows.append({"Strategy": sid, "Regime": p.get("regime", "—"), "Mô tả": p.get("label", p.get("error", "")),
                     "Score×": p.get("score_mult"), "Min score": p.get("min_score"), "VNINDEX": p.get("vnindex"),
                     "Lỗi khởi tạo": p.get("error", "")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Mỗi notebook tự phân loại regime theo luật riêng (S1–S6: 4 mức; S7: 5 mức từ điểm 0–100). "
               "S1–S6 vướng bug B1 (MA200 thực chất là EMA30) nếu chưa bật bản vá.")

    st.subheader("Tóm tắt theo strategy")
    rows = []
    for sid in scan.sids:
        cnt = pd.Series([scan.results[s][sid].signal for s in scan.symbols]).value_counts()
        row = {"Strategy": f"{sid} (dòng {REGISTRY[sid].info.family})"}
        for sig in ("STRONG_BUY", "BUY", "WATCH", "NONE", "REDUCE", "EXIT", "FILTERED", "NO_DATA", "ERROR"):
            row[SHORT[sig]] = int(cnt.get(sig, 0))
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(LEGEND)

    st.subheader("Tóm tắt đồng thuận (Meta engine)")
    labels = pd.Series([scan.consensus[s].label for s in scan.symbols]).value_counts().rename_axis("Consensus").reset_index(name="Số mã")
    a, b = st.columns([1, 2])
    a.dataframe(labels, hide_index=True, width="stretch")
    df = scanner_df(scan, store)
    top = df[df["Consensus"].isin(["ĐỒNG THUẬN MUA", "NGHIÊNG MUA"])].head(10)
    b.markdown("**Top mã nghiêng mua**")
    b.dataframe(top[["Ticker", "Consensus", "Bull", "Families", "Score", "Lead"]] if not top.empty else pd.DataFrame(), hide_index=True, width="stretch")
    st.info("ℹ️ **Bull** = số strategy nghiêng mua / số strategy có đánh giá. **Families** = số *dòng code* (A/B/C/D) nghiêng mua — "
            "S1–S2, S3–S4, S5–S6 gần như cùng một bộ não nên chỉ nên xem là 1 phiếu.")


def scanner(scan: ScanResult, store):
    st.subheader("Scanner")
    df = scanner_df(scan, store)
    f1, f2, f3, f4 = st.columns([2, 2, 1, 1])
    q = f1.text_input("Tìm mã", "").upper().strip()
    cons = f2.multiselect("Consensus", sorted(df["Consensus"].unique()), default=[])
    minbull = f3.number_input("Tối thiểu strategy MUA", 0, len(scan.sids), 0)
    only_conf = f4.checkbox("Chỉ mã có xung đột")
    v = df.copy()
    if q: v = v[v["Ticker"].str.contains(q)]
    if cons: v = v[v["Consensus"].isin(cons)]
    if minbull: v = v[v["Bull"].str.split("/").str[0].astype(int) >= minbull]
    if only_conf: v = v[v["Conflict"] != ""]
    st.caption(f"{len(v)}/{len(df)} mã · {LEGEND}")
    st.caption("Entry/SL/TP/R:R lấy từ **strategy dẫn đầu (Lead)** = strategy nghiêng mua có điểm cao nhất; đơn vị giá theo API. "
               "R:R của các strategy tính theo T1 hoặc T2 khác nhau (xem cột 'R:R basis').")
    st.dataframe(_style_sig(v, list(scan.sids)), hide_index=True, width="stretch", height=560)
    st.download_button("⬇️ Tải CSV", v.to_csv(index=False).encode("utf-8-sig"), "scanner.csv", "text/csv")


def detail(scan: ScanResult, store):
    st.subheader("Chi tiết mã")
    sym = st.selectbox("Chọn mã", scan.symbols)
    if not sym:
        return
    c = scan.consensus[sym]
    m = st.columns(4)
    m[0].metric("Consensus", c.label)
    m[1].metric("Mua / có đánh giá", f"{c.n_bull}/{c.n_active}")
    m[2].metric("Dòng code nghiêng mua", f"{c.n_bull_families}/{c.n_families}")
    m[3].metric("Điểm TB (thống kê, 0–100)", c.agg_score if c.agg_score is not None else "—")
    if c.conflict:
        st.warning("⚡ Bất đồng: " + c.conflict)
    for line in c.disagreement:
        st.caption(line)
    try:
        st.plotly_chart(price_chart(store.get_raw(sym), sym), width="stretch")
        st.caption("MA/RSI trên biểu đồ chỉ để tham khảo — không phải input của các strategy.")
    except Exception as e:  # noqa: BLE001
        st.error(f"Không vẽ được biểu đồ: {e}")
    tabs = st.tabs([f"{sid} {SHORT[scan.results[sym][sid].signal]}" for sid in scan.sids])
    for tab, sid in zip(tabs, scan.sids):
        r = scan.results[sym][sid]
        with tab:
            info = REGISTRY[sid].info
            st.markdown(f"**{sid} · {info.name}** (dòng {info.family}) — *{info.notebook}*")
            a = st.columns(4)
            a[0].metric("Tín hiệu gốc", r.native_signal[:40] or "—")
            a[1].metric("Chuẩn hoá", r.signal)
            a[2].metric(f"Điểm (thang {r.score_scale})", r.score if r.score is not None else "—")
            a[3].metric("Trạng thái", r.status)
            if r.status in ("ERROR", "NO_DATA", "UNSUPPORTED") or (r.status == "FILTERED" and not r.entry):
                for w in r.warnings: st.error(w) if r.status == "ERROR" else st.info(w)
            if sid == "S7":
                st.info(f"S7 chỉ đưa ra % gợi ý: SL ≈ −{r.sl_pct}% · TP ≈ +{r.tp_pct}% (R:R≈2 theo cấu tạo). Không có Entry/SL/TP tuyệt đối.") if r.sl_pct else None
            else:
                b = st.columns(5)
                fmt = lambda x: "—" if x is None else f"{x:,.2f}"   # noqa: E731
                b[0].metric("Entry", fmt(r.entry)); b[1].metric("SL", fmt(r.stop_loss))
                b[2].metric("TP1", fmt(r.take_profit)); b[3].metric("TP2", fmt(r.take_profit_2))
                b[4].metric(f"R:R (theo {r.rr_basis or '—'})", fmt(r.risk_reward))
            if r.setup: st.markdown(f"**Setup:** {r.setup}")
            if r.holder_advice: st.markdown(f"**Cho người đang giữ:** {r.holder_advice}")
            x1, x2 = st.columns(2)
            with x1:
                st.markdown("**✅ Điều kiện/điểm mạnh (sub-score ≥ 6.5 hoặc lý do của notebook)**")
                for t in r.passed_conditions or ["—"]: st.write("• " + t)
                if r.reasons and r.reasons != r.passed_conditions:
                    st.markdown("**Lý do**"); [st.write("• " + t) for t in r.reasons]
            with x2:
                st.markdown("**⛔ Điều kiện không đạt / bộ lọc cứng**")
                for t in r.failed_conditions or ["—"]: st.write("• " + t)
            if r.warnings and r.status == "OK":
                st.markdown("**⚠️ Cảnh báo**"); [st.warning(w) for w in r.warnings]
            with st.expander("Ghi chú khác biệt/bug của notebook gốc áp dụng cho strategy này"):
                for n in r.legacy_notes: st.write("• " + n)
            with st.expander("Output gốc của notebook (đối chiếu)"):
                st.json({k: v for k, v in r.extra.items() if not str(k).startswith("_stdout")})


def matrix(scan: ScanResult):
    st.subheader("Strategy Matrix")
    df = matrix_df(scan)
    c1, c2, c3 = st.columns([2, 2, 1])
    want = c1.multiselect("Hiện mã có ít nhất 1 strategy ở trạng thái", ["SB", "B", "W", "N", "R", "X", "F", "–", "E"], default=[])
    exact = c2.multiselect("Hoặc lọc theo strategy cụ thể (Sx=tín hiệu, ví dụ S5=B)", [f"{s}={k}" for s in scan.sids for k in ("SB", "B", "W", "R", "X")])
    only_conf = c3.checkbox("Chỉ xung đột")
    v = df.copy()
    if want: v = v[v[list(scan.sids)].isin(want).any(axis=1)]
    for e in exact:
        s, k = e.split("="); v = v[v[s] == k]
    if only_conf: v = v[v["Conflict"] != ""]
    st.caption(f"{len(v)} mã · {LEGEND}")
    st.dataframe(_style_sig(v, list(scan.sids)), hide_index=True, width="stretch", height=560)
    st.markdown("**Phiếu theo dòng code (A: S1–S2 · B: S3–S4 · C: S5–S6 · D: S7)**")
    fam = pd.DataFrame([{"Ticker": s, **{f"Dòng {k}": SHORT.get(x, x) if x != "MIXED" else "MIX" for k, x in scan.consensus[s].family_votes.items()}}
                        for s in v["Ticker"]])
    if not fam.empty:
        st.dataframe(fam, hide_index=True, width="stretch")


def audit_page(scan: ScanResult | None):
    st.subheader("Cảnh báo & bản vá")
    st.markdown("Kết quả gốc của notebook luôn được giữ. Bảng dưới liệt kê bản vá và trạng thái trong lượt quét gần nhất.")
    rows = [{"ID": p["ids"], "Bản vá": p["label"], "Áp dụng": p["strategies"],
             "Trạng thái": ("BẬT" if (scan.patches.get(k, p["default"]) if scan else p["default"]) else "TẮT (hành vi gốc)"),
             "Vì sao": p["why"]} for k, p in PATCHES.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.markdown("Chi tiết đầy đủ B1–B17 / L1–L5: xem `docs/audit_7_notebooks.md`.")
