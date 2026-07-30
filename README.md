# YouTube Research Web V3

Bản web miễn phí, giao diện tối, chạy trên **Streamlit Community Cloud** và lưu dữ liệu lâu dài bằng **Supabase Free**.

## Chức năng

- Chỉ dán link kênh, `@handle` hoặc Channel ID.
- Tự lấy tên kênh, subscriber, tổng view, số video, video mới nhất, tần suất đăng.
- Tự phân loại chủ đề và ngách, không cần AI trả phí.
- Trang **Dành cho bạn** hiển thị video outlier theo hiệu suất của chính kênh.
- Trang **Từ khóa** tìm video theo thị trường và khoảng thời gian.
- Thư viện **Video**, **Shorts/video ngắn**, và bảng **Kênh**.
- Lưu snapshot để tính tăng trưởng 7 ngày/30 ngày.
- Xuất Excel.

## Triển khai miễn phí

### Bước 1 — Tạo Supabase

1. Tạo một project Supabase Free.
2. Vào **SQL Editor**, dán toàn bộ nội dung `supabase_schema.sql`, rồi Run.
3. Vào **Project Settings → API** và lấy:
   - Project URL
   - `service_role` key

Không đưa `service_role` key vào GitHub.

### Bước 2 — Đưa mã nguồn lên GitHub

1. Tạo repository mới.
2. Upload toàn bộ thư mục này.
3. Không upload file `.streamlit/secrets.toml`.

### Bước 3 — Deploy Streamlit Community Cloud

1. Đăng nhập Streamlit Community Cloud và kết nối GitHub.
2. Chọn repository, branch `main`, file chạy `app.py`.
3. Trong **Advanced settings → Secrets**, nhập:

```toml
YOUTUBE_API_KEY = "API_KEY_CUA_BAN"
SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_KEY = "SERVICE_ROLE_KEY_CUA_BAN"
```

4. Bấm Deploy. App nhận một địa chỉ dạng `ten-app.streamlit.app`.

## Bảo mật

- YouTube API key và Supabase service role key phải lưu trong Streamlit Secrets.
- Không commit key lên GitHub.
- Nếu chia sẻ app công khai, ai có link cũng có thể dùng chức năng thêm/cập nhật kênh. Nên đặt app ở chế độ private hoặc chỉ chia sẻ trong team.

## Lưu ý quota

Nghiên cứu từ khóa dùng endpoint tìm kiếm nên tốn quota nhiều hơn cập nhật kênh. Không nên bấm tìm kiếm liên tục hoặc quét quá nhiều kênh trong một lần.
