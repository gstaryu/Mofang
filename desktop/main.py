# -*- coding: utf-8 -*-
"""墨仿 Mofang — 桌面版（pywebview 薄壳）。

桌面版 = 原生窗口内嵌网页版前端：进程内启动 FastAPI，窗口指向它。
UI 与功能与网页版 100% 一致（同一套前端），数据目录共用 core/paths 逻辑。
启动: python desktop/main.py   （或双击 桌面版.bat / dist 下的 Mofang.exe）
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _install_excepthook(data_dir: str) -> None:
    """未捕获异常写日志，便于打包版排错。"""

    def hook(etype, value, tb):
        import traceback
        log = os.path.join(data_dir, "mofang-error.log")
        with open(log, "a", encoding="utf-8") as f:
            traceback.print_exception(etype, value, tb, file=f)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, f"{etype.__name__}: {value}\n\n日志已写入:\n{log}",
                "墨仿出现错误", 0x10)
        except Exception:
            pass
        sys.__excepthook__(etype, value, tb)

    sys.excepthook = hook


def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _icon_path() -> str:
    """图标文件：源码 = desktop/icon.ico；打包 = 包内根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", "."), "icon.ico")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")


def _set_window_icon_async(title: str, icon_path: str) -> None:
    """窗口创建后用 WM_SETICON 换掉默认的 Python 图标（含任务栏）。"""
    def work():
        import ctypes
        import time
        try:
            user32 = ctypes.windll.user32
            hwnd = None
            for _ in range(150):                 # 最多等 30s 窗口出现
                hwnd = user32.FindWindowW(None, title)
                if hwnd:
                    break
                time.sleep(0.2)
            if not hwnd:
                return
            big = user32.LoadImageW(None, icon_path, 1, 32, 32, 0x00000010)
            small = user32.LoadImageW(None, icon_path, 1, 16, 16, 0x00000010)
            user32.SendMessageW(hwnd, 0x0080, 1, big)     # WM_SETICON ICON_BIG
            user32.SendMessageW(hwnd, 0x0080, 0, small)   # WM_SETICON ICON_SMALL
        except Exception:
            pass
    import threading
    threading.Thread(target=work, daemon=True).start()


def main() -> None:
    from core.paths import get_data_dir, ensure_data_dirs
    data_dir = ensure_data_dirs(get_data_dir())
    os.environ["MOFANG_DATA"] = data_dir          # server.app 读取
    _install_excepthook(data_dir)

    # --windowed 打包下 sys.stdout/stderr 为 None，uvicorn 日志初始化会崩；
    # 重定向到日志文件（同时留档启动输出）。
    if sys.stdout is None or sys.stderr is None:
        log_io = open(os.path.join(data_dir, "mofang-run.log"), "a",
                      buffering=1, encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = log_io
        if sys.stderr is None:
            sys.stderr = log_io

    port = _free_port()
    import uvicorn
    from server.app import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading = __import__("threading")
    threading.Thread(target=server.run, daemon=True).start()

    import time
    for _ in range(50):                            # 等服务就绪再开窗口
        try:
            import socket
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)

    import webview
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("gstaryu.Mofang")
    except Exception:
        pass
    _set_window_icon_async("墨仿 Mofang — 手写模拟打印工具（仅供学习交流）", _icon_path())

    class ExportBridge:
        """暴露给前端的“另存为”对话框（桌面版导出走选定路径）。"""

        def pick_save_path(self, default_name: str = "mofang.pdf",
                           file_types: str = "") -> str | None:
            import webview as _w
            win = _w.windows[0]
            result = win.create_file_dialog(
                _w.SAVE_DIALOG, save_filename=default_name,
                file_types=(types, "所有文件 (*.*)")) if (types := file_types) else \
                win.create_file_dialog(_w.SAVE_DIALOG, save_filename=default_name)
            if isinstance(result, (list, tuple)) and result:
                return result[0]
            return result

    window = webview.create_window(
        "墨仿 Mofang — 手写模拟打印工具（仅供学习交流）",
        f"http://127.0.0.1:{port}",
        width=1280, height=860, min_size=(980, 640),
        js_api=ExportBridge(),
    )
    # 允许 blob 下载兜底（网页版流程在 WebView2 内的下载行为）
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:
        pass
    webview.start()                                # GUI 主循环（阻塞）
    # 窗口关闭后退出；daemon 线程自动结束


if __name__ == "__main__":
    main()
