"""
Engine Smart Money Concepts (SMC) — đọc CẤU TRÚC đồ thị giá (không phải chỉ số tại 1 phiên).

Đây là lý do bạn yêu cầu thêm S9: các strategy khác (S1–S8) phần lớn chấm điểm chỉ báo TẠI PHIÊN
GẦN NHẤT; SMC thì ngược lại — nhìn vào chuỗi đỉnh/đáy để xác định xu hướng đang hình thành ra sao,
vùng giá nào "tổ chức" (smart money) có khả năng đã gom/xả, và dùng đúng các vùng đó làm entry/SL/TP.

Các khái niệm áp dụng (đúng định nghĩa SMC phổ biến — ICT/ Smart Money Concepts):

1. SWING (điểm xoay)
   Một nến là "đỉnh xoay" nếu high của nó là max trong cửa sổ `left`/`right` nến hai bên; tương tự cho
   "đáy xoay". Vì cần `right` nến SAU đó mới xác nhận, swing chỉ được coi là tồn tại kể từ nến thứ
   (idx + right) — KHÔNG lộ thông tin tương lai tại các nến trước đó (khi quét lịch sử để vẽ cấu trúc,
   luôn dùng mốc này). Lọc nhiễu bằng biên độ tối thiểu so với ATR (`min_swing_atr`).

2. MARKET STRUCTURE — BOS / CHoCH
   Theo dõi chuỗi đỉnh xoay (SH) và đáy xoay (SL) gần nhất, xác định xu hướng hiện tại:
     - Uptrend  : đỉnh sau cao hơn đỉnh trước (HH) VÀ đáy sau cao hơn đáy trước (HL)
     - Downtrend: đỉnh sau thấp hơn (LH) VÀ đáy sau thấp hơn (LL)
   Sự kiện cấu trúc (xác nhận bằng GIÁ ĐÓNG CỬA vượt qua mức, không dùng bóng nến — giảm nhiễu):
     - BOS (Break of Structure)   : giá đóng cửa phá đỉnh/đáy xoay THEO ĐÚNG hướng xu hướng hiện tại
                                     → xác nhận xu hướng tiếp diễn.
     - CHoCH (Change of Character): giá đóng cửa phá đỉnh/đáy xoay NGƯỢC xu hướng hiện tại
                                     → cảnh báo khả năng đảo chiều; xu hướng được cập nhật lại từ đây.

3. ORDER BLOCK (OB) — vùng nến tổ chức
   Nến ĐỐI LẬP MÀU cuối cùng trước một đợt di chuyển mạnh tạo ra BOS/CHoCH:
     - OB tăng = nến giảm cuối cùng trước đợt tăng phá cấu trúc lên.
     - OB giảm = nến tăng cuối cùng trước đợt giảm phá cấu trúc xuống.
   Vùng OB = [low, high] của nến đó. OB coi là "đã test" (mitigated) khi giá sau đó quay lại GIAO với
   vùng này — theo quy ước SMC, sau khi test thì OB coi như đã hoàn thành vai trò, dùng OB CHƯA TEST
   làm vùng entry đáng tin hơn.

4. FAIR VALUE GAP (FVG) — khoảng trống mất cân bằng
   3 nến liên tiếp (i-1, i, i+1): FVG tăng khi low[i+1] > high[i-1] (nến i là nến bứt phá mạnh để lại
   khoảng trống); FVG giảm khi high[i+1] < low[i-1]. Giá có xu hướng quay lại "lấp" khoảng trống này
   trước khi đi tiếp — vùng FVG chưa lấp là vùng hút giá tự nhiên, dùng làm entry phụ trợ.

5. LIQUIDITY POOL (vùng thanh khoản) & LIQUIDITY SWEEP (quét thanh khoản)
   Nhiều đỉnh xoay gần bằng nhau (trong dung sai `liq_tol_atr`×ATR) tạo thành vùng "buy-side liquidity"
   (lệnh dừng lỗ của người bán khống + lệnh chờ breakout nằm phía trên) — tương tự đáy xoay tạo
   "sell-side liquidity" phía dưới. "Sweep" = giá xuyên qua vùng này (quét thanh khoản/stop) rồi đóng
   cửa quay trở lại — một mẫu hình đảo chiều kinh điển, đặc biệt mạnh khi đi kèm CHoCH ngay sau đó.

6. PREMIUM / DISCOUNT (vùng chiết khấu/định giá cao)
   Trong biên dao động của đợt sóng cấu trúc gần nhất (đáy xoay ↔ đỉnh xoay đang chi phối), chia đôi
   50% = điểm cân bằng (equilibrium). Dưới 50% = Discount (vùng "rẻ", ưu tiên tìm mua trong uptrend);
   trên 50% = Premium (vùng "đắt", ưu tiên tìm bán/chốt lời, tránh mua mới).

TẤT CẢ đều nhân quả: chỉ dùng OHLCV tại/trước phiên đang xét (không `shift(-n)`, không nhìn nến tương lai).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Literal
import numpy as np
import pandas as pd

from .ai_indicators import atr as _atr_series

Kind = Literal["high", "low"]


@dataclass
class Swing:
    idx: int            # vị trí nến tạo đỉnh/đáy
    confirmed_idx: int  # vị trí nến mà tại đó swing này được XÁC NHẬN (idx + right)
    price: float
    kind: Kind


@dataclass
class StructureEvent:
    idx: int             # nến xác nhận break (đóng cửa vượt mức)
    kind: str            # "BOS_UP" | "BOS_DOWN" | "CHOCH_UP" | "CHOCH_DOWN"
    level: float          # mức đỉnh/đáy xoay bị phá
    broken_swing_idx: int
    trend_after: str      # "up" | "down"


@dataclass
class OrderBlock:
    idx: int               # nến hình thành OB (nến đối lập màu cuối cùng)
    top: float
    bottom: float
    kind: str               # "bullish" | "bearish"
    break_idx: int          # nến xác nhận BOS/CHoCH mà OB này dẫn tới
    break_kind: str         # "BOS" | "CHOCH"
    mitigated_idx: Optional[int] = None   # nến đầu tiên giá quay lại giao với vùng OB (None = chưa test)

    @property
    def mitigated(self) -> bool:
        return self.mitigated_idx is not None


@dataclass
class FVG:
    idx: int          # nến giữa (i) của bộ 3 nến tạo gap
    top: float
    bottom: float
    kind: str          # "bullish" | "bearish"
    filled_idx: Optional[int] = None

    @property
    def filled(self) -> bool:
        return self.filled_idx is not None


@dataclass
class LiquidityPool:
    price: float
    kind: str                 # "buy_side" (trên đỉnh) | "sell_side" (dưới đáy)
    touches: List[int]        # các idx đỉnh/đáy xoay góp vào pool này
    swept_idx: Optional[int] = None

    @property
    def swept(self) -> bool:
        return self.swept_idx is not None


@dataclass
class SMCAnalysis:
    swings: List[Swing] = field(default_factory=list)
    events: List[StructureEvent] = field(default_factory=list)
    order_blocks: List[OrderBlock] = field(default_factory=list)
    fvgs: List[FVG] = field(default_factory=list)
    liquidity: List[LiquidityPool] = field(default_factory=list)
    trend: str = "ranging"                       # "up" | "down" | "ranging"
    last_event: Optional[StructureEvent] = None
    range_low: Optional[float] = None             # biên dưới đợt sóng đang chi phối (cho premium/discount)
    range_high: Optional[float] = None
    zone: str = "equilibrium"                     # "discount" | "equilibrium" | "premium"
    zone_pct: Optional[float] = None               # vị trí giá hiện tại trong range, 0=đáy .. 1=đỉnh


# ───────────────────────────── 1. Swing detection ─────────────────────────────
def detect_swings(df: pd.DataFrame, left: int = 3, right: int = 3, min_swing_atr: float = 0.4) -> List[Swing]:
    high, low = df["high"].values, df["low"].values
    atr = _atr_series(df, 14).values
    n = len(df)
    swings: List[Swing] = []
    for i in range(left, n - right):
        window_h = high[i - left: i + right + 1]
        window_l = low[i - left: i + right + 1]
        a = atr[i] if not np.isnan(atr[i]) else 0.0
        if a <= 0:   # không có biến động (ATR=0, vd. dữ liệu phẳng tuyệt đối) -> không đủ cơ sở xác định swing
            continue
        if high[i] == window_h.max() and (high[i] - window_h.min()) >= min_swing_atr * a:
            swings.append(Swing(idx=i, confirmed_idx=i + right, price=float(high[i]), kind="high"))
        if low[i] == window_l.min() and (window_l.max() - low[i]) >= min_swing_atr * a:
            swings.append(Swing(idx=i, confirmed_idx=i + right, price=float(low[i]), kind="low"))
    swings.sort(key=lambda s: s.idx)
    return swings


# ───────────────────────────── 2. Market structure: BOS / CHoCH ─────────────────────────────
def classify_structure(df: pd.DataFrame, swings: List[Swing]) -> List[StructureEvent]:
    """Duyệt theo thời gian NẾN XÁC NHẬN (confirmed_idx) của từng swing — đúng thứ tự thông tin thực sự
    có sẵn tại từng thời điểm — rồi dò các nến sau đó xem khi nào giá đóng cửa phá mức."""
    close = df["close"].values
    events: List[StructureEvent] = []
    trend = "ranging"
    last_high: Optional[Swing] = None     # đỉnh xoay gần nhất đã biết, CHƯA bị phá
    last_low: Optional[Swing] = None
    pending = sorted(swings, key=lambda s: s.confirmed_idx)
    p = 0
    active_levels: List[Swing] = []       # các swing đã "biết" tính tới nến hiện tại, chưa bị phá

    for i in range(len(df)):
        while p < len(pending) and pending[p].confirmed_idx == i:
            sw = pending[p]
            active_levels.append(sw)
            if sw.kind == "high":
                last_high = sw if last_high is None or sw.idx > last_high.idx else last_high
            else:
                last_low = sw if last_low is None or sw.idx > last_low.idx else last_low
            p += 1
        if i == 0:
            continue
        # Kiểm tra phá đỉnh/đáy đang active gần nhất theo mỗi phía (chỉ cần mức GẦN NHẤT phía trên/dưới)
        highs_above = [s for s in active_levels if s.kind == "high" and s.price > close[i - 1]]
        lows_below = [s for s in active_levels if s.kind == "low" and s.price < close[i - 1]]
        nearest_high = min(highs_above, key=lambda s: s.price) if highs_above else None
        nearest_low = max(lows_below, key=lambda s: s.price) if lows_below else None

        if nearest_high is not None and close[i] > nearest_high.price:
            kind = "BOS_UP" if trend != "down" else "CHOCH_UP"
            events.append(StructureEvent(idx=i, kind=kind, level=nearest_high.price,
                                         broken_swing_idx=nearest_high.idx, trend_after="up"))
            trend = "up"
            active_levels = [s for s in active_levels if s is not nearest_high]
        elif nearest_low is not None and close[i] < nearest_low.price:
            kind = "BOS_DOWN" if trend != "up" else "CHOCH_DOWN"
            events.append(StructureEvent(idx=i, kind=kind, level=nearest_low.price,
                                         broken_swing_idx=nearest_low.idx, trend_after="down"))
            trend = "down"
            active_levels = [s for s in active_levels if s is not nearest_low]
    return events


# ───────────────────────────── 3. Order Blocks ─────────────────────────────
def find_order_blocks(df: pd.DataFrame, events: List[StructureEvent]) -> List[OrderBlock]:
    open_, close = df["open"].values, df["close"].values
    high, low = df["high"].values, df["low"].values
    obs: List[OrderBlock] = []
    for ev in events:
        bullish_break = ev.trend_after == "up"
        # dò ngược từ nến NGAY TRƯỚC điểm phá (ev.idx) tới nến đối lập màu gần nhất
        j = ev.idx - 1
        while j > 0 and ((close[j] >= open_[j]) == bullish_break):
            j -= 1
        if j < 0:
            continue
        ob_kind = "bullish" if bullish_break else "bearish"
        ob = OrderBlock(idx=j, top=float(high[j]), bottom=float(low[j]), kind=ob_kind,
                        break_idx=ev.idx, break_kind="CHOCH" if "CHOCH" in ev.kind else "BOS")
        # mitigation: nến đầu tiên SAU khi hình thành giá quay lại giao với vùng OB
        for k in range(ev.idx + 1, len(df)):
            if low[k] <= ob.top and high[k] >= ob.bottom:
                ob.mitigated_idx = k
                break
        obs.append(ob)
    return obs


# ───────────────────────────── 4. Fair Value Gaps ─────────────────────────────
def find_fvgs(df: pd.DataFrame) -> List[FVG]:
    high, low = df["high"].values, df["low"].values
    fvgs: List[FVG] = []
    for i in range(1, len(df) - 1):
        if low[i + 1] > high[i - 1]:
            g = FVG(idx=i, top=float(low[i + 1]), bottom=float(high[i - 1]), kind="bullish")
        elif high[i + 1] < low[i - 1]:
            g = FVG(idx=i, top=float(low[i - 1]), bottom=float(high[i + 1]), kind="bearish")
        else:
            continue
        for k in range(i + 2, len(df)):
            if low[k] <= g.top and high[k] >= g.bottom:
                g.filled_idx = k
                break
        fvgs.append(g)
    return fvgs


# ───────────────────────────── 5. Liquidity pools & sweep ─────────────────────────────
def find_liquidity_pools(df: pd.DataFrame, swings: List[Swing], liq_tol_atr: float = 0.25) -> List[LiquidityPool]:
    atr_last = _atr_series(df, 14).iloc[-1]
    tol = (atr_last if pd.notna(atr_last) else df["close"].iloc[-1] * 0.01) * liq_tol_atr
    high, low = df["high"].values, df["low"].values
    pools: List[LiquidityPool] = []

    def cluster(items: List[Swing], kind: str):
        used = set()
        for s in sorted(items, key=lambda x: x.price):
            if s.idx in used:
                continue
            grp = [t for t in items if t.idx not in used and abs(t.price - s.price) <= tol]
            if len(grp) >= 1:
                for t in grp:
                    used.add(t.idx)
                price = float(np.mean([t.price for t in grp]))
                pools.append(LiquidityPool(price=price, kind=kind, touches=[t.idx for t in grp]))

    cluster([s for s in swings if s.kind == "high"], "buy_side")
    cluster([s for s in swings if s.kind == "low"], "sell_side")

    for pool in pools:
        start = max(pool.touches) + 1 if pool.touches else 0
        for k in range(start, len(df)):
            if pool.kind == "buy_side" and high[k] > pool.price and df["close"].iloc[k] < pool.price:
                pool.swept_idx = k
                break
            if pool.kind == "sell_side" and low[k] < pool.price and df["close"].iloc[k] > pool.price:
                pool.swept_idx = k
                break
    return pools


# ───────────────────────────── 6. Premium / Discount ─────────────────────────────
def premium_discount(df: pd.DataFrame, trend: str, last_event: Optional[StructureEvent],
                     swings: List[Swing]):
    """
    Biên dao động = 2 swing GẦN NHẤT, NGƯỢC KIND nhau (1 đỉnh + 1 đáy) — đúng kiểu vẽ Fibonacci retracement
    giữa 2 điểm xoay cố định (như ảnh tham chiếu "Super SMC": 0, 0.236, 0.5, 0.618, 1...), KHÔNG tự co giãn
    theo giá hôm nay.

    LÝ DO đổi cách tính (so với bản đầu — lỗi đã phát hiện khi test): bản cũ dùng
    `range_high = max(..., giá hôm nay)` cho trường hợp uptrend — nghĩa là chính giá hôm nay luôn được tính
    vào biên trên, nên ngay khi xu hướng vừa chuyển sang tăng, "vùng Discount" gần như KHÔNG BAO GIỜ xảy ra
    được nữa (giá luôn kéo biên trên lên theo). Dùng 2 swing CỐ ĐỊNH (không phụ thuộc giá hôm nay) mới đúng
    bản chất "giá đang hồi được bao nhiêu % của đợt sóng vừa qua" mà Premium/Discount cần đo.
    """
    price = float(df["close"].iloc[-1])
    if not swings:
        return None, None, "equilibrium", None
    recent = [s for s in swings if s.confirmed_idx <= len(df) - 1]
    if len(recent) < 2:
        return None, None, "equilibrium", None
    recent = sorted(recent, key=lambda s: s.idx)
    last = recent[-1]
    prior_opp = next((s for s in reversed(recent[:-1]) if s.kind != last.kind), None)
    if prior_opp is None:
        return None, None, "equilibrium", None
    range_low = last.price if last.kind == "low" else prior_opp.price
    range_high = last.price if last.kind == "high" else prior_opp.price
    if range_high <= range_low:
        return range_low, range_high, "equilibrium", None
    pct = (price - range_low) / (range_high - range_low)
    zone = "discount" if pct < 0.45 else "premium" if pct > 0.55 else "equilibrium"
    return float(range_low), float(range_high), zone, float(np.clip(pct, 0, 1))


# ───────────────────────────── Tổng hợp ─────────────────────────────
def analyze(df: pd.DataFrame, left: int = 3, right: int = 3, min_swing_atr: float = 0.4,
           liq_tol_atr: float = 0.25) -> SMCAnalysis:
    """df phải có cột open/high/low/close/volume, đã sắp theo thời gian tăng dần, ĐÃ CẮT tới as_of
    (không có nến tương lai/chưa đóng)."""
    swings = detect_swings(df, left, right, min_swing_atr)
    events = classify_structure(df, swings)
    obs = find_order_blocks(df, events)
    fvgs = find_fvgs(df)
    liq = find_liquidity_pools(df, swings, liq_tol_atr)
    last_event = events[-1] if events else None
    trend = last_event.trend_after if last_event else "ranging"
    r_low, r_high, zone, zone_pct = premium_discount(df, trend, last_event, swings)
    return SMCAnalysis(swings=swings, events=events, order_blocks=obs, fvgs=fvgs, liquidity=liq,
                       trend=trend, last_event=last_event, range_low=r_low, range_high=r_high,
                       zone=zone, zone_pct=zone_pct)
