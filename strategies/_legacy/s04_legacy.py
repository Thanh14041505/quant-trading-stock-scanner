# -*- coding: utf-8 -*-
# ╔════════════════════════════════════════════════════════════════════════╗
# ║  FILE SINH TỰ ĐỘNG — KHÔNG SỬA TAY                                      ║
# ║  Sinh bởi tools/extract_legacy.py; nội dung các cell là NGUYÊN VĂN.     ║
# ╚════════════════════════════════════════════════════════════════════════╝
# Source Notebook : Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb
# Section         : Production scanner (QuantEngine.run_pipeline và các engine phụ thuộc)
# Cells được giữ  : [2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
# Ghi chú         : S4 — v5.6 (S3 + RSI/Composite Divergence). Loại: 0,1, 5 (len(VN100)), 21 (TPlusQuantEngine, xem B6), 22 (__main__), 23 (markdown).
# Lý do giữ nguyên: dự án ưu tiên "bảo toàn logic notebook" (bug, ngưỡng, thứ tự tính toán).
#                   Mọi vá lỗi nằm ở lớp adapter (strategies/strategy_XX.py), KHÔNG ở file này.


# ═════ [source cell 2] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
"""
╔══════════════════════════════════════════════════════════════════════════╗
║   VN QUANT ENGINE v5.6 — VSA Integration + Volume Profile Precision   ║
╠══════════════════════════════════════════════════════════════════════════╣
║  CÀI ĐẶT:  pip install vnstock pandas numpy -q                         ║
║  DÙNG:     engine = QuantEngine(capital=500_000_000)                    ║
║            df = engine.run(mode="swing")                               ║
║            engine.detail("VND")                                        ║
╠══════════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v5.2 (so với v5.1):                                          ║
║                                                                          ║
║  CONFIG                                                                  ║
║  ~ vp_bins: 8 → 30  (zone ~0.3%, đủ chi tiết mà không nhiễu)           ║
║    Lý do: 8 bins quá thô trên khung 35 ngày (~1.5%/zone),              ║
║    30 bins cho zone ~0.3-0.5% phù hợp đặt entry/SL chính xác          ║
║                                                                          ║
║  VSAEngine (NEW CLASS)                                                   ║
║  + Detect 5 trạng thái Smart Money từ Vol × Spread × ClosePos          ║
║  + 🚀 NỔ VOL: Vol lớn, spread rộng, đóng cao → mua thực sự            ║
║  + 🩸 CẠN VOL: Vol khô, spread hẹp → cung cạn kiệt                    ║
║  + 🔨 RÚT CHÂN: Vol lớn, spread rộng, đóng cao sau rũ → gom hàng      ║
║  + ⚠️ PHÂN PHỐI: Vol lớn nhưng đóng thấp → xả hàng núp bóng          ║
║  + 🥀 CẠN CẦU: Giá tăng nhẹ không có Vol → breakout fake              ║
║  + Vectorized np.select → O(n) không loop                               ║
║                                                                          ║
║  ScoringEngine (ENHANCED)                                                ║
║  + Thêm VSA sub-score vào tổng điểm                                     ║
║  + NỔ VOL: +2.5 | RÚT CHÂN: +2.0 | CẠN VOL: +1.5                     ║
║  + PHÂN PHỐI: -2.0 | CẠN CẦU: -1.0                                    ║
║                                                                          ║
║  SignalBuilder.apply_filters (ENHANCED)                                  ║
║  + Hard filter: PHÂN PHỐI trong swing → loại ngay                       ║
║  + Hard filter: Breakout + CẠN CẦU → loại ngay (bull trap)             ║
║                                                                          ║
║  GIỮ NGUYÊN từ v5.1:                                                    ║
║  = VolumeDryupDetector (Wyckoff Spring logic)                           ║
║  = WinRateEstimator (Pattern + Regime multiplier)                       ║
║  = SignalBuilder levels/entry/SL (swing 2×ATR, hold max -8%)           ║
║  = PositionSizer (Kelly-fractional + vol adjustment)                    ║
║  = RegimeEngine (Bull/Sideways/Bear/Panic detection)                    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

# =====================================================
# VN QUANT T+2.5 SWING ENGINE v5.3
# Kết hợp Grok Quant + Engine v5.2 (VSA + Volume Profile)
# Dành riêng cho giao dịch T+2.5 (Swing 3-10 ngày)
# =====================================================

import warnings
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List

warnings.filterwarnings("ignore")


# ═════ [source cell 3] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 1 — CONFIG                                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Tất cả tham số điều chỉnh được tập trung tại đây — không cần sửa code
# trong các class. Khi muốn thay đổi behavior, chỉ override QuantConfig.
#
# Ví dụ:  cfg = QuantConfig(capital=200_000_000, risk_per_trade=0.005)
#         engine = QuantEngine(cfg=cfg)

@dataclass
class QuantConfig:
    # Data
    lookback_short: int = 40
    lookback_long: int = 750   # v5.5: tăng từ 280 → 750, đủ dữ liệu cho Weekly Ichimoku
    sources: list = field(default_factory=lambda: ["KBS", "VCI"])
    delay_sec: float = 1.6
    vp_bins: int = 30

    # Scoring
    # Score / R:R thresholds
    # Swing dùng ngưỡng gốc; Hold dùng ngưỡng riêng để tránh nhầm config.
    min_score_swing: float = 6.3
    min_score_hold: float = 6.3
    min_rr_swing: float = 2.0
    min_rr_hold: float = 3.0

    # Liquidity
    min_avg_vol_20d: int = 80_000
    min_avg_val_20d: float = 5_000_000

    # Risk & Position
    capital: float = 100_000_000
    risk_per_trade: float = 0.01      # 1%
    max_position_pct: float = 0.18
    kelly_fraction: float = 0.25

    # Entry
    entry_pullback_pct: float = 0.6
    entry_atr_mult: float = 0.45

    # Dry-up
    dryup_range_ratio: float = 0.65
    dryup_vol_ratio:    float = 0.70
    dryup_sessions: int = 5
    dryup_bonus: float = 2.0

    wr_base: float = 45.0

    # RSI / Composite Index Divergence (v5.6)
    divergence_lb_left: int = 5
    divergence_lb_right: int = 5
    divergence_range_lower: int = 5
    divergence_range_upper: int = 60
    divergence_use_close: bool = False
    divergence_rsi_length: int = 14
    divergence_rsi_mom_length: int = 9
    divergence_rsi_ma_length: int = 3
    divergence_ma_length: int = 3
    divergence_fast_length: int = 13
    divergence_slow_length: int = 33
    divergence_max_age_bars: int = 15


# ═══════════════════════════════════════════════════════════════════════════════
# WATCHLIST — giữ nguyên từ v5
# ═══════════════════════════════════════════════════════════════════════════════


T_PLUS_WATCHLIST = ['FPT', 'VCB', 'HPG', 'TCB', 'ACB', 'BID', 'MWG', 'SSI', 'VND', 'CTD', 'VHM', 'VIC', 'VRE', 'PNJ', 'MSN',
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
                   'SBB', 'VNP', 'HVN']


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
                   'SBB', 'VNP', 'HVN']


# Base weights — normalized về 100, regime sẽ điều chỉnh dynamic
BASE_WEIGHTS = {
    "volume_ratio": 12, "cmf": 10, "obv": 6, "force": 3, "inst_flow": 4,
    "rsi": 10, "rsi_divergence": 8, "ema": 7, "stoch": 6, "macd": 5,
    "vp_position": 12, "trend": 10, "rs_score": 5, "vsa": 11,
}

REGIME_WEIGHT_DELTA = {
    "bull":     {"volume_ratio": +3, "trend": +5, "rsi": -2, "vp_position": +2, "vsa": +2},
    "sideways": {"cmf": +3, "obv": +3, "vp_position": +5, "trend": -3},
    "bear":     {"cmf": +5, "trend": -5, "rsi": +3, "volume_ratio": -3, "vsa": +3},
    "panic":    {"cmf": +5, "force": +5, "volume_ratio": +5, "rsi": -5, "vsa": +4},
}

REGIME_SCORE_MULT = {"bull": 1.0, "sideways": 0.95, "bear": 0.85, "panic": 0.70}
REGIME_WR_MULT    = {"bull": 1.15, "sideways": 1.0, "bear": 0.80, "panic": 0.65}


# ═════ [source cell 4] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ CONFIG VALIDATOR — FIX: kiểm tra config trước khi scan                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Mục đích:
#   Các engine trong notebook gọi self.cfg.xxx ở nhiều nơi. Nếu thiếu một
#   field, lỗi trước đây chỉ xuất hiện khi scan tới đúng mã/nhánh code đó.
#   Validator này phát hiện lỗi ngay khi khởi tạo QuantEngine.


def validate_quant_config(cfg: QuantConfig):
    """Validate các config bắt buộc trước khi chạy QuantEngine."""

    required_fields = [
        # Data
        "lookback_short", "lookback_long", "sources", "delay_sec", "vp_bins",
        # Score / R:R
        "min_score_swing", "min_score_hold", "min_rr_swing", "min_rr_hold",
        # Liquidity
        "min_avg_vol_20d", "min_avg_val_20d",
        # Risk / position
        "capital", "risk_per_trade", "max_position_pct", "kelly_fraction",
        # Entry
        "entry_pullback_pct", "entry_atr_mult",
        # Dry-up
        "dryup_range_ratio", "dryup_vol_ratio", "dryup_sessions", "dryup_bonus",
        # Win rate
        "wr_base",
        # Divergence
        "divergence_lb_left", "divergence_lb_right",
        "divergence_range_lower", "divergence_range_upper",
        "divergence_use_close", "divergence_rsi_length",
        "divergence_rsi_mom_length", "divergence_rsi_ma_length",
        "divergence_ma_length", "divergence_fast_length",
        "divergence_slow_length", "divergence_max_age_bars",
    ]

    missing = [name for name in required_fields if not hasattr(cfg, name)]
    if missing:
        raise AttributeError(
            "QuantConfig đang thiếu parameter:\n" +
            "\n".join(f"  - {name}" for name in missing)
        )

    # Basic sanity checks
    if cfg.min_rr_swing <= 0 or cfg.min_rr_hold <= 0:
        raise ValueError("min_rr_swing và min_rr_hold phải > 0")
    if cfg.min_score_swing < 0 or cfg.min_score_hold < 0:
        raise ValueError("min_score_swing và min_score_hold phải >= 0")
    if cfg.risk_per_trade <= 0:
        raise ValueError("risk_per_trade phải > 0")
    if cfg.capital <= 0:
        raise ValueError("capital phải > 0")
    if cfg.divergence_lb_left < 1 or cfg.divergence_lb_right < 1:
        raise ValueError("divergence_lb_left/right phải >= 1")

    return True


# Test config ngay sau khi sửa notebook.
_cfg_check = QuantConfig()
validate_quant_config(_cfg_check)
print("✅ QuantConfig validation passed.")



# ═════ [source cell 6] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 2 — DATA LAYER                                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Nhiệm vụ: Fetch OHLCV từ vnstock, chuẩn hóa tên cột, xử lý missing data.
#
# Vấn đề thực tế ở VN:
#   - API vnstock có v3 và v4 với signature khác nhau → dùng fallback
#   - Ngày lễ, ngày không giao dịch → forward fill giá, volume = 0
#   - Một số mã trả về tên cột khác nhau tùy source (KBS vs VCI)
#
# Design choice: không raise exception, return None nếu data không hợp lệ
# → caller (pipeline) tự quyết định skip hay retry

class DataLayer:
    """
    Fetch và chuẩn hóa OHLCV data từ vnstock.

    Hỗ trợ hai version API vnstock (v3/v4) với cơ chế fallback tự động.
    Xử lý missing data theo chuẩn: ffill giá (giữ giá cuối hợp lệ),
    volume=0 khi không giao dịch (tránh nhầm với phiên bình thường).

    Output luôn là DataFrame đã chuẩn hóa với cột:
    time, open, high, low, close, volume
    """

    def __init__(self, cfg: QuantConfig):
        self.cfg = cfg

    def fetch(self, symbol: str, days: int) -> Optional[pd.DataFrame]:
        end = (datetime.today() + timedelta(1)).strftime("%Y-%m-%d")
        start = (datetime.today() - timedelta(days=days + 45)).strftime("%Y-%m-%d")

        for src in self.cfg.sources:
            for fn in (self._v4, self._v3):
                try:
                    df = fn(symbol, start, end, src)
                    if df is not None:
                        clean = self._clean(df, days)
                        if clean is not None and len(clean) >= 25:
                            return clean
                except:
                    continue
        return None

    def _v4(self, sym, start, end, src):
        from vnstock import Quote
        q = Quote(symbol=sym, source=src)
        try:
            return q.history(start=start, end=end, interval="1D")
        except:
            return q.history(start_date=start, end_date=end, interval="1D")

    def _v3(self, sym, start, end, src):
        from vnstock import Vnstock
        stk = Vnstock().stock(symbol=sym, source=src)
        try:
            return stk.quote.history(start=start, end=end, interval="1D")
        except:
            return stk.quote.history(start_date=start, end_date=end, interval="1D")

    def _clean(self, df: pd.DataFrame, days: int) -> Optional[pd.DataFrame]:
        df = df.copy()
        df.columns = [c.lower().strip() for c in df.columns]
        df = df.rename(columns={"tradingdate": "time", "date": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})

        if not {"time", "open", "high", "low", "close", "volume"}.issubset(df.columns):
            return None

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].ffill().bfill()
        df["volume"] = df["volume"].fillna(0)

        df = df[df["close"] > 0].sort_values("time").reset_index(drop=True)
        return df.tail(days).reset_index(drop=True)


# ═════ [source cell 7] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 3 — REGIME ENGINE                                                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Tại sao cần phát hiện Regime?
#   RSI=80 trong bull market → vẫn có thể mua tiếp
#   RSI=60 trong bear market → có thể đã là đỉnh
#   Cùng một setup kỹ thuật, kết quả khác nhau hoàn toàn tùy thị trường.
#
# Approach: đo VNINDEX, không đo từng mã
#   - EMA10/EMA30 cross → trend ngắn hạn
#   - SMA200 → trend dài hạn
#   - Momentum 5 phiên → tốc độ di chuyển
#   - ATR% → mức biến động → phân biệt Panic vs Bear bình thường
#
# Output: 4 regime + dynamic weights + score multiplier + win rate multiplier
#   Bull:     weights thiên momentum, multiplier 1.0
#   Sideways: weights thiên mean-reversion (VP, CMF), multiplier 0.95
#   Bear:     siết filter, giảm score 15%, multiplier 0.85
#   Panic:    chỉ giao dịch cực thận trọng, multiplier 0.70

class RegimeEngine:
    """
    Phát hiện Market Regime từ VNINDEX và tính Dynamic Weights.

    Thuật toán:
    1. Tính EMA10, EMA30, SMA200 của VNINDEX
    2. Đo momentum 5 phiên (mom5)
    3. Đo ATR% để phân biệt Panic (biến động cao + giảm mạnh)
    4. Rule-based classification → 4 regime
    5. Điều chỉnh BASE_WEIGHTS theo regime (REGIME_WEIGHT_DELTA)
    6. Normalize weights về tổng = 100

    Tại sao rule-based thay vì ML?
    - Data VNINDEX chỉ có từ 2000, không đủ cho supervised learning
    - Rule-based dễ audit, dễ debug, không overfit
    - Regime thay đổi chậm (tuần/tháng), không cần model phức tạp
    """

    def __init__(self, data_layer: DataLayer):
        self.dl      = data_layer
        self._regime = "sideways"
        self._ctx    = {}

    def detect(self) -> dict:
        print("  📊 VN-Index regime...", end=" ", flush=True)
        df = self.dl.fetch("VNINDEX", days=60)
        if df is None or len(df) < 30:
            print("⚠ neutral")
            self._regime = "sideways"
            self._ctx = {
                "regime": "sideways", "score_mult": 0.95,
                "label": "⚪ Không xác định", "vnindex": 0.0,
                "wr_mult": 1.0,
            }
            return self._ctx

        c     = df["close"]
        ema10 = c.ewm(span=10, adjust=False).mean()
        ema30 = c.ewm(span=30, adjust=False).mean()
        ma200 = c.rolling(200).mean() if len(c) >= 200 else ema30
        atr   = pd.concat([
            df["high"] - df["low"],
            (df["high"] - c.shift()).abs(),
            (df["low"]  - c.shift()).abs()
        ], axis=1).max(axis=1).rolling(14).mean()

        trend_up    = ema10.iloc[-1] > ema30.iloc[-1]
        above_ma200 = c.iloc[-1] > ma200.iloc[-1]
        mom5        = (c.iloc[-1] - c.iloc[-6]) / c.iloc[-6] * 100 if len(c) >= 6 else 0.0
        atr_norm    = atr.iloc[-1] / c.iloc[-1] * 100   # ATR% — chuẩn hóa theo giá
        high_vol    = atr_norm > 2.5                     # >2.5% là biến động cao bất thường

        # Thứ tự if-elif quan trọng: Panic > Bear > Bull > Sideways
        if   high_vol and mom5 < -2.0:                regime, label, ctx = "panic",    "🔴 PANIC — thận trọng tối đa",  1.5
        elif not trend_up and mom5 < -1.0:            regime, label, ctx = "bear",     "🔴 Downtrend — hạ tỷ trọng",    2.5
        elif trend_up and above_ma200 and mom5 > 1.0: regime, label, ctx = "bull",     "🟢 Uptrend — thuận chiều mua",  8.0
        elif trend_up and mom5 > -1.0:                regime, label, ctx = "sideways", "🟡 Uptrend nghỉ / tích lũy",   6.0
        else:                                          regime, label, ctx = "sideways", "🟡 Sideways — chọn lọc",       4.5

        mult = REGIME_SCORE_MULT[regime]
        print(f"✓  {c.iloc[-1]:,.2f}  |  {label}  |  5d:{mom5:+.1f}%  ATR:{atr_norm:.1f}%")

        self._regime = regime
        self._ctx = {
            "regime":        regime,
            "label":         label,
            "context_score": ctx,
            "score_mult":    mult,
            "wr_mult":       REGIME_WR_MULT[regime],
            "mom5":          round(mom5, 2),
            "vnindex":       round(float(c.iloc[-1]), 2),
            "atr_pct":       round(atr_norm, 2),
        }
        return self._ctx

    def get_dynamic_weights(self) -> dict:
        """
        Áp dụng delta lên BASE_WEIGHTS theo regime, normalize về tổng=100.

        Ví dụ Bull regime:
        - volume_ratio +3: momentum đang mạnh, volume quan trọng hơn
        - trend +5: uptrend rõ ràng, trọng số trend tăng
        - rsi -2: RSI cao không còn là cảnh báo mua đuổi trong bull
        """
        w = dict(BASE_WEIGHTS)
        delta = REGIME_WEIGHT_DELTA.get(self._regime, {})
        for k, d in delta.items():
            if k in w:
                w[k] = max(0, w[k] + d)
        total = sum(w.values())
        return {k: round(v / total * 100, 1) for k, v in w.items()}

    def get_min_score(self, mode: str, cfg: QuantConfig) -> float:
        """
        Nâng min_score khi thị trường xấu để lọc chặt hơn.
        context_score cao (≥7) = thị trường tốt → giữ ngưỡng gốc
        context_score thấp (<3.5) = thị trường xấu → tăng ngưỡng +1.5
        """
        base = cfg.min_score_swing if mode == "swing" else cfg.min_score_hold
        ctx  = self._ctx.get("context_score", 5.0)
        if   ctx >= 7.0: return base
        elif ctx >= 5.0: return base + 0.5
        elif ctx >= 3.5: return base + 1.0
        else:            return base + 1.5

    @property
    def regime(self) -> str:
        return self._regime

    @property
    def ctx(self) -> dict:
        return self._ctx


# ═════ [source cell 8] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 4 — VSA ENGINE  (NEW v5.2)                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Volume Spread Analysis (VSA) — đọc dấu chân Smart Money
#
# Tại sao chỉ volume_ratio và CMF chưa đủ?
#   - volume_ratio chỉ biết "nhiều hay ít", không biết "mua hay bán"
#   - CMF là lagging indicator (tính 21 phiên), phản ứng chậm
#   - Smart Money có thể giả tạo volume (pump & dump):
#     * Nổ volume MUA thực sự: volume lớn + spread rộng + đóng cửa CAO
#     * Xả hàng núp bóng:      volume lớn + spread rộng + đóng cửa THẤP
#     → Chỉ nhìn volume sẽ không phân biệt được
#
# Ba thành phần VSA:
#   1. Volume   : vol_ratio = volume / MA(volume, 20) → chuẩn hóa
#   2. Spread   : spread_ratio = (H-L) / MA(H-L, 20) → chuẩn hóa
#   3. Close Pos: (close - low) / spread → 0=đóng thấp nhất, 1=đóng cao nhất
#                 Đây là key để phân biệt mua thật vs xả hàng
#
# 5 trạng thái và logic:
#   🚀 NỔ VOL    : vol>1.5x AND spread>1.2x AND close_pos>0.7 AND roc>1.5%
#                  → Lực mua áp đảo, đóng gần đỉnh, breakout thực
#   🩸 CẠN VOL   : vol<0.6x AND spread<0.85x AND close_pos≥0.4 AND roc>-1.5%
#                  → Cung cạn, không ai bán, nền trước breakout
#   🔨 RÚT CHÂN  : vol>1.3x AND spread>1.3x AND close_pos>0.65 AND roc>-2%
#                  → Vol lớn nhưng đóng cao → rũ hàng yếu tay xong gom lại
#                  (v5.2 fix: roc > -0.02 thay vì < 0.01 để loại nến đỏ sâu)
#   ⚠️ PHÂN PHỐI : vol>1.5x AND close_pos<0.35 AND spread>1.0x AND roc<2%
#                  → Vol lớn nhưng đóng thấp → Smart Money đang xả
#   🥀 CẠN CẦU  : vol<0.6x AND close_pos<0.4 AND roc>0
#                  → Giá tăng nhẹ không có lực đỡ → breakout sẽ thất bại
#
# Implementation: np.select vectorized — O(n) trên toàn series, không loop
# → Có thể tính cho 1000 phiên trong microseconds

class VSAEngine:
    """
    Volume Spread Analysis — phát hiện hành vi Smart Money.

    Đọc 3 chiều cùng lúc: Volume × Spread × ClosePosition
    để phân biệt mua thật / xả hàng / rũ nền / cạn cung.

    Tất cả tính toán vectorized với numpy, không dùng loop Python.
    """

    @staticmethod
    def detect(df: pd.DataFrame, lookback: int = 30) -> pd.Series:
        """
        Tính VSA signal cho toàn bộ DataFrame.

        Parameters
        ----------
        df       : DataFrame với cột open, high, low, close, volume
        lookback : Cửa sổ rolling để tính MA volume và MA spread (mặc định 20)

        Returns
        -------
        pd.Series : VSA signal tại mỗi phiên (string label)
        """
        if df is None or len(df) < lookback + 2:
            return pd.Series(["—"] * len(df), index=df.index if df is not None else None)

        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

        # ── 1. Chuẩn hóa Volume ───────────────────────────────────────────────
        # vol_ratio > 1 → phiên này giao dịch nhiều hơn trung bình
        # Dùng replace(0, nan) tránh chia cho 0 khi mã ngưng GD
        avg_vol   = v.rolling(lookback).mean().replace(0, np.nan)
        vol_ratio = v / avg_vol

        # ── 2. Chuẩn hóa Spread (biên độ nến H-L) ───────────────────────────
        # spread_ratio > 1 → nến hôm nay rộng hơn trung bình
        spread      = h - l
        avg_spread  = spread.rolling(lookback).mean().replace(0, np.nan)
        spread_ratio = spread / avg_spread

        # ── 3. Vị trí đóng cửa trong nến (Close Position) ────────────────────
        # 0.0 = đóng tại đáy nến (bearish)
        # 0.5 = đóng giữa nến (neutral)
        # 1.0 = đóng tại đỉnh nến (bullish)
        # Xử lý doji (spread=0) → gán 0.5 (neutral)
        close_pos = np.where(spread == 0, 0.5, (c - l) / (spread + 1e-9))

        # ── 4. Rate of Change (1 phiên) ───────────────────────────────────────
        # Để lọc: nến tăng hay giảm bao nhiêu %
        roc = c.pct_change()

        # ── 5. Quy tắc VSA (thứ tự ưu tiên từ trên xuống) ───────────────────
        # np.select trả về choice tương ứng với condition đầu tiên = True
        # Nếu không match → default "—"

        conditions = [
            # 🚀 NỔ VOL: Lực mua áp đảo
            # Vol lớn (>1.5x) + Spread rộng (>1.2x) + Đóng gần đỉnh (>0.7) + Giá tăng (>1.5%)
            (vol_ratio > 1.5) & (spread_ratio > 1.2) & (close_pos > 0.7) & (roc > 0.015),

            # 🩸 CẠN VOL: Cung cạn kiệt, tiền thông minh đang gom âm thầm
            # Vol nhỏ (<0.6x) + Spread hẹp (<0.85x) + Không bị bán tháo (close_pos≥0.4)
            # + Không có roc âm sâu (<-1.5%) để loại panic sell
            (vol_ratio < 0.6) & (spread_ratio < 0.85) & (close_pos >= 0.4) & (roc > -0.015),

            # 🔨 RÚT CHÂN / GOM HÀNG: Rũ yếu tay xong đỡ lại
            # Vol lớn (>1.3x) + Spread rộng (>1.3x) + Đóng cao (>0.65) + KHÔNG phải nến đỏ sâu
            # v5.2 fix: roc > -0.02 (thay roc < 0.01) để loại nến đỏ giảm >2%
            (vol_ratio > 1.3) & (spread_ratio > 1.3) & (close_pos > 0.65) & (roc > -0.02),

            # ⚠️ PHÂN PHỐI: Smart Money đang xả hàng
            # Vol lớn (>1.5x) + Đóng thấp (<0.35 thân nến) + Spread rộng (>1.0x)
            # + Giá không tăng mạnh (<2%) → volume là để xả không phải mua
            (vol_ratio > 1.5) & (close_pos < 0.35) & (spread_ratio > 1.0) & (roc < 0.02),

            # 🥀 CẠN CẦU: Breakout fake — giá tăng không có người mua đỡ
            # Vol nhỏ (<0.6x) + Đóng thấp trong nến (<0.4) + Giá vẫn tăng nhẹ
            # → Người bán không nhiều nhưng người mua cũng không, breakout thiếu sức
            (vol_ratio < 0.6) & (close_pos < 0.4) & (roc > 0),
        ]

        choices = ["🚀 NỔ VOL", "🩸 CẠN VOL", "🔨 RÚT CHÂN", "⚠️ PHÂN PHỐI", "🥀 CẠN CẦU"]

        result = np.select(conditions, choices, default="—")
        return pd.Series(result, index=df.index)

    @staticmethod
    def get_latest(df: pd.DataFrame, lookback: int = 30) -> str:
        """Trả về VSA signal của phiên gần nhất."""
        signals = VSAEngine.detect(df, lookback)
        if signals is None or len(signals) == 0:
            return "—"
        return str(signals.iloc[-1])

    @staticmethod
    def to_score(vsa_signal: str) -> float:
        """
        Map VSA signal → điểm số để tích hợp vào ScoringEngine.

        Scale 0-10 để consistent với các indicator khác:
        - NỔ VOL:    8.5 (cực kỳ tích cực)
        - RÚT CHÂN:  8.0 (tích cực, setup gom hàng)
        - CẠN VOL:   7.0 (tích cực, nền tốt)
        - Neutral:   5.0 (không có tín hiệu rõ)
        - CẠN CẦU:   3.5 (tiêu cực nhẹ)
        - PHÂN PHỐI: 1.5 (tiêu cực mạnh)
        """
        return {
            "🚀 NỔ VOL":    8.5,
            "🔨 RÚT CHÂN":  8.0,
            "🩸 CẠN VOL":   7.0,
            "—":            5.0,
            "🥀 CẠN CẦU":  3.5,
            "⚠️ PHÂN PHỐI": 1.5,
        }.get(vsa_signal, 5.0)


# ═════ [source cell 9] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 4A — ICHIMOKU ITP ENGINE  (v5.5 — mở rộng W1/M1 flat + hotel)     ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# v5.5 CHANGELOG:
# - Mở rộng flat-detection + "Khách sạn" (hotel) sang khung W1/M1
#   (bản gốc chỉ có D1: d1_khach_san).
# - _safe_float(): tránh hiển thị "nan" thô khi dữ liệu chưa đủ dài
#   (đặc biệt Monthly cần rất nhiều lịch sử mới đủ 52 nến).

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional

class IchimokuITPEngine:
    """
    Ichimoku ITP Multi-Timeframe — D1/W1/M1, resample in-memory từ 1 lần
    fetch Daily duy nhất (không fetch riêng cho từng khung).

    QUAN TRỌNG: hàm extract_mtf_levels() yêu cầu tối thiểu 120 phiên Daily.
    Caller (run_pipeline) PHẢI truyền df dài (lookback_long), không phải
    df ngắn (lookback_short=40) — bug này từng khiến ichi["error"]=True
    ở gần như mọi trường hợp, vô hiệu hóa toàn bộ tính năng ITP.
    """

    HOTEL_THRESHOLD = {"d": 0.045, "w": 0.06, "m": 0.075}

    @staticmethod
    def _safe_float(x) -> Optional[float]:
        try:
            f = float(x)
            return None if np.isnan(f) else f
        except (TypeError, ValueError):
            return None

    @staticmethod
    def compute_base_ichimoku(df: pd.DataFrame, atr_mult: float = 1.5) -> pd.DataFrame:
        """Tính Ichimoku + Flat detection theo ATR (linh hoạt). (Giữ nguyên logic gốc)"""
        df = df.copy()
        if 'time' in df.columns:
            df = df.set_index('time').sort_index()

        df['tenkan'] = (df['high'].rolling(9).max() + df['low'].rolling(9).min()) / 2
        df['kijun']  = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2
        df['senkou_a'] = ((df['tenkan'] + df['kijun']) / 2).shift(26)
        df['senkou_b'] = (df['high'].rolling(52).max() + df['low'].rolling(52).min()) / 2
        df['senkou_b_shifted'] = df['senkou_b'].shift(26)

        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift()).abs(),
            (df['low'] - df['close'].shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        price_scale = df['close']
        flat_threshold = atr * atr_mult / price_scale

        df['kijun_diff'] = df['kijun'].diff()
        df['ssb_diff']   = df['senkou_b_shifted'].diff()

        df['is_kijun_flat'] = df['kijun_diff'].rolling(4).max().abs() <= flat_threshold
        df['is_ssb_flat']   = df['ssb_diff'].rolling(4).max().abs() <= flat_threshold

        return df

    @classmethod
    def _tf_snapshot(cls, last_row, tf_key: str) -> dict:
        """Trích xuất snapshot 1 khung thời gian (d/w/m) — logic dùng chung."""
        tenkan = cls._safe_float(last_row.get('tenkan'))
        kijun  = cls._safe_float(last_row.get('kijun'))
        ssb    = cls._safe_float(last_row.get('senkou_b_shifted'))

        kijun_flat = bool(last_row.get('is_kijun_flat')) if pd.notna(last_row.get('is_kijun_flat')) else False
        ssb_flat   = bool(last_row.get('is_ssb_flat'))   if pd.notna(last_row.get('is_ssb_flat'))   else False

        separation = abs(tenkan - kijun) / kijun if (tenkan is not None and kijun) else 0
        is_hotel = bool(separation > cls.HOTEL_THRESHOLD[tf_key] and kijun_flat)

        return {
            "tenkan": tenkan, "kijun": kijun, "ssb": ssb,
            "kijun_flat": kijun if kijun_flat else None,
            "ssb_flat":   ssb   if ssb_flat   else None,
            "khach_san":  is_hotel,
        }

    @classmethod
    def extract_mtf_levels(cls, df_d1: pd.DataFrame) -> dict:
        if df_d1 is None or len(df_d1) < 120:
            return {"error": True, "close": 0}

        df = df_d1.copy()
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'])
            df = df.set_index('time')

        df_d = cls.compute_base_ichimoku(df, atr_mult=1.5)
        df_w = df.resample('W').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
        df_w = cls.compute_base_ichimoku(df_w, atr_mult=2.0)
        df_m = df.resample('ME').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
        df_m = cls.compute_base_ichimoku(df_m, atr_mult=2.5)

        last_d = df_d.iloc[-1]
        last_w = df_w.iloc[-1] if len(df_w) > 0 else last_d
        last_m = df_m.iloc[-1] if len(df_m) > 0 else last_d

        snap_d = cls._tf_snapshot(last_d, "d")
        snap_w = cls._tf_snapshot(last_w, "w")
        snap_m = cls._tf_snapshot(last_m, "m")

        itp_strength = sum([
            1   if snap_d["kijun_flat"] is not None else 0,
            1   if snap_d["ssb_flat"]   is not None else 0,
            1   if snap_d["khach_san"] else 0,
            0.5 if snap_w["kijun_flat"] is not None else 0,
        ])

        return {
            "close": cls._safe_float(last_d['close']) or 0.0,
            "d1_tenkan": snap_d["tenkan"], "d1_kijun": snap_d["kijun"],
            "d1_kijun_flat": snap_d["kijun_flat"], "d1_ssb_flat": snap_d["ssb_flat"],
            "d1_khach_san": snap_d["khach_san"],
            "w1_kijun": snap_w["kijun"], "w1_ssb": snap_w["ssb"],
            "w1_kijun_flat": snap_w["kijun_flat"], "w1_ssb_flat": snap_w["ssb_flat"],
            "w1_khach_san": snap_w["khach_san"],
            "m1_kijun": snap_m["kijun"], "m1_ssb": snap_m["ssb"],
            "m1_kijun_flat": snap_m["kijun_flat"], "m1_ssb_flat": snap_m["ssb_flat"],
            "m1_khach_san": snap_m["khach_san"],
            "itp_strength": round(itp_strength, 1),
        }


# ═════ [source cell 10] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 4B — RSI / COMPOSITE INDEX DIVERGENCE ENGINE (v5.6)             ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Tái tạo ý tưởng từ Pine Script "Composite Index Divergence Indicator".
# Lưu ý: script gốc KHÔNG tìm divergence trên RSI(14) thuần; nó dùng
# Composite Index = Momentum(RSI14, 9) + SMA(RSI3, 3).
#
# 4 loại tín hiệu:
#   Regular Bullish : Price Lower Low + Oscillator Higher Low
#   Hidden Bullish  : Price Higher Low + Oscillator Lower Low
#   Regular Bearish : Price Higher High + Oscillator Lower High
#   Hidden Bearish  : Price Lower High + Oscillator Higher High
#
# Pivot lbR=5 chỉ được xác nhận sau 5 nến bên phải -> tránh look-ahead.
# Tỷ lệ ~75% của script gốc KHÔNG được hard-code thành xác suất thật;
# cần backtest riêng trên dữ liệu VN nếu muốn xác nhận.

class RSIDivergenceEngine:
    SIGNALS = {
        "regular_bullish": "🟢 RSI PHÂN KỲ DƯƠNG",
        "hidden_bullish": "🟢 RSI PHÂN KỲ DƯƠNG ẨN",
        "regular_bearish": "🔴 RSI PHÂN KỲ ÂM",
        "hidden_bearish": "🔴 RSI PHÂN KỲ ÂM ẨN",
        "none": "—",
    }

    @staticmethod
    def _rsi(close: pd.Series, length: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(length).mean()
        loss = (-delta.clip(upper=0)).rolling(length).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - 100 / (1 + rs)

    @classmethod
    def _composite_index(cls, close: pd.Series, cfg: QuantConfig) -> pd.Series:
        rsi_main = cls._rsi(close, cfg.divergence_rsi_length)
        rsi_mom = rsi_main.diff(cfg.divergence_rsi_mom_length)
        rsi_short = cls._rsi(close, cfg.divergence_rsi_ma_length)
        rsi_sma = rsi_short.rolling(cfg.divergence_ma_length).mean()
        return rsi_mom + rsi_sma

    @staticmethod
    def _pivot_lows(series: pd.Series, left: int, right: int) -> list:
        v = series.values; out=[]
        for i in range(left, len(v)-right):
            x=v[i]
            if not np.isfinite(x): continue
            w=v[i-left:i+right+1]
            if x == np.nanmin(w) and np.all(x < v[i-left:i]) and np.all(x <= v[i+1:i+right+1]): out.append(i)
        return out

    @staticmethod
    def _pivot_highs(series: pd.Series, left: int, right: int) -> list:
        v=series.values; out=[]
        for i in range(left, len(v)-right):
            x=v[i]
            if not np.isfinite(x): continue
            w=v[i-left:i+right+1]
            if x == np.nanmax(w) and np.all(x > v[i-left:i]) and np.all(x >= v[i+1:i+right+1]): out.append(i)
        return out

    @staticmethod
    def _in_range(p1:int,p2:int,lower:int,upper:int)->bool:
        return lower <= (p2-p1) <= upper

    @classmethod
    def detect(cls, df: pd.DataFrame, cfg: QuantConfig) -> dict:
        empty={"rsi_divergence":"—","rsi_divergence_type":"none","rsi_divergence_strength":0.0,
               "rsi_divergence_age":None,"rsi_divergence_confirmed":False,"rsi_divergence_pivot_date":None,
               "rsi_divergence_confirmed_date":None,"rsi_divergence_price_1":None,"rsi_divergence_price_2":None,
               "rsi_divergence_osc_1":None,"rsi_divergence_osc_2":None}
        if df is None or len(df) < 80: return empty
        try:
            work=df.copy().reset_index(drop=True)
            for col in ["open","high","low","close","volume"]: work[col]=pd.to_numeric(work[col],errors="coerce")
            close=work["close"]; hi=work["close"] if cfg.divergence_use_close else work["high"]; lo=work["close"] if cfg.divergence_use_close else work["low"]
            osc=cls._composite_index(close,cfg); L=cfg.divergence_lb_left; R=cfg.divergence_lb_right
            lows=cls._pivot_lows(osc,L,R); highs=cls._pivot_highs(osc,L,R); cand=[]
            for p2 in lows:
                prev=[p for p in lows if p<p2]
                if not prev: continue
                p1=prev[-1]
                if not cls._in_range(p1,p2,cfg.divergence_range_lower,cfg.divergence_range_upper): continue
                a,b=float(lo.iloc[p1]),float(lo.iloc[p2]); x,y=float(osc.iloc[p1]),float(osc.iloc[p2])
                if not np.isfinite([a,b,x,y]).all(): continue
                if b<a and y>x: cand.append(("regular_bullish",p2,a,b,x,y))
                if b>a and y<x: cand.append(("hidden_bullish",p2,a,b,x,y))
            for p2 in highs:
                prev=[p for p in highs if p<p2]
                if not prev: continue
                p1=prev[-1]
                if not cls._in_range(p1,p2,cfg.divergence_range_lower,cfg.divergence_range_upper): continue
                a,b=float(hi.iloc[p1]),float(hi.iloc[p2]); x,y=float(osc.iloc[p1]),float(osc.iloc[p2])
                if not np.isfinite([a,b,x,y]).all(): continue
                if b>a and y<x: cand.append(("regular_bearish",p2,a,b,x,y))
                if b<a and y>x: cand.append(("hidden_bearish",p2,a,b,x,y))
            if not cand: return empty
            typ,pivot,p1price,p2price,o1,o2=max(cand,key=lambda z:z[1])
            confirmed=pivot+R; age=(len(work)-1)-confirmed
            if age<0 or age>cfg.divergence_max_age_bars: return empty
            price_gap=abs(p2price-p1price)/(abs(p1price)+1e-9)*100; osc_gap=abs(o2-o1)
            strength=min(10.0,4.0+min(price_gap*0.8,2.5)+min(osc_gap*0.15,2.0)+(1.0 if typ.startswith("regular") else 0.3))
            dates=None
            if "time" in df.columns: dates=pd.to_datetime(df["time"],errors="coerce").reset_index(drop=True)
            elif isinstance(df.index,pd.DatetimeIndex): dates=pd.to_datetime(df.index)
            pdate=str(dates.iloc[pivot]) if dates is not None and pivot<len(dates) else None
            cdate=str(dates.iloc[confirmed]) if dates is not None and confirmed<len(dates) else None
            text=cls.SIGNALS[typ]+(f" ({age} phiên sau xác nhận)" if age>0 else " (vừa xác nhận)")
            return {"rsi_divergence":text,"rsi_divergence_type":typ,"rsi_divergence_strength":round(strength,2),
                    "rsi_divergence_age":int(age),"rsi_divergence_confirmed":True,"rsi_divergence_pivot_date":pdate,
                    "rsi_divergence_confirmed_date":cdate,"rsi_divergence_price_1":round(p1price,4),
                    "rsi_divergence_price_2":round(p2price,4),"rsi_divergence_osc_1":round(o1,4),"rsi_divergence_osc_2":round(o2,4)}
        except Exception:
            return empty

    @classmethod
    def multi_timeframe(cls, df_d1: pd.DataFrame, cfg: QuantConfig) -> dict:
        empty={"D1":cls.detect(df_d1,cfg),"W1":cls.detect(pd.DataFrame(),cfg),"M1":cls.detect(pd.DataFrame(),cfg)}
        if df_d1 is None or len(df_d1)<120: return empty
        df=df_d1.copy()
        if "time" in df.columns:
            df["time"]=pd.to_datetime(df["time"],errors="coerce"); df=df.dropna(subset=["time"]).set_index("time").sort_index()
        elif not isinstance(df.index,pd.DatetimeIndex): return empty
        cols=["open","high","low","close","volume"]
        d1=df[cols].copy(); w1=d1.resample("W-FRI").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna(subset=["close"]); m1=d1.resample("ME").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna(subset=["close"])
        return {"D1":cls.detect(d1.reset_index(),cfg),"W1":cls.detect(w1.reset_index(),cfg),"M1":cls.detect(m1.reset_index(),cfg)}



# ═════ [source cell 11] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 5 — INDICATOR ENGINE                                              ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Tính toàn bộ chỉ báo kỹ thuật từ OHLCV thuần Python/numpy/pandas.
# Không dùng thư viện ta hay pandas_ta để tránh dependency.
#
# Nhóm chỉ báo:
#   Volume   : volume_ratio, OBV, CMF, Force Index
#   Momentum : RSI14, MACD(12,26,9), Stochastic(14,3)
#   Trend    : EMA20, EMA50, SMA50, SMA200 (long_trend)
#   Structure: Volume Profile (POC/VAH/VAL), Bollinger Band %B
#   Relative : RS so với VNINDEX (20 phiên)
#   Flow     : Institutional flow estimate (AD line 5/20)
#   VSA      : (tách riêng, call VSAEngine.get_latest)
#
# Tất cả output là float/bool/str được pack vào dict `raw`
# để ScoringEngine chấm điểm và SignalBuilder tính levels

class IndicatorEngine:
    """
    Tính toàn bộ chỉ báo kỹ thuật từ OHLCV.

    v5.2.1 CHANGELOG:
    - relative_strength: sửa lỗi đảo dấu khi VNINDEX giảm (rv < 0).
      Công thức cũ dùng (rs/d)*sign(rv) ≡ rs/rv — một phép CHIA hai
      đại lượng có thể âm, khiến mã yếu hơn thị trường trong nhịp
      giảm lại ra điểm dương (và ngược lại). Công thức mới dùng
      HIỆU SỐ (rs - rv) trước khi chuẩn hóa theo biến động index.
    - volume_profile: đảm bảo Value Area luôn tích lũy đủ ≥68.2%
      volume bằng vòng lặp thay vì filter cumsum (tránh co cụm
      lặng lẽ khi bin lớn nhất đã vượt ngưỡng).
    """

    @staticmethod
    def volume_profile(df: pd.DataFrame, n_bins: int = 30) -> dict:
        """
        Volume Profile — tìm vùng giá giao dịch nhiều nhất.

        Thuật toán:
        1. Chia range giá (Low_min → High_max) thành n_bins vùng bằng nhau
        2. Gán mỗi phiên vào bin theo Typical Price = (H+L+C)/3
        3. Cộng dồn volume vào mỗi bin
        4. POC = bin có volume cao nhất
        5. Value Area = tích lũy các bin (giảm dần theo volume) cho tới
           khi đạt ≥68.2% tổng volume (1 std dev)
           → VAH = đỉnh Value Area, VAL = đáy Value Area

        v5.2.1: dùng vòng lặp tích lũy tới khi ĐẠT ngưỡng thay vì
        filter `cumsum <= target`. Bản cũ có thể trả về tập rỗng nếu
        bin đầu tiên đã chiếm >68.2% volume — fallback vah=val=poc
        vẫn chạy được nhưng là silent-fail. Bản mới luôn có ít nhất
        1 bin trong VA (đúng theo lý thuyết Market Profile: nếu POC
        áp đảo tuyệt đối thì VA chính là một điểm, không phải bug).
        """
        if len(df) < 25:
            return {"poc": None, "vah": None, "val": None, "vp_signal": "unknown"}
        try:
            lo, hi = df["low"].min(), df["high"].max()
            sz     = (hi - lo) / n_bins
            edges  = np.arange(lo, hi + sz + 1e-9, sz)
            df2    = df.copy()
            df2["tp"]  = (df2["high"] + df2["low"] + df2["close"]) / 3
            df2["bin"] = pd.cut(df2["tp"], bins=edges, labels=edges[:-1], include_lowest=True)
            vp     = df2.groupby("bin", observed=True)["volume"].sum()
            poc    = float(vp.idxmax())
            srt    = vp.sort_values(ascending=False)

            # ── Value Area: tích lũy tới khi đạt ≥68.2% volume ────────────────
            target  = vp.sum() * 0.682
            cum     = 0.0
            va_bins = []
            for idx, val in srt.items():
                va_bins.append(idx)
                cum += val
                if cum >= target:
                    break

            vah = float(max(va_bins))
            val = float(min(va_bins))
            close = float(df["close"].iloc[-1])
            noise = poc * 0.015  # Buffer 1.5% để tránh tín hiệu nhiễu

            if   close > vah * 1.005:       sig = "breakout"
            elif close < val * 0.995:       sig = "below_value"
            elif abs(close - poc) <= noise: sig = "at_poc"
            else:                           sig = "value_area"
            return {"poc": round(poc, 2), "vah": round(vah, 2), "val": round(val, 2), "vp_signal": sig}
        except Exception:
            return {"poc": None, "vah": None, "val": None, "vp_signal": "unknown"}

    @staticmethod
    def long_trend(df_long: pd.DataFrame) -> dict:
        """
        Phân loại xu hướng dài hạn dựa trên vị trí giá vs SMA50/SMA200.
        (Giữ nguyên logic v5.2 — không có bug được báo cáo ở hàm này.)
        """
        if df_long is None or len(df_long) < 60:
            return {"trend_long": "sideway", "sma50": None, "sma200": None}

        c       = df_long["close"]
        sma50_s = c.rolling(50).mean()
        sma50   = float(sma50_s.iloc[-1])
        close   = float(c.iloc[-1])

        past50  = float(sma50_s.iloc[-10]) if len(sma50_s) >= 10 else sma50
        slope50 = (sma50 - past50) / (past50 + 1e-9)
        dist50  = (close - sma50) / (sma50 + 1e-9)

        sma200 = None
        if len(c) >= 200:
            sma200_s = c.rolling(200).mean()
            sma200   = float(sma200_s.iloc[-1])
            past200  = float(sma200_s.iloc[-20]) if len(sma200_s) >= 20 else sma200
            slope200 = (sma200 - past200) / (past200 + 1e-9)

            if close > sma50 and close > sma200:
                trend = "uptrend" if sma50 > sma200 and slope200 > -0.005 else "weak_up"
            elif close < sma50 and close < sma200:
                trend = "downtrend"
            elif close > sma50 and close < sma200:
                trend = "weak_up" if slope50 > 0.005 and dist50 > 0.015 else "sideway"
            elif close < sma50 and close > sma200:
                trend = "downtrend" if dist50 < -0.04 or slope50 < -0.01 else "sideway"
            else:
                trend = "sideway"
        else:
            if   close > sma50: trend = "weak_up"   if slope50 > 0 else "sideway"
            elif close < sma50: trend = "downtrend"  if slope50 < 0 or dist50 < -0.04 else "sideway"
            else:               trend = "sideway"

        return {
            "trend_long": trend,
            "sma50":  round(sma50, 2),
            "sma200": round(sma200, 2) if sma200 else None,
        }

    @staticmethod
    def relative_strength(df_stk: pd.DataFrame, df_vni: pd.DataFrame, period: int = 20) -> float:
        """
        Relative Strength (Alpha) so với VNINDEX — FIXED v5.2.1.

        RS = (return_stock - return_vni) / max(|return_vni|, 1%)

        BUG ĐÃ SỬA: công thức cũ dùng (rs/d) * sign(rv), về mặt đại số
        tương đương rs/rv — tức là lấy TỶ LỆ giữa hai đại lượng có thể
        âm. Khi rv < 0 (VNINDEX giảm), phép chia cho số âm đảo dấu toàn
        bộ kết quả:
          - Mã giảm sâu hơn index (yếu hơn) → ra điểm DƯƠNG (sai)
          - Mã tăng ngược trong khi index giảm (mạnh vượt trội) → ra
            điểm ÂM (sai)

        Công thức mới dùng HIỆU SỐ (rs - rv) — đúng bản chất "alpha"
        trong quant: đo khoảng vượt trội/tụt hậu tuyệt đối so với
        benchmark, sau đó mới chuẩn hóa theo biến động benchmark (d)
        để so sánh cross-sector. Hiệu số không bao giờ đảo dấu bất kể
        rv âm hay dương.

        RS > 0 : mã mạnh hơn thị trường (alpha dương)
        RS < 0 : mã yếu hơn thị trường (alpha âm)
        RS = 0 : trung tính / đồng pha với index

        LƯU Ý: đổi công thức làm thay đổi thang đo của rs so với v5.1.
        Các ngưỡng dùng rs ở WinRateEstimator ("rs_strong">1.5,
        "rs_weak"<0.5) và ScoringEngine (rs*4.2+1.8) vẫn nằm trong dải
        hợp lý nhưng nên backtest lại phân phối rs thực tế trên vài
        chục mã trước khi tin tưởng hoàn toàn ngưỡng cũ.
        """
        if df_stk is None or df_vni is None: return 0.0
        if len(df_stk) < period or len(df_vni) < period: return 0.0
        try:
            s_s = df_stk["close"].rolling(3).mean()
            v_s = df_vni["close"].rolling(3).mean()
            rs  = s_s.iloc[-1] / s_s.iloc[-period] - 1
            rv  = v_s.iloc[-1] / v_s.iloc[-period] - 1

            d    = max(abs(rv), 0.01)   # sàn 1% để tránh chia cho ~0 khi index đi ngang
            diff = rs - rv              # alpha thực — luôn đúng dấu

            return float(max(min(diff / d, 10.0), -10.0))
        except:
            return 0.0

    @staticmethod
    def money_flow(df: pd.DataFrame) -> dict:
        """Ước tính dòng tiền tổ chức từ Accumulation/Distribution line. (Giữ nguyên)"""
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        clv    = ((c - l) - (h - c)) / (h - l + 1e-9)
        ad     = (clv * v).cumsum()
        ad5    = ad.ewm(span=5,  adjust=False).mean()
        ad20   = ad.ewm(span=20, adjust=False).mean()
        inst_up = bool(ad5.iloc[-1] > ad20.iloc[-1])
        ad_roc  = float((ad.iloc[-1] - ad.iloc[-6]) / (v.rolling(20).mean().iloc[-1] * 5 + 1e-9)) if len(df) >= 6 else 0

        if   inst_up and ad_roc > 0.3: inst_score = 9.0
        elif inst_up and ad_roc > 0:   inst_score = 7.0
        elif inst_up:                  inst_score = 5.5
        elif ad_roc > 0:               inst_score = 4.0
        else:                          inst_score = 2.0

        cs     = (c - l) / (h - l + 1e-9)
        cs5    = float(cs.rolling(5).mean().iloc[-1])
        cs20   = float(cs.rolling(20).mean().iloc[-1])
        smart  = bool(cs5 > cs20 and cs5 > 0.55)

        vol_ma = v.rolling(20).mean()
        tr     = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr    = tr.rolling(14).mean()
        vr     = v / (vol_ma + 1e-9)
        hl     = (h - l) / (atr + 1e-9)
        b_acc  = bool(vr.iloc[-1] > 2.0 and hl.iloc[-1] < 1.5 and c.iloc[-1] > c.iloc[-2])
        b_brk  = bool(vr.iloc[-1] > 2.5 and (c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] > 0.01)

        n = sum([inst_up, smart, b_acc or b_brk])
        if   b_brk: label = "🏦 Tổ chức đẩy"
        elif b_acc: label = "🔍 Tích lũy lặng lẽ"
        elif n >= 2: label = "💰 Tiền lớn vào"
        elif n == 1: label = "🔄 Trung tính"
        else:        label = "📤 Tiền lớn rút"

        return {"inst_flow": inst_score, "inst_flow_up": inst_up,
                "smart_money": smart, "block_accum": b_acc, "block_break": b_brk, "mf_label": label}

    @staticmethod
    def compute_all(df: pd.DataFrame, vp: dict, trend: dict,
                rs: float, mf: dict, vsa_signal: str,
                df_long: pd.DataFrame = None, divergence: dict = None,
                divergence_mtf: dict = None) -> dict:
        """Tổng hợp tất cả indicators vào dict `raw`. (Giữ nguyên logic v5.2)"""
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        R = {"close": round(float(c.iloc[-1]), 2), "volume": int(v.iloc[-1])}

        vol_ma20 = v.rolling(20).mean().iloc[-1]
        R["volume_ratio"] = round(v.iloc[-1] / vol_ma20, 2) if vol_ma20 > 0 else 0.0
        R["avg_vol_20d"]  = int(vol_ma20)
        R["avg_val_20d"]  = round(float(vol_ma20 * c.rolling(20).mean().iloc[-1]), 0)

        obv = (np.sign(c.diff().fillna(0)) * v).cumsum()
        R["obv_signal"] = 1 if obv.rolling(5).mean().iloc[-1] > obv.rolling(20).mean().iloc[-1] else -1
        if len(df) >= 6:
            y  = obv.iloc[-6:].values.astype(float)
            sl = float(np.polyfit(np.arange(6, dtype=float), y, 1)[0])
            R["obv_slope"] = round(sl / (abs(float(obv.iloc[-6])) + 1e-9) * 100, 2)
        else:
            R["obv_slope"] = 0.0

        mfv = ((c - l) - (h - c)) / (h - l + 1e-9) * v
        R["cmf"] = round(float((mfv.rolling(21).sum() / v.rolling(21).sum().replace(0, np.nan)).iloc[-1]), 4)

        fi   = (c.diff() * v).ewm(span=13, adjust=False).mean()
        fima = fi.abs().rolling(20).mean().iloc[-1]
        R["force_index"] = round(float(fi.iloc[-1]) / (fima + 1e-9), 4)

        for k in ["inst_flow", "inst_flow_up", "smart_money", "block_accum", "block_break", "mf_label"]:
            R[k] = mf.get(k)

        delta = c.diff()
        g  = delta.clip(lower=0).rolling(14).mean()
        ls = (-delta.clip(upper=0)).rolling(14).mean()
        R["rsi"] = round(float((100 - 100 / (1 + g / ls.replace(0, np.nan))).iloc[-1]), 2)

        ema20 = c.ewm(span=20, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()
        R["ema_pct"] = round(float((c.iloc[-1] - ema20.iloc[-1]) / ema20.iloc[-1] * 100), 2)
        R["ema20"]   = round(float(ema20.iloc[-1]), 2)
        R["ema50"]   = round(float(ema50.iloc[-1]), 2)

        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        ml    = ema12 - ema26
        ms    = ml.ewm(span=9, adjust=False).mean()
        mh    = ml - ms
        R["macd_hist_pct"]  = round(float(mh.iloc[-1]) / (float(c.iloc[-1]) + 1e-9) * 100, 4)
        R["macd_cross_up"]  = bool(mh.iloc[-1] > 0 and mh.iloc[-2] <= 0)

        l14 = l.rolling(14).min()
        h14 = h.rolling(14).max()
        sk  = (c - l14) / (h14 - l14 + 1e-9) * 100
        sd  = sk.rolling(3).mean()
        R["stoch_k"]        = round(float(sk.iloc[-1]), 2)
        R["stoch_d"]        = round(float(sd.iloc[-1]), 2)
        R["stoch_cross_up"] = bool(sk.iloc[-1] > sd.iloc[-1] and sk.iloc[-2] <= sd.iloc[-2])

        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        R["atr_ratio"] = round(float(tr.rolling(14).mean().iloc[-1]) / (float(c.iloc[-1]) + 1e-9) * 100, 2)
        R["atr_abs"]   = round(float(tr.rolling(14).mean().iloc[-1]), 2)

        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        R["bb_pctb"] = round(float((c - (sma20 - 2 * std20)).iloc[-1]) / (float(4 * std20.iloc[-1]) + 1e-9), 4)

        R.update({k: vp.get(k) for k in ["vp_signal", "poc", "vah", "val"]})
        R["trend_long"] = trend.get("trend_long", "sideway")
        R["sma50"]      = trend.get("sma50")
        R["sma200"]     = trend.get("sma200")
        R["rs"]         = round(float(rs), 2) if isinstance(rs, (int, float)) else 0.0

        R["vsa_signal"] = vsa_signal

        # === RSI / Composite Index Divergence (v5.6) =========================
        div = divergence or {}
        R.update({
            "rsi_divergence": div.get("rsi_divergence", "—"),
            "rsi_divergence_type": div.get("rsi_divergence_type", "none"),
            "rsi_divergence_strength": div.get("rsi_divergence_strength", 0.0),
            "rsi_divergence_age": div.get("rsi_divergence_age"),
            "rsi_divergence_confirmed": div.get("rsi_divergence_confirmed", False),
            "rsi_divergence_pivot_date": div.get("rsi_divergence_pivot_date"),
            "rsi_divergence_confirmed_date": div.get("rsi_divergence_confirmed_date"),
            "rsi_divergence_mtf": divergence_mtf or {},
        })

        # === ICHIMOKU ITP (v5.5 fix) ===
        # BUG gốc: dùng `df` (lookback_short=40) trong khi extract_mtf_levels
        # yêu cầu >=120 phiên → luôn error=True, tính năng ITP không chạy thật.
        ichi_src = df_long if df_long is not None and len(df_long) >= 120 else df
        ichi = IchimokuITPEngine.extract_mtf_levels(ichi_src)
        R.update({
            "ichi": ichi,
            "d1_kijun": ichi.get("d1_kijun"),
            "d1_kijun_flat": ichi.get("d1_kijun_flat"),
            "d1_khach_san": ichi.get("d1_khach_san"),
            "w1_kijun": ichi.get("w1_kijun"),
            "itp_strength": ichi.get("itp_strength", 0),
        })

        return R


# ═════ [source cell 12] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 5B — ITP TOUCH + MA CONTEXT + HOLDER ADVISOR  (NEW v5.5)         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class ItpTouchAnalyzer:
    """
    Xác định giá hiện tại có đang CHẠM vùng Dao Găm (Kijun/SenkouB flat)
    trên D1/W1/M1 hay không, dùng khung sai số (tolerance zone) 1.5%
    thay vì so sánh bằng tuyệt đối.

    'Dao găm' = đường Kijun-sen hoặc Senkou B đang FLAT (is_kijun_flat/
    is_ssb_flat = True). Nếu đường đang dốc, không coi là dao găm — vì
    bản chất dao găm là vùng giá đã tích tụ đủ lâu, không phải MA thường.
    """

    TOUCH_TOL = 0.015  # 1.5% — khung sai số "chạm" theo tư duy Quant

    @staticmethod
    def _touch_status(close: float, level: float) -> str:
        dist_pct = (close - level) / level * 100
        if abs(dist_pct) <= ItpTouchAnalyzer.TOUCH_TOL * 100:
            return f"Chạm ({dist_pct:+.1f}%)"
        elif dist_pct > 0:
            return f"Trên +{dist_pct:.1f}%"
        else:
            return f"Dưới {dist_pct:.1f}%"

    @classmethod
    def analyze(cls, ichi: dict) -> dict:
        empty = {"ITP Dao Găm D1": "—", "ITP Dao Găm W1/M1": "—",
                  "Khoảng cách hỗ trợ ITP %": None}
        if not ichi or ichi.get("error") or ichi.get("close", 0) <= 0:
            return empty

        close = ichi["close"]

        # ── D1 ──────────────────────────────────────────────────────────────
        d1_parts = []
        if ichi.get("d1_kijun_flat"):
            d1_parts.append(f"DG-Kijun D1: {cls._touch_status(close, ichi['d1_kijun_flat'])}")
        if ichi.get("d1_ssb_flat"):
            d1_parts.append(f"DG-SSB D1: {cls._touch_status(close, ichi['d1_ssb_flat'])}")
        if ichi.get("d1_khach_san"):
            d1_parts.append("🏨 Khách sạn D1")
        d1_txt = " | ".join(d1_parts) if d1_parts else "Không có DG D1"

        # ── W1/M1 ───────────────────────────────────────────────────────────
        wm_parts = []
        for tf, kijun_key, ssb_key, hotel_key, label in [
            ("W1", "w1_kijun_flat", "w1_ssb_flat", "w1_khach_san", "W1"),
            ("M1", "m1_kijun_flat", "m1_ssb_flat", "m1_khach_san", "M1"),
        ]:
            if ichi.get(kijun_key):
                wm_parts.append(f"DG-Kijun {label}: {cls._touch_status(close, ichi[kijun_key])}")
            if ichi.get(ssb_key):
                wm_parts.append(f"DG-SSB {label}: {cls._touch_status(close, ichi[ssb_key])}")
            if ichi.get(hotel_key):
                wm_parts.append(f"🏨 Khách sạn {label}")
        wm_txt = " | ".join(wm_parts) if wm_parts else "Không có DG W1/M1"

        # ── Bonus: khoảng cách tới hỗ trợ ITP gần nhất bên dưới giá ─────────
        supports = [v for k in ["d1_kijun_flat", "d1_ssb_flat", "w1_kijun_flat",
                                 "w1_ssb_flat", "m1_kijun_flat", "m1_ssb_flat"]
                    if (v := ichi.get(k)) and v > 0 and v < close]
        nearest_pct = round((close - max(supports)) / close * 100, 2) if supports else None

        tf_status = {}
        for tf, keys in {"D1":["d1_kijun_flat","d1_ssb_flat"],"W1":["w1_kijun_flat","w1_ssb_flat"],"M1":["m1_kijun_flat","m1_ssb_flat"]}.items():
            parts=[]
            for key in keys:
                level=ichi.get(key)
                if level: parts.append(cls._touch_status(close,level))
            hotel_key=f"{tf.lower()}_khach_san"
            if ichi.get(hotel_key): parts.append("🏨 Khách sạn")
            tf_status[tf]=" | ".join(parts) if parts else "Không có DG"
        return {
            "ITP Dao Găm D1": d1_txt,
            "ITP Dao Găm W1/M1": wm_txt,
            "ITP Dao Găm D1 Status": tf_status["D1"],
            "ITP Dao Găm W1 Status": tf_status["W1"],
            "ITP Dao Găm M1 Status": tf_status["M1"],
            "Khoảng cách hỗ trợ ITP %": nearest_pct,
        }


class MAContextEngine:
    """
    Trạng thái giá so với MA9/MA10 (ngắn hạn) và MA50/MA200 (trung-dài hạn).

    Gãy đồng thời cả MA9 và MA10 = tín hiệu "mất xu hướng tăng ngắn hạn"
    theo trường phái lướt sóng theo MA ngắn phổ biến ở VN — không phải
    dấu hiệu đảo chiều dài hạn, chỉ là cảnh báo động lượng ngắn suy yếu.
    """

    TOUCH_TOL = 0.015

    @staticmethod
    def compute(df: pd.DataFrame, raw: dict) -> dict:
        if df is None or len(df) < 12:
            return {"MA Context": "—", "_short_trend_broken": False}

        c = df["close"]
        ma9_v  = float(c.rolling(9).mean().iloc[-1])
        ma10_v = float(c.rolling(10).mean().iloc[-1])
        close  = float(c.iloc[-1])

        sma50, sma200 = raw.get("sma50"), raw.get("sma200")
        parts = []

        broken_short = bool(close < ma9_v and close < ma10_v)
        if broken_short:
            parts.append("⚠️ Gãy MA9/MA10 (Mất xu hướng ngắn hạn)")

        for ma_val, name in [(sma50, "MA50"), (sma200, "MA200")]:
            if not ma_val:
                continue
            dist = (close - ma_val) / ma_val * 100
            if abs(dist) <= MAContextEngine.TOUCH_TOL * 100:
                parts.append(f"Chạm {name} ({dist:+.1f}%)")
            elif dist > 0:
                parts.append(f"Trên {name} (+{dist:.1f}%)")
            else:
                parts.append(f"Dưới {name} ({dist:.1f}%)")

        return {
            "MA Context": " | ".join(parts) if parts else "—",
            "_short_trend_broken": broken_short,
        }


class HolderAdvisor:
    """
    Khuyến nghị cho người ĐANG NẮM GIỮ cổ phiếu — khác cột "Tín hiệu"/
    "Khuyến nghị" hiện có (dành cho người TÌM ĐIỂM MUA MỚI). Robot không
    biết giá vốn thực của người dùng nên toàn bộ dựa trên TRẠNG THÁI KỸ
    THUẬT hiện tại, không dựa trên %lãi/lỗ cá nhân.

    Thứ tự ưu tiên (nghiêm trọng nhất xét trước):
    1. CẮT LỖ/BÁN HẾT — thủng vùng đỡ cứng (MA50) + downtrend hoặc CMF âm nặng
    2. HẠ TỶ TRỌNG    — vẫn uptrend nhưng vừa gãy MA9/10 kèm Vol cao (chốt lời)
    3. GIA TĂNG       — uptrend + VSA tích cực + đang test thành công vùng đỡ
    4. HOLD MẠNH      — uptrend sạch, chưa có cảnh báo
    5. THEO DÕI       — mặc định
    """

    @staticmethod
    def advise(raw: dict, ma_ctx: dict, itp_touch: dict, dryup: dict) -> dict:
        trend        = raw.get("trend_long", "sideway")
        vsa          = raw.get("vsa_signal", "—")
        cmf          = raw.get("cmf", 0.0)
        vol_ratio    = raw.get("volume_ratio", 1.0)
        short_broken = ma_ctx.get("_short_trend_broken", False)
        sma50        = raw.get("sma50")
        close        = raw.get("close", 0)

        vsa_positive = vsa in ["🚀 NỔ VOL", "🔨 RÚT CHÂN", "🩸 CẠN VOL"]
        vsa_negative = vsa == "⚠️ PHÂN PHỐI"
        below_ma50_hard = bool(sma50 and close < sma50 * 0.985)

        # ── 1. Cắt lỗ / Bán hết ──────────────────────────────────────────────
        if (trend == "downtrend" and (below_ma50_hard or cmf < -0.15)) or (below_ma50_hard and vsa_negative):
            reason = []
            if trend == "downtrend": reason.append("Xu hướng dài hạn đã đảo chiều xuống")
            if below_ma50_hard:      reason.append("Giá thủng MA50 (mất vùng đỡ trung hạn)")
            if cmf < -0.15:          reason.append(f"Dòng tiền rút mạnh (CMF={cmf:.3f})")
            if vsa_negative:         reason.append("VSA cho thấy đang bị xả (Phân phối)")
            return {"Holder Action": "🚫 CẮT LỖ / BÁN HẾT", "Holder Reason": "; ".join(reason)}

        # ── 2. Hạ tỷ trọng ────────────────────────────────────────────────────
        if short_broken and trend in ("uptrend", "weak_up") and vol_ratio > 1.2:
            return {
                "Holder Action": "⚠️ HẠ TỶ TRỌNG 30-50%",
                "Holder Reason": (f"Gãy MA9/MA10 kèm Vol tăng ({vol_ratio:.1f}x TB) trong khi xu hướng "
                                   f"dài hạn ({trend}) chưa đổi — dấu hiệu chốt lời ngắn hạn, nên khóa "
                                   f"một phần lợi nhuận, phần còn lại theo dõi MA50."),
            }

        # ── 3. Gia tăng vị thế ───────────────────────────────────────────────
        touching_support = ("Chạm" in ma_ctx.get("MA Context", "") or
                            "Chạm" in itp_touch.get("ITP Dao Găm D1", "") or
                            "Chạm" in itp_touch.get("ITP Dao Găm W1/M1", ""))
        if trend in ("uptrend", "weak_up") and vsa_positive and touching_support:
            return {
                "Holder Action": "🚀 GIA TĂNG VỊ THẾ",
                "Holder Reason": (f"Uptrend nguyên vẹn, VSA xác nhận dòng tiền vào ({vsa}), đang test "
                                   f"thành công vùng đỡ mạnh — R:R tốt vì SL đặt sát vùng đỡ vừa test."),
            }

        # ── 4. Hold mạnh ─────────────────────────────────────────────────────
        if trend == "uptrend" and not short_broken:
            return {"Holder Action": "💎 HOLD MẠNH",
                    "Holder Reason": "Xu hướng dài và ngắn hạn đồng thuận tăng, chưa có cảnh báo nào kích hoạt."}

        # ── 5. Theo dõi ──────────────────────────────────────────────────────
        return {"Holder Action": "👀 THEO DÕI",
                "Holder Reason": "Chưa đủ tín hiệu rõ ràng; theo dõi thêm diễn biến MA9/10 và dòng tiền."}


# ═════ [source cell 13] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 6 — VOLUME DRY-UP DETECTOR                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Wyckoff Spring / Volume Dry-up — một trong những setup mạnh nhất VN
#
# Lý thuyết Wyckoff:
#   Phase A: Selling Climax — bán tháo với volume lớn
#   Phase B: Accumulation — gom hàng âm thầm, volume giảm dần
#   Phase C: Spring — thử thách đáy cuối (volume bùng sau nền khô)
#   Phase D: Markup — bắt đầu sóng tăng
#
# Detector này focus vào Phase B→C:
#   - Volume khô dần (cung cạn)
#   - Biên độ nến hẹp dần (không ai giao dịch)
#   - Không có nến đỏ mạnh kèm volume (không phân phối)
#   → Khi 3 điều kiện thỏa = nền đang hoàn tất
#
# Spring detection:
#   Volume đột tăng >1.5× MA20 SAU ít nhất n-1 phiên khô
#   + Giá đóng cửa tăng → Smart Money vừa kích hoạt

class VolumeDryupDetector:
    """
    Phát hiện nền cạn cung (Volume Dry-up) — Wyckoff Phase B/C.

    3 thành phần kiểm tra:
    1. Vol 5 phiên gần < 70% MA20 (cung cạn kiệt)
    2. Biên độ nến hẹp hơn ATR14 × 75% (nền tích lũy yên tĩnh)
    3. Không có nến đỏ mạnh kèm volume cao (không phân phối)

    Bonus: Wyckoff Spring — volume đột tăng sau nền khô, giá đóng cao.

    Output gồm: flag, strength 0-3, label mô tả, bonus score 0-2 điểm.
    """

    def __init__(self, cfg: QuantConfig):
        self.cfg = cfg

    def detect(self, df: pd.DataFrame) -> dict:
        if len(df) < 25:
            return self._empty()

        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        n = self.cfg.dryup_sessions  # mặc định 5 phiên

        # ── 1. Volume khô ────────────────────────────────────────────────────
        vol_ma20     = v.rolling(20).mean()
        recent_vols  = v.iloc[-n:]
        recent_ma    = vol_ma20.iloc[-n:]
        vol_ratios   = recent_vols.values / (recent_ma.values + 1e-9)
        vol_dry      = bool(np.all(vol_ratios < self.cfg.dryup_vol_ratio))
        avg_vol_ratio = float(np.mean(vol_ratios))

        # ── 2. Nền hẹp ───────────────────────────────────────────────────────
        tr    = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr14 = float(tr.rolling(14).mean().iloc[-1])
        recent_ranges = (h.iloc[-n:] - l.iloc[-n:]).values
        avg_range     = float(np.mean(recent_ranges))
        narrow_base   = bool(avg_range < atr14 * self.cfg.dryup_range_ratio)

        # Kiểm tra thêm: biên độ có đang thu hẹp dần không?
        if n >= 4:
            first_half  = float(np.mean(recent_ranges[:n//2]))
            second_half = float(np.mean(recent_ranges[n//2:]))
            narrowing   = bool(second_half < first_half * 0.85)
        else:
            narrowing = narrow_base

        # ── 3. Không phân phối ───────────────────────────────────────────────
        recent_o   = df["open"].iloc[-n:].values if "open" in df.columns else df["close"].iloc[-n:].values
        recent_c   = c.iloc[-n:].values
        recent_v   = v.iloc[-n:].values
        recent_vma = vol_ma20.iloc[-n:].values
        no_distrib = True
        for i in range(n):
            bearish_body  = (recent_o[i] - recent_c[i]) / (recent_o[i] + 1e-9) > 0.015
            high_vol_bar  = recent_v[i] > recent_vma[i] * 1.2
            if bearish_body and high_vol_bar:
                no_distrib = False
                break

        # ── 4. Wyckoff Spring ─────────────────────────────────────────────────
        last_vol    = float(v.iloc[-1])
        last_ma20   = float(vol_ma20.iloc[-1])
        prev_dry    = bool(np.all(vol_ratios[:-1] < self.cfg.dryup_vol_ratio))
        spring_flag = bool(prev_dry and last_vol > last_ma20 * 1.5 and c.iloc[-1] > c.iloc[-2])

        # ── Tổng hợp ─────────────────────────────────────────────────────────
        strength    = sum([vol_dry, narrow_base or narrowing, no_distrib])
        dry_up_flag = strength >= 2

        if   spring_flag:   label = "🚀 Wyckoff Spring — Bứt phá nền"
        elif strength == 3: label = "💎 Cạn cung hoàn hảo — Chờ kích hoạt"
        elif strength == 2: label = "📦 Đang tích lũy — Vol khô dần"
        elif vol_dry:       label = "🔇 Vol thấp — Chưa rõ xu hướng"
        else:               label = "—"

        if   spring_flag:   bonus = min(self.cfg.dryup_bonus, 2.0)
        elif strength == 3: bonus = self.cfg.dryup_bonus * 0.8
        elif strength == 2: bonus = self.cfg.dryup_bonus * 0.5
        else:               bonus = 0.0

        return {
            "dry_up_flag":     dry_up_flag,
            "dry_up_strength": strength,
            "dry_up_label":    label,
            "spring_flag":     spring_flag,
            "vol_dry":         vol_dry,
            "narrow_base":     narrow_base or narrowing,
            "no_distrib":      no_distrib,
            "avg_vol_ratio":   round(avg_vol_ratio, 2),
            "avg_range_ratio": round(avg_range / (atr14 + 1e-9), 2),
            "bonus_score":     round(bonus, 2),
        }

    def _empty(self) -> dict:
        return {
            "dry_up_flag": False, "dry_up_strength": 0,
            "dry_up_label": "—", "spring_flag": False,
            "vol_dry": False, "narrow_base": False, "no_distrib": False,
            "avg_vol_ratio": 1.0, "avg_range_ratio": 1.0, "bonus_score": 0.0,
        }


# ═════ [source cell 14] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 7 — WIN RATE ESTIMATOR                                            ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Tại sao không dùng backtest để tính win rate?
#   1. vnstock không có tick data đủ sâu cho rolling backtest
#   2. Market VN thay đổi cấu trúc nhanh (circuit breaker T+0 pilot,
#      margin calls, HNX vs HOSE behavior khác nhau)
#   3. Backtest overfitted không honest bằng heuristic model có lý luận
#
# Approach: Pattern-based heuristic + Regime adjustment
#
# Công thức:
#   win_rate = base (45%) + Σ(pattern_delta) × regime_mult
#   Clamp: [25%, 82%] — không bao giờ "chắc chắn" hay "không có cơ hội"
#
# Pattern table: 19 patterns, mỗi pattern +/- điểm % vào win rate
# Regime multiplier:
#   Bull × 1.15 → cùng setup thắng nhiều hơn khi thị trường tốt
#   Panic × 0.65 → cùng setup thắng ít hơn khi thị trường hoảng loạn

class WinRateEstimator:
    """
    Ước tính xác suất thắng dựa trên Pattern + Regime Multiplier.

    Không phải backtest — là heuristic model:
    - Mỗi pattern kỹ thuật đóng góp +/- % vào win rate base
    - Regime điều chỉnh tổng thể theo chất lượng thị trường
    - Output: win_rate_est (%), confidence label, danh sách pattern active

    Scale: base 45% (thực tế VN), cap [25%, 82%]
    """

    _PATTERNS = {
        # VP Signals — vị trí giá trong Volume Profile
        "vp_breakout":    {"weight": 8.0,  "check": lambda r, d: r.get("vp_signal") == "breakout"},
        "vp_at_poc":      {"weight": 5.0,  "check": lambda r, d: r.get("vp_signal") == "at_poc"},
        "vp_value_area":  {"weight": 3.0,  "check": lambda r, d: r.get("vp_signal") == "value_area"},

        # RSI Zone
        "rsi_oversold":   {"weight": 7.0,  "check": lambda r, d: r.get("rsi", 50) < 35},
        "rsi_healthy":    {"weight": 4.0,  "check": lambda r, d: 38 <= r.get("rsi", 50) <= 55},
        "rsi_overbought": {"weight": -6.0, "check": lambda r, d: r.get("rsi", 50) > 75},

        # Volume & Flow
        "vol_surge":      {"weight": 6.0,  "check": lambda r, d: r.get("volume_ratio", 1) > 2.0},
        "vol_decent":     {"weight": 3.0,  "check": lambda r, d: 1.3 <= r.get("volume_ratio", 1) <= 2.0},
        "cmf_positive":   {"weight": 5.0,  "check": lambda r, d: r.get("cmf", 0) > 0.05},
        "inst_flow_up":   {"weight": 4.0,  "check": lambda r, d: bool(r.get("inst_flow_up", False))},

        # VSA patterns (v5.2) — thêm vào win rate
        "vsa_nos_vol":    {"weight": 9.0,  "check": lambda r, d: r.get("vsa_signal") == "🚀 NỔ VOL"},
        "vsa_rut_chan":   {"weight": 7.0,  "check": lambda r, d: r.get("vsa_signal") == "🔨 RÚT CHÂN"},
        "vsa_can_vol":    {"weight": 5.0,  "check": lambda r, d: r.get("vsa_signal") == "🩸 CẠN VOL"},
        "vsa_phan_phoi":  {"weight": -8.0, "check": lambda r, d: r.get("vsa_signal") == "⚠️ PHÂN PHỐI"},
        "vsa_can_cau":    {"weight": -4.0, "check": lambda r, d: r.get("vsa_signal") == "🥀 CẠN CẦU"},

        # Trend
        "trend_up":       {"weight": 7.0,  "check": lambda r, d: r.get("trend_long") == "uptrend"},
        "trend_weak_up":  {"weight": 3.0,  "check": lambda r, d: r.get("trend_long") == "weak_up"},
        "trend_down":     {"weight": -8.0, "check": lambda r, d: r.get("trend_long") == "downtrend"},

        # RSI / Composite Index Divergence (v5.6)
        # Heuristic adjustment only; this is NOT a historical win rate.
        "rsi_regular_bull": {"weight": 8.0, "check": lambda r, d: r.get("rsi_divergence_type") == "regular_bullish"},
        "rsi_hidden_bull":  {"weight": 5.0, "check": lambda r, d: r.get("rsi_divergence_type") == "hidden_bullish"},
        "rsi_regular_bear": {"weight": -8.0, "check": lambda r, d: r.get("rsi_divergence_type") == "regular_bearish"},
        "rsi_hidden_bear":  {"weight": -5.0, "check": lambda r, d: r.get("rsi_divergence_type") == "hidden_bearish"},

        # Momentum
        "macd_cross_up":  {"weight": 5.0,  "check": lambda r, d: bool(r.get("macd_cross_up", False))},
        "stoch_cross_up": {"weight": 4.0,  "check": lambda r, d: bool(r.get("stoch_cross_up", False))},
        "rs_strong":      {"weight": 4.0,  "check": lambda r, d: r.get("rs", 1) > 1.5},
        "rs_weak":        {"weight": -3.0, "check": lambda r, d: r.get("rs", 1) < 0.5},

        # Wyckoff
        "spring":         {"weight": 9.0,  "check": lambda r, d: bool(d.get("spring_flag", False))},
        "dryup_perfect":  {"weight": 6.0,  "check": lambda r, d: d.get("dry_up_strength", 0) >= 3 and not d.get("spring_flag", False)},
        "dryup_forming":  {"weight": 3.0,  "check": lambda r, d: d.get("dry_up_strength", 0) == 2},
    }

    def __init__(self, cfg: QuantConfig):
        self.cfg = cfg

    def estimate(self, raw: dict, dryup: dict, regime_mult: float) -> dict:
        base          = self.cfg.wr_base  # 45%
        pattern_delta = 0.0
        triggered     = []

        for name, info in self._PATTERNS.items():
            try:
                if info["check"](raw, dryup):
                    pattern_delta += info["weight"]
                    if info["weight"] > 0:
                        triggered.append(name)
            except Exception:
                pass

        adjusted = (base + pattern_delta) * regime_mult
        win_rate = max(25.0, min(82.0, adjusted))

        if   len(triggered) >= 6 and win_rate >= 65: conf = "🟢 Cao"
        elif len(triggered) >= 4 and win_rate >= 55: conf = "🟡 Trung bình"
        elif len(triggered) >= 2 and win_rate >= 45: conf = "🟠 Thấp"
        else:                                         conf = "🔴 Rất thấp"

        return {
            "win_rate_est":     round(win_rate, 1),
            "win_rate_label":   f"{win_rate:.0f}% ({conf})",
            "wr_confidence":    conf,
            "wr_patterns":      len(triggered),
            "wr_pattern_names": triggered[:5],
        }


# ═════ [source cell 15] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 8 — SCORING ENGINE                                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Chấm điểm 0-10 cho từng indicator, tổng hợp có trọng số.
#
# Design:
#   - Mỗi indicator → điểm sub-score 0-10
#   - Nhân với dynamic weight (đã normalize về tổng=100)
#   - Nhân regime_mult (0.7 - 1.0) → tổng score bị kéo xuống khi thị trường xấu
#   - Cộng bonus từ VolumeDryupDetector (0-2 điểm)
#   - Score cuối = (Σ sub_score × weight / 100) × regime_mult + bonus
#
# VSA integration (v5.2):
#   VSAEngine.to_score(vsa_signal) → sub-score 0-10
#   Weight "vsa" = 10 (trong BASE_WEIGHTS)
#   → Thay thế một phần cho volume_ratio trong việc đánh giá dòng tiền
#
# Mode swing vs hold:
#   RSI scoring khác nhau:
#   - Swing: RSI 28-45 điểm cao nhất (mua đáy sau retracement)
#   - Hold:  RSI 48-58 điểm cao nhất (mua khi momentum ổn định)

class ScoringEngine:
    """
    Chấm điểm 0-10 mỗi indicator, tổng hợp weighted + regime + bonus.

    v5.2: Thêm VSA sub-score với weight = 10 (trong BASE_WEIGHTS).
    VSA được tính qua VSAEngine.to_score() → scale 0-10 consistent.
    """

    def score(self, raw: dict, mode: str, weights: dict, regime_mult: float,
              bonus: float = 0.0) -> tuple[dict, float]:
        def clamp(x): return max(0.0, min(10.0, float(x)))
        s = {}

        # ── Volume ratio ──────────────────────────────────────────────────────
        # Piecewise linear: vol thấp (<0.8x) điểm thấp, vol cao (>2.2x) điểm cao
        # Không tuyến tính để tránh overweight phiên có vol đột biến bất thường
        vol = raw.get("volume_ratio", 1.0)
        if   vol <= 0.8: s["volume_ratio"] = clamp(vol * 4.0)
        elif vol < 1.3:  s["volume_ratio"] = clamp(3.5 + (vol - 0.8) * 6.0)
        elif vol < 2.2:  s["volume_ratio"] = clamp(6.0 + (vol - 1.3) * 3.5)
        else:            s["volume_ratio"] = clamp(8.5 + (vol - 2.2) * 1.2)

        # ── CMF ───────────────────────────────────────────────────────────────
        # CMF range thực tế -0.25 → +0.25, map về 0-10
        s["cmf"]   = clamp((raw.get("cmf", 0) + 0.25) / 0.055)

        # ── OBV ───────────────────────────────────────────────────────────────
        # Base 7.5 nếu OBV đang tăng, 2.5 nếu giảm
        # Điều chỉnh thêm theo slope (tốc độ thay đổi)
        ob         = 7.5 if raw.get("obv_signal") == 1 else 2.5
        s["obv"]   = clamp(ob + min(2.8, max(-2.8, raw.get("obv_slope", 0) / 9)))

        # ── Force Index ───────────────────────────────────────────────────────
        s["force"] = clamp((raw.get("force_index", 0) + 1.0) * 4.8)

        # ── Institutional Flow ────────────────────────────────────────────────
        s["inst_flow"] = float(raw.get("inst_flow", 5.0))

        # ── VSA (v5.2) ────────────────────────────────────────────────────────
        # VSAEngine.to_score map signal → 1.5 (PHÂN PHỐI) đến 8.5 (NỔ VOL)
        s["vsa"] = VSAEngine.to_score(raw.get("vsa_signal", "—"))

        # ── RSI / Composite Index Divergence (v5.6) ─────────────────────────
        # Divergence chỉ là tín hiệu bổ trợ; không được phép một mình tạo
        # tín hiệu mua/bán khi trend, VSA và thanh khoản không ủng hộ.
        div_type = raw.get("rsi_divergence_type", "none")
        div_strength = float(raw.get("rsi_divergence_strength", 0.0) or 0.0)
        if div_type == "regular_bullish": s["rsi_divergence"] = min(10.0, 7.5 + div_strength * 0.25)
        elif div_type == "hidden_bullish": s["rsi_divergence"] = min(10.0, 6.5 + div_strength * 0.20)
        elif div_type == "regular_bearish": s["rsi_divergence"] = max(0.0, 3.0 - div_strength * 0.20)
        elif div_type == "hidden_bearish": s["rsi_divergence"] = max(0.0, 3.8 - div_strength * 0.15)
        else: s["rsi_divergence"] = 5.0

        # ── RSI ───────────────────────────────────────────────────────────────
        rsi = raw.get("rsi", 50.0)
        if mode == "hold":
            # Hold: muốn RSI ổn định (48-58) không quá nóng hay quá lạnh
            if   rsi <= 32: s["rsi"] = 6.5
            elif rsi <= 48: s["rsi"] = 8.5
            elif rsi <= 58: s["rsi"] = 9.0
            elif rsi <= 68: s["rsi"] = 5.5
            elif rsi <= 78: s["rsi"] = 2.0
            else:           s["rsi"] = 0.5
        else:
            # Swing: muốn RSI vừa từ oversold lên (28-45)
            if   rsi <= 28: s["rsi"] = 9.5
            elif rsi <= 45: s["rsi"] = 8.0 + (45 - rsi) / 8.5
            elif rsi <= 55: s["rsi"] = 6.5
            elif rsi <= 68: s["rsi"] = 4.0
            elif rsi <= 78: s["rsi"] = 1.5
            else:           s["rsi"] = 0.5

        # ── EMA %distance ─────────────────────────────────────────────────────
        # ema_pct = % giá cách EMA20: -6% → score 0, +6% → score ~11
        s["ema"] = clamp((raw.get("ema_pct", 0) + 6.0) / 1.1)

        # ── Stochastic ────────────────────────────────────────────────────────
        k = raw.get("stoch_k", 50.0)
        if   k < 22: s["stoch"] = 8.8
        elif k < 45: s["stoch"] = 7.0
        elif k < 75: s["stoch"] = 4.2
        else:        s["stoch"] = 1.2
        if raw.get("stoch_cross_up"): s["stoch"] = min(10.0, s["stoch"] + 1.8)

        # ── MACD ─────────────────────────────────────────────────────────────
        s["macd"] = clamp(5.0 + raw.get("macd_hist_pct", 0) * 480)
        if raw.get("macd_cross_up"): s["macd"] = min(10.0, s["macd"] + 1.7)

        # ── VP Position ───────────────────────────────────────────────────────
        vp_map = {"breakout": 9.2, "value_area": 6.8, "at_poc": 5.5,
                  "below_value": 2.2, "unknown": 4.5}
        s["vp_position"] = vp_map.get(raw.get("vp_signal", "unknown"), 4.5)

        # ── Trend ─────────────────────────────────────────────────────────────
        tr_map = {"uptrend": 9.5, "weak_up": 6.8, "sideway": 4.2, "downtrend": 0.8}
        s["trend"] = tr_map.get(raw.get("trend_long", "sideway"), 4.2)

        # ── RS Score ─────────────────────────────────────────────────────────
        s["rs_score"] = clamp(raw.get("rs", 1.0) * 4.2 + 1.8)

        # ── Tổng hợp ─────────────────────────────────────────────────────────
        tw       = sum(weights.values()) or 1
        weighted = sum(s.get(k, 4.5) * weights.get(k, 0) for k in weights)
        total    = round(weighted / tw * regime_mult + bonus, 2)

        return {k: round(v, 2) for k, v in s.items()}, total


# ═════ [source cell 16] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 9 — POSITION SIZER                                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# "Mua bao nhiêu?" quan trọng hơn "Mua cổ phiếu nào?"
# Mua đúng mã, sai size → vẫn mất tài khoản (one bad trade wipes gains)
#
# 3 phương pháp, lấy MIN (conservative):
#
# 1. Fixed Risk:
#    Shares = (capital × risk%) / (entry - stoploss)
#    → Kiểm soát mức lỗ tối đa bằng tiền tuyệt đối
#
# 2. Volatility Adjustment:
#    vol_adj = min(1.0, 2.0 / ATR%)
#    → Mã biến động cao (ATR 4%) → giảm size 50%
#    → Tránh tình trạng stop bị bắn bởi noise bình thường
#
# 3. Kelly Fraction (1/4 Kelly):
#    Kelly = (win% × RR - loss%) / RR
#    Shares = capital × kelly_fraction / entry
#    → Giới hạn size theo xác suất thắng ước tính
#    → Dùng 1/4 Kelly (conservative) vì win rate là estimate không chắc
#
# v5.2: Kelly calculation dùng win_rate từ WinRateEstimator thay vì estimate thô

class PositionSizer:
    """
    Tính size lệnh: Kelly-fractional + Fixed Risk + Volatility Adjustment.

    Lấy MIN của 3 phương pháp để đảm bảo bảo toàn vốn.
    Cap tối đa 20% NAV/mã tránh concentration risk.
    Làm tròn xuống 100 cổ (lot chuẩn HOSE).
    """

    def __init__(self, cfg: QuantConfig):
        self.cfg = cfg

    def calculate(self, entry: float, stoploss: float, score: float,
                  atr_ratio: float, win_rate: float = 50.0) -> dict:
        cfg      = self.cfg
        capital  = cfg.capital
        risk_amt = capital * cfg.risk_per_trade       # VNĐ cho phép lỗ
        sl_dist  = max(entry - stoploss, entry * 0.005)  # Khoảng cách SL, min 0.5%

        # Method 1: Fixed Risk
        shares_risk = risk_amt / sl_dist

        # Method 2: Volatility Adjustment
        # ATR 2% = baseline không điều chỉnh
        # ATR 4% = giảm 50% size (biến động gấp đôi bình thường)
        vol_adj      = min(1.0, 2.0 / max(atr_ratio, 0.5))
        shares_vol   = shares_risk * vol_adj

        # Method 3: Kelly Fraction
        # win_rate từ WinRateEstimator (đã tích hợp pattern + regime)
        win_est      = win_rate / 100.0
        rr_est       = 2.0    # Assume RR = 2 (conservative baseline)
        kelly        = max(0, (win_est * rr_est - (1 - win_est)) / rr_est)
        kelly_frac   = kelly * cfg.kelly_fraction   # 1/4 Kelly
        shares_kelly = (capital * kelly_frac) / entry

        # Lấy MIN (conservative) + cap max position
        shares_raw = min(shares_vol, shares_kelly)
        max_shares = (capital * cfg.max_position_pct) / entry
        shares     = min(shares_raw, max_shares)

        # Làm tròn xuống lot 100 cổ (chuẩn HOSE)
        shares_lot = int(shares // 100) * 100
        if shares_lot <= 0: shares_lot = 100

        cost        = shares_lot * entry
        risk_actual = shares_lot * sl_dist
        pct_nav     = cost / capital * 100

        return {
            "shares":       shares_lot,
            "cost_vnd":     round(cost, 0),
            "pct_nav":      round(pct_nav, 1),
            "risk_vnd":     round(risk_actual, 0),
            "risk_pct_nav": round(risk_actual / capital * 100, 2),
            "kelly":        round(kelly_frac * 100, 1),
            "vol_adj":      round(vol_adj, 2),
        }


# ═════ [source cell 17] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
from pandas.core.frame import DataFrame
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 10 — SIGNAL BUILDER                                               ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Tính Smart Entry, Levels, Filters, Verdict.
#
# Smart Entry: không mua đuổi theo giá hiện tại, đặt lệnh chờ ở vùng tốt hơn
#   - Hold:    chờ về VAL (vùng giá trị thấp) hoặc dip 1.5×ATR
#   - Breakout: chờ retest VAH để tránh mua đỉnh
#   - At POC:  mua sát POC — điểm cân bằng volume cao nhất
#   - EMA20:   mua test đường MA động
#   - Default: dip nhỏ theo ATR
#
# Stoploss:
#   Swing: sl_base × 0.993 (buffer anti-hunt), max 2.0×ATR
#   Hold:  max(sl_base × 0.97, entry - 3×ATR, entry × 0.92) → không cut > 8%
#   Lý do Hold lỏng hơn: T+2.5 có rủi ro bị rũ bởi MM trong ngắn hạn
#
# Hard filters (apply_filters):
#   v5.2 thêm: VSA PHÂN PHỐI → không mua T+
#              VSA CẠN CẦU + breakout → không mua (bull trap)
#
# R:R Gate:
#   Swing: T2/risk ≥ 2.0, Hold: T2/risk ≥ 3.0

class SignalBuilder:
    """
    Tính Smart Entry, Levels, Filters, Verdict.
    v5.2: Thêm 2 hard filter VSA vào apply_filters.
    """

    def __init__(self, cfg: QuantConfig):
        self.cfg = cfg

    def smart_entry(self, df: pd.DataFrame, raw: dict, vp: dict, mode: str) -> dict:
        """
        Xác định vùng entry tốt hơn giá thị trường hiện tại.

        Ưu tiên: VAL (Hold) > Retest VAH (Breakout) > POC > EMA20 > ATR dip
        """
        close = float(df["close"].iloc[-1])
        atr   = raw["atr_abs"]
        poc   = vp.get("poc"); vah = vp.get("vah"); val = vp.get("val")
        sig   = raw.get("vp_signal", "unknown")
        ema20 = raw.get("ema20", close)
        pb    = self.cfg.entry_pullback_pct / 100
        amult = self.cfg.entry_atr_mult

        if mode == "hold":
            if val and val < close * 0.98:
                entry, note = round(val * 1.005, 2), "Chờ về vùng VAL"
            else:
                entry, note = round(close - atr * 1.5, 2), "Chờ nhịp dip sâu"

        elif sig == "breakout":
            if vah and vah < close:
                entry, note = round(vah * 1.003, 2), "Retest VAH (tránh mua đỉnh)"
            else:
                entry, note = round(close * (1 - pb), 2), f"Pullback {pb*100:.1f}%"

        elif sig == "at_poc":
            if poc:
                entry, note = round(poc * 0.997, 2), "Mua sát POC"
            else:
                entry, note = round(close * (1 - pb), 2), "Pullback"

        elif abs(close - ema20) / close < 0.015:
            entry, note = round(ema20 * 1.002, 2), "Test hỗ trợ EMA20"

        else:
            entry, note = round(close - atr * amult, 2), f"Dip {amult}×ATR"

        return {"entry": entry, "entry_note": note}

    def find_swing_low(self, df: pd.DataFrame, lookback: int = 18) -> float:
        """
        Tìm đáy Swing Low gần nhất để đặt stoploss.

        Pivot Low: nến thấp hơn 2 nến trước và 2 nến sau.
        Chỉ xét pivot ở cuối lookback (>40% từ đầu window)
        để tránh dùng đáy quá cũ làm SL quá xa.
        """
        r  = df["low"].tail(lookback).reset_index(drop=True)
        sl = float(r.min())
        for i in range(2, len(r) - 2):
            if (r.iloc[i] < r.iloc[i-1] and r.iloc[i] < r.iloc[i+1] and
                r.iloc[i] <= r.iloc[i-2] and r.iloc[i] <= r.iloc[i+2]):
                if i > len(r) * 0.4:
                    sl = float(r.iloc[i])
                    break
        return round(sl, 2)

    def find_resistance(self, df: pd.DataFrame, mode: str = "swing") -> float:
        """
        Tìm kháng cự ngắn hạn để capping target.

        Swing: 15 phiên (kháng cự gần, tránh target bị chặn sớm)
        Hold:  30 phiên (kháng cự xa hơn, target cần bỏ qua kháng cự ngắn)
        """
        lookback = 15 if mode == "swing" else 30
        return float(df["high"].tail(lookback).max())

    def find_itp_boundaries(self, ichi: dict) -> Tuple[float, float, str, float]:
        close = ichi.get("close", 0)
        supports = []
        resistances = []

        for key in ["d1_kijun_flat", "d1_ssb_flat", "w1_kijun", "w1_ssb", "m1_kijun", "m1_ssb"]:
            val = ichi.get(key)
            if val and val > 0:
                if val < close * 0.995:
                    supports.append(val)
                elif val > close * 1.005:
                    resistances.append(val)

        best_support = max(supports) if supports else close * 0.96
        best_resist = min(resistances) if resistances else close * 1.20

        reason = "Đồng pha MTF"
        if ichi.get("d1_khach_san"):
            reason = "Khách sạn D1"
        elif ichi.get("d1_kijun_flat") or ichi.get("d1_ssb_flat"):
            reason = "Dao găm ITP"

        return best_support, best_resist, reason, ichi.get("itp_strength", 0)

    def levels(self, df: pd.DataFrame, raw: dict, vp: dict, se: dict, mode: str) -> dict:
        """
        PHIÊN BẢN MỚI v5.4 — Tích hợp Ichimoku ITP + Gate 9-10%
        Tính SL và TP cho cả swing và hold.

        Swing SL: sl_base × 0.993 (buffer 0.7% chống hunt)
                  Giới hạn tối đa 2.0×ATR để không cắt quá xa
        Hold SL:  Lấy max (mức cao nhất) của 3 cách tính:
                  - sl_base × 0.97 (3% buffer)
                  - entry - 3.0×ATR
                  - entry × 0.92 (hard floor: không cut quá 8%)
                  → max() vì mức càng cao = càng ít bị cut = phù hợp hold

        Swing T1: entry + 1.5×risk (R:R 1.5), cap tại kháng cự
        Swing T2: entry + 2.5×risk (R:R 2.5)
        Hold  T1: entry + 2.5×risk (bỏ qua kháng cự ngắn hạn)
        Hold  T2: entry + 4.0×risk (sóng dài)

        v5.4.1 — Fix: SL dùng max() thay vì min() (bug khiến cutloss luôn
        vượt ngưỡng 5%, chặn hết tín hiệu "SIÊU PHẨM"). Fix: nhánh hold
        giờ fallback về _legacy_levels thay vì thiếu return → None crash.
        """
        ichi = raw.get("ichi", {})
        if ichi.get("error") or not ichi:
            return self._legacy_levels(df, raw, vp, se, mode)

        support_itp, resist_itp, itp_reason, itp_strength = self.find_itp_boundaries(ichi)
        entry = se["entry"]
        atr = raw["atr_abs"]
        vsa = raw.get("vsa_signal", "—")

        if mode == "hold":
            # Chưa có công thức ITP riêng cho hold — dùng legacy an toàn
            # thay vì để hàm rơi qua không return (bug cũ).
            return self._legacy_levels(df, raw, vp, se, mode)

        # ── mode == "swing" ──────────────────────────────────────────────────
        t1 = round(resist_itp * 0.99, 2)
        potential_pct = (t1 - entry) / entry * 100
        if potential_pct < 9.0:
            t1 = round(entry * 1.095, 2)

        t2 = round(t1 + atr * 2.0, 2)

        # FIX: max() thay vì min() — chặn dưới SL không bị kéo quá xa entry
        sl = round(max(support_itp * 0.99, entry - atr * 1.35), 2)

        risk = max(entry - sl, entry * 0.005)
        rr = round((t1 - entry) / risk, 2)
        profit_pct = round((t1 - entry) / entry * 100, 2)
        cutloss_pct = round((entry - sl) / entry * 100, 2)

        vsa_positive = vsa in ["🚀 NỔ VOL", "🔨 RÚT CHÂN", "🩸 CẠN VOL"]
        itp_strong = itp_strength >= 1.5

        if profit_pct >= 9.0 and rr >= 2.1 and cutloss_pct <= 5.0 and vsa_positive and itp_strong:
            action = "🔥 SIÊU PHẨM T+ (VSA+ITP)"
            rr_ok = True
        elif profit_pct >= 9.0 and rr >= 2.0 and vsa_positive:
            action = f"✅ MUA T+ (VSA+ITP {itp_strength:.1f})"
            rr_ok = True
        else:
            action = f"⛔ Chưa đạt chuẩn (Profit {profit_pct:.1f}% | VSA:{vsa})"
            rr_ok = False

        return {
            "entry": entry, "entry_note": se["entry_note"] + f" | ITP:{itp_reason}",
            "stoploss": sl, "cutloss_sw_pct": cutloss_pct,
            "swing_t1": t1, "swing_t2": t2, "swing_rr": rr,
            "swing_t1_pct": profit_pct,
            "hold_sl": round(sl * 0.96, 2),
            "hold_t1": round(entry * 1.20, 2),
            "hold_t2": round(entry * 1.40, 2),
            "hold_rr": 3.8,
            "action": action, "rr_ok": rr_ok,
            "itp_strength": itp_strength,
            "itp_reason": itp_reason
        }

    def _legacy_levels(self, df: pd.DataFrame, raw: dict, vp: dict,
               se: dict, mode: str) -> dict:
        """
        Tính SL và TP cho cả swing và hold.

        Swing SL: sl_base × 0.993 (buffer 0.7% chống hunt)
                  Giới hạn tối đa 2.0×ATR để không cắt quá xa
        Hold SL:  Lấy max (mức cao nhất) của 3 cách tính:
                  - sl_base × 0.97 (3% buffer)
                  - entry - 3.0×ATR
                  - entry × 0.92 (hard floor: không cut quá 8%)
                  → max() vì mức càng cao = càng ít bị cut = phù hợp hold

        Swing T1: entry + 1.5×risk (R:R 1.5), cap tại kháng cự
        Swing T2: entry + 2.5×risk (R:R 2.5)
        Hold  T1: entry + 2.5×risk (bỏ qua kháng cự ngắn hạn)
        Hold  T2: entry + 4.0×risk (sóng dài)
        """
        atr     = raw["atr_abs"]
        sl_base = self.find_swing_low(df, 18)
        resist  = self.find_resistance(df, mode)
        entry   = se["entry"]

        # Swing SL
        sl_sw = round(sl_base * 0.993, 2)
        if (entry - sl_sw) > atr * 2.2:
            sl_sw = round(entry - atr * 2.0, 2)

        # Hold SL — an toàn: không bao giờ cut > 8% từ entry
        sl_hd = max(
            round(sl_base * 0.97, 2),    # 3% buffer dưới swing low
            round(entry - atr * 3.0, 2), # Tối đa 3×ATR
            round(entry * 0.92, 2),       # Hard floor: -8%
        )

        risk_sw = max(entry - sl_sw, entry * 0.005)
        risk_hd = max(entry - sl_hd, entry * 0.005)

        # Swing targets
        t1_sw = round(entry + risk_sw * 1.5, 2)
        if resist > entry * 1.01:
            t1_sw = round(min(t1_sw, resist * 0.99), 2)
        if t1_sw <= entry * 1.02:
            t1_sw = round(entry * 1.03, 2)
        t2_sw = round(entry + risk_sw * 2.5, 2)
        if t2_sw <= t1_sw: t2_sw = round(t1_sw + atr, 2)
        rr_sw  = round((t2_sw - entry) / risk_sw, 2) if risk_sw > 0 else 0.0

        # Hold targets
        t1_hd = round(entry + risk_hd * 2.5, 2)
        t2_hd = round(entry + risk_hd * 4.0, 2)
        if t2_hd <= t1_hd: t2_hd = round(t1_hd + atr * 2, 2)
        rr_hd = round((t2_hd - entry) / risk_hd, 2) if risk_hd > 0 else 0.0

        cutloss_sw_pct = round((entry - sl_sw) / entry * 100, 2)
        cutloss_hd_pct = round((entry - sl_hd) / entry * 100, 2)

        # R:R Gate
        if mode == "swing":
            rr_ok  = rr_sw >= self.cfg.min_rr_swing
            action = "✅ BUY T+" if rr_ok and cutloss_sw_pct <= 8.0 else f"⛔ R:R={rr_sw:.1f}<{self.cfg.min_rr_swing}"
        else:
            rr_ok  = rr_hd >= self.cfg.min_rr_hold
            action = "✅ BUY HOLD" if rr_ok and cutloss_hd_pct <= 8.0 else f"⛔ R:R={rr_hd:.1f}<{self.cfg.min_rr_hold}"

        return {
            "entry": entry, "entry_note": se["entry_note"],
            "stoploss": sl_sw, "cutloss_sw_pct": cutloss_sw_pct,
            "swing_t1": t1_sw, "swing_t2": t2_sw, "swing_rr": rr_sw,
            "swing_t1_pct": round((t1_sw - entry) / entry * 100, 2),
            "swing_sl_pct": round((sl_sw - entry) / entry * 100, 2),
            "hold_sl": sl_hd, "cutloss_hd_pct": cutloss_hd_pct,
            "hold_t1": t1_hd, "hold_t2": t2_hd, "hold_rr": rr_hd,
            "hold_t1_pct": round((t1_hd - entry) / entry * 100, 2),
            "action": action, "rr_ok": rr_ok,
        }

    def classify_horizon(self, raw: dict) -> str:
        """
        Phân loại T+ / Hold / Tiềm năng dựa trên điều kiện kỹ thuật.

        Hold score: giá vs SMA50/200, RSI, CMF+OBV, RS
        T+ score:   volume ratio, RSI không quá mua, EMA, cross signals
        → Tổ hợp → 5 nhãn từ 'T+ & Hold' đến 'Chờ thêm'
        """
        close  = raw["close"]; sma50 = raw.get("sma50", close)
        hold = 0
        if sma50 and close > sma50:                                  hold += 1
        if raw.get("sma200") and close > raw["sma200"]:             hold += 1
        if 38 <= raw.get("rsi", 50) <= 65:                          hold += 1
        if raw.get("cmf", 0) > 0.025 and raw.get("obv_signal") == 1: hold += 2
        if raw.get("rs", 1.0) >= 1.0:                               hold += 1
        tp = 0
        vr = raw.get("volume_ratio", 1.0)
        if vr >= 1.35:                                               tp += 2
        if raw.get("rsi", 50) < 68:                                  tp += 1
        if raw.get("ema_pct", 0) > -3.5:                            tp += 1
        if raw.get("stoch_cross_up") or raw.get("macd_cross_up") or vr >= 1.8: tp += 2
        # VSA bonus vào T+ classification
        if raw.get("vsa_signal") in ("🚀 NỔ VOL", "🔨 RÚT CHÂN"): tp += 2
        if raw.get("vsa_signal") == "🩸 CẠN VOL":                   hold += 1

        if hold >= 4 and tp >= 4:  return "🔥 T+ & Hold"
        if hold >= 4:              return "📈 Hold"
        if tp >= 4:                return "⚡ T+ only"
        if hold >= 3 or tp >= 3:   return "🔄 Tiềm năng"
        return                            "⏳ Chờ thêm"

    def liquidity_ok(self, raw: dict, cfg: QuantConfig) -> tuple[bool, str]:
        avg_vol = raw.get("avg_vol_20d", 0)
        avg_val = raw.get("avg_val_20d", 0)
        if avg_vol < cfg.min_avg_vol_20d:
            return False, f"Thanh khoản thấp ({avg_vol} cp/ngày)"
        if avg_val < cfg.min_avg_val_20d:
            return False, f"Giá trị thấp ({avg_val} /ngày)"
        return True, ""

    def divergence_advice(self, raw: dict, mode: str = "swing") -> dict:
        """
        Đánh giá RSI/Composite Index Divergence để hỗ trợ khuyến nghị.

        Divergence chỉ là tín hiệu bổ sung, không tự động tạo BUY/SELL.
        Chỉ divergence đã xác nhận và còn trong giới hạn tuổi được xem là active.
        D1 được dùng cho recommendation hiện tại; W1/M1 vẫn được báo cáo riêng.
        """
        div_type = str(raw.get("rsi_divergence_type", "none") or "none").lower()
        div_strength = float(raw.get("rsi_divergence_strength", 0) or 0)
        div_age = raw.get("rsi_divergence_age", None)
        confirmed = bool(raw.get("rsi_divergence_confirmed", False))
        max_age = getattr(self.cfg, "divergence_max_age_bars", 15)

        if div_age is not None:
            try:
                active = confirmed and float(div_age) <= float(max_age)
            except (TypeError, ValueError):
                active = confirmed
        else:
            active = confirmed

        if not active or div_type in ("none", "", "nan"):
            return {
                "label": "—", "bias": "neutral",
                "reason": "Không có RSI divergence D1 đang hoạt động.",
                "active": False, "type": div_type,
                "strength": div_strength, "age": div_age,
            }

        if div_type == "regular_bullish":
            label = "🟢 THEO DÕI MUA / CHỜ XÁC NHẬN"
            bias = "bullish"
            reason = (
                "Phân kỳ dương thường: giá tạo đáy thấp hơn nhưng Composite RSI "
                "tạo đáy cao hơn → cảnh báo suy yếu đà giảm và khả năng hồi/đảo chiều."
            )
        elif div_type == "hidden_bullish":
            label = "🟢 THEO DÕI TIẾP DIỄN TĂNG"
            bias = "bullish_continuation"
            reason = (
                "Phân kỳ dương ẩn: giá tạo đáy cao hơn nhưng Composite RSI tạo đáy "
                "thấp hơn → hỗ trợ khả năng tiếp diễn xu hướng tăng."
            )
        elif div_type == "regular_bearish":
            label = "🔴 CẢNH BÁO SUY YẾU / TRÁNH MUA ĐUỔI"
            bias = "bearish"
            reason = (
                "Phân kỳ âm thường: giá tạo đỉnh cao hơn nhưng Composite RSI tạo đỉnh "
                "thấp hơn → cảnh báo động lượng tăng đang suy yếu."
            )
        elif div_type == "hidden_bearish":
            label = "🔴 CẢNH BÁO TIẾP DIỄN GIẢM"
            bias = "bearish_continuation"
            reason = (
                "Phân kỳ âm ẩn: giá tạo đỉnh thấp hơn nhưng Composite RSI tạo đỉnh "
                "cao hơn → hỗ trợ khả năng tiếp diễn xu hướng giảm."
            )
        else:
            label = "—"
            bias = "neutral"
            reason = f"Divergence không xác định: {div_type}"

        meta = []
        if div_strength > 0:
            meta.append(f"Strength {div_strength:.1f}")
        if div_age is not None:
            try:
                meta.append(f"Age {float(div_age):.0f} bars")
            except (TypeError, ValueError):
                pass
        if meta:
            reason += " | " + " | ".join(meta)

        return {
            "label": label, "bias": bias, "reason": reason,
            "active": True, "type": div_type,
            "strength": div_strength, "age": div_age,
        }

    def apply_filters(self, raw: dict, mode: str, liq_ok: bool,
                  liq_reason: str, dryup: dict) -> tuple[bool, list]:
        """
        Hard filter — loại mã không đủ điều kiện.

        Filters v5.2 mới (VSA-based):
        1. PHÂN PHỐI trong swing mode → Upthrust, xả hàng núp bóng
           → Không mua T+ dù score cao vì tiền đang rút
        2. Breakout + CẠN CẦU → Bull trap
           → Vol không đỡ breakout, sẽ fail và quay lại range

        Wyckoff Spring exception:
        Nếu có Spring (vol đột tăng sau nền khô) → bỏ qua warning vol thấp
        vì đây là vol tốt, không phải vol yếu

        Giữ nguyên logic gốc. LƯU Ý: raw.get("itp_strength", 0) đã ĐÚNG
        vì compute_all() set field này ở cả 2 chỗ (flat + nested trong
        "ichi") cùng giá trị — không có key-mismatch bug như một số review
        tự động đã báo. Thêm fallback kép cho chắc, phòng compute_all bị
        sửa sau này mà quên set field flat.
        """
        reasons = []
        if not liq_ok: reasons.append(liq_reason)
        if raw.get("volume_ratio", 0) < 0.5: reasons.append(f"Vol Ratio thấp ({raw.get('volume_ratio',0):.2f}x)")

        rsi = raw.get("rsi", 50)
        if rsi > 85: reasons.append(f"RSI quá mua ({rsi:.0f})")
        elif rsi > 75 and mode == "swing": reasons.append(f"RSI cao T+ ({rsi:.0f})")

        if raw.get("ema_pct", 0) < -9: reasons.append(f"Dưới EMA20 sâu ({raw.get('ema_pct',0):.1f}%)")
        if raw.get("cmf", 0) < -0.20:  reasons.append(f"CMF âm nặng ({raw.get('cmf',0):.3f})")
        if mode == "hold" and raw.get("trend_long") == "downtrend": reasons.append("Downtrend dài hạn")
        if mode == "hold" and raw.get("obv_signal") == -1: reasons.append("OBV suy yếu")
        if raw.get("stoch_k", 50) > 75: reasons.append(f"Stoch quá mua ({raw.get('stoch_k',50):.0f})")

        # ── VSA Hard Filters (v5.2) ──────────────────────────────────────────
        vsa = raw.get("vsa_signal", "—")
        # Fallback kép — không phải fix bug, chỉ tăng độ bền nếu schema đổi sau này
        itp_strength = raw.get("itp_strength", raw.get("ichi", {}).get("itp_strength", 0))

        # Divergence âm + downtrend là cảnh báo mạnh cho swing; divergence dương
        # không được dùng như hard-buy filter.
        if mode == "swing" and raw.get("rsi_divergence_type") == "regular_bearish" and raw.get("trend_long") == "downtrend":
            reasons.append("RSI phân kỳ âm + xu hướng dài hạn giảm")

        if mode == "swing":
            vsa_good = vsa in ["🚀 NỔ VOL", "🔨 RÚT CHÂN", "🩸 CẠN VOL"]
            if not vsa_good and itp_strength < 1.0:
                reasons.append("VSA yếu + ITP không hỗ trợ")

        # Filter 1: Upthrust / Phân phối
        # Vol lớn nhưng đóng thấp trong nến → Smart Money đang xả
        # Không mua T+ dù các indicator khác tốt
        if mode == "swing" and vsa == "⚠️ PHÂN PHỐI":
            reasons.append("⚠️ VSA: Upthrust / Xả hàng núp bóng")

        # Filter 2: Breakout không có Vol → bull trap
        # Breakout phải kèm Vol lớn, nếu CẠN CẦU thì sẽ fail
        if raw.get("vp_signal") == "breakout" and vsa == "🥀 CẠN CẦU":
            reasons.append("🥀 VSA: Breakout thiếu Vol (Bull Trap)")

        # Spring exception: bỏ qua warning vol thấp nếu có Wyckoff Spring
        if dryup.get("spring_flag") and any("Vol thấp" in r for r in reasons):
            reasons = [r for r in reasons if "Vol thấp" not in r]

        return len(reasons) == 0, reasons

    @staticmethod
    def verdict(score: float, passed: bool, mode: str) -> str:
        if not passed: return "🚫 BỊ LỌC"
        if mode == "hold":
            if score >= 8.0: return "💎 HOLD MẠNH"
            if score >= 6.5: return "✅ XEM XÉT HOLD"
            if score >= 5.5: return "👀 THEO DÕI"
            return "❌ BỎ QUA"
        else:
            if score >= 7.5: return "🔥 MUA MẠNH T+"
            if score >= 6.5: return "✅ XEM XÉT T+"
            if score >= 5.0: return "👀 THEO DÕI"
            if score >= 3.5: return "⚠️  YẾU"
            return "❌ BỎ QUA"


# ═════ [source cell 18] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 11 — DISPLAY                                                      ║
# ╚══════════════════════════════════════════════════════════════════════════╝

_TREND = {
    "uptrend":   "🟢 Uptrend",
    "weak_up":   "🔵 Weak Up",
    "sideway":   "🟡 Sideway",
    "downtrend": "🔴 Downtrend",
}

_VP = {
    "breakout":    "⬆ Breakout",
    "value_area":  "◼ Value Area",
    "at_poc":      "⬛ POC",
    "below_value": "⬇ Dưới VAL",
    "unknown":     "—",
}


def _display(df: pd.DataFrame, mode: str):
    """
    Hiển thị kết quả phân tích.

    Có thêm:
    - Composite Index Divergence D1 / W1 / M1
    - Divergence strength / confirmation
    - Dao Găm Ichimoku D1 / W1 / M1
    - Các thông số Kijun / Senkou B / Khách sạn
    """

    # ========================================================================
    # CHECK NOTEBOOK / TERMINAL
    # ========================================================================
    try:
        from IPython.display import display as ipy
        in_nb = True
    except ImportError:
        in_nb = False

    # ========================================================================
    # COLUMNS
    # ========================================================================
    cols = [

        # --------------------------------------------------------------------
        # BASIC
        # --------------------------------------------------------------------
        "Mã",
        "Tín hiệu",
        "Khuyến nghị",
        "Score",
        "Win%",
        "Giá",
        "RSI",
        "CMF",
        "RS",
        "Vol",

        # --------------------------------------------------------------------
        # COMPOSITE INDEX DIVERGENCE
        # --------------------------------------------------------------------
        "Composite Div",
        "Div Advice",
        "Div Bias",
        "Div Strength",
        "Div Age",
        "Div Confirmed",
        "Div Pivot Date",
        "Div Confirm Date",

        # Multi-timeframe divergence
        "Div W1",
        "Div W1 Strength",
        "Div M1",
        "Div M1 Strength",

        # --------------------------------------------------------------------
        # MARKET / VSA
        # --------------------------------------------------------------------
        "VSA",
        "Thanh khoản",
        "Dòng tiền",
        "Cạn cung",
        "VP",
        "Trend",

        # --------------------------------------------------------------------
        # ENTRY / TARGET / RISK
        # --------------------------------------------------------------------
        "Entry",
        "Entry zone",
        "SL T+",
        "SL Hold",
        "T+ T1",
        "T+ T2",
        "T+ R:R",
        "T+ %",
        "Hold T1",
        "Hold T2",
        "Hold R:R",
        "Action",
        "Lý do",

        # --------------------------------------------------------------------
        # DAO GĂM / ITP SUMMARY
        # --------------------------------------------------------------------
        "ITP Dao Găm D1",
        "ITP Dao Găm W1/M1",
        "KC Hỗ Trợ ITP %",

        # --------------------------------------------------------------------
        # DAO GĂM STATUS
        # --------------------------------------------------------------------
        "Dao Gam D1",
        "Dao Gam W1",
        "Dao Gam M1",

        # --------------------------------------------------------------------
        # DAO GĂM D1 DETAILS
        # --------------------------------------------------------------------
        "D1 Kijun",
        "D1 Kijun Flat",
        "D1 Senkou B Flat",
        "D1 Khach San",

        # --------------------------------------------------------------------
        # DAO GĂM W1 DETAILS
        # --------------------------------------------------------------------
        "W1 Kijun",
        "W1 Kijun Flat",
        "W1 Senkou B Flat",
        "W1 Khach San",

        # --------------------------------------------------------------------
        # DAO GĂM M1 DETAILS
        # --------------------------------------------------------------------
        "M1 Kijun",
        "M1 Kijun Flat",
        "M1 Senkou B Flat",
        "M1 Khach San",

        "Dao Gam Strength",

        # --------------------------------------------------------------------
        # MA / HOLDER
        # --------------------------------------------------------------------
        "MA Context",
        "Holder Action",
        "Holder Reason",
    ]

    # Chỉ lấy những column thực sự tồn tại.
    show = [
        c for c in cols
        if c in df.columns
    ]

    d = df[
        show
    ].copy()

    # ========================================================================
    # TERMINAL / NON-NOTEBOOK
    # ========================================================================
    if not in_nb:

        pd.set_option(
            "display.max_columns",
            None
        )

        pd.set_option(
            "display.width",
            500
        )

        print(
            d.to_string(
                index=False
            )
        )

        return

    # ========================================================================
    # ROW BACKGROUND
    # ========================================================================
    def rbg(row):

        s = str(
            row.get(
                "Tín hiệu",
                ""
            )
        )

        bg = (
            "#1a3a1a" if "🔥" in s or "💎" in s else
            "#1a2e1a" if "✅" in s else
            "#3a1a1a" if "🚫" in s else
            "#3a3a1a" if "⚠" in s else
            ""
        )

        return [
            f"background-color:{bg}"
            if bg
            else ""
            for _ in row
        ]

    # ========================================================================
    # SCORE COLOR
    # ========================================================================
    def cs(v):

        try:

            f = float(v)

            return (
                "color:#4ade80;font-weight:bold"
                if f >= 7.5
                else
                "color:#facc15"
                if f >= 6
                else
                "color:#f87171"
            )

        except:
            return ""

    # ========================================================================
    # WIN RATE COLOR
    # ========================================================================
    def cw(v):

        try:

            f = float(
                str(v).replace(
                    "%",
                    ""
                )
            )

            return (
                "color:#4ade80;font-weight:bold"
                if f >= 65
                else
                "color:#facc15"
                if f >= 55
                else
                "color:#f87171"
            )

        except:
            return ""

    # ========================================================================
    # VSA COLOR
    # ========================================================================
    def cvsa(v):

        s = str(v)

        if "NỔ VOL" in s:
            return "color:#4ade80;font-weight:bold"

        if "RÚT CHÂN" in s:
            return "color:#60a5fa;font-weight:bold"

        if "CẠN VOL" in s:
            return "color:#a78bfa"

        if "PHÂN PHỐI" in s:
            return "color:#f87171;font-weight:bold"

        if "CẠN CẦU" in s:
            return "color:#fb923c"

        return ""

    # ========================================================================
    # R:R COLOR
    # ========================================================================
    def cr(v):

        try:

            f = float(
                str(v).replace(
                    "1:",
                    ""
                )
            )

            return (
                "color:#4ade80;font-weight:bold"
                if f >= 2
                else
                "color:#facc15"
                if f >= 1.5
                else
                "color:#f87171"
            )

        except:
            return ""

    # ========================================================================
    # COMPOSITE DIVERGENCE COLOR
    # ========================================================================
    def cdiv(v):

        s = str(v).lower()

        # Bullish divergence
        if (
            "regular_bull" in s
            or "bullish" in s
            or "hidden_bull" in s
        ):
            return "color:#4ade80;font-weight:bold"

        # Bearish divergence
        if (
            "regular_bear" in s
            or "bearish" in s
            or "hidden_bear" in s
        ):
            return "color:#f87171;font-weight:bold"

        return ""

    # ========================================================================
    # DIVERGENCE BIAS COLOR
    # ========================================================================
    def cdivbias(v):

        s = str(v).lower()

        if "bull" in s:
            return "color:#4ade80;font-weight:bold"

        if "bear" in s:
            return "color:#f87171;font-weight:bold"

        return "color:#94a3b8"

    # ========================================================================
    # DIVERGENCE CONFIRMATION COLOR
    # ========================================================================
    def cconfirmed(v):

        s = str(v).lower()

        if s in [
            "true",
            "1",
            "yes"
        ]:
            return "color:#4ade80;font-weight:bold"

        if s in [
            "false",
            "0",
            "no"
        ]:
            return "color:#facc15"

        return ""

    # ========================================================================
    # DAO GĂM COLOR
    # ========================================================================
    def cdaogam(v):

        s = str(v).lower()

        # Positive / support conditions
        if any(
            x in s
            for x in [
                "bull",
                "support",
                "hỗ trợ",
                "tăng",
                "buy",
                "strong"
            ]
        ):
            return "color:#4ade80;font-weight:bold"

        # Negative conditions
        if any(
            x in s
            for x in [
                "bear",
                "resistance",
                "kháng cự",
                "giảm",
                "sell",
                "weak"
            ]
        ):
            return "color:#f87171;font-weight:bold"

        return ""

    # ========================================================================
    # STYLED TABLE
    # ========================================================================
    rr_cols = [
        c
        for c in [
            "T+ R:R",
            "Hold R:R"
        ]
        if c in d.columns
    ]

    divergence_cols = [
        c
        for c in [
            "Composite Div",
            "Div W1",
            "Div M1"
        ]
        if c in d.columns
    ]

    divergence_bias_cols = [
        c
        for c in [
            "Div Bias"
        ]
        if c in d.columns
    ]

    divergence_confirm_cols = [
        c
        for c in [
            "Div Confirmed"
        ]
        if c in d.columns
    ]

    dao_gam_cols = [
        c
        for c in [
            "Dao Gam D1",
            "Dao Gam W1",
            "Dao Gam M1"
        ]
        if c in d.columns
    ]

    styled = (
        d.style

        # ------------------------------------------------------------
        # Row signal background
        # ------------------------------------------------------------
        .apply(
            rbg,
            axis=1
        )

        # ------------------------------------------------------------
        # Score
        # ------------------------------------------------------------
        .map(
            cs,
            subset=[
                c for c in [
                    "Score"
                ]
                if c in d.columns
            ]
        )

        # ------------------------------------------------------------
        # Win rate
        # ------------------------------------------------------------
        .map(
            cw,
            subset=[
                c for c in [
                    "Win%"
                ]
                if c in d.columns
            ]
        )

        # ------------------------------------------------------------
        # VSA
        # ------------------------------------------------------------
        .map(
            cvsa,
            subset=[
                c for c in [
                    "VSA"
                ]
                if c in d.columns
            ]
        )

        # ------------------------------------------------------------
        # R:R
        # ------------------------------------------------------------
        .map(
            cr,
            subset=rr_cols
        )

        # ------------------------------------------------------------
        # Composite Divergence
        # ------------------------------------------------------------
        .map(
            cdiv,
            subset=divergence_cols
        )

        # ------------------------------------------------------------
        # Divergence Bias
        # ------------------------------------------------------------
        .map(
            cdivbias,
            subset=divergence_bias_cols
        )

        # ------------------------------------------------------------
        # Divergence Confirmation
        # ------------------------------------------------------------
        .map(
            cconfirmed,
            subset=divergence_confirm_cols
        )

        # ------------------------------------------------------------
        # Dao Găm
        # ------------------------------------------------------------
        .map(
            cdaogam,
            subset=dao_gam_cols
        )

        # ------------------------------------------------------------
        # Table style
        # ------------------------------------------------------------
        .set_table_styles([

            {
                "selector": "th",
                "props": [
                    ("background-color", "#1e293b"),
                    ("color", "#94a3b8"),
                    ("font-size", "10px"),
                    ("padding", "4px 6px"),
                    ("text-align", "center"),
                    ("border-bottom", "1px solid #334155"),
                ],
            },

            {
                "selector": "td",
                "props": [
                    ("font-size", "10px"),
                    ("padding", "3px 6px"),
                    ("border-bottom", "1px solid #1e293b"),
                    ("text-align", "center"),
                ],
            },

        ])

        .format(
            na_rep="—"
        )
    )

    # ========================================================================
    # DISPLAY
    # ========================================================================
    ipy(
        styled
    )


# ═════ [source cell 19] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 12 — QUANT ENGINE (CONTROLLER)                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Orchestrate toàn pipeline theo thứ tự:
#
# Fetch → Clean → VP → Trend → RS → MF → VSA → RSI/Composite Divergence
# → Indicators → DryUp → ITP/MA/Holder → WinRate → Score → Filter
# → Entry → Levels → PositionSize → Output
#
# Hai entry point chính:
#   engine.run(mode="swing")        → Scan toàn bộ VN100
#   engine.run(["VND","FPT"], mode) → Scan danh sách riêng
#   engine.detail("VND")            → Phân tích chi tiết 1 mã

class QuantEngine:
    """
    Controller chính v5.2 — orchestrate toàn bộ pipeline.

    Pipeline mới so với v5.1:
    + VSAEngine.get_latest() → vsa_signal → vào raw dict
    + vsa_signal → ScoringEngine (weight 10)
    + vsa_signal → WinRateEstimator (5 pattern mới)
    + vsa_signal → apply_filters (2 hard filter mới)
    + vsa_signal → classify_horizon (T+ bonus)
    + vsa_signal → output column "VSA"
    + vp_bins = 30 (từ 8)
    """

    def __init__(self, capital: float = 100_000_000, cfg: QuantConfig = None):
        self.cfg     = cfg or QuantConfig(capital=capital)
        self.cfg.capital = capital

        # FIX: Validate toàn bộ config ngay khi engine khởi tạo.
        # Nhờ vậy lỗi thiếu self.cfg.xxx được phát hiện ngay, thay vì
        # chạy tới một mã cụ thể (ví dụ VIC) mới crash giữa scan.
        validate_quant_config(self.cfg)

        self.dl      = DataLayer(self.cfg)
        self.regime  = RegimeEngine(self.dl)
        self.ind_eng = IndicatorEngine()
        self.score_e = ScoringEngine()
        self.sig_b   = SignalBuilder(self.cfg)
        self.pos_sz  = PositionSizer(self.cfg)
        self.dryup_d = VolumeDryupDetector(self.cfg)
        self.wr_est  = WinRateEstimator(self.cfg)
        # VSAEngine là stateless (static methods) — không cần instantiate

    def run_pipeline(self, symbol: str, df_vni: pd.DataFrame,
                    mode: str, weights: dict, regime_mult: float,
                    min_score: float, wr_mult: float = 1.0) -> Optional[dict]:
        """Pipeline xử lý 1 mã — return dict hoặc None nếu bỏ qua."""

        # ========================================================================
        # STEP 1 — FETCH DATA
        # ========================================================================
        df = self.dl.fetch(symbol, self.cfg.lookback_short)

        if df is None or len(df) < 25:
            return None

        # ========================================================================
        # STEP 2 — VP + TREND + RS + MONEY FLOW
        # ========================================================================
        vp = self.ind_eng.volume_profile(
            df,
            self.cfg.vp_bins
        )

        df_lng = self.dl.fetch(
            symbol,
            self.cfg.lookback_long
        )

        trend = self.ind_eng.long_trend(df_lng)

        rs = self.ind_eng.relative_strength(
            df,
            df_vni
        )

        mf = self.ind_eng.money_flow(
            df
        )

        # ========================================================================
        # STEP 2b — COMPOSITE INDEX DIVERGENCE
        # ========================================================================
        # Tính D1 / W1 / M1 từ cùng df_long để tránh gọi API thêm.
        divergence_mtf = RSIDivergenceEngine.multi_timeframe(
            df_lng,
            self.cfg
        )

        divergence_d1 = divergence_mtf.get(
            "D1",
            {}
        )

        # ========================================================================
        # STEP 3 — VSA
        # ========================================================================
        vsa_signal = VSAEngine.get_latest(df)

        # ========================================================================
        # STEP 4 — INDICATORS
        # ========================================================================
        raw = self.ind_eng.compute_all(
            df,
            vp,
            trend,
            rs,
            mf,
            vsa_signal,
            df_long=df_lng,
            divergence=divergence_d1,
            divergence_mtf=divergence_mtf
        )

        # ========================================================================
        # STEP 5 — VOLUME DRY-UP
        # ========================================================================
        dryup = self.dryup_d.detect(df)

        # ========================================================================
        # STEP 5b — MA / ITP / HOLDER / DIVERGENCE ADVICE
        # ========================================================================
        ma_ctx = MAContextEngine.compute(
            df,
            raw
        )

        itp_touch = ItpTouchAnalyzer.analyze(
            raw.get("ichi", {})
        )

        holder = HolderAdvisor.advise(
            raw,
            ma_ctx,
            itp_touch,
            dryup
        )

        # Recommendation divergence dùng D1.
        div_adv = self.sig_b.divergence_advice(
            raw,
            mode
        )

        # ========================================================================
        # STEP 6 — WIN RATE
        # ========================================================================
        wr = self.wr_est.estimate(
            raw,
            dryup,
            wr_mult
        )

        # ========================================================================
        # STEP 7 — LIQUIDITY FILTER
        # ========================================================================
        liq_ok, liq_reason = self.sig_b.liquidity_ok(
            raw,
            self.cfg
        )

        # ========================================================================
        # STEP 8 — HARD FILTER
        # ========================================================================
        passed, reasons = self.sig_b.apply_filters(
            raw,
            mode,
            liq_ok,
            liq_reason,
            dryup
        )

        # ========================================================================
        # STEP 9 — SCORE
        # ========================================================================
        scores, score = self.score_e.score(
            raw,
            mode,
            weights,
            regime_mult,
            bonus=dryup["bonus_score"]
        )

        # ========================================================================
        # STEP 10 — ENTRY + LEVELS
        # ========================================================================
        se = self.sig_b.smart_entry(
            df,
            raw,
            vp,
            mode
        )

        lvl = self.sig_b.levels(
            df,
            raw,
            vp,
            se,
            mode
        )

        # ========================================================================
        # STEP 11 — POSITION SIZING
        # ========================================================================
        sl_use = (
            lvl["stoploss"]
            if mode == "swing"
            else lvl["hold_sl"]
        )

        pos = self.pos_sz.calculate(
            lvl["entry"],
            sl_use,
            score,
            raw["atr_ratio"],
            wr["win_rate_est"]
        )

        # ========================================================================
        # STEP 12 — SIGNAL + HORIZON
        # ========================================================================
        verdict = self.sig_b.verdict(
            score,
            passed,
            mode
        )

        horizon = self.sig_b.classify_horizon(
            raw
        )

        rr_check = (
            lvl["swing_rr"]
            if mode == "swing"
            else lvl["hold_rr"]
        )

        # Dùng threshold đúng theo horizon.
        min_rr_required = (
            self.cfg.min_rr_swing
            if mode == "swing"
            else self.cfg.min_rr_hold
        )

        ok = (
            passed
            and score >= min_score
            and rr_check >= min_rr_required
        )

        # ========================================================================
        # COMPOSITE INDEX DIVERGENCE DATA
        # ========================================================================
        div_mtf = raw.get(
            "rsi_divergence_mtf",
            {}
        ) or {}

        div_w1 = div_mtf.get(
            "W1",
            {}
        ) or {}

        div_m1 = div_mtf.get(
            "M1",
            {}
        ) or {}

        # ========================================================================
        # RETURN RESULT
        # ========================================================================
        return {

            # ====================================================================
            # BASIC
            # ====================================================================
            "Mã": symbol,

            "Tín hiệu": verdict,

            "Khuyến nghị": (
                f"{horizon} | {div_adv['label']}"
                if div_adv["label"] != "—"
                else horizon
            ),

            "Score": round(
                score,
                2
            ),

            "Win%": f"{wr['win_rate_est']:.0f}%",

            "Giá": f"{raw['close']:.2f}",

            "RSI": f"{raw['rsi']:.2f}",

            "CMF": f"{round(raw['cmf'], 3):.3f}",

            "RS": f"{raw['rs']:.1f}",

            "Vol": f"{raw['volume_ratio']:.1f}x",

            # ====================================================================
            # COMPOSITE INDEX DIVERGENCE — D1
            # ====================================================================
            "Composite Div": raw.get(
                "rsi_divergence_type",
                "none"
            ),

            "Div Advice": div_adv.get(
                "label",
                "—"
            ),

            "Div Bias": div_adv.get(
                "bias",
                "neutral"
            ),

            "Div Strength": round(
                float(
                    raw.get(
                        "rsi_divergence_strength",
                        0
                    ) or 0
                ),
                2
            ),

            "Div Age": raw.get(
                "rsi_divergence_age",
                None
            ),

            "Div Confirmed": bool(
                raw.get(
                    "rsi_divergence_confirmed",
                    False
                )
            ),

            "Div Pivot Date": raw.get(
                "rsi_divergence_pivot_date",
                None
            ),

            "Div Confirm Date": raw.get(
                "rsi_divergence_confirmed_date",
                None
            ),

            # ====================================================================
            # COMPOSITE INDEX DIVERGENCE — W1
            # ====================================================================
            "Div W1": div_w1.get(
                "type",
                "none"
            ),

            "Div W1 Strength": round(
                float(
                    div_w1.get(
                        "strength",
                        0
                    ) or 0
                ),
                2
            ),

            # ====================================================================
            # COMPOSITE INDEX DIVERGENCE — M1
            # ====================================================================
            "Div M1": div_m1.get(
                "type",
                "none"
            ),

            "Div M1 Strength": round(
                float(
                    div_m1.get(
                        "strength",
                        0
                    ) or 0
                ),
                2
            ),

            # ====================================================================
            # VSA / MARKET STRUCTURE
            # ====================================================================
            "VSA": vsa_signal,

            "Thanh khoản": (
                f"{raw['avg_vol_20d']//1000:.0f}K/ng"
            ),

            "Dòng tiền": raw["mf_label"],

            "Cạn cung": dryup["dry_up_label"],

            "VP": _VP.get(
                raw["vp_signal"],
                "—"
            ),

            "Trend": _TREND.get(
                raw["trend_long"],
                "—"
            ),

            # ====================================================================
            # ENTRY / RISK / TARGET
            # ====================================================================
            "Entry": f"{lvl['entry']:.2f}",

            "Entry zone": lvl["entry_note"],

            "SL T+": f"{lvl['stoploss']:.2f}",

            "SL Hold": f"{lvl['hold_sl']:.2f}",

            "T+ T1": f"{lvl['swing_t1']:.2f}",

            "T+ T2": f"{lvl['swing_t2']:.2f}",

            "T+ R:R": f"1:{lvl['swing_rr']:.1f}",

            "T+ %": f"{lvl['swing_t1_pct']:.2f}",

            "Hold T1": f"{lvl['hold_t1']:.2f}",

            "Hold T2": f"{lvl['hold_t2']:.2f}",

            "Hold R:R": f"1:{lvl['hold_rr']:.1f}",

            "Action": lvl["action"],

            "Lý do": reasons,

            # ====================================================================
            # POSITION SIZE
            # ====================================================================
            "Giá trị": f"{pos['cost_vnd']/1e6:.0f}M",

            "% NAV": f"{pos['pct_nav']:.2f}%",

            "Rủi ro %": f"{pos['risk_pct_nav']:.2f}%",

            # ====================================================================
            # ITP / DAO GĂM EXISTING
            # ====================================================================
            "ITP Dao Găm D1": itp_touch[
                "ITP Dao Găm D1"
            ],

            "ITP Dao Găm W1/M1": itp_touch[
                "ITP Dao Găm W1/M1"
            ],

            # ====================================================================
            # DAO GĂM ICHIMOKU — STATUS
            # ====================================================================
            "Dao Gam D1": raw.get(
                "ITP Dao Găm D1 Status",
                "—"
            ),

            "Dao Gam W1": raw.get(
                "ITP Dao Găm W1 Status",
                "—"
            ),

            "Dao Gam M1": raw.get(
                "ITP Dao Găm M1 Status",
                "—"
            ),

            # ====================================================================
            # DAO GĂM ICHIMOKU — D1 DETAILS
            # ====================================================================
            "D1 Kijun": raw.get(
                "d1_kijun"
            ),

            "D1 Kijun Flat": raw.get(
                "d1_kijun_flat"
            ),

            "D1 Senkou B Flat": raw.get(
                "d1_ssb_flat"
            ),

            "D1 Khach San": raw.get(
                "d1_khach_san"
            ),

            # ====================================================================
            # DAO GĂM ICHIMOKU — W1 DETAILS
            # ====================================================================
            "W1 Kijun": raw.get(
                "w1_kijun"
            ),

            "W1 Kijun Flat": raw.get(
                "w1_kijun_flat"
            ),

            "W1 Senkou B Flat": raw.get(
                "w1_ssb_flat"
            ),

            "W1 Khach San": raw.get(
                "w1_khach_san"
            ),

            # ====================================================================
            # DAO GĂM ICHIMOKU — M1 DETAILS
            # ====================================================================
            "M1 Kijun": raw.get(
                "m1_kijun"
            ),

            "M1 Kijun Flat": raw.get(
                "m1_kijun_flat"
            ),

            "M1 Senkou B Flat": raw.get(
                "m1_ssb_flat"
            ),

            "M1 Khach San": raw.get(
                "m1_khach_san"
            ),

            # Tổng hợp sức mạnh Dao Găm.
            "Dao Gam Strength": raw.get(
                "itp_strength",
                0
            ),

            # ====================================================================
            # ITP / MA / HOLDER
            # ====================================================================
            "KC Hỗ Trợ ITP %": itp_touch[
                "Khoảng cách hỗ trợ ITP %"
            ],

            "MA Context": ma_ctx[
                "MA Context"
            ],

            "Holder Action": holder[
                "Holder Action"
            ],

            "Holder Reason": holder[
                "Holder Reason"
            ],

            # ====================================================================
            # INTERNAL COLUMNS
            # ====================================================================
            "_score": score,

            "_ok": ok,

            "_win_rate": wr[
                "win_rate_est"
            ],

            "_dry_strength": dryup[
                "dry_up_strength"
            ],

            "_vsa": vsa_signal,

            "_divergence": raw.get(
                "rsi_divergence_type",
                "none"
            ),

            "_divergence_bias": div_adv[
                "bias"
            ],

            "_divergence_reason": div_adv[
                "reason"
            ],

            "_positives": " | ".join(
                f"{k}={v:.1f}"
                for k, v in scores.items()
                if v >= 6.5
            ),

            "_wr_patterns": ", ".join(
                wr["wr_pattern_names"]
            ),
        }

    def run(self, symbols: list = None, mode: str = "swing", top_n: int = 300) -> pd.DataFrame:
        assert mode in ("swing", "hold")
        watchlist = symbols or VN100
        label     = "SWING T+1→T+2.5" if mode == "swing" else "HOLD DÀI HẠN"

        print(f"\n{'═'*72}")
        print(f"  VN QUANT ENGINE v5.2 | {label} | {len(watchlist)} mã")
        print(f"  Vốn: {self.cfg.capital/1e6:.0f}M  Risk/trade: {self.cfg.risk_per_trade*100:.1f}%")
        print(f"  VP Bins: {self.cfg.vp_bins}  |  Lookback: {self.cfg.lookback_short}d/{self.cfg.lookback_long}d")
        print(f"  {datetime.today().strftime('%d/%m/%Y %H:%M')}")
        print(f"{'═'*72}\n")

        ctx       = self.regime.detect()
        weights   = self.regime.get_dynamic_weights()
        r_mult    = ctx["score_mult"]
        wr_mult   = ctx.get("wr_mult", 1.0)
        min_score = self.regime.get_min_score(mode, self.cfg)

        print(f"\n  Regime: {ctx['regime'].upper()}  Score×{r_mult:.2f}  WR×{wr_mult:.2f}  MinScore:{min_score:.1f}")
        print(f"  Weights: vol={weights.get('volume_ratio',0):.0f}% cmf={weights.get('cmf',0):.0f}% "
              f"vsa={weights.get('vsa',0):.0f}% trend={weights.get('trend',0):.0f}% "
              f"vp={weights.get('vp_position',0):.0f}%\n")

        df_vni  = self.dl.fetch("VNINDEX", self.cfg.lookback_short)
        records = []

        for i, sym in enumerate(watchlist):
            print(f"  [{i+1:3d}/{len(watchlist)}] {sym:6s}...", end=" ", flush=True)
            try:
                rec = self.run_pipeline(sym, df_vni, mode, weights, r_mult, min_score, wr_mult)
                if rec is None:
                    print("❌ thiếu dữ liệu"); continue

                vsa_icon  = ("🔥" if "NỔ VOL" in rec["VSA"] else
                             "🔨" if "RÚT CHÂN" in rec["VSA"] else
                             "⚠" if "PHÂN PHỐI" in rec["VSA"] else "")
                dry_icon  = "💎" if rec["_dry_strength"] >= 3 else "📦" if rec["_dry_strength"] == 2 else ""
                ok_icon   = ("🔥" if "🔥" in rec["Tín hiệu"] or "💎" in rec["Tín hiệu"]
                             else "✅" if rec["_ok"] else "·")
                print(f"{ok_icon}{vsa_icon}{dry_icon}  {rec['Score']:.1f}  WR:{rec['Win%']}  {rec['Dòng tiền']}")
                records.append(rec)
            except AttributeError as e:
                # Config / code integration bug: KHÔNG nuốt lỗi và chạy tiếp.
                # Nếu lỗi kiểu self.cfg.xxx thì cần sửa engine ngay.
                print(f"❌ ENGINE CONFIG ERROR — {sym}: {e}")
                raise
            except KeyError as e:
                # Thiếu key trong raw/lvl thường là lỗi integration giữa các engine.
                print(f"❌ ENGINE DATA/KEY ERROR — {sym}: {e}")
                raise
            except Exception as e:
                # Lỗi dữ liệu/API của riêng mã vẫn được log và cho phép scan tiếp.
                print(f"⚠ DATA/PROCESSING ERROR — {sym}: {e}")
                import traceback
                with open("quant_engine_err.log", "a", encoding="utf-8") as f:
                    f.write(f"\n--- {datetime.now()} | {sym} ---\n")
                    f.write(traceback.format_exc())
                continue

            if i < len(watchlist) - 1:
                time.sleep(self.cfg.delay_sec)

        if not records:
            print("❌ Không có dữ liệu."); return pd.DataFrame()

        res = (pd.DataFrame(records)
               .sort_values(["_ok", "_score"], ascending=[False, False])
               .reset_index(drop=True))

        n_ok  = res["_ok"].sum()
        n_f   = res["Tín hiệu"].str.contains("🔥|💎").sum()
        n_g   = res["Tín hiệu"].str.contains("✅").sum()
        n_du  = (res["_dry_strength"] >= 2).sum()
        n_vsa = res["_vsa"].str.contains("NỔ VOL|RÚT CHÂN").sum()

        print(f"\n{'═'*72}")
        print(f"  {ctx['label']}")
        print(f"  Scan:{len(res)}  Đủ ĐK:{n_ok}  Mạnh:{n_f}  Xem:{n_g}  "
              f"Cạn cung:{n_du}  VSA tích cực:{n_vsa}")
        print(f"{'═'*72}\n")

        _display(res.head(top_n) if not res.empty else res, mode)
        self._print_detail(res)
        return res

    def detail(self, symbol: str, mode: str = "swing"):
        """Phân tích chi tiết 1 mã với giải thích đầy đủ."""
        print(f"\n{'═'*58}\n  PHÂN TÍCH CHI TIẾT: {symbol}  (v5.2)\n{'═'*58}\n")
        ctx     = self.regime.detect()
        weights = self.regime.get_dynamic_weights()
        df_vni  = self.dl.fetch("VNINDEX", self.cfg.lookback_short)
        rec     = self.run_pipeline(symbol, df_vni, mode, weights, ctx["score_mult"],
                                    self.regime.get_min_score(mode, self.cfg),
                                    ctx.get("wr_mult", 1.0))
        if rec is None:
            print("Không lấy được dữ liệu."); return

        print(f"  Mã: {symbol}  |  Giá: {rec['Giá']}  |  Score: {rec['Score']:.1f}  |  Win Rate: {rec['Win%']}")
        print(f"  Tín hiệu: {rec['Tín hiệu']}  |  Khuyến nghị: {rec['Khuyến nghị']}")
        print(f"  VSA: {rec['VSA']}  |  Dòng tiền: {rec['Dòng tiền']}")

        print(f"  Trend: {rec['Trend']}  |  VP: {rec['VP']}")
        print(f"  Cạn cung: {rec['Cạn cung']}")

        print(f"\n  ── GIAO DỊCH ─────────────────────────────────────────────")
        print(f"  Entry   : {rec['Entry']}  ({rec['Entry zone']})")
        print(f"  SL T+   : {rec['SL T+']}  (chặt - swing)")
        print(f"  SL Hold : {rec['SL Hold']}  (lỏng - hold)")
        print(f"  Action  : {rec['Action']}")
        print(f"\n  T+ (1-3 phiên): T1={rec['T+ T1']} (+{rec['T+ %']}%)  T2={rec['T+ T2']}  R:R {rec['T+ R:R']}")
        print(f"  Hold (dài hạn): T1={rec['Hold T1']}  T2={rec['Hold T2']}  R:R {rec['Hold R:R']}")
        print(f"\n  ── POSITION SIZING ────────────────────────────────────────")
        print(f"  Giá trị: {rec['Giá trị']}  |  % NAV: {rec['% NAV']}  |  Rủi ro: {rec['Rủi ro %']} NAV")
        print(f"\n  ── WIN RATE PATTERNS ──────────────────────────────────────")
        print(f"  {rec['_wr_patterns']}")
        if rec["_positives"]:
            print(f"\n  ── ĐIỂM MẠNH ──────────────────────────────────────────────")
            print(f"  {rec['_positives']}")
        if rec["Lý do"]:
            print(f"\n  ── LÝ DO BỊ LỌC ───────────────────────────────────────────")
            for r in rec["Lý do"]:
                print(f"  • {r}")
        print()

    def _print_detail(self, res: pd.DataFrame):
        """In chi tiết top mã đạt điều kiện."""
        top = res[res["Tín hiệu"].str.contains("🔥|💎|✅")].head(8)
        if top.empty: return
        print(f"\n  📋 Chi tiết top {len(top)} mã:")
        for _, r in top.iterrows():
            dry  = f"  {r['Cạn cung']}" if r["_dry_strength"] >= 2 else ""
            print(f"\n  {r['Mã']:6s}  {r['Tín hiệu']}  {r['Khuyến nghị']}")
            print(f"         Score={r['Score']:.1f}  WR={r['Win%']}  VSA={r['VSA']}{dry}")
            print(f"         {r['Dòng tiền']}")
            print(f"         Entry: {r['Entry']} ({r['Entry zone']})  SL: {r['SL T+']}")
            print(f"         T+  → T1:{r['T+ T1']}(+{r['T+ %']}%)  T2:{r['T+ T2']}  R:R {r['T+ R:R']}")
            print(f"         Hold→ T1:{r['Hold T1']}  T2:{r['Hold T2']}  R:R {r['Hold R:R']}")
            print(f"         {r['Action']}  {r['Giá trị']}  {r['% NAV']} NAV  Rủi ro {r['Rủi ro %']}")


# ═════ [source cell 20] Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam.ipynb ═════
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CELL 13 — CONVENIENCE & ENTRY POINT                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def run_scanner(symbols: List[str] = None, mode: str = "swing", top_n: int = 300, capital: float = 100_000_000):
    """Shortcut backward-compatible với v3/v4/v5."""
    engine = QuantEngine(capital=capital)
    return engine.run(symbols=symbols, mode=mode, top_n=top_n)
