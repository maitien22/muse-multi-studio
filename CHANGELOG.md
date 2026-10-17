# Changelog

## v0.2.1 — Windows startup hotfix

- Loại bỏ pywebview/pythonnet và phụ thuộc CLR gây lỗi `Python.Runtime.Loader.Initialize` khi mở EXE ở một số máy và đường dẫn Unicode.
- Mở Muse trong cửa sổ Microsoft Edge/Chrome App Mode không có thanh URL; dùng backend FastAPI/SQLite hiện có.
- Bổ sung kiểm thử thực tế EXE Windows `--ui-smoke`: Chromium render giao diện thành PNG; kiểm tra khởi động từ thư mục có tiếng Việt.
- Giữ nguyên dữ liệu `%LOCALAPPDATA%\MuseMultiStudio`, không đưa key lên GitHub.

## v0.2.0
- Sửa toàn vẹn ảnh/video, retry an toàn, queue đa luồng, migration và lưu cấu hình.
