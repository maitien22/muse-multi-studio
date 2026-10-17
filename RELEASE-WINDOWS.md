# Phát hành Muse Multi Studio v0.2.1 trên Windows

## Trạng thái hiện tại

- Mã nguồn v0.2.1: đã kiểm thử tự động Linux (`27 passed`).
- Migration SQLite v0.1.0 thực tế: đã kiểm chứng không mất key, remote ID và thư viện.
- Runtime HTTP: `/api/health` đã khởi động, trả version 0.2.1.
- EXE Windows **chưa được tạo/kiểm thử trong môi trường Linux của cuộc trò chuyện**.
- Để có EXE **thật**, chạy Windows build hoặc GitHub Actions theo hướng dẫn dưới đây.

## Cách 1 — GitHub Actions, không cần CMD

1. Tạo repo **Private** tên `muse-multi-studio` trên `https://github.com/new`. Để trống (không thêm README, .gitignore hay license).
2. Giải nén ZIP mã nguồn vào máy Windows, mở thư mục `Muse-MultiStudio`.
3. Nhấp đúp `publish_to_github.bat`, dán URL dạng `https://github.com/maitien22/muse-multi-studio.git` vào cửa sổ và Enter. Cần cài Git for Windows, đăng nhập GitHub khi được hỏi. **Không dán API key AI vào đây**.
4. Mở repository → **Actions** → **Test and build Muse Multi Studio Windows** → xem run thành công (màu xanh).
5. Chọn **Artifacts** → `MuseMultiStudio-Windows-v0.2.1` → tải ZIP được build trên Windows.
6. Giải nén toàn bộ `MuseMultiStudio-Windows-v0.2.1.zip`. Chạy file `MuseMultiStudio/MuseMultiStudio.exe` **trong thư mục đầy đủ**; không tách riêng file EXE.
7. Nếu repository dùng tagged version `v0.2.1`, workflow có thể xuất beta release kèm ZIP sau khi test thành công.

## Cách 2 — Build trên máy Windows trực tiếp

1. Cài Python 3.12 và Git, sử dụng Windows 10/11.
2. Trong thư mục dự án, nhấp đúp `build_windows.bat`.
3. Builder tự cài thư viện và PyInstaller, tạo EXE tại `dist/MuseMultiStudio/MuseMultiStudio.exe`.
4. Builder chạy Windows backend smoke test (gọi `/api/health`) và xuất `dist/MuseMultiStudio-Windows-v0.2.1.zip` nếu thành công.

## An toàn dữ liệu khi nâng cấp

- Đóng Muse cũ trước khi chạy bản mới.
- Sao lưu toàn bộ `%LOCALAPPDATA%\MuseMultiStudio`, gồm `muse.db`, `credential.key`, `output`, `references`.
- Không đưa thư mục này lên GitHub, không chia sẻ `credential.key` hay API key AI.
- Migration tự động cập nhật schema khi app v0.2.1 mở lần đầu; nên sao lưu trước để có thể phục hồi.

## Giới hạn xác minh

- Bài kiểm thử Windows EXE smoke chỉ xác nhận file PE khởi động và backend trả trạng thái; cần kiểm tra **WebView2/Giao diện desktop thực tế** trên máy Windows người dùng.
- Cần API key và hạn mức hợp lệ để thử tạo ảnh/video thực qua fal.ai/OpenAI; kiểm thử nội bộ không tiêu tiền hay gọi API thật.
- 8 worker là số tác vụ đồng thời nội bộ, không đảm bảo dịch vụ cho phép chạy 8 request có trả phí song song.
