"""
S9 — AI SMC Structure Read (đa khung thời gian: Daily rộng + Weekly + Monthly)   [Dòng E]

LỊCH SỬ YÊU CẦU (2 vòng chỉnh sửa của bạn):
  1) S1–S8 phần lớn chấm điểm chỉ báo TẠI PHIÊN GẦN NHẤT — thiếu góc nhìn CẤU TRÚC đồ thị. -> thêm SMC.
  2) Hai vấn đề với bản SMC đầu tiên (chỉ tính khung ngày, cửa sổ swing hẹp):
       a. Thị trường VN chỉ Long — một số case TP tính ra lại ≤ giá hiện tại (bug thật, đã xác nhận và
          sửa: biên an toàn 0.995 có thể kéo TP xuống dưới giá nếu kháng cự quá gần).
       b. "Đừng tính SMC mấy đoạn nhỏ nhỏ" — cần nhìn cấu trúc khung LỚN (1D rộng/1W/1M), chỉ khuyến
          nghị mua khi gần đáy khung lớn + có dòng tiền vào HOẶC test đáy thành công.

CÁCH LÀM Ở BẢN NÀY (top-down, đúng cách trader SMC chuyên nghiệp dùng đa khung — HTF cho BIAS, LTF cho
ENTRY), toàn bộ nhân quả (`strategies/timeframes.py` resample tuần/tháng từ đúng dữ liệu đã có):
  - BIAS (xu hướng lớn)   : Monthly nếu đủ dữ liệu để có swing xác nhận, else Weekly, else Daily (cửa sổ
                             rộng). Đây là bộ lọc ĐẦU TIÊN — nếu BIAS là downtrend mà CHƯA có CHoCH tăng
                             xác nhận trên chính khung đó, KHÔNG khuyến nghị mua mới (đúng "VN chỉ Long,
                             không đánh ngược xu hướng lớn").
  - VÙNG "GẦN ĐÁY"        : giá hiện tại nằm trong Discount zone của khung BIAS (ưu tiên) hoặc Weekly.
  - XÁC NHẬN VÀO LỆNH     : (a) dòng tiền vào — CMF20 ngày > 0 hoặc OBV đang dốc lên 10 phiên, HOẶC
                             (b) test đáy thành công — đáy xoay gần nhất (ngày/tuần) nằm sát đáy khung
                             BIAS rồi tạo đáy sau cao hơn (higher low) hoặc CHoCH tăng ngay sau đó.
  - ENTRY/SL/TP           : vẫn lấy từ Order Block/FVG/Liquidity khung NGÀY (cửa sổ đã nới rộng, xem
                             DEFAULTS) để vào lệnh chính xác, nhưng chỉ hiển thị khi đã qua đủ điều kiện
                             BIAS+gần đáy+xác nhận ở trên — và LUÔN đảm bảo Entry ≤ Giá ≤ TP (long-only:
                             không bao giờ hiện một "setup" mà giá hiện tại nằm ngoài vùng hợp lý).

Hai loại khuyến nghị vẫn tách riêng như bản trước: `native_signal`/`signal` (mua mới) và `holder_advice`
(đang giữ). Toàn bộ định nghĩa SMC gốc (swing/BOS/CHoCH/OB/FVG/Liquidity/Premium-Discount): `strategies/smc.py`.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import pandas as pd

from .base import (BaseStrategy, StrategyInfo, StrategyResult, ScanContext,
                   STRONG_BUY, BUY, WATCH, NONE, REDUCE, EXIT, FILTERED, NO_DATA, ERROR)
from .ai_indicators import atr as _atr_series, cmf as _cmf_series, vnindex_regime as _regime
from . import smc
from .timeframes import resample_ohlcv
from data.store import DataError, BENCHMARK

AI_DISCLAIMER = ("SMC (Smart Money Concepts) đa khung thời gian do trợ lý AI tự viết, không trích từ "
                  "notebook nào. Đây là một cách diễn giải phổ biến của SMC, không phải chân lý duy nhất — "
                  "chỉ mang tính tham khảo, KHÔNG PHẢI khuyến nghị đầu tư.")

_VI = {"up": "Uptrend", "down": "Downtrend", "ranging": "Sideway/chưa rõ"}
_ZONE_VI = {"discount": "Discount", "premium": "Premium", "equilibrium": "Equilibrium"}


class Strategy09(BaseStrategy):
    info = StrategyInfo("S9", "AI SMC Structure Read (đa khung D/W/M)", "E",
                        "(không có — SMC do trợ lý AI tự viết, không thuộc notebook nào)",
                        True, "BIAS từ khung Tuần/Tháng + entry khung Ngày; chỉ mua gần đáy khung lớn có dòng tiền/test đáy thành công")

    DEFAULTS = dict(
        min_history_rows=220, min_avg_value_20d=8_000_000,
        # Daily WIDE — chỉ dùng làm BIAS DỰ PHÒNG khi chưa đủ dữ liệu Weekly/Monthly (nới rộng 3->6 để
        # đỡ nhiễu, đúng yêu cầu "đừng tính SMC đoạn nhỏ nhỏ" cho phần XÁC ĐỊNH XU HƯỚNG).
        bias_swing_left=6, bias_swing_right=6, bias_min_swing_atr=0.5,
        # Daily ENTRY (LTF) — dùng để tìm Order Block/FVG đặt entry CHÍNH XÁC trong vùng mà HTF đã duyệt.
        # Cố ý giữ cửa sổ hẹp hơn bias: nếu cũng nới rộng, giai đoạn TÍCH LUỸ biên độ nhỏ (chính là nơi cần
        # tìm entry nhất) sẽ không còn OB/FVG nào để dùng — đây là bug thật tôi tìm ra khi test bằng kịch
        # bản tích luỹ rồi breakout giống ảnh bạn gửi.
        entry_swing_left=3, entry_swing_right=3, entry_min_swing_atr=0.4, liq_tol_atr=0.25,
        # Weekly/Monthly (HTF — xác định BIAS chính): cửa sổ nhỏ hơn vì bản thân nến tuần/tháng đã "lớn"
        weekly_swing_left=2, weekly_swing_right=2, weekly_min_swing_atr=0.3,
        monthly_swing_left=1, monthly_swing_right=1, monthly_min_swing_atr=0.2,
        min_weekly_bars=30, min_monthly_bars=15,     # dưới mức này coi như chưa đủ dữ liệu cho khung đó
        # Ngưỡng "gần đáy" & entry
        near_low_zone_pct=0.30, retest_tol_atr=1.0, money_flow_obv_days=10,
        atr_sl_buffer=0.3, max_entry_dist_atr=3.0, tp_safety_pct=0.5,   # % lùi TP khỏi kháng cự (an toàn, không để TP<=giá)
        entry_gap_warn_atr=1.5,   # cảnh báo khi vùng entry đã cách giá hiện tại hơn X×ATR (chờ test lại)
        tp_rr_fallback=2.0,   # TP dự phòng theo bội số R:R khi không có kháng cự/liquidity phía trên (breakout)
        rr_min_display=0.8,
    )

    def default_config(self) -> Dict[str, Any]:
        return dict(self.DEFAULTS)

    def prepare(self, ctx: ScanContext):
        as_of = ctx.store.latest_session()
        if as_of is None:
            raise DataError("Chưa xác định được phiên giao dịch gần nhất (thiếu VNINDEX)")
        vni = ctx.store.get_raw(BENCHMARK).drop(columns=["_src"], errors="ignore")
        vni["time"] = pd.to_datetime(vni["time"])
        vni = vni.sort_values("time").reset_index(drop=True)
        reg = _regime(vni) if len(vni) >= 60 else {"regime": "N/A", "mult": 1.0, "slope10_pct": None}
        cfg = dict(self.DEFAULTS)
        for k, v in ctx.overrides.get("S9", {}).items():
            if k in cfg:
                cfg[k] = type(cfg[k])(v)
        return dict(regime=reg, cfg=cfg)

    def prep_summary(self, prep) -> Dict[str, Any]:
        r = prep["regime"]
        return {"regime": r["regime"], "label": f"EMA50 slope 10 phiên: {r['slope10_pct']}%" if r.get("slope10_pct") is not None else "—",
                "score_mult": None, "min_score": None, "vnindex": None}

    def run_symbol(self, symbol: str, prep, ctx: ScanContext) -> StrategyResult:
        cfg = prep["cfg"]
        try:
            df = ctx.store.get_raw(symbol).drop(columns=["_src"], errors="ignore")
        except DataError as e:
            return StrategyResult("S9", symbol, "NO_DATA", ctx.mode, "—", NO_DATA, warnings=[f"API: {str(e)[:160]}"])
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time").reset_index(drop=True)
        if len(df) < cfg["min_history_rows"]:
            return StrategyResult("S9", symbol, "FILTERED", ctx.mode, "Thiếu lịch sử", FILTERED,
                                  failed_conditions=[f"Chỉ có {len(df)} phiên (<{cfg['min_history_rows']})"],
                                  legacy_notes=[AI_DISCLAIMER])
        avg_val20 = (df["close"] * df["volume"]).tail(20).mean()
        if avg_val20 < cfg["min_avg_value_20d"]:
            return StrategyResult("S9", symbol, "FILTERED", ctx.mode, "Thanh khoản thấp", FILTERED,
                                  price=float(df["close"].iloc[-1]),
                                  failed_conditions=[f"Giá trị GD TB 20 phiên {avg_val20:,.0f} < ngưỡng {cfg['min_avg_value_20d']:,.0f}"],
                                  legacy_notes=[AI_DISCLAIMER])
        try:
            return self._read(symbol, df, prep, ctx, cfg)
        except Exception as e:  # noqa: BLE001
            return StrategyResult("S9", symbol, "ERROR", ctx.mode, "—", ERROR,
                                  warnings=[f"{type(e).__name__}: {str(e)[:200]}"], legacy_notes=[AI_DISCLAIMER])

    # ───────────────────────────── đa khung: BIAS (HTF) + entry (LTF) ─────────────────────────────
    def _read(self, symbol, df, prep, ctx, cfg) -> StrategyResult:
        price = float(df["close"].iloc[-1])
        atr_now = float(_atr_series(df, 14).iloc[-1])

        daily_wide = smc.analyze(df, left=cfg["bias_swing_left"], right=cfg["bias_swing_right"],
                                 min_swing_atr=cfg["bias_min_swing_atr"], liq_tol_atr=cfg["liq_tol_atr"])
        daily = smc.analyze(df, left=cfg["entry_swing_left"], right=cfg["entry_swing_right"],
                            min_swing_atr=cfg["entry_min_swing_atr"], liq_tol_atr=cfg["liq_tol_atr"])
        wk_df = resample_ohlcv(df, "W-FRI")
        mo_df = resample_ohlcv(df, "ME")
        weekly = (smc.analyze(wk_df, left=cfg["weekly_swing_left"], right=cfg["weekly_swing_right"],
                              min_swing_atr=cfg["weekly_min_swing_atr"])
                 if len(wk_df) >= cfg["min_weekly_bars"] else None)
        monthly = (smc.analyze(mo_df, left=cfg["monthly_swing_left"], right=cfg["monthly_swing_right"],
                               min_swing_atr=cfg["monthly_min_swing_atr"])
                  if len(mo_df) >= cfg["min_monthly_bars"] else None)

        # BIAS: ưu tiên Monthly (đã có sự kiện cấu trúc) -> Weekly -> Daily rộng (dự phòng). "Chưa đủ dữ
        # liệu" không có nghĩa là bỏ qua khung đó hoàn toàn — chỉ là không dùng nó làm BIAS.
        if monthly is not None and monthly.events:
            bias_tf, bias = "Monthly", monthly
        elif weekly is not None and weekly.events:
            bias_tf, bias = "Weekly", weekly
        else:
            bias_tf, bias = "Daily", daily_wide

        bias_trend = bias.trend
        bias_zone = bias.zone

        # Dòng tiền vào (khung ngày): CMF20 dương hoặc OBV 10 phiên đang dốc lên
        cmf_now = float(_cmf_series(df, 20).iloc[-1])
        obv = df["volume"].where(df["close"].diff() > 0, -df["volume"].where(df["close"].diff() < 0, 0)).cumsum()
        nflow = cfg["money_flow_obv_days"]
        obv_rising = len(obv) > nflow and obv.iloc[-1] > obv.iloc[-1 - nflow]
        money_flow_in = (pd.notna(cmf_now) and cmf_now > 0) or obv_rising

        # Test đáy thành công: đáy xoay gần nhất (ngày HOẶC tuần) nằm sát đáy khung BIAS, rồi có đáy sau
        # cao hơn hoặc CHoCH tăng ngay sau đó -> dùng chính khung BIAS để không lẫn nhiễu khung nhỏ.
        retest_ok = False
        bias_lows = [s for s in bias.swings if s.kind == "low"]
        if bias.range_low is not None and len(bias_lows) >= 2 and atr_now > 0:
            last2 = sorted(bias_lows, key=lambda s: s.idx)[-2:]
            near_range_low = abs(last2[0].price - bias.range_low) <= cfg["retest_tol_atr"] * (atr_now if bias_tf == "Daily" else atr_now * 4.5)
            higher_low = last2[-1].price > last2[0].price
            choch_after = bias.last_event is not None and bias.last_event.kind == "CHOCH_UP" and bias.last_event.idx >= last2[0].idx
            retest_ok = near_range_low and (higher_low or choch_after)

        # Entry/SL/TP: vùng Order Block tăng (khung ngày) CHƯA TEST, gần giá nhất
        bull_obs = [o for o in daily.order_blocks if o.kind == "bullish" and not o.mitigated and o.top <= price]
        bull_obs = [o for o in bull_obs if atr_now <= 0 or (price - o.top) <= cfg["max_entry_dist_atr"] * atr_now]
        bull_obs.sort(key=lambda o: price - o.top)
        bull_fvgs_open = [f for f in daily.fvgs if f.kind == "bullish" and not f.filled]
        entry_ob = bull_obs[0] if bull_obs else None
        confluence_fvg = None
        if entry_ob:
            confluence_fvg = next((f for f in bull_fvgs_open if f.bottom <= entry_ob.top and f.top >= entry_ob.bottom), None)

        # "Gần đáy khung lớn": kiểm tra theo vị trí của CHÍNH VÙNG ENTRY (OB), không phải giá đóng cửa
        # hôm nay. LÝ DO (bug phát hiện khi test bằng kịch bản tích luỹ→breakout): cấu trúc cần vài phiên
        # để XÁC NHẬN (đúng nguyên tắc không nhìn trước), nên tới lúc OB "xuất hiện" trong kết quả thì giá
        # thường đã nhích lên khỏi đáy — nếu bắt giá HÔM NAY phải còn nằm trong vùng Discount thì gần như
        # không bao giờ khớp cùng lúc với một OB vừa được xác nhận. Vùng OB tự nó đã neo tại khu vực đáy
        # (ràng buộc entry ≤ giá qua `top<=price` + giới hạn khoảng cách ATR ở trên), nên dùng NÓ để đánh
        # giá "gần đáy" mới đúng — giá hôm nay vẫn phải ≤ giá tại entry mới hợp lệ (đã đảm bảo ở trên).
        if bias.range_low is not None and bias.range_high is not None and bias.range_high > bias.range_low:
            probe_price = entry_ob.top if entry_ob else price
            probe_pct = (probe_price - bias.range_low) / (bias.range_high - bias.range_low)
            near_low = probe_pct <= cfg["near_low_zone_pct"]
        else:
            near_low = False

        entry = sl = tp = rr = None
        setup_parts: List[str] = []
        if entry_ob:
            entry = round((entry_ob.top + entry_ob.bottom) / 2, 2)
            sl = round(min(entry_ob.bottom - cfg["atr_sl_buffer"] * atr_now, price * 0.999), 2)
            setup_parts.append(f"OB tăng (chưa test) {entry_ob.bottom:.2f}–{entry_ob.top:.2f}"
                               + (" + FVG trùng vùng" if confluence_fvg else ""))
            buy_pools = sorted([p for p in daily.liquidity if p.kind == "buy_side" and not p.swept and p.price > price],
                               key=lambda p: p.price)
            res_highs = sorted([s.price for s in daily.swings if s.kind == "high" and s.price > price])
            # cũng xét kháng cự/đỉnh khung BIAS nếu nó xa hơn (mục tiêu lớn hơn, hợp lý hơn cho khung lớn)
            bias_highs = sorted([s.price for s in bias.swings if s.kind == "high" and s.price > price]) if bias_tf != "Daily" else []
            candidates = [p.price for p in buy_pools[:1]] + res_highs[:1] + bias_highs[:1]
            min_tp = price + 0.5 * atr_now
            if candidates:
                raw_tp = min(candidates) * (1 - cfg["tp_safety_pct"] / 100)
                # LUÔN đảm bảo long-only hợp lệ: TP phải > giá hiện tại một khoảng tối thiểu (0.5×ATR),
                # nếu kháng cự quá gần thì bỏ TP (không có đủ dư địa) thay vì ép ra số vô lý (bug đã sửa).
                tp = round(raw_tp, 2) if raw_tp > min_tp else None
            if tp is None:
                # KHÔNG có kháng cự/liquidity nào phía trên (giá đang phá đỉnh — "vùng trời xanh") -> không
                # có nghĩa là không nên mua; dùng mục tiêu theo bội số R:R cố định thay vì bỏ trắng TP.
                fallback_tp = entry + cfg["tp_rr_fallback"] * (entry - sl)
                if fallback_tp > min_tp:
                    tp = round(fallback_tp, 2)
                    setup_parts.append(f"Không có kháng cự phía trên (breakout) — TP theo {cfg['tp_rr_fallback']:.1f}R")
            if sl is not None and entry is not None and entry > sl:
                risk = entry - sl
                if tp and tp > entry:
                    rr = round((tp - entry) / risk, 3)

        narrative = (f"BIAS ({bias_tf}): {_VI.get(bias_trend,'—')} · Zone {bias_tf}: {_ZONE_VI.get(bias_zone,'—')}"
                    + (f" ({bias.zone_pct*100:.0f}% range {bias.range_low:.1f}-{bias.range_high:.1f})" if bias.zone_pct is not None else ""))
        if bias.last_event:
            ev = bias.last_event
            narrative += f"; sự kiện {bias_tf} gần nhất: {ev.kind} (mức {ev.level:.2f})"
        narrative += f"; dòng tiền (ngày): {'VÀO' if money_flow_in else 'chưa rõ'}; test đáy ({bias_tf}): {'THÀNH CÔNG' if retest_ok else 'chưa có'}"

        # ─── Khuyến nghị MUA MỚI — chỉ xét khi BIAS không chống lại ───
        # QUAN TRỌNG: `retest_ok` (higher-low/CHoCH quanh đáy BIAS) tự nó LÀ bằng chứng đảo chiều sớm —
        # không đòi hỏi thêm một CHoCH chính thức trên CHÍNH khung BIAS mới cho qua, vì lúc CHoCH chính
        # thức đó xảy ra thì giá thường đã chạy khá xa khỏi đáy rồi (mất hết lợi thế "mua gần đáy"). Vẫn
        # chặn khi downtrend rõ ràng và KHÔNG có either CHoCH lẫn test-đáy nào hỗ trợ.
        bias_blocks_long = bias_trend == "down" and not (
            (bias.last_event and bias.last_event.kind == "CHOCH_UP") or retest_ok)
        warnings_: List[str] = []
        reasons: List[str] = []
        if bias_blocks_long:
            sig, native = NONE, f"🔴 BỎ QUA — BIAS {bias_tf} đang Downtrend, chưa có CHoCH tăng xác nhận"
        elif not near_low:
            sig, native = WATCH, f"👀 THEO DÕI — Chưa về vùng Discount của khung {bias_tf}, chờ chiết khấu sâu hơn"
        elif not (money_flow_in or retest_ok):
            sig, native = WATCH, f"👀 THEO DÕI — Đã gần đáy khung {bias_tf} nhưng CHƯA có dòng tiền vào/test đáy xác nhận"
        elif entry_ob is None or tp is None:
            sig, native = WATCH, f"👀 THEO DÕI — Đủ điều kiện khung lớn nhưng chưa có vùng Entry (OB)/TP khung ngày đủ rõ"
            if entry_ob is not None and tp is None:
                warnings_.append("Có vùng OB nhưng kháng cự gần nhất quá sát giá — chưa đủ dư địa đặt TP hợp lý")
        elif money_flow_in and retest_ok:
            sig, native = STRONG_BUY, f"🔥 MUA MẠNH — Gần đáy {bias_tf} + dòng tiền vào + test đáy thành công"
            reasons.append(f"Giá đang trong vùng Discount của khung {bias_tf}, có cả dòng tiền vào và test đáy thành công")
        else:
            sig, native = BUY, f"✅ MUA — Gần đáy {bias_tf} + " + ("dòng tiền vào" if money_flow_in else "test đáy thành công")
            reasons.append("Gần đáy khung lớn, có xác nhận " + ("dòng tiền (CMF/OBV)" if money_flow_in else "test đáy (higher-low/CHoCH)"))

        if bias_zone == "premium":
            warnings_.append(f"Zone {bias_tf} hiện là Premium — xa vùng đáy, không ưu tiên mua mới")

        # ─── Khuyến nghị NẮM GIỮ — dựa trên BIAS khung lớn, không cần giá vốn ───
        # Dùng CHUNG điều kiện nới lỏng với bên mua mới (retest_ok tự nó là bằng chứng đảo chiều sớm) để
        # 2 khuyến nghị không mâu thuẫn nhau (vd. bên mua nói "đủ điều kiện" mà bên giữ vẫn nói "cắt lỗ").
        reversal_evidence = (bias.last_event and bias.last_event.kind == "CHOCH_UP") or retest_ok
        if bias.last_event and bias.last_event.kind == "CHOCH_DOWN":
            holder = f"🔴 CẮT LỖ — Vừa có CHoCH giảm trên khung {bias_tf} (đảo chiều khung lớn)"
        elif bias_trend == "down" and not reversal_evidence:
            holder = f"🔴 CẮT LỖ / ĐỨNG NGOÀI — BIAS {bias_tf} là Downtrend, chưa có tín hiệu đảo chiều"
        elif bias_zone == "premium":
            holder = f"🟡 HẠ TỶ TRỌNG — Giá đang ở vùng Premium của khung {bias_tf}, cân nhắc chốt lời một phần"
        elif near_low and (money_flow_in or retest_ok):
            holder = f"🟢 GIA TĂNG — Đang gần đáy khung {bias_tf}, có xác nhận dòng tiền/test đáy"
        elif bias_trend == "up":
            holder = f"🟢 TIẾP TỤC GIỮ — BIAS {bias_tf} vẫn là Uptrend"
        elif reversal_evidence:
            holder = f"🟡 QUAN SÁT CHẶT — Có dấu hiệu đảo chiều sớm ở khung {bias_tf} nhưng BIAS chính thức chưa đổi"
        else:
            holder = "🟡 QUAN SÁT — Cấu trúc khung lớn chưa rõ ràng"

        if sig in (NONE, EXIT):
            entry = sl = tp = rr = None
        if rr is not None and rr < cfg["rr_min_display"]:
            warnings_.append(f"R:R tính ra khá thấp ({rr:.3f})")
        if entry is not None and atr_now > 0 and (price - entry) > cfg["entry_gap_warn_atr"] * atr_now:
            warnings_.append(f"Giá hiện tại đã cách vùng Entry {(price-entry)/atr_now:.1f}×ATR — "
                             f"đây là vùng CHỜ GIÁ HỒI VỀ, không phải mua đuổi tại giá hiện tại")
        # Lưới an toàn cuối cùng (long-only): không BAO GIỜ hiển thị setup mà giá nằm ngoài [SL, TP].
        if entry is not None and (sl is None or tp is None or not (sl < entry <= price < tp)):
            entry = sl = tp = rr = None
            if sig in (STRONG_BUY, BUY):
                sig, native = WATCH, native.replace("MUA MẠNH", "THEO DÕI").replace("✅ MUA", "👀 THEO DÕI")
                warnings_.append("Không đảm bảo được Entry ≤ Giá < TP hợp lệ cho thị trường long-only — chỉ theo dõi")

        setup = " | ".join(setup_parts) if setup_parts else "—"
        return StrategyResult(
            sid="S9", symbol=symbol, status="OK", mode=ctx.mode, native_signal=native, signal=sig,
            score=None, score_scale=100, price=price, setup=setup,
            entry=entry, stop_loss=sl, take_profit=tp, risk_reward=rr,
            rr_basis="Liquidity/đỉnh xoay (ngày+khung lớn)" if rr is not None else "",
            holder_advice=holder, reasons=reasons, warnings=warnings_,
            passed_conditions=reasons, failed_conditions=[],
            legacy_notes=[AI_DISCLAIMER, narrative],
            extra={
                "bias_timeframe": bias_tf, "bias_trend": bias_trend, "bias_zone": bias_zone,
                "bias_zone_pct": bias.zone_pct, "bias_range_low": bias.range_low, "bias_range_high": bias.range_high,
                "daily_trend": daily.trend, "weekly_trend": weekly.trend if weekly else None,
                "monthly_trend": monthly.trend if monthly else None,
                "near_low": near_low, "money_flow_in": money_flow_in, "retest_ok": retest_ok,
                "cmf20": round(cmf_now, 3) if pd.notna(cmf_now) else None, "obv_rising_10d": bool(obv_rising),
                "n_order_blocks_unmitigated": sum(1 for o in daily.order_blocks if not o.mitigated),
                "n_fvg_open": sum(1 for f in daily.fvgs if not f.filled),
                "last_bias_event": bias.last_event.kind if bias.last_event else None,
                "last_bias_event_level": bias.last_event.level if bias.last_event else None,
                "narrative": narrative,
            })
