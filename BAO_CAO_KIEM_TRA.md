# Báo cáo kiểm tra bản bàn giao

## Đã kiểm tra thực tế

- `python -m py_compile app.py tracker/*.py`: đạt.
- `python -m compileall`: đạt.
- Import các module `tracker.service_web`, `tracker.supabase_store`, `tracker.youtube_api`: đạt.
- Kiểm tra hàm đổi duration YouTube sang giây: đạt.
- Kiểm tra tính outlier và view/ngày bằng dữ liệu mẫu: đạt.
- Kiểm tra tính tăng trưởng 7 ngày từ snapshot theo lô: đạt.
- Kiểm tra không còn `.head(12)`, `[:12]` hoặc `limit=12`: đạt.
- Kiểm tra hai `st.radio` đều có label không rỗng: đạt.
- Kiểm tra 45 widget key dạng chuỗi không bị trùng: đạt.
- Kiểm tra các truy vấn bảng lớn không dùng `select="*"`: đạt.
- Kiểm tra không có API key thật hoặc Supabase key thật trong source: không phát hiện key thật.

## Chưa thể kiểm tra trong môi trường đóng gói

- Chưa chạy được lệnh `streamlit run app.py` vì môi trường đóng gói không có package Streamlit và không truy cập được package index để cài thêm.
- Chưa kiểm tra kết nối Supabase thật vì không sử dụng Secrets của người dùng.
- Chưa kiểm tra YouTube API thật vì không sử dụng API key của người dùng.

Sau khi deploy, dùng hai nút **Kiểm tra Supabase** và **Kiểm tra YouTube API** trong trang Cài đặt để xác nhận kết nối thật.
