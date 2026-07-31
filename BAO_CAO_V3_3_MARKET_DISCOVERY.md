# V3.3 — Market-native keyword discovery

## Mục tiêu
Sửa logic "Tự khám phá thị trường" để có một chế độ thực sự không phụ thuộc vào:
- từ khóa đã lưu;
- từ khóa người dùng nhập;
- 185 kênh đang theo dõi.

## Cách hoạt động mới
1. Người dùng chọn quốc gia, ngôn ngữ và nhóm nội dung.
2. Tool gọi YouTube Data API `videos.list` với `chart=mostPopular` theo từng quốc gia / category.
3. Tool tách cụm 2–4 từ từ tiêu đề của mẫu video phổ biến hiện tại.
4. Tool xếp hạng theo số video, số kênh, độ phủ quốc gia/category, độ mới và view/ngày.
5. Kết quả chỉ là danh sách ứng viên thị trường; không tự ghi vào danh sách từ khóa đã lưu.
6. Người dùng có thể chọn từ khóa rồi bấm lưu hoặc đưa sang nghiên cứu sâu.

## Lưu ý dữ liệu
YouTube Data API không cung cấp search volume chính xác. "Điểm thị trường" là tín hiệu suy ra từ mẫu video `mostPopular`, không phải lượng tìm kiếm chính thức.

## Quota
Bước phát hiện từ khóa dùng `videos.list`, khoảng 1 quota unit cho mỗi tổ hợp quốc gia/category, thay vì `search.list` 100 units/request.

## Kiểm tra
- `python -m compileall` toàn bộ source: OK.
- Test hàm discovery bằng Fake API: OK.
- Không thay đổi schema Supabase.
- Không chứa API key thật.
