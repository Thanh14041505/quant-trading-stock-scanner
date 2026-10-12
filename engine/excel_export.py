"""
Xuất kết quả quét ra Excel — mỗi strategy 1 sheet, đủ TOÀN BỘ cột output gốc của strategy đó.

Mục đích (theo yêu cầu của bạn): file này dùng để một AI khác đọc lại, kết hợp tin tức/phân tích cơ bản
để ra khuyến nghị — nên nguyên tắc là KHÔNG LƯỢC BỚT cột, dump đúng những gì mỗi strategy đã tính.

Cột lấy từ đâu:
  * S1–S7 (family != "E"): CHÍNH LÀ `StrategyResult.extra`, tức dict gốc mà notebook trả về (đã qua
    `strategies.mapping.clean()` — chỉ đổi kiểu numpy -> Python thuần, KHÔNG đổi tên/giá trị). Loại 2 khoá
    `_stdout`/`traceback` vì đó là log nội bộ của app, không phải output của notebook.
  * S8 (family "E", không có notebook gốc): dựng một bộ cột tương đương thủ công từ các field của
    StrategyResult + phần điểm con (score_breakdown), vì S8 không có `rec` dict để dump.

Vì mỗi mã có thể trả về bộ khoá hơi khác nhau (mã bị lọc/lỗi/thiếu dữ liệu có ít khoá hơn mã chạy đủ),
cột của sheet = HỢP của mọi khoá xuất hiện ở bất kỳ mã nào, thứ tự ưu tiên theo dòng có nhiều khoá nhất.

Format & conditional formatting: KHÔNG hard-code theo từng cột của từng notebook (sẽ phải tự tay làm cho
hàng trăm cột khác nhau) — dùng một bộ luật CHUNG, tự suy ra từ KIỂU DỮ LIỆU và TỪ KHOÁ trong tên cột:
  * Cột toàn số (không phải bool): thang màu đỏ-vàng-xanh theo chính phân phối giá trị của cột đó.
  * Cột tên chứa "vol"/"thanh khoản"/"giá trị"/"value"/"khối lượng": data bar.
  * Cột bool: TRUE xanh, FALSE đỏ nhạt.
  * Cột chữ: 3 luật theo icon/từ khoá TÍCH CỰC (🟢✅🔥💎📈 MUA/BUY/TĂNG/MẠNH/Bull/Uptrend…), TIÊU CỰC
    (🔴❌⛔📉🚫 BỊ LỌC/BỎ QUA/CẮT LỖ/YẾU/Downtrend/Bear…), TRUNG LẬP/CẢNH BÁO (🟡👀⏳🔄⚠️ THEO DÕI/Trung tính…).
Đây là bộ luật tổng quát, không tinh chỉnh riêng cho từng cột như một vài bản Excel cũ bạn có thể đã thấy
(mỗi cột ở đó có luật riêng theo đúng từ vựng của notebook đó) — nếu muốn tinh ở mức đó cho cột cụ thể nào,
nói tôi chỉnh thêm.
"""
from __future__ import annotations
import io
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.formatting.rule import FormulaRule, ColorScaleRule, DataBarRule, CellIsRule
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from engine.runner import ScanResult
from strategies.registry import REGISTRY

_SKIP_KEYS = {"_stdout", "traceback"}

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
TITLE_FONT = Font(name="Calibri", bold=True, size=14, color="1F4E78")
BAND_FILLS = [PatternFill("solid", fgColor="FFFFFF"), PatternFill("solid", fgColor="F5F9FC")]
THIN = Side(style="thin", color="D9D9D9")
CELL_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CELL_FONT = Font(name="Calibri", size=10)

POS_FILL = PatternFill("solid", fgColor="DCFCE7")   # xanh lá nhạt
NEG_FILL = PatternFill("solid", fgColor="FEE2E2")   # đỏ nhạt
NEU_FILL = PatternFill("solid", fgColor="FEF9C3")   # vàng nhạt
BOOL_TRUE_FILL = PatternFill("solid", fgColor="BBF7D0")
BOOL_FALSE_FILL = PatternFill("solid", fgColor="FECACA")

POS_WORDS = ["🟢", "✅", "🔥", "💎", "📈", "⬆", "MUA MẠNH", "✅ MUA", "MUA T+", "✅ BUY", "TĂNG", "MẠNH",
            "Bull", "Uptrend", "Tích lũy", "GIA TĂNG", "XEM XÉT", "NỔ VOL", "RÚT CHÂN", "Tiền lớn vào", "TIẾP TỤC GIỮ"]
NEG_WORDS = ["🔴", "❌", "⛔", "📉", "🚫", "BỊ LỌC", "BỎ QUA", "CẮT LỖ", "YẾU", "Downtrend", "Bear",
            "PHÂN PHỐI", "CẠN CẦU", "Tiền lớn rút", "GIẢM TỶ TRỌNG", "HẠ TỶ TRỌNG", "EXIT", "REDUCE"]
NEU_WORDS = ["🟡", "👀", "⏳", "🔄", "⚠️", "THEO DÕI", "Trung tính", "Sideway", "Chờ thêm", "WATCH", "CẠN VOL"]


# ───────────────────────────── gom dữ liệu theo strategy ─────────────────────────────
def _flatten_value(v: Any):
    """Đưa giá trị về kiểu Excel ghi được: list/tuple -> nối chuỗi; dict -> bỏ (dùng ở S8 nên không gặp ở đây);
    NaN/Inf -> None (Excel/openpyxl không nhận); numpy scalar -> kiểu Python thuần."""
    if isinstance(v, (list, tuple)):
        return " | ".join(str(x) for x in v)
    if isinstance(v, (np.generic,)):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _rows_for_notebook_strategy(scan: ScanResult, sid: str) -> List[Dict[str, Any]]:
    rows = []
    for sym in scan.symbols:
        r = scan.results[sym][sid]
        rec = {k: v for k, v in (r.extra or {}).items() if k not in _SKIP_KEYS}
        if "Mã" not in rec and "symbol" not in rec:
            rec = {"Mã": sym, **rec}
        if r.status in ("NO_DATA", "ERROR") and len(rec) <= 2:
            rec.setdefault("Trạng thái", r.status)
            rec.setdefault("Ghi chú lỗi", "; ".join(r.warnings) if r.warnings else "")
        rows.append({k: _flatten_value(v) for k, v in rec.items()})
    return rows


def _rows_for_s8(scan: ScanResult) -> List[Dict[str, Any]]:
    rows = []
    for sym in scan.symbols:
        r = scan.results[sym]["S8"]
        bd = (r.extra or {}).get("score_breakdown", {}) or {}
        row = {
            "Mã": sym, "Trạng thái": r.status, "Tín hiệu": r.native_signal, "Tín hiệu chuẩn hoá": r.signal,
            "Score": r.score, "Giá": r.price, "Entry": r.entry, "SL": r.stop_loss, "TP": r.take_profit,
            "R:R": r.risk_reward, "R:R basis": r.rr_basis, "Setup": r.setup,
            "Trend score": bd.get("trend"), "Momentum score": bd.get("momentum"), "Flow score": bd.get("flow"),
            "Structure score": bd.get("structure"), "RS score": bd.get("rs"),
            "RSI14": (r.extra or {}).get("rsi14"), "ATR%": (r.extra or {}).get("atr_pct"),
            "Vol/TB20 (x)": (r.extra or {}).get("vol_ratio_20d"), "Regime x": (r.extra or {}).get("regime_mult"),
            "Lý do": " | ".join(r.reasons) if r.reasons else "", "Cảnh báo": " | ".join(r.warnings) if r.warnings else "",
            "Điều kiện không đạt": " | ".join(r.failed_conditions) if r.failed_conditions else "",
            "Ghi chú": " | ".join(r.legacy_notes) if r.legacy_notes else "",
        }
        rows.append({k: _flatten_value(v) for k, v in row.items()})
    return rows


def _rows_for_s9(scan: ScanResult) -> List[Dict[str, Any]]:
    rows = []
    for sym in scan.symbols:
        r = scan.results[sym]["S9"]
        x = r.extra or {}
        row = {
            "Mã": sym, "Trạng thái": r.status, "Tín hiệu": r.native_signal, "Tín hiệu chuẩn hoá": r.signal,
            "Giá": r.price, "Khung BIAS": x.get("bias_timeframe"),
            "BIAS Trend": x.get("bias_trend"), "BIAS Zone": x.get("bias_zone"), "BIAS Zone %": x.get("bias_zone_pct"),
            "BIAS Range Low": x.get("bias_range_low"), "BIAS Range High": x.get("bias_range_high"),
            "Daily Trend": x.get("daily_trend"), "Weekly Trend": x.get("weekly_trend"), "Monthly Trend": x.get("monthly_trend"),
            "Gần đáy khung lớn": x.get("near_low"), "Dòng tiền vào": x.get("money_flow_in"), "Test đáy thành công": x.get("retest_ok"),
            "CMF20": x.get("cmf20"), "OBV dốc lên 10 phiên": x.get("obv_rising_10d"),
            "Sự kiện BIAS gần nhất": x.get("last_bias_event"), "Mức bị phá (BIAS)": x.get("last_bias_event_level"),
            "Setup (OB/FVG)": r.setup, "Entry": r.entry, "SL": r.stop_loss, "TP": r.take_profit,
            "R:R": r.risk_reward, "R:R basis": r.rr_basis,
            "Khuyến nghị nắm giữ (holder)": r.holder_advice,
            "Số OB chưa test (daily)": x.get("n_order_blocks_unmitigated"), "Số FVG chưa lấp (daily)": x.get("n_fvg_open"),
            "Lý do": " | ".join(r.reasons) if r.reasons else "", "Cảnh báo": " | ".join(r.warnings) if r.warnings else "",
            "Diễn giải cấu trúc": x.get("narrative"),
            "Ghi chú": " | ".join(n for n in r.legacy_notes if n != x.get("narrative")) if r.legacy_notes else "",
        }
        rows.append({k: _flatten_value(v) for k, v in row.items()})
    return rows


def rows_for_strategy(scan: ScanResult, sid: str) -> List[Dict[str, Any]]:
    if sid == "S9":
        return _rows_for_s9(scan)
    if REGISTRY[sid].info.family == "E":
        return _rows_for_s8(scan)
    return _rows_for_notebook_strategy(scan, sid)


def _ordered_columns(rows: List[Dict[str, Any]]) -> List[str]:
    """Hợp các khoá, thứ tự theo dòng có NHIỀU khoá nhất trước (thường là mã chạy đủ, không bị lọc/lỗi),
    rồi phụ thêm khoá lạ (nếu có) xuất hiện ở các dòng khác."""
    if not rows:
        return []
    template = max(rows, key=len)
    cols = list(template.keys())
    seen = set(cols)
    for row in rows:
        for k in row:
            if k not in seen:
                cols.append(k)
                seen.add(k)
    return cols


# ───────────────────────────── ghi 1 sheet + định dạng ─────────────────────────────
def _col_kind(col: str, values: List[Any]) -> str:
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "text"
    if all(isinstance(v, bool) for v in non_null):
        return "bool"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "number"
    return "text"


def _write_sheet(wb: Workbook, title: str, rows: List[Dict[str, Any]], subtitle: str = "") -> None:
    ws = wb.create_sheet(title=title[:31])
    cols = _ordered_columns(rows)
    if not cols:
        ws.append(["(Không có dữ liệu — strategy chưa chạy hoặc chưa chọn mã nào)"])
        return

    # header
    for j, col in enumerate(cols, start=1):
        c = ws.cell(row=1, column=j, value=col)
        c.font, c.fill, c.alignment, c.border = HEADER_FONT, HEADER_FILL, HEADER_ALIGN, CELL_BORDER
    ws.row_dimensions[1].height = 32

    # data + zebra banding (fill tĩnh — các luật CF bên dưới sẽ đè lên khi khớp điều kiện)
    for i, row in enumerate(rows, start=2):
        band = BAND_FILLS[i % 2]
        for j, col in enumerate(cols, start=1):
            v = row.get(col)
            c = ws.cell(row=i, column=j, value=v)
            c.font, c.border = CELL_FONT, CELL_BORDER
            c.fill = band

    n = len(rows) + 1
    kinds = {col: _col_kind(col, [row.get(col) for row in rows]) for col in cols}

    for j, col in enumerate(cols, start=1):
        letter = get_column_letter(j)
        rng = f"{letter}2:{letter}{n}"
        kind = kinds[col]
        low = col.lower()
        if kind == "bool":
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=["TRUE"], fill=BOOL_TRUE_FILL))
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=["FALSE"], fill=BOOL_FALSE_FILL))
            for i in range(2, n + 1):
                ws.cell(row=i, column=j).alignment = Alignment(horizontal="center")
        elif kind == "number":
            is_vol = any(k in low for k in ("vol", "thanh khoản", "khối lượng", "giá trị", "value"))
            if is_vol:
                ws.conditional_formatting.add(rng, DataBarRule(start_type="min", end_type="max", color="63B3ED"))
            else:
                ws.conditional_formatting.add(rng, ColorScaleRule(
                    start_type="min", start_color="F8696B", mid_type="percentile", mid_value=50, mid_color="FFEB84",
                    end_type="max", end_color="63BE7B"))
            fmt = "0.000" if ("r:r" in low or low.endswith("_rr") or "risk_reward" in low) else \
                  "0" if all(isinstance(row.get(col), int) or row.get(col) is None for row in rows) else "0.00"
            for i in range(2, n + 1):
                cell = ws.cell(row=i, column=j)
                if cell.value is not None:
                    cell.number_format = fmt
                cell.alignment = Alignment(horizontal="right")
        else:
            pos = ",".join(f'ISNUMBER(SEARCH("{w}",${letter}2))' for w in POS_WORDS)
            neg = ",".join(f'ISNUMBER(SEARCH("{w}",${letter}2))' for w in NEG_WORDS)
            neu = ",".join(f'ISNUMBER(SEARCH("{w}",${letter}2))' for w in NEU_WORDS)
            ws.conditional_formatting.add(rng, FormulaRule(formula=[f"OR({neu})"], fill=NEU_FILL))
            ws.conditional_formatting.add(rng, FormulaRule(formula=[f"OR({neg})"], fill=NEG_FILL))
            ws.conditional_formatting.add(rng, FormulaRule(formula=[f"OR({pos})"], fill=POS_FILL))

        header_len = len(str(col))
        try:
            sample_len = max((len(str(row.get(col, ""))) for row in rows[:200]), default=0)
        except Exception:
            sample_len = 10
        ws.column_dimensions[letter].width = max(8, min(42, max(header_len, sample_len) + 2))

    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{n}"
    if subtitle:
        ws.sheet_properties.tabColor = "1F4E78"


def _write_overview(wb: Workbook, scan: ScanResult, sids: List[str]) -> None:
    ws = wb.create_sheet(title="ℹ️ Tổng quan")
    ws["A1"] = "Unified 7-Strategy Stock Scanner — Xuất dữ liệu chi tiết"
    ws["A1"].font = TITLE_FONT
    meta = [
        ("Ngày xuất", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ("Dữ liệu tới phiên (as-of)", str(scan.as_of)),
        ("Mode", "Swing T+" if scan.mode == "swing" else "Hold"),
        ("Số mã", len(scan.symbols)),
        ("Số strategy", len(sids)),
    ]
    r = 3
    for k, v in meta:
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v)
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="Sheet").font = HEADER_FONT
    ws.cell(row=r, column=1).fill = HEADER_FILL
    ws.cell(row=r, column=2, value="Strategy").font = HEADER_FONT
    ws.cell(row=r, column=2).fill = HEADER_FILL
    ws.cell(row=r, column=3, value="Nguồn / Ghi chú").font = HEADER_FONT
    ws.cell(row=r, column=3).fill = HEADER_FILL
    r += 1
    for sid in sids:
        info = REGISTRY[sid].info
        ws.cell(row=r, column=1, value=sid)
        ws.cell(row=r, column=2, value=info.name)
        note = info.notebook if info.family != "E" else "Không thuộc notebook nào — xem cột 'Ghi chú' trong sheet S8"
        ws.cell(row=r, column=3, value=f"{note} — {info.note}")
        r += 1
    r += 2
    for line in [
        "Mỗi sheet = 1 strategy, mỗi dòng = 1 mã, mỗi cột = 1 khoá trong output GỐC của strategy đó.",
        "S1–S7: cột lấy nguyên văn từ dict output của notebook (bao gồm cả các khoá nội bộ bắt đầu bằng '_').",
        "S8: không có notebook gốc — cột được dựng thủ công từ kết quả tính của trợ lý AI (xem sheet S8).",
        "S7 không có Entry/SL/TP/R:R tuyệt đối — chỉ có % gợi ý (suggested_sl_pct/suggested_tp_pct).",
        "Conditional formatting dùng luật CHUNG theo từ khoá/icon (xem đầu file engine/excel_export.py), "
        "không tinh chỉnh riêng cho từng cột của từng notebook.",
    ]:
        ws.cell(row=r, column=1, value="• " + line)
        r += 1
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 70


def build_workbook(scan: ScanResult) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    sids = [s for s in REGISTRY if s in scan.sids]   # giữ thứ tự S1..S8 cố định bất kể thứ tự chọn trên UI
    _write_overview(wb, scan, sids)
    for sid in sids:
        rows = rows_for_strategy(scan, sid)
        _write_sheet(wb, sid, rows, subtitle=REGISTRY[sid].info.name)
    return wb


def export_bytes(scan: ScanResult) -> bytes:
    wb = build_workbook(scan)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
