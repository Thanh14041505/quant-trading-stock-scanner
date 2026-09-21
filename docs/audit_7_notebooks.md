# AUDIT 7 NOTEBOOK — Unified 7-Strategy Stock Scanner

*Bước 1–3 của workflow: đọc, audit, đề xuất kiến trúc. **Chưa có dòng code app nào được viết.***
*Ngày audit: 20/09/2026.*

---

## 0. Phạm vi và độ sâu đã đọc (nói rõ để bạn biết mức tin cậy)

**Đã đọc toàn văn (source, không phải output):**
- S1: Config, Data Layer, Regime, Scoring, Position Sizer, Signal Builder, `QuantEngine.run_pipeline/run`.
- S3: Config, Scoring, Signal Builder (kể cả nhánh ITP + legacy).
- S4: Config, phần diff so với S3, `run_pipeline`, `TPlusQuantEngine`.
- S5: Config, Data Layer, Regime, Scoring, Signal Builder, `run_pipeline`, Fundamental Engine, phần Ichimoku dùng `chikou`.
- S7: toàn bộ Phase 13.0 → 13.9 (Daily Scanner) + data adapter.
- S2, S4, S6: diff định lượng theo từng cell so với bản tiền nhiệm (S1, S3, S5).

**Chưa đọc từng dòng (sẽ đọc khi port ở Step 4, vì port phải sao chép nguyên văn):**
`IndicatorEngine.compute_all`, ngưỡng chi tiết của `VSAEngine`, bảng pattern của `WinRateEstimator`, `MomentumEngine`, `CompositeDivergenceEngine`, `IchimokuEngine` / `IchimokuITPEngine` / `ItpTouchAnalyzer` / `HolderAdvisor`, `DaoGamDetector`, `PositionAdvisor`, `DivergenceAdvisor`, `FeatureEngine` của S5/S6.

**Loại khỏi production (không port):** cell cài đặt, `register_user`, Display/HTML, Backtester / BacktestEngine / Monte-Carlo / divergence_study (S2, S5, S6), và toàn bộ Research Phase 2–12 của S7.

**Đánh số strategy (đề xuất, theo dòng dõi rồi thời gian):**

| Mã | File notebook | Phiên bản tự nhận |
|---|---|---|
| S1 | `Tool_CK_Claude_v1` | VN Quant Engine v5.5 (Ichimoku đa khung + T+ ≥ 9%) |
| S2 | `Tool_CK_Claude_v1_1` | v5.7 (S1 + Composite RSI Divergence + Dao Găm advisor) |
| S3 | `Tool_CK_Grok_v2` | T+2.5 Swing v5.3 (VSA + Volume Profile + Ichimoku ITP) |
| S4 | `Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam` | v5.6 (S3 + RSI/Composite Divergence D1/W1/M1) |
| S5 | `Tool_CK_Grok_v2_PR016` | v8 (viết lại: FeatureEngine, Ichimoku D/W/M, Dao Găm) |
| S6 | `Tool_CK_Grok_v2_PR016_enhanced_v2` | v8+ (S5 + Hidden Divergence) |
| S7 | `Tool_CK_Claude_ChatGPT_v3_ProductionDailyScanner` | Phase 13 Daily EOD Scanner |

---

## 1. Tóm tắt điều hành — 5 điều bạn cần biết trước khi duyệt

**1) 7 notebook là 4 dòng code, không phải 7 bộ não độc lập.**
Mức giống nhau theo từng dòng (difflib, 1.00 = giống hệt):

| Class | S1↔S2 | S3↔S4 | S5↔S6 | S1↔S3 | S1↔S5 |
|---|---|---|---|---|---|
| RegimeEngine | 1.00 | 1.00 | 1.00 | 0.95 | 0.10 |
| VSAEngine | 1.00 | 1.00 | — | 0.98 | — |
| VolumeDryupDetector | 1.00 | 1.00 | — | 1.00 | — |
| PositionSizer | 1.00 | 1.00 | 1.00 | 1.00 | 0.19 |
| ScoringEngine | 1.00 | 0.95 | 1.00 | 0.64 | 0.27 |
| SignalBuilder | 1.00 | 0.90 | 0.65* | 0.41 | 0.11 |

*S5↔S6 thấp do S6 chỉ reformat + thêm hidden divergence.*

Bốn dòng: **A** = S1, S2 · **B** = S3, S4 · **C** = S5, S6 · **D** = S7.
Hệ quả cho Consensus: các class quyết định của S5 và S6 (ScoringEngine, PositionSizer, Ichimoku, Regime, Fundamental) **giống hệt nhau** nên Score/verdict/Entry/SL/TP/R:R **nhiều khả năng trùng** (chỉ khác nhãn Horizon và nhãn phân kỳ; sẽ xác nhận bằng test). Nếu đếm 7 phiếu bầu thô, dòng C bị đếm đôi. Đây không phải lỗi của bạn — nhưng Meta Engine phải hiển thị được điều này.

**2) Chỉ S7 có mục "Daily Scanner" đúng nghĩa.** Với 6 notebook còn lại, "scanner production" = đường `QuantEngine.run()` (mặc định `mode="swing"`); Backtest/Research nằm ở cell riêng phía sau. Tôi đề xuất coi `run_pipeline` là source of truth cho S1–S6, và Phase 13 cho S7.

**3) Có bug ảnh hưởng nhiều notebook cùng lúc** (mục 5), nổi bật: Market Regime của cả 6 notebook đầu **không bao giờ dùng MA200 thật** (chi tiết B1). Theo nguyên tắc của bạn, tôi **không sửa âm thầm** — cần bạn quyết định.

**4) Không thấy look-ahead thật sự trong đường production.** Có 4 điểm rủi ro cần flag (mục 5, nhóm L).

**5) API key `vnstock_…` bị hard-code ở 6/7 notebook** (chỉ S7 đã sửa và dùng biến môi trường). Nếu các file này từng được chia sẻ/commit, nên **thu hồi (rotate) key** trước khi deploy.

---

## 2. Audit từng strategy

Quy ước: **[V]** = đã xác minh trong code; **[?]** = suy ra từ diff/tên, sẽ xác nhận ở Step 4/7.

### S1 — `Tool_CK_Claude_v1` · v5.5 · Dòng A

- **Nguồn production:** `QuantEngine.run(symbols, mode)` → `run_pipeline` (Cell 1–13). Loại: Display, `_print_detail`.
- **Triết lý:** chấm điểm 0–10 nhiều indicator có trọng số, điều chỉnh theo regime VNINDEX; dòng tiền (VSA/Wyckoff) + Ichimoku đa khung phong cách Trịnh Phát; hai chế độ: **swing (T+1→T+2.5)** và **hold**; lọc cứng theo rủi ro trước, điểm sau.
- **Indicators [V]:** RSI14 (SMA, không phải Wilder), CMF, OBV, Force Index, Stoch, MACD, EMA20, ATR14 (SMA), Volume Profile (POC/VAH/VAL, 35 bins), RS vs VNINDEX (20 phiên), VSA 5 trạng thái, BB squeeze + phân kỳ RSI/MACD (`div_lookback=15`) + hidden accumulation, Ichimoku D/W/M (9/26/52; M 3/6/12), Dao Găm (Kijun D/W/M), DMI/ADX/Aroon (14/25), Volume Dry-up (Wyckoff Spring), MA9/10/50/200.
- **Filters cứng [V]:** thanh khoản (`min_avg_vol_20d=50k`, `min_avg_val_20d=10e6`); volume ratio < 0.5; RSI > 85 (> 75 nếu swing); giá dưới EMA20 > 9%; CMF < −0.20; Stoch > 75; hold: downtrend dài hạn / OBV suy yếu; VSA "PHÂN PHỐI" (swing); breakout + "CẠN CẦU" (bull trap); ngoại lệ Wyckoff Spring.
- **Scoring [V]:** 16 sub-score (0–10) × `BASE_WEIGHTS` (tổng thực tế = 117, được chuẩn hóa khi tính) ± `REGIME_WEIGHT_DELTA`, × `REGIME_SCORE_MULT` (1.0/0.95/0.85/0.70), + bonus dry-up (≤ 2).
- **Signal [V]:** `verdict` swing: ≥ 7.5 MUA MẠNH T+, ≥ 6.5 XEM XÉT T+, ≥ 5.0 THEO DÕI, ≥ 3.5 YẾU. `_ok = passed ∧ score ≥ min_score(regime) ∧ R:R ≥ min_rr(1.5)`. Nhãn cuối cho mở vị thế mới: **`new_buy_tag`** = MUA / QUAN SÁT / BỎ QUA (DMI/Aroon chỉ hạ 1 bậc hoặc nâng QUAN SÁT→MUA, không override filter cứng). Ngoài ra: nhãn horizon (T+ & Hold / Hold / T+ only / Tiềm năng / Chờ thêm), `hold_action` cho người đang giữ.
- **Entry [V]:** `smart_entry` 10 mức ưu tiên (phân kỳ dương kép → squeeze breakout → pullback Kijun D → test mép Kumo → hold: Kijun W/VAL → retest VAH → phân kỳ đơn → POC → EMA20 → BB Lower → dip ATR). **Lưu ý:** entry thường là *giá đặt chờ dưới thị trường*, không phải giá hiện tại.
- **SL/TP/R:R [V]:** SL swing = swing-low × 0.993 (≤ 2×ATR); SL hold = max(3 cách, sàn −8%). T1 = entry + 2.0×risk, T2 = entry + 3.5×risk, có thể thay bằng kháng cự Ichimoku/Kijun W; **T1 bị đẩy lên tối thiểu +9%**; phân kỳ âm → ép target ngắn. **R:R = (T2 − entry)/risk.**
- **Sizing [V]:** MIN(Fixed risk 1% NAV, điều chỉnh biến động, 1/4 Kelly dựa trên "win rate" heuristic), trần 20% NAV, làm tròn lô 100.
- **Defaults chính [V]:** `min_score_swing 5.0`, `min_score_hold 6.0`, `min_rr 1.5`, `min_rr_swing 2.0`, `min_rr_hold 3.0`, `min_tp_pct 9.0`, `min_atr_pct 1.5`, `lookback_short 50`, `lookback_long 600`, `vp_bins 35`, `delay_sec 2`, `adx_trend_min 25`. Danh sách đầy đủ sẽ nằm trong `S1Config`.
- **Output:** ~60 trường (gồm các trường nội bộ `_…`). **Cờ:** B2, B3, B4, B10, B11, B14, B15.

### S2 — `Tool_CK_Claude_v1_1` · v5.7 · Dòng A

- **Khác S1 [V, theo diff]:** thêm `CompositeDivergenceEngine` (port Pine "Composite Index Divergence", 4 loại phân kỳ; pivot xác nhận trễ `lbR=5`; `range 5–60`), `DivergenceAdvisor` (điều chỉnh `new_buy_tag`, `hold_action`, cảnh báo Dao Găm, "Theo dõi PK/DG"), sửa lỗi `df_override`. Backtester + divergence_study: loại.
- **Điểm mấu chốt:** `cd_replace_legacy_rsi_div = True` (mặc định) **ghi đè** `rsi_bull_div / rsi_bear_div` cũ bằng phân kỳ Composite → Scoring, WinRate, Entry, Levels đều nhận đầu vào khác S1. Code `ScoringEngine`/`SignalBuilder` giống hệt S1 nhưng **kết quả không giống** với mã có phân kỳ RSI. Vì vậy S2 vẫn là strategy riêng.
- **Defaults thêm:** `cd_rsi_len 14`, `cd_mom_len 9`, `cd_rsi_ma_len 3`, `cd_sma_len 3`, `cd_fast_len 13`, `cd_slow_len 33`, `cd_lbl 5`, `cd_lbr 5`, `cd_range_min 5`, `cd_range_max 60`, `cd_use_close False`, `cd_signal_window 3`, `dg_near_pct 2.0`.
- **Cờ:** như S1 + RSI hai công thức trong cùng notebook (SMA cho indicator, Wilder cho Composite — B12).

### S3 — `Tool_CK_Grok_v2` · v5.3 T+2.5 · Dòng B

- **Nguồn production:** `TPlusQuantEngine.run_tplus_scan` → `QuantEngine.run(mode="swing")`. Chuyên T+2.5 (swing 3–10 ngày).
- **Triết lý [V]:** chỉ mua T+ khi **dòng tiền VSA tích cực** và **Ichimoku ITP (Trịnh Phát) cho target ≥ 9% với cắt lỗ ≤ 5%**. Cùng lõi v5.2 với S1 (VSA, dry-up, regime, sizer) nhưng scoring/levels khác.
- **Scoring [V]:** 13 sub-score (không có sub-score Ichimoku/phân kỳ — ITP tác động qua levels và filter), tổng weight 101. `ScoringEngine` **không nhận cfg**, hằng số hard-code.
- **Filters [V]:** như S1 + thêm "VSA yếu + ITP không hỗ trợ" (VSA ∉ {NỔ VOL, RÚT CHÂN, CẠN VOL} và `itp_strength < 1.0`).
- **Levels ITP (swing) [V]:** `T1 = kháng cự ITP × 0.99` (kháng cự = Kijun/SSB phẳng D1, W1, M1 gần nhất phía trên, mặc định +20%); nếu lãi < 9% → **`T1 = entry × 1.095`**; `T2 = T1 + 2×ATR`; `SL = max(hỗ trợ ITP × 0.99, entry − 1.35×ATR)`; **R:R = (T1 − entry)/risk**. Nhãn: "🔥 SIÊU PHẨM T+" (lãi ≥ 9%, R:R ≥ 2.1, cắt lỗ ≤ 5%, VSA+, ITP ≥ 1.5), "✅ MUA T+" (lãi ≥ 9%, R:R ≥ 2.0, VSA+), còn lại "Chưa đạt chuẩn". Nhánh hold → `_legacy_levels`.
- **Signal [?]:** `verdict` + `_ok` giống cấu trúc S4 (chưa đọc `run_pipeline` của S3). **Không có** `new_buy_tag`. Có `HolderAdvisor` cho người đang giữ.
- **Defaults [V]:** `min_score_swing 6.3` (**`TPlusQuantEngine` ghi đè 6.2** và `risk_per_trade 0.008`), `min_rr_swing 2.0`, `min_avg_vol_20d 80k`, `min_avg_val_20d 5e6`, `max_position_pct 0.18`, `entry_pullback_pct 0.6`, `entry_atr_mult 0.45`, `dryup_range_ratio 0.65`, `dryup_sessions 5`, `lookback 40/750`, `vp_bins 30`, `delay 1.6`.
- **Cờ:** B5, B6, B3 (biến thể 9.5%).

### S4 — `Tool_CK_Grok_ChatGPT_v3_RSI_Divergence_DaoGam` · v5.6 · Dòng B

- **Khác S3 [V, theo diff + đọc `run_pipeline`]:** `RSIDivergenceEngine` (Composite Index D1/W1/M1, pivot xác nhận sau `lbR=5` phiên — **có chủ đích tránh look-ahead**, `max_age_bars 15`); sub-score `rsi_divergence` (weight 8; tổng weight 109); pattern win-rate mới; filter "phân kỳ âm thường + downtrend"; `divergence_advice` (nhãn khuyến nghị); `validate_quant_config` (sửa lỗi thiếu `min_*_hold` của S3); `min_score_hold 6.3`, `min_rr_hold 3.0`.
- **Signal [V]:** `_ok = passed ∧ score ≥ min_score ∧ R:R ≥ (min_rr_swing | min_rr_hold theo mode)`. Cột "Khuyến nghị" = horizon + nhãn phân kỳ.
- **Defaults thêm:** `divergence_lb_left/right 5`, `range 5–60`, `rsi_len 14`, `mom_len 9`, `rsi_ma_len 3`, `ma_len 3`, `fast 13`, `slow 33`, `max_age_bars 15`, `use_close False`.
- **Cờ:** B6 (TPlus override), B12.

### S5 — `Tool_CK_Grok_v2_PR016` · v8 · Dòng C

- **Nguồn production:** `QuantEngine.run` → `run_pipeline` (Cell 1–19). Loại: `BacktestEngine`, `run_and_validate`, Monte-Carlo, export/report.
- **Triết lý [V]:** viết lại theo hướng "Decision Maker chỉ đọc `raw`"; **Ichimoku D/W/M là trục chính** (weight 12, Kumo twist, Dao Găm MA65/129 D/W/M); **target theo kháng cự kỹ thuật thật** (không còn ATR × hằng số) nhưng vẫn ép lãi ≥ 9%. **Không có VSA, không có DMI/Aroon, không có `WinRateEstimator`, không có bonus dry-up trong score.**
- **Sizing [V]:** MIN(Fixed risk 1% NAV × điều chỉnh biến động, 1/4 Kelly, trần 20% NAV). Kelly dùng `win_est = 0.30 + 0.045 × score` (heuristic theo score) và `rr_est = max(1.5, (T1 − entry)/SL_dist)` theo target thật; **không ép tối thiểu 1 lô** — nếu không đủ 1 lô an toàn thì `shares = 0` kèm `size_note`.
- **Indicators:** `FeatureEngine` (cache EMA/SMA/ATR/RSI/MACD/Stoch), Volume Profile (35 bins), RS (ratio 0.2–4), money-flow "institutional" heuristic, long trend (có `weak_down`), BB squeeze, phân kỳ RSI/MACD (fractal, `div_lookback 5`), volume context, Ichimoku D/W/M, Dao Găm, `FundamentalEngine` (P/E, P/B, ROE, ROA, EPS quý gần nhất; **chỉ ảnh hưởng `rs_score` ở mode hold**; gọi API riêng cho mỗi mã).
- **Filters [V]:** thanh khoản; volume ratio < **0.85**; RSI > 82 (>75 swing); dưới EMA20 > 9%; CMF < −0.20; Stoch > 88; dưới mây 3 khung; hold: downtrend/OBV; phân kỳ âm kép.
- **Scoring [V]:** 13 sub-score, weight tổng = 100; `total = min(10, weighted/Σw) × regime_mult` (không có bonus dry-up).
- **Signal [V]:** `ok(swing) = passed ∧ score ≥ min_score(regime) ∧ swing_rr ≥ min_rr(1.5) ∧ T1% ≥ min_profit_pct(9)`; `verdict` **đã gộp `ok`** (không còn lệch icon/bảng như S1–S4). Horizon (T+ & Hold / Hold / T+ / Tiềm năng / Chờ). `portfolio_holder_recommend(avg_cost)`: CẮT LỖ / HẠ TỶ TRỌNG (MẠNH) / GIA TĂNG / TIẾP TỤC HOLD.
- **Entry [V]:** 7 mức (phân kỳ dương → pullback Kijun D trên mây → squeeze breakout → đáy mây → dry-up → hold: VAL/swing low/Ichimoku → BB Lower…). **SL:** swing-low × 0.993, nếu xa > 2.2×ATR thì entry − 1.8×ATR. **R:R = (T1 − entry)/risk.**
- **Defaults [V]:** `min_score_swing 5.0`, `min_score_hold 6.0`, `min_rr 1.5`, `min_profit_pct 9.0`, `min_avg_vol_20d 50k`, `min_avg_val_20d 10e5`, `lookback 60/280/800`, `vp_bins 35`, `delay 2`, `bb 20/2.0`, `squeeze_pct 15`, `squeeze_lookback 60`, `div_lookback 5`, Ichimoku 9/26/52/26, `dao_gam 65/129`, `dao_gam_atr_buffer 0.4`, `ma_test_pct_buffer 0.012`, `use_fundamental True`.
- **Cờ:** B1, B3, B4, B9, B10, B11.

### S6 — `Tool_CK_Grok_v2_PR016_enhanced_v2` · v8+ · Dòng C

- **Khác S5 [V, theo diff từng cell]:** thêm **Hidden Divergence** (RSI + MACD, 4 loại) trong `MomentumEngine`; `classify_horizon` cộng/trừ theo hidden div; `divergence_note`; cột "Phân Kỳ". **`ScoringEngine`, `PositionSizer`, `IchimokuEngine`, `RegimeEngine`, `FundamentalEngine`, `FeatureEngine` giống hệt S5.** BacktestEngine đổi (loại).
- **Hệ quả:** Score / `Tín hiệu` / Entry / SL / TP / R:R của S6 **trùng S5**; chỉ khác nhãn Horizon và nhãn momentum/phân kỳ. Cần xác nhận bằng test ở Step 7.
- **Cờ:** như S5.

### S7 — `Tool_CK_Claude_ChatGPT_v3_ProductionDailyScanner` · Phase 13 · Dòng D

- **Nguồn production [V]:** Phase 13.0–13.9 (config, data adapter, causal feature engine, regime, scoring, probability adapter, `scan_one_symbol`, `scan_watchlist`). Loại: Research Phase 2–12 (calendar tests, labeler, factor engine, setup/state/exit-risk engines, probability model, walk-forward, ablation).
- **Lưu ý quan trọng:** Phase 13 là **bản đơn giản hoá**, *không* dùng các engine của Phase 5–8 (VSA, Ichimoku, DMI/Aroon, SetupEngine, MarketStateEngine, ExitRiskEngine). Nó có `score_stock_snapshot` và `detect_market_regime` riêng, rule-based.
- **Triết lý [V]:** công cụ "decision-support", không phải hệ thống tự động; tách bạch regime / feature / setup / probability / exit-risk / thanh khoản / xếp hạng; "exit thắng buy".
- **Data [V]:** `as_of` = phiên cuối thực tế của VNINDEX (giải quyết Chủ nhật/ngày lễ); cache parquet; KBS → VCI; retry có backoff; lỗi 1 mã → dòng `ERROR`, không crash; **quy đổi giá KBS (nghìn đồng) sang VND**.
- **Features [V]:** MA20/50/200 + slope, ATR14 (SMA), RSI14 (**Wilder**), MACD, ADX-like, volume ratio, OBV, CMF20, MFI14, breakout/breakdown 20 (dùng `shift(1)` — causal), RS 60 ngày vs VNINDEX (merge theo ngày).
- **Filters [V]:** `min_history_rows 250`, `min_price 5000`, `min_avg_value_20d 5e8` (VND).
- **Scoring [V]:** `alpha = 0.25·trend + 0.20·momentum + 0.25·flow + 0.15·structure + 0.15·RS` (thang 0–100); `exit_risk` 0–100 (cộng dồn).
- **Regime [V]:** điểm 0–100 từ VNINDEX vs MA20/50/200, slope, CMF → STRONG_BULL ≥ 75 / BULL ≥ 60 / SIDEWAYS ≥ 45 / BEAR ≥ 30 / STRONG_BEAR.
- **Signal [V]:** `EXIT` (exit_risk ≥ 65) → `REDUCE` (≥ 45 và alpha < 58) → bear market: chỉ `WATCH` → `alpha ≥ 70`: BUY/STRONG_BUY → `alpha ≥ 58`: WATCH → `NO_SIGNAL`. Xếp hạng theo `combined_score`.
- **Risk [V]:** **không có Entry, không có SL/TP tuyệt đối.** Chỉ có `suggested_sl_pct = clip(1.5×ATR%, 3%, 12%)` và `suggested_tp_pct = clip(2×SL%, 6%, 25%)` ⇒ R:R ≈ 2.0 theo cấu tạo. Không có position sizing.
- **Probability [V]:** `p_tp` chỉ có khi tồn tại biến toàn cục `probability_model`/`MODEL`/`model` (đã train trong notebook); nếu không → `NaN` và `combined = alpha`. **Signal không dùng `p_tp`.**
- **Defaults [V]:** `buy_score 70`, `strong_buy_score 85`, `watch_score 58`, `min_p_tp 0.55`, `strong_p_tp 0.65`, `exit_risk_threshold 65`, `reduce_risk_threshold 45`, `rs_lookback 60`, `LOOKBACK_DAYS 420`, `top_n 10/15/15`, `require_market_confirmation True`, `allow_new_long_in_bear False`.
- **Cờ:** B7, B8, B9, và phụ thuộc thứ tự cell (`normalize_ohlcv` ở cell hotfix 124 được gọi từ cell 116–122).

---

## 3. Độ phủ trường output theo yêu cầu (mục 4 của prompt)

| Trường | S1 | S2 | S3 | S4 | S5 | S6 | S7 |
|---|---|---|---|---|---|---|---|
| signal (nhãn gốc) | verdict + `new_buy_tag` | như S1 + advisor | verdict + action | verdict + div advice | verdict | verdict | `signal` |
| score (thang) | 0–10 | 0–10 | 0–10 | 0–10 | 0–10 | 0–10 | 0–100 |
| setup | `entry_note` + horizon | như S1 | `entry_note` + ITP reason | như S3 | `entry_note` + horizon | như S5 | `setup` (enum) |
| entry | ✓ (giá đặt chờ) | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| stop_loss | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | chỉ % |
| take_profit | T1/T2 | T1/T2 | T1/T2 | T1/T2 | T1/T2 | T1/T2 | chỉ % |
| risk_reward | (T2−E)/R | (T2−E)/R | (T1−E)/R | (T1−E)/R | (T1−E)/R | (T1−E)/R | ✗ (≈2.0) |
| position sizing | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| holder advice | `hold_action` | ✓ + advisor | HolderAdvisor | ✓ | holder recommend | ✓ | `EXIT/REDUCE` toàn cục |
| reasons | `_positives`, `Lý do` | ✓ | ✓ | ✓ | ✓ | ✓ | `reasons` |
| warnings | rải rác trong note | ✓ | ✓ | ✓ | `partial_note` | ✓ | `warnings` |
| passed / failed conditions | không có list riêng; failed = `Lý do` (filter) | như S1 | như S1 | như S1 | như S1 | như S1 | không có |

Theo nguyên tắc "field nào không tồn tại thì không tạo logic thay thế": S7 sẽ hiển thị `—` cho Entry/SL/TP/R:R tuyệt đối (chỉ hiển thị % gốc). "Passed conditions" của S1–S6 tôi chỉ có thể **trình bày lại** (sub-score ≥ 6.5 = `_positives` mà notebook đã tự in), không tạo điều kiện mới.

---

## 4. Bảng so sánh defaults dễ gây nhầm lẫn

| Tham số | S1/S2 | S3/S4 | S5/S6 | S7 |
|---|---|---|---|---|
| Ngưỡng điểm swing | 5.0 (+regime) | 6.3 (TPlus: 6.2) (+regime) | 5.0 (+regime) | alpha ≥ 70 |
| R:R tối thiểu (gate `_ok`) | 1.5 (text: 2.0) | 2.0 | 1.5 | — |
| Thanh khoản (giá trị/ngày)* | 10e6 | 5e6 | 10e5 | 5e8 VND |
| Thanh khoản (volume) | 50k | 80k | 50k | — |
| Lookback ngắn/dài | 50 / 600 | 40 / 750 | 60 / 280 (+800 tuần) | 420 ngày lịch |
| `vp_bins` | 35 | 30 | 35 | — |
| `delay_sec` | 2 | 1.6 | 2 | 0.8 |
| Trần vị thế / NAV | 20% | 18% | 20% | — |
| `entry_atr_mult` | 0.35 | 0.45 | 0.4 | — |

\*Nếu giá nguồn ở đơn vị nghìn đồng (theo ghi chú của S7 về KBS), thì các ngưỡng lần lượt ≈ 10 tỷ / 5 tỷ / 1 tỷ / 0,5 tỷ đồng. **Cần xác nhận với dữ liệu API thật ở Step 7.**

⇒ Cùng một tên tham số, khác default và đôi khi khác **ngữ nghĩa** giữa các notebook. Mỗi strategy phải có `Config` riêng.

---

## 5. Danh sách phát hiện

Mức độ: 🔴 ảnh hưởng tín hiệu trực tiếp · 🟠 ảnh hưởng độ tin cậy/so sánh · 🟡 nhỏ. Tất cả đều là **flag, không sửa**; cột cuối là cách tôi đề xuất xử lý.

### Nhóm B — Bug / bất nhất

| ID | Mức | Phát hiện (bằng chứng) | Ảnh hưởng | Đề xuất xử lý |
|---|---|---|---|---|
| B1 | 🔴 | **Regime không dùng MA200 thật** ở S1–S6: `dl.fetch("VNINDEX", days=60)` (~40 phiên) nhưng code `ma200 = rolling(200) if len ≥ 200 else ema30` ⇒ `above_ma200` thực chất là `close > EMA30`. | Sai điều kiện "bull", lệch weights, score multiplier, min_score của cả 6 strategy. | Mặc định **giữ nguyên hành vi gốc** (Ưu tiên 1). Thêm toggle `regime_true_ma200` (mặc định tắt) + badge cảnh báo trên UI. |
| B2 | 🟠 | S1/S2: `_ok` dùng `min_rr=1.5` nhưng chuỗi `Action` dùng `min_rr_swing=2.0` ⇒ một mã có thể "đủ điều kiện" mà Action ghi "⛔ R:R<2.0". | Hai cổng R:R khác nhau trong cùng notebook. | Hiển thị cả hai, không hợp nhất. |
| B3 | 🟠 | **Target bị đẩy lên tối thiểu +9%**: S1/S2 (đã cap theo kháng cự rồi vẫn `t1 < min_t1 → t1 = min_t1`), S3/S4 (`→ entry×1.095`), S5/S6 (nếu không có kháng cự ≥ 9% thì `max(kháng cự xa nhất, entry×1.09)` hoặc `entry×1.11`). | Target có thể vượt kháng cự thực; R:R đẹp hơn thực tế. | Giữ nguyên; thêm cảnh báo khi target bị nâng cưỡng bức. |
| B4 | 🟠 | **Định nghĩa R:R khác nhau**: S1/S2 = (T2−E)/risk; S3/S4, S5/S6 = (T1−E)/risk; S7 = không có. | Cột R:R không so sánh được giữa các strategy. | UI ghi rõ "R:R theo T1/T2" cạnh mỗi giá trị. |
| B5 | 🔴 | S3: `QuantConfig` **thiếu `min_score_hold` và `min_rr_hold`** nhưng code hold dùng ⇒ `AttributeError` khi `mode="hold"`. S4 đã sửa. | Mode hold của S3 không chạy được. | S3 chỉ hỗ trợ swing (đúng tên "T+2.5") và ghi rõ; không tự bịa default cho hold. |
| B6 | 🟠 | S3/S4 `TPlusQuantEngine`: gọi `super().__init__` (các sub-engine giữ `cfg` cũ) rồi **gán `self.cfg` mới** ⇒ `risk_per_trade=0.008` **không tới** `PositionSizer`; `min_score_swing=6.2` chỉ hiệu lực ở nơi đọc `self.cfg` trong `run`. | "Default" T+ thực tế khác vẻ ngoài. | **[?] cần xác nhận bằng chạy thật ở Step 7** rồi quyết định default nào là chuẩn. |
| B7 | 🔴 | S7 `classify_signal`: ngưỡng STRONG_BUY so `alpha` với `strong_p_tp×100 = 65` (< `buy_score = 70`) ⇒ **mọi mã `alpha ≥ 70` đều thành STRONG_BUY; nhãn BUY không bao giờ xuất hiện.** `strong_buy_score (85)`, `min_p_tp`, `require_market_confirmation` **không được dùng**; tham số `p_tp` bị bỏ qua. | Nhãn tín hiệu S7 kém phân biệt. | Giữ nguyên hành vi gốc + hiển thị `alpha_score` cạnh nhãn; toggle "patched" (dùng `strong_buy_score`) mặc định tắt. |
| B8 | 🟠 | S7 không có Entry/SL/TP tuyệt đối/R:R/sizing. | Không so được với S1–S6. | Hiển thị `—`; chỉ hiện % gốc. |
| B9 | 🟠 | **Đơn vị giá/thanh khoản không nhất quán**: S7 quy đổi KBS sang VND; S1–S6 giữ nguyên đơn vị API. S6 hiển thị `av2/1e9` (giả định VND) trong khi ngưỡng `10e5`. | Ngưỡng thanh khoản lệch tới 20 lần giữa các strategy nếu đơn vị không khớp. | Data layer giữ **đơn vị gốc của API** + metadata `price_unit`; adapter S7 nhân 1000 để đúng ngữ nghĩa gốc. Kiểm chứng bằng dữ liệu thật. |
| B10 | 🟠 | **RS căn theo vị trí (`iloc[-20]`) chứ không theo ngày** giữa mã và VNINDEX ở S1–S6 (S7 merge theo ngày). Định nghĩa RS cũng khác: S1 ∈ [−10, 10]; S5 ∈ [0.2, 4]. | Mã có phiên thiếu/tạm dừng → RS lệch; RS không dùng chung được. | Giữ nguyên; port riêng từng bản RS. |
| B11 | 🟠 | `lookback_short` truyền vào `fetch` như **ngày lịch** nhưng `tail(days)` cắt theo **số dòng** (S1–S4): 50 ≈ 34 phiên. S5/S6 cắt `tail(60)` phiên từ dữ liệu 800 ngày lịch. | Cùng tên tham số, cửa sổ hiệu dụng khác. | Data layer fetch **một lần** ở lookback tối đa; mỗi strategy có bộ cắt tái hiện đúng cửa sổ hiệu dụng gốc. |
| B12 | 🟠 | RSI **SMA** (Cutler) ở S1–S6, **Wilder** ở S7 và ở Composite Divergence (S2, S4). | "RSI chung" sẽ âm thầm đổi kết quả. | **Không** dùng indicator chung cho RSI; xem mục 6. |
| B13 | 🟠 | API key hard-code ở S1–S6. | Bảo mật. | Không mang vào app; dùng `st.secrets`/password input. Khuyến nghị thu hồi key cũ. |
| B14 | 🟡 | S1/S2 `PositionSizer`: `shares_lot ≤ 0 → 100` ép tối thiểu 1 lô kể cả khi vượt ngân sách rủi ro. (S5/S6 có `size_note`.) | Rủi ro thực tế > `risk_per_trade` với vốn nhỏ. | Giữ nguyên; hiển thị `risk_pct_nav` thực tế. |
| B15 | 🟡 | S1 `run_pipeline`: tính VP và fetch `df_long` hai lần, `df_override` bị bỏ qua; `sleep` hai lần/mã. S2 đã sửa. | Hiệu năng (chỉ ảnh hưởng tốc độ). | Không ảnh hưởng port. |
| B16 | 🟠 | "Win rate" của S1–S4 là **heuristic** (`wr_base 45%` + pattern weight), còn S5/S6 dùng `win_est = 0.30 + 0.045×score`; **Kelly sizing** của cả S1–S6 phụ thuộc vào các con số này. S4 tự ghi "không phải xác suất thực nghiệm". | Sizing dựa trên số không thực nghiệm. | Gắn nhãn "ước lượng heuristic" trên UI. |
| B17 | 🟡 | S7 gọi `globals().get("model")` — có thể bắt nhầm biến tên `model`. | Rủi ro khi port. | Trong app, `p_tp` chỉ tồn tại nếu có artifact model được nạp tường minh. |

### Nhóm L — Look-ahead / tính nhân quả

| ID | Kết luận | Chi tiết |
|---|---|---|
| L1 | ✅ Không leak | S5/S6 `chikou = c.shift(-d)` **được tính nhưng không dùng** (so sánh Chikou dùng `close` hiện tại vs 26 phiên trước — đúng). Là "bẫy" cho người sửa sau. |
| L2 | ✅ Không leak | Swing low/high và pivot phân kỳ chỉ dùng cửa sổ kết thúc ở phiên cuối; pivot cần `order`/`lbR` nến bên phải nên **trễ** chứ không nhìn trước (S4 chủ động ghi rõ). |
| L3 | ⚠️ Rủi ro nhẹ | Cả 6 Data Layer cũ dùng `ffill().bfill()` trên OHLC: `bfill` điền các dòng đầu bằng giá **sau đó**, và `ffill` tạo nến phẳng giả. S7 đã bỏ (test `no_synthetic_candles`). |
| L4 | ⚠️ Rủi ro vận hành | S1–S6 `end = hôm nay + 1` và không xác định "phiên cuối hợp lệ": chạy **trong giờ giao dịch** sẽ đưa **nến chưa đóng** vào chỉ báo; S7 dùng `as_of` = phiên cuối của VNINDEX. |
| L5 | ⚠️ Rủi ro khi backtest | `FundamentalEngine` (S5/S6) lấy quý báo cáo mới nhất, không căn ngày công bố → sẽ leak nếu dùng để replay lịch sử. Với scan hiện tại thì không vấn đề. Ngoài phạm vi vì loại backtest. |

---

## 6. Đề xuất kiến trúc (Step 3) — **chờ bạn duyệt**

**Điều chỉnh so với sơ đồ trong prompt (vì bằng chứng ở B9–B12):** "Common Indicators" chỉ nên chia sẻ những gì **đã chứng minh giống hệt**. Tôi đề xuất:

```text
stock_scanner/
├── app.py                      # Streamlit entry
├── config/
│   ├── defaults_s01.py … s07.py    # dataclass Config, default sao NGUYÊN VĂN từ notebook
│   └── legacy_flags.py             # toggle B1/B7…: mặc định = hành vi gốc
├── data/
│   ├── provider.py                 # vnstock Quote, KBS→VCI, retry/backoff, API key (st.secrets/password)
│   ├── store.py                    # parquet cache + st.cache_data; 1 lần fetch/mã ở lookback tối đa
│   ├── session.py                  # as_of = phiên cuối VNINDEX (bỏ nến chưa đóng), ngày lễ
│   └── views.py                    # bộ cắt/quy đổi đơn vị theo từng strategy (tái hiện cửa sổ gốc, B11/B9)
├── indicators/
│   ├── shared_verified/            # CHỈ class đã chứng minh identical (VSA, DryUp, RegimeRules, PositionSizer S1–S4) + golden test
│   └── (còn lại nằm trong từng strategy)
├── strategies/
│   ├── base.py                     # StrategyResult (dataclass), BaseStrategy
│   ├── strategy_01.py … strategy_07.py   # mỗi file: nguồn notebook/section, port nguyên văn
├── engine/
│   ├── runner.py                   # chạy 7 strategy độc lập, try/except từng mã × từng strategy
│   └── consensus.py                # Meta: agreement/conflict, family-dedup, KHÔNG sửa signal gốc
├── ui/  (dashboard, scanner, detail, matrix)
├── tests/golden/                   # đầu ra notebook gốc trên dữ liệu đóng băng → so với bản port (Step 7)
└── requirements.txt, README.md
```

**`StrategyResult` (mỗi strategy trả về):** `native_signal` (nhãn gốc, không đổi), `signal` (chuẩn hoá cho ma trận), `score` + `score_scale`, `setup`, `entry`, `stop_loss`, `take_profit` (T1, T2), `risk_reward` + `rr_basis` ("T1"/"T2"/None), `holder_advice` (trục riêng với tín hiệu mở vị thế), `reasons`, `warnings`, `passed_conditions` (trình bày lại `_positives`), `failed_conditions` (filter gốc), `legacy_notes` (B1…B17 áp dụng), `family` (A/B/C/D), `raw` (toàn bộ output gốc để đối chiếu).

**Chuẩn hoá signal (chỉ để hiển thị ma trận; `native_signal` luôn được giữ):** `STRONG_BUY / BUY / WATCH / NONE / REDUCE / EXIT / FILTERED / NO_DATA / ERROR`.
- S1–S4: BUY khi `verdict ∈ {MUA MẠNH T+, XEM XÉT T+}` **và** `_ok`; STRONG_BUY khi `MUA MẠNH T+` và `_ok`; WATCH = "THEO DÕI"; NONE = "YẾU/BỎ QUA"; FILTERED = "BỊ LỌC". (S1/S2: tôi đề xuất lấy **`new_buy_tag`** — nhãn cuối của notebook — làm tín hiệu chính, vì nó đã gộp `ok`.)
- S5/S6: đọc trực tiếp từ `verdict` (đã gộp `ok`).
- S7: STRONG_BUY/BUY/WATCH/REDUCE/EXIT/NO_SIGNAL trực tiếp.
- "HOLD" trong ví dụ của bạn là **lời khuyên cho người đang giữ** → cột riêng `holder_advice`, không lẫn với tín hiệu mua mới.

**Consensus (chỉ đọc, không ghi ngược):** (a) số phiếu thô 7/7; (b) số phiếu theo **dòng (A/B/C/D)** để không đếm đôi S5+S6; (c) danh sách strategy bất đồng + loại bất đồng (BUY vs EXIT…); (d) aggregate score chỉ là **số thống kê hiển thị**, gắn nhãn "không phải strategy".

**Hiệu năng / API:** ~240 mã × 1 fetch (lookback tối đa ~800 ngày lịch) + S5/S6 thêm 1 lần gọi Fundamental/mã (`use_fundamental=True`); `delay` gốc 0.8–2 giây/mã ⇒ lần quét lạnh đầu tiên có thể **vài phút đến hơn chục phút**. Vì vậy: parquet cache theo (mã, phiên cuối), quét theo nút bấm + thanh tiến trình, có thể chọn tập mã con; **giới hạn tốc độ thực tế của gói API key bạn dùng tôi chưa biết — cần bạn cho biết**.

**Validation (Step 7):** trích class gốc **nguyên văn** từ notebook, cho chạy trên **cùng một DataFrame đóng băng** (thay `DataLayer.fetch`), lưu JSON kỳ vọng ⇒ so từng field với bản port (indicator, score, signal, entry, SL, TP, R:R). Sai lệch phải truy nguyên nhân (mục 13 của prompt) trước khi sửa.

---

## 7. Quyết định đã được duyệt (cập nhật sau phản hồi của bạn)

| # | Nội dung | Kết luận | Cách triển khai |
|---|---|---|---|
| 1 | Numbering & dòng dõi | Duyệt | S1–S7 như mục 0; cột `family` A/B/C/D trong Meta Engine (Consensus hiển thị cả phiếu thô và phiếu theo dòng). |
| 2 | Mode | Có ô chọn Swing T+ / Hold trên UI | Radio ở sidebar; áp dụng cho S1–S6 (S7 không có mode). |
| 3 | Bug | Giao tôi quyết định | Mặc định **giữ hành vi gốc** + cảnh báo; bản vá bật/tắt trong sidebar. Riêng L4 (nến chưa đóng) và B5 (S3 Hold) mặc định BẬT. Xem `config/legacy_flags.py`. |
| 4 | Chia sẻ indicator | Duyệt | Mỗi strategy chạy engine gốc riêng; DataLayer dùng chung qua store. `indicators/shared_verified/` để dành cho phần đã chứng minh giống hệt (hiện chưa cần dùng — xem README). |
| 5 | S7 probability | Để sau | `p_tp = NaN`, `combined = alpha` (đúng hành vi notebook khi không có model). |
| 6 | B6 `TPlusQuantEngine` | Giao tôi quyết định | Dùng **hiệu lực thực của bản gốc**: `min_score_swing = 6.2`, `risk_per_trade = 1%` (0.8% không bao giờ tới PositionSizer). Người dùng vẫn chỉnh được trong sidebar. |
