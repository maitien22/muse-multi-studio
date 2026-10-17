# Muse Multi Studio — Ứng dụng tạo ảnh/video AI đa luồng (local)

<!-- Ảnh giao diện tham khảo nằm trong bản ZIP v0.2.0 được cung cấp kèm cuộc trò chuyện. -->

> **Bản mã nguồn MVP 0.2.0**, lấy cảm hứng từ ảnh chụp màn hình giao diện. Không phải mã nguồn của nhà phát triển Muse Studio; không sử dụng đăng nhập trái phép, không giả lập kết quả AI.

## Chức năng thực đã lập trình

- Giao diện Dark Pro: Studio, prompt hàng loạt, bộ lọc Chờ/Đang chạy/Xong/Lỗi, các nút Chạy/Tạm dừng/Hủy/Retry/Xóa, tìm kiếm.
- Đa luồng **thực**: `ThreadPoolExecutor` 1–8 worker; queue SQLite có khóa giao dịch, không nhân bản job khi nhiều worker cùng nhận việc.
- Kết nối **API thực** tới fal.ai (Flux.1 Dev tạo ảnh, Flux image-to-image, Kling 2.6 Pro text-to-video/image-to-video) và OpenAI GPT Image (tạo/chỉnh ảnh).
- Quản lý nhiều dự án (tạo/đổi tên/xóa khi trống), đánh lại thứ tự tác vụ trong SQLite.
- Hỗ trợ ảnh tham chiếu: chọn nhiều ảnh, ghép từng prompt, dùng chung hoặc ghép theo tên ảnh trong prompt.
- Nhiều tài khoản API, mỗi tài khoản một proxy HTTP/HTTPS; API key được mã hóa trên đĩa bằng Fernet, không được xuất qua API đọc.
- Tải, kiểm tra định dạng và lưu kết quả ảnh/video nguyên tử; gallery vẫn giữ kết quả và prompt sau khi xóa job.
- Khôi phục tác vụ với remote ID đã lưu; chỉ tạo request tính phí mới khi được phép. Tác vụ có trạng thái chưa rõ yêu cầu xác nhận thủ công trước khi resubmit.
- Đóng gói EXE bằng GitHub Actions trên `windows-latest` hoặc `build_windows.bat` trên máy Windows, kèm smoke test EXE thực.

**Không có chế độ mô phỏng ảnh/video.** Nếu chưa có API key hợp lệ, giới hạn tài khoản, lỗi model hoặc hết credits, tác vụ báo lỗi thực.

## Chạy trên Windows (ít thao tác)

1. Cài Python 3.11+ (đánh dấu **Add Python to PATH**).
2. Giải nén repository, nhấp đúp `start_windows.bat` — công cụ tự tạo `.venv` và cài dependencies.
3. Ứng dụng mở cửa sổ desktop Windows bằng WebView2 (không phải trang web bên ngoài). Nếu thiếu `pywebview`, công cụ dự phòng mở `http://127.0.0.1:8765` trong trình duyệt. Không cần internet để dùng giao diện / quản lý queue; kết nối API cần internet.
4. Chọn **Tài khoản** → thêm API key `fal` hoặc `openai` (key được lưu **trên máy**, không nhập vào GitHub).
5. Quay lại **Studio** → nhập prompt từng dòng → chọn Ảnh / Video / Ảnh→Video, tỷ lệ, tài khoản → **Tạo & chạy**.
6. Kết quả nằm tại `%LOCALAPPDATA%\MuseMultiStudio\output`, SQLite và mã khóa ở `%LOCALAPPDATA%\MuseMultiStudio`. **Không xóa thư mục này** khi nâng cấp.

Chạy thủ công (đa nền tảng):

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

## Đóng gói `.exe`

- Nhấp `build_windows.bat` trên **Windows** (cần kết nối internet tải PyInstaller, pywebview và dependencies).
- Hoặc đẩy mã nguồn lên GitHub: Actions tự kiểm thử Linux và tạo artifact `MuseMultiStudio-Windows` chạy bằng EXE trong thư mục; tải và giải nén cả artifact rồi chạy `MuseMultiStudio.exe`.
- Không được giả định EXE đã kiểm thử khi chưa chạy **trực tiếp trên Windows**. Bản zip mã nguồn này không chứa EXE build từ Windows.

## Kiến trúc

```
run.py                  mở localhost, chạy Uvicorn
app/main.py             REST API local; validate; lưu ảnh tham chiếu
app/store.py            SQLite WAL + Fernet key storage
app/engine.py           1–8 worker, trạng thái thực, retry/cancel, resume
app/providers.py        fal.ai queue + OpenAI Images + tải kết quả
app/static/*            giao diện HTML/CSS/JavaScript
.github/workflows/*     test + build Windows, smoke EXE, artifact portable ZIP
```

### Giới hạn hiện tại (không nói quá mức)

- **Đây là bản MVP, chưa phải bản thương mại hoàn thiện.** Chưa được kiểm thử tạo ảnh/video thật vì không có API key của người dùng trong phiên này. Backend đã lập trình gửi lệnh HTTP thực tới API đã công bố.
- OpenAI **chỉ tích hợp ảnh** trong phiên bản này; video dùng **fal.ai**. Sora API cũ đã thông báo ngừng 24/09/2026, không dùng nữa.
- Cổng `8765` phải trống. Dùng biến môi trường `MUSE_PORT` để đổi.
- Proxy hỗ trợ HTTP/HTTPS, chưa hỗ trợ SOCKS. Key nằm trong `credential.key` và SQLite được mã hóa: nên sao lưu cả hai file cùng lúc; mất tệp khóa sẽ không giải mã được các API key cũ. Người có quyền truy cập cùng tài khoản Windows vẫn có thể đọc dữ liệu local; khóa Fernet **không bảo vệ khỏi người kiểm soát máy**.
- Có thể giới hạn tốc độ/rate limit từ fal.ai/OpenAI; tăng số luồng **không bỏ qua** giới hạn nhà cung cấp.
- Phần trăm khi đang chạy được để **không xác định**, chỉ hiện 100% khi tải file xong. Không dùng tiến độ giả. Cancel remote của fal.ai là yêu cầu tối đa, không cam kết hoàn tiền tác vụ bị hủy.
- Nhập ảnh tham chiếu dùng data URI do fal.ai công bố hỗ trợ. Nếu model riêng từ chối ảnh hoặc hạn chế kích thước, task hiển thị lỗi nhà cung cấp; cần kiểm thử với tài khoản thật.
- Chưa hỗ trợ đăng nhập username/password trực tiếp vào tài khoản Muse của bên thứ ba, hay quản lý license tài khoản bên thứ ba.

## API

- `GET /api/health`, `GET /api/state`, `/api/projects` (CRUD, renumber)
- `POST /api/accounts`, `DELETE /api/accounts/{id}`
- `POST /api/references` (multipart image)
- `POST /api/jobs` (prompts, kind, account_id, ratio, duration, ref_names)
- `POST /api/control` `{ "command":"start" | "pause" }`
- `POST /api/jobs/{id}/cancel`, `/retry`, `DELETE /api/jobs/{id}`
- `POST /api/jobs/retry-failed?project_id=N`, `POST /api/settings`; `GET /api/jobs?limit=100&offset=0` (phân trang).

## Kiểm thử

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -q
```

Ứng dụng chỉ bind `127.0.0.1`; request khác origin localhost bị từ chối. Không công khai cổng local qua Tunnel khi chứa API key / dữ liệu cá nhân.

## Tài liệu tham khảo API

- https://fal.ai/models/fal-ai/flux/dev/api
- https://fal.ai/models/fal-ai/flux/dev/image-to-image/api
- https://fal.ai/models/fal-ai/kling-video/v2.6/pro/text-to-video/api
- https://fal.ai/models/fal-ai/kling-video/v2.6/pro/image-to-video/api
- https://developers.openai.com/api/reference/resources/images

## Đưa lên GitHub

Tạo repository riêng `muse-multi-studio` trên GitHub (nên chọn **Private**). Đẩy toàn bộ tệp mã nguồn nhưng không đẩy dữ liệu người dùng. Workflow `.github/workflows/check.yml` tự chạy khi push. Nếu dùng công cụ kết nối GitHub trong ChatGPT, gửi URL repository trống để trợ lý upload lần đầu.

## v0.2.0 — Kiểm thử và phát hành

Bản mã nguồn này được kiểm thử tự động trên Linux. Muốn có **EXE Windows thật**: tạo repo GitHub riêng, push mã nguồn; vào **Actions → Test and build Muse Multi Studio Windows → Run workflow**; sau khi job Windows xanh, tải artifact `MuseMultiStudio-Windows-v0.2.0`, giải nén ZIP và chạy `MuseMultiStudio.exe`. Trên Windows tự build bằng `build_windows.bat`.

CI dùng runner Windows để đóng gói PyInstaller, chạy chính EXE bằng `--server-only`, gọi `/api/health`, sau đó tạo ZIP. **Smoke test này không chứng nhận giao diện WebView2**, chỉ xác nhận EXE chứa backend có thể khởi động. Trước khi chạy bản mới, sao lưu toàn bộ `%LOCALAPPDATA%\MuseMultiStudio`, đặc biệt `muse.db` và `credential.key`. Không tải API key hay SQLite lên GitHub.

Xem [CHANGELOG.md](CHANGELOG.md) để biết lỗi đã sửa và phần còn cần kiểm chứng.

**Hướng dẫn phát hành EXE và upload GitHub không cần CMD:** [RELEASE-WINDOWS.md](RELEASE-WINDOWS.md), `publish_to_github.bat`.
