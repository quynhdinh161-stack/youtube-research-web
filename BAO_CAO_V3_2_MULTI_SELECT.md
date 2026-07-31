# Báo cáo V3.2 - Multi-select thị trường

Đã sửa:
- Quốc gia ở trang Toàn thị trường: selectbox -> multiselect.
- Ngôn ngữ ở trang Toàn thị trường: selectbox -> multiselect.
- Quét riêng từng tổ hợp quốc gia/ngôn ngữ rồi gộp video trùng để hiển thị.
- Hiển thị số tổ hợp và quota ước tính trước khi quét.
- Giới hạn tối đa 12 tổ hợp/lần để tránh tiêu hao quota quá nhanh.
- Tổng quota hiển thị sau quét là tổng của tất cả tổ hợp.
- Lưu từ khóa theo từng tổ hợp vào Supabase, dùng cấu trúc bảng hiện tại.
- Trang Từ khóa đã lưu cũng cho chọn nhiều quốc gia và nhiều ngôn ngữ.

Không cần chạy SQL migration mới.

Kiểm tra đã chạy:
- python -m compileall: OK.
- Không thay đổi Streamlit Secrets.
- Không nhúng API key vào source.

Lưu ý: YouTube Data API chỉ hỗ trợ một regionCode và một relevanceLanguage cho mỗi search.list. Ví dụ chọn 2 quốc gia x 3 ngôn ngữ = 6 lần tìm kiếm (trừ các lượt được cache).
