"""
Dark mode — CSS override runtime (không cần đổi .streamlit/config.toml, không cần restart app).

CÁCH HOẠT ĐỘNG: Streamlit dựng UI bằng các biến CSS chuẩn (--background-color, --text-color…) trên thẻ gốc.
Ta chèn 1 khối <style> ghi đè các biến này (và vài selector cụ thể) khi người dùng bật dark mode trong sidebar.

GIỚI HẠN THÀNH THẬT: bảng dữ liệu tương tác (st.dataframe — thư viện glide-data-grid) tự vẽ theo canvas và
KHÔNG đọc các biến CSS này, nên khi bật dark mode, khung bảng sẽ tối nhưng phần lưới dữ liệu bên trong vẫn theo
theme mặc định của trình duyệt. Nếu muốn bảng cũng tối 100%, cách chắc chắn là đặt `[theme] base = "dark"` trong
`.streamlit/config.toml` (tĩnh, cần khởi động lại app) — đã có sẵn tuỳ chọn `DARK_CONFIG_SNIPPET` bên dưới.
"""

DARK_CSS = """
<style>
:root, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    --background-color: #0e1117; --secondary-background-color: #161b22;
    --text-color: #e6edf3; --primary-color: #58a6ff;
    background-color: var(--background-color) !important; color: var(--text-color) !important;
}
[data-testid="stSidebar"] { background-color: #10151c !important; }
[data-testid="stMetric"], [data-testid="stExpander"], .stTabs [data-baseweb="tab-panel"] {
    background-color: #161b22 !important; border-radius: 8px;
}
[data-testid="stMetricValue"], [data-testid="stMetricLabel"], p, span, label, h1, h2, h3, h4, .stMarkdown {
    color: #e6edf3 !important;
}
.stButton>button, .stDownloadButton>button { background-color: #21262d !important; color: #e6edf3 !important;
    border: 1px solid #30363d !important; }
[data-testid="stDataFrame"] { filter: invert(0.92) hue-rotate(180deg); }   /* mẹo tối màu khung glide-data-grid */
[data-testid="stDataFrame"] img, [data-testid="stDataFrame"] svg { filter: invert(1) hue-rotate(180deg); }
hr { border-color: #30363d !important; }
</style>
"""

# Dán nội dung này vào .streamlit/config.toml nếu muốn dark mode "chuẩn" ngay từ lúc khởi động
# (bảng dữ liệu sẽ tối đúng theo theme thay vì dùng mẹo filter ở trên).
DARK_CONFIG_SNIPPET = """
[theme]
base = "dark"
backgroundColor = "#0e1117"
secondaryBackgroundColor = "#161b22"
textColor = "#e6edf3"
primaryColor = "#58a6ff"
"""


def apply(dark: bool) -> None:
    import streamlit as st
    if dark:
        st.markdown(DARK_CSS, unsafe_allow_html=True)


def plotly_template(dark: bool) -> str:
    return "plotly_dark" if dark else "plotly_white"
