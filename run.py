"""Launch a native Windows window (WebView2); fall back to local browser."""
import os
import socket
import sys
import threading
import time
import webbrowser
import uvicorn
from app.main import app

HOST='127.0.0.1'
PORT=int(os.getenv('MUSE_PORT','8765'))
URL=f'http://{HOST}:{PORT}'


def await_server(seconds=15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            with socket.create_connection((HOST,PORT),timeout=.2):
                return True
        except OSError:
            time.sleep(.12)
    return False


def main():
    if '--server-only' in sys.argv:
        uvicorn.run(app,host=HOST,port=PORT,log_level='warning')
        return
    if sys.platform=='win32':
        # Run API server on a thread; native WebView2 remains on the GUI thread.
        server=uvicorn.Server(uvicorn.Config(app,host=HOST,port=PORT,log_level='warning'))
        thread=threading.Thread(target=server.run,name='muse-backend',daemon=True)
        thread.start()
        if not await_server():
            raise RuntimeError('Không thể khởi động backend, hãy kiểm tra cổng '+str(PORT))
        try:
            try:
                import webview
            except ImportError:
                webbrowser.open(URL)
                thread.join()
                return
            webview.create_window('Muse Multi Studio',URL,width=1300,height=820,min_size=(980,680),background_color='#090c17')
            webview.start()
        finally:
            server.should_exit=True
            thread.join(timeout=5)
    else:
        threading.Thread(target=lambda:(await_server() and webbrowser.open(URL)),daemon=True).start()
        uvicorn.run(app,host=HOST,port=PORT,log_level='warning')


if __name__=='__main__':
    main()
