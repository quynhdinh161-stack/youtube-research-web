# YouTube Research Web — Giai đoạn 1

Dashboard Streamlit nghiên cứu kênh và video YouTube, lưu dữ liệu lâu dài trên Supabase.

## Đã hoàn thành trong bản này

- Menu sidebar ổn định gồm 9 trang:
  - Tổng quan
  - Từ khóa tăng trong tuần
  - Video vượt trội
  - Toàn thị trường
  - Kênh mới nổi
  - Kênh theo dõi
  - Từ khóa đã lưu
  - Shorts
  - Cài đặt
- Không dùng `st.radio` với label rỗng.
- Không tự gọi YouTube API khi mở app hoặc đổi trang.
- Trang Tổng quan chỉ đọc dữ liệu đã lưu từ Supabase.
- Supabase được cache 5 phút bằng `st.cache_data`.
- Snapshot tăng trưởng được tải một lần theo lô, không gọi riêng từng kênh.
- Truy vấn không còn dùng `select="*"` cho các bảng lớn.
- Dữ liệu video/snapshot được đọc theo trang từ Supabase.
- Video vượt trội:
  - Không còn giới hạn cứng 12 video.
  - Ngưỡng Tất cả, ≥1.2x, ≥2x, ≥5x, ≥10x, ≥20x và Kênh nhỏ bùng nổ.
  - Bộ lọc thời gian, loại video, quốc gia, view, subscriber, chủ đề, ngách và từ khóa.
  - Sắp xếp theo hệ số vượt trội, view/ngày, lượt xem hoặc mới nhất.
  - 24 video mỗi trang, 4 video mỗi hàng.
  - Chọn tối đa 20, 50, 100 hoặc 200 kết quả.
- Outlier dùng median tối đa 20 video cũ hơn của chính kênh.
- Quét kênh chỉ chạy khi người dùng bấm nút.
- Quét theo batch 10 kênh, có progress bar và không dừng toàn bộ khi một kênh lỗi.
- Quét tất cả và xóa kênh đều yêu cầu xác nhận.
- API key chỉ đọc từ Streamlit Secrets, không có ô hiển thị key trên giao diện.
- Bổ sung `tracker/config.py` bị thiếu trong source cũ.

## Chưa hoàn thành

Hai trang sau được giữ trong menu nhưng chưa ghi dữ liệu vì schema hiện tại chưa có bảng phù hợp:

- Từ khóa tăng trong tuần.
- Từ khóa đã lưu.

Trang Toàn thị trường đã tìm thủ công và cache kết quả trong phiên, nhưng chưa lưu kết quả vào Supabase. Việc lưu market scan, từ khóa và lịch sử tăng trưởng cần SQL migration riêng ở Giai đoạn 2–3.

## Cấu trúc source

```text
youtube-research-web/
├── .streamlit/
│   └── config.toml
├── tracker/
│   ├── __init__.py
│   ├── classifier.py
│   ├── config.py
│   ├── service_web.py
│   ├── supabase_store.py
│   ├── utils.py
│   └── youtube_api.py
├── app.py
├── requirements.txt
├── supabase_schema.sql
├── HUONG_DAN_CAP_NHAT.md
└── README.md
```

`app.py` phải nằm ở thư mục gốc của repository. Không đưa toàn bộ source vào thêm một thư mục lồng nữa khi upload GitHub.

## Streamlit Secrets

Vào Streamlit Community Cloud → App settings → Secrets và cấu hình:

```toml
YOUTUBE_API_KEY = "API_KEY_CUA_BAN"
SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_KEY = "SERVICE_ROLE_KEY_CUA_BAN"
```

Không commit `.streamlit/secrets.toml` hoặc key thật lên GitHub.

## SQL

Bản Giai đoạn 1 không thêm bảng và không yêu cầu migration mới. Nếu database đã chạy `supabase_schema.sql` của bản cũ thì không cần chạy lại.

## Cập nhật app

Xem hướng dẫn chi tiết trong `HUONG_DAN_CAP_NHAT.md`.
