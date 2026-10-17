"""Local API plus an isolated Edge/Chrome App window; no CLR/pythonnet dependency."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from app.main import app, default_data_dir

HOST = '127.0.0.1'
PORT = int(os.getenv('MUSE_PORT', '8765'))
URL = f'http://{HOST}:{PORT}'


def await_server(seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=.3):
                return True
        except OSError:
            time.sleep(.15)
    return False


def browser_executable():
    """Find an installed desktop browser without importing WebView2/.NET bindings."""
    override = os.environ.get('MUSE_BROWSER_EXECUTABLE')
    if override:
        p = Path(override)
        if p.is_file():
            return str(p)
        raise FileNotFoundError('MUSE_BROWSER_EXECUTABLE không tồn tại: ' + override)
    for exe in ('msedge.exe', 'chrome.exe'):
        found = shutil.which(exe)
        if found:
            return found
    roots = [os.environ.get('PROGRAMFILES(X86)'), os.environ.get('PROGRAMFILES'),
             os.environ.get('LOCALAPPDATA')]
    for root in filter(None, roots):
        for relative in ('Microsoft/Edge/Application/msedge.exe',
                         'Google/Chrome/Application/chrome.exe'):
            candidate = Path(root) / relative
            if candidate.is_file():
                return str(candidate)
    return None


def run_ui_smoke(browser, url, data_dir):
    """Headless Chromium UI smoke: actually renders the local frontend into a PNG."""
    if not browser:
        raise RuntimeError('Không tìm thấy Edge/Chrome để kiểm thử giao diện')
    screenshot = Path(os.environ.get('MUSE_UI_SMOKE_PATH') or (data_dir / 'ui-smoke.png'))
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    if screenshot.exists():
        screenshot.unlink()
    profile = data_dir / 'ui-smoke-profile'
    cmd = [browser, '--headless=new', '--disable-gpu', '--hide-scrollbars',
           '--no-first-run', '--no-default-browser-check', '--disable-extensions',
           '--user-data-dir=' + str(profile), '--window-size=1280,800',
           '--virtual-time-budget=2500', '--screenshot=' + str(screenshot), url]
    result = subprocess.run(cmd, capture_output=True, timeout=45, check=False)
    if result.returncode or not screenshot.is_file() or screenshot.stat().st_size < 1000:
        details = result.stderr.decode('utf-8', errors='replace')[-1000:]
        raise RuntimeError('Không render được giao diện Chromium: ' + details)
    with screenshot.open('rb') as stream:
        if stream.read(8) != b'\x89PNG\r\n\x1a\n':
            raise RuntimeError('Screenshot kiểm thử không hợp lệ')
    return screenshot


def open_app_window(browser, url, data_dir):
    """--app creates a borderless browser window, not an ordinary web-browser tab."""
    if browser:
        profile = data_dir / 'browser-profile'
        profile.mkdir(parents=True, exist_ok=True)
        command = [browser, '--app=' + url, '--user-data-dir=' + str(profile),
                   '--no-first-run', '--no-default-browser-check', '--new-window',
                   '--window-size=1300,820']
        proc = subprocess.Popen(command)
        # Dedicated profile avoids reusing the user's ordinary Edge session.
        # Closing the app window normally closes this browser process.
        proc.wait()
    else:
        # A browser-less system can still access the local UI in its default browser.
        if not webbrowser.open(url):
            raise RuntimeError('Không thể tìm thấy trình duyệt để mở Muse')
        print('Muse đang hoạt động tại ' + url + '. Đóng tiến trình để thoát.')
        while True:
            time.sleep(1)


def main():
    if '--server-only' in sys.argv:
        uvicorn.run(app, host=HOST, port=PORT, log_level='warning', log_config=None)
        return
    if sys.platform == 'win32':
        server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT,
                                               log_level='warning', log_config=None))
        worker = threading.Thread(target=server.run, name='muse-backend', daemon=True)
        worker.start()
        if not await_server():
            server.should_exit = True
            raise RuntimeError('Không thể khởi động backend tại cổng ' + str(PORT))
        try:
            browser = browser_executable()
            if '--ui-smoke' in sys.argv:
                run_ui_smoke(browser, URL, default_data_dir())
            else:
                open_app_window(browser, URL, default_data_dir())
        finally:
            server.should_exit = True
            worker.join(timeout=8)
    else:
        threading.Thread(target=lambda: (await_server() and webbrowser.open(URL)),
                         daemon=True).start()
        uvicorn.run(app, host=HOST, port=PORT, log_level='warning', log_config=None)


if __name__ == '__main__':
    main()
