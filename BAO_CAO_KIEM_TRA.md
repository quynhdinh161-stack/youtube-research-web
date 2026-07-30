# Báo cáo kiểm tra bản Dashboard 2 trong 1 — Auto Discovery

## Đã kiểm tra thực tế

- `python -m compileall` cho toàn bộ source: đạt.
- Import và chạy logic các module `market_service`, `service_web`, `supabase_store`, `youtube_api`: đạt.
- Test giả lập một phiên quét thị trường gồm search, dữ liệu kênh, phân tích sâu, lưu scan và kết quả: đạt.
- Test tính mức tăng từ khóa giữa hai phiên quét: đạt.
- Test tổng hợp kênh mới nổi từ kết quả thị trường: đạt.
- Test trích cụm từ tự động từ tiêu đề, xếp hạng theo video/kênh/view-ngày và loại cụm gần trùng: đạt.
- Test suy ra chủ đề, ngách, quốc gia và ngôn ngữ cho từ khóa tự phát hiện: đạt.
- Tự khám phá dùng lại ba bảng thị trường hiện có; không yêu cầu migration mới.
- Test outlier tách Shorts/video dài và yêu cầu tối thiểu 5 baseline: đạt.
- Không còn `st.radio` có label rỗng.
- Không còn giới hạn cứng `.head(12)` hoặc `[:12]`.
- Không tìm thấy widget key tĩnh bị trùng.
- Không có API key hoặc Supabase key thật trong source.

## Chưa thể kiểm tra trong môi trường đóng gói

- Không chạy được giao diện Streamlit đầy đủ vì môi trường đóng gói không có package Streamlit trong kho cài đặt.
- Không kết nối thử với Supabase và YouTube API thật vì không sử dụng Secrets của người dùng.
- SQL migration đã được kiểm tra cấu trúc tĩnh nhưng chưa chạy trên database thật của người dùng.

Vì vậy, sau deploy cần thực hiện quy trình kiểm tra nhanh trong `HUONG_DAN_CAP_NHAT.md`.

## Bản vá V3.1 – nút trong form
- Sửa nút “Quét toàn thị trường” bị khóa sau khi nhập từ khóa. Nguyên nhân: widget trong `st.form` không rerun khi người dùng gõ, nên `disabled=not bool(query)` luôn giữ trạng thái ban đầu.
- Nút quét hiện luôn khả dụng khi YouTube API đã cấu hình; nếu để trống từ khóa, app hiển thị cảnh báo sau khi bấm.
- Sửa tương tự nút “Lưu từ khóa”.
- Bổ sung CSS riêng cho `stFormSubmitButton` để nút chính hiển thị rõ trên Streamlit Community Cloud.
