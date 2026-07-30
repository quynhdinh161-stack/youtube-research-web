# Hướng dẫn cập nhật bản Dashboard 2 trong 1 — Auto Discovery

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
Add automatic market discovery from tracked channels
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
2. Mở **Tổng quan** và bấm **Tự khám phá thị trường**.
3. Chờ tool tự chọn 5 cụm từ và quét toàn YouTube.
4. Mở **Toàn thị trường** để xem bảng tóm tắt và kết quả đã lưu.
5. Mở **Từ khóa đã lưu** để kiểm tra các dòng có chu kỳ `auto-discovery`.
6. Thử nút **Theo dõi kênh** trên một kết quả.
7. Sang **Kênh theo dõi**, chọn kênh vừa thêm và bấm quét để lấy dữ liệu đầy đủ.
8. Quét lại sau một khoảng thời gian để trang **Từ khóa tăng trong tuần** có dữ liệu so sánh.

Nên thử với một từ khóa và 0–5 kênh phân tích sâu trước, chưa quét đồng loạt 20 từ khóa ngay lần đầu.

## Lưu ý quota

Cấu hình mặc định Tự khám phá quét tối đa 5 từ khóa và 12 kết quả/từ khóa, không phân tích sâu. Nếu không có cache, mức tối đa ước tính khoảng 510 quota units. Quét lại trong 30 phút sẽ ưu tiên dùng dữ liệu Supabase và không gọi lại API.

Bản này không cần chạy SQL migration mới nếu ba bảng `market_keywords`, `market_scans`, `market_results` đã tồn tại.
