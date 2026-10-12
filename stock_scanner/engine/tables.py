"""Chuyển ScanResult thành DataFrame cho UI (Scanner, Strategy Matrix)."""
from __future__ import annotations
from typing import Optional
import pandas as pd
from strategies.base import SHORT, BULLISH, STRONG_BUY
from engine.runner import ScanResult

_RANK = {STRONG_BUY: 0}      # STRONG_BUY ưu tiên trước BUY khi chọn strategy dẫn đầu


def last_close(store, symbol) -> Optional[float]:
    try:
        return float(store.get_raw(symbol)["close"].iloc[-1])
    except Exception:
        return None


def pick_levels(scan: ScanResult, symbol: str, price: Optional[float], eligible: Optional[set] = None) -> Optional[dict]:
    """
    Chọn bộ Entry/SL/TP/R:R hiển thị cho một mã.

    Thứ tự:
      1) Strategy nghiêng MUA (STRONG_BUY trước, rồi BUY) có ĐỦ Entry/SL/TP trong output gốc của notebook
         -> ưu tiên điểm (quy về 0–100) cao nhất. Đây là số liệu GỐC, không tính lại.
      2) Nếu chỉ S7 nghiêng mua (notebook S7 không có Entry/SL/TP tuyệt đối, chỉ có % gợi ý — audit B8):
         Entry = giá đóng cửa gần nhất, SL/TP = giá × (1 ∓ %) theo suggested_sl_pct/tp_pct của S7,
         R:R = tp% / sl%. Được đánh dấu "S7*" để không nhầm với số liệu gốc.
    """
    res = [r for sid, r in scan.results[symbol].items() if eligible is None or sid in eligible]
    full = [r for r in res if r.signal in BULLISH and None not in (r.entry, r.stop_loss, r.take_profit)]
    if full:
        b = min(full, key=lambda r: (_RANK.get(r.signal, 1), -(r.score_pct or 0), r.sid))
        return dict(lead=b.sid, setup=b.setup, entry=b.entry, sl=b.stop_loss, tp=b.take_profit,
                    rr=b.risk_reward, basis=b.rr_basis)
    pct = [r for r in res if r.signal in BULLISH and r.sl_pct and r.tp_pct]
    if pct and price:
        b = min(pct, key=lambda r: (_RANK.get(r.signal, 1), r.sid))
        return dict(lead=f"{b.sid}*", setup=f"{b.setup} · Entry = giá hiện tại; SL/TP suy ra từ % gợi ý của {b.sid}",
                    entry=price, sl=price * (1 - b.sl_pct / 100), tp=price * (1 + b.tp_pct / 100),
                    rr=b.tp_pct / b.sl_pct, basis=f"{b.sid} %")
    return None


def scanner_df(scan: ScanResult, store, include_ai: bool = False) -> pd.DataFrame:
    from strategies.registry import NOTEBOOK_SIDS
    eligible = set(scan.sids) if include_ai else set(scan.sids) & set(NOTEBOOK_SIDS)
    rows = []
    for s in scan.symbols:
        c = scan.consensus[s]
        r = scan.results[s]
        price = last_close(store, s)
        lv = pick_levels(scan, s, price, eligible) or {}
        row = {"Ticker": s, "Price": price}
        for sid in scan.sids:
            row[sid] = SHORT[r[sid].signal]
        row.update({
            "Consensus": c.label,
            "Bull": f"{c.n_bull}/{c.n_active}",
            "Families": f"{c.n_bull_families}/{c.n_families}",
            "Score": c.agg_score,
            "Lead": lv.get("lead", ""),
            "Setup": lv.get("setup", ""),
            "Entry": lv.get("entry"),
            "SL": lv.get("sl"),
            "TP": lv.get("tp"),
            "R:R": lv.get("rr"),
            "R:R basis": lv.get("basis", ""),
            "Conflict": c.conflict,
        })
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Làm tròn: giá 2 chữ số thập phân, R:R 3 chữ số (theo yêu cầu hiển thị)
    for col in ("Price", "Entry", "SL", "TP"):
        df[col] = pd.to_numeric(df[col], errors="coerce").round(2)
    df["R:R"] = pd.to_numeric(df["R:R"], errors="coerce").round(3)
    df["Score"] = pd.to_numeric(df["Score"], errors="coerce").round(1)
    order = {"ĐỒNG THUẬN MUA": 0, "NGHIÊNG MUA": 1, "PHÂN HOÁ (thiểu số mua)": 2, "PHÂN HOÁ (có cả mua và thoát)": 3,
             "THEO DÕI": 4, "TRUNG LẬP": 5, "TIÊU CỰC": 6, "KHÔNG CÓ DỮ LIỆU": 7}
    df["_o"] = df["Consensus"].map(order).fillna(9)
    return df.sort_values(["_o", "Score"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)


def matrix_df(scan: ScanResult) -> pd.DataFrame:
    rows = []
    for s in scan.symbols:
        row = {"Ticker": s}
        for sid in scan.sids:
            row[sid] = SHORT[scan.results[s][sid].signal]
        row["Conflict"] = scan.consensus[s].conflict
        rows.append(row)
    return pd.DataFrame(rows)
