# 7-Strategy Stock Scanner (Việt Nam)

Streamlit app quét cổ phiếu Việt Nam, chạy song song **7 strategy độc lập** (7 notebook `Tool_CK_*`), hiển thị tín hiệu
riêng của từng strategy, đồng thuận/bất đồng (Meta engine), Entry/SL/TP/R:R khi notebook có.

> **Nguyên tắc số 1:** logic 7 notebook được giữ **nguyên văn**. App không viết lại strategy; nó chạy chính code notebook
> (`strategies/_legacy/`, sinh tự động, có kiểm tra hash) qua một lớp adapter mỏng. Bug của notebook được **flag**,
> không sửa âm thầm (xem `docs/audit_7_notebooks.md`).

## Kiến trúc

```text
Vnstock API ──► data/store.py (RAM + parquet, 1 lần fetch/mã, as_of = phiên hoàn chỉnh gần nhất)
                     │
                     ├─ strategies/legacy_adapter.py: DataLayer lấy từ store, datetime đóng băng ở as_of
                     ▼
   S1 S2 S3 S4 S5 S6 (engine notebook nguyên văn)     S7 (Phase 13, trích theo tên)
                     ▼
        engine/consensus.py  (chỉ đọc, KHÔNG sửa signal gốc; đếm theo dòng code A/B/C/D)
                     ▼
        ui/ + app.py  (Dashboard · Scanner · Chi tiết mã · Strategy Matrix · Cảnh báo & bản vá)
```

```text
stock_scanner/
├── app.py                     # Streamlit entry
├── config/legacy_flags.py     # các bản vá bug (mặc định = hành vi gốc) + ghi chú B*/L*
├── data/                      # provider (vnstock), store (cache), demo (dữ liệu giả lập)
├── strategies/
│   ├── base.py                # StrategyResult / BaseStrategy
│   ├── strategy_01.py … 07.py # adapter + ánh xạ tín hiệu (ghi rõ notebook/section nguồn)
│   ├── legacy_adapter.py      # chạy engine notebook trên dữ liệu từ store
│   ├── registry.py            # danh sách strategy
│   └── _legacy/               # code notebook NGUYÊN VĂN (sinh tự động — đừng sửa tay)
├── engine/                    # runner.py (điều phối, cách ly lỗi), consensus.py, tables.py
├── ui/                        # sidebar, pages, charts
├── tools/                     # extract_legacy.py · verify_extraction.py · validate_vs_notebook.py
├── tests/                     # smoke_offline.py · test_app_ui.py
└── docs/audit_7_notebooks.md  # audit chi tiết 7 notebook (B1–B17, L1–L5)
```

## Cài đặt & chạy local

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Không có API key? Tick **"Dùng dữ liệu GIẢ LẬP"** ở sidebar để xem thử giao diện (dữ liệu tổng hợp, không phải thị trường thật).

## API key (Vnstock)

Không hard-code key. Thứ tự ưu tiên: ô nhập *Vnstock API Key* (password) → `st.secrets["VNSTOCK_API_KEY"]` → biến môi trường `VNSTOCK_API_KEY`.

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # rồi điền key (file đã nằm trong .gitignore)
```

> ⚠️ 6/7 notebook gốc có API key **hard-code**. Nếu các file đó từng được chia sẻ/commit, hãy **thu hồi/đổi key** trước khi deploy.
> Thư viện vnstock/vnai có thể tự lưu key vào thư mục home của máy chạy — điều này nằm ngoài app.

## S8 — Claude AI Technical Read (mới)

Ngoài 7 strategy trích từ notebook, app có thêm **S8**: một góc đọc kỹ thuật độc lập do trợ lý AI tự viết
(`strategies/strategy_08.py`), dùng chỗ trống mà bạn đã thiết kế sẵn ở mục 12 của prompt gốc ("Thiết kế để sau
này có thể thêm Strategy 8, 9…"). S8 **không trích từ notebook nào** nên không chịu ràng buộc "giữ nguyên bug".

- Phương pháp: điểm 0–100 gồm Trend (30) + Momentum (25) + Dòng tiền (20) + Cấu trúc (15) + Sức mạnh so VNINDEX (10),
  nhân theo regime VNINDEX tự tính (độc lập, không dùng lại RegimeEngine của S1–S6). Toàn bộ chỉ báo tính nhân quả
  (không nhìn tương lai). Entry = giá hiện tại; SL = mức gần hơn giữa đáy 20 phiên và entry − 1.2×ATR14; TP = 2R
  hoặc đỉnh 60 phiên (không có kiểu ép target ≥ 9% như một số notebook).
- **Family "E"** — mặc định **KHÔNG được tính vào Consensus/Bull/Families** và không được dùng để tự động chọn
  Entry/SL/TP ở Scanner, đúng tinh thần "7 trading brains độc lập". Bật **P3 · Tính S8 (AI) vào Consensus** ở
  sidebar nếu muốn xem AI như một strategy thứ 8 đầy đủ.
- Luôn hiển thị riêng ở tab **Chi tiết mã** (điểm con Trend/Momentum/Flow/Structure/RS, lý do, cảnh báo).
- **⚠️ Không phải khuyến nghị đầu tư** — chỉ để đối chiếu/tham khảo bên cạnh 7 notebook gốc.

## Dark mode

Toggle **🌙 Dark mode** ở đầu sidebar — áp dụng ngay, không cần khởi động lại app (CSS override runtime, xem
`ui/theme.py`). Biểu đồ giá đổi sang `plotly_dark`. **Giới hạn:** khung bảng dữ liệu tương tác (`st.dataframe`)
dùng canvas riêng, chỉ tối được bằng một mẹo lọc màu (filter), không hoàn hảo 100% như theme gốc. Muốn dark mode
"chuẩn" ngay từ lúc khởi động (bảng cũng tối đúng theme) — dán khối `[theme]` trong `ui/theme.py`
(biến `DARK_CONFIG_SNIPPET`) vào `.streamlit/config.toml` (cần khởi động lại app, áp dụng cho mọi người dùng).

## Cách dùng

1. Sidebar: chọn **Mode** (Swing T+ / Hold), danh sách mã, strategy, (tuỳ chọn) tham số & bản vá → **▶️ QUÉT**.
2. **Dashboard**: ngày quét, phiên dữ liệu (as-of), regime của từng strategy, tóm tắt tín hiệu & đồng thuận.
3. **Scanner**: `Ticker · Price · S1…S7 · Consensus · Score · Setup · Entry · SL · TP · R:R`. Entry/SL/TP/R:R lấy từ
   *strategy dẫn đầu* (nghiêng mua, điểm cao nhất) — cột `R:R basis` cho biết R:R tính theo T1 hay T2 (mỗi notebook một kiểu).
4. **Chi tiết mã**: biểu đồ + từng strategy (tín hiệu gốc, điểm, entry/SL/TP, lý do, điều kiện đạt/không đạt, cảnh báo, output gốc).
5. **Strategy Matrix**: ma trận S1–S7 + lọc theo tín hiệu/xung đột + phiếu theo dòng code.

Nhãn: `SB` Strong Buy · `B` Buy · `W` Watch · `N` không tín hiệu · `R` Reduce · `X` Exit · `F` bị lọc · `–` không dữ liệu · `E` lỗi.
Nhãn chuẩn hoá chỉ để hiển thị; **tín hiệu gốc của notebook luôn được giữ** (`native_signal`).

**Dòng code (family):** A = S1,S2 · B = S3,S4 · C = S5,S6 · D = S7. Các strategy cùng dòng dùng chung phần lớn code
(S5/S6 gần như cho cùng điểm/tín hiệu) nên Consensus hiển thị cả phiếu thô (`Bull`) lẫn phiếu theo dòng (`Families`).

## Cấu hình & tham số

Default lấy nguyên từ notebook (dataclass `QuantConfig` của từng strategy). Sidebar → *Tham số từng strategy* tự sinh ô
nhập cho mọi tham số số/bool; chỉ giá trị bạn đổi mới được áp dụng. Lưu ý: cùng tên tham số có thể **khác default và khác
ngữ nghĩa** giữa các notebook (ví dụ `min_avg_val_20d`, `lookback_short`, định nghĩa RS) — xem audit mục 4–5.

Hai điểm khác notebook *có chủ đích* (đều tắt/bật được ở sidebar):
- **L4** – bỏ nến hôm nay nếu chưa đóng cửa (15:00): tránh dùng nến chưa hoàn chỉnh (BẬT mặc định).
- **B5** – S3 mode Hold: notebook gốc thiếu `min_score_hold/min_rr_hold` nên crash; bổ sung giá trị của S4 (BẬT mặc định).
- **B6** – S3/S4: dùng hiệu lực thực của `TPlusQuantEngine` (`min_score_swing=6.2`, risk 1%).

Các bản vá khác (mặc định TẮT = hành vi gốc): **B1** (Regime dùng MA200 thật), **B7** (S7: STRONG_BUY theo `strong_buy_score`).

## Deploy lên Streamlit Community Cloud

1. Đẩy thư mục này lên GitHub (không commit `.streamlit/secrets.toml`, không commit notebook chứa key).
2. share.streamlit.io → *New app* → chọn repo, branch, file chính `app.py`. Chọn Python 3.11 hoặc 3.12.
3. *Advanced settings → Secrets*: dán `VNSTOCK_API_KEY = "..."`.
4. Lưu ý: filesystem của Cloud là tạm thời (cache parquet mất khi app khởi động lại) và RAM giới hạn — lần quét lạnh đầu tiên
   với ~240 mã mất vài phút (mỗi mã 1 lần tải lookback ~820 ngày + độ trễ `delay`). Có thể quét tập mã con.

## Thêm Strategy 8, 9…

1. Nếu là notebook mới kiểu `QuantEngine`: thêm mục vào `SPECS` trong `tools/extract_legacy.py` (danh sách cell production),
   chạy `python tools/extract_legacy.py --notebooks <thư_mục>` → sinh `strategies/_legacy/s08_legacy.py`.
2. Tạo `strategies/strategy_08.py`: kế thừa `LegacyEngineStrategy` (đặt `module_path`, `weights_fn/min_score_fn`, viết `map_result`),
   hoặc kế thừa `BaseStrategy` trực tiếp (xem `strategy_07.py`). Ghi rõ *Source Notebook / Section* ở docstring.
3. Thêm 1 dòng vào `strategies/registry.py`. UI, Matrix, Consensus tự nhận strategy mới (đặt `family` mới hoặc dùng lại).

## Kiểm tra / Validation

```bash
python tools/verify_extraction.py --notebooks <thư_mục_notebook>            # _legacy còn khớp nguyên văn notebook?
python tools/validate_vs_notebook.py --notebooks <thư_mục> --provider demo  # app vs chạy nguyên notebook (offline)
python tools/validate_vs_notebook.py --notebooks <thư_mục> --provider vnstock --tickers FPT VCB HPG   # cần API key
python tests/smoke_offline.py swing        # chạy 8 strategy (S1–S7 + S8) trên dữ liệu giả lập
python tests/test_app_ui.py                # chạy UI headless (swing/hold × dark mode × include-AI)
```

`validate_vs_notebook.py` exec **chính các cell trong .ipynb** (DataLayer/MarketDataStore gốc, chỉ thay tầng `vnstock.Quote`
bằng dữ liệu của store) rồi so **mọi cột output** (S1–S6: 50–62 cột/mã; S7 toàn bộ). Nếu lệch: truy nguyên nhân (dữ liệu, NaN,
làm tròn, thứ tự tính, múi giờ, bug notebook) **trước khi** sửa — không sửa để "ép giống".

## Debug / bảo trì

- Một mã hoặc một strategy lỗi → chỉ ô đó hiện `E`/`–`; xem cảnh báo trong tab của strategy (kèm traceback trong *Output gốc*).
- Strategy không khởi tạo được (ví dụ thiếu VNINDEX) → hiện ở Dashboard, cột "Lỗi khởi tạo"; các strategy khác vẫn chạy.
- Đơn vị giá: S1–S6 dùng đơn vị API; S7 quy đổi VND (KBS ×1000). Ngưỡng thanh khoản của các notebook khác nhau — cần đối chiếu
  với dữ liệu thật khi validation (audit B9).
- `strategies/_legacy/*.py` là file sinh tự động: muốn đổi logic notebook → sửa notebook rồi chạy lại `extract_legacy.py`;
  muốn vá lỗi → thêm cờ ở `config/legacy_flags.py` và xử lý trong adapter.

## Giới hạn đã biết

- Đây là công cụ hỗ trợ ra quyết định, không phải khuyến nghị đầu tư.
- Dữ liệu API thật **chưa được kiểm thử trong môi trường phát triển** (sandbox không truy cập được vnstock) — cần chạy
  `validate_vs_notebook.py --provider vnstock` và một lượt quét thật trên máy bạn trước khi tin vào kết quả.
- S7 chưa có model xác suất (`p_tp = NaN`), nên `combined_score = alpha_score` (đúng như notebook khi thiếu model).
- Chưa kiểm chứng với pandas 3.x (requirements ghim `pandas<3`).
