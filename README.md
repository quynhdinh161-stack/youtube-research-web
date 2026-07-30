# YouTube Research Web — Dashboard 2 trong 1

Một ứng dụng Streamlit dùng chung hai công cụ:

1. **Theo dõi kênh đã nhập**: quản lý khoảng 185 kênh, quét video, Shorts, tăng trưởng và video vượt trội.
2. **Nghiên cứu toàn thị trường**: tìm video/kênh mới theo từ khóa, lưu lịch sử quét vào Supabase, phát hiện từ khóa tăng và thêm kênh mới vào danh sách theo dõi.

## Tính năng chính

### Tool 1 — Kênh theo dõi

- Không tự quét khi mở app hoặc đổi trang.
- Quét kênh được chọn, kênh chưa cập nhật hoặc toàn bộ kênh.
- Quét theo batch, có progress bar và bắt lỗi từng kênh.
- Video vượt trội dùng median của 10–30 video cùng loại từ chính kênh.
- Shorts chỉ so với Shorts; video dài chỉ so với video dài.
- Chỉ hiển thị outlier khi có ít nhất 5 video baseline hợp lệ.
- Bộ lọc, phân trang và xuất Excel danh sách kênh.

### Tool 2 — Toàn thị trường

- Tìm theo từ khóa, quốc gia, ngôn ngữ, thời gian và loại video.
- Chỉ gọi YouTube API khi bấm nút.
- Cache kết quả trùng cấu hình trong Supabase 30 phút.
- Lưu từ khóa, lịch sử quét và từng video tìm được.
- Lấy subscriber và dữ liệu kênh cho kết quả thị trường.
- Tùy chọn phân tích sâu 0/5/10/20 kênh để tính median/outlier.
- Thêm kênh mới phát hiện vào danh sách theo dõi chỉ bằng một nút.
- Trang Từ khóa tăng so sánh dữ liệu thu thập 24 giờ, 3 ngày, 7 ngày hoặc 30 ngày.
- Trang Kênh mới nổi gộp cả kênh theo dõi và kênh mới từ thị trường.

YouTube Data API không cung cấp lượng tìm kiếm từ khóa chính xác. Chỉ số tăng trưởng từ khóa trong app được tính từ mẫu video đã lưu qua nhiều lần quét.

## Cấu trúc source

```text
youtube-research-web/
├── .streamlit/
│   └── config.toml
├── tracker/
│   ├── __init__.py
│   ├── classifier.py
│   ├── config.py
│   ├── market_service.py
│   ├── service_web.py
│   ├── supabase_store.py
│   ├── utils.py
│   └── youtube_api.py
├── app.py
├── requirements.txt
├── supabase_schema.sql
├── supabase_market_migration.sql
├── HUONG_DAN_CAP_NHAT.md
└── README.md
```

`app.py` phải nằm ngay thư mục gốc của repository.

## Secrets

Giữ nguyên ba secrets hiện tại trên Streamlit Community Cloud:

```toml
YOUTUBE_API_KEY = "..."
SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_KEY = "..."
```

Không commit key thật hoặc `.streamlit/secrets.toml` lên GitHub.

## Cài đặt database

Database cũ vẫn giữ nguyên. Chạy thêm đúng một lần file:

```text
supabase_market_migration.sql
```

File này tạo ba bảng mới:

- `market_keywords`
- `market_scans`
- `market_results`

## Quota ước tính

Một lần tìm thị trường dùng khoảng:

- 102 units khi không phân tích sâu.
- Khoảng 112 units khi phân tích sâu 5 kênh.
- Khoảng 122 units khi phân tích sâu 10 kênh.
- Khoảng 142 units khi phân tích sâu 20 kênh.

Con số thực tế có thể chênh nhẹ theo số lượng kênh và lỗi API. `search.list` là phần tốn quota lớn nhất.

## Giới hạn hiện tại

- Không tự chạy lịch quét bên trong Streamlit. Chu kỳ lưu trong từ khóa chỉ là cấu hình chuẩn bị cho cron/GitHub Actions ở giai đoạn sau.
- Một lần tìm lấy tối đa 50 kết quả vì giới hạn một trang `search.list` và yêu cầu tiết kiệm quota.
- Từ khóa cần ít nhất hai lần quét ở các thời điểm khác nhau mới tính được mức tăng.
- Kết quả thị trường chưa thể hiện lượng tìm kiếm thật của người dùng YouTube.
