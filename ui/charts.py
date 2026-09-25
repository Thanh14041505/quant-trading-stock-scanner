"""Biểu đồ giá/khối lượng/RSI cho màn hình chi tiết.

LƯU Ý: các đường MA/RSI ở đây CHỈ để người dùng quan sát — KHÔNG phải input của 7 strategy
(mỗi strategy tự tính indicator theo notebook gốc của nó; xem audit B12: RSI SMA vs Wilder).
"""
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def price_chart(raw: pd.DataFrame, symbol: str, bars: int = 180, dark: bool = False) -> go.Figure:
    df = raw.drop(columns=["_src"], errors="ignore").copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    for n in (20, 50, 200):
        df[f"ma{n}"] = df["close"].rolling(n).mean()
    d = df["close"].diff()
    g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + g / l.replace(0, float("nan")))
    v = df.tail(bars)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=v["time"], open=v["open"], high=v["high"], low=v["low"], close=v["close"],
                                 name=symbol, increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), 1, 1)
    for n, col in ((20, "#f2b134"), (50, "#3b82f6"), (200, "#a855f7")):
        fig.add_trace(go.Scatter(x=v["time"], y=v[f"ma{n}"], name=f"MA{n}", line=dict(width=1.2, color=col)), 1, 1)
    fig.add_trace(go.Bar(x=v["time"], y=v["volume"], name="Volume", marker_color="#94a3b8"), 2, 1)
    fig.add_trace(go.Scatter(x=v["time"], y=v["rsi"], name="RSI14 (hiển thị)", line=dict(color="#0ea5e9")), 3, 1)
    for y in (30, 70):
        fig.add_hline(y=y, line_dash="dot", line_color="#94a3b8", row=3, col=1)
    fig.update_layout(height=620, margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", y=1.04), template="plotly_dark" if dark else "plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)" if not dark else "#0e1117",
                      plot_bgcolor="rgba(0,0,0,0)" if not dark else "#0e1117")
    return fig
