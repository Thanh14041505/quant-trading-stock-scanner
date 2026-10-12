# -*- coding: utf-8 -*-
# ╔════════════════════════════════════════════════════════════════════════╗
# ║  FILE SINH TỰ ĐỘNG — KHÔNG SỬA TAY                                      ║
# ║  Sinh bởi tools/extract_legacy.py; nội dung các cell là NGUYÊN VĂN.     ║
# ╚════════════════════════════════════════════════════════════════════════╝
# Source Notebook : Tool_CK_Grok_v2_PR016.ipynb
# Section         : Production scanner (QuantEngine.run_pipeline và các engine phụ thuộc)
# Cells được giữ  : [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
# Ghi chú         : S5 — v8 (PR016). Loại: 0,1, 22 (__main__). Giữ cell 20 (BacktestEngine) vì QuantEngine.__init__ khởi tạo nó; KHÔNG dùng trong scan.
# Lý do giữ nguyên: dự án ưu tiên "bảo toàn logic notebook" (bug, ngưỡng, thứ tự tính toán).
#                   Mọi vá lỗi nằm ở lớp adapter (strategies/strategy_XX.py), KHÔNG ở file này.


# ═════ [source cell 2] Tool_CK_Grok_v2_PR016.ipynb ═════
"""
╔══════════════════════════════════════════════════════════════════════╗
║   VN QUANT ENGINE v8                                                ║
║   + Ichimoku Đa Khung Thời Gian (Trịnh Phát Style)                 ║
║   + Target theo kháng cự kỹ thuật (không còn ATR × hằng số)        ║
╠══════════════════════════════════════════════════════════════════════╣
║  WHAT'S NEW v8:                                                      ║
║  [NEW] IchimokuEngine — tính D/W/M đồng thời                       ║
║        Tenkan / Kijun / Senkou A&B / Chikou trên 3 khung           ║
║        Kumo Twist detection (mây đổi màu → cảnh báo đảo chiều)    ║
║        Cloud Support/Resistance zones từ 3 timeframe               ║
║  [NEW] Target theo kháng cự thực: Kijun, Senkou, swing high        ║
║        Ưu tiên mức có lợi nhuận ≥ 9% (min_profit_pct config)      ║
║  [NEW] IchiScore tích hợp vào ScoringEngine (weight 12%)           ║
║  [NEW] smart_entry ưu tiên: Kijun-sen pullback, đáy mây (Kumo)    ║
║  [FIX] applymap → map (Pandas 2.1+ compat)                         ║
║  [FIX] Magic numbers → QuantConfig constants                        ║
║  [FIX] _swing_low/high → scipy vectorized (10× faster)             ║
║  [KEEP] Toàn bộ v7: MomentumEngine, Regime, Position Sizing        ║
╚══════════════════════════════════════════════════════════════════════╝

Cách dùng (Google Colab):
    from vn_market_scanner_v7 import QuantEngine
    engine = QuantEngine(capital=500_000_000)
    df = engine.run()
    df = engine.run(mode="hold")
    engine.detail("HPG")
"""

import warnings, time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

warnings.filterwarnings("ignore")

# scipy optional — fallback to loop nếu không có
try:
    from scipy.signal import argrelextrema
    _HAS_SCIPY = True
except Exception: # Changed from ImportError to Exception to catch AttributeError
    _HAS_SCIPY = False


# ══════════════════════════════════════════════════════════════════
# CONFIG — không còn magic numbers trong ScoringEngine
# ══════════════════════════════════════════════════════════════════

@dataclass
class QuantConfig:
    # Data
    lookback_short:         int   = 60
    lookback_long:          int   = 280
    lookback_weekly:        int   = 800   # ~2 năm để tính W/M Ichimoku
    sources:                list  = field(default_factory=lambda: ["KBS","VCI"])
    delay_sec:              float = 2
    vp_bins:                int   = 35

    # Scoring thresholds
    min_score_swing:        float = 5.0
    min_score_hold:         float = 6.0
    min_rr:                 float = 1.5
    min_profit_pct:         float = 9.0   # lợi nhuận T+ tối thiểu hiển thị (%)

    # Liquidity
    min_avg_vol_20d:        int   = 50_000
    min_avg_val_20d:        float = 10e5

    # Position sizing
    capital:                float = 100_000_000
    risk_per_trade:         float = 0.01
    max_position_pct:       float = 0.20
    kelly_fraction:         float = 0.25
    entry_atr_mult:         float = 0.4

    # MomentumEngine
    bb_period:              int   = 20
    bb_std:                 float = 2.0
    squeeze_pct:            float = 15.0
    squeeze_lookback:       int   = 60
    div_lookback:           int   = 5

    # Ichimoku periods
    ichi_tenkan:            int   = 9
    ichi_kijun:             int   = 26
    ichi_senkou_b:          int   = 52
    ichi_displacement:      int   = 26

    # ScoringEngine constants (thay cho magic numbers)
    vol_score_low_cap:      float = 0.8    # vol dưới mức này → điểm thấp
    vol_score_mid:          float = 1.3
    vol_score_high:         float = 2.2
    cmf_score_offset:       float = 0.25
    cmf_score_scale:        float = 0.055
    obv_slope_scale:        float = 9.0
    force_scale:            float = 4.8
    ema_score_offset:       float = 6.0
    ema_score_scale:        float = 1.1
    macd_hist_scale:        float = 480.0
    stoch_bull_cross_bonus: float = 1.8
    macd_cross_bonus:       float = 1.7

    use_fundamental:        bool  = True

    # Ichimoku Trịnh Phát — Dao Găm (MA dài hạn dùng làm hỗ trợ/kháng cự)
    dao_gam_mid:            int   = 65     # Dao găm trung hạn
    dao_gam_long:           int   = 129    # Dao găm dài hạn
    dao_gam_atr_buffer:     float = 0.4    # Vùng đệm "chạm" theo ATR
    ma_test_pct_buffer:     float = 0.012  # ~1.2% biên độ test MA50/200
    ma_short_fast:          int   = 9
    ma_short_slow:          int   = 10


VN100 = ['FPT', 'VCB', 'HPG', 'TCB', 'ACB', 'BID', 'MWG', 'SSI', 'VND', 'CTD', 'VHM', 'VIC', 'VRE', 'PNJ', 'MSN',
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


BASE_WEIGHTS = {
    "volume_ratio":12,"cmf":10,"obv":6,"force":4,"inst_flow":6,
    "rsi":9,"ema":6,"stoch":5,"macd":4,
    "vp_position":10,"trend":9,"rs_score":7,
    "ichimoku":12,   # [NEW]
}

REGIME_WEIGHT_DELTA = {
    "bull":     {"volume_ratio":+3,"trend":+4,"ichimoku":+3,"rsi":-2,"cmf":-2},
    "sideways": {"cmf":+3,"obv":+3,"vp_position":+4,"ichimoku":+2,"trend":-4},
    "bear":     {"cmf":+5,"force":+3,"trend":-5,"ichimoku":-3,"volume_ratio":-3},
    "panic":    {"cmf":+4,"force":+5,"volume_ratio":+4,"ichimoku":-4,"trend":-6},
}
REGIME_SCORE_MULT = {"bull":1.00,"sideways":0.95,"bear":0.85,"panic":0.70}


# ═════ [source cell 3] Tool_CK_Grok_v2_PR016.ipynb ═════
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class SwingPoint:
    """
    Đại diện cho một Swing High / Swing Low.
    Đây sẽ là cấu trúc chuẩn cho toàn bộ Trend Engine.
    """

    index: int
    timestamp: pd.Timestamp
    price: float

    swing_type: str      # HIGH / LOW

    strength: int = 1

    confidence: float = 50.0

    atr: Optional[float] = None

    volume: Optional[float] = None


# ═════ [source cell 4] Tool_CK_Grok_v2_PR016.ipynb ═════
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class FeatureResult:
    """
    Chuẩn output cho mọi Feature Engine.

    Ví dụ:

    TrendEngine

    MoneyFlowEngine

    MomentumEngine

    IchimokuEngine

    đều trả về FeatureResult.
    """

    # Tên feature
    name: str

    # Điểm chuẩn hóa
    score: float = 50.0

    # Độ tin cậy
    confidence: float = 50.0

    # Trọng số động
    weight: float = 1.0

    # Các metric gốc
    metrics: dict[str, Any] = field(default_factory=dict)

    # Luận điểm tích cực
    reasons: list[str] = field(default_factory=list)

    # Luận điểm tiêu cực
    warnings: list[str] = field(default_factory=list)


@dataclass
class MarketContext:
    """
    Bối cảnh thị trường tại thời điểm scan.
    Không phải của riêng một cổ phiếu.
    """

    market_regime: str = "UNKNOWN"      # BULL / SIDEWAY / BEAR
    market_score: float = 50

    leading_sectors: List[str] = field(default_factory=list)

    vnindex_strength: float = 50

    liquidity_score: float = 50

    foreign_flow_score: float = 50

    sentiment_score: float = 50


@dataclass
class MarketEvidence:
    """
    Chuẩn hóa toàn bộ kết quả phân tích của hệ thống.

    Quy ước:
    0   = rất yếu
    50  = trung tính
    100 = cực mạnh
    """

    features: list[FeatureResult] = field(default_factory=list)

    market_context: Optional[MarketContext] = None

    overall_score: float = 50.0

    confidence: float = 50.0

    reasons: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)


@dataclass
class DecisionGate:
    """
    Hard Filters.

    Nếu bất kỳ điều kiện nào FAIL thì
    Decision Engine sẽ không BUY
    dù score có cao.
    """

    liquidity_pass: bool = True

    market_pass: bool = True

    sector_pass: bool = True

    trend_pass: bool = True

    risk_pass: bool = True

    reason: str = ""


# ═════ [source cell 5] Tool_CK_Grok_v2_PR016.ipynb ═════
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List


class BaseEngine(ABC):
    """
    Base class cho toàn bộ Quant Engine.

    Mọi Engine đều implement analyze().
    """

    @abstractmethod
    def analyze(self, df):

        raise NotImplementedError()


# ═════ [source cell 6] Tool_CK_Grok_v2_PR016.ipynb ═════
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StockProfile:
    """
    Hồ sơ định lượng của một cổ phiếu.
    Đây sẽ là đầu ra tổng hợp trước khi ra quyết định.
    """

    symbol: str

    # ===== Context =====
    market_regime: str = "UNKNOWN"
    sector: str = "UNKNOWN"

    # ===== Trend =====
    trend_stage: str = "UNKNOWN"

    # ===== Scores =====
    trend_score: float = 50
    momentum_score: float = 50
    money_flow_score: float = 50
    volume_score: float = 50
    risk_score: float = 50

    # ===== Final =====
    overall_score: float = 50
    confidence: float = 50

    # ===== Decision =====
    suggested_action: str = "WATCH"

    # ===== Risk =====
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    # ===== Explainability =====
    investment_thesis: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)


@dataclass
class DataQuality:
    """
    Đánh giá chất lượng dữ liệu đầu vào.
    Đây là cơ sở để tính confidence của toàn bộ Quant Engine.
    """

    total_rows: int = 0

    missing_rows: int = 0

    duplicated_rows: int = 0

    invalid_rows: int = 0

    missing_volume: int = 0

    confidence: float = 100.0

    issues: list[str] = field(default_factory=list)


# ═════ [source cell 7] Tool_CK_Grok_v2_PR016.ipynb ═════
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class MarketData:
    """
    Object chuẩn truyền xuyên suốt toàn bộ VQDE.

    Mọi Engine chỉ làm việc với MarketData,
    không làm việc trực tiếp với DataFrame.
    """

    symbol: str

    # Raw Data
    daily: pd.DataFrame

    weekly: Optional[pd.DataFrame] = None

    monthly: Optional[pd.DataFrame] = None

    # Metadata
    source: str = ""

    fetched_at: Optional[datetime] = None

    # Liquidity
    avg_volume20: float = 0

    avg_value20: float = 0

    last_price: float = 0

    # Quality
    quality: Optional[DataQuality] = None

    # Cache cho các Engine
    cache: dict = field(default_factory=dict)


# ═════ [source cell 8] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# HELPERS — vectorized swing finder
# ══════════════════════════════════════════════════════════════════

def find_swing_lows_vec(series: pd.Series, order: int = 5) -> list:
    """
    Vectorized swing low finder dùng scipy nếu có, fallback loop.
    order = số nến mỗi bên phải thấp hơn.
    """
    arr = series.values
    if _HAS_SCIPY:
        idx = argrelextrema(arr, np.less_equal, order=order)[0].tolist()
        # Lọc chỉ lấy những nến thực sự local min (không bị flat)
        idx = [i for i in idx if i > order and i < len(arr)-order]
        return idx
    # Fallback
    idx = []
    for i in range(order, len(arr)-order):
        if all(arr[i] <= arr[i-j] for j in range(1,order+1)) and \
           all(arr[i] <= arr[i+j] for j in range(1,order+1)):
            idx.append(i)
    return idx


def find_swing_highs_vec(series: pd.Series, order: int = 5) -> list:
    arr = series.values
    if _HAS_SCIPY:
        idx = argrelextrema(arr, np.greater_equal, order=order)[0].tolist()
        idx = [i for i in idx if i > order and i < len(arr)-order]
        return idx
    idx = []
    for i in range(order, len(arr)-order):
        if all(arr[i] >= arr[i-j] for j in range(1,order+1)) and \
           all(arr[i] >= arr[i+j] for j in range(1,order+1)):
            idx.append(i)
    return idx


OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}

def resample_ohlcv(
    df: pd.DataFrame,
    timeframe: str = "W-FRI",
) -> pd.DataFrame:
    """
    Generic OHLCV Resampler.

    Ví dụ:

    W-FRI

    ME

    QE

    """

    df2 = df.copy()

    if "time" in df2.columns:
        df2["time"] = pd.to_datetime(df2["time"])
        df2 = df2.set_index("time")

    agg = {
        k: v
        for k, v in OHLCV_AGG.items()
        if k in df2.columns
    }

    return (
        df2
        .resample(timeframe)
        .agg(agg)
        .dropna()
        .reset_index()
    )



def validate_ohlcv(df: pd.DataFrame) -> DataQuality:
    """
    Kiểm tra tính hợp lệ của dữ liệu OHLCV.
    """

    quality = DataQuality(total_rows=len(df))

    if df.empty:
        quality.confidence = 0
        quality.issues.append("Empty DataFrame")
        return quality

    duplicated = df.duplicated().sum()
    if duplicated:
        quality.duplicated_rows = int(duplicated)
        quality.issues.append(f"Duplicated rows: {duplicated}")

    invalid = (
        (df["high"] < df["low"])
        | (df["close"] > df["high"])
        | (df["close"] < df["low"])
        | (df["volume"] < 0)
    ).sum()

    if invalid:
        quality.invalid_rows = int(invalid)
        quality.issues.append(f"Invalid OHLC rows: {invalid}")

    quality.missing_volume = int((df["volume"] == 0).sum())

    penalty = (
        duplicated * 0.5
        + invalid * 5
        + quality.missing_volume * 0.1
    )

    quality.confidence = max(0, 100 - penalty)

    return quality


# ═════ [source cell 9] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 1. DATA LAYER  [PR010 — fixed stats, single-fetch, clean cache]
# ══════════════════════════════════════════════════════════════════
from vnstock import Quote

class DataLayer:
    """
    Data access layer with in-memory cache + performance stats.

    fetch() always returns a cleaned OHLCV DataFrame (or None).
    MarketData object is available via build_market_data() when needed.
    """

    def __init__(self, cfg: QuantConfig):
        self.cfg = cfg
        self._cache: dict = {}
        self._stats = {
            "cache_hit": 0,
            "download_ok": 0,
            "download_fail": 0,
        }

    def fetch(self, symbol: str, days: int) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV, clean, cache, return DataFrame.
        Single-fetch pattern: call once with max lookback, then .tail() outside.
        """
        key = f"{symbol}_{days}"
        if key in self._cache:
            self._stats["cache_hit"] += 1
            return self._cache[key].copy()

        end   = (datetime.today() + timedelta(1)).strftime("%Y-%m-%d")
        start = (datetime.today() - timedelta(days=days + 1)).strftime("%Y-%m-%d")

        for src in self.cfg.sources:
            try:
                df = self._fetch_v4(symbol, start, end, src)
                if df is None or df.empty:
                    continue
                clean = self._clean(df, days)
                if clean is not None and len(clean) >= 20:
                    self._cache[key] = clean.copy()
                    self._stats["download_ok"] += 1
                    return clean.copy()
            except Exception:
                continue

        self._stats["download_fail"] += 1
        return None

    def stats(self) -> dict:
        """Performance statistics for debugging / benchmark."""
        return dict(self._stats)

    def clear_cache(self):
        self._cache.clear()

    def _fetch_v4(self, sym: str, start: str, end: str, src: str) -> Optional[pd.DataFrame]:
        """Use Quote API (vnstock v4+)."""
        try:
            q = Quote(symbol=sym, source=src)
            try:
                return q.history(start=start, end=end, interval="1D")
            except TypeError:
                return q.history(start_date=start, end_date=end, interval="1D")
        except Exception:
            return None

    def _clean(self, df: pd.DataFrame, days: int) -> Optional[pd.DataFrame]:
        df = df.copy()
        df.columns = [c.lower().strip() for c in df.columns]
        df = df.rename(columns={
            "tradingdate": "time", "date": "time",
            "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
        })
        if not {"time", "open", "high", "low", "close", "volume"}.issubset(df.columns):
            return None
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].ffill().bfill()
        df["volume"] = df["volume"].fillna(0)
        df = df[df["close"] > 0].sort_values("time").reset_index(drop=True)

        quality = validate_ohlcv(df)
        if quality.confidence < 80:
            print(f"[DataQuality] Warning: {quality}")

        return df.tail(days).reset_index(drop=True)

    def build_market_data(
        self,
        symbol: str,
        df: pd.DataFrame,
        source: str = "",
    ) -> MarketData:
        """Convert cleaned DataFrame → MarketData (weekly/monthly + quality)."""
        weekly  = resample_ohlcv(df, "W-FRI")
        monthly = resample_ohlcv(df, "ME")
        avg_vol20 = float(df["volume"].tail(20).mean())
        avg_val20 = float((df["close"] * df["volume"]).tail(20).mean())

        return MarketData(
            symbol=symbol,
            daily=df,
            weekly=weekly,
            monthly=monthly,
            source=source,
            fetched_at=datetime.now(),
            avg_volume20=avg_vol20,
            avg_value20=avg_val20,
            last_price=float(df["close"].iloc[-1]),
            quality=DataQuality(total_rows=len(df), confidence=100.0),
        )



# ═════ [source cell 10] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 2. ICHIMOKU ENGINE  [NEW]
# ══════════════════════════════════════════════════════════════════

class IchimokuEngine:
    """
    Ichimoku Kinko Hyo theo style Trịnh Phát — đa khung thời gian.

    Nguyên tắc cốt lõi:
    - Nhìn ĐỒNG THỜI 3 khung: Ngày (D), Tuần (W), Tháng (M)
    - Vùng hỗ trợ/kháng cự MẠNH = khi ≥2 khung đồng thuận
    - Chiều xu hướng = màu mây (xanh = bullish, đỏ = bearish)
    - Điểm mua lý tưởng = giá pullback về Kijun-sen hoặc đáy mây

    5 đường Ichimoku:
    1. Tenkan-sen (9): trung điểm max/min 9 kỳ — đường chuyển đổi ngắn hạn
    2. Kijun-sen (26): trung điểm max/min 26 kỳ — đường cơ sở trung hạn
       → Vùng hỗ trợ/kháng cự quan trọng nhất trong Ichimoku
    3. Senkou Span A: trung điểm (Tenkan+Kijun)/2, shift +26 kỳ
    4. Senkou Span B (52): trung điểm max/min 52 kỳ, shift +26 kỳ
       → Span A và B tạo thành Kumo (Mây) — vùng hỗ trợ/kháng cự tổng hợp
    5. Chikou Span: close hiện tại shift -26 kỳ
       → Xác nhận trend: nếu Chikou > giá 26 phiên trước = bullish
    """

    def __init__(self, cfg: QuantConfig):
        self.cfg = cfg
        self.t  = cfg.ichi_tenkan
        self.k  = cfg.ichi_kijun
        self.sb = cfg.ichi_senkou_b
        self.d  = cfg.ichi_displacement

    def compute_ichi(self, df: pd.DataFrame, label: str = "D") -> dict:
        """
        Tính Ichimoku cho 1 dataframe (có thể là daily/weekly/monthly).
        label: "D" / "W" / "M" — prefix cho các key trả về.
        """
        if df is None or len(df) < 3:
            return self._ichi_defaults(label)

        h = df["high"]
        l = df["low"]
        c = df["close"]

        # CHỈNH SỬA: Thêm min_periods=1 để dù khung Tuần/Tháng có ít nến vẫn tính được max/min
        # Tenkan-sen
        tenkan = (h.rolling(self.t, min_periods=1).max() + l.rolling(self.t, min_periods=1).min()) / 2
        # Kijun-sen
        kijun  = (h.rolling(self.k, min_periods=1).max() + l.rolling(self.k, min_periods=1).min()) / 2
        # Senkou Span A (shift +displacement)
        span_a = ((tenkan + kijun) / 2).shift(self.d)
        # Senkou Span B
        span_b = ((h.rolling(self.sb, min_periods=1).max() + l.rolling(self.sb, min_periods=1).min()) / 2).shift(self.d)
        # Chikou Span (close shift -displacement)
        chikou = c.shift(-self.d)

        tenkan_now = float(tenkan.iloc[-1]) if not pd.isna(tenkan.iloc[-1]) else 0
        kijun_now  = float(kijun.iloc[-1])  if not pd.isna(kijun.iloc[-1])  else 0

        # Mây hiện tại = giá trị span tại index hiện tại (đã shift về quá khứ)
        span_a_now = float(span_a.iloc[-1]) if not pd.isna(span_a.iloc[-1]) else 0
        span_b_now = float(span_b.iloc[-1]) if not pd.isna(span_b.iloc[-1]) else 0
        close_now  = float(c.iloc[-1])

        # Chikou so với giá 26 phiên trước
        chikou_val   = float(c.iloc[-1])   # chikou = close hiện tại nhìn về quá khứ
        # CHỈNH SỬA: Nếu số nến nhỏ hơn self.d, so sánh với nến đầu tiên có sẵn thay vì chính nó
        price_26ago  = float(c.iloc[-self.d-1]) if len(c) > self.d else float(c.iloc[0])
        chikou_bull  = bool(chikou_val > price_26ago)

        # Màu mây (bullish = xanh nếu SpanA > SpanB)
        cloud_bullish = bool(span_a_now > span_b_now)
        cloud_top     = max(span_a_now, span_b_now)
        cloud_bot     = min(span_a_now, span_b_now)

        # Vị trí giá so với mây
        above_cloud  = bool(close_now > cloud_top  and cloud_top  > 0)
        below_cloud  = bool(close_now < cloud_bot  and cloud_bot  > 0)
        inside_cloud = bool(cloud_bot <= close_now <= cloud_top)

        # Kumo Twist: mây sắp đổi màu trong 5 kỳ tới
        future_span_a = ((tenkan + kijun) / 2)
        future_span_b = (h.rolling(self.sb).max() + l.rolling(self.sb).min()) / 2
        twist_ahead = False
        if len(future_span_a) >= 5 and len(future_span_b) >= 5:
            fa_now  = float(future_span_a.iloc[-1])
            fb_now  = float(future_span_b.iloc[-1])
            fa_5ago = float(future_span_a.iloc[-6]) if len(future_span_a) >= 6 else fa_now
            fb_5ago = float(future_span_b.iloc[-6]) if len(future_span_b) >= 6 else fb_now
            # Đổi màu: SpanA vượt SpanB hoặc ngược lại trong khoảng này
            twist_ahead = bool((fa_now > fb_now) != (fa_5ago > fb_5ago))

        # Tenkan cắt Kijun
        tenkan_prev = float(tenkan.iloc[-2]) if len(tenkan) >= 2 and not pd.isna(tenkan.iloc[-2]) else tenkan_now
        kijun_prev  = float(kijun.iloc[-2])  if len(kijun)  >= 2 and not pd.isna(kijun.iloc[-2])  else kijun_now
        tk_cross_up   = bool(tenkan_now > kijun_now and tenkan_prev <= kijun_prev)
        tk_cross_down = bool(tenkan_now < kijun_now and tenkan_prev >= kijun_prev)

        prefix = label.lower()
        return {
            f"ichi_{prefix}_tenkan":       round(tenkan_now, 2),
            f"ichi_{prefix}_kijun":        round(kijun_now,  2),
            f"ichi_{prefix}_span_a":       round(span_a_now, 2),
            f"ichi_{prefix}_span_b":       round(span_b_now, 2),
            f"ichi_{prefix}_cloud_top":    round(cloud_top,  2),
            f"ichi_{prefix}_cloud_bot":    round(cloud_bot,  2),
            f"ichi_{prefix}_above_cloud":  above_cloud,
            f"ichi_{prefix}_below_cloud":  below_cloud,
            f"ichi_{prefix}_inside_cloud": inside_cloud,
            f"ichi_{prefix}_cloud_bull":   cloud_bullish,
            f"ichi_{prefix}_chikou_bull":  chikou_bull,
            f"ichi_{prefix}_tk_cross_up":  tk_cross_up,
            f"ichi_{prefix}_tk_cross_dn":  tk_cross_down,
            f"ichi_{prefix}_twist_ahead":  twist_ahead,
        }

    def compute_dao_gam(self, df: pd.DataFrame, label: str) -> dict:
        """
        Dao Găm (Trịnh Phát): MA(65) và MA(129) — hỗ trợ/kháng cự trung-dài hạn.
        Uy lực hơn khi đi ngang ("phẳng"). Kèm cờ `reliable` — False nếu số nến
        có sẵn ở khung này chưa đủ để MA phản ánh đúng chu kỳ (VD: MA129 Tháng
        cần ~129 tháng ≈ 10.75 năm dữ liệu ngày, thường không đủ với lookback mặc định).
        """
        prefix = label.lower()
        if df is None or len(df) < 5:
            return {
                f"dg_{prefix}_65": 0.0, f"dg_{prefix}_129": 0.0,
                f"dg_{prefix}_65_flat": False, f"dg_{prefix}_129_flat": False,
                f"dg_{prefix}_65_reliable": False, f"dg_{prefix}_129_reliable": False,
            }
        c = df["close"]
        dg65  = c.rolling(self.cfg.dao_gam_mid,  min_periods=1).mean()
        dg129 = c.rolling(self.cfg.dao_gam_long, min_periods=1).mean()

        def _is_flat(s: pd.Series) -> bool:
            if len(s) < 5: return False
            w = s.tail(5)
            return bool((w.max()-w.min())/w.mean() < 0.015) if w.mean() else False

        return {
            f"dg_{prefix}_65":  round(float(dg65.iloc[-1]), 2),
            f"dg_{prefix}_129": round(float(dg129.iloc[-1]), 2),
            f"dg_{prefix}_65_flat":  _is_flat(dg65),
            f"dg_{prefix}_129_flat": _is_flat(dg129),
            f"dg_{prefix}_65_reliable":  bool(len(df) >= self.cfg.dao_gam_mid),
            f"dg_{prefix}_129_reliable": bool(len(df) >= self.cfg.dao_gam_long),
        }

    def compute_all_tf(self, df_daily: pd.DataFrame) -> dict:
        result = {}
        result.update(self.compute_ichi(df_daily, "D"))
        result.update(self.compute_dao_gam(df_daily, "D"))          # NEW

        try:
            df_w = resample_ohlcv(df_daily, "W-FRI")
            result.update(self.compute_ichi(df_w, "W"))
            result.update(self.compute_dao_gam(df_w, "W"))          # NEW
        except Exception:
            print('Fail tính Ichi khung weekly')
            result.update(self._ichi_defaults("W"))
            result.update(self.compute_dao_gam(None, "W"))          # NEW

        try:
            df_m = resample_ohlcv(df_daily, "ME")
            result.update(self.compute_ichi(df_m, "M"))
            result.update(self.compute_dao_gam(df_m, "M"))          # NEW
        except Exception:
            result.update(self._ichi_defaults("M"))
            result.update(self.compute_dao_gam(None, "M"))          # NEW

        result.update(self._multi_tf_summary(result, df_daily))
        return result

    def _multi_tf_summary(self, r: dict, df: pd.DataFrame) -> dict:
        """
        Tổng hợp tín hiệu 3 khung → IchiScore + vùng hỗ trợ/kháng cự tổng hợp.

        Trịnh Phát style:
        - Điểm mua mạnh khi ≥2 khung: giá trên mây, Tenkan > Kijun, Chikou Bull
        - Vùng kháng cự = cloud_top gần nhất (D → W → M theo thứ tự ưu tiên)
        - Vùng hỗ trợ  = Kijun-sen gần nhất (D → W → M)
        """
        close = float(df["close"].iloc[-1])

        # Đếm số khung đồng thuận
        above_count = sum([
            r.get("ichi_d_above_cloud", False),
            r.get("ichi_w_above_cloud", False),
            r.get("ichi_m_above_cloud", False),
        ])

        below_count = sum([
            r.get("ichi_d_below_cloud", False),
            r.get("ichi_w_below_cloud", False),
            r.get("ichi_m_below_cloud", False),
        ])

        chikou_count = sum([
            r.get("ichi_d_chikou_bull", False),
            r.get("ichi_w_chikou_bull", False),
            r.get("ichi_m_chikou_bull", False),
        ])

        tk_cross_up = any([
            r.get("ichi_d_tk_cross_up", False),
            r.get("ichi_w_tk_cross_up", False),
        ])

        cloud_bull_count = sum([
            r.get("ichi_d_cloud_bull", False),
            r.get("ichi_w_cloud_bull", False),
            r.get("ichi_m_cloud_bull", False),
        ])

        # IchiScore (0–10)
        # Logic: điểm đầy đủ khi 3 khung đều bullish + Tenkan cắt lên Kijun
        ichi_score = 5.0  # neutral baseline

        if above_count == 3:
            ichi_score = 9.0
        elif above_count == 2:
            ichi_score = 7.5
        elif above_count == 1:
            ichi_score = 6.0
        elif below_count == 3:
            ichi_score = 1.0
        elif below_count == 2:
            ichi_score = 2.5
        elif below_count == 1:
            ichi_score = 3.5
        # Nếu kẹt trong mây cả 3 khung
        else:
            ichi_score = 4.0

        # Bonus từ Chikou và TK cross
        if chikou_count >= 2:
            ichi_score = min(10.0, ichi_score + 1.0)
        if tk_cross_up:
            ichi_score = min(10.0, ichi_score + 1.5)
        if cloud_bull_count >= 2:
            ichi_score = min(10.0, ichi_score + 0.5)

        # Twist sắp đến → cảnh báo
        twist_warning = any([
            r.get("ichi_d_twist_ahead", False),
            r.get("ichi_w_twist_ahead", False),
        ])

        # Vùng hỗ trợ Ichimoku (ưu tiên: Kijun D → W → M)
        # Lấy giá trị Kijun gần close nhất (dưới hoặc bằng close)
        kijun_candidates = [
            r.get("ichi_d_kijun", 0),
            r.get("ichi_w_kijun", 0),
            r.get("ichi_m_kijun", 0),
        ]
        cloud_bot_candidates = [
            r.get("ichi_d_cloud_bot", 0),
            r.get("ichi_w_cloud_bot", 0),
            r.get("ichi_m_cloud_bot", 0),
        ]

        # Hỗ trợ Ichimoku = Kijun cao nhất dưới close
        ichi_supports = sorted(
            [v for v in kijun_candidates + cloud_bot_candidates if 0 < v < close],
            reverse=True
        )
        ichi_sup1 = ichi_supports[0] if len(ichi_supports) > 0 else 0
        ichi_sup2 = ichi_supports[1] if len(ichi_supports) > 1 else 0

        # Kháng cự Ichimoku = cloud_top / Kijun thấp nhất trên close
        cloud_top_candidates = [
            r.get("ichi_d_cloud_top", 0),
            r.get("ichi_w_cloud_top", 0),
            r.get("ichi_m_cloud_top", 0),
        ]
        ichi_res_candidates = sorted(
            [v for v in cloud_top_candidates + kijun_candidates if v > close * 1.005],
            reverse=False
        )
        ichi_res1 = ichi_res_candidates[0] if len(ichi_res_candidates) > 0 else 0
        ichi_res2 = ichi_res_candidates[1] if len(ichi_res_candidates) > 1 else 0

        # Label tổng hợp
        if above_count == 3 and tk_cross_up:
            ichi_label = "☁️✅ Trên mây 3TF + TK cắt lên — MUA MẠNH"
        elif above_count == 3:
            ichi_label = "☁️✅ Trên mây 3TF — Uptrend vững"
        elif above_count == 2:
            ichi_label = "☁️🟡 Trên mây 2TF — Tích cực"
        elif above_count == 1:
            ichi_label = "☁️⚠ Trên mây 1TF — Yếu, cẩn thận"
        elif below_count >= 2:
            ichi_label = "☁️🔴 Dưới mây — Downtrend"
        else:
            ichi_label = "☁️⬜ Trong mây — Tích lũy / chờ"

        print(ichi_label)
        return {
            "ichi_score":        round(min(10.0, max(0.0, ichi_score)), 2),
            "ichi_above_count":  above_count,
            "ichi_below_count":  below_count,
            "ichi_chikou_count": chikou_count,
            "ichi_cloud_bull":   cloud_bull_count,
            "ichi_tk_cross_up":  tk_cross_up,
            "ichi_twist_warn":   twist_warning,
            "ichi_sup1":         round(ichi_sup1, 2),   # hỗ trợ gần nhất
            "ichi_sup2":         round(ichi_sup2, 2),   # hỗ trợ tiếp theo
            "ichi_res1":         round(ichi_res1, 2),   # kháng cự gần nhất
            "ichi_res2":         round(ichi_res2, 2),   # kháng cự tiếp theo
            "ichi_label":        ichi_label,
        }

    @staticmethod
    def _ichi_defaults(label: str) -> dict:
        p = label.lower()
        return {
            f"ichi_{p}_tenkan":0.0,f"ichi_{p}_kijun":0.0,
            f"ichi_{p}_span_a":0.0,f"ichi_{p}_span_b":0.0,
            f"ichi_{p}_cloud_top":0.0,f"ichi_{p}_cloud_bot":0.0,
            f"ichi_{p}_above_cloud":False,f"ichi_{p}_below_cloud":False,
            f"ichi_{p}_inside_cloud":False,f"ichi_{p}_cloud_bull":False,
            f"ichi_{p}_chikou_bull":False,f"ichi_{p}_tk_cross_up":False,
            f"ichi_{p}_tk_cross_dn":False,f"ichi_{p}_twist_ahead":False,
        }


# ═════ [source cell 11] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 3. MOMENTUM ENGINE  [PR011 — uses FeatureEngine cache for BB/MACD]
# ══════════════════════════════════════════════════════════════════

class MomentumEngine:
    """
    Feature Engineering tách biệt — tính toán TRƯỚC, truyền kết quả
    vào dict raw để SignalBuilder chỉ cần đọc, không tính lại.

    Đúng với nguyên tắc Separation of Concerns:
    - MomentumEngine  = Data Processor / Feature Engineer
    - SignalBuilder   = Decision Maker (chỉ đọc raw, ra quyết định)

    4 nhóm tính năng:
    Phase 1A: Bollinger Bands + BB Squeeze
    Phase 1B: RSI Divergence (bull / bear)
    Phase 1C: MACD Histogram Divergence
    Phase 1D: Volume Dry-up + Hidden Accumulation
    """

    def __init__(self, cfg: QuantConfig):
        self.cfg = cfg

    def compute(self, df: pd.DataFrame, raw: dict, feature_cache: dict = None) -> dict:
        """
        Nhận DataFrame OHLCV và dict raw hiện tại.
        feature_cache (từ FeatureEngine.build) — tái sử dụng BB / MACD nếu có.
        Trả về dict raw được bổ sung các features mới.
        """
        r = dict(raw)
        fc = feature_cache or {}

        try: r.update(self._bollinger(df, fc))
        except Exception: r.update(self._bb_defaults())
        try: r.update(self._rsi_divergence(df, r))
        except Exception: r.update({"rsi_bull_div":False,"rsi_bear_div":False,"rsi_bull_strength":0.0,"rsi_bear_strength":0.0})
        try: r.update(self._macd_divergence(df, fc))
        except Exception: r.update({"macd_bull_div":False,"macd_bear_div":False,"macd_bull_strength":0.0,"macd_bear_strength":0.0})
        try: r.update(self._volume_context(df, r))
        except Exception: r.update({"vol_dry_up":False,"vol_spike":False,"hidden_accum":False,"cmf_rising":False})
        r["momentum_signal"] = self._summarize(r)
        return r

    # ── Phase 1A: Bollinger Bands + Squeeze ──────────────────────
    def _bollinger(self, df: pd.DataFrame, feature_cache: dict = None) -> dict:
        """
        BB Squeeze: khi dải băng co hẹp lại → sắp có cú nổ lớn.
        Dùng FeatureEngine cache (bb_mid/upper/lower/std) nếu có.
        """
        c   = df["close"]
        p   = self.cfg.bb_period
        std = self.cfg.bb_std
        lb  = self.cfg.squeeze_lookback
        pct = self.cfg.squeeze_pct
        fc  = feature_cache or {}

        if "bb_mid" in fc and "bb_upper" in fc and "bb_lower" in fc and "bb_std" in fc:
            sma   = fc["bb_mid"]
            upper = fc["bb_upper"]
            lower = fc["bb_lower"]
            sigma = fc["bb_std"]
        else:
            sma   = c.rolling(p).mean()
            sigma = c.rolling(p).std()
            upper = sma + std * sigma
            lower = sma - std * sigma

        mid_safe = sma.replace(0, np.nan)
        bw    = (upper - lower) / mid_safe

        bw_now  = float(bw.iloc[-1]) if not np.isnan(bw.iloc[-1]) else 0.05
        bw_hist = bw.dropna().tail(lb)
        pct_val = float(np.percentile(bw_hist, pct)) if len(bw_hist) >= 10 else bw_now * 1.5

        is_squeeze = bool(bw_now < pct_val)

        rng   = (upper - lower).iloc[-1]
        bb_b  = float((c.iloc[-1] - lower.iloc[-1]) / rng) if rng > 1e-9 else 0.5

        bw_5ago      = float(bw.dropna().iloc[-6]) if len(bw.dropna()) >= 6 else bw_now
        bw_expanding = bool(bw_now > bw_5ago * 1.05)

        return {
            "bb_upper":       round(float(upper.iloc[-1]), 2),
            "bb_mid":         round(float(sma.iloc[-1]), 2),
            "bb_lower":       round(float(lower.iloc[-1]), 2),
            "bb_bandwidth":   round(bw_now, 4),
            "bb_bandwidth_pct_threshold": round(pct_val, 4),
            "is_bb_squeeze":  is_squeeze,
            "bb_pctb":        round(bb_b, 4),
            "bb_expanding":   bw_expanding,
        }

    # ── Phase 1B: RSI Divergence ──────────────────────────────────
    def _rsi_divergence(self, df: pd.DataFrame, raw: dict) -> dict:
        """
        Thuật toán tìm phân kỳ RSI bằng fractal swing lows/highs.

        Fractal Swing Low: nến có low thấp hơn N nến hai bên.
        N = div_lookback (mặc định 5) — nghĩa là thấp hơn 5 nến trái và phải.

        Bullish Divergence (Phân kỳ dương):
          Giá tạo Lower Low (đáy sau thấp hơn đáy trước)
          NHƯNG RSI tại đáy sau cao hơn RSI tại đáy trước
          → Lực bán đang cạn dần, khả năng đảo chiều tăng cao

        Bearish Divergence (Phân kỳ âm):
          Giá tạo Higher High (đỉnh sau cao hơn đỉnh trước)
          NHƯNG RSI tại đỉnh sau thấp hơn RSI tại đỉnh trước
          → Momentum suy yếu dù giá vẫn tăng, cảnh báo đảo chiều xuống
        """
        c  = df["close"]
        l  = df["low"]
        h  = df["high"]
        lb = self.cfg.div_lookback

        # Tính RSI14 (dùng lại nếu đã có trong raw)
        rsi_val = raw.get("rsi", None)
        delta   = c.diff()
        gain    = delta.clip(lower=0).rolling(14).mean()
        loss    = (-delta.clip(upper=0)).rolling(14).mean()
        rsi_s   = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

        # Tìm swing lows trong 40 phiên gần nhất
        sl_idx = self._find_swing_lows(l, lookback=40, wing=lb)
        # Tìm swing highs
        sh_idx = self._find_swing_highs(h, lookback=40, wing=lb)

        bull_div = False
        bear_div = False
        bull_strength = 0.0   # mức độ phân kỳ (RSI gap)
        bear_strength = 0.0

        # ── Bullish Divergence: dùng 2 swing low gần nhất ───────
        if len(sl_idx) >= 2:
            i2, i1 = sl_idx[-1], sl_idx[-2]   # i2 mới hơn
            price_ll = bool(float(l.iloc[i2]) < float(l.iloc[i1]))
            rsi_hl   = bool(float(rsi_s.iloc[i2]) > float(rsi_s.iloc[i1]))
            if price_ll and rsi_hl:
                bull_div = True
                bull_strength = round(float(rsi_s.iloc[i2]) - float(rsi_s.iloc[i1]), 2)

        # ── Bearish Divergence: dùng 2 swing high gần nhất ──────
        if len(sh_idx) >= 2:
            j2, j1 = sh_idx[-1], sh_idx[-2]   # j2 mới hơn
            price_hh = bool(float(h.iloc[j2]) > float(h.iloc[j1]))
            rsi_lh   = bool(float(rsi_s.iloc[j2]) < float(rsi_s.iloc[j1]))
            if price_hh and rsi_lh:
                bear_div = True
                bear_strength = round(float(rsi_s.iloc[j1]) - float(rsi_s.iloc[j2]), 2)

        return {
            "rsi_bull_div":      bull_div,
            "rsi_bear_div":      bear_div,
            "rsi_bull_strength": bull_strength,   # RSI gap dương → mạnh hơn nếu lớn
            "rsi_bear_strength": bear_strength,
        }

    # ── Phase 1C: MACD Histogram Divergence ──────────────────────
    def _macd_divergence(self, df: pd.DataFrame, feature_cache: dict = None) -> dict:
        """
        MACD Histogram divergence — dùng macd_hist từ FeatureEngine cache nếu có.
        """
        c   = df["close"]
        l   = df["low"]
        h   = df["high"]
        lb  = self.cfg.div_lookback
        fc  = feature_cache or {}

        if "macd_hist" in fc:
            mh = fc["macd_hist"]
        else:
            ema12 = c.ewm(span=12, adjust=False).mean()
            ema26 = c.ewm(span=26, adjust=False).mean()
            ml    = ema12 - ema26
            ms    = ml.ewm(span=9, adjust=False).mean()
            mh    = ml - ms

        sl_idx = self._find_swing_lows(l, lookback=40, wing=lb)
        sh_idx = self._find_swing_highs(h, lookback=40, wing=lb)

        bull_div = False
        bear_div = False
        bull_strength = 0.0
        bear_strength = 0.0

        if len(sl_idx) >= 2:
            i2, i1 = sl_idx[-1], sl_idx[-2]
            price_ll  = bool(float(l.iloc[i2]) < float(l.iloc[i1]))
            macd_hl   = bool(float(mh.iloc[i2]) > float(mh.iloc[i1]))
            if price_ll and macd_hl:
                bull_div      = True
                bull_strength = round(float(mh.iloc[i2]) - float(mh.iloc[i1]), 6)

        if len(sh_idx) >= 2:
            j2, j1 = sh_idx[-1], sh_idx[-2]
            price_hh  = bool(float(h.iloc[j2]) > float(h.iloc[j1]))
            macd_lh   = bool(float(mh.iloc[j2]) < float(mh.iloc[j1]))
            if price_hh and macd_lh:
                bear_div      = True
                bear_strength = round(float(mh.iloc[j1]) - float(mh.iloc[j2]), 6)

        return {
            "macd_bull_div":      bull_div,
            "macd_bear_div":      bear_div,
            "macd_bull_strength": bull_strength,
            "macd_bear_strength": bear_strength,
        }

    # ── Phase 1D: Volume Context ──────────────────────────────────
    def _volume_context(self, df: pd.DataFrame, raw: dict) -> dict:
        """
        Volume Dry-up: 3 phiên gần nhất có volume < 50% trung bình 20 phiên.
        Đây là tín hiệu cạn cung — người bán đã mệt, không còn ai muốn bán nữa.
        Kết hợp với BB Squeeze hoặc bull divergence = setup mua rất an toàn.

        Hidden Accumulation: Giá đi ngang/giảm nhẹ nhưng CMF đang dốc lên dương.
        Ai đó đang gom hàng ngầm mà không đẩy giá lên để tránh thu hút chú ý.
        """
        v    = df["volume"]
        c    = df["close"]

        vol_ma20 = v.rolling(20).mean()
        vol_ma3  = v.rolling(3).mean()

        # Tránh ZeroDivisionError
        ma20_last = float(vol_ma20.iloc[-1])
        ma3_last  = float(vol_ma3.iloc[-1])

        vol_dry_up = bool(ma20_last > 1e-9 and ma3_last < ma20_last * 0.50)

        # Vol spike: ngày hôm nay đột biến
        vol_spike = bool(ma20_last > 1e-9 and float(v.iloc[-1]) > ma20_last * 2.0)

        # Hidden accumulation: giá sideway/giảm nhưng CMF tăng dương
        cmf_now  = float(raw.get("cmf", 0))
        price_5d = float(c.iloc[-1]) - float(c.iloc[-6]) if len(c) >= 6 else 0
        price_flat_or_down = price_5d <= float(c.iloc[-1]) * 0.01   # ±1%
        hidden_accum = bool(price_flat_or_down and cmf_now > 0.05)

        # CMF trend: CMF hiện tại so với 10 phiên trước
        mfv    = ((c-df["low"])-(df["high"]-c)) / (df["high"]-df["low"]+1e-9) * v
        cmf_s  = mfv.rolling(21).sum() / v.rolling(21).sum().replace(0, np.nan)
        cmf_10ago = float(cmf_s.iloc[-11]) if len(cmf_s) >= 11 else cmf_now
        cmf_rising = bool(cmf_now > cmf_10ago + 0.03)   # CMF tăng đáng kể

        return {
            "vol_dry_up":       vol_dry_up,
            "vol_spike":        vol_spike,
            "hidden_accum":     hidden_accum,
            "cmf_rising":       cmf_rising,
        }

    # ── Summary: 1 signal string để log/display ──────────────────
    @staticmethod
    def _summarize(r: dict) -> str:
        """Tổng hợp các tín hiệu momentum thành 1 label ngắn gọn."""
        signals = []
        if r.get("rsi_bull_div"):          signals.append("📈RSI Div+")
        if r.get("macd_bull_div"):         signals.append("📈MACD Div+")
        if r.get("rsi_bear_div"):          signals.append("📉RSI Div-")
        if r.get("macd_bear_div"):         signals.append("📉MACD Div-")
        if r.get("is_bb_squeeze"):         signals.append("🔴BB Squeeze")
        if r.get("bb_expanding"):          signals.append("💥BB Nổ")
        if r.get("vol_dry_up"):            signals.append("💤Vol Cạn")
        if r.get("hidden_accum"):          signals.append("🔍Gom Ngầm")
        if r.get("vol_spike"):             signals.append("🌊Vol Spike")
        return " | ".join(signals) if signals else "—"

    # ── Fractal Swing Finder ──────────────────────────────────────
    @staticmethod
    def _find_swing_lows(series: pd.Series, lookback: int, wing: int) -> list:
        """
        Tìm danh sách index của swing lows trong N phiên gần nhất.
        Swing low: giá trị thấp hơn tất cả `wing` phiên bên trái và bên phải.
        Trả về list index (trong df gốc) được sắp xếp theo thời gian.
        """
        s   = series.tail(lookback).reset_index(drop=True)
        idx = []
        for i in range(wing, len(s) - wing):
            val = s.iloc[i]
            left_ok  = all(val <= s.iloc[i-j] for j in range(1, wing+1))
            right_ok = all(val <= s.iloc[i+j] for j in range(1, wing+1))
            if left_ok and right_ok:
                # Chuyển về index trong df gốc
                idx.append(len(series) - lookback + i)
        return idx

    @staticmethod
    def _find_swing_highs(series: pd.Series, lookback: int, wing: int) -> list:
        s   = series.tail(lookback).reset_index(drop=True)
        idx = []
        for i in range(wing, len(s) - wing):
            val = s.iloc[i]
            left_ok  = all(val >= s.iloc[i-j] for j in range(1, wing+1))
            right_ok = all(val >= s.iloc[i+j] for j in range(1, wing+1))
            if left_ok and right_ok:
                idx.append(len(series) - lookback + i)
        return idx

    # ── Default values (khi exception) ───────────────────────────
    @staticmethod
    def _bb_defaults() -> dict:
        return {
            "bb_upper":0.0,"bb_mid":0.0,"bb_lower":0.0,
            "bb_bandwidth":0.05,"bb_bandwidth_pct_threshold":0.05,
            "is_bb_squeeze":False,"bb_pctb":0.5,"bb_expanding":False,
        }

    @staticmethod
    def _div_defaults(prefix: str) -> dict:
        return {
            f"{prefix}_bull_div":False, f"{prefix}_bear_div":False,
            f"{prefix}_bull_strength":0.0, f"{prefix}_bear_strength":0.0,
        }

    @staticmethod
    def _vol_defaults() -> dict:
        return {
            "vol_dry_up":False,"vol_spike":False,
            "hidden_accum":False,"cmf_rising":False,
        }



# ═════ [source cell 12] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 4. REGIME ENGINE
# ══════════════════════════════════════════════════════════════════

class RegimeEngine:
    def __init__(self, dl: DataLayer):
        self.dl = dl; self._regime="sideways"; self._ctx={}

    def detect(self) -> dict:
        print("  📊 Market Regime...", end=" ", flush=True)
        df = self.dl.fetch("VNINDEX", days=60)
        if df is None or len(df)<30:
            print("⚠ neutral")
            self._regime="sideways"
            self._ctx={"regime":"sideways","label":"⚪ Không xác định",
                       "context_score":5.0,"score_mult":0.95,"mom5":0.0,"vnindex":0.0,"atr_pct":2.0}
            return self._ctx
        c=df["close"]; v=df["volume"]
        ema10=c.ewm(span=10,adjust=False).mean()
        ema30=c.ewm(span=30,adjust=False).mean()
        sma200=c.rolling(200).mean() if len(c)>=200 else ema30
        tr=pd.concat([df["high"]-df["low"],(df["high"]-c.shift()).abs(),(df["low"]-c.shift()).abs()],axis=1).max(axis=1)
        atr_pct=float(tr.rolling(14).mean().iloc[-1]/c.iloc[-1]*100)
        trend_up=ema10.iloc[-1]>ema30.iloc[-1]
        above200=c.iloc[-1]>sma200.iloc[-1]
        mom5=(c.iloc[-1]-c.iloc[-6])/c.iloc[-6]*100 if len(c)>=6 else 0.0
        d=c.diff(); g=d.clip(lower=0).rolling(14).mean(); ls=(-d.clip(upper=0)).rolling(14).mean()
        vni_rsi=float((100-100/(1+g/ls.replace(0,np.nan))).iloc[-1])
        if atr_pct>2.5 and mom5<-2.0:          regime,label,ctx="panic",   "🔴 PANIC",                1.5
        elif not trend_up and mom5<-1.0:        regime,label,ctx="bear",    "🔴 Downtrend",             2.5
        elif trend_up and above200 and mom5>1.0:regime,label,ctx="bull",    "🟢 Uptrend — thuận mua",  8.0
        elif trend_up and mom5>-1.0:            regime,label,ctx="sideways","🟡 Uptrend nghỉ",          6.0
        else:                                   regime,label,ctx="sideways","🟡 Sideways",              4.5
        mult=REGIME_SCORE_MULT[regime]
        print(f"✓  [{regime.upper()}]  {c.iloc[-1]:,.2f}  |  {label}  5d:{mom5:+.1f}% ATR:{atr_pct:.1f}%")
        self._regime=regime
        self._ctx={"regime":regime,"label":label,"context_score":ctx,"score_mult":mult,
                   "mom5":round(mom5,2),"vnindex":round(float(c.iloc[-1]),2),
                   "atr_pct":round(atr_pct,2),"vni_rsi":round(vni_rsi,1)}
        return self._ctx

    def dynamic_weights(self) -> dict:
        w=dict(BASE_WEIGHTS)
        for k,d in REGIME_WEIGHT_DELTA.get(self._regime,{}).items():
            if k in w: w[k]=max(0,w[k]+d)
        total=sum(w.values()) or 1
        return {k:round(v/total*100,1) for k,v in w.items()}

    def min_score(self, mode: str, cfg: QuantConfig) -> float:
        base=cfg.min_score_swing if mode=="swing" else cfg.min_score_hold
        ctx=self._ctx.get("context_score",5.0)
        if ctx>=7.0: return base
        elif ctx>=5.0: return base+0.5
        elif ctx>=3.5: return base+1.0
        else: return base+1.5

    @property
    def regime(self): return self._regime
    @property
    def ctx(self): return self._ctx


# ═════ [source cell 13] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 5. FUNDAMENTAL ENGINE
# ══════════════════════════════════════════════════════════════════
import numpy as np
import pandas as pd
from typing import Tuple, Optional
from vnstock import Fundamental

class FundamentalEngine:
    def __init__(self):
        self._cache: dict = {}
        self._fun = Fundamental()

    def score(self, symbol: str) -> Tuple[float, str]:
        if symbol in self._cache:
            return self._cache[symbol]
        try:
            # 1. Gọi hàm lấy chỉ số mặc định (dạng bảng giống bạn vừa print)
            df = self._fun.equity(symbol).ratio(period="quarter")

            if df is None or df.empty:
                raise ValueError("Bảng dữ liệu trống hoặc không hợp lệ")

            # 2. Đặt 'item_id' làm index để gọi chính xác dòng dữ liệu mong muốn
            df = df.set_index("item_id")

            # 3. Tìm cột Quý gần đây nhất (Lọc các cột chứa từ khóa '-Q' và xếp từ mới đến cũ)
            quarter_cols = [str(col) for col in df.columns if "-Q" in str(col)]
            if not quarter_cols:
                raise ValueError("Không tìm thấy cột dữ liệu báo cáo theo Quý")

            quarter_cols.sort(reverse=True)
            latest_col = quarter_cols[0]  # Kết quả sẽ là kỳ mới nhất, ví dụ: '2026-Q1'

            # 4. Trích xuất an toàn các chỉ số PE, PB, ROE, ROA, EPS từ item_id của kỳ mới nhất
            pe = self._get_val(df, "pe_ratio", latest_col)
            pb = self._get_val(df, "pb_ratio", latest_col)

            # Lấy ROE / ROA (Ưu tiên bản tính trượt trailling 4 quý gần nhất cho chính xác)
            roe = self._get_val(df, "roe_trailling", latest_col) or self._get_val(df, "roe", latest_col)
            roa = self._get_val(df, "roa_trailling", latest_col) or self._get_val(df, "roa", latest_col)
            eps = self._get_val(df, "trailing_eps", latest_col)

            # 5. Tiến hành chấm điểm dựa trên các thông số đã bóc tách
            s = 0
            if pe:
                if pe < 8: s += 2.5
                elif pe < 12: s += 1.5
                elif pe < 18: s += 0.5
                elif pe > 30: s -= 2.0
            if roe:
                # Vnstock mới trả về dạng % sẵn (ví dụ FPT là 27.23), giữ nguyên logic của bạn
                rv = roe * 100 if roe < 1 else roe
                if rv > 20: s += 2.5
                elif rv > 15: s += 1.5
                elif rv > 10: s += 0.5
                elif rv < 8: s -= 1.5
            if pb:
                if pb < 1.2: s += 1.5
                elif pb < 2.0: s += 0.5
                elif pb > 4.0: s -= 1.5
            if eps and eps > 0: s += 1.0

            fs = round(min(max(s, 0.0), 10.0), 1)

            # Định dạng chuỗi summary hiển thị ra màn hình lọc (Đã thêm ROA)
            parts = [
                f"P/E:{pe:.1f}" if pe else "",
                f"P/B:{pb:.1f}" if pb else "",
                f"ROE:{roe:.1f}%" if roe else "",
                f"ROA:{roa:.1f}%" if roa else ""
            ]
            summary = " | ".join(p for p in parts if p) or "—"
            result = (fs, summary)

        except Exception as e:
            print(f"Lỗi chấm điểm mã {symbol}: {e}")
            result = (5.0, "—")

        self._cache[symbol] = result
        return result

    @staticmethod
    def _get_val(df: pd.DataFrame, item_id: str, col: str) -> Optional[float]:
        """Hàm bổ trợ bóc tách và ép kiểu dữ liệu an toàn từ Index của Vnstock"""
        if item_id in df.index:
            try:
                val = pd.to_numeric(df.loc[item_id, col], errors='coerce')
                # Phòng trường hợp index bị trùng lặp dòng ngoài ý muốn
                if isinstance(val, pd.Series):
                    val = val.iloc[0]
                if not np.isnan(val) and val != 0:
                    return float(val)
            except:
                pass
        return None


# ═════ [source cell 14] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# FEATURE ENGINE  [PR010 — shared indicator cache]
# ══════════════════════════════════════════════════════════════════
class FeatureEngine:
    """
    Tính một lần các chỉ báo dùng chung (EMA / ATR / RSI / MACD …)
    rồi cache vào dict. IndicatorEngine chỉ đọc cache, không tính lại.

    Cách dùng:
        cache = FeatureEngine.build(df)
        raw   = IndicatorEngine.compute_all(df, vp, trend, rs, mf, feature_cache=cache)
    """

    # ── primitives ──────────────────────────────────────────────
    @staticmethod
    def ema(series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(period, min_periods=1).mean()

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        c = df["close"]
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - c.shift()).abs(),
            (df["low"]  - c.shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period, min_periods=1).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        d = series.diff()
        g = d.clip(lower=0).rolling(period, min_periods=1).mean()
        l = (-d.clip(upper=0)).rolling(period, min_periods=1).mean()
        return 100 - 100 / (1 + g / l.replace(0, np.nan))

    @staticmethod
    def macd(series: pd.Series, fast=12, slow=26, signal=9):
        ema_f = FeatureEngine.ema(series, fast)
        ema_s = FeatureEngine.ema(series, slow)
        line  = ema_f - ema_s
        sig   = FeatureEngine.ema(line, signal)
        hist  = line - sig
        return line, sig, hist

    @staticmethod
    def stoch(df: pd.DataFrame, k_period=14, d_period=3):
        l = df["low"].rolling(k_period, min_periods=1).min()
        h = df["high"].rolling(k_period, min_periods=1).max()
        k = (df["close"] - l) / (h - l + 1e-9) * 100
        d = k.rolling(d_period, min_periods=1).mean()
        return k, d

    # ── build full cache ────────────────────────────────────────
    @staticmethod
    def build(df: pd.DataFrame) -> dict:
        """
        Compute all shared indicators once.
        Returns dict of Series (and a few scalars) ready for IndicatorEngine.
        """
        if df is None or len(df) < 5:
            return {}

        c = df["close"]
        cache = {
            # EMA family
            "ema5":   FeatureEngine.ema(c, 5),
            "ema12":  FeatureEngine.ema(c, 12),
            "ema20":  FeatureEngine.ema(c, 20),
            "ema26":  FeatureEngine.ema(c, 26),
            "ema50":  FeatureEngine.ema(c, 50),
            # SMA
            "sma20":  FeatureEngine.sma(c, 20),
            "sma50":  FeatureEngine.sma(c, 50),
            "ma9":    FeatureEngine.sma(c, 9),
            "ma10":   FeatureEngine.sma(c, 10),
            # Volatility
            "atr14":  FeatureEngine.atr(df, 14),
            # Momentum
            "rsi14":  FeatureEngine.rsi(c, 14),
        }

        # MACD
        ml, ms, mh = FeatureEngine.macd(c)
        cache["macd_line"] = ml
        cache["macd_sig"]  = ms
        cache["macd_hist"] = mh

        # Stochastic
        sk, sd = FeatureEngine.stoch(df)
        cache["stoch_k"] = sk
        cache["stoch_d"] = sd

        # Bollinger (for reuse by MomentumEngine later)
        mid = cache["sma20"]
        std = c.rolling(20, min_periods=1).std()
        cache["bb_mid"]   = mid
        cache["bb_upper"] = mid + 2 * std
        cache["bb_lower"] = mid - 2 * std
        cache["bb_std"]   = std

        return cache


# ══════════════════════════════════════════════════════════════════
# 6. INDICATOR ENGINE  [PR010 — uses FeatureEngine cache]
# ══════════════════════════════════════════════════════════════════

class IndicatorEngine:
    @staticmethod
    def volume_profile(df: pd.DataFrame, n_bins: int = 18) -> dict:
        if len(df) < 25:
            return {"poc": None, "vah": None, "val": None, "vp_signal": "unknown"}
        try:
            df2 = df.copy()
            df2["tp"] = (df2["high"] + df2["low"] + df2["close"]) / 3
            lo, hi = df2["low"].min(), df2["high"].max()
            rng = hi - lo
            if rng < 0.1:
                return {"poc": round(df2["close"].mean(), 2), "vah": None, "val": None, "vp_signal": "unknown"}
            actual = min(60, max(18, int(rng / 0.15)))
            edges = np.linspace(lo, hi, actual + 1)
            df2["bin"] = pd.cut(df2["tp"], bins=edges, labels=edges[:-1], include_lowest=True, right=False)
            vp = df2.groupby("bin", observed=True)["volume"].sum()
            poc = float(vp.idxmax())
            srt = vp.sort_values(ascending=False)
            va = srt[srt.cumsum() <= vp.sum() * 0.70].index
            vah = float(va.max()) if len(va) else poc
            val = float(va.min()) if len(va) else poc
            cur = float(df["close"].iloc[-1])
            if cur > vah * 1.008:
                sig = "breakout"
            elif cur < val * 0.992:
                sig = "below_value"
            elif abs(cur - poc) / poc < 0.015:
                sig = "at_poc"
            else:
                sig = "value_area"
            return {"poc": round(poc, 2), "vah": round(vah, 2), "val": round(val, 2), "vp_signal": sig}
        except Exception:
            return {"poc": None, "vah": None, "val": None, "vp_signal": "unknown"}

    @staticmethod
    def long_trend(df_long: pd.DataFrame) -> dict:
        if df_long is None or len(df_long) < 60:
            return {"trend_long": "sideway", "sma50": None, "sma200": None, "slope": 0.0}
        c = df_long["close"]
        sma50s = c.rolling(50).mean()
        sma200s = c.rolling(200).mean() if len(c) >= 200 else None
        sma50 = float(sma50s.iloc[-1])
        sma200 = float(sma200s.iloc[-1]) if sma200s is not None else None
        close = float(c.iloc[-1])
        ema20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
        s50_20 = sma50s.tail(20)
        slope = float((s50_20.iloc[-1] - s50_20.iloc[0]) / s50_20.iloc[0] * 100) if len(s50_20) >= 10 else 0.0
        if sma200:
            if close > sma50 > sma200 and slope > 0.5:
                t = "uptrend"
            elif close > sma50 > sma200:
                t = "weak_up"
            elif close < sma50 < sma200 and slope < -0.3:
                t = "downtrend"
            elif close < sma50 < sma200:
                t = "weak_down"
            elif abs(close - sma50) / sma50 < 0.015 and ema20 > sma50:
                t = "weak_up"
            else:
                t = "sideway"
        else:
            t = "weak_up" if close > sma50 and slope > 0.5 else (
                "weak_down" if close < sma50 and slope < -0.5 else "sideway"
            )
        return {
            "trend_long": t,
            "sma50": round(sma50, 2),
            "sma200": round(sma200, 2) if sma200 else None,
            "slope": round(slope, 2),
        }

    @staticmethod
    def relative_strength(df_stk, df_vni, period: int = 20) -> float:
        if df_stk is None or df_vni is None:
            return 1.0
        if len(df_stk) < period or len(df_vni) < period:
            return 1.0
        try:
            cs, cv = df_stk["close"], df_vni["close"]
            r_s = (cs.iloc[-1] / cs.iloc[-period]) - 1
            r_v = (cv.iloc[-1] / cv.iloc[-period]) - 1
            rs_raw = (1 + r_s) / (1 + r_v) if abs(1 + r_v) > 1e-5 else 1 + r_s * 5
            es = cs.ewm(span=10, adjust=False).mean()
            ev = cv.ewm(span=10, adjust=False).mean()
            b_s = cs.iloc[-period]
            b_v = cv.iloc[-period]
            rs_ema = (
                (es.iloc[-1] / b_s) / (ev.iloc[-1] / b_v)
                if b_s > 0 and b_v > 0 and ev.iloc[-1] / b_v > 1e-5
                else rs_raw
            )
            return float(max(0.2, min(4.0, round(0.7 * rs_raw + 0.3 * rs_ema, 2))))
        except Exception:
            return 1.0

    @staticmethod
    def inst_money_flow(df: pd.DataFrame) -> dict:
        """Institutional / smart money heuristics — original logic preserved."""
        if df is None or len(df) < 25:
            return {"inst_flow": 5.0, "inst_up": False, "smart": False,
                    "b_acc": False, "b_brk": False, "mf_label": "—"}
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        clv = ((c - l) - (h - c)) / (h - l + 1e-9)
        ad = (clv * v).cumsum()
        inst_up = bool(
            ad.ewm(span=5, adjust=False).mean().iloc[-1]
            > ad.ewm(span=20, adjust=False).mean().iloc[-1]
        )
        ad_roc = (
            float((ad.iloc[-1] - ad.iloc[-6]) / (v.rolling(20).mean().iloc[-1] * 5 + 1e-9))
            if len(df) >= 6 else 0
        )
        if inst_up and ad_roc > 0.3:
            inst_score = 9.0
        elif inst_up and ad_roc > 0:
            inst_score = 7.0
        elif inst_up:
            inst_score = 5.5
        elif ad_roc > 0:
            inst_score = 4.0
        else:
            inst_score = 2.0
        cs5 = float(clv.rolling(5).mean().iloc[-1])
        cs20 = float(clv.rolling(20).mean().iloc[-1])
        smart = bool(cs5 > cs20 and cs5 > 0.4)
        vol_ma = v.rolling(20).mean()
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        vr = v / (vol_ma + 1e-9)
        hl_r = (h - l) / (atr + 1e-9)
        b_acc = bool(vr.iloc[-1] > 2.0 and hl_r.iloc[-1] < 1.5 and c.iloc[-1] > c.iloc[-2])
        b_brk = bool(vr.iloc[-1] > 2.5 and (c.iloc[-1] - c.iloc[-2]) / (c.iloc[-2] + 1e-9) > 0.01)
        n = sum([inst_up, smart, b_acc or b_brk])
        if b_brk:
            lbl = "🏦 Tổ chức đẩy"
        elif b_acc:
            lbl = "🔍 Tích lũy ngầm"
        elif n >= 2:
            lbl = "💰 Tiền lớn vào"
        elif n == 1:
            lbl = "🔄 Trung tính"
        else:
            lbl = "📤 Tiền lớn rút"
        return {
            "inst_flow": inst_score,
            "inst_up": inst_up,
            "smart": smart,
            "b_acc": b_acc,
            "b_brk": b_brk,
            "mf_label": lbl,
        }

    @staticmethod
    def compute_all(
        df: pd.DataFrame,
        vp: dict,
        trend: dict,
        rs: float,
        mf: dict,
        feature_cache: dict = None,
    ) -> dict:
        """
        Build the full raw indicator dict.
        If feature_cache (from FeatureEngine.build) is provided, reuse EMA/RSI/ATR/MACD/Stoch
        instead of recalculating — same numerical result, less CPU.
        """
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        R = {"close": round(float(c.iloc[-1]), 2), "volume": int(v.iloc[-1])}

        # ── volume ──
        vol_ma20 = v.rolling(20).mean().iloc[-1]
        R["volume_ratio"] = round(float(v.iloc[-1] / (vol_ma20 + 1e-9)), 2)
        R["avg_vol_20d"]  = int(vol_ma20)
        R["avg_val_20d"]  = round(float(vol_ma20 * c.rolling(20).mean().iloc[-1]), 0)

        # ── OBV ──
        obv = (np.sign(c.diff().fillna(0)) * v).cumsum()
        R["obv_signal"] = 1 if obv.rolling(5).mean().iloc[-1] > obv.rolling(20).mean().iloc[-1] else -1
        if len(df) >= 6:
            y = obv.iloc[-6:].values.astype(float)
            sl = float(np.polyfit(np.arange(6, dtype=float), y, 1)[0])
            R["obv_slope"] = round(sl / (abs(float(obv.iloc[-6])) + 1e-9) * 100, 2)
        else:
            R["obv_slope"] = 0.0

        # ── CMF ──
        mfv = ((c - l) - (h - c)) / (h - l + 1e-9) * v
        R["cmf"] = round(float((mfv.rolling(21).sum() / v.rolling(21).sum().replace(0, np.nan)).iloc[-1]), 4)

        # ── Force Index ──
        fi = (c.diff() * v).ewm(span=13, adjust=False).mean()
        fim = fi.abs().rolling(20).mean().iloc[-1]
        R["force_index"] = round(float(fi.iloc[-1]) / (fim + 1e-9), 4)

        for k in ["inst_flow", "inst_up", "smart", "b_acc", "b_brk", "mf_label"]:
            R[k] = mf.get(k)

        # ── helpers to read from cache or compute ──
        fc = feature_cache or {}

        def _last(key, fallback_series):
            if key in fc:
                val = fc[key].iloc[-1]
            else:
                val = fallback_series.iloc[-1]
            return float(val) if not pd.isna(val) else 0.0

        # RSI
        if "rsi14" in fc:
            R["rsi"] = round(float(fc["rsi14"].iloc[-1]), 2)
        else:
            delta = c.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            R["rsi"] = round(float((100 - 100 / (1 + gain / loss.replace(0, np.nan))).iloc[-1]), 2)

        # EMA family
        if "ema20" in fc:
            ema20_val = float(fc["ema20"].iloc[-1])
            ema50_val = float(fc["ema50"].iloc[-1]) if "ema50" in fc else float(c.ewm(span=50, adjust=False).mean().iloc[-1])
            ema5_val  = float(fc["ema5"].iloc[-1])  if "ema5"  in fc else float(c.ewm(span=5,  adjust=False).mean().iloc[-1])
        else:
            ema20_s = c.ewm(span=20, adjust=False).mean()
            ema50_s = c.ewm(span=50, adjust=False).mean()
            ema5_s  = c.ewm(span=5,  adjust=False).mean()
            ema20_val = float(ema20_s.iloc[-1])
            ema50_val = float(ema50_s.iloc[-1])
            ema5_val  = float(ema5_s.iloc[-1])

        R["ema_pct"] = round(float((c.iloc[-1] - ema20_val) / ema20_val * 100), 2)
        R["ema20"]   = round(ema20_val, 2)
        R["ema50"]   = round(ema50_val, 2)
        R["ema5"]    = round(ema5_val, 2)

        # MACD
        if "macd_hist" in fc:
            mh = fc["macd_hist"]
            R["macd_hist_pct"] = round(float(mh.iloc[-1]) / (float(c.iloc[-1]) + 1e-9) * 100, 4)
            R["macd_cross_up"] = bool(len(mh) > 1 and mh.iloc[-1] > 0 and mh.iloc[-2] <= 0)
        else:
            ema12 = c.ewm(span=12, adjust=False).mean()
            ema26 = c.ewm(span=26, adjust=False).mean()
            ml = ema12 - ema26
            ms = ml.ewm(span=9, adjust=False).mean()
            mh = ml - ms
            R["macd_hist_pct"] = round(float(mh.iloc[-1]) / (float(c.iloc[-1]) + 1e-9) * 100, 4)
            R["macd_cross_up"] = bool(len(mh) > 1 and mh.iloc[-1] > 0 and mh.iloc[-2] <= 0)

        # Stochastic
        if "stoch_k" in fc:
            sk = fc["stoch_k"]
            sd = fc["stoch_d"]
            R["stoch_k"] = round(float(sk.iloc[-1]), 2)
            R["stoch_d"] = round(float(sd.iloc[-1]), 2)
            R["stoch_cross_up"] = bool(len(sk) > 1 and sk.iloc[-1] > sd.iloc[-1] and sk.iloc[-2] <= sd.iloc[-2])
        else:
            l14 = l.rolling(14).min()
            h14 = h.rolling(14).max()
            sk = (c - l14) / (h14 - l14 + 1e-9) * 100
            sd = sk.rolling(3).mean()
            R["stoch_k"] = round(float(sk.iloc[-1]), 2)
            R["stoch_d"] = round(float(sd.iloc[-1]), 2)
            R["stoch_cross_up"] = bool(len(sk) > 1 and sk.iloc[-1] > sd.iloc[-1] and sk.iloc[-2] <= sd.iloc[-2])

        # ATR
        if "atr14" in fc:
            atr_val = float(fc["atr14"].iloc[-1])
        else:
            tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
            atr_val = float(tr.rolling(14).mean().iloc[-1])
        R["atr_ratio"] = round(atr_val / (float(c.iloc[-1]) + 1e-9) * 100, 2)
        R["atr_abs"]   = round(atr_val, 2)

        # Bollinger %B
        if "bb_lower" in fc and "bb_std" in fc:
            bb_lo = float(fc["bb_lower"].iloc[-1])
            bb_st = float(fc["bb_std"].iloc[-1])
            R["bb_pctb"] = round(float((c.iloc[-1] - bb_lo) / (4 * bb_st + 1e-9)), 4)
        else:
            sm20 = c.rolling(20).mean()
            st20 = c.rolling(20).std()
            R["bb_pctb"] = round(float((c - (sm20 - 2 * st20)).iloc[-1] / (float(4 * st20.iloc[-1]) + 1e-9)), 4)

        # VP + trend + RS
        R.update({k: vp.get(k) for k in ["vp_signal", "poc", "vah", "val"]})
        R["trend_long"]  = trend.get("trend_long", "sideway")
        R["sma50"]       = trend.get("sma50")
        R["sma200"]      = trend.get("sma200")
        R["slope_sma50"] = trend.get("slope", 0.0)
        R["rs"]          = round(float(rs), 2)

        # MA9 / MA10
        if "ma9" in fc:
            ma9v  = fc["ma9"].iloc[-1]
            ma10v = fc["ma10"].iloc[-1]
            R["ma9"]  = round(float(ma9v), 2)  if not pd.isna(ma9v)  else None
            R["ma10"] = round(float(ma10v), 2) if not pd.isna(ma10v) else None
        else:
            ma9  = c.rolling(9).mean()
            ma10 = c.rolling(10).mean()
            R["ma9"]  = round(float(ma9.iloc[-1]), 2)  if not pd.isna(ma9.iloc[-1])  else None
            R["ma10"] = round(float(ma10.iloc[-1]), 2) if not pd.isna(ma10.iloc[-1]) else None

        return R



# ═════ [source cell 15] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 7. SCORING ENGINE  [UPDATED — Ichimoku integrated, no magic nums]
# ══════════════════════════════════════════════════════════════════

class ScoringEngine:
    def score(self, raw: dict, mode: str, weights: dict,
              regime_mult: float, fund_score: float = 5.0,
              cfg: QuantConfig = None) -> tuple[dict, float]:
        if cfg is None: cfg = QuantConfig()
        def clamp(x): return max(0.0, min(10.0, float(x)))
        s = {}

        # Volume — 3 ngưỡng từ config
        vol = raw.get("volume_ratio", 1.0)
        vl  = cfg.vol_score_low_cap; vm = cfg.vol_score_mid; vh = cfg.vol_score_high
        if   vol <= vl: s["volume_ratio"] = clamp(vol * 4.0)
        elif vol <  vm: s["volume_ratio"] = clamp(3.5 + (vol-vl)/(vm-vl) * 2.5)
        elif vol <  vh: s["volume_ratio"] = clamp(6.0 + (vol-vm)/(vh-vm) * 2.5)
        else:           s["volume_ratio"] = clamp(8.5 + (vol-vh) * 1.2)

        s["cmf"]       = clamp((raw.get("cmf",0) + cfg.cmf_score_offset) / cfg.cmf_score_scale)
        ob             = 7.5 if raw.get("obv_signal") == 1 else 2.5
        s["obv"]       = clamp(ob + min(2.8, max(-2.8, raw.get("obv_slope",0) / cfg.obv_slope_scale)))
        s["force"]     = clamp((raw.get("force_index",0) + 1.0) * cfg.force_scale)
        s["inst_flow"] = float(raw.get("inst_flow", 5.0))

        rsi = raw.get("rsi", 50.0)
        if mode == "hold":
            if   rsi <= 32: s["rsi"] = 6.5
            elif rsi <= 48: s["rsi"] = 8.5
            elif rsi <= 58: s["rsi"] = 9.2
            elif rsi <= 68: s["rsi"] = 5.5
            elif rsi <= 78: s["rsi"] = 2.0
            else:           s["rsi"] = 0.5
        else:
            if   rsi <= 28: s["rsi"] = 9.5
            elif rsi <= 45: s["rsi"] = 8.0 + (45-rsi)/8.5
            elif rsi <= 55: s["rsi"] = 6.5
            elif rsi <= 68: s["rsi"] = 4.0
            elif rsi <= 78: s["rsi"] = 1.5
            else:           s["rsi"] = 0.5

        s["ema"]  = clamp((raw.get("ema_pct",0) + cfg.ema_score_offset) / cfg.ema_score_scale)
        k = raw.get("stoch_k", 50.0)
        s["stoch"] = 8.8 if k<22 else (7.0 if k<45 else (4.2 if k<75 else 1.2))
        if raw.get("stoch_cross_up"): s["stoch"] = min(10.0, s["stoch"] + cfg.stoch_bull_cross_bonus)
        s["macd"] = clamp(5.0 + raw.get("macd_hist_pct",0) * cfg.macd_hist_scale)
        if raw.get("macd_cross_up"):  s["macd"] = min(10.0, s["macd"] + cfg.macd_cross_bonus)

        vp_map = {"breakout":9.2,"value_area":6.8,"at_poc":5.5,"below_value":2.2,"unknown":4.5}
        s["vp_position"] = vp_map.get(raw.get("vp_signal","unknown"), 4.5)
        t_map = {"uptrend":9.5,"weak_up":6.8,"sideway":4.2,"downtrend":0.8,"weak_down":1.8}
        s["trend"] = t_map.get(raw.get("trend_long","sideway"), 4.2)
        rs_base = clamp(raw.get("rs",1.0)*4.2 + 1.8)
        s["rs_score"] = clamp(rs_base*0.6 + fund_score*0.4) if mode=="hold" else rs_base

        # Ichimoku score — trực tiếp từ IchimokuEngine
        s["ichimoku"] = float(raw.get("ichi_score", 5.0))

        tw       = sum(weights.values()) or 1
        weighted = sum(s.get(k, 4.5) * weights.get(k, 0) for k in weights)
        total    = round(min(10.0, weighted/tw) * regime_mult, 2)
        return {k: round(v,2) for k,v in s.items()}, total


# ═════ [source cell 16] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 8. POSITION SIZER
# ══════════════════════════════════════════════════════════════════

class PositionSizer:
    def __init__(self, cfg: QuantConfig): self.cfg = cfg

    def calculate(self, entry: float, stoploss: float, target: float,
                  score: float, atr_ratio: float) -> dict:
        capital  = self.cfg.capital
        risk_amt = capital * self.cfg.risk_per_trade
        sl_dist  = max(entry - stoploss, entry * 0.005)
        shares_risk = risk_amt / sl_dist
        vol_adj = min(1.0, 2.0 / max(atr_ratio, 0.5))
        shares_vol = shares_risk * vol_adj
        win_est = 0.30 + (score/10) * 0.45

        # FIX: rr_est trước đây = sl_dist*2/sl_dist = luôn = 2.0 (hardcode ngầm).
        # Giờ dùng khoảng cách target thật (T1 theo mode swing/hold) để Kelly phản
        # ánh đúng R:R kỹ thuật thực tế của từng kèo.
        target_dist = max(target - entry, 0.0)
        rr_est  = max(1.5, target_dist / sl_dist) if sl_dist > 0 else 1.5

        kelly   = max(0, (win_est*rr_est - (1-win_est)) / rr_est)
        kf      = kelly * self.cfg.kelly_fraction
        shares_k   = (capital * kf) / entry
        max_sh  = (capital * self.cfg.max_position_pct) / entry
        shares  = min(min(shares_vol, shares_k), max_sh)

        # FIX: không ép lên tối thiểu 100cp nữa khi size an toàn tính ra < 1 lô.
        # Trước đây max(100, int(shares//100)*100) sẽ đẩy 45cp → 100cp, vô tình
        # vượt risk_per_trade cho phép. Giờ nếu không đủ 1 lô an toàn → bỏ kèo (0).
        calculated_shares = int(shares // 100) * 100
        lot  = calculated_shares if calculated_shares >= 100 else 0

        cost     = lot * entry
        risk_vnd = lot * sl_dist
        size_note = "" if lot > 0 else (
            "⚠️ Vốn/risk_per_trade không đủ mua 1 lô (100cp) an toàn — bỏ qua kèo này"
        )

        return {
            "shares": lot, "cost_vnd": round(cost,0),
            "pct_nav": round(cost/capital*100,1) if lot>0 else 0.0,
            "risk_vnd": round(risk_vnd,0),
            "win_est": round(win_est*100,2),
            "rr_est": round(rr_est,1),
            "risk_pct_nav": round(risk_vnd/capital*100,2) if lot>0 else 0.0,
            "kelly_pct": round(kf*100,1), "vol_adj": round(vol_adj,2),
            "size_note": size_note,
        }


# ═════ [source cell 17] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 9. SIGNAL BUILDER  [UPDATED — Ichimoku entry/target]
# ══════════════════════════════════════════════════════════════════

class SignalBuilder:
    """
    Decision Maker — chỉ đọc raw dict, ra quyết định.
    KHÔNG tính toán. Tất cả đã qua IndicatorEngine + MomentumEngine + IchimokuEngine.
    """

    def __init__(self, cfg: QuantConfig): self.cfg = cfg

    def smart_entry(self, df: pd.DataFrame, raw: dict,
                    vp: dict, mode: str) -> dict:
        """
        Thứ tự ưu tiên entry (Ichimoku-aware):

        1. Bullish Divergence → mua sát giá (xác suất đảo chiều cao)
        2. Kijun-sen pullback TRÊN MÂY → vùng vàng Trịnh Phát
        3. BB Squeeze + Breakout → mua momentum
        4. Đáy mây (Cloud Bottom) → hỗ trợ mạnh
        5. Volume Dry-up → cạn cung, mua an toàn
        6. Hold mode → VAL / Swing low
        7. Default → BB Lower zone
        """
        close = float(df["close"].iloc[-1])
        atr   = raw.get("atr_abs", close * 0.02)
        val   = vp.get("val"); vah = vp.get("vah"); poc = vp.get("poc")
        sig   = raw.get("vp_signal", "unknown")
        ema5  = raw.get("ema5", close)

        # Ichimoku levels từ daily
        kijun_d     = raw.get("ichi_d_kijun", 0)
        cloud_bot_d = raw.get("ichi_d_cloud_bot", 0)
        cloud_top_d = raw.get("ichi_d_cloud_top", 0)
        above_cloud = raw.get("ichi_d_above_cloud", False)
        ichi_sup1   = raw.get("ichi_sup1", 0)

        bull_div    = raw.get("rsi_bull_div",False) or raw.get("macd_bull_div",False)
        squeeze     = raw.get("is_bb_squeeze",False)
        bb_expanding= raw.get("bb_expanding",False)
        dry_up      = raw.get("vol_dry_up",False)
        bb_lower    = raw.get("bb_lower", close - atr*2)

        # 1. Bullish Divergence
        if bull_div:
            return {"entry": round(close - atr*0.2, 2),
                    "note":  "📈 Phân kỳ dương — đáy xác nhận, mua sát giá"}

        # 2. Kijun-sen pullback (Trịnh Phát golden zone)
        # Điều kiện: giá trên mây + đang về test Kijun (trong 1.5 ATR)
        # FIX: thêm guard pressure() — nếu dòng tiền đang "Rút" mạnh thì không
        # bắt dao ngay sát Kijun (dễ khớp khi đà giảm chưa dừng), lùi entry sâu hơn.
        if above_cloud and kijun_d > 0 and (close - kijun_d) <= atr * 1.5 and close > kijun_d:
            if self.pressure(raw) == "🔴 Rút":
                return {"entry": round(kijun_d * 0.995, 2),
                        "note":  "☁️⚠️ Test Kijun-sen D nhưng dòng tiền đang rút — chờ giá thấp hơn"}
            return {"entry": round(kijun_d * 1.002, 2),
                    "note":  "☁️ Pullback Kijun-sen D — vùng vàng Ichimoku"}

        # 3. BB Squeeze + đang breakout
        if squeeze and (sig == "breakout" or bb_expanding):
            if vah and vah < close:
                return {"entry": round(vah*1.003, 2), "note": "🔴💥 Squeeze Breakout VAH"}
            return {"entry": round(close - atr*0.15, 2), "note": "🔴💥 Squeeze Breakout"}

        # 4. Đáy mây (Cloud Bottom) — hỗ trợ Ichimoku mạnh
        if cloud_bot_d > 0 and 0 < (close - cloud_bot_d) <= atr * 2.0:
            return {"entry": round(cloud_bot_d * 1.003, 2),
                    "note":  "☁️ Test đáy mây Kumo — hỗ trợ mạnh"}

        # 5. Volume Dry-up
        if dry_up:
            return {"entry": round(close - atr*0.1, 2), "note": "💤 Volume cạn — mua sát giá"}

        # 6. Hold mode
        if mode == "hold":
            if val and val < close * 0.975:
                return {"entry": round(val*1.003, 2), "note": "Chờ về VAL"}
            swlo = self._swing_low(df["low"], 18)
            if swlo < close * 0.965:
                return {"entry": round(swlo*1.008, 2), "note": "Chờ swing low"}
            if ichi_sup1 > 0 and ichi_sup1 < close * 0.97:
                return {"entry": round(ichi_sup1*1.003, 2), "note": "☁️ Chờ hỗ trợ Ichimoku"}
            return {"entry": round(close - atr*1.2, 2), "note": "Dip ATR×1.2"}

        # 7. Default Swing — BB Lower zone
        if bb_lower > 0 and bb_lower < close * 0.99:
            return {"entry": round(close - (close-bb_lower)*0.3, 2), "note": "BB Lower zone"}

        if sig == "at_poc" and poc:
            return {"entry": round(poc*0.997, 2), "note": "Mua sát POC"}
        if ema5 < close and close - ema5 <= atr * 1.5:
            return {"entry": round(ema5*1.002, 2), "note": "Test EMA5"}
        return {"entry": round(close - atr*self.cfg.entry_atr_mult, 2),
                "note": f"Dip {self.cfg.entry_atr_mult}×ATR"}

    def levels(self, df: pd.DataFrame, raw: dict,
               vp: dict, se: dict) -> dict:
        """
        Target theo kháng cự kỹ thuật thực, không dùng ATR × hằng số.

        Thứ tự ưu tiên TARGET:
        1. Kháng cự Ichimoku (Kijun W/M, Senkou Span A/B W/M)
        2. VAH (Volume Profile kháng cự)
        3. Swing High gần nhất
        4. Kháng cự tổng hợp ichi_res1/res2

        Mục tiêu: T+ ≥ 9% (min_profit_pct config)
        Nếu kháng cự kỹ thuật gần < 9% → dùng kháng cự xa hơn hoặc nới target.
        """
        close  = float(df["close"].iloc[-1])
        atr    = raw.get("atr_abs", close * 0.02)
        entry  = se["entry"]
        min_profit = self.cfg.min_profit_pct / 100.0

        swlo   = self._swing_low(df["low"], 18)
        val    = vp.get("val"); vah = vp.get("vah")
        res_sw = self._swing_high(df["high"], 20)  # lookback rộng hơn cho target

        # Các mức kháng cự Ichimoku
        ichi_res1 = raw.get("ichi_res1", 0)
        ichi_res2 = raw.get("ichi_res2", 0)
        kijun_w   = raw.get("ichi_w_kijun", 0)
        kijun_m   = raw.get("ichi_m_kijun", 0)
        span_a_w  = raw.get("ichi_w_span_a", 0)
        span_b_m  = raw.get("ichi_m_span_b", 0)

        # Stoploss
        sl_sw = round(swlo * 0.993, 2)
        sl_sw = sl_sw if (entry - sl_sw) <= atr*2.2 else round(entry - atr*1.8, 2)
        sl_hd = sl_sw if (entry - sl_sw) <= atr*3.0 else round(entry - atr*2.3, 2)
        risk_sw = max(entry - sl_sw, atr * 0.5)
        risk_hd = max(entry - sl_hd, atr * 0.5)

        # Momentum flags
        bear_div = raw.get("rsi_bear_div",False) or raw.get("macd_bear_div",False)
        bull_div = raw.get("rsi_bull_div",False) or raw.get("macd_bull_div",False)
        squeeze  = raw.get("is_bb_squeeze",False)

        # ── T+ Target: ưu tiên kháng cự kỹ thuật, tối thiểu 9% ─
        # Tập hợp tất cả kháng cự trên entry
        all_res = sorted([
            x for x in [vah, res_sw, ichi_res1, ichi_res2, kijun_w, span_a_w]
            if x and x > entry * 1.01
        ])

        # Lọc theo min_profit_pct
        min_target = entry * (1 + min_profit)
        profitable_res = [x for x in all_res if x >= min_target]

        if bear_div:
            # Bearish divergence → rút target, ưu tiên an toàn
            t1_sw    = round(entry + atr * 1.5, 2)
            warn_note = "⚠️ PHÂN KỲ ÂM — chốt nhanh!"
        elif profitable_res:
            # Có kháng cự kỹ thuật đủ lợi nhuận → dùng kháng cự đó
            t1_sw    = round(profitable_res[0], 2)
            warn_note = ""
        elif all_res:
            # Kháng cự gần nhưng < 9% → lấy kháng cự xa nhất có thể
            # hoặc nới thêm 1 ATR từ kháng cự gần nhất
            t1_sw    = round(max(all_res[-1], entry*(1+min_profit)), 2)
            warn_note = f"ℹ️ Kháng cự gần < {self.cfg.min_profit_pct:.0f}%, dùng mức xa hơn"
        else:
            # Không có kháng cự rõ ràng → dùng min_profit + ATR buffer
            t1_sw    = round(entry * (1 + min_profit + 0.02), 2)
            warn_note = f"ℹ️ Không có kháng cự rõ — target {self.cfg.min_profit_pct+2:.0f}%"

        # T+ Target 2 — kháng cự xa hơn hoặc Kijun Monthly
        t2_cands = [x for x in [profitable_res[1] if len(profitable_res)>1 else 0,
                                  kijun_m, span_b_m, entry*(1+min_profit*2)]
                    if x and x > t1_sw * 1.01]
        t2_sw = round(min(t2_cands), 2) if t2_cands else round(t1_sw * 1.05, 2)
        if t2_sw <= t1_sw: t2_sw = round(t1_sw * 1.05, 2)

        # ── Hold Target: kháng cự dài hạn ───────────────────────
        hold_res = sorted([
            x for x in [kijun_m, span_b_m, ichi_res2, res_sw, entry*(1+min_profit*2.5)]
            if x and x > entry * (1 + min_profit)
        ])
        t1_hd = round(hold_res[0], 2) if hold_res else round(entry*(1+min_profit*2), 2)
        t2_hd_cands = [x for x in hold_res[1:] + [entry*(1+min_profit*4)] if x > t1_hd*1.01]
        t2_hd = round(min(t2_hd_cands), 2) if t2_hd_cands else round(t1_hd * 1.1, 2)
        if t2_hd <= t1_hd: t2_hd = round(t1_hd * 1.1, 2)

        rr_sw = round((t1_sw - entry) / risk_sw, 2) if risk_sw > 0 else 0
        rr_hd = round((t1_hd - entry) / risk_hd, 2) if risk_hd > 0 else 0

        partial = f"Chốt 1/3 tại T1={t1_sw:,.0f} ({(t1_sw-entry)/entry*100:+.1f}%), trailing phần còn lại"
        if warn_note: partial = warn_note + " | " + partial

        return {
            "entry":      entry, "entry_note":  se["note"], "stoploss":    sl_sw,
            "swing_t1":   t1_sw, "swing_t2":    t2_sw,      "swing_rr":    rr_sw,
            "swing_t1_pct": round((t1_sw-entry)/entry*100, 2),
            "swing_sl_pct": round((sl_sw-entry)/entry*100, 2),
            "hold_t1":    t1_hd, "hold_t2":     t2_hd,      "hold_rr":     rr_hd,
            "hold_t1_pct":  round((t1_hd-entry)/entry*100, 2),
            "pullback_pct": round((entry-float(df["close"].iloc[-1]))/float(df["close"].iloc[-1])*100, 2),
            "partial_note": partial,
            "bear_div_warning": warn_note,
        }

    def classify_horizon(self, raw: dict) -> str:
        close = raw.get("close",0); sma50=raw.get("sma50",close); sma200=raw.get("sma200",None)
        h = 0
        if sma200 and close > sma50 > sma200:                         h+=2
        if 38 <= raw.get("rsi",50) <= 65:                             h+=1
        if raw.get("cmf",0)>0.025 and raw.get("obv_signal")==1:      h+=2
        if raw.get("rs",1.0)>=1.0:                                    h+=1
        # Ichimoku bonus Hold
        if raw.get("ichi_above_count",0) >= 2:                        h+=2
        if raw.get("ichi_tk_cross_up",False):                         h+=1

        t = 0; vr = raw.get("volume_ratio",1.0)
        if raw.get("rsi",50) < 68:                                    t+=1
        if raw.get("ema_pct",0) > -3.5:                               t+=1
        if vr >= 1.35:                                                 t+=2
        if raw.get("stoch_cross_up") or raw.get("macd_cross_up") or vr>=1.8: t+=2
        if raw.get("b_acc") or raw.get("b_brk"):                      t+=1

        # Momentum bonuses/penalties
        bear_div = raw.get("rsi_bear_div",False) or raw.get("macd_bear_div",False)
        bull_div = raw.get("rsi_bull_div",False) or raw.get("macd_bull_div",False)
        squeeze  = raw.get("is_bb_squeeze",False)
        dry_up   = raw.get("vol_dry_up",False)
        if dry_up and squeeze: t+=2
        elif dry_up or squeeze: t+=1
        if raw.get("hidden_accum",False): t+=1
        if raw.get("macd_bull_div",False): h+=2
        if bull_div: t+=1; h+=1
        if bear_div: t-=3; h-=3

        if h >= 4 and t >= 4: return "🔥 T+ & Hold"
        if h >= 4:             return "📈 Hold"
        if t >= 4:             return "⚡ T+"
        if h >= 3 or t >= 3:  return "🔄 Tiềm năng"
        return                        "⏳ Chờ"

    def liquidity_ok(self, raw: dict) -> tuple[bool, str]:
        av = raw.get("avg_vol_20d",0); av2 = raw.get("avg_val_20d",0)
        if av < self.cfg.min_avg_vol_20d:
            return False, f"Vol thấp ({av//1000:.0f}K<{self.cfg.min_avg_vol_20d//1000:.0f}K)"
        if av2 < self.cfg.min_avg_val_20d:
            return False, f"Giá trị thấp ({av2/1e9:.1f}B<{self.cfg.min_avg_val_20d/1e9:.0f}B)"
        return True, ""

    def check_dao_gam(self, close: float, atr: float, raw: dict) -> dict:
        """
        Kiểm tra giá có đang chạm vùng Dao Găm (MA65/MA129) ở khung Tháng→Tuần→Ngày
        không (ưu tiên khung lớn hơn — lực đỡ/cản mạnh hơn). Phân biệt rõ:
        - Test từ TRÊN xuống (pullback về hỗ trợ) = tín hiệu tốt hơn
        - Test từ DƯỚI lên (hồi sau khi đã thủng) = kém tin cậy hơn
        """
        buffer = max(atr * self.cfg.dao_gam_atr_buffer, close * 0.004)

        candidates = [
            ("Tháng", "dg_m_129", "dg_m_129_flat", "dg_m_129_reliable", "DG129"),
            ("Tháng", "dg_m_65",  "dg_m_65_flat",  "dg_m_65_reliable",  "DG65"),
            ("Tuần",  "dg_w_129", "dg_w_129_flat", "dg_w_129_reliable", "DG129"),
            ("Tuần",  "dg_w_65",  "dg_w_65_flat",  "dg_w_65_reliable",  "DG65"),
            ("Ngày",  "dg_d_129", "dg_d_129_flat", "dg_d_129_reliable", "DG129"),
            ("Ngày",  "dg_d_65",  "dg_d_65_flat",  "dg_d_65_reliable",  "DG65"),
        ]
        for tf_label, level_key, flat_key, rel_key, dg_name in candidates:
            level = raw.get(level_key, 0)
            if level and level > 0 and abs(close - level) <= buffer:
                flat       = raw.get(flat_key, False)
                reliable   = raw.get(rel_key, False)
                from_above = close >= level
                role = "hỗ trợ" if from_above else "kháng cự (test lại sau khi thủng)"
                tag  = " · phẳng, lực mạnh" if flat else ""
                warn = " ⚠️ dữ liệu chưa đủ dài" if not reliable else ""
                return {
                    "dg_label":      f"⚔️ {dg_name} {tf_label} — {role}{tag}{warn}",
                    "dg_level":      round(level, 2),
                    "dg_flat":       flat,
                    "dg_from_above": from_above,
                    "dg_reliable":   reliable,
                }
        return {"dg_label": "—", "dg_level": 0.0, "dg_flat": False,
                 "dg_from_above": True, "dg_reliable": True}

    def dao_gam_note(self, dg: dict, raw: dict) -> str:
        """Gợi ý riêng cho tín hiệu Dao Găm — KHÔNG thay thế verdict tổng thể."""
        if dg["dg_label"] == "—":
            return "—"
        if not dg["dg_from_above"]:
            return "⚠️ Test lại từ dưới sau khi thủng — độ tin cậy thấp, chờ xác nhận thêm"
        if not dg["dg_reliable"]:
            return "ℹ️ Chạm DG nhưng lịch sử giá chưa đủ dài — chỉ tham khảo"
        bear_div = raw.get("rsi_bear_div", False) or raw.get("macd_bear_div", False)
        cmf_ok   = raw.get("cmf", 0) > 0
        if bear_div:
            return "⚠️ Chạm DG nhưng phân kỳ âm — chờ xác nhận thêm"
        if dg["dg_flat"] and cmf_ok:
            return "🎯 DG phẳng + dòng tiền dương — vùng mua khá tốt"
        if cmf_ok:
            return "🟡 Có thể mua thăm dò, theo dõi thêm"
        return "👀 Chạm DG nhưng dòng tiền yếu — chờ xác nhận"

    def check_ma_status(self, close: float, raw: dict) -> str:
        """
        Trạng thái MA9/MA10 (ngắn hạn) và MA50/MA200 (dài hạn).
        Mất cả MA9 & MA10 = cảnh báo gãy xu hướng tăng ngắn hạn.
        Test MA50/200 phân biệt test-từ-trên (hỗ trợ, tốt) và thủng-nhẹ-từ-trên (cảnh báo).
        """
        ma9, ma10   = raw.get("ma9"), raw.get("ma10")
        ma50, ma200 = raw.get("sma50"), raw.get("sma200")   # dùng đúng key đã có sẵn
        buf = self.cfg.ma_test_pct_buffer

        if ma9 and ma10 and close < ma9 and close < ma10:
            return "❌ Mất MA9/10 — cảnh báo gãy xu hướng ngắn hạn"

        if ma200 and abs(close - ma200) / ma200 <= buf:
            return "🎯 Test MA200 — hỗ trợ dài hạn" if close >= ma200 else "⚠️ Thủng nhẹ MA200 — theo dõi"
        if ma50 and abs(close - ma50) / ma50 <= buf:
            return "🎯 Test MA50 — hỗ trợ trung hạn" if close >= ma50 else "⚠️ Thủng nhẹ MA50 — theo dõi"

        if ma9 and ma10 and close > ma9 > ma10:
            return "🟢 Xu hướng ngắn hạn tốt"
        return "🟡 Trung tính"

    def portfolio_holder_recommend(self, close: float, score: float, mode: str,
                                    dg: dict, ma_status: str, raw: dict, lvl: dict,
                                    avg_cost: Optional[float] = None) -> tuple[str, str]:
        """
        Khuyến nghị cho người ĐANG HOLD — khác với khuyến nghị mua mới (verdict).
        LƯU Ý: lvl['stoploss'] là SL kỹ thuật tính theo entry giả định HÔM NAY,
        không phải giá vốn thật. Truyền avg_cost (giá vốn thật) nếu biết, để tính
        đúng lãi/lỗ — dùng qua engine.detail(symbol, avg_cost=...).
        """
        bear_div = raw.get("rsi_bear_div", False) or raw.get("macd_bear_div", False)
        cmf      = raw.get("cmf", 0)
        below_sl = close <= lvl["stoploss"]
        broke_ma = "Mất MA9/10" in ma_status

        pnl_txt = ""
        if avg_cost and avg_cost > 0:
            pnl_pct = round((close - avg_cost) / avg_cost * 100, 2)
            pnl_txt = f" (Lãi/lỗ hiện tại: {pnl_pct:+.1f}%)"

        if below_sl:
            return ("🚨 CẮT LỖ",
                    f"Giá đã thủng vùng hỗ trợ kỹ thuật (SL hệ thống {lvl['stoploss']:,.0f})."
                    f" Rủi ro giảm tiếp cao, nên cắt để bảo toàn vốn.{pnl_txt}")

        if bear_div and broke_ma:
            return ("📉 HẠ TỶ TRỌNG MẠNH",
                    "Phân kỳ âm VÀ gãy MA9/10 cùng lúc — 2 cảnh báo trùng nhau,"
                    f" nên chốt bớt 1/2-2/3 vị thế để phòng thủ.{pnl_txt}")
        if bear_div:
            ind = "RSI" if raw.get("rsi_bear_div") else "MACD"
            return ("📉 HẠ TỶ TRỌNG",
                    f"Phân kỳ âm ({ind}) — momentum suy yếu dù giá có thể chưa giảm,"
                    f" nên chốt lời một phần, giữ phần còn lại với SL chặt hơn.{pnl_txt}")
        if broke_ma:
            return ("📉 HẠ TỶ TRỌNG",
                    "Đã mất cả MA9 và MA10 — xu hướng tăng ngắn hạn không còn,"
                    f" nên giảm quy mô vị thế chờ xác nhận lại xu hướng.{pnl_txt}")

        # Ngưỡng "gia tăng" bám theo config thay vì hardcode — đòi hỏi điểm cao hơn
        # min_score chuẩn vì đây là quyết định MUA THÊM, không phải mở vị thế mới
        gia_tang_threshold = (self.cfg.min_score_hold if mode=="hold" else self.cfg.min_score_swing) + 1.0
        if score >= gia_tang_threshold and cmf > 0.05:
            if dg["dg_label"] != "—" and dg["dg_from_above"]:
                return ("🔥 GIA TĂNG",
                        f"Điểm kỹ thuật cao ({score:.1f}) + {dg['dg_label']} + dòng tiền dương"
                        f" (CMF {cmf:+.3f}) — vùng mua thêm khá thuận lợi.{pnl_txt}")
            if "Test MA" in ma_status and "Thủng" not in ma_status:
                return ("🔥 GIA TĂNG",
                        f"Điểm kỹ thuật cao + {ma_status} thành công + dòng tiền dương"
                        f" — có thể cân nhắc mua thêm.{pnl_txt}")

        return ("🔒 TIẾP TỤC HOLD",
                f"Chưa vi phạm hỗ trợ kỹ thuật, chưa có cảnh báo rõ ràng"
                f" (Score {score:.1f}, CMF {cmf:+.3f}). Theo dõi thêm, chưa cần hành động.{pnl_txt}")



    def apply_filters(self, raw: dict, mode: str, liq_ok: bool, liq_reason: str) -> tuple[bool, list]:
        r = []
        if not liq_ok: r.append(liq_reason)
        if raw.get("volume_ratio",0) < 0.85: r.append(f"Vol thấp ({raw.get('volume_ratio',0):.2f}x)")
        rsi = raw.get("rsi",50)
        if rsi > 82: r.append(f"RSI quá mua ({rsi:.0f})")
        elif rsi > 75 and mode == "swing": r.append(f"RSI cao T+ ({rsi:.0f})")
        if raw.get("ema_pct",0) < -9: r.append(f"Dưới EMA20 ({raw.get('ema_pct',0):.1f}%)")
        if raw.get("cmf",0) < -0.20: r.append(f"CMF âm ({raw.get('cmf',0):.3f})")
        if raw.get("stoch_k",50) > 88: r.append(f"Stoch quá mua ({raw.get('stoch_k',50):.0f})")
        if raw.get("ichi_below_count",0) == 3: r.append("☁️ Dưới mây 3TF — downtrend mạnh")
        if mode == "hold":
            if raw.get("trend_long") in ("downtrend","weak_down"): r.append("Downtrend dài hạn")
            if raw.get("obv_signal") == -1: r.append("OBV suy yếu")
        if raw.get("rsi_bear_div") and raw.get("macd_bear_div"): r.append("⚠️ Phân kỳ âm kép")
        return len(r) == 0, r

    @staticmethod
    def verdict(score: float, passed: bool, ok: bool, mode: str) -> str:
        """
        verdict là NGUỒN DUY NHẤT quyết định nhãn — icon console (run()) và cột
        "Tín hiệu" trong bảng giờ LUÔN đồng bộ vì cùng đọc chuỗi trả về từ đây.
        `ok` đã gộp đủ: passed + đạt min_score theo regime + đạt R:R + đạt %profit
        (mode-aware — xem run_pipeline). Trước đây verdict tự đặt ngưỡng riêng,
        độc lập với ok → có thể hiển thị ✅ dù ok=False, gây lệch giữa log và bảng.
        """
        if not passed:
            return "🚫 BỊ LỌC"
        if mode == "hold":
            if ok and score >= 8.0: return "💎 HOLD MẠNH"
            if ok:                  return "✅ XEM XÉT HOLD"
            if score >= 5.5:        return "👀 THEO DÕI"
            return "❌ BỎ QUA"
        else:
            if ok and score >= 7.5: return "🔥 MUA MẠNH T+"
            if ok:                  return "✅ XEM XÉT T+"
            if score >= 5.0:        return "👀 THEO DÕI"
            return "❌ BỎ QUA"

    @staticmethod
    def pressure(raw: dict) -> str:
        buy = sum([raw.get("cmf",0)>0.05, raw.get("force_index",0)>0.08,
                   raw.get("obv_signal")==1, raw.get("volume_ratio",1)>1.5,
                   raw.get("macd_hist_pct",0)>0.05, raw.get("stoch_cross_up",False)])
        sel = sum([raw.get("cmf",0)<-0.08, raw.get("force_index",0)<-0.08,
                   raw.get("obv_signal")==-1, raw.get("volume_ratio",1)<0.7])
        if buy>=4: return "💚 Mạnh"
        if buy==3: return "🟢 Vào"
        if sel>=3: return "🔴 Rút"
        if buy==2: return "🟡 Tích cực"
        return            "⚪ Trung lập"

    @staticmethod
    def _swing_low(series: pd.Series, lookback: int) -> float:
        idx = find_swing_lows_vec(series.tail(lookback), order=3)
        if idx:
            vals = [float(series.tail(lookback).iloc[i]) for i in idx]
            return round(max(v for v in vals if v > 0), 2) if vals else round(float(series.tail(lookback).min()), 2)
        return round(float(series.tail(lookback).min()), 2)

    @staticmethod
    def _swing_high(series: pd.Series, lookback: int) -> float:
        idx = find_swing_highs_vec(series.tail(lookback), order=3)
        if idx:
            vals = [float(series.tail(lookback).iloc[i]) for i in idx]
            return round(max(vals), 2) if vals else round(float(series.tail(lookback).max()), 2)
        return round(float(series.tail(lookback).max()), 2)


# ═════ [source cell 18] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 10. DISPLAY  [FIX: applymap → map, Pandas 2.1+]
# ══════════════════════════════════════════════════════════════════

_TREND = {"uptrend":"🟢 Up","weak_up":"🔵 Weak Up","sideway":"🟡 Side",
          "downtrend":"🔴 Down","weak_down":"🟠 Weak Dn"}
_VP    = {"breakout":"⬆ Break","value_area":"◼ Value","at_poc":"⬛ POC",
          "below_value":"⬇ Below","unknown":"⚪ —"}


def display_table(df: pd.DataFrame, market: dict, min_score: float,
                  mode: str, capital: float):
    try:
        from IPython.display import display as ipy
        in_nb = True
    except ImportError:
        in_nb = False

    cols = [
        "Mã","Tín hiệu","Horizon","Score",
        "Giá","Vol","RSI","CMF","RS",
        "Dòng tiền","VP","Trend", "Ichimoku", "Momentum",
        "Entry","% Win","SL",
        "T+ T1","T+ T2","T+ R:R","T+ %",
        "Hold T1","Hold T2","Hold R:R","Hold %",
        "FA Score","Lý do",
        # NEW — thêm bên phải để copy Excel
        "Dao Găm","Mức DG","DG Gợi Ý","Trạng Thái MA",
        "Khuyến Nghị Hold","Lý Do Hold",
    ]
    show = [c for c in cols if c in df.columns]
    d    = df[show].copy()

    if not in_nb:
        pd.set_option("display.max_columns",None); pd.set_option("display.width",300)
        print(d.to_string(index=False)); return

    def rbg(row):
        s=str(row.get("Tín hiệu",""))
        bg=("#0d2e16" if "🔥" in s or "💎" in s else
            "#12261a" if "✅" in s else
            "#2e1a1a" if "🚫" in s else
            "#3a3a1a" if "⚠" in s else "#1a1f2e")
        return [f"background-color:{bg}" for _ in row]

    # Dùng .map() thay vì .applymap() (Pandas 2.1+ compat)
    def cs(v):
        try:
            f = float(v)
            return "color:#4ade80;font-weight:bold" if f>=7.5 else ("color:#facc15" if f>=6 else "color:#f87171")
        except: return ""
    def ch(v):
        s = str(v)
        if "T+ & Hold" in s: return "color:#4ade80;font-weight:bold"
        if "Hold"      in s: return "color:#60a5fa;font-weight:bold"
        if "T+"        in s: return "color:#facc15"
        if "Tiềm năng" in s: return "color:#a78bfa"
        return "color:#94a3b8"
    def cr(v):
        try:
            f = float(str(v).replace("1:",""))
            return "color:#4ade80;font-weight:bold" if f>=2 else ("color:#facc15" if f>=1.5 else "color:#f87171")
        except: return ""
    def crs(v):
        try:
            f = float(v)
            return "color:#22c55e;font-weight:bold" if f>=1.5 else ("color:#84cc16" if f>=1 else "color:#f87171")
        except: return ""
    def cichi(v):
        s = str(v)
        if "3TF" in s and "✅" in s: return "color:#4ade80;font-weight:bold"
        if "2TF" in s:               return "color:#84cc16"
        if "Dưới" in s:              return "color:#f87171"
        if "Twist" in s:             return "color:#f59e0b"
        return "color:#94a3b8"
    def cmom(v):
        s = str(v)
        if "Div+" in s: return "color:#4ade80;font-weight:bold"
        if "Div-" in s: return "color:#f87171;font-weight:bold"
        if "Sqz"  in s: return "color:#f59e0b"
        return "color:#94a3b8"

    def cdg(v):
        s = str(v)
        if "phẳng" in s: return "color:#4ade80;font-weight:bold"
        if "⚔️" in s:    return "color:#facc15"
        return "color:#64748b"
    def cma(v):
        s = str(v)
        if "Mất MA9/10" in s: return "color:#f87171;font-weight:bold"
        if "Thủng" in s:      return "color:#f59e0b"
        if "Test MA" in s:    return "color:#4ade80;font-weight:bold"
        if "tốt" in s:        return "color:#60a5fa"
        return "color:#94a3b8"
    def chold(v):
        s = str(v)
        if "GIA TĂNG" in s:     return "color:#4ade80;font-weight:bold;background-color:#0d2e16"
        if "CẮT LỖ" in s:       return "color:#f87171;font-weight:bold;background-color:#2e1a1a"
        if "HẠ TỶ TRỌNG" in s:  return "color:#f59e0b;font-weight:bold"
        if "HOLD" in s:         return "color:#60a5fa"
        return ""

    def sub(*c): return [x for x in c if x in d.columns]

    styled = (
        d.style
        .apply(rbg, axis=1)
        .map(cs,   subset=sub("Score"))       # .map() không deprecated
        .map(ch,   subset=sub("Horizon"))
        .map(cr,   subset=sub("T+ R:R","Hold R:R"))
        .map(crs,  subset=sub("RS"))
        .map(cichi,subset=sub("Ichimoku"))
        .map(cmom, subset=sub("Momentum"))
        .map(cdg, subset=sub("Dao Găm"))              # NEW
        .map(cma, subset=sub("Trạng Thái MA"))          # NEW
        .map(chold, subset=sub("Khuyến Nghị Hold"))     # NEW
        .set_table_styles([
            {"selector":"table","props":[("border-collapse","collapse"),("width","100%"),
             ("font-size","11px"),("font-family","'Segoe UI',monospace")]},
            {"selector":"thead tr","props":[("background-color","#1e293b")]},
            {"selector":"th","props":[("color","#e2e8f0"),("padding","5px 7px"),
             ("text-align","center"),("font-size","10px"),("white-space","nowrap"),
             ("border-bottom","2px solid #334155")]},
            {"selector":"td","props":[("padding","4px 7px"),("text-align","center"),
             ("border-bottom","1px solid #1e293b"),("white-space","nowrap")]},
            {"selector":"tr:hover td","props":[("background-color","rgba(148,163,184,0.06)")]},
        ])
        .set_caption(
            f"<b>VN Quant Engine v8</b>  |  "
            f"{'SWING T+' if mode=='swing' else 'HOLD'}  |  "
            f"VNI:{market.get('vnindex',0):,.2f}  |  "
            f"[{market.get('regime','?').upper()}] {market.get('label','—')}  |  "
            f"Min profit T+:{min_score:.1f}pt / ≥9%  |  "
            f"Vốn:{capital/1e6:.0f}M  |  "
            f"{datetime.today().strftime('%d/%m/%Y %H:%M')}"
        )
        .format({
                "Score":    "{:.2f}",
                "Giá":      "{:,.2f}",
                "RSI":      "{:.2f}",
                "CMF":      "{:+.3f}",
                "RS":       "{:.2f}",
                "FA Score": "{:.1f}",
                "Entry":    "{:,.2f}",
                "SL":       "{:,.2f}",
                "T+ T1":    "{:,.2f}","T+ T2":   "{:,.2f}",
                "Hold T1":  "{:,.2f}","Hold T2":  "{:,.2f}",
                "T+ %":     "{:+.2f}%","Hold %":  "{:+.2f}%",
                "POC":      lambda x: f"{x:,.2f}" if pd.notna(x) and x else "—",
                "Mức DG": lambda x: f"{x:,.2f}" if pd.notna(x) and x else "—",
            }, na_rep="—")
           )
    ipy(styled)


# ═════ [source cell 19] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 11. QUANT ENGINE — CONTROLLER  [PR016 — run → auto backtest top N]
# ══════════════════════════════════════════════════════════════════

class QuantEngine:
    """
    Pipeline v8:
    Fetch → Clean → VP → Trend → RS → MF → Indicators
    → IchimokuEngine (D/W/M) [NEW]
    → MomentumEngine (BB/Divergence/DryUp)
    → Liquidity → Hard Filter
    → Score (regime × weights, Ichimoku integrated)
    → Smart Entry (Kijun-aware) [UPDATED]
    → Levels (kháng cự kỹ thuật, target ≥9%) [UPDATED]
    → Position Size → Output
    """

    def __init__(self, capital: float = 100_000_000, cfg: QuantConfig = None):
        self.cfg    = cfg or QuantConfig(capital=capital)
        self.cfg.capital = capital
        self.dl     = DataLayer(self.cfg)
        self.regime = RegimeEngine(self.dl)
        self.ind    = IndicatorEngine()
        self.ichi   = IchimokuEngine(self.cfg)    # [NEW]
        self.mom    = MomentumEngine(self.cfg)
        self.scorer = ScoringEngine()
        self.sig    = SignalBuilder(self.cfg)
        self.pos_sz = PositionSizer(self.cfg)
        self.fa     = FundamentalEngine()
        self.bt     = BacktestEngine(cfg=self.cfg, capital=self.cfg.capital)

    def run_pipeline(self, symbol: str, df_vni: pd.DataFrame,
                     mode: str, weights: dict, regime_mult: float,
                     min_score_val: float, avg_cost: Optional[float] = None) -> Optional[dict]:

        # ═══ PR010: Single-Fetch + FeatureEngine cache ═══
        max_lookback = max(self.cfg.lookback_short, self.cfg.lookback_long, self.cfg.lookback_weekly)
        df_full = self.dl.fetch(symbol, max_lookback)
        if df_full is None or len(df_full) < 30:
            return None

        # Slice cho từng mục đích — không fetch lại
        df    = df_full.tail(self.cfg.lookback_short).reset_index(drop=True)
        df_lg = df_full.tail(self.cfg.lookback_long).reset_index(drop=True)

        # Feature cache — tính EMA/ATR/RSI/MACD/Stoch MỘT LẦN
        feat_cache = FeatureEngine.build(df)

        # Standard components
        vp    = self.ind.volume_profile(df, self.cfg.vp_bins)
        trend = self.ind.long_trend(df_lg)
        rs    = self.ind.relative_strength(df, df_vni)
        mf    = self.ind.inst_money_flow(df)
        raw   = self.ind.compute_all(df, vp, trend, rs, mf, feature_cache=feat_cache)

        # FIX: không còn "except Exception: pass" im lặng — log rõ mã lỗi,
        # và đảm bảo raw luôn có đủ key ichi_* mặc định để Scoring/SmartEntry/
        # Levels/Display không bị lệch khi Ichimoku fail cho 1 mã cụ thể.
        try:
            ichi_data = self.ichi.compute_all_tf(df_full)
            raw.update(ichi_data)
        except Exception as e:
            print(f"  ⚠️ [Ichimoku] {symbol} lỗi tính đa khung: {str(e)[:80]} — fallback trung tính")
            ichi_fallback = {
                "ichi_score": 5.0,
                "ichi_label": "☁️⚠ Lỗi tính Ichimoku — điểm trung tính",
                "ichi_above_count": 0, "ichi_below_count": 0, "ichi_chikou_count": 0,
                "ichi_cloud_bull": 0, "ichi_tk_cross_up": False, "ichi_twist_warn": False,
                "ichi_sup1": 0.0, "ichi_sup2": 0.0, "ichi_res1": 0.0, "ichi_res2": 0.0,
                "ichi_d_kijun": 0.0, "ichi_d_cloud_bot": 0.0, "ichi_d_cloud_top": 0.0,
                "ichi_d_above_cloud": False, "ichi_w_kijun": 0.0, "ichi_m_kijun": 0.0,
                "ichi_w_span_a": 0.0, "ichi_m_span_b": 0.0,
                "dg_d_65": 0.0, "dg_d_129": 0.0, "dg_w_65": 0.0, "dg_w_129": 0.0,
                "dg_m_65": 0.0, "dg_m_129": 0.0,
            }
            for k, v in ichi_fallback.items():
                raw.setdefault(k, v)

        # Momentum features
        raw = self.mom.compute(df, raw, feature_cache=feat_cache)
        # Update momentum_signal với Ichimoku info
        raw["momentum_signal"] = self.mom._summarize(raw)

        fa_score, fa_note      = (self.fa.score(symbol) if self.cfg.use_fundamental else (5.0,"—"))
        liq_ok, liq_reason     = self.sig.liquidity_ok(raw)
        passed, reasons        = self.sig.apply_filters(raw, mode, liq_ok, liq_reason)
        scores, score          = self.scorer.score(raw, mode, weights, regime_mult, fa_score, self.cfg)
        se  = self.sig.smart_entry(df, raw, vp, mode)
        lvl = self.sig.levels(df, raw, vp, se)

        # FIX: PositionSizer giờ cần target thật để tính rr_est đúng — lấy theo mode
        target_for_sizing = lvl["swing_t1"] if mode == "swing" else lvl["hold_t1"]
        pos = self.pos_sz.calculate(lvl["entry"], lvl["stoploss"], target_for_sizing,
                                     score, raw["atr_ratio"])


        # ═══ FIX (mới): ok giờ mode-aware — hold dùng hold_rr, swing dùng swing_rr/profit% ═══
        if mode == "swing":
            ok = (passed and score>=min_score_val and
                  lvl["swing_rr"]>=self.cfg.min_rr and
                  lvl["swing_t1_pct"] >= self.cfg.min_profit_pct)
        else:  # hold
            ok = (passed and score>=min_score_val and
                  lvl["hold_rr"]>=self.cfg.min_rr)

        verdict  = self.sig.verdict(score, passed, ok, mode)   # FIX: truyền ok vào verdict
        horizon  = self.sig.classify_horizon(raw)
        pressure = self.sig.pressure(raw)

        # NEW: Dao Găm / Trạng thái MA / Khuyến nghị cho người đang hold
        dg_info   = self.sig.check_dao_gam(raw["close"], raw.get("atr_abs", raw["close"]*0.02), raw)
        dg_note   = self.sig.dao_gam_note(dg_info, raw)
        ma_status = self.sig.check_ma_status(raw["close"], raw)
        hold_rec, hold_reason = self.sig.portfolio_holder_recommend(
            raw["close"], score, mode, dg_info, ma_status, raw, lvl, avg_cost=avg_cost
        )

        top_pts = sorted(scores.items(), key=lambda x:-x[1])[:3]
        pos_str = " | ".join(f"{k}={v:.1f}" for k,v in top_pts if v>=6.5)

        # FIX: nếu vốn không đủ 1 lô an toàn, show rõ lý do ngay trong cột "Lý do"
        ly_do = " | ".join(reasons) if reasons else ""
        if pos.get("size_note"):
            ly_do = (ly_do + " | " if ly_do else "") + pos["size_note"]

        return {
            "Mã":          symbol,
            "Tín hiệu":    verdict,
            "Horizon":     horizon,
            "Score":       score,
            "Giá":         raw["close"],
            "Vol":         f"{raw['volume_ratio']:.1f}x",
            "Thanh khoản": f"{raw['avg_vol_20d']//1000:.0f}K/ng",
            "RSI":         raw["rsi"],
            "CMF":         round(raw["cmf"],3),
            "RS":          raw["rs"],
            "Dòng tiền":   raw["mf_label"],
            "VP":          _VP.get(raw["vp_signal"],"—"),
            "Trend":       _TREND.get(raw["trend_long"],"—"),
            "Ichimoku":    raw.get("ichi_label","—"),
            "Momentum":    raw.get("momentum_signal","—"),
            "Entry":       lvl["entry"],
            "Entry Zone":  lvl["entry_note"],
            "SL":          lvl["stoploss"],
            "T+ T1":       lvl["swing_t1"],
            "T+ T2":       lvl["swing_t2"],
            "T+ R:R":      f"1:{lvl['swing_rr']:.1f}",
            "T+ %":        lvl["swing_t1_pct"],
            "Hold T1":     lvl["hold_t1"],
            "Hold T2":     lvl["hold_t2"],
            "Hold R:R":    f"1:{lvl['hold_rr']:.1f}",
            "Hold %":      lvl["hold_t1_pct"],
            "FA Score":    fa_score,
            "Mua (CP)":    pos["shares"],
            "Giá trị":     f"{pos['cost_vnd']/1e6:.0f}M",
            "% NAV":       f"{pos['pct_nav']:.1f}%",
            "% Win":       f"{pos['win_est']:.1f}%",
            "Rủi ro %":    f"{pos['risk_pct_nav']:.2f}%",
            "_score":      score,
            "_ok":         ok,
            "_positives":  pos_str,
            "Lý do":    ly_do,
            # ══════════════════════════════════════════════════
            # NEW — thêm bên phải để copy Excel
            # ══════════════════════════════════════════════════
            "Dao Găm":          dg_info["dg_label"],
            "Mức DG":           dg_info["dg_level"] if dg_info["dg_level"] else None,
            "DG Gợi Ý":         dg_note,
            "Trạng Thái MA":    ma_status,
            "Khuyến Nghị Hold": hold_rec,
            "Lý Do Hold":       hold_reason,

            "_fa_note":    fa_note,
            "_pullback":   lvl["pullback_pct"],
            "_partial_note": lvl["partial_note"],
            "_bear_div_warn": lvl.get("bear_div_warning",""),
            "_ichi_above":  raw.get("ichi_above_count",0),
            "_rsi_bull_div":raw.get("rsi_bull_div",False),
            "_rsi_bear_div":raw.get("rsi_bear_div",False),
            "_bb_squeeze":  raw.get("is_bb_squeeze",False),
            "_vol_dry_up":  raw.get("vol_dry_up",False),
        }

    def run(self, symbols: list = None, mode: str = "swing", top_n: int = 300) -> pd.DataFrame:
        assert mode in ("swing","hold")
        watchlist = symbols or VN100
        label     = "SWING T+" if mode=="swing" else "HOLD DÀI HẠN"

        print(f"\n{'═'*70}")
        print(f"  VN QUANT ENGINE v8  |  {label}  |  {len(watchlist)} mã")
        print(f"  Vốn:{self.cfg.capital/1e6:.0f}M  Risk:{self.cfg.risk_per_trade*100:.1f}%  "
              f"Min T+profit:{self.cfg.min_profit_pct:.0f}%  |  "
              f"{datetime.today().strftime('%d/%m/%Y %H:%M')}")
        print(f"{'═'*70}\n")

        ctx      = self.regime.detect()
        weights  = self.regime.dynamic_weights()
        r_mult   = ctx["score_mult"]
        min_sc   = self.regime.min_score(mode, self.cfg)

        print(f"\n  [{ctx['regime'].upper()}]  mult={r_mult:.2f}  min_score={min_sc:.1f}")
        print(f"  Weights → vol={weights.get('volume_ratio',0):.0f}% cmf={weights.get('cmf',0):.0f}% "
              f"ichi={weights.get('ichimoku',0):.0f}% trend={weights.get('trend',0):.0f}% "
              f"vp={weights.get('vp_position',0):.0f}%\n")

        df_vni  = self.dl.fetch("VNINDEX", self.cfg.lookback_short)
        records = []

        for i, sym in enumerate(watchlist):
            print(f"  [{i+1:3d}/{len(watchlist)}] {sym:6s}...", end=" ", flush=True)
            try:
                rec = self.run_pipeline(sym, df_vni, mode, weights, r_mult, min_sc)
                if rec is None:
                    print("❌ thiếu data")
                else:
                    # FIX: icon đọc thẳng từ "Tín hiệu" — ✅ trong string giờ LUÔN
                    # đồng nghĩa _ok=True (do verdict() đã gộp ok vào), không cần
                    # tính lại "ok" riêng như trước (nguồn gây lệch icon/bảng)
                    s = rec["Tín hiệu"]
                    icon = "🔥" if any(x in s for x in ["🔥","💎"]) else ("✅" if "✅" in s else "·")
                    print(f"{icon} {rec['Score']:.1f}  {rec['Horizon']}  "
                          f"T+:{rec['T+ %']:+.1f}%  {rec.get('Ichimoku','—')[:20]}")
                    records.append(rec)
            except Exception as e:
                print(f"⚠ {str(e)[:60]}")
            finally:
                if i < len(watchlist)-1:
                    time.sleep(self.cfg.delay_sec)

        if not records: print("❌ Không có dữ liệu."); return pd.DataFrame()

        res = (pd.DataFrame(records)
               .sort_values(["_ok","_score"], ascending=[False,False])
               .reset_index(drop=True))

        n_ok     = int(res["_ok"].sum())
        n_f      = int(res["Tín hiệu"].str.contains("🔥|💎",regex=True).sum())
        n_g      = int(res["Tín hiệu"].str.contains("✅",regex=True).sum())
        n_ichi3  = int((res["_ichi_above"] >= 3).sum())
        n_bdiv   = int(res["_rsi_bull_div"].sum())

        print(f"\n{'═'*70}")
        print(f"  {ctx['label']}")
        print(f"  Scan {len(res)} mã  |  Đủ ĐK:{n_ok}  Mạnh:{n_f}  Xem:{n_g}")
        print(f"  Trên mây 3TF:{n_ichi3}  Bull Div:{n_bdiv}")
        print(f"{'═'*70}\n")

        if n_f == 0 and n_ok < 3:
            print(f"  💡 Ít tín hiệu ({ctx['regime']} market + min_profit≥{self.cfg.min_profit_pct:.1f}%).")
            print(f"     Thử: cfg.min_profit_pct = {self.cfg.min_profit_pct-2:.1f} hoặc "
                  f"cfg.min_score_swing = {self.cfg.min_score_swing-0.5:.1f}\n")

        show = res.head(top_n)
        if show.empty: show = res.head(min(50, top_n))
        display_table(show, ctx, min_sc, mode, self.cfg.capital)
        self._print_top(res)
        print()
        return res


    def run_and_validate(
        self,
        symbols: list = None,
        mode: str = "swing",
        top_n: int = 300,
        backtest_top: int = 10,
        days: int = 400,
        use_full: bool = False,
        step: int = 5,
        window: int = 120,
        do_monte_carlo: bool = True,
        do_export: bool = True,
        do_plot: bool = False,
        do_report: bool = True,
        export_dir: str = ".",
    ):
        """
        Pipeline liên tục PR016:
          1) Scan live (run)
          2) Lấy top `backtest_top` mã ĐỦ ĐK (_ok)
          3) Backtest từng mã + portfolio chung
          4) Monte-Carlo / export CSV / HTML report (tuỳ chọn)

        Chỉ cần gọi 1 hàm — không phải nhớ API rời.
        """
        # ── 1. Live scan ──
        res = self.run(symbols=symbols, mode=mode, top_n=top_n)
        if res is None or res.empty:
            print("❌ Scan rỗng — dừng validate")
            return {"scan": res, "per_symbol": {}, "portfolio": None, "mc": None}

        # ── 2. Chọn top mã OK ──
        ok = res[res["_ok"] == True] if "_ok" in res.columns else res
        if ok.empty:
            # fallback: top theo Score dù bị lọc
            print("⚠ Không có mã _ok — fallback top Score")
            ok = res
        top = ok.head(backtest_top)
        syms = [str(s).upper() for s in top["Mã"].tolist()]
        print(f"\n{'═'*70}")
        print(f"  PR016 VALIDATE  backtest top {len(syms)} mã từ scan")
        print(f"  {', '.join(syms)}")
        print(f"  days={days}  full={use_full}  mode={mode}")
        print(f"{'═'*70}\n")

        # ── 3a. Backtest từng mã ──
        per_symbol = {}
        data = {}
        for sym in syms:
            print(f"\n—— Backtest {sym} ——")
            try:
                r = self.backtest_symbol(
                    sym, mode=mode, days=days,
                    use_full=use_full, step=step, window=window,
                )
                per_symbol[sym] = r
                if r is not None:
                    df = self.dl.fetch(sym, days)
                    if df is not None and len(df) >= 60:
                        data[sym] = df
                    if do_export and r.trades:
                        base = f"{export_dir.rstrip('/')}/{sym}_{mode}"
                        self.bt.export_trades(r, f"{base}_trades.csv")
                        self.bt.export_equity(r, f"{base}_equity.csv")
                    if do_plot and r is not None:
                        self.bt.plot_equity(r, title=f"{sym} {mode}")
            except Exception as e:
                print(f"  ⚠ {sym} backtest lỗi: {str(e)[:80]}")
                per_symbol[sym] = None

        # ── 3b. Portfolio backtest trên đúng top mã ──
        portfolio = None
        if len(data) >= 2:
            print(f"\n—— Portfolio backtest ({len(data)} mã) ——")
            try:
                portfolio = self.bt.run_portfolio(
                    data,
                    min_score=self.cfg.min_score_hold if mode == "hold" else self.cfg.min_score_swing,
                    max_hold_days=30,
                    risk_per_trade=self.cfg.risk_per_trade,
                    max_positions=min(5, len(data)),
                    mode=mode,
                )
                print(self.bt.summary(portfolio))
                if do_export and portfolio.trades:
                    self.bt.export_trades(portfolio, f"{export_dir.rstrip('/')}/portfolio_{mode}_trades.csv")
                    self.bt.export_equity(portfolio, f"{export_dir.rstrip('/')}/portfolio_{mode}_equity.csv")
                if do_plot:
                    self.bt.plot_equity(portfolio, title=f"Portfolio top{len(data)} {mode}")
            except Exception as e:
                print(f"  ⚠ portfolio lỗi: {str(e)[:80]}")

        # ── 4. Monte-Carlo trên portfolio (hoặc mã đầu) ──
        mc = None
        mc_target = portfolio
        if mc_target is None:
            for r in per_symbol.values():
                if r is not None and r.n_trades >= 3:
                    mc_target = r
                    break
        if do_monte_carlo and mc_target is not None and mc_target.n_trades >= 3:
            print("\n—— Monte-Carlo ——")
            try:
                mc = self.monte_carlo(mc_target, n_sims=500)
            except Exception as e:
                print(f"  ⚠ MC lỗi: {str(e)[:80]}")

        # ── 5. HTML report ──
        if do_report and (portfolio is not None or any(per_symbol.values())):
            report_src = portfolio if portfolio is not None else next(
                (r for r in per_symbol.values() if r is not None), None
            )
            if report_src is not None:
                path = f"{export_dir.rstrip('/')}/validate_{mode}_report.html"
                try:
                    self.report(report_src, path=path, title=f"VQDE Validate Top{len(syms)} {mode}")
                except Exception as e:
                    print(f"  ⚠ report lỗi: {str(e)[:80]}")

        # ── 6. Tóm tắt nhanh ──
        print(f"\n{'═'*70}")
        print("  VALIDATE SUMMARY")
        for sym, r in per_symbol.items():
            if r is None:
                print(f"  {sym:6s}  — lỗi / thiếu data")
            else:
                print(f"  {sym:6s}  trades={r.n_trades:3d}  ret={r.total_return_pct:+6.1f}%  "
                      f"WR={r.win_rate:5.1f}%  DD={r.max_drawdown_pct:6.1f}%  PF={r.profit_factor}")
        if portfolio is not None:
            print(f"  PORT     trades={portfolio.n_trades:3d}  ret={portfolio.total_return_pct:+6.1f}%  "
                  f"WR={portfolio.win_rate:5.1f}%  DD={portfolio.max_drawdown_pct:6.1f}%")
        if mc:
            print(f"  MC       P(profit)={mc.get('prob_profit')}%  "
                  f"ret median={mc.get('ret_median')}%  [{mc.get('ret_p5')} .. {mc.get('ret_p95')}]")
        print(f"{'═'*70}\n")
        print(f"  Cache stats: {self.dl.stats()}")

        return {
            "scan": res,
            "symbols": syms,
            "per_symbol": per_symbol,
            "portfolio": portfolio,
            "mc": mc,
        }

    def detail(self, symbol: str, mode: str = "swing", avg_cost: Optional[float] = None):
        print(f"\n{'═'*58}\n  PHÂN TÍCH v8: {symbol}\n{'═'*58}\n")
        ctx    = self.regime.detect()
        w      = self.regime.dynamic_weights()
        df_vni = self.dl.fetch("VNINDEX", self.cfg.lookback_short)
        rec    = self.run_pipeline(symbol, df_vni, mode, w,
                                    ctx["score_mult"], self.regime.min_score(mode, self.cfg),
                                    avg_cost=avg_cost)
        if rec is None: print("Không lấy được dữ liệu."); return

        print(f"  {symbol}  |  Giá:{rec['Giá']:,.0f}  Score:{rec['Score']:.1f}")
        print(f"  {rec['Tín hiệu']}  |  {rec['Horizon']}")
        print(f"  {rec['Dòng tiền']}  |  Trend:{rec['Trend']}  |  VP:{rec['VP']}")
        print(f"  Ichimoku: {rec.get('Ichimoku','—')}")
        print(f"  Momentum: {rec.get('Momentum','—')}")
        if rec["_bear_div_warn"]: print(f"  {rec['_bear_div_warn']}")
        print(f"  FA:{rec['FA Score']:.1f} ({rec['_fa_note']})")
        print(f"\n  ── ENTRY ─────────────────────────────────────────────")
        print(f"  Vào lệnh : {rec['Entry']:,.0f}  ({rec['Entry Zone']})")
        print(f"  Stoploss : {rec['SL']:,.0f}")
        print(f"\n  ── TARGETS ───────────────────────────────────────────")
        print(f"  T+  → T1:{rec['T+ T1']:,.0f} ({rec['T+ %']:+.1f}%)  T2:{rec['T+ T2']:,.0f}  {rec['T+ R:R']}")
        print(f"  Hold→ T1:{rec['Hold T1']:,.0f} ({rec['Hold %']:+.1f}%)  T2:{rec['Hold T2']:,.0f}  {rec['Hold R:R']}")
        print(f"\n  ── POSITION SIZING ───────────────────────────────────")
        print(f"  Mua:{rec['Mua (CP)']}cp | {rec['Giá trị']} | {rec['% NAV']} NAV | Rủi ro:{rec['Rủi ro %']}")
        print(f"  {rec['_partial_note']}")
        if rec["_positives"]: print(f"\n  ✓ {rec['_positives']}")
        print()

        print(f"\n  ── DAO GĂM & MA (Trịnh Phát) ─────────────────────────")
        print(f"  {rec['Dao Găm']}  |  Mức: {rec['Mức DG']}")
        print(f"  → {rec['DG Gợi Ý']}")
        print(f"  MA: {rec['Trạng Thái MA']}")
        if avg_cost:
            print(f"\n  ── ĐANG HOLD (giá vốn {avg_cost:,.0f}) ────────────────")
        else:
            print(f"\n  ── NẾU ĐANG HOLD (chưa có giá vốn — dùng kỹ thuật) ───")
        print(f"  Khuyến nghị: {rec['Khuyến Nghị Hold']}")
        print(f"  → {rec['Lý Do Hold']}")

    def _print_top(self, res: pd.DataFrame):
        top = res[res["Tín hiệu"].str.contains("🔥|💎|✅",regex=True)].head(10)
        if top.empty: return
        print(f"\n  📋 TOP {len(top)} MÃ:")
        for _, r in top.iterrows():
            warn = " ⚠️BEAR DIV" if r.get("_rsi_bear_div") else ""
            print(f"\n  {r['Mã']:6s} {r['Tín hiệu']} {r['Horizon']}{warn}")
            print(f"         {r.get('Ichimoku','—')}")
            print(f"         {r.get('Momentum','—')}")
            print(f"         Entry:{r['Entry']:,.0f}({r['Entry Zone']}) SL:{r['SL']:,.0f}")
            print(f"         T+→T1:{r['T+ T1']:,.0f}({r['T+ %']:+.1f}%) T2:{r['T+ T2']:,.0f} {r['T+ R:R']}")
            print(f"         Hold→T1:{r['Hold T1']:,.0f}({r['Hold %']:+.1f}%) T2:{r['Hold T2']:,.0f} {r['Hold R:R']}")
            print(f"         {r['_partial_note']}")
            print(f"         Mua {r['Mua (CP)']}cp ({r['Giá trị']} {r['% NAV']} NAV rủi ro {r['Rủi ro %']})")
            if r["_positives"]: print(f"         ✓ {r['_positives']}")


    # ═══ PR012: Backtest integration ═══
    def backtest_symbol(
        self,
        symbol: str,
        mode: str = "swing",
        days: int = None,
        min_score: float = None,
        max_hold_days: int = 30,
        risk_per_trade: float = None,
        use_full: bool = False,
        step: int = 5,
        window: int = 120,
    ):
        """
        Fetch history → auto-build signals → run single-symbol backtest.
        use_full=True: walk-forward IndicatorEngine (chậm hơn, chính xác hơn).
        window: lookback bars for full mode (PR015).
        """
        days = days or max(self.cfg.lookback_long, self.cfg.lookback_weekly, 400)
        df = self.dl.fetch(symbol, days)
        if df is None or len(df) < 60:
            print(f"❌ {symbol}: không đủ data để backtest")
            return None

        min_sc = min_score if min_score is not None else (
            self.cfg.min_score_hold if mode == "hold" else self.cfg.min_score_swing
        )
        risk = risk_per_trade if risk_per_trade is not None else self.cfg.risk_per_trade
        df_vni = self.dl.fetch("VNINDEX", days) if use_full else None

        print(f"\n{'═'*50}")
        print(f"  BACKTEST  {symbol}  mode={mode}  bars={len(df)}  full={use_full}")
        print(f"  min_score={min_sc}  max_hold={max_hold_days}d  risk={risk*100:.1f}%")
        print(f"  cost: fee={self.bt.cost.fee_rate*100:.2f}%  slip={self.bt.cost.slippage_rate*100:.2f}%")
        print(f"{'═'*50}")

        result = self.bt.run_symbol(
            df,
            symbol=symbol,
            min_score=min_sc,
            max_hold_days=max_hold_days,
            risk_per_trade=risk,
            mode=mode,
            use_full=use_full,
            step=step,
            df_vni=df_vni,
            window=window,
        )

        print(self.bt.summary(result))
        if result.trades:
            print(f"\n  Last 5 trades:")
            for t in result.trades[-5:]:
                print(f"    {t.entry_date} → {t.exit_date}  "
                      f"{t.entry_price:.2f}→{t.exit_price:.2f}  "
                      f"pnl={t.pnl:,.0f} ({t.pnl_pct:+.1f}%)  {t.exit_reason}")
        return result

    def backtest_symbol_export(
        self,
        symbol: str,
        mode: str = "swing",
        days: int = None,
        min_score: float = None,
        export_dir: str = ".",
        plot: bool = True,
        **kwargs,
    ):
        """Backtest 1 mã + export CSV + plot equity."""
        result = self.backtest_symbol(symbol, mode=mode, days=days, min_score=min_score, **kwargs)
        if result is None:
            return None
        base = f"{export_dir.rstrip('/')}/{symbol}_{mode}"
        self.bt.export_trades(result, f"{base}_trades.csv")
        self.bt.export_equity(result, f"{base}_equity.csv")
        if plot:
            self.bt.plot_equity(result, title=f"{symbol} {mode}")
        return result

    def backtest_portfolio(
        self,
        symbols: list = None,
        mode: str = "swing",
        days: int = None,
        min_score: float = None,
        max_hold_days: int = 30,
        risk_per_trade: float = None,
        max_positions: int = 5,
    ):
        """
        Multi-symbol portfolio backtest with shared capital.
        """
        symbols = symbols or ["FPT", "HPG", "VCB", "MWG", "SSI", "ACB", "TCB", "MSN"]
        days = days or max(self.cfg.lookback_long, 400)
        min_sc = min_score if min_score is not None else (
            self.cfg.min_score_hold if mode == "hold" else self.cfg.min_score_swing
        )
        risk = risk_per_trade if risk_per_trade is not None else self.cfg.risk_per_trade

        print(f"\n{'═'*50}")
        print(f"  PORTFOLIO BACKTEST  {len(symbols)} mã  mode={mode}")
        print(f"  max_pos={max_positions}  min_score={min_sc}  risk={risk*100:.1f}%")
        print(f"{'═'*50}\n")

        data = {}
        for sym in symbols:
            print(f"  fetch {sym}...", end=" ", flush=True)
            df = self.dl.fetch(sym, days)
            if df is not None and len(df) >= 60:
                data[sym] = df
                print(f"OK ({len(df)} bars)")
            else:
                print("skip")

        if not data:
            print("❌ Không có data")
            return None

        result = self.bt.run_portfolio(
            data,
            min_score=min_sc,
            max_hold_days=max_hold_days,
            risk_per_trade=risk,
            max_positions=max_positions,
            mode=mode,
        )
        print("\n" + self.bt.summary(result))
        return result


    def benchmark_cache(self, symbols: list = None, days: int = 300) -> dict:
        """Benchmark DataLayer cache performance."""
        symbols = symbols or ["FPT", "HPG", "VCB", "MWG", "SSI", "ACB", "TCB", "MSN"]
        return BacktestEngine.benchmark_cache(self.dl, symbols, days)


    def grid_search_symbol(
        self,
        symbol: str,
        mode: str = "swing",
        days: int = None,
        min_scores: list = None,
        max_holds: list = None,
        use_full: bool = False,
        step: int = 5,
    ) -> "pd.DataFrame":
        """Grid search min_score × max_hold for one symbol."""
        days = days or max(self.cfg.lookback_long, 400)
        df = self.dl.fetch(symbol, days)
        if df is None or len(df) < 60:
            print(f"❌ {symbol}: insufficient data")
            return None
        print(f"\\nGrid search {symbol}  bars={len(df)}  full={use_full}")
        return self.bt.grid_search(
            df, symbol=symbol, mode=mode,
            min_scores=min_scores, max_holds=max_holds,
            risk_per_trade=self.cfg.risk_per_trade,
            use_full=use_full, step=step,
        )

    def report(
        self,
        result,
        path: str = "backtest_report.html",
        title: str = "VQDE Backtest Report",
        grid=None,
    ) -> str:
        """Generate HTML report from a BacktestResult."""
        return self.bt.html_report(result, path=path, title=title, grid=grid)


    def grid_search_portfolio(
        self,
        symbols: list = None,
        mode: str = "swing",
        days: int = None,
        min_scores: list = None,
        max_holds: list = None,
        max_positions_list: list = None,
    ):
        """Multi-symbol parameter grid."""
        symbols = symbols or ["FPT", "HPG", "VCB", "MWG", "SSI", "ACB"]
        days = days or max(self.cfg.lookback_long, 400)
        data = {}
        for sym in symbols:
            df = self.dl.fetch(sym, days)
            if df is not None and len(df) >= 60:
                data[sym] = df
                print(f"  {sym}: {len(df)} bars")
            else:
                print(f"  {sym}: skip")
        if not data:
            print("❌ No data")
            return None
        return self.bt.grid_search_portfolio(
            data,
            mode=mode,
            min_scores=min_scores,
            max_holds=max_holds,
            max_positions_list=max_positions_list,
            risk_per_trade=self.cfg.risk_per_trade,
        )

    def monte_carlo(self, result, n_sims: int = 500, seed: int = 42) -> dict:
        """Bootstrap robustness test on a BacktestResult trade list."""
        return self.bt.monte_carlo(result, n_sims=n_sims, seed=seed)



# ═════ [source cell 20] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# 12. BACKTEST ENGINE  [PR015 — optimized WF + portfolio grid + Monte-Carlo]
# ══════════════════════════════════════════════════════════════════
from dataclasses import dataclass, field
from typing import List, Optional, Dict
import pandas as pd
import numpy as np


@dataclass
class TradeRecord:
    symbol: str
    entry_date: str
    exit_date: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    shares: int = 0
    side: str = "LONG"
    pnl: float = 0.0
    pnl_pct: float = 0.0
    score: float = 0.0
    exit_reason: str = ""
    holding_days: int = 0
    fees: float = 0.0          # total round-trip fees + slippage cost
    gross_pnl: float = 0.0     # before costs


@dataclass
class BacktestResult:
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: Optional[pd.Series] = None
    total_return_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_holding_days: float = 0.0
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    total_fees: float = 0.0
    notes: str = ""
    per_symbol: Dict[str, dict] = field(default_factory=dict)


@dataclass
class CostModel:
    """
    Vietnam equity cost approximation (one-side).
    fee_rate: commission + tax (e.g. 0.15% = 0.0015)
    slippage_rate: adverse price move on fill (e.g. 0.10% = 0.001)
    """
    fee_rate: float = 0.0015
    slippage_rate: float = 0.0010

    def buy_price(self, px: float) -> float:
        return px * (1 + self.slippage_rate)

    def sell_price(self, px: float) -> float:
        return px * (1 - self.slippage_rate)

    def fee(self, notional: float) -> float:
        return abs(notional) * self.fee_rate


class SignalSeriesBuilder:
    """
    Build historical score / entry / SL / TP series from OHLCV
    using FeatureEngine cache + lightweight rolling score.

    Not a full re-run of QuantEngine every bar (too slow);
    approximates the live scoring with the same indicator inputs.
    """

    def __init__(self, cfg: QuantConfig = None):
        self.cfg = cfg or QuantConfig()

    def build(
        self,
        df: pd.DataFrame,
        mode: str = "swing",
        min_bars: int = 60,
    ) -> pd.DataFrame:
        """
        Returns DataFrame with columns:
          score, entry, stoploss, target, rsi, atr, ema_pct, volume_ratio
        Index aligned with df.
        """
        n = len(df)
        out = pd.DataFrame(index=df.index)
        out["score"] = np.nan
        out["entry"] = np.nan
        out["stoploss"] = np.nan
        out["target"] = np.nan

        if n < min_bars:
            return out

        fc = FeatureEngine.build(df)
        c = df["close"]
        h = df["high"]
        l = df["low"]
        v = df["volume"]

        rsi = fc.get("rsi14", FeatureEngine.rsi(c, 14))
        atr = fc.get("atr14", FeatureEngine.atr(df, 14))
        ema20 = fc.get("ema20", FeatureEngine.ema(c, 20))
        ema50 = fc.get("ema50", FeatureEngine.ema(c, 50))
        vol_ma = v.rolling(20, min_periods=5).mean()
        vol_ratio = v / (vol_ma + 1e-9)

        # CMF rolling
        mfv = ((c - l) - (h - c)) / (h - l + 1e-9) * v
        cmf = mfv.rolling(21, min_periods=5).sum() / v.rolling(21, min_periods=5).sum().replace(0, np.nan)

        # PR013: fuller rolling score (RSI + vol + CMF + EMA + MACD + Stoch + trend)
        macd_hist = fc.get("macd_hist")
        stoch_k = fc.get("stoch_k")
        if macd_hist is None:
            _, _, macd_hist = FeatureEngine.macd(c)
        if stoch_k is None:
            stoch_k, _ = FeatureEngine.stoch(df)

        scores = []
        for i in range(n):
            if i < min_bars - 1:
                scores.append(np.nan)
                continue
            s = 5.0
            r = float(rsi.iloc[i]) if not pd.isna(rsi.iloc[i]) else 50.0
            vr = float(vol_ratio.iloc[i]) if not pd.isna(vol_ratio.iloc[i]) else 1.0
            cm = float(cmf.iloc[i]) if not pd.isna(cmf.iloc[i]) else 0.0
            ema20_v = float(ema20.iloc[i]) if not pd.isna(ema20.iloc[i]) else float(c.iloc[i])
            ema50_v = float(ema50.iloc[i]) if not pd.isna(ema50.iloc[i]) else ema20_v
            ep = (float(c.iloc[i]) - ema20_v) / (ema20_v + 1e-9) * 100
            mh = float(macd_hist.iloc[i]) if not pd.isna(macd_hist.iloc[i]) else 0.0
            sk = float(stoch_k.iloc[i]) if not pd.isna(stoch_k.iloc[i]) else 50.0

            # RSI
            if mode == "hold":
                if r <= 32: s += 1.2
                elif r <= 48: s += 1.8
                elif r <= 58: s += 2.0
                elif r >= 78: s -= 2.5
                elif r >= 68: s -= 1.0
            else:
                if r <= 28: s += 2.5
                elif r <= 45: s += 1.5
                elif r >= 78: s -= 2.5
                elif r >= 68: s -= 1.2

            # Volume
            if vr >= 2.0: s += 2.0
            elif vr >= 1.3: s += 1.2
            elif vr < 0.5: s -= 1.2

            # CMF / money flow
            if cm > 0.15: s += 1.8
            elif cm > 0.05: s += 1.0
            elif cm < -0.15: s -= 1.8
            elif cm < -0.05: s -= 1.0

            # Trend EMA
            if float(c.iloc[i]) > ema20_v > ema50_v and ep > 0:
                s += 1.5
            elif float(c.iloc[i]) < ema20_v < ema50_v:
                s -= 1.5
            elif ep < -3:
                s -= 1.0

            # MACD hist
            if mh > 0:
                s += min(1.5, abs(mh) / (float(c.iloc[i]) + 1e-9) * 500)
            else:
                s -= min(1.5, abs(mh) / (float(c.iloc[i]) + 1e-9) * 500)

            # Stochastic
            if sk < 25: s += 1.2
            elif sk > 80: s -= 1.2

            scores.append(float(np.clip(s, 0, 10)))

        out["score"] = scores
        out["entry"] = c.values

        atr_vals = atr.bfill().fillna(c * 0.02)
        out["stoploss"] = (c - 1.5 * atr_vals).values
        # Target ~ 2.5R or min profit
        risk = c - out["stoploss"]
        out["target"] = (c + 2.5 * risk).values
        out["rsi"] = rsi.values
        out["atr"] = atr_vals.values
        out["volume_ratio"] = vol_ratio.values
        return out

    def build_full(
        self,
        df: pd.DataFrame,
        mode: str = "swing",
        min_bars: int = 80,
        step: int = 5,
        df_vni: pd.DataFrame = None,
        window: int = 120,
    ) -> pd.DataFrame:
        """
        Walk-forward gần full IndicatorEngine — PR015 optimized.

        Optimizations:
        - FeatureEngine.build() MỘT LẦN trên toàn bộ df
        - Cửa sổ cố định `window` bars (không expanding full history)
        - Chỉ recompute mỗi `step` bar, forward-fill giữa các bước
        """
        n = len(df)
        out = pd.DataFrame(index=df.index)
        for col in ("score", "entry", "stoploss", "target", "rsi", "atr", "volume_ratio"):
            out[col] = np.nan

        if n < min_bars:
            return out

        # Precompute features once
        fc_full = FeatureEngine.build(df)
        ind = IndicatorEngine()
        scorer = ScoringEngine()
        cfg = self.cfg
        weights = dict(BASE_WEIGHTS) if "BASE_WEIGHTS" in globals() else {
            "volume_ratio": 12, "cmf": 10, "obv": 6, "force": 4, "inst_flow": 6,
            "rsi": 9, "ema": 6, "stoch": 5, "macd": 4,
            "vp_position": 10, "trend": 9, "rs_score": 7, "ichimoku": 12,
        }
        regime_mult = 1.0

        # numpy buffers for speed
        scores = np.full(n, np.nan)
        entries = np.full(n, np.nan)
        stops = np.full(n, np.nan)
        tps = np.full(n, np.nan)
        rsis = np.full(n, np.nan)
        atrs = np.full(n, np.nan)
        vrs = np.full(n, np.nan)

        last = {
            "score": np.nan, "entry": np.nan, "sl": np.nan, "tp": np.nan,
            "rsi": np.nan, "atr": np.nan, "vr": np.nan,
        }

        for i in range(min_bars - 1, n):
            if (i - (min_bars - 1)) % step == 0 or i == n - 1:
                start_i = max(0, i + 1 - window)
                window_df = df.iloc[start_i: i + 1].reset_index(drop=True)
                # slice precomputed features to same window
                fc = {}
                for k, s in fc_full.items():
                    if hasattr(s, "iloc"):
                        fc[k] = s.iloc[start_i: i + 1].reset_index(drop=True)
                    else:
                        fc[k] = s
                try:
                    vp = ind.volume_profile(window_df, cfg.vp_bins)
                    trend = ind.long_trend(window_df) if len(window_df) >= 60 else {
                        "trend_long": "sideway", "sma50": None, "sma200": None, "slope": 0.0
                    }
                    vni_slice = None
                    if df_vni is not None and len(df_vni) >= len(window_df):
                        vni_slice = df_vni.iloc[-len(window_df):].reset_index(drop=True)
                    rs = ind.relative_strength(window_df, vni_slice) if vni_slice is not None else 1.0
                    mf = ind.inst_money_flow(window_df)
                    raw = ind.compute_all(window_df, vp, trend, rs, mf, feature_cache=fc)
                    _, total = scorer.score(raw, mode, weights, regime_mult, 5.0, cfg)

                    entry = float(raw.get("close", window_df["close"].iloc[-1]))
                    atr = float(raw.get("atr_abs", 0)) or entry * 0.02
                    last["score"] = float(total)
                    last["entry"] = entry
                    last["sl"] = entry - 1.5 * atr
                    last["tp"] = entry + 2.5 * (entry - last["sl"])
                    last["rsi"] = float(raw.get("rsi", 50))
                    last["atr"] = atr
                    last["vr"] = float(raw.get("volume_ratio", 1))
                except Exception:
                    pass

            scores[i] = last["score"]
            entries[i] = last["entry"]
            stops[i] = last["sl"]
            tps[i] = last["tp"]
            rsis[i] = last["rsi"]
            atrs[i] = last["atr"]
            vrs[i] = last["vr"]

        out["score"] = scores
        out["entry"] = entries
        out["stoploss"] = stops
        out["target"] = tps
        out["rsi"] = rsis
        out["atr"] = atrs
        out["volume_ratio"] = vrs
        return out


class BacktestEngine:
    """
    PR012:
    - Single-symbol walk-forward with cost model
    - Multi-symbol portfolio (capital shared, max positions)
    - SignalSeriesBuilder wired for auto signal generation
    """

    def __init__(
        self,
        cfg: QuantConfig = None,
        capital: float = 100_000_000,
        cost: CostModel = None,
    ):
        self.cfg = cfg or QuantConfig(capital=capital)
        self.capital = capital
        self.cost = cost or CostModel()
        self.signal_builder = SignalSeriesBuilder(self.cfg)

    # ── single symbol ──────────────────────────────────────────
    def run_symbol(
        self,
        df: pd.DataFrame,
        scores: pd.Series = None,
        entries: pd.Series = None,
        stoplosses: pd.Series = None,
        targets: pd.Series = None,
        symbol: str = "",
        min_score: float = 6.0,
        max_hold_days: int = 30,
        risk_per_trade: float = 0.01,
        mode: str = "swing",
        use_full: bool = False,
        step: int = 5,
        df_vni: pd.DataFrame = None,
        window: int = 120,
    ) -> BacktestResult:
        """
        If scores/entries/SL/TP not provided, auto-build via SignalSeriesBuilder.
        use_full=True → build_full (IndicatorEngine walk-forward, slower).
        """
        result = BacktestResult()
        if df is None or len(df) < 30:
            result.notes = "Insufficient data"
            return result

        # Auto-generate signals if missing
        if scores is None or entries is None:
            if use_full:
                sig = self.signal_builder.build_full(df, mode=mode, step=step, df_vni=df_vni, window=window)
            else:
                sig = self.signal_builder.build(df, mode=mode)
            scores = sig["score"]
            entries = sig["entry"]
            stoplosses = sig["stoploss"]
            targets = sig["target"]

        cash = float(self.capital)
        position = None
        equity = []
        trades: List[TradeRecord] = []

        times = (
            df["time"].astype(str).tolist()
            if "time" in df.columns
            else [str(i) for i in range(len(df))]
        )
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        closes = df["close"].values.astype(float)

        for i in range(len(df)):
            # ── manage open position ──
            if position is not None:
                position.holding_days += 1
                sl = getattr(position, "_sl", position.entry_price * 0.95)
                tp = getattr(position, "_tp", position.entry_price * 1.10)

                exit_px = None
                reason = ""
                if lows[i] <= sl:
                    exit_px = float(sl)
                    reason = "SL"
                elif highs[i] >= tp:
                    exit_px = float(tp)
                    reason = "TP"
                elif position.holding_days >= max_hold_days:
                    exit_px = float(closes[i])
                    reason = "MAX_HOLD"

                if exit_px is not None:
                    sell_px = self.cost.sell_price(exit_px)
                    notional = position.shares * sell_px
                    fee = self.cost.fee(notional)
                    gross = (sell_px - position.entry_price) * position.shares
                    # entry fee already deducted from cash; add exit fee
                    net = gross - fee
                    # also subtract entry fee portion tracked
                    entry_fee = getattr(position, "_entry_fee", 0.0)
                    net -= 0  # entry fee already out of cash

                    position.exit_date = times[i]
                    position.exit_price = sell_px
                    position.gross_pnl = gross
                    position.fees = entry_fee + fee
                    position.pnl = net - entry_fee  # net of both sides relative to entry cost basis
                    # simpler: cash accounting is source of truth
                    cash += notional - fee
                    position.pnl = (sell_px - position.entry_price) * position.shares - entry_fee - fee
                    position.pnl_pct = (sell_px / position.entry_price - 1) * 100
                    position.exit_reason = reason
                    trades.append(position)
                    position = None

            # ── open new ──
            if position is None and i < len(scores):
                sc = float(scores.iloc[i]) if not pd.isna(scores.iloc[i]) else 0
                if sc >= min_score:
                    raw_entry = (
                        float(entries.iloc[i])
                        if i < len(entries) and not pd.isna(entries.iloc[i])
                        else closes[i]
                    )
                    entry_px = self.cost.buy_price(raw_entry)
                    sl_px = (
                        float(stoplosses.iloc[i])
                        if i < len(stoplosses) and not pd.isna(stoplosses.iloc[i])
                        else raw_entry * 0.95
                    )
                    tp_px = (
                        float(targets.iloc[i])
                        if i < len(targets) and not pd.isna(targets.iloc[i])
                        else raw_entry * 1.10
                    )
                    risk = entry_px - sl_px
                    if risk > 0 and cash > 0:
                        risk_budget = cash * risk_per_trade
                        shares = int(risk_budget / risk)
                        cost_notional = shares * entry_px
                        fee = self.cost.fee(cost_notional)
                        if shares > 0 and cost_notional + fee <= cash:
                            cash -= cost_notional + fee
                            position = TradeRecord(
                                symbol=symbol,
                                entry_date=times[i],
                                entry_price=entry_px,
                                shares=shares,
                                score=sc,
                            )
                            position._sl = sl_px
                            position._tp = tp_px
                            position._entry_fee = fee

            mtm = cash + (position.shares * closes[i] if position else 0)
            equity.append(mtm)

        if position is not None:
            sell_px = self.cost.sell_price(float(closes[-1]))
            notional = position.shares * sell_px
            fee = self.cost.fee(notional)
            entry_fee = getattr(position, "_entry_fee", 0.0)
            cash += notional - fee
            position.exit_date = times[-1]
            position.exit_price = sell_px
            position.fees = entry_fee + fee
            position.pnl = (sell_px - position.entry_price) * position.shares - entry_fee - fee
            position.pnl_pct = (sell_px / position.entry_price - 1) * 100
            position.exit_reason = "EOD"
            trades.append(position)

        return self._finalize(result, trades, equity, symbol)

    # ── multi-symbol portfolio ─────────────────────────────────
    def run_portfolio(
        self,
        data: Dict[str, pd.DataFrame],
        min_score: float = 6.0,
        max_hold_days: int = 30,
        risk_per_trade: float = 0.01,
        max_positions: int = 5,
        mode: str = "swing",
    ) -> BacktestResult:
        """
        Shared capital across symbols. Max concurrent positions limited.
        data: {symbol: OHLCV DataFrame}
        """
        result = BacktestResult()
        if not data:
            result.notes = "Empty portfolio data"
            return result

        # Align on calendar: use union of all dates, process chronologically
        signals = {}
        for sym, df in data.items():
            if df is None or len(df) < 30:
                continue
            sig = self.signal_builder.build(df, mode=mode)
            sig = sig.copy()
            sig["symbol"] = sym
            if "time" in df.columns:
                sig["time"] = pd.to_datetime(df["time"].values)
            else:
                sig["time"] = pd.to_datetime(df.index)
            sig["high"] = df["high"].values
            sig["low"] = df["low"].values
            sig["close"] = df["close"].values
            signals[sym] = sig.reset_index(drop=True)

        if not signals:
            result.notes = "No valid symbol data"
            return result

        # Build global event list sorted by date
        events = []
        for sym, sig in signals.items():
            for i in range(len(sig)):
                events.append((sig["time"].iloc[i], sym, i))
        events.sort(key=lambda x: x[0])

        cash = float(self.capital)
        open_pos: Dict[str, TradeRecord] = {}
        trades: List[TradeRecord] = []
        equity_map = {}  # date -> equity

        for dt, sym, i in events:
            sig = signals[sym]
            high = float(sig["high"].iloc[i])
            low = float(sig["low"].iloc[i])
            close = float(sig["close"].iloc[i])
            tstr = str(dt.date()) if hasattr(dt, "date") else str(dt)

            # manage existing position for this symbol
            if sym in open_pos:
                pos = open_pos[sym]
                pos.holding_days += 1
                sl = getattr(pos, "_sl", pos.entry_price * 0.95)
                tp = getattr(pos, "_tp", pos.entry_price * 1.10)
                exit_px = None
                reason = ""
                if low <= sl:
                    exit_px, reason = float(sl), "SL"
                elif high >= tp:
                    exit_px, reason = float(tp), "TP"
                elif pos.holding_days >= max_hold_days:
                    exit_px, reason = close, "MAX_HOLD"

                if exit_px is not None:
                    sell_px = self.cost.sell_price(exit_px)
                    fee = self.cost.fee(pos.shares * sell_px)
                    entry_fee = getattr(pos, "_entry_fee", 0.0)
                    cash += pos.shares * sell_px - fee
                    pos.exit_date = tstr
                    pos.exit_price = sell_px
                    pos.fees = entry_fee + fee
                    pos.pnl = (sell_px - pos.entry_price) * pos.shares - entry_fee - fee
                    pos.pnl_pct = (sell_px / pos.entry_price - 1) * 100
                    pos.exit_reason = reason
                    trades.append(pos)
                    del open_pos[sym]

            # open new if slot available
            if sym not in open_pos and len(open_pos) < max_positions:
                sc = float(sig["score"].iloc[i]) if not pd.isna(sig["score"].iloc[i]) else 0
                if sc >= min_score:
                    raw_entry = float(sig["entry"].iloc[i]) if not pd.isna(sig["entry"].iloc[i]) else close
                    entry_px = self.cost.buy_price(raw_entry)
                    sl_px = float(sig["stoploss"].iloc[i]) if not pd.isna(sig["stoploss"].iloc[i]) else raw_entry * 0.95
                    tp_px = float(sig["target"].iloc[i]) if not pd.isna(sig["target"].iloc[i]) else raw_entry * 1.10
                    risk = entry_px - sl_px
                    if risk > 0 and cash > 0:
                        risk_budget = self.capital * risk_per_trade  # fixed vs initial capital
                        shares = int(risk_budget / risk)
                        notional = shares * entry_px
                        fee = self.cost.fee(notional)
                        if shares > 0 and notional + fee <= cash:
                            cash -= notional + fee
                            pos = TradeRecord(
                                symbol=sym,
                                entry_date=tstr,
                                entry_price=entry_px,
                                shares=shares,
                                score=sc,
                            )
                            pos._sl = sl_px
                            pos._tp = tp_px
                            pos._entry_fee = fee
                            open_pos[sym] = pos

            # MTM
            mtm = cash
            for s, p in open_pos.items():
                # use last known close for that symbol at this event
                mtm += p.shares * float(signals[s]["close"].iloc[
                    min(i if s == sym else len(signals[s]) - 1, len(signals[s]) - 1)
                ])
            equity_map[dt] = mtm

        # close leftovers
        for sym, pos in list(open_pos.items()):
            close = float(signals[sym]["close"].iloc[-1])
            sell_px = self.cost.sell_price(close)
            fee = self.cost.fee(pos.shares * sell_px)
            entry_fee = getattr(pos, "_entry_fee", 0.0)
            cash += pos.shares * sell_px - fee
            pos.exit_date = str(signals[sym]["time"].iloc[-1].date()) if hasattr(signals[sym]["time"].iloc[-1], "date") else str(signals[sym]["time"].iloc[-1])
            pos.exit_price = sell_px
            pos.fees = entry_fee + fee
            pos.pnl = (sell_px - pos.entry_price) * pos.shares - entry_fee - fee
            pos.pnl_pct = (sell_px / pos.entry_price - 1) * 100
            pos.exit_reason = "EOD"
            trades.append(pos)
        open_pos.clear()

        if equity_map:
            eq = pd.Series(equity_map).sort_index()
            equity = eq.tolist()
        else:
            equity = [self.capital]

        result = self._finalize(result, trades, equity, "PORTFOLIO")
        # per-symbol breakdown
        for sym in data:
            sym_trades = [t for t in trades if t.symbol == sym]
            if sym_trades:
                result.per_symbol[sym] = {
                    "n": len(sym_trades),
                    "pnl": round(sum(t.pnl for t in sym_trades), 0),
                    "win_rate": round(100 * sum(1 for t in sym_trades if t.pnl > 0) / len(sym_trades), 1),
                }
        return result

    # ── helpers ────────────────────────────────────────────────
    def _finalize(self, result, trades, equity, label) -> BacktestResult:
        result.trades = trades
        result.n_trades = len(trades)
        result.total_fees = round(sum(t.fees for t in trades), 0)
        if trades:
            wins = [t for t in trades if t.pnl > 0]
            losses = [t for t in trades if t.pnl <= 0]
            result.n_wins = len(wins)
            result.n_losses = len(losses)
            result.win_rate = round(len(wins) / len(trades) * 100, 1)
            gross_win = sum(t.pnl for t in wins) or 0
            gross_loss = abs(sum(t.pnl for t in losses)) or 1e-9
            result.profit_factor = round(gross_win / gross_loss, 2)
            result.avg_holding_days = round(float(np.mean([t.holding_days for t in trades])), 1)
            result.total_return_pct = (
                round((equity[-1] / self.capital - 1) * 100, 2) if equity else 0
            )
        if equity:
            eq = pd.Series(equity)
            result.equity_curve = eq
            peak = eq.cummax()
            dd = (eq - peak) / peak.replace(0, np.nan)
            result.max_drawdown_pct = round(float(dd.min() * 100), 2)
        result.notes = f"{label}: {result.n_trades} trades, fees={result.total_fees:,.0f}"
        return result


    def export_trades(self, result: BacktestResult, path: str = "trades.csv") -> str:
        """Export trade list to CSV. Returns path."""
        if not result.trades:
            print("No trades to export")
            return path
        rows = []
        for t in result.trades:
            rows.append({
                "symbol": t.symbol,
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "shares": t.shares,
                "pnl": round(t.pnl, 0),
                "pnl_pct": round(t.pnl_pct, 2),
                "fees": round(t.fees, 0),
                "score": t.score,
                "exit_reason": t.exit_reason,
                "holding_days": t.holding_days,
            })
        df = pd.DataFrame(rows)
        df.to_csv(path, index=False)
        print(f"✓ Exported {len(df)} trades → {path}")
        return path

    def export_equity(self, result: BacktestResult, path: str = "equity.csv") -> str:
        """Export equity curve to CSV."""
        if result.equity_curve is None or len(result.equity_curve) == 0:
            print("No equity curve")
            return path
        eq = result.equity_curve.reset_index()
        eq.columns = ["step", "equity"] if eq.shape[1] == 2 else list(eq.columns)
        eq.to_csv(path, index=False)
        print(f"✓ Exported equity ({len(eq)} points) → {path}")
        return path

    def plot_equity(self, result: BacktestResult, title: str = "Equity Curve"):
        """Plot equity curve if matplotlib available."""
        if result.equity_curve is None or len(result.equity_curve) == 0:
            print("No equity curve to plot")
            return
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(10, 4))
            eq = result.equity_curve.reset_index(drop=True)
            ax.plot(eq.values, color="#2563eb", linewidth=1.5)
            ax.axhline(self.capital, color="#94a3b8", linestyle="--", linewidth=1, label="Initial")
            ax.fill_between(range(len(eq)), eq.values, self.capital,
                            where=(eq.values >= self.capital), alpha=0.15, color="green")
            ax.fill_between(range(len(eq)), eq.values, self.capital,
                            where=(eq.values < self.capital), alpha=0.15, color="red")
            ax.set_title(f"{title}  |  ret={result.total_return_pct}%  DD={result.max_drawdown_pct}%")
            ax.set_ylabel("Equity")
            ax.set_xlabel("Bar")
            ax.legend(loc="upper left")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
        except ImportError:
            print("matplotlib not available — skip plot")

    @staticmethod
    def benchmark_cache(data_layer, symbols: list, days: int = 300) -> dict:
        """
        Benchmark DataLayer cache: fetch twice, report hit rate & speedup.
        """
        import time
        data_layer.clear_cache()
        # cold
        t0 = time.perf_counter()
        for s in symbols:
            data_layer.fetch(s, days)
        cold = time.perf_counter() - t0
        stats_cold = data_layer.stats()
        # warm
        t1 = time.perf_counter()
        for s in symbols:
            data_layer.fetch(s, days)
        warm = time.perf_counter() - t1
        stats_warm = data_layer.stats()
        report = {
            "symbols": len(symbols),
            "days": days,
            "cold_sec": round(cold, 2),
            "warm_sec": round(warm, 2),
            "speedup": round(cold / warm, 1) if warm > 0 else None,
            "stats": stats_warm,
        }
        print(f"Cache benchmark ({len(symbols)} symbols, {days}d):")
        print(f"  cold={cold:.2f}s  warm={warm:.2f}s  speedup={report['speedup']}x")
        print(f"  stats={stats_warm}")
        return report



    def grid_search(
        self,
        df: pd.DataFrame,
        symbol: str = "",
        mode: str = "swing",
        min_scores: list = None,
        max_holds: list = None,
        risk_per_trade: float = 0.01,
        use_full: bool = False,
        step: int = 5,
    ) -> pd.DataFrame:
        """
        Grid search over min_score × max_hold_days.
        Returns DataFrame sorted by total_return_pct.
        """
        min_scores = min_scores or [5.0, 5.5, 6.0, 6.5, 7.0]
        max_holds = max_holds or [10, 15, 20, 30, 45]
        rows = []

        # pre-build signals once
        if use_full:
            sig = self.signal_builder.build_full(df, mode=mode, step=step)
        else:
            sig = self.signal_builder.build(df, mode=mode)

        scores = sig["score"]
        entries = sig["entry"]
        stoplosses = sig["stoploss"]
        targets = sig["target"]

        for ms in min_scores:
            for mh in max_holds:
                r = self.run_symbol(
                    df,
                    scores=scores,
                    entries=entries,
                    stoplosses=stoplosses,
                    targets=targets,
                    symbol=symbol,
                    min_score=ms,
                    max_hold_days=mh,
                    risk_per_trade=risk_per_trade,
                    mode=mode,
                )
                rows.append({
                    "min_score": ms,
                    "max_hold": mh,
                    "n_trades": r.n_trades,
                    "win_rate": r.win_rate,
                    "profit_factor": r.profit_factor,
                    "total_return_pct": r.total_return_pct,
                    "max_dd_pct": r.max_drawdown_pct,
                    "avg_hold": r.avg_holding_days,
                    "total_fees": r.total_fees,
                })
        grid = pd.DataFrame(rows).sort_values("total_return_pct", ascending=False)
        print("Grid search top 5:")
        print(grid.head().to_string(index=False))
        return grid

    def html_report(
        self,
        result: BacktestResult,
        path: str = "backtest_report.html",
        title: str = "VQDE Backtest Report",
        grid: pd.DataFrame = None,
    ) -> str:
        """Generate a simple standalone HTML report."""
        trades_html = ""
        if result.trades:
            rows = []
            for t in result.trades[-50:]:  # last 50
                color = "#16a34a" if t.pnl >= 0 else "#dc2626"
                rows.append(
                    f"<tr>"
                    f"<td>{t.symbol}</td><td>{t.entry_date}</td><td>{t.exit_date}</td>"
                    f"<td>{t.entry_price:.2f}</td><td>{t.exit_price:.2f}</td>"
                    f"<td>{t.shares}</td>"
                    f"<td style='color:{color}'>{t.pnl:,.0f}</td>"
                    f"<td style='color:{color}'>{t.pnl_pct:+.1f}%</td>"
                    f"<td>{t.exit_reason}</td><td>{t.holding_days}</td>"
                    f"</tr>"
                )
            trades_html = "\n".join(rows)

        grid_html_block = ""
        if grid is not None and len(grid):
            grid_html_block = grid.head(10).to_html(index=False, float_format="%.2f")

        per_sym = ""
        if result.per_symbol:
            items = sorted(result.per_symbol.items(), key=lambda x: -x[1]["pnl"])
            per_sym = "<ul>" + "".join(
                f"<li><b>{s}</b>: n={d['n']}, pnl={d['pnl']:,.0f}, wr={d['win_rate']}%</li>"
                for s, d in items
            ) + "</ul>"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#0f172a;color:#e2e8f0}}
h1,h2{{color:#38bdf8}}
.card{{background:#1e293b;border-radius:12px;padding:16px 20px;margin:12px 0}}
.metrics span{{display:inline-block;margin:6px 16px 6px 0;padding:8px 12px;background:#334155;border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #334155;padding:6px 8px;text-align:right}}
th{{background:#334155;text-align:center}}
td:first-child,th:first-child{{text-align:left}}
</style></head><body>
<h1>{title}</h1>
<div class="card metrics">
  <span>Trades: <b>{result.n_trades}</b> (W{result.n_wins}/L{result.n_losses})</span>
  <span>Win rate: <b>{result.win_rate}%</b></span>
  <span>Profit factor: <b>{result.profit_factor}</b></span>
  <span>Return: <b>{result.total_return_pct}%</b></span>
  <span>Max DD: <b>{result.max_drawdown_pct}%</b></span>
  <span>Avg hold: <b>{result.avg_holding_days}d</b></span>
  <span>Fees: <b>{result.total_fees:,.0f}</b></span>
</div>
<div class="card"><h2>Notes</h2><p>{result.notes}</p>{per_sym}</div>
"""
        if grid_html_block:
            html += f'<div class="card"><h2>Grid search (top)</h2>{grid_html_block}</div>'
        html += f"""
<div class="card"><h2>Trades (last 50)</h2>
<table>
<thead><tr>
<th>Symbol</th><th>Entry</th><th>Exit</th><th>Entry Px</th><th>Exit Px</th>
<th>Shares</th><th>PnL</th><th>PnL%</th><th>Reason</th><th>Days</th>
</tr></thead>
<tbody>
{trades_html}
</tbody></table></div>
</body></html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"✓ HTML report → {path}")
        return path



    def grid_search_portfolio(
        self,
        data: dict,
        mode: str = "swing",
        min_scores: list = None,
        max_holds: list = None,
        max_positions_list: list = None,
        risk_per_trade: float = 0.01,
    ) -> pd.DataFrame:
        """
        Multi-symbol grid: min_score × max_hold × max_positions.
        data: {symbol: OHLCV DataFrame}
        """
        min_scores = min_scores or [5.5, 6.0, 6.5]
        max_holds = max_holds or [15, 20, 30]
        max_positions_list = max_positions_list or [3, 5]
        rows = []
        for ms in min_scores:
            for mh in max_holds:
                for mp in max_positions_list:
                    r = self.run_portfolio(
                        data,
                        min_score=ms,
                        max_hold_days=mh,
                        risk_per_trade=risk_per_trade,
                        max_positions=mp,
                        mode=mode,
                    )
                    rows.append({
                        "min_score": ms,
                        "max_hold": mh,
                        "max_positions": mp,
                        "n_trades": r.n_trades,
                        "win_rate": r.win_rate,
                        "profit_factor": r.profit_factor,
                        "total_return_pct": r.total_return_pct,
                        "max_dd_pct": r.max_drawdown_pct,
                        "total_fees": r.total_fees,
                    })
        grid = pd.DataFrame(rows).sort_values("total_return_pct", ascending=False)
        print("Portfolio grid top 5:")
        print(grid.head().to_string(index=False))
        return grid

    def monte_carlo(
        self,
        result: BacktestResult,
        n_sims: int = 500,
        seed: int = 42,
    ) -> dict:
        """
        Bootstrap shuffle of trade PnL sequence to estimate return / DD distribution.
        Does not re-simulate prices — tests path dependency of the trade list.
        """
        if not result.trades or len(result.trades) < 3:
            print("Need ≥3 trades for Monte-Carlo")
            return {}

        rng = np.random.default_rng(seed)
        pnls = np.array([t.pnl for t in result.trades], dtype=float)
        n = len(pnls)

        final_eq = np.zeros(n_sims)
        max_dd = np.zeros(n_sims)

        for s in range(n_sims):
            sample = rng.choice(pnls, size=n, replace=True)
            equity = self.capital + np.cumsum(sample)
            final_eq[s] = equity[-1]
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / np.where(peak == 0, np.nan, peak)
            max_dd[s] = np.nanmin(dd) * 100

        rets = (final_eq / self.capital - 1) * 100
        report = {
            "n_sims": n_sims,
            "n_trades": n,
            "ret_median": round(float(np.median(rets)), 2),
            "ret_p5": round(float(np.percentile(rets, 5)), 2),
            "ret_p95": round(float(np.percentile(rets, 95)), 2),
            "dd_median": round(float(np.median(max_dd)), 2),
            "dd_p5": round(float(np.percentile(max_dd, 5)), 2),  # more negative = worse
            "dd_p95": round(float(np.percentile(max_dd, 95)), 2),
            "prob_profit": round(float((rets > 0).mean() * 100), 1),
        }
        print("Monte-Carlo robustness:")
        print(f"  Return median={report['ret_median']}%  [{report['ret_p5']}% .. {report['ret_p95']}%]")
        print(f"  MaxDD median={report['dd_median']}%  [{report['dd_p5']}% .. {report['dd_p95']}%]")
        print(f"  P(profit)={report['prob_profit']}%  ({n_sims} sims, {n} trades)")
        return report


    def summary(self, result: BacktestResult) -> str:
        lines = [
            f"Trades       : {result.n_trades} (W{result.n_wins}/L{result.n_losses})",
            f"Win rate     : {result.win_rate}%",
            f"Profit factor: {result.profit_factor}",
            f"Total return : {result.total_return_pct}%",
            f"Max DD       : {result.max_drawdown_pct}%",
            f"Avg hold     : {result.avg_holding_days} days",
            f"Total fees   : {result.total_fees:,.0f}",
            f"Note         : {result.notes}",
        ]
        if result.per_symbol:
            lines.append("Per symbol   :")
            for s, d in sorted(result.per_symbol.items(), key=lambda x: -x[1]["pnl"]):
                lines.append(f"  {s:6s}  n={d['n']:3d}  pnl={d['pnl']:>12,.0f}  wr={d['win_rate']}%")
        return "\n".join(lines)



# ═════ [source cell 21] Tool_CK_Grok_v2_PR016.ipynb ═════
# ══════════════════════════════════════════════════════════════════
# BACKWARD COMPAT — gọi như cũ vẫn chạy được
# ══════════════════════════════════════════════════════════════════

def run_scanner(symbols=None, mode="swing", top_n=300,
                capital=100_000_000):
    """Shortcut — tương thích v3/v4/v5."""
    return QuantEngine(capital=capital).run(symbols=symbols, mode=mode, top_n=top_n)
