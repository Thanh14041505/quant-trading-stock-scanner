"""Biểu đồ giá/khối lượng/RSI cho màn hình chi tiết.

LƯU Ý: các đường MA/RSI ở đây CHỈ để người dùng quan sát — KHÔNG phải input của 7 strategy
(mỗi strategy tự tính indicator theo notebook gốc của nó; xem audit B12: RSI SMA vs Wilder).

`price_chart(..., smc_result=...)`: khi truyền thêm kết quả phân tích SMC (strategies/smc.py — swing,
BOS/CHoCH, order block, FVG, liquidity, premium/discount), biểu đồ nến sẽ vẽ chồng toàn bộ cấu trúc này
lên — đúng phần "chi tiết dựa trên đồ thị" mà S9 bổ sung so với các strategy chỉ chấm điểm tại 1 phiên.
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


def price_chart(raw: pd.DataFrame, symbol: str, bars: int = 180, dark: bool = False, smc_result=None) -> go.Figure:
    df = raw.drop(columns=["_src"], errors="ignore").copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    for n in (20, 50, 200):
        df[f"ma{n}"] = df["close"].rolling(n).mean()
    d = df["close"].diff()
    g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + g / l.replace(0, float("nan")))

    n_total = len(df)
    start_idx = max(0, n_total - bars)
    v = df.iloc[start_idx:].reset_index(drop=True)
    x0, x1 = v["time"].iloc[0], v["time"].iloc[-1]

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=v["time"], open=v["open"], high=v["high"], low=v["low"], close=v["close"],
                                 name=symbol, increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), 1, 1)
    for n, col in ((20, "#f2b134"), (50, "#3b82f6"), (200, "#a855f7")):
        fig.add_trace(go.Scatter(x=v["time"], y=v[f"ma{n}"], name=f"MA{n}", line=dict(width=1.2, color=col)), 1, 1)
    fig.add_trace(go.Bar(x=v["time"], y=v["volume"], name="Volume", marker_color="#94a3b8"), 2, 1)
    fig.add_trace(go.Scatter(x=v["time"], y=v["rsi"], name="RSI14 (hiển thị)", line=dict(color="#0ea5e9")), 3, 1)
    for y in (30, 70):
        fig.add_hline(y=y, line_dash="dot", line_color="#94a3b8", row=3, col=1)

    if smc_result is not None:
        _overlay_smc(fig, df, smc_result, start_idx, x0, x1)

    fig.update_layout(height=680 if smc_result is not None else 620, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.04),
                      template="plotly_dark" if dark else "plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)" if not dark else "#0e1117",
                      plot_bgcolor="rgba(0,0,0,0)" if not dark else "#0e1117")
    return fig


def _overlay_smc(fig: go.Figure, df: pd.DataFrame, res, start_idx: int, x0, x1) -> None:
    """Vẽ chồng cấu trúc SMC lên row 1 (nến). Chỉ vẽ phần giao với cửa sổ đang hiển thị để đỡ rối."""
    times = df["time"]
    last_idx = len(df) - 1

    # Premium/Discount: dải nền theo biên range_low/range_high
    if res.range_low is not None and res.range_high is not None and res.range_high > res.range_low:
        mid = (res.range_low + res.range_high) / 2
        fig.add_hrect(y0=mid, y1=res.range_high, fillcolor="rgba(239,68,68,0.05)", line_width=0, row=1, col=1)
        fig.add_hrect(y0=res.range_low, y1=mid, fillcolor="rgba(34,197,94,0.05)", line_width=0, row=1, col=1)

    # Swing: tam giác tại đỉnh/đáy xoay trong cửa sổ hiển thị
    sw_x_h, sw_y_h, sw_x_l, sw_y_l = [], [], [], []
    for s in res.swings:
        if s.idx < start_idx or s.idx > last_idx:
            continue
        if s.kind == "high":
            sw_x_h.append(times.iloc[s.idx]); sw_y_h.append(s.price)
        else:
            sw_x_l.append(times.iloc[s.idx]); sw_y_l.append(s.price)
    if sw_x_h:
        fig.add_trace(go.Scatter(x=sw_x_h, y=sw_y_h, mode="markers", name="Swing High",
                                 marker=dict(symbol="triangle-down", size=8, color="#64748b")), 1, 1)
    if sw_x_l:
        fig.add_trace(go.Scatter(x=sw_x_l, y=sw_y_l, mode="markers", name="Swing Low",
                                 marker=dict(symbol="triangle-up", size=8, color="#64748b")), 1, 1)

    # Order blocks: hình chữ nhật từ nến hình thành tới hết cửa sổ (hoặc tới lúc mitigated)
    for ob in res.order_blocks:
        end_idx = ob.mitigated_idx if ob.mitigated_idx is not None else last_idx
        if end_idx < start_idx or ob.idx > last_idx:
            continue
        x_start = times.iloc[max(ob.idx, start_idx)]
        x_end = times.iloc[min(end_idx, last_idx)]
        color = (OB_BULL_MIT if ob.mitigated else OB_BULL_OPEN) if ob.kind == "bullish" else \
                (OB_BEAR_MIT if ob.mitigated else OB_BEAR_OPEN)
        fig.add_shape(type="rect", x0=x_start, x1=x_end, y0=ob.bottom, y1=ob.top, fillcolor=color,
                     line=dict(width=0), row=1, col=1)
        if not ob.mitigated and end_idx >= start_idx:
            label = "OB tăng" if ob.kind == "bullish" else "OB giảm"
            fig.add_annotation(x=x_end, y=ob.top, text=label, showarrow=False, font=dict(size=9, color="#16a34a" if ob.kind == "bullish" else "#dc2626"),
                               xanchor="right", yanchor="bottom", row=1, col=1)

    # FVG chưa lấp: dải mỏng
    for f in res.fvgs:
        if f.filled or f.idx < start_idx or f.idx > last_idx:
            continue
        x_start = times.iloc[f.idx]
        fig.add_shape(type="rect", x0=x_start, x1=x1, y0=f.bottom, y1=f.top,
                     fillcolor=FVG_BULL if f.kind == "bullish" else FVG_BEAR, line=dict(width=0), row=1, col=1)

    # Liquidity pools trong khoảng giá của cửa sổ hiển thị
    lo, hi = df["low"].iloc[start_idx:].min(), df["high"].iloc[start_idx:].max()
    for p in res.liquidity:
        if not (lo <= p.price <= hi):
            continue
        color = LIQ_BUY if p.kind == "buy_side" else LIQ_SELL
        dash = "dot" if not p.swept else "dash"
        fig.add_hline(y=p.price, line_dash=dash, line_color=color, line_width=1, row=1, col=1,
                     annotation_text=("Liquidity" + (" (swept)" if p.swept else "")),
                     annotation_position="right", annotation_font_size=8, annotation_font_color=color)

    # BOS/CHoCH: đường dọc + nhãn tại nến xác nhận phá cấu trúc
    for ev in res.events:
        if ev.idx < start_idx or ev.idx > last_idx:
            continue
        is_choch = "CHOCH" in ev.kind
        fig.add_vline(x=times.iloc[ev.idx], line_dash="dash", line_width=1,
                     line_color=CHOCH_COLOR if is_choch else BOS_COLOR, row=1, col=1,
                     annotation_text=ev.kind.replace("_", " "), annotation_position="top",
                     annotation_font_size=9, annotation_font_color=CHOCH_COLOR if is_choch else BOS_COLOR)
