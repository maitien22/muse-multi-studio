# Security

- Chỉ truy cập backend trên `127.0.0.1`; không mở cổng 8765 ra internet/Cloudflare Tunnel.
- Không lưu API key trong `.env`, git, log hoặc URL. API key được Fernet-encrypt bằng file `credential.key` dưới thư mục dữ liệu. Hãy bảo vệ tài khoản Windows và sao lưu `credential.key` cùng `muse.db`.
- Fernet bảo vệ chống đọc SQLite đơn lẻ, **không** bảo vệ nếu kẻ tấn công đã chiếm cùng tài khoản hệ điều hành có quyền đọc cả `credential.key`.
- HTTPS proxy kèm username/password được lưu mã hóa; trạng thái UI không hiển thị giá trị secret.
- Request từ Origin bên ngoài localhost bị chặn; vẫn cần bảo vệ máy khỏi phần mềm độc hại local.
- Không thêm chức năng đăng nhập tài khoản bên thứ ba bằng cách vượt CAPTCHA/2FA hoặc sử dụng phiên đăng nhập không được phép.
- File tải về chỉ chấp nhận HTTPS URL từ các CDN hỗ trợ; tăng provider mới thì kiểm tra allowlist.
- Không tải/upload dữ liệu riêng tư lên dịch vụ AI nếu chưa có quyền sử dụng và đồng ý với điều khoản dịch vụ.
