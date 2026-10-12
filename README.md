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

## ⚠️ vnstock/vnai đang bị PyPI quarantine (từ 24/09/2026) + lưu ý an ninh

PyPI tạm ẩn 2 package `vnstock` và `vnai` để rà soát bảo mật (`pip install vnstock` báo "No matching
distribution found" dù ghim version nào). `requirements.txt` của repo này cài thay thế trực tiếp từ
nguồn ngoài PyPI (đã xác nhận chạy được trên Streamlit Cloud):

```
https://files.pythonhosted.org/packages/1f/34/7f419ef6661009006fbc149f4fca26159b7f56d9836b6cb9c170c3c0c465/vnai-2.6.1-py3-none-any.whl
git+https://github.com/thinh-vu/vnstock.git@v4.0.4
```

**Không** cài các package `vnstock-cli` / `vnstock-ta` / `vnstock-quant` / `vnstock-pipeline` /
`vnstock-installer` xuất hiện trên PyPI cùng thời điểm, và không thêm `--extra-index-url` trỏ ra ngoài
PyPI theo hướng dẫn trong mô tả của chúng — mô tả các package này chứa chỉ dẫn nhắm vào trợ lý AI để tự
ý fetch cấu hình/cài đặt từ nguồn ngoài PyPI, chưa được kiểm chứng độc lập.

**Lưu ý thêm:** khi cài/chạy, `vnai` có thể tự tạo một file `AGENTS.md` ở thư mục gốc (nội dung tự nhận
"auto-generated", trỏ người/agent đọc nó sang `vnstocks.com/onboard/agent-guide`) — đây là file DO THƯ
VIỆN tự sinh ra, KHÔNG phải do tôi hay bạn tạo. `AGENTS.md` là tên file nhiều công cụ AI (kể cả Claude)
tự động đọc làm hướng dẫn, nên đây là nơi dễ bị lợi dụng để "nói chuyện" với AI qua ngả khác ngoài ý
muốn của bạn. Repo này đã thêm `AGENTS.md` vào `.gitignore`; nếu thấy file đó xuất hiện, bạn nên xoá và
**không** làm theo nội dung bên trong (tôi cũng không fetch URL đó).

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

## S9 — AI SMC Structure Read (đa khung thời gian: Daily/Weekly/Monthly)

Bạn nhận xét: S1–S8 chủ yếu chấm điểm chỉ báo TẠI PHIÊN GẦN NHẤT, không nhìn cấu trúc đồ thị đã hình
thành ra sao. **S9** (`strategies/smc.py` + `strategies/timeframes.py` + `strategies/strategy_09.py`)
bù đắp đúng khoảng trống này — và đã qua 2 vòng chỉnh sau khi bạn phản hồi trực tiếp trên kết quả thật.

**Thiết kế top-down (đúng cách trader SMC chuyên nghiệp dùng đa khung — HTF cho BIAS, LTF cho ENTRY):**
- **BIAS** (xu hướng lớn, quyết định có xét mua hay không): ưu tiên khung **Monthly** nếu đã có sự kiện
  cấu trúc, rồi tới **Weekly**, cuối cùng mới tới Daily (cửa sổ rộng, chỉ dùng dự phòng khi chưa đủ dữ
  liệu Weekly/Monthly). Daily/Weekly/Tháng được resample NHÂN QUẢ từ chính dữ liệu ngày
  (`strategies/timeframes.py`) — đúng yêu cầu "nhìn tổng thể đồ thị rộng rộng xíu, đừng tính SMC đoạn
  nhỏ nhỏ" của bạn.
- **ENTRY** (vùng vào lệnh chính xác): Order Block/FVG trên khung **Daily với cửa sổ HẸP HƠN BIAS**
  (`entry_swing_left/right`, mặc định 3) — cố ý tách riêng khỏi cửa sổ BIAS (mặc định 6), vì nếu dùng
  chung 1 cửa sổ rộng, giai đoạn TÍCH LUỸ biên độ nhỏ (chính là nơi cần tìm entry nhất) sẽ không còn
  Order Block nào để dùng — đây là bug thật tôi tìm ra khi tự dựng kịch bản tích luỹ→breakout giống ảnh
  "Super SMC" bạn gửi.
- **Điều kiện vào lệnh** (đúng mô tả của bạn: *"mua nếu gần đáy mà có dòng tiền vào HOẶC test đáy thành
  công trong khung lớn"*):
  1. BIAS không chống lại — downtrend trên khung BIAS mà CHƯA có bằng chứng đảo chiều (CHoCH tăng hoặc
     "test đáy thành công") thì loại ngay, đúng tinh thần *"VN chỉ Long, không đánh ngược xu hướng lớn"*.
  2. **Gần đáy khung lớn** — xét theo vị trí của chính **vùng Entry (Order Block)**, không phải giá đóng
     cửa hôm nay (sửa sau khi phát hiện: cấu trúc cần vài phiên xác nhận, nên tới lúc OB "xuất hiện"
     trong kết quả thì giá thường đã nhích lên khỏi đáy — bắt giá HÔM NAY phải còn trong Discount gần như
     không bao giờ khớp cùng lúc với một OB vừa được xác nhận).
  3. **Dòng tiền vào** (CMF20 dương hoặc OBV 10 phiên dốc lên) **HOẶC** **test đáy thành công** (đáy xoay
     sau cao hơn đáy trước, hoặc CHoCH tăng, quanh đáy khung BIAS).
- **Entry/SL/TP long-only, có lưới an toàn cuối cùng:** Entry = giữa vùng OB tăng; SL = dưới đáy OB; TP =
  liquidity pool/đỉnh xoay gần nhất phía trên, hoặc theo bội số R:R cố định (`tp_rr_fallback`, mặc định
  2R) nếu giá đang phá đỉnh mới không còn kháng cự để nhắm tới. Code đảm bảo **luôn luôn**
  `SL < Entry ≤ Giá hiện tại < TP` — nếu không thỏa (lỗi thực tế đã tìm thấy: có lúc TP tính ra lại ≤ giá
  do biên an toàn trừ kháng cự quá gần) thì bỏ hẳn Entry/SL/TP thay vì hiển thị số liệu vô lý, tự hạ tín
  hiệu xuống THEO DÕI. Khi vùng Entry đã cách giá hiện tại hơn 1.5×ATR, có cảnh báo rõ "vùng CHỜ GIÁ HỒI
  VỀ, không phải mua đuổi".

**Tách riêng 2 loại khuyến nghị** (đúng yêu cầu gốc của bạn): `native_signal`/`signal` = mua mới (chưa có
vị thế); `holder_advice` = đang giữ (CẮT LỖ/HẠ TỶ TRỌNG/GIA TĂNG/TIẾP TỤC GIỮ) — tính được ngay cả khi
không nhập giá vốn, dựa trên chính cấu trúc khung lớn, và luôn NHẤT QUÁN với bên mua mới (không còn tình
trạng bên mua nói "đủ điều kiện" mà bên giữ vẫn nói "cắt lỗ ngay").

**Trực quan trên biểu đồ:** tab *Chi tiết mã* có checkbox **"🧭 Hiện cấu trúc SMC"** — vẽ chồng lên nến
(theo cửa sổ Entry/LTF): tam giác swing high/low, đường dọc BOS (xanh)/CHoCH (đỏ), vùng chữ nhật Order
Block, dải FVG chưa lấp, đường ngang Liquidity Pool, nền mờ Premium/Discount.

S9 là family "E" như S8 — mặc định **không tính vào Consensus 7-notebook** (bật P3 nếu muốn gộp chung).
Có sheet riêng trong file Excel xuất ra với đầy đủ: Khung BIAS, BIAS Trend/Zone, Daily/Weekly/Monthly
Trend, Gần đáy/Dòng tiền/Test đáy, Entry/SL/TP/R:R, khuyến nghị nắm giữ, diễn giải cấu trúc dạng câu.

⚠️ SMC là một cách diễn giải phổ biến, không phải chân lý duy nhất, và vẫn chỉ mang tính tham khảo.

## Dark mode## Dark mode

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

Default lấy nguyên từ notebook (dataclass `QuantConfig` của từng strategy / `SCAN_CFG` của S7 / `DEFAULTS` của S8).
Sidebar có 2 mục:

- **🔗 Tham số DÙNG CHUNG** (`config/shared_params.py`): tự động gom mọi tham số TRÙNG TÊN xuất hiện ở ≥ 2 strategy
  đang chọn (ví dụ `vp_bins`, `lookback_short`, `lookback_long`, `min_rr`…), gom theo nhóm (Dữ liệu & thanh khoản,
  Ichimoku & Dao Găm, Entry/Risk…). Sửa 1 ô ở đây áp dụng NGAY cho mọi strategy có tham số đó — kể cả khi default
  gốc của chúng khác nhau (sidebar hiện rõ default gốc từng strategy để biết đang ghi đè gì). Nếu sau đó bạn còn sửa
  tiếp ở mục dưới cho MỘT strategy cụ thể, giá trị riêng đó được ưu tiên hơn giá trị dùng chung.
- **Tham số riêng từng Strategy**: như trước, để chỉnh tham số chỉ 1 strategy có, hoặc ghi đè riêng lẻ.

⚠️ Lưu ý: cùng tên tham số có thể **khác ĐỊNH NGHĨA/đơn vị gốc** giữa các notebook (ví dụ `lookback_short` là NGÀY
LỊCH ở S1–S4 nhưng SỐ PHIÊN ở S5–S6 — xem audit B9–B12). Gom theo tên là lựa chọn của bạn để sửa nhanh hơn; nó
không đổi cách mỗi strategy diễn giải con số đó.

Hai điểm khác notebook *có chủ đích* (đều tắt/bật được ở sidebar):
- **L4** – bỏ nến hôm nay nếu chưa đóng cửa (15:00): tránh dùng nến chưa hoàn chỉnh (BẬT mặc định).
- **B5** – S3 mode Hold: notebook gốc thiếu `min_score_hold/min_rr_hold` nên crash; bổ sung giá trị của S4 (BẬT mặc định).
- **B6** – S3/S4: dùng hiệu lực thực của `TPlusQuantEngine` (`min_score_swing=6.2`, risk 1%).

Các bản vá khác (mặc định TẮT = hành vi gốc): **B1** (Regime dùng MA200 thật), **B7** (S7: STRONG_BUY theo `strong_buy_score`).

## Xuất Excel (mỗi strategy 1 sheet)

Sau khi quét xong, nút **📥 Xuất Excel (mỗi strategy 1 sheet)** xuất hiện ở sidebar. File gồm:

- 1 sheet **ℹ️ Tổng quan** (ngày quét, phiên dữ liệu, mode, danh sách strategy/nguồn).
- 1 sheet cho **mỗi strategy** (S1…S8, tối đa 9 sheet), mỗi dòng = 1 mã, mỗi cột = **đúng một khoá trong output
  GỐC** của strategy đó (với S1–S7: toàn bộ khoá trong dict mà notebook trả về, kể cả các khoá nội bộ bắt đầu
  bằng `_`; với S8: bộ cột tương đương do không có notebook gốc để dump — xem docstring đầu
  `engine/excel_export.py`).
- Định dạng: header xanh đậm cố định, zebra striping, freeze cột Mã + dòng tiêu đề, autofilter, số làm tròn
  2–3 chữ số. **Conditional formatting** dùng MỘT bộ luật chung cho mọi sheet (không tinh chỉnh tay theo từng
  cột của từng notebook): thang màu đỏ-vàng-xanh cho cột số, data bar cho cột khối lượng/giá trị giao dịch,
  xanh/đỏ cho cột đúng/sai (`_ok`…), và 3 luật theo icon/từ khoá (🟢✅🔥 tích cực · 🔴❌⛔ tiêu cực · 🟡👀⏳ trung
  lập) cho cột chữ.
- Mã bị lọc (`🚫 BỊ LỌC`) vẫn có đủ cột như bình thường (notebook vẫn tính xong rồi mới lọc); mã lỗi/thiếu dữ
  liệu (NO_DATA/ERROR) chỉ có vài cột (Mã, Trạng thái, Ghi chú lỗi) — các ô còn lại để trống thay vì bịa số liệu.

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
