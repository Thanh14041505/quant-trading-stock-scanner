"""Biểu đồ giá/khối lượng/RSI cho màn hình chi tiết.

LƯU Ý: các đường MA/RSI ở đây CHỈ để người dùng quan sát — KHÔNG phải input của 7 strategy
(mỗi strategy tự tính indicator theo notebook gốc của nó; xem audit B12: RSI SMA vs Wilder).

`price_chart(..., smc_result=...)`: khi truyền thêm kết quả phân tích SMC (strategies/smc.py — swing,
BOS/CHoCH, order block, FVG, liquidity, premium/discount), biểu đồ nến sẽ vẽ chồng cấu trúc này lên —
đúng phần "chi tiết dựa trên đồ thị" mà S9 bổ sung so với các strategy chỉ chấm điểm tại 1 phiên.

HAI ĐIỂM ĐÃ SỬA SAU PHẢN HỒI THỰC TẾ (ảnh chụp màn hình cho thấy chart quá rối + có khoảng trống):
  1. Trục X dùng NHÃN DẠNG CHUỖI (categorical), không dùng datetime thật — nến liền kề nhau bất kể cách
     nhau bao nhiêu ngày lịch, nên thứ Bảy/Chủ Nhật/nghỉ lễ KHÔNG còn tạo khoảng trống trên biểu đồ (đây
     là cách hầu hết nền tảng trading thực tế vẽ, không riêng TradingView).
  2. MỌI loại cấu trúc SMC đều bị GIỚI HẠN SỐ LƯỢNG hiển thị (`_MAX_*` bên dưới) — ưu tiên phần tử GẦN
     GIÁ HIỆN TẠI/GẦN THỜI ĐIỂM HIỆN TẠI nhất. Trước đó vẽ hết TOÀN BỘ swing/OB/FVG/liquidity/BOS-CHoCH
     tìm được trong cả cửa sổ hiển thị (180 phiên) — với dữ liệu thật nhiều tháng, số lượng này có thể
     lên tới hàng chục, chồng chéo nhãn chữ và tạo dải màu đặc kín màn hình (đúng như ảnh bạn gửi). Order
     Block cũ không bao giờ bị test cũng không còn kéo dài tới hết khung hình nữa — giới hạn tối đa
     `_OB_MAX_SPAN_BARS` phiên để không tạo dải màu khổng lồ.

LƯU Ý KỸ THUẬT: trục X dạng category (chuỗi) khiến `add_hline`/`add_vline` kèm `annotation_text` TỰ ĐỘNG
bị lỗi trong plotly (nội bộ cố tính trung bình giá trị X dạng SỐ để đặt nhãn, trong khi X ở đây là chuỗi)
— nên mọi đường kẻ + nhãn SMC bên dưới đều dùng `add_shape` + `add_annotation` thủ công, không dùng
`add_hline`/`add_vline`.
"""
from __future__ import annotations
from typing import Optional
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

OB_BULL_OPEN = "rgba(34,197,94,0.22)"
OB_BULL_MIT = "rgba(34,197,94,0.08)"
OB_BEAR_OPEN = "rgba(239,68,68,0.22)"
OB_BEAR_MIT = "rgba(239,68,68,0.08)"
FVG_BULL = "rgba(14,165,233,0.18)"
FVG_BEAR = "rgba(249,115,22,0.18)"
LIQ_BUY = "#a855f7"
LIQ_SELL = "#f59e0b"
CHOCH_COLOR = "#ef4444"
BOS_COLOR = "#3b82f6"

# Giới hạn số lượng phần tử vẽ (chỉ áp dụng cho OVERLAY SMC, không ảnh hưởng tín hiệu/logic của S9) —
# chỉnh ở đây nếu muốn chart "dày"/"mỏng" hơn, không cần sửa logic bên dưới.
_MAX_EVENTS = 6          # số sự kiện BOS/CHoCH gần nhất hiển thị nhãn + đường dọc
_MAX_OB_EACH = 2         # số Order Block mỗi loại (tăng/giảm) GẦN GIÁ nhất
_MAX_FVG_EACH = 2        # số FVG chưa lấp mỗi loại GẦN GIÁ nhất
_MAX_LIQ_EACH = 2        # số Liquidity Pool mỗi phía (mua/bán) GẦN GIÁ nhất
_OB_MAX_SPAN_BARS = 40   # 1 Order Block/FVG chưa test tối đa kéo dài bao nhiêu phiên trên hình (tránh dải màu khổng lồ)


def price_chart(raw: pd.DataFrame, symbol: str, bars: int = 180, dark: bool = False, smc_result=None) -> go.Figure:
    df = raw.drop(columns=["_src"], errors="ignore").copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    df["_x"] = df["time"].dt.strftime("%d/%m/%y")   # nhãn trục X dạng chuỗi — bỏ qua khoảng trống lịch
    for n in (20, 50, 200):
        df[f"ma{n}"] = df["close"].rolling(n).mean()
    d = df["close"].diff()
    g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + g / l.replace(0, float("nan")))

    n_total = len(df)
    start_idx = max(0, n_total - bars)
    v = df.iloc[start_idx:].reset_index(drop=True)

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=v["_x"], open=v["open"], high=v["high"], low=v["low"], close=v["close"],
                                 name=symbol, increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), 1, 1)
    for n, col in ((20, "#f2b134"), (50, "#3b82f6"), (200, "#a855f7")):
        fig.add_trace(go.Scatter(x=v["_x"], y=v[f"ma{n}"], name=f"MA{n}", line=dict(width=1.2, color=col)), 1, 1)
    fig.add_trace(go.Bar(x=v["_x"], y=v["volume"], name="Volume", marker_color="#94a3b8"), 2, 1)
    fig.add_trace(go.Scatter(x=v["_x"], y=v["rsi"], name="RSI14 (hiển thị)", line=dict(color="#0ea5e9")), 3, 1)
    for y in (30, 70):
        fig.add_hline(y=y, line_dash="dot", line_color="#94a3b8", row=3, col=1)

    if smc_result is not None:
        _overlay_smc(fig, df, smc_result, start_idx)

    # Trục X dạng category: nến cách đều nhau, T7/CN/nghỉ lễ không tạo khoảng trống. Giãn nhãn (nticks)
    # để không dày đặc chữ khi cửa sổ hiển thị có 100-180 phiên.
    fig.update_xaxes(type="category", nticks=14)
    fig.update_layout(height=680 if smc_result is not None else 620, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.04),
                      template="plotly_dark" if dark else "plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)" if not dark else "#0e1117",
                      plot_bgcolor="rgba(0,0,0,0)" if not dark else "#0e1117")
    return fig


def _nearest(items, key_price, price: float, n: int):
    """n phần tử có `key_price` gần `price` nhất (dùng để giới hạn số OB/FVG/Liquidity hiển thị)."""
    return sorted(items, key=lambda it: abs(key_price(it) - price))[:n]


def _overlay_smc(fig: go.Figure, df: pd.DataFrame, res, start_idx: int) -> None:
    """Vẽ chồng cấu trúc SMC lên row 1 (nến) — có giới hạn số lượng, xem hằng số `_MAX_*` đầu file."""
    x = df["_x"]
    last_idx = len(df) - 1
    last_x = x.iloc[last_idx]
    price = float(df["close"].iloc[-1])

    # Premium/Discount: dải nền theo biên range_low/range_high
    if res.range_low is not None and res.range_high is not None and res.range_high > res.range_low:
        mid = (res.range_low + res.range_high) / 2
        fig.add_hrect(y0=mid, y1=res.range_high, fillcolor="rgba(239,68,68,0.05)", line_width=0, row=1, col=1)
        fig.add_hrect(y0=res.range_low, y1=mid, fillcolor="rgba(34,197,94,0.05)", line_width=0, row=1, col=1)

    # Swing: tam giác — chỉ trong cửa sổ hiển thị (số lượng swing vốn đã thưa, không cần giới hạn thêm)
    sw_x_h, sw_y_h, sw_x_l, sw_y_l = [], [], [], []
    for s in res.swings:
        if s.idx < start_idx or s.idx > last_idx:
            continue
        if s.kind == "high":
            sw_x_h.append(x.iloc[s.idx]); sw_y_h.append(s.price)
        else:
            sw_x_l.append(x.iloc[s.idx]); sw_y_l.append(s.price)
    if sw_x_h:
        fig.add_trace(go.Scatter(x=sw_x_h, y=sw_y_h, mode="markers", name="Swing High",
                                 marker=dict(symbol="triangle-down", size=8, color="#64748b")), 1, 1)
    if sw_x_l:
        fig.add_trace(go.Scatter(x=sw_x_l, y=sw_y_l, mode="markers", name="Swing Low",
                                 marker=dict(symbol="triangle-up", size=8, color="#64748b")), 1, 1)

    # Order blocks: chỉ _MAX_OB_EACH cái GẦN GIÁ nhất mỗi loại, và không kéo dài quá _OB_MAX_SPAN_BARS
    # phiên (trước đây 1 OB cũ chưa test có thể kéo dài tới hết khung hình -> dải màu khổng lồ như ảnh).
    for kind, color_open, color_mit in (("bullish", OB_BULL_OPEN, OB_BULL_MIT), ("bearish", OB_BEAR_OPEN, OB_BEAR_MIT)):
        obs_in_view = [o for o in res.order_blocks if o.kind == kind
                      and (o.mitigated_idx is None or o.mitigated_idx >= start_idx) and o.idx <= last_idx]
        for ob in _nearest(obs_in_view, lambda o: (o.top + o.bottom) / 2, price, _MAX_OB_EACH):
            natural_end = ob.mitigated_idx if ob.mitigated_idx is not None else last_idx
            end_idx = min(natural_end, ob.idx + _OB_MAX_SPAN_BARS, last_idx)
            x_start = x.iloc[max(ob.idx, start_idx)]
            x_end = x.iloc[end_idx]
            fig.add_shape(type="rect", x0=x_start, x1=x_end, y0=ob.bottom, y1=ob.top,
                         fillcolor=color_mit if ob.mitigated else color_open, line=dict(width=0), row=1, col=1)
            if not ob.mitigated:
                label = "OB tăng" if kind == "bullish" else "OB giảm"
                fig.add_annotation(x=x_end, y=ob.top, text=label, showarrow=False,
                                   font=dict(size=9, color="#16a34a" if kind == "bullish" else "#dc2626"),
                                   xanchor="right", yanchor="bottom", row=1, col=1)

    # FVG chưa lấp: chỉ _MAX_FVG_EACH cái GẦN GIÁ nhất mỗi loại
    for kind, color in (("bullish", FVG_BULL), ("bearish", FVG_BEAR)):
        fvgs_open = [f for f in res.fvgs if f.kind == kind and not f.filled and start_idx <= f.idx <= last_idx]
        for f in _nearest(fvgs_open, lambda f: (f.top + f.bottom) / 2, price, _MAX_FVG_EACH):
            x_end = x.iloc[min(f.idx + _OB_MAX_SPAN_BARS, last_idx)]
            fig.add_shape(type="rect", x0=x.iloc[f.idx], x1=x_end, y0=f.bottom, y1=f.top,
                         fillcolor=color, line=dict(width=0), row=1, col=1)

    # Liquidity pools: chỉ _MAX_LIQ_EACH mức GẦN GIÁ nhất mỗi phía (mua/bán) — tránh dày đặc đường ngang.
    # xref="x domain" (0..1) để kẻ hết chiều ngang mà không phụ thuộc giá trị X cụ thể nào.
    for kind, color in (("buy_side", LIQ_BUY), ("sell_side", LIQ_SELL)):
        pools = [p for p in res.liquidity if p.kind == kind]
        for p in _nearest(pools, lambda p: p.price, price, _MAX_LIQ_EACH):
            dash = "dot" if not p.swept else "dash"
            fig.add_shape(type="line", xref="x domain", x0=0, x1=1, y0=p.price, y1=p.price,
                         line=dict(color=color, width=1, dash=dash), row=1, col=1)
            fig.add_annotation(x=last_x, y=p.price, text="Liquidity" + (" (swept)" if p.swept else ""),
                               showarrow=False, font=dict(size=8, color=color), xanchor="right",
                               yanchor="bottom", row=1, col=1)

    # BOS/CHoCH: chỉ _MAX_EVENTS sự kiện GẦN HIỆN TẠI nhất trong cửa sổ hiển thị (trước đây vẽ HẾT, với
    # dữ liệu nhiều tháng có thể vài chục sự kiện -> chữ chồng lên nhau không đọc nổi như ảnh bạn gửi).
    # yref="y domain" (0..1) để kẻ hết chiều dọc của ô (row 1) mà không cần biết trước biên độ giá.
    events_in_view = [e for e in res.events if start_idx <= e.idx <= last_idx]
    for ev in events_in_view[-_MAX_EVENTS:]:
        is_choch = "CHOCH" in ev.kind
        color = CHOCH_COLOR if is_choch else BOS_COLOR
        ev_x = x.iloc[ev.idx]
        fig.add_shape(type="line", xref="x", yref="y domain", x0=ev_x, x1=ev_x, y0=0, y1=1,
                     line=dict(color=color, width=1, dash="dash"), row=1, col=1)
        fig.add_annotation(x=ev_x, y=1, yref="y domain", text=ev.kind.replace("_", " "), showarrow=False,
                           font=dict(size=9, color=color), yanchor="bottom", row=1, col=1)
