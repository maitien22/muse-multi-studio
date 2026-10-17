# Hướng dẫn bảo trì dự án cho Codex / GitHub

Đây là repository **Muse Multi Studio**, ứng dụng Windows độc lập tạo ảnh/video AI đa luồng. Không nhập chung repository, dữ liệu hay migration của các dự án Cốc Cốc/TienFlow khác.

## Bất biến bắt buộc

1. **Không mô phỏng runtime**. Chỉ coi task `done` khi provider trả về tệp thật và tệp đã được lưu đầy đủ trên đĩa. Trong tests được dùng mock transport/stub có ghi rõ, nhưng tuyệt đối không thêm fallback giả vào runtime production.
2. Hàng đợi phải lưu qua SQLite, đa luồng không được lấy trùng job. Resume job fal.ai bằng `remote_id` khi có. Không xóa output cũ khi nâng cấp.
3. Luôn đi đủ đường **UI → API → Validation → SQLite → Worker → Provider → Download → Gallery → Test** khi thêm/sửa chức năng.
4. API key và proxy URL có thông tin đăng nhập phải mã hóa khi lưu. Không log secret, không đưa vào GitHub/GUI đọc lại, không mở backend ra ngoài localhost.
5. Giao diện desktop Dark Pro giống ảnh trong `docs/giao-dien.png`; chỉnh sửa phải tương thích viewport 1280x760 và nhỏ hơn.
6. Chỉ công bố model/API nếu tài liệu hiện hành xác minh được; không thêm endpoint Sora đã ngừng hoặc provider không rõ quyền sử dụng.
7. Nếu chức năng chưa có nguồn provider thật, hiển thị **chưa hỗ trợ**; không tự động sinh file demo coi như output thật.
8. Bản Windows EXE chỉ công bố hoạt động sau khi workflow `windows` build và người dùng kiểm thử launcher Windows. Không gọi ZIP mã nguồn là EXE.

## Chạy CI / Smoke test

```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q
python -m compileall -q app run.py
```

Kiểm thử thật bắt buộc trong môi trường riêng của người dùng, với API key hợp lệ và có hạn mức. Không đưa key vào unit tests; kiểm thử HTTP contract bằng `httpx.MockTransport`.

## Roadmap sau bản MVP

- Kiểm thử tài khoản fal thật: text-to-image, image-to-image, image-to-video, text-to-video.
- Xác minh hỗ trợ API provider Muse được người dùng xác định; không giả định mỗi tài khoản Muse có public API.
- Quản lý giới hạn riêng tài khoản, rate limiting/backoff, tối ưu retry có idempotency.
- Kiểm thử hủy remote và đối soát chi phí, báo chi phí theo response provider (nếu có).
- Windows GitHub Actions tạo build artifact, smoke test khởi động `.exe` trong Windows VM.
- Xem xét SQLite migration, backup/restore UX, integrity check, kiểm thử 1–8 workers dưới tải.
