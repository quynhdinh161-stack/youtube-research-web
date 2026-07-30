# Hướng dẫn cập nhật bản Dashboard 2 trong 1

## Bước 1 — Chạy SQL migration trước

1. Mở Supabase của dự án.
2. Chọn **SQL Editor** → **New query**.
3. Mở file `supabase_market_migration.sql` trong ZIP.
4. Sao chép toàn bộ nội dung vào SQL Editor.
5. Bấm **Run**.
6. Kiểm tra Table Editor có ba bảng:
   - `market_keywords`
   - `market_scans`
   - `market_results`

Migration không xóa hoặc sửa dữ liệu trong `channels`, `videos`, `snapshots`.

## Bước 2 — Cập nhật GitHub

1. Tải ZIP và giải nén.
2. Sao lưu repository hiện tại trước khi thay.
3. Thay source cũ bằng toàn bộ nội dung của thư mục giải nén.
4. Đảm bảo cấu trúc đúng:

```text
youtube-research-web/
├── app.py
├── requirements.txt
├── tracker/
├── .streamlit/
└── supabase_market_migration.sql
```

Không để `app.py` nằm trong một thư mục lồng mới.

5. Commit với nội dung gợi ý:

```text
Add combined tracked-channel and market research tools
```

## Bước 3 — Reboot Streamlit

1. Mở Streamlit Community Cloud.
2. Chọn app đang chạy.
3. Bấm **Reboot app**.
4. Chờ app chạy lại.
5. Trên trình duyệt nhấn **Ctrl + Shift + R**.

Không cần đổi Secrets.

## Bước 4 — Kiểm tra

1. Vào **Cài đặt** → bấm **Kiểm tra bảng thị trường**.
2. Vào **Từ khóa đã lưu** → thêm một từ khóa thử.
3. Bấm **Quét ngay**.
4. Mở **Toàn thị trường** để xem video đã lưu.
5. Thử nút **Theo dõi kênh** trên một kết quả.
6. Sang **Kênh theo dõi**, chọn kênh vừa thêm và bấm quét để lấy dữ liệu đầy đủ.
7. Quét lại cùng từ khóa sau một khoảng thời gian để trang **Từ khóa tăng trong tuần** có dữ liệu so sánh.

Nên thử với một từ khóa và 0–5 kênh phân tích sâu trước, chưa quét đồng loạt 20 từ khóa ngay lần đầu.
