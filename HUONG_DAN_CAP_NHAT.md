# Hướng dẫn cập nhật GitHub và Streamlit

## 1. Sao lưu bản hiện tại

Tải repository hiện tại từ GitHub về máy hoặc tạo một branch sao lưu trước khi thay source.

## 2. Thay source trên GitHub

Giải nén file ZIP mới. Upload **các file và thư mục bên trong** lên đúng repository `youtube-research-web`.

Cấu trúc ở cấp gốc phải có:

```text
app.py
requirements.txt
supabase_schema.sql
tracker/
.streamlit/
```

Không để thành:

```text
youtube-research-web/youtube_research_web_clean/app.py
```

Main file path của Streamlit vẫn là:

```text
app.py
```

Commit gợi ý:

```text
Stage 1: fix loading, navigation and outlier pagination
```

## 3. Không thay Secrets

Giữ nguyên các Secrets đang dùng:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `YOUTUBE_API_KEY`

Không upload key thật lên GitHub.

## 4. Reboot Streamlit

1. Mở Streamlit Community Cloud.
2. Chọn app hiện tại, không xóa app.
3. Mở phần quản lý app.
4. Bấm **Reboot app**.
5. Sau khi app chạy lại, mở trang web.
6. Nhấn `Ctrl + Shift + R` để tải lại cứng trình duyệt.

## 5. Kiểm tra nhanh sau deploy

- Menu sidebar hiển thị đủ 9 trang.
- Mở Tổng quan không xuất hiện tiến trình quét YouTube.
- Video vượt trội có bộ lọc và phân trang.
- Không còn chỉ hiện 12 video.
- Nút Quét dữ liệu mới yêu cầu xác nhận.
- Kênh theo dõi chỉ quét khi bấm nút.
- Cài đặt báo Supabase và YouTube API đã cấu hình.

## 6. SQL migration

Không có migration mới trong Giai đoạn 1. Không cần chạy lại SQL nếu các bảng `channels`, `videos`, `snapshots` đã tồn tại.
