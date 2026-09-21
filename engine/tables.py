"""Chuyển ScanResult thành DataFrame cho UI (Scanner, Strategy Matrix)."""
from __future__ import annotations
from typing import Optional
import pandas as pd
from strategies.base import SHORT, BULLISH
from engine.runner import ScanResult


def last_close(store, symbol) -> Optional[float]:
    try:
        return float(store.get_raw(symbol)["close"].iloc[-1])
    except Exception:
        return None


def scanner_df(scan: ScanResult, store) -> pd.DataFrame:
    rows = []
    for s in scan.symbols:
        c = scan.consensus[s]
        r = scan.results[s]
        lead = r.get(c.lead) if c.lead else None
        row = {"Ticker": s, "Price": last_close(store, s)}
        for sid in scan.sids:
            row[sid] = SHORT[r[sid].signal]
        row.update({
            "Consensus": c.label,
            "Bull": f"{c.n_bull}/{c.n_active}",
            "Families": f"{c.n_bull_families}/{c.n_families}",
            "Score": c.agg_score,
            "Lead": c.lead,
            "Setup": lead.setup if lead else "",
            "Entry": lead.entry if lead else None,
            "SL": lead.stop_loss if lead else None,
            "TP": lead.take_profit if lead else None,
            "R:R": lead.risk_reward if lead else None,
            "R:R basis": lead.rr_basis if lead else "",
            "Conflict": c.conflict,
        })
        rows.append(row)
    df = pd.DataFrame(rows)
    order = {"ĐỒNG THUẬN MUA": 0, "NGHIÊNG MUA": 1, "PHÂN HOÁ (thiểu số mua)": 2, "PHÂN HOÁ (có cả mua và thoát)": 3,
             "THEO DÕI": 4, "TRUNG LẬP": 5, "TIÊU CỰC": 6, "KHÔNG CÓ DỮ LIỆU": 7}
    if not df.empty:
        df["_o"] = df["Consensus"].map(order).fillna(9)
        df = df.sort_values(["_o", "Score"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)
    return df


def matrix_df(scan: ScanResult) -> pd.DataFrame:
    rows = []
    for s in scan.symbols:
        row = {"Ticker": s}
        for sid in scan.sids:
            row[sid] = SHORT[scan.results[s][sid].signal]
        row["Conflict"] = scan.consensus[s].conflict
        rows.append(row)
    return pd.DataFrame(rows)
