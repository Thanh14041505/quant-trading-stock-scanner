# -*- coding: utf-8 -*-
# ╔════════════════════════════════════════════════════════════════════════╗
# ║  FILE SINH TỰ ĐỘNG — KHÔNG SỬA TAY (tools/extract_legacy.py)            ║
# ╚════════════════════════════════════════════════════════════════════════╝
# Source Notebook : Tool_CK_Claude_ChatGPT_v3_ProductionDailyScanner.ipynb
# Section         : PHASE 13 — DAILY LIVE / EOD STOCK SCANNER (Production)
# Trích theo tên  : hàm/hằng số production của Phase 13.0–13.6 + hotfix normalize_ohlcv.
# Không trích     : MarketDataStore/Drive cache (thay bằng data/store.py), Phase 2–12 (Research),
#                   print_daily_report/save_daily_report, scan_watchlist (runner của app thay thế).
# Điểm cần biết   : `_call_data_layer` KHÔNG có ở đây — adapter strategy_07.py gắn vào lúc chạy
#                   (scan_one_symbol tra cứu tên này trong global của module).
import ast  # noqa: F401
import numpy as np
import pandas as pd


# ═════ [cell 115] MY_STOCKS ═════
MY_STOCKS = ['FPT', 'VCB', 'HPG', 'TCB', 'ACB', 'BID', 'MWG', 'SSI', 'VND', 'CTD', 'VHM', 'VIC', 'VRE', 'PNJ', 'MSN',
                   'GAS', 'PLX', 'SAB', 'STB', 'SHB', 'LPB', 'VPB', 'MBB', 'HDB', 'TPB', 'OCB', 'SSB', 'VIB', 'CTG', 'POW',
                   'GVR', 'DGC', 'DPM', 'BSR', 'PVD', 'PVT', 'VCG', 'VSC', 'HSG', 'NKG', 'BCM', 'KDH', 'DXG', 'NLG', 'TCH',
                   'DIG', 'PDR', 'KBC', 'CRE', 'VPI', 'HDG', 'AGG', 'HT1', 'AAA', 'DBC', 'NVL', 'VHC', 'MSH', 'CII', 'VGI',
                   'ANV', 'SMC', 'HAG', 'DLG', 'BFC', 'PTB', 'TLH', 'PHR', 'DCM', 'LAS', 'VIX', 'MSR', 'GEL', 'HUT', 'GEG',
                   'GEX', 'FTS', 'HCM', 'CTS', 'MBS', 'VCI', 'ORS', 'BSI', 'BAF', 'BMP', 'BVH', 'BWE', 'CMG', 'CTR', 'DGW',
                   'DSE', 'DXS', 'EIB', 'EVF', 'FRT', 'GEE', 'GMD', 'HDC', 'HHV', 'IMP', 'KDC', 'KOS', 'MSB', 'NAB', 'NT2',
                   'PAN', 'PC1', 'REE', 'SBT', 'SCS', 'SIP', 'SJS', 'SZC', 'VGC', 'VJC', 'VNM', 'VPL', 'CEO', 'SHS', 'PVS',
                   'MST', 'VC3', 'IDC', 'VTZ', 'VFS', 'PVC', 'C69', 'TNG', 'VGS', 'KSF', 'PVB', 'BVS', 'CTP', 'FID', 'VTV',
                   'PLC', 'OCH', 'PVI', 'NTP', 'IPA', 'DXP', 'VIW', 'TVN', 'OIL', 'ACV', 'HNG', 'BVB', 'FOX', 'DRI', 'DDV',
                   'AAS', 'VEA', 'TV1', 'ABB', 'VGT', 'QTP', 'MZG', 'PHP', 'SBS', 'STH', 'F88', 'HNM', 'FOC', 'DSH', 'BMS',
                   'QNS', 'TOS', 'XMC', 'BNA', 'VC7', 'VC2', 'DTD', 'UNI', 'NBC', 'NAG', 'CAP', 'PSI', 'VGP', 'PPT', 'PCH',
                   'NVB', 'L40', 'APS', 'VHE', 'API', 'PVG', 'IDJ', 'LDP', 'CMS', 'DST', 'AAV', 'AMS', 'BIG', 'VTD', 'G36',
                   'DSH', 'DDB', 'CLI', 'PIV', 'CLX', 'TTG', 'DVN', 'PXL', 'MPC', 'ABW', 'PGB', 'VBB', 'NCG', 'ALC', 'KCB',
                   'GCF', 'KLB', 'VAB', 'C32', 'CIG', 'HSL', 'RYG', 'VTO', 'HII', 'TCM', 'PPC', 'ELC', 'TCI', 'SHI', 'DAH',
                   'LDG', 'HQC', 'HHP', 'SCR', 'LCG', 'QCG', 'TTH', 'NRC', 'TVC', 'TIG', 'SVN', 'DL1', 'KIP', 'CTX', 'APF',
                   'SBB', 'VNP', 'HVN', 'TLG']


# ═════ [cell 115] BENCHMARK_SYMBOL ═════
BENCHMARK_SYMBOL = "VNINDEX"


# ═════ [cell 115] LOOKBACK_DAYS ═════
LOOKBACK_DAYS = 420


# ═════ [cell 115] SCAN_CFG ═════
SCAN_CFG = {
    # Liquidity
    "min_history_rows": 250,
    "min_price": 5_000.0,
    "min_avg_value_20d": 500_000_000.0,

    # Signal
    "buy_score": 70.0,
    "strong_buy_score": 85.0,
    "watch_score": 58.0,

    # Probability
    "min_p_tp": 0.55,
    "strong_p_tp": 0.65,

    # Exit
    "exit_risk_threshold": 65.0,
    "reduce_risk_threshold": 45.0,

    # Relative strength
    "rs_lookback": 60,

    # Ranking
    "top_n_buy": 10,
    "top_n_watch": 15,
    "top_n_exit": 15,

    # Safety
    "require_market_confirmation": True,
    "allow_new_long_in_bear": False,
}


# ═════ [cell 115] VERBOSE_SCAN ═════
VERBOSE_SCAN = False


# ═════ [cell 116] _production_clean ═════
def _production_clean(self, df):
    """
    Normalize provider output to the scanner's canonical VND OHLCV schema.

    No forward/backward fill is performed.
    """
    x = df.copy()

    source = str(
        x.attrs.get("vnstock_source", "")
    ).upper()

    x.columns = [
        str(c).lower().strip()
        for c in x.columns
    ]

    x = x.rename(columns={
        "tradingdate": "time",
        "date": "time",
        "datetime": "time",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
    })

    required = {
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }

    if not required.issubset(x.columns):
        return None

    x["time"] = pd.to_datetime(
        x["time"],
        errors="coerce"
    ).dt.normalize()

    for col in [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]:
        x[col] = pd.to_numeric(
            x[col],
            errors="coerce"
        )

    # KBS's historical Quote values are expressed in thousands of VND.
    if source == "KBS":
        for col in ["open", "high", "low", "close"]:
            x[col] = x[col] * 1000

    x = x.dropna(
        subset=[
            "time",
            "open",
            "high",
            "low",
            "close",
        ]
    )

    x = x[
        (x["close"] > 0) &
        (x["high"] >= x["low"])
    ].copy()

    x["volume"] = x["volume"].fillna(0)

    x = (
        x
        .drop_duplicates(
            subset="time",
            keep="last"
        )
        .sort_values("time")
        .reset_index(drop=True)
    )

    return x


# ═════ [cell 117] _safe_num ═════
def _safe_num(s):
    return pd.to_numeric(s, errors="coerce")


# ═════ [cell 117] build_scanner_features ═════
def build_scanner_features(df, benchmark_df=None):
    """
    Build a compact causal feature set from OHLCV.

    All rolling values use data available on or before the current bar.
    """
    x = normalize_ohlcv(df)

    c = x["close"]
    h = x["high"]
    l = x["low"]
    o = x["open"]
    v = x["volume"]

    # Trend
    x["ret_1d"] = c.pct_change(1)
    x["ret_5d"] = c.pct_change(5)
    x["ret_20d"] = c.pct_change(20)
    x["ret_60d"] = c.pct_change(60)

    x["ma20"] = c.rolling(20, min_periods=20).mean()
    x["ma50"] = c.rolling(50, min_periods=50).mean()
    x["ma200"] = c.rolling(200, min_periods=200).mean()

    x["ma20_slope"] = x["ma20"].pct_change(5)
    x["ma50_slope"] = x["ma50"].pct_change(10)

    x["above_ma20"] = (c > x["ma20"]).astype(int)
    x["above_ma50"] = (c > x["ma50"]).astype(int)
    x["above_ma200"] = (c > x["ma200"]).astype(int)

    # ATR
    prev_close = c.shift(1)
    tr = pd.concat([
        h - l,
        (h - prev_close).abs(),
        (l - prev_close).abs()
    ], axis=1).max(axis=1)

    x["atr14"] = tr.rolling(14, min_periods=14).mean()
    x["atr_pct"] = x["atr14"] / c

    # RSI
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    x["rsi14"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()

    x["macd"] = ema12 - ema26
    x["macd_signal"] = x["macd"].ewm(
        span=9,
        adjust=False
    ).mean()
    x["macd_hist"] = x["macd"] - x["macd_signal"]

    # ADX-like trend strength
    up_move = h.diff()
    down_move = -l.diff()

    plus_dm = pd.Series(
        np.where(
            (up_move > down_move) & (up_move > 0),
            up_move,
            0.0
        ),
        index=x.index
    )

    minus_dm = pd.Series(
        np.where(
            (down_move > up_move) & (down_move > 0),
            down_move,
            0.0
        ),
        index=x.index
    )

    atr = x["atr14"].replace(0, np.nan)

    plus_di = 100 * plus_dm.ewm(
        alpha=1 / 14,
        adjust=False
    ).mean() / atr

    minus_di = 100 * minus_dm.ewm(
        alpha=1 / 14,
        adjust=False
    ).mean() / atr

    dx = (
        (plus_di - minus_di).abs() /
        (plus_di + minus_di).replace(0, np.nan)
    ) * 100

    x["adx14"] = dx.ewm(
        alpha=1 / 14,
        adjust=False
    ).mean()

    # Volume / flow
    x["vol_ma20"] = v.rolling(
        20,
        min_periods=20
    ).mean()

    x["volume_ratio"] = v / x["vol_ma20"]

    x["dollar_value"] = c * v
    x["avg_value_20d"] = x["dollar_value"].rolling(
        20,
        min_periods=20
    ).mean()

    # OBV
    direction = np.sign(c.diff()).fillna(0)
    x["obv"] = (direction * v).cumsum()
    x["obv_ma20"] = x["obv"].rolling(
        20,
        min_periods=20
    ).mean()

    # Chaikin Money Flow
    hl_range = (h - l).replace(0, np.nan)
    mfm = ((c - l) - (h - c)) / hl_range
    mfv = mfm * v

    x["cmf20"] = (
        mfv.rolling(20, min_periods=20).sum() /
        v.rolling(20, min_periods=20).sum()
    )

    # Money Flow Index
    typical = (h + l + c) / 3
    raw_money = typical * v
    direction_typical = typical.diff()

    positive_money = raw_money.where(
        direction_typical > 0,
        0
    )
    negative_money = raw_money.where(
        direction_typical < 0,
        0
    ).abs()

    pos_sum = positive_money.rolling(
        14,
        min_periods=14
    ).sum()

    neg_sum = negative_money.rolling(
        14,
        min_periods=14
    ).sum()

    money_ratio = pos_sum / neg_sum.replace(0, np.nan)

    x["mfi14"] = 100 - (
        100 / (1 + money_ratio)
    )

    # Structure / breakout
    x["resistance20"] = h.shift(1).rolling(
        20,
        min_periods=20
    ).max()

    x["support20"] = l.shift(1).rolling(
        20,
        min_periods=20
    ).min()

    x["breakout20"] = (
        c > x["resistance20"]
    ).astype(int)

    x["breakdown20"] = (
        c < x["support20"]
    ).astype(int)

    x["distance_resistance"] = (
        c / x["resistance20"] - 1
    )

    x["distance_support"] = (
        c / x["support20"] - 1
    )

    # Relative strength vs benchmark
    if benchmark_df is not None:
        b = normalize_ohlcv(benchmark_df)[
            ["time", "close"]
        ].rename(columns={"close": "benchmark_close"})

        x = x.merge(
            b,
            on="time",
            how="left"
        )

        x["benchmark_ret_60d"] = (
            x["benchmark_close"].pct_change(60)
        )

        x["relative_strength_60d"] = (
            x["ret_60d"] -
            x["benchmark_ret_60d"]
        )
    else:
        x["benchmark_close"] = np.nan
        x["benchmark_ret_60d"] = np.nan
        x["relative_strength_60d"] = np.nan

    return x


# ═════ [cell 118] detect_market_regime ═════
def detect_market_regime(benchmark_df):
    x = build_scanner_features(benchmark_df)

    if x.empty:
        return {
            "regime": "UNKNOWN",
            "score": np.nan,
            "reason": "No benchmark data"
        }

    r = x.iloc[-1]

    score = 50.0
    reasons = []

    if r["close"] > r["ma20"]:
        score += 10
        reasons.append("VNINDEX > MA20")
    else:
        score -= 10
        reasons.append("VNINDEX < MA20")

    if r["close"] > r["ma50"]:
        score += 10
        reasons.append("VNINDEX > MA50")
    else:
        score -= 10
        reasons.append("VNINDEX < MA50")

    if r["close"] > r["ma200"]:
        score += 15
        reasons.append("VNINDEX > MA200")
    else:
        score -= 15
        reasons.append("VNINDEX < MA200")

    if r["ma20_slope"] > 0:
        score += 5
    else:
        score -= 5

    if r["ma50_slope"] > 0:
        score += 5
    else:
        score -= 5

    if r["cmf20"] > 0:
        score += 5
        reasons.append("market CMF positive")
    else:
        score -= 5

    score = float(np.clip(score, 0, 100))

    if score >= 75:
        regime = "STRONG_BULL"
    elif score >= 60:
        regime = "BULL"
    elif score >= 45:
        regime = "SIDEWAYS"
    elif score >= 30:
        regime = "BEAR"
    else:
        regime = "STRONG_BEAR"

    return {
        "regime": regime,
        "score": score,
        "close": float(r["close"]),
        "ma20": float(r["ma20"]) if pd.notna(r["ma20"]) else np.nan,
        "ma50": float(r["ma50"]) if pd.notna(r["ma50"]) else np.nan,
        "ma200": float(r["ma200"]) if pd.notna(r["ma200"]) else np.nan,
        "reason": "; ".join(reasons)
    }


# ═════ [cell 119] _clip_score ═════
def _clip_score(x):
    return float(np.clip(x, 0, 100))


# ═════ [cell 119] score_stock_snapshot ═════
def score_stock_snapshot(x):
    """
    Transparent rule-based score.

    This is intentionally interpretable and acts as a safety/ranking layer
    around the probability model rather than pretending the hand-built
    score itself is statistically optimal.
    """
    r = x.iloc[-1]

    # -------------------------
    # Trend score
    # -------------------------
    trend = 0.0

    trend += 20 if r["above_ma20"] else 0
    trend += 20 if r["above_ma50"] else 0
    trend += 20 if r["above_ma200"] else 0
    trend += 15 if r["ma20_slope"] > 0 else 0
    trend += 15 if r["ma50_slope"] > 0 else 0
    trend += 10 if r["adx14"] >= 20 else 0
    trend = _clip_score(trend)

    # -------------------------
    # Momentum
    # -------------------------
    momentum = 50.0

    if r["ret_20d"] > 0:
        momentum += 15
    else:
        momentum -= 15

    if r["ret_60d"] > 0:
        momentum += 15
    else:
        momentum -= 15

    if 50 <= r["rsi14"] <= 70:
        momentum += 15
    elif r["rsi14"] > 75:
        momentum -= 10
    elif r["rsi14"] < 40:
        momentum -= 10

    if r["macd_hist"] > 0:
        momentum += 10
    else:
        momentum -= 10

    momentum = _clip_score(momentum)

    # -------------------------
    # Flow / volume
    # -------------------------
    flow = 50.0

    if r["volume_ratio"] >= 1.5:
        flow += 15
    elif r["volume_ratio"] >= 1.1:
        flow += 8
    elif r["volume_ratio"] < 0.7:
        flow -= 8

    if r["cmf20"] > 0.10:
        flow += 20
    elif r["cmf20"] > 0:
        flow += 10
    else:
        flow -= 15

    if r["mfi14"] >= 50:
        flow += 10
    else:
        flow -= 10

    if r["obv"] > r["obv_ma20"]:
        flow += 10
    else:
        flow -= 10

    flow = _clip_score(flow)

    # -------------------------
    # Structure / setup
    # -------------------------
    structure = 50.0
    setup = "NONE"

    if r["breakout20"]:
        structure += 35
        setup = "BREAKOUT"
    elif (
        r["close"] > r["ma20"] and
        r["close"] > r["ma50"] and
        r["ret_5d"] < 0 and
        r["ret_20d"] > 0
    ):
        structure += 20
        setup = "PULLBACK_IN_UPTREND"
    elif (
        r["close"] > r["ma50"] and
        r["ret_20d"] > 0
    ):
        structure += 10
        setup = "UPTREND_CONTINUATION"

    if r["distance_resistance"] < 0.03:
        structure += 5

    if r["breakdown20"]:
        structure -= 40
        setup = "BREAKDOWN"

    structure = _clip_score(structure)

    # -------------------------
    # Relative strength
    # -------------------------
    rs = 50.0

    if pd.notna(r["relative_strength_60d"]):
        if r["relative_strength_60d"] > 0.10:
            rs += 35
        elif r["relative_strength_60d"] > 0.03:
            rs += 20
        elif r["relative_strength_60d"] < -0.10:
            rs -= 35
        elif r["relative_strength_60d"] < -0.03:
            rs -= 20

    rs = _clip_score(rs)

    # -------------------------
    # Composite
    # -------------------------
    alpha_score = (
        0.25 * trend +
        0.20 * momentum +
        0.25 * flow +
        0.15 * structure +
        0.15 * rs
    )

    # -------------------------
    # Exit risk
    # -------------------------
    exit_risk = 0.0
    exit_reasons = []

    if r["close"] < r["ma20"]:
        exit_risk += 15
        exit_reasons.append("price below MA20")

    if r["close"] < r["ma50"]:
        exit_risk += 25
        exit_reasons.append("price below MA50")

    if r["ma20_slope"] < 0:
        exit_risk += 10
        exit_reasons.append("MA20 slope negative")

    if r["macd_hist"] < 0:
        exit_risk += 10
        exit_reasons.append("MACD histogram negative")

    if r["cmf20"] < -0.05:
        exit_risk += 20
        exit_reasons.append("money flow distribution")

    if r["volume_ratio"] >= 1.5 and r["ret_1d"] < 0:
        exit_risk += 10
        exit_reasons.append("high-volume down day")

    if r["breakdown20"]:
        exit_risk += 30
        exit_reasons.append("20D support breakdown")

    # Divergence-like warning:
    # price still rising while money flow is deteriorating.
    if (
        r["ret_20d"] > 0 and
        r["cmf20"] < 0 and
        r["obv"] < r["obv_ma20"]
    ):
        exit_risk += 15
        exit_reasons.append("price-flow divergence")

    exit_risk = _clip_score(exit_risk)

    return {
        "trend_score": trend,
        "momentum_score": momentum,
        "flow_score": flow,
        "structure_score": structure,
        "relative_strength_score": rs,
        "alpha_score": _clip_score(alpha_score),
        "setup": setup,
        "exit_risk": exit_risk,
        "exit_reasons": "; ".join(exit_reasons),
    }


# ═════ [cell 119] classify_signal ═════
def classify_signal(
    alpha_score,
    p_tp,
    exit_risk,
    market_regime,
    cfg
):
    # Exit dominates a new-buy signal.
    if exit_risk >= cfg["exit_risk_threshold"]:
        return "EXIT"

    if exit_risk >= cfg["reduce_risk_threshold"]:
        if alpha_score < cfg["watch_score"]:
            return "REDUCE"

    # Market gate.
    bear_market = market_regime in {
        "BEAR",
        "STRONG_BEAR"
    }

    if bear_market and not cfg["allow_new_long_in_bear"]:
        if alpha_score >= cfg["watch_score"]:
            return "WATCH"

    if (
        alpha_score >= cfg["buy_score"]
    ):
        if alpha_score >= cfg["strong_p_tp"] * 100:
            return "STRONG_BUY"
        return "BUY"

    if alpha_score >= cfg["watch_score"]:
        return "WATCH"

    return "NO_SIGNAL"


# ═════ [cell 120] _get_live_probability ═════
def _get_live_probability(snapshot_df):
    """
    Use the already-trained ProbabilityModel when available.

    If no compatible trained model exists, return NaN rather than inventing
    a probability. The rule-based Alpha Score still works as a fallback
    ranking layer.
    """
    model_candidates = [
        globals().get("probability_model"),
        globals().get("MODEL"),
        globals().get("model"),
    ]

    model = next(
        (m for m in model_candidates if m is not None),
        None
    )

    if model is None:
        return np.nan

    try:
        p = model.predict_proba(snapshot_df)
        return float(np.asarray(p).reshape(-1)[-1])
    except Exception:
        return np.nan


# ═════ [cell 120] combine_probability_and_score ═════
def combine_probability_and_score(alpha_score, p_tp):
    """
    Do not manufacture a probability when the statistical model is absent.

    If p_tp exists, blend it with interpretable Alpha Score.
    """
    if pd.isna(p_tp):
        return float(alpha_score)

    p_score = float(p_tp) * 100.0

    return float(
        0.60 * alpha_score +
        0.40 * p_score
    )


# ═════ [cell 121] scan_one_symbol ═════
def scan_one_symbol(
    symbol,
    benchmark_df,
    market_info,
    cfg=SCAN_CFG,
    as_of=None
):
    symbol = str(symbol).upper().strip()

    result = {
        "symbol": symbol,
        "status": "ERROR",
        "signal": "ERROR",
        "error": None
    }

    try:
        raw = _call_data_layer(
            symbol,
            lookback_days=LOOKBACK_DAYS,
            as_of=as_of
        )

        df = normalize_ohlcv(raw)

        # Only use information available on the benchmark's latest session.
        if as_of is not None:
            df = df[df["time"] <= pd.Timestamp(as_of).normalize()].copy()

        if df.empty:
            raise RuntimeError("no rows at or before scanner as_of date")

        if len(df) < cfg["min_history_rows"]:
            result.update({
                "status": "FILTERED",
                "signal": "INSUFFICIENT_HISTORY",
                "history_rows": len(df)
            })
            return result

        features = build_scanner_features(
            df,
            benchmark_df=benchmark_df
        )

        r = features.iloc[-1]

        avg_value = float(
            r["avg_value_20d"]
        ) if pd.notna(r["avg_value_20d"]) else 0.0

        last_price = float(r["close"])

        if last_price < cfg["min_price"]:
            result.update({
                "status": "FILTERED",
                "signal": "LOW_PRICE",
                "last_price": last_price,
                "avg_value_20d": avg_value
            })
            return result

        if avg_value < cfg["min_avg_value_20d"]:
            result.update({
                "status": "FILTERED",
                "signal": "LOW_LIQUIDITY",
                "last_price": last_price,
                "avg_value_20d": avg_value
            })
            return result

        scores = score_stock_snapshot(features)

        # The live probability model should receive exactly the same feature
        # contract used during model training. If it cannot do so, p_tp stays NaN.
        p_tp = _get_live_probability(
            features.tail(1)
        )

        combined = combine_probability_and_score(
            scores["alpha_score"],
            p_tp
        )

        signal = classify_signal(
            scores["alpha_score"],
            p_tp if pd.notna(p_tp) else scores["alpha_score"] / 100,
            scores["exit_risk"],
            market_info["regime"],
            cfg
        )

        # Price-based stop reference.
        atr_pct = (
            float(r["atr_pct"])
            if pd.notna(r["atr_pct"])
            else 0.05
        )

        suggested_sl_pct = float(
            np.clip(1.5 * atr_pct, 0.03, 0.12)
        )

        suggested_tp_pct = float(
            np.clip(2.0 * suggested_sl_pct, 0.06, 0.25)
        )

        # Human-readable reasons.
        reasons = []

        if scores["trend_score"] >= 70:
            reasons.append("trend strong")
        if scores["flow_score"] >= 70:
            reasons.append("money flow/volume supportive")
        if scores["structure_score"] >= 70:
            reasons.append(f"setup={scores['setup']}")
        if scores["relative_strength_score"] >= 70:
            reasons.append("relative strength strong")
        if r["volume_ratio"] >= 1.5:
            reasons.append(
                f"volume {r['volume_ratio']:.1f}x average"
            )

        warnings = []

        if scores["exit_risk"] >= cfg["reduce_risk_threshold"]:
            warnings.append(
                scores["exit_reasons"]
            )

        if r["rsi14"] > 75:
            warnings.append("RSI overbought")

        if (
            r["ret_20d"] > 0 and
            r["cmf20"] < 0
        ):
            warnings.append("price-flow divergence")

        result.update({
            "status": "OK",
            "signal": signal,
            "date": r["time"],
            "last_price": last_price,
            "history_rows": len(df),
            "avg_value_20d": avg_value,

            "alpha_score": round(scores["alpha_score"], 2),
            "combined_score": round(combined, 2),

            "p_tp": (
                round(float(p_tp), 4)
                if pd.notna(p_tp)
                else np.nan
            ),

            "trend_score": round(scores["trend_score"], 2),
            "momentum_score": round(scores["momentum_score"], 2),
            "flow_score": round(scores["flow_score"], 2),
            "structure_score": round(scores["structure_score"], 2),
            "relative_strength_score": round(
                scores["relative_strength_score"], 2
            ),

            "setup": scores["setup"],
            "exit_risk": round(scores["exit_risk"], 2),

            "rsi14": round(float(r["rsi14"]), 2),
            "adx14": round(float(r["adx14"]), 2),
            "volume_ratio": round(float(r["volume_ratio"]), 2),
            "cmf20": round(float(r["cmf20"]), 3),
            "ret_20d": round(float(r["ret_20d"]) * 100, 2),
            "ret_60d": round(float(r["ret_60d"]) * 100, 2),

            "suggested_sl_pct": round(
                suggested_sl_pct * 100,
                2
            ),
            "suggested_tp_pct": round(
                suggested_tp_pct * 100,
                2
            ),

            "reasons": "; ".join(reasons),
            "warnings": "; ".join(
                [w for w in warnings if w]
            ),
            "market_regime": market_info["regime"],
            "market_score": market_info["score"],
        })

        return result

    except Exception as exc:
        result.update({
            "status": "ERROR",
            "signal": "ERROR",
            "error": f"{type(exc).__name__}: {exc}"
        })

        if VERBOSE_SCAN:
            import traceback
            traceback.print_exc()

        return result


# ═════ [cell 124] normalize_ohlcv ═════
def normalize_ohlcv(df, source=None):
    """
    Normalize OHLCV dataframe from vnstock / KBS / VCI
    into the canonical schema used by the scanner:

        time
        open
        high
        low
        close
        volume

    Also handles common vnstock column naming variations.
    """

    if df is None:
        raise ValueError("OHLCV dataframe is None")

    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"OHLCV must be pandas.DataFrame, got {type(df)}"
        )

    if df.empty:
        raise ValueError("OHLCV dataframe is empty")

    x = df.copy()

    # --------------------------------------------------------
    # Normalize column names
    # --------------------------------------------------------
    x.columns = [
        str(c).strip()
        for c in x.columns
    ]

    # Map lower-case column names -> actual column names
    col_map = {
        str(c).strip().lower(): c
        for c in x.columns
    }

    def find_column(candidates):
        for candidate in candidates:
            key = candidate.lower()

            if key in col_map:
                return col_map[key]

        return None

    # --------------------------------------------------------
    # TIME / DATE
    # --------------------------------------------------------
    time_col = find_column([
        "time",
        "date",
        "datetime",
        "dt",
        "trading_date",
        "tradingdate",
        "timestamp",
    ])

    # Some vnstock responses may use "TradingDate"
    if time_col is None:
        time_col = find_column([
            "trading_date",
            "TradingDate",
            "Date",
            "Time",
        ])

    # --------------------------------------------------------
    # OHLCV
    # --------------------------------------------------------
    open_col = find_column([
        "open",
        "Open",
        "o",
    ])

    high_col = find_column([
        "high",
        "High",
        "h",
    ])

    low_col = find_column([
        "low",
        "Low",
        "l",
    ])

    close_col = find_column([
        "close",
        "Close",
        "c",
        "price",
    ])

    volume_col = find_column([
        "volume",
        "Volume",
        "vol",
        "Vol",
        "v",
    ])

    # --------------------------------------------------------
    # If Date/Time is stored as index
    # --------------------------------------------------------
    if time_col is None:

        if isinstance(
            x.index,
            pd.DatetimeIndex
        ):
            x = x.reset_index()

            # Usually reset_index() creates "index"
            time_col = find_column([
                "time",
                "date",
                "datetime",
                "dt",
                "trading_date",
                "tradingdate",
                "timestamp",
                "index",
            ])

    # --------------------------------------------------------
    # Validate columns
    # --------------------------------------------------------
    missing = []

    if time_col is None:
        missing.append("time")

    if open_col is None:
        missing.append("open")

    if high_col is None:
        missing.append("high")

    if low_col is None:
        missing.append("low")

    if close_col is None:
        missing.append("close")

    if volume_col is None:
        missing.append("volume")

    if missing:

        raise ValueError(
            "Unable to normalize OHLCV. "
            f"Missing columns: {missing}. "
            f"Available columns: {list(x.columns)}"
        )

    # --------------------------------------------------------
    # Rename to canonical names
    # --------------------------------------------------------
    rename_map = {
        time_col: "time",
        open_col: "open",
        high_col: "high",
        low_col: "low",
        close_col: "close",
        volume_col: "volume",
    }

    x = x.rename(
        columns=rename_map
    )

    # --------------------------------------------------------
    # Convert time
    # --------------------------------------------------------
    x["time"] = pd.to_datetime(
        x["time"],
        errors="coerce"
    )

    # Remove timezone if present.
    #
    # We only care about trading date for this EOD scanner.
    try:
        if hasattr(
            x["time"].dt,
            "tz"
        ):
            if x["time"].dt.tz is not None:
                x["time"] = (
                    x["time"]
                    .dt
                    .tz_localize(None)
                )
    except Exception:
        pass

    x["time"] = x["time"].dt.normalize()

    # --------------------------------------------------------
    # Convert numeric columns
    # --------------------------------------------------------
    for col in [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]:

        x[col] = pd.to_numeric(
            x[col],
            errors="coerce"
        )

    # --------------------------------------------------------
    # KBS price unit normalization
    #
    # KBS historical OHLC data may be represented in
    # thousand VND.
    #
    # We only multiply prices when source is explicitly KBS.
    # Never blindly multiply unknown sources.
    # --------------------------------------------------------
    if source is not None:

        source_upper = str(
            source
        ).upper()

        if source_upper == "KBS":

            # Detect whether values appear to be in
            # thousand VND rather than VND.
            #
            # Typical FPT:
            #   150  -> 150,000 VND
            #
            # Avoid multiplying if already clearly VND.
            median_close = (
                x["close"]
                .dropna()
                .median()
            )

            if (
                pd.notna(median_close)
                and median_close > 0
                and median_close < 1000
            ):

                for col in [
                    "open",
                    "high",
                    "low",
                    "close",
                ]:
                    x[col] = (
                        x[col] * 1000.0
                    )

    # --------------------------------------------------------
    # Remove invalid rows
    # --------------------------------------------------------
    x = x.dropna(
        subset=[
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    )

    # --------------------------------------------------------
    # Basic OHLC sanity checks
    # --------------------------------------------------------
    x = x[
        (x["open"] > 0)
        & (x["high"] > 0)
        & (x["low"] > 0)
        & (x["close"] > 0)
        & (x["volume"] >= 0)
    ]

    # High must be >= low
    x = x[
        x["high"] >= x["low"]
    ]

    # High should contain O/C
    x = x[
        (x["high"] >= x["open"])
        & (x["high"] >= x["close"])
    ]

    # Low should be <= O/C
    x = x[
        (x["low"] <= x["open"])
        & (x["low"] <= x["close"])
    ]

    # --------------------------------------------------------
    # Sort and deduplicate
    # --------------------------------------------------------
    x = (
        x
        .sort_values("time")
        .drop_duplicates(
            subset=["time"],
            keep="last"
        )
        .reset_index(drop=True)
    )

    # --------------------------------------------------------
    # Final canonical column order
    # --------------------------------------------------------
    canonical_columns = [
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    # Keep canonical columns first.
    other_columns = [
        c
        for c in x.columns
        if c not in canonical_columns
    ]

    x = x[
        canonical_columns
        + other_columns
    ]

    if x.empty:
        raise ValueError(
            "OHLCV became empty after normalization "
            "and validation."
        )

    return x
