import atexit
import codecs
import ctypes
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Optional


APP_TITLE = "Lua Obfuscator"
APP_VERSION = "1.0.15"
HERCULES_COMMIT = "ace084c897369faf584dfa3baeea159d7b205213"
LUA_RUNTIME_HASHES = {
    "lua54.dll": "a842f0d33c897ce08411ea2565e8c19859b45a2374b905de2d56434c7fa4d732",
    "lua54.exe": "8c95679e6210e5c3972ea473d248607d41b2cb734af67a60dd9eec4bf3ca237d",
    "luac54.exe": "45541cea599c9f74e0945508a1de00908534c84943c17ff06e43407635585a7a",
}
LOG_DOCUMENT_MAX_BLOCKS = 300
LOG_MESSAGE_MAX_CHARS = 12000
LOG_MESSAGE_HEAD_CHARS = 7000
LOG_MESSAGE_TAIL_CHARS = 4000
PROCESS_LOG_HEAD_CHARS = 49152
PROCESS_LOG_TAIL_CHARS = 8000
PROCESS_READ_CHUNK_BYTES = 65536
PROCESS_READ_BUDGET_BYTES = 262144
CAPTURED_LOG_HEAD_BYTES = 24576
CAPTURED_LOG_TAIL_BYTES = 8192
VALIDATION_LOG_MAX_BYTES = 32768
WORK_CLEANUP_MIN_AGE_SECONDS = 24 * 60 * 60
WORK_CLEANUP_SCAN_LIMIT = 128
WORK_CLEANUP_REMOVE_LIMIT = 8
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
APP_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = APP_DIR / ".runtime"
SETUP_LOCK_DIR = RUNTIME_DIR / "setup.lock"
VENV_ROOT = APP_DIR / ".venv"
VENV_PY = VENV_ROOT / "Scripts" / "python.exe"
VENV_PYW = VENV_ROOT / "Scripts" / "pythonw.exe"
EMBEDDED_PY = RUNTIME_DIR / "python" / "python.exe"
EMBEDDED_PYW = RUNTIME_DIR / "python" / "pythonw.exe"
APP_MUTEX_NAMES = (
    r"Global\FleeceLuaObfuscatorApp",
    r"Local\FleeceLuaObfuscatorApp",
)
APP_MUTEX_HANDLE = None
ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183


def show_native_setup_error(message: str):
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10)
    else:
        print(f"{APP_TITLE}: {message}", file=sys.stderr)


def bootstrap_local_python():
    current = os.path.normcase(os.path.realpath(sys.executable))
    for local_python, local_pythonw in (
        (VENV_PY, VENV_PYW),
        (EMBEDDED_PY, EMBEDDED_PYW),
    ):
        valid_executables = {
            os.path.normcase(os.path.realpath(path))
            for path in (local_python, local_pythonw)
            if path.is_file()
        }
        if current in valid_executables and sys.flags.isolated:
            return
        if not local_python.is_file() or not local_pythonw.is_file():
            continue
        try:
            if current not in valid_executables:
                validation = subprocess.run(
                    [str(local_python), "-I", "-c", "pass"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if validation.returncode != 0:
                    continue
            subprocess.Popen(
                [
                    str(local_pythonw),
                    "-I",
                    str(Path(__file__).resolve()),
                    *sys.argv[1:],
                ],
                cwd=str(APP_DIR),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            continue
        raise SystemExit(0)

    show_native_setup_error(
        "Setup is missing, incomplete, or no longer usable.\n\n"
        "Run Installer.bat, let it finish, then open the Lua Obfuscator shortcut."
    )
    raise SystemExit(1)


if __name__ == "__main__":
    bootstrap_local_python()


try:
    from PySide6.QtCore import (
        QEasingCurve,
        QEvent,
        QPoint,
        QProcess,
        QPropertyAnimation,
        QRect,
        Qt,
        QTimer,
        QUrl,
        Signal,
    )
    from PySide6.QtGui import (
        QCloseEvent,
        QDesktopServices,
        QDragEnterEvent,
        QDropEvent,
        QMouseEvent,
        QPainter,
        QPen,
        QTextCursor,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QSizePolicy,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except Exception:
    if __name__ == "__main__":
        show_native_setup_error(
            "Setup is incomplete and the app window cannot load.\n\n"
            "Run Installer.bat again to repair the setup."
        )
        raise SystemExit(1)
    raise


def handle_unhandled_exception(error_type, error, trace):
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        error_name = f"{error_type.__module__}.{error_type.__qualname__}"
        stack = "".join(traceback.format_tb(trace, limit=50))
        report = truncate_log_message(f"{stack}{error_name}: {error}\n")
        (RUNTIME_DIR / "error.log").write_text(
            report,
            encoding="utf-8",
        )
    except OSError:
        pass
    show_native_setup_error(
        "The app stopped because of an unexpected error.\n\n"
        "Run Installer.bat again. If it still happens, check .runtime\\error.log."
    )
    application = QApplication.instance()
    if application is not None:
        application.quit()


if os.name == "nt":
    NATIVE_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    NATIVE_KERNEL32.CreateMutexW.argtypes = (
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    NATIVE_KERNEL32.CreateMutexW.restype = wintypes.HANDLE
    NATIVE_KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
    NATIVE_KERNEL32.CloseHandle.restype = wintypes.BOOL
else:
    NATIVE_KERNEL32 = None


def release_app_mutex():
    global APP_MUTEX_HANDLE
    if APP_MUTEX_HANDLE is None or NATIVE_KERNEL32 is None:
        return
    NATIVE_KERNEL32.CloseHandle(APP_MUTEX_HANDLE)
    APP_MUTEX_HANDLE = None


def _try_create_named_mutex(name):
    if NATIVE_KERNEL32 is None:
        return "unavailable", None
    ctypes.set_last_error(0)
    handle = NATIVE_KERNEL32.CreateMutexW(None, False, name)
    error_code = ctypes.get_last_error()
    if handle and error_code == ERROR_ALREADY_EXISTS:
        NATIVE_KERNEL32.CloseHandle(handle)
        return "exists", None
    if handle:
        return "acquired", handle
    if error_code == ERROR_ACCESS_DENIED:
        return "denied", None
    return "failed", None


def acquire_app_mutex():
    global APP_MUTEX_HANDLE
    if NATIVE_KERNEL32 is None:
        return True
    for index, name in enumerate(APP_MUTEX_NAMES):
        status, handle = _try_create_named_mutex(name)
        if status == "acquired":
            APP_MUTEX_HANDLE = handle
            atexit.register(release_app_mutex)
            return True
        if status == "exists":
            return False
        if index == 0 and status == "denied":
            continue
        return False
    return False


PRESET_MAP = {
    "Low": "light",
    "Medium": "balanced",
    "High": "maximum",
}
TARGET_MAP = {
    "Lua 5.4": "lua",
    "Roblox Luau": "luau",
}
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def build_obfuscation_arguments(cli_name, source_argument, target, preset):
    return [
        "-E",
        cli_name,
        source_argument,
        "--target",
        target,
        f"--{preset}",
        "--no-watermark",
    ]


def extend_bounded_bytes(buffer, data, limit):
    available = max(0, limit - len(buffer))
    kept = data[:available]
    buffer.extend(kept)
    return len(data) - len(kept)


def is_plain_directory(path):
    try:
        details = os.lstat(path)
    except (OSError, ValueError):
        return False
    reparse_point = (
        getattr(details, "st_file_attributes", 0)
        & FILE_ATTRIBUTE_REPARSE_POINT
    )
    return stat.S_ISDIR(details.st_mode) and not reparse_point


def prepare_work_root(runtime_dir):
    runtime_dir = Path(os.path.abspath(os.fspath(runtime_dir)))
    if not is_plain_directory(runtime_dir):
        raise RuntimeError("The private runtime folder is unsafe or unavailable. Run Installer.bat again.")
    root = runtime_dir / "work"
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        pass
    if not is_plain_directory(root) or root.resolve(strict=True).parent != runtime_dir.resolve(strict=True):
        raise RuntimeError("The private work folder is unsafe. Run Installer.bat again.")
    return root


def remove_job_directory(path, work_root):
    target = Path(path)
    root = Path(work_root)
    if not is_plain_directory(root) or not is_plain_directory(root.parent):
        return False
    if target.parent != root or not target.name.startswith("job-"):
        return False
    if not is_plain_directory(target):
        return False
    try:
        shutil.rmtree(target)
        return True
    except (OSError, ValueError):
        return False


def cleanup_stale_work_directories(work_root, current_time=None):
    root = Path(work_root)
    if not is_plain_directory(root) or not is_plain_directory(root.parent):
        return 0
    now = time.time() if current_time is None else current_time
    removed = 0
    scanned = 0
    try:
        entries = os.scandir(root)
    except (OSError, ValueError):
        return 0

    with entries:
        for entry in entries:
            if scanned >= WORK_CLEANUP_SCAN_LIMIT or removed >= WORK_CLEANUP_REMOVE_LIMIT:
                break
            scanned += 1
            if not entry.name.startswith("job-"):
                continue
            try:
                details = entry.stat(follow_symlinks=False)
            except (OSError, ValueError):
                continue
            if (
                not stat.S_ISDIR(details.st_mode)
                or (
                    getattr(details, "st_file_attributes", 0)
                    & FILE_ATTRIBUTE_REPARSE_POINT
                )
                or now - details.st_mtime < WORK_CLEANUP_MIN_AGE_SECONDS
            ):
                continue
            if remove_job_directory(Path(entry.path), root):
                removed += 1
    return removed


def truncate_log_message(message: str) -> str:
    if len(message) <= LOG_MESSAGE_MAX_CHARS:
        return message
    removed = len(message) - LOG_MESSAGE_HEAD_CHARS - LOG_MESSAGE_TAIL_CHARS
    marker = f"\n[... {removed:,} characters truncated ...]\n"
    return (
        message[:LOG_MESSAGE_HEAD_CHARS]
        + marker
        + message[-LOG_MESSAGE_TAIL_CHARS:]
    )


def read_bounded_log_stream(stream) -> str:
    stream.flush()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    if size <= CAPTURED_LOG_HEAD_BYTES + CAPTURED_LOG_TAIL_BYTES:
        stream.seek(0)
        data = stream.read()
    else:
        stream.seek(0)
        head = stream.read(CAPTURED_LOG_HEAD_BYTES)
        stream.seek(-CAPTURED_LOG_TAIL_BYTES, os.SEEK_END)
        tail = stream.read(CAPTURED_LOG_TAIL_BYTES)
        removed = size - CAPTURED_LOG_HEAD_BYTES - CAPTURED_LOG_TAIL_BYTES
        marker = f"\n[... {removed:,} captured bytes truncated ...]\n".encode()
        data = head + marker + tail
    return data.decode("utf-8", errors="replace").strip()


class TrafficLightButton(QPushButton):
    def __init__(self, color_name: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.setObjectName(color_name)
        self.setToolTip(tooltip)
        self.setFixedSize(13, 13)
        self.setCursor(Qt.PointingHandCursor)


class TitleBar(QFrame):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.drag_offset = QPoint()
        self.setObjectName("titleBar")
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        maximize_button = TrafficLightButton("maximizeDot", "Maximize")
        minimize_button = TrafficLightButton("minimizeDot", "Minimize")
        close_button = TrafficLightButton("closeDot", "Close")

        close_button.clicked.connect(host.close)
        minimize_button.clicked.connect(host.showMinimized)
        maximize_button.clicked.connect(self.toggle_maximized)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        controls.addWidget(maximize_button)
        controls.addWidget(minimize_button)
        controls.addWidget(close_button)

        controls_holder = QWidget()
        controls_holder.setFixedWidth(64)
        controls_holder.setLayout(controls)

        title = QLabel(APP_TITLE)
        title.setObjectName("windowTitle")
        title.setAlignment(Qt.AlignCenter)

        left_spacer = QWidget()
        left_spacer.setFixedWidth(64)

        layout.addWidget(left_spacer)
        layout.addStretch()
        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(controls_holder)

    def toggle_maximized(self):
        if self.host.isMaximized():
            self.host.showNormal()
        else:
            self.host.showMaximized()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
            event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.drag_offset = (
                event.globalPosition().toPoint()
                - self.host.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton and not self.host.isMaximized():
            self.host.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()


class ChevronButton(QPushButton):
    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(Qt.white, 1.4))

        x = self.width() - 20
        y = self.height() // 2 - 1
        painter.drawLine(x - 4, y - 2, x, y + 2)
        painter.drawLine(x, y + 2, x + 4, y - 2)


class AnimatedDropdown(QWidget):
    changed = Signal(str)

    def __init__(self, items, current_index=0, parent=None):
        super().__init__(parent)
        self.items = list(items)
        self._current = self.items[current_index]
        self._animation = None
        self._closing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.button = ChevronButton(self._current)
        self.button.setObjectName("dropdownButton")
        self.button.setMinimumHeight(38)
        self.button.clicked.connect(self.toggle_popup)
        layout.addWidget(self.button)

        self.popup = QFrame(
            self,
            Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.popup.setObjectName("dropdownPopup")
        self.popup.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout(self.popup)
        outer.setContentsMargins(0, 0, 0, 0)

        surface = QFrame()
        surface.setObjectName("dropdownSurface")

        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(5, 5, 5, 5)
        surface_layout.setSpacing(2)

        for item in self.items:
            option = QPushButton(item)
            option.setObjectName("dropdownOption")
            option.setMinimumHeight(32)
            option.clicked.connect(
                lambda checked=False, value=item: self.select(value)
            )
            surface_layout.addWidget(option)

        outer.addWidget(surface)

    def currentText(self):
        return self._current

    def select(self, value):
        self._current = value
        self.button.setText(value)
        self.changed.emit(value)
        self.hide_popup()

    def toggle_popup(self):
        if self.popup.isVisible() and not self._closing:
            self.hide_popup()
        else:
            self.show_popup()

    def show_popup(self):
        self._stop_popup_animation()
        self._closing = False
        popup_height = len(self.items) * 34 + 12
        popup_width = self.width()

        button_top_left = self.mapToGlobal(QPoint(0, 0))
        below_y = button_top_left.y() + self.height() + 4

        screen = QApplication.screenAt(button_top_left)
        available = screen.availableGeometry() if screen else QRect()

        if available and below_y + popup_height > available.bottom():
            final_y = button_top_left.y() - popup_height - 4
        else:
            final_y = below_y

        final_x = button_top_left.x()
        if available:
            final_x = max(
                available.left(),
                min(final_x, available.right() - popup_width + 1),
            )
            final_y = max(
                available.top(),
                min(final_y, available.bottom() - popup_height + 1),
            )

        end_rect = QRect(final_x, final_y, popup_width, popup_height)
        QApplication.instance().installEventFilter(self)
        self.popup.setGeometry(end_rect)
        self.popup.setWindowOpacity(0.0)
        self.popup.show()
        self.popup.raise_()
        opacity_animation = QPropertyAnimation(
            self.popup, b"windowOpacity", self
        )
        opacity_animation.setDuration(110)
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation = opacity_animation
        opacity_animation.finished.connect(
            lambda current=opacity_animation: self._popup_animation_finished(
                current, False
            )
        )
        opacity_animation.start()

    def hide_popup(self):
        if not self.popup.isVisible():
            return
        self._stop_popup_animation()
        self._closing = True
        QApplication.instance().removeEventFilter(self)
        opacity_animation = QPropertyAnimation(
            self.popup, b"windowOpacity", self
        )
        opacity_animation.setDuration(75)
        opacity_animation.setStartValue(self.popup.windowOpacity())
        opacity_animation.setEndValue(0.0)
        opacity_animation.setEasingCurve(QEasingCurve.InCubic)
        self._animation = opacity_animation
        opacity_animation.finished.connect(
            lambda current=opacity_animation: self._popup_animation_finished(
                current, True
            )
        )
        opacity_animation.start()

    def _stop_popup_animation(self):
        if self._animation is None:
            return
        animation = self._animation
        self._animation = None
        animation.stop()
        animation.deleteLater()

    def _popup_animation_finished(self, animation, hide_after):
        if self._animation is animation:
            self._animation = None
        if hide_after:
            self.popup.hide()
            self.popup.setWindowOpacity(1.0)
            self._closing = False
        animation.deleteLater()

    def eventFilter(self, watched, event):
        if self.popup.isVisible() and event.type() == QEvent.MouseButtonPress:
            global_position = event.globalPosition().toPoint()

            popup_rect = self.popup.frameGeometry()
            button_rect = QRect(
                self.button.mapToGlobal(QPoint(0, 0)),
                self.button.size(),
            )

            if (
                not popup_rect.contains(global_position)
                and not button_rect.contains(global_position)
            ):
                self.hide_popup()

        return super().eventFilter(watched, event)


class LuaObfuscator(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(APP_TITLE)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)

        self.resize(660, 570)
        self.setMinimumSize(620, 530)

        self.app_dir = Path(__file__).resolve().parent
        self.source_file: Optional[Path] = None
        self.output_folder = Path.home() / "Downloads"
        self.output_file: Optional[Path] = None
        self.process: Optional[QProcess] = None
        self.validation_process: Optional[QProcess] = None
        self.validation_output = bytearray()
        self.validation_output_dropped = 0
        self.validation_timed_out = False
        self.work_dir: Optional[Path] = None
        self.staged_output: Optional[Path] = None
        self.active_target: Optional[str] = None
        self.running = False
        self.cancel_requested = False
        self.last_log_message = ""
        self.process_log_head_chars = 0
        self.process_log_overflow_chars = 0
        self.process_log_tail = ""
        self.process_log_decoder = None
        self.process_log_finalized = False
        self.process_read_scheduled = False
        self.process_log_final_requested = False
        self.pending_process_result = None

        self.validation_timer = QTimer(self)
        self.validation_timer.setSingleShot(True)
        self.validation_timer.timeout.connect(self.validation_timeout)
        self.stale_cleanup_timer = QTimer(self)
        self.stale_cleanup_timer.setSingleShot(True)
        self.stale_cleanup_timer.timeout.connect(self.start_stale_work_cleanup)

        self.lua_path = self.find_lua_runtime()
        self.cli_path = self.find_hercules_cli()

        self.apply_style()
        self.build_ui()
        self.report_setup_status()
        self.stale_cleanup_timer.start(750)

    @staticmethod
    def _creation_flags():
        return 0x08000000 if os.name == "nt" else 0

    def start_stale_work_cleanup(self):
        work_root = self.app_dir / ".runtime" / "work"
        threading.Thread(
            target=cleanup_stale_work_directories,
            args=(work_root,),
            name="FleeceLuaWorkCleanup",
            daemon=True,
        ).start()

    @staticmethod
    def file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(262144), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def is_compatible_lua(self, path: Path) -> bool:
        try:
            runtime_dir = path.resolve().parent
            for filename, expected_hash in LUA_RUNTIME_HASHES.items():
                candidate = (runtime_dir / filename).resolve()
                if candidate.parent != runtime_dir or not candidate.is_file():
                    return False
                if self.file_sha256(candidate) != expected_hash:
                    return False
            return True
        except (OSError, RuntimeError, ValueError):
            return False

    def find_lua_runtime(self) -> Optional[Path]:
        candidate = self.app_dir / ".runtime" / "lua54" / "lua54.exe"
        try:
            candidate = candidate.resolve()
            compatible = candidate.is_file() and self.is_compatible_lua(candidate)
        except (OSError, RuntimeError, ValueError):
            return None
        return candidate if compatible else None

    def find_hercules_cli(self) -> Optional[Path]:
        candidate = self.app_dir / ".runtime" / "hercules" / "src" / "hercules.lua"
        try:
            candidate = candidate.resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        version_file = candidate.parent.parent / ".fleece-version"
        required_files = (
            candidate.parent / "pipeline.lua",
            candidate.parent / "manifest.lua",
            candidate.parent.parent / "LICENSE",
            version_file,
        )
        try:
            version = version_file.read_text(encoding="ascii").strip()
            files_available = all(path.is_file() for path in required_files)
        except (OSError, RuntimeError, UnicodeError, ValueError):
            return None
        if files_available and version == HERCULES_COMMIT:
            return candidate
        return None

    def apply_style(self):
        QApplication.instance().setStyleSheet(
            """
            QWidget {
                color: #f5f5f5;
                font-family: "Segoe UI";
                font-size: 13px;
            }

            QFrame#windowFrame {
                background: #070707;
                border: 1px solid #252525;
                border-radius: 14px;
            }

            QFrame#titleBar {
                background: #070707;
                border: none;
                border-bottom: 1px solid #1c1c1c;
                border-top-left-radius: 14px;
                border-top-right-radius: 14px;
            }

            QLabel#windowTitle {
                color: #bdbdbd;
                font-size: 12px;
                font-weight: 600;
            }

            QPushButton#closeDot,
            QPushButton#minimizeDot,
            QPushButton#maximizeDot {
                border: none;
                border-radius: 6px;
                min-height: 13px;
                max-height: 13px;
                min-width: 13px;
                max-width: 13px;
                padding: 0;
            }

            QPushButton#closeDot { background: #ff5f57; }
            QPushButton#minimizeDot { background: #febc2e; }
            QPushButton#maximizeDot { background: #28c840; }

            QPushButton#closeDot:hover,
            QPushButton#minimizeDot:hover,
            QPushButton#maximizeDot:hover {
                border: 1px solid rgba(0, 0, 0, 90);
            }

            QLabel#label {
                color: #b8b8b8;
                font-size: 12px;
                font-weight: 600;
            }

            QLabel#status {
                color: #8b8b8b;
                font-size: 12px;
            }

            QLabel#note {
                color: #7a7a7a;
                font-size: 11px;
            }

            QFrame#panel {
                background: #0d0d0d;
                border: 1px solid #242424;
                border-radius: 14px;
            }

            QPushButton {
                background: #151515;
                border: 1px solid #2b2b2b;
                border-radius: 10px;
                min-height: 38px;
                padding: 0 14px;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #1d1d1d;
                border-color: #3a3a3a;
            }

            QPushButton:pressed { background: #101010; }

            QPushButton#primary {
                background: #ffffff;
                color: #000000;
                border: none;
                min-height: 42px;
            }

            QPushButton#primary:hover { background: #e7e7e7; }

            QPushButton#small {
                min-height: 28px;
                max-height: 28px;
                border-radius: 8px;
                padding: 0 10px;
                color: #bdbdbd;
                font-size: 11px;
            }

            QPushButton#dropdownButton {
                background: #0a0a0a;
                border: 1px solid #292929;
                border-radius: 10px;
                min-height: 38px;
                padding: 0 38px 0 12px;
                text-align: left;
                font-weight: 500;
            }

            QPushButton#dropdownButton:hover {
                background: #101010;
                border-color: #3b3b3b;
            }

            QFrame#dropdownSurface {
                background: #111111;
                border: 1px solid #303030;
                border-radius: 11px;
            }

            QPushButton#dropdownOption {
                background: transparent;
                border: none;
                border-radius: 7px;
                min-height: 32px;
                padding: 0 10px;
                text-align: left;
                font-weight: 500;
            }

            QPushButton#dropdownOption:hover { background: #242424; }

            QFrame#pathFrame {
                background: #0a0a0a;
                border: 1px solid #292929;
                border-radius: 10px;
            }

            QLabel#pathLabel {
                color: #d7d7d7;
                padding-left: 11px;
            }

            QTextEdit {
                background: #090909;
                color: #c8c8c8;
                border: 1px solid #242424;
                border-radius: 10px;
                padding: 8px;
                font-family: "Cascadia Mono", "Consolas";
                font-size: 11px;
                selection-background-color: #ffffff;
                selection-color: #000000;
            }

            QProgressBar {
                background: #121212;
                border: none;
                border-radius: 3px;
                min-height: 6px;
                max-height: 6px;
            }

            QProgressBar::chunk {
                background: #ffffff;
                border-radius: 3px;
            }

            QScrollBar:vertical {
                width: 8px;
                background: transparent;
            }

            QScrollBar::handle:vertical {
                background: #333333;
                border-radius: 4px;
                min-height: 24px;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
            """
        )

    def build_ui(self):
        label_gap = 6
        group_gap = 10
        side_button_width = 84

        central = QWidget()
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)

        window_frame = QFrame()
        window_frame.setObjectName("windowFrame")
        outer.addWidget(window_frame)

        window_layout = QVBoxLayout(window_frame)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.setSpacing(0)

        self.title_bar = TitleBar(self)
        window_layout.addWidget(self.title_bar)

        content = QWidget()
        window_layout.addWidget(content, 1)

        page = QVBoxLayout(content)
        page.setContentsMargins(22, 18, 22, 18)
        page.setSpacing(0)

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(group_gap)

        file_group = QVBoxLayout()
        file_group.setSpacing(label_gap)
        file_label = QLabel("Script file (.lua, .luau, or .txt)")
        file_label.setObjectName("label")
        file_group.addWidget(file_label)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        file_frame = QFrame()
        file_frame.setObjectName("pathFrame")
        file_frame.setMinimumHeight(38)
        file_layout = QHBoxLayout(file_frame)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.file_path_label = QLabel("Choose a file or drag it here")
        self.file_path_label.setObjectName("pathLabel")
        self.file_path_label.setTextInteractionFlags(Qt.NoTextInteraction)
        file_layout.addWidget(self.file_path_label)
        self.file_browse_button = QPushButton("Browse")
        self.file_browse_button.setFixedWidth(side_button_width)
        self.file_browse_button.clicked.connect(self.choose_file)
        file_row.addWidget(file_frame, 1)
        file_row.addWidget(self.file_browse_button)
        file_group.addLayout(file_row)
        layout.addLayout(file_group)

        selectors = QHBoxLayout()
        selectors.setSpacing(10)

        level_column = QVBoxLayout()
        level_column.setSpacing(label_gap)
        level_label = QLabel("Obfuscation level")
        level_label.setObjectName("label")
        self.level_dropdown = AnimatedDropdown(
            ["Low", "Medium", "High"],
            current_index=1,
        )
        self.level_dropdown.changed.connect(self.level_changed)
        level_column.addWidget(level_label)
        level_column.addWidget(self.level_dropdown)

        info_column = QVBoxLayout()
        info_column.setSpacing(label_gap)
        info_label = QLabel("Target")
        info_label.setObjectName("label")
        self.target_dropdown = AnimatedDropdown(
            ["Lua 5.4", "Roblox Luau"],
            current_index=0,
        )
        info_column.addWidget(info_label)
        info_column.addWidget(self.target_dropdown)

        selectors.addLayout(level_column, 1)
        selectors.addLayout(info_column, 1)
        layout.addLayout(selectors)

        self.level_note = QLabel(
            "Medium is the recommended balance. High is much larger and slower."
        )
        self.level_note.setObjectName("note")
        self.level_note.setWordWrap(True)
        layout.addWidget(self.level_note)

        save_group = QVBoxLayout()
        save_group.setSpacing(label_gap)
        output_label = QLabel("Save to")
        output_label.setObjectName("label")
        save_group.addWidget(output_label)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_frame = QFrame()
        path_frame.setObjectName("pathFrame")
        path_frame.setMinimumHeight(38)
        path_layout = QHBoxLayout(path_frame)
        path_layout.setContentsMargins(0, 0, 0, 0)
        self.output_path_label = QLabel(str(self.output_folder))
        self.output_path_label.setObjectName("pathLabel")
        self.output_path_label.setTextInteractionFlags(Qt.NoTextInteraction)
        path_layout.addWidget(self.output_path_label)
        self.output_browse_button = QPushButton("Browse")
        self.output_browse_button.setFixedWidth(side_button_width)
        self.output_browse_button.clicked.connect(self.choose_output_folder)
        path_row.addWidget(path_frame, 1)
        path_row.addWidget(self.output_browse_button)
        save_group.addLayout(path_row)
        layout.addLayout(save_group)

        self.obfuscate_button = QPushButton("Obfuscate")
        self.obfuscate_button.setObjectName("primary")
        self.obfuscate_button.clicked.connect(self.obfuscate_or_cancel)
        layout.addWidget(self.obfuscate_button)

        progress_group = QVBoxLayout()
        progress_group.setSpacing(label_gap)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_group.addWidget(self.progress_bar)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status")
        progress_group.addWidget(self.status_label)
        layout.addLayout(progress_group)

        log_group = QVBoxLayout()
        log_group.setSpacing(label_gap)
        log_header = QHBoxLayout()
        log_header.setSpacing(6)
        log_label = QLabel("Log")
        log_label.setObjectName("label")
        self.open_folder_button = QPushButton("Open output")
        self.open_folder_button.setObjectName("small")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self.open_output_folder)
        clear_button = QPushButton("Clear")
        clear_button.setObjectName("small")
        clear_button.clicked.connect(self.clear_log)
        log_header.addWidget(log_label)
        log_header.addStretch()
        log_header.addWidget(self.open_folder_button)
        log_header.addWidget(clear_button)
        log_group.addLayout(log_header)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.document().setMaximumBlockCount(LOG_DOCUMENT_MAX_BLOCKS)
        self.log_box.setPlaceholderText("No activity")
        self.log_box.setMinimumHeight(105)
        log_group.addWidget(self.log_box, 1)
        layout.addLayout(log_group, 1)

        page.addWidget(panel, 1)

    def report_setup_status(self):
        missing = []
        if self.lua_path is None:
            missing.append("Lua 5.4")
        if self.cli_path is None:
            missing.append("Hercules")

        if missing:
            self.status_label.setText("Setup needed")
            self.append_log(
                "Missing: " + ", ".join(missing) + ". Run installer.bat again."
            )
        else:
            self.status_label.setText("Ready")
            self.append_log(f"Lua: {self.lua_path}")
            self.append_log(f"Hercules: {self.cli_path.parent.parent}")

    def level_changed(self, value: str):
        notes = {
            "Low": "Low is fast and produces smaller output.",
            "Medium": "Medium is the recommended balance of protection and size.",
            "High": "High uses every compatible protection. Output can be huge and slower.",
        }
        self.level_note.setText(notes[value])

    def choose_file(self):
        start_folder = (
            str(self.source_file.parent)
            if self.source_file
            else str(Path.home() / "Downloads")
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Lua or Luau File",
            start_folder,
            "Lua and Luau files (*.lua *.luau *.txt);;All files (*.*)",
        )
        if filename:
            self.set_source_file(Path(filename))

    def set_source_file(self, path: Path):
        if self.running:
            return
        try:
            path = path.expanduser().resolve(strict=True)
            path_is_file = path.is_file()
        except (OSError, RuntimeError, ValueError) as error:
            self.clear_source_selection()
            self.status_label.setText("Choose a script file")
            self.append_log(f"Could not open that script path: {error}")
            return
        if not path_is_file or path.suffix.lower() not in {".lua", ".luau", ".txt"}:
            self.clear_source_selection()
            self.status_label.setText("Choose a script file")
            self.append_log("Choose a valid .lua, .luau, or .txt file.")
            return

        self.source_file = path
        self.output_folder = path.parent
        self.file_path_label.setText(str(path))
        self.file_path_label.setToolTip(str(path))
        self.output_path_label.setText(str(self.output_folder))
        self.output_path_label.setToolTip(str(self.output_folder))
        self.output_file = None
        self.open_folder_button.setEnabled(False)
        self.status_label.setText("Ready")
        self.append_log(f"Selected: {path.name}")
        if path.suffix.lower() == ".luau":
            self.target_dropdown.select("Roblox Luau")

    def clear_source_selection(self):
        self.source_file = None
        self.output_file = None
        self.file_path_label.setText("Choose a file or drag it here")
        self.file_path_label.setToolTip("")
        self.open_folder_button.setEnabled(False)

    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Output Folder",
            str(self.output_folder),
        )
        if folder:
            try:
                self.output_folder = Path(folder).resolve(strict=True)
            except (OSError, RuntimeError, ValueError) as error:
                self.status_label.setText("Invalid output")
                self.append_log(f"Could not use that output folder: {error}")
                return
            self.output_path_label.setText(str(self.output_folder))
            self.output_path_label.setToolTip(str(self.output_folder))

    def clear_log(self):
        self.log_box.clear()
        self.last_log_message = ""
        if not self.running:
            self.status_label.setText("Ready")
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)

    def append_log(self, message: str):
        message = truncate_log_message(str(message))
        message = ANSI_RE.sub("", message).strip()
        if not message or message == self.last_log_message:
            return

        self.last_log_message = message
        cursor = self.log_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        if not self.log_box.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(message)
        self.log_box.setTextCursor(cursor)
        scrollbar = self.log_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def reset_process_log_capture(self):
        self.process_log_head_chars = 0
        self.process_log_overflow_chars = 0
        self.process_log_tail = ""
        self.process_log_decoder = codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )
        self.process_log_finalized = False
        self.process_read_scheduled = False
        self.process_log_final_requested = False
        self.pending_process_result = None

    def consume_process_log_text(self, text: str):
        if not text:
            return
        available = max(0, PROCESS_LOG_HEAD_CHARS - self.process_log_head_chars)
        head = text[:available]
        for index in range(0, len(head), LOG_MESSAGE_MAX_CHARS):
            self.append_log(head[index : index + LOG_MESSAGE_MAX_CHARS])
        self.process_log_head_chars += len(head)
        overflow = text[len(head) :]
        if overflow:
            self.process_log_overflow_chars += len(overflow)
            self.process_log_tail = (self.process_log_tail + overflow)[
                -PROCESS_LOG_TAIL_CHARS:
            ]

    def finalize_process_log_capture(self):
        if self.process_log_finalized:
            return
        self.process_log_finalized = True
        if self.process_log_decoder is not None:
            self.consume_process_log_text(self.process_log_decoder.decode(b"", final=True))
        if not self.process_log_overflow_chars:
            return
        removed = self.process_log_overflow_chars - len(self.process_log_tail)
        if removed > 0:
            self.append_log(
                f"[... {removed:,} process output characters truncated ...]\n"
                + self.process_log_tail
            )
        else:
            self.append_log(self.process_log_tail)

    def refresh_tool_paths(self):
        self.lua_path = self.find_lua_runtime()
        self.cli_path = self.find_hercules_cli()

    def obfuscate_or_cancel(self):
        if self.running:
            self.cancel_obfuscation()
        else:
            self.start_obfuscation()

    def start_obfuscation(self):
        if self.running:
            return
        self.refresh_tool_paths()

        try:
            source_is_file = self.source_file is not None and self.source_file.is_file()
        except (OSError, RuntimeError, ValueError):
            source_is_file = False
        if not source_is_file:
            self.status_label.setText("Choose a file")
            self.append_log("Choose a .lua, .luau, or .txt file first.")
            return

        if self.lua_path is None:
            self.status_label.setText("Lua 5.4 missing")
            self.append_log("Lua 5.4 was not found. Run Installer.bat again.")
            return

        if self.cli_path is None:
            self.status_label.setText("Hercules missing")
            self.append_log("Hercules was not found. Run Installer.bat again.")
            return

        target_label = self.target_dropdown.currentText()
        target = TARGET_MAP[target_label]
        output_extension = ".luau" if target == "luau" else ".lua"
        output_file = self.output_folder / (
            f"{self.source_file.stem}.obfuscated{output_extension}"
        )

        try:
            self.output_folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.status_label.setText("Invalid output")
            self.append_log(f"Could not create the output folder: {error}")
            return

        try:
            output_matches_source = (
                output_file.resolve() == self.source_file.resolve(strict=True)
            )
        except (OSError, RuntimeError, ValueError) as error:
            self.status_label.setText("Invalid output")
            self.append_log(f"Could not validate the output path: {error}")
            return
        if output_matches_source:
            self.status_label.setText("Invalid output")
            self.append_log("The output cannot overwrite the original file.")
            return

        try:
            output_exists = output_file.exists()
        except (OSError, RuntimeError, ValueError) as error:
            self.status_label.setText("Invalid output")
            self.append_log(f"Could not inspect the output path: {error}")
            return
        if output_exists:
            choice = QMessageBox.question(
                self,
                "Replace output?",
                f"{output_file.name} already exists. Replace it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if choice != QMessageBox.Yes:
                self.status_label.setText("Cancelled")
                return

        preset = PRESET_MAP[self.level_dropdown.currentText()]
        self.cleanup_work_dir()

        try:
            work_root = prepare_work_root(self.app_dir / ".runtime")
            self.work_dir = Path(
                tempfile.mkdtemp(prefix="job-", dir=str(work_root))
            )
            staged_source = self.work_dir / f"input{output_extension}"
            shutil.copy2(self.source_file, staged_source)
            self.staged_output = self.work_dir / (
                f"input_obfuscated{output_extension}"
            )
            staged_source_argument = os.path.relpath(
                staged_source,
                start=self.cli_path.parent,
            )
        except (OSError, RuntimeError, ValueError) as error:
            self.cleanup_work_dir()
            self.status_label.setText("Could not prepare")
            self.append_log(f"Could not prepare the source file: {error}")
            return

        args = build_obfuscation_arguments(
            self.cli_path.name,
            staged_source_argument,
            target,
            preset,
        )

        self.output_file = output_file
        self.active_target = target
        self.cancel_requested = False
        self.last_log_message = ""
        self.log_box.clear()
        self.reset_process_log_capture()
        self.open_folder_button.setEnabled(False)

        self.append_log(f"Input: {self.source_file}")
        self.append_log(f"Target: {target_label}")
        self.append_log(f"Preset: {preset} ({self.level_dropdown.currentText()})")
        self.append_log(f"Output: {output_file}")

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(self.cli_path.parent))
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_process_output)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)

        self.running = True
        self.obfuscate_button.setText("Cancel")
        self.status_label.setText("Obfuscating...")
        self.progress_bar.setRange(0, 0)
        self.set_controls_enabled(False)

        self.process.start(str(self.lua_path), args)

    def set_controls_enabled(self, enabled: bool):
        self.file_browse_button.setEnabled(enabled)
        self.output_browse_button.setEnabled(enabled)
        self.level_dropdown.setEnabled(enabled)
        self.target_dropdown.setEnabled(enabled)

    def schedule_process_log_read(self):
        if self.process_read_scheduled:
            return
        self.process_read_scheduled = True
        QTimer.singleShot(0, self.continue_process_log_read)

    def continue_process_log_read(self):
        self.process_read_scheduled = False
        final = self.process_log_final_requested
        complete = self.read_process_output(final=final)
        if final and complete and self.pending_process_result is not None:
            self.complete_process_finished()

    def read_process_output(self, final=False):
        if not self.process:
            return True
        if self.process_log_decoder is None:
            self.process_log_decoder = codecs.getincrementaldecoder("utf-8")(
                errors="replace"
            )
        remaining = PROCESS_READ_BUDGET_BYTES
        while self.process.bytesAvailable() > 0 and remaining > 0:
            size = min(
                PROCESS_READ_CHUNK_BYTES,
                self.process.bytesAvailable(),
                remaining,
            )
            chunk = bytes(self.process.read(size))
            if not chunk:
                break
            self.consume_process_log_text(self.process_log_decoder.decode(chunk))
            remaining -= len(chunk)
        if self.process.bytesAvailable() > 0:
            self.schedule_process_log_read()
            return False
        if final:
            self.finalize_process_log_capture()
        return True

    def cancel_obfuscation(self):
        if not self.running:
            return
        self.cancel_requested = True
        self.status_label.setText("Stopping...")
        process = self.validation_process or self.process
        if process and process.state() != QProcess.NotRunning:
            process.kill()

    def staged_output_size(self):
        if self.staged_output is None:
            return None
        try:
            if not self.staged_output.is_file():
                return None
            size = self.staged_output.stat().st_size
        except (OSError, RuntimeError, ValueError) as error:
            self.append_log(f"Could not inspect the staged output: {error}")
            return None
        return size if size > 0 else None

    def start_output_validation(self, staged_size):
        if self.active_target != "lua" or self.lua_path is None:
            if self.active_target == "luau":
                self.append_log("Luau output is not syntax-checked locally. Test it in its intended Luau environment before use.")
            self.publish_validated_output()
            return

        compiler_path = self.lua_path.with_name("luac54.exe")
        try:
            compiler_available = compiler_path.is_file()
            staged_output_argument = os.path.relpath(
                self.staged_output,
                start=compiler_path.parent,
            )
        except (OSError, RuntimeError, ValueError) as error:
            self.finish_operation(
                "Failed",
                f"Lua syntax check could not be prepared: {error}",
            )
            return

        if not compiler_available:
            self.finish_operation(
                "Failed",
                "Lua output could not be syntax checked because the private compiler is missing. Run Installer.bat again.",
            )
            return

        process = QProcess(self)
        self.validation_process = process
        self.validation_output.clear()
        self.validation_output_dropped = 0
        self.validation_timed_out = False
        process.setWorkingDirectory(str(compiler_path.parent))
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(
            lambda current=process: self.read_validation_output(current)
        )
        process.finished.connect(
            lambda exit_code, exit_status, current=process: (
                self.validation_finished(current, exit_code, exit_status)
            )
        )
        process.errorOccurred.connect(
            lambda error, current=process: self.validation_error(current, error)
        )

        timeout_seconds = max(30, min(300, 30 + staged_size // 1048576))
        self.validation_timer.start(timeout_seconds * 1000)
        self.status_label.setText("Checking output...")
        self.append_log("Checking Lua 5.4 syntax...")
        process.start(str(compiler_path), ["-p", staged_output_argument])

    def read_validation_output(self, process):
        if self.validation_process is not process:
            return
        data = bytes(process.readAllStandardOutput())
        self.validation_output_dropped += extend_bounded_bytes(
            self.validation_output,
            data,
            VALIDATION_LOG_MAX_BYTES,
        )

    def validation_details(self):
        details = self.validation_output.decode("utf-8", errors="replace").strip()
        if self.validation_output_dropped:
            marker = (
                f"[... {self.validation_output_dropped:,} validation output bytes "
                "discarded ...]"
            )
            details = f"{details}\n{marker}" if details else marker
        return details

    def validation_timeout(self):
        process = self.validation_process
        if process is None or process.state() == QProcess.NotRunning:
            return
        self.validation_timed_out = True
        self.status_label.setText("Stopping syntax check...")
        process.kill()

    def validation_finished(self, process, exit_code, exit_status):
        if self.validation_process is not process:
            return
        self.read_validation_output(process)
        self.validation_timer.stop()
        details = self.validation_details()
        timed_out = self.validation_timed_out
        self.validation_process = None
        process.deleteLater()

        if self.cancel_requested:
            self.finish_operation("Cancelled", "Obfuscation cancelled.")
        elif timed_out:
            if details:
                self.append_log(details)
            self.finish_operation("Failed", "Lua syntax check timed out.")
        elif exit_status != QProcess.NormalExit or exit_code != 0:
            if details:
                self.append_log(details)
            self.finish_operation("Failed", "Lua output failed its syntax check.")
        else:
            self.append_log("Lua 5.4 syntax check passed.")
            self.publish_validated_output()

    def validation_error(self, process, error):
        if self.validation_process is not process:
            return
        self.read_validation_output(process)
        if error == QProcess.FailedToStart:
            self.validation_timer.stop()
            details = self.validation_details()
            self.validation_process = None
            process.deleteLater()
            if details:
                self.append_log(details)
            if self.cancel_requested:
                self.finish_operation("Cancelled", "Obfuscation cancelled.")
            else:
                self.finish_operation("Failed", "Lua syntax check could not start.")
        elif error != QProcess.Crashed:
            self.append_log(f"Lua syntax-check process error: {error}")

    def publish_validated_output(self):
        if self.cancel_requested:
            self.finish_operation("Cancelled", "Obfuscation cancelled.")
        elif self.publish_staged_output():
            self.finish_operation(
                "Done",
                "Finished successfully.",
                progress=100,
                output_ready=True,
            )
        else:
            self.finish_operation("Failed", "The output could not be saved.")

    def publish_staged_output(self) -> bool:
        if self.output_file is None or self.staged_output is None:
            return False

        transfer_file = self.output_file.with_name(
            f".{self.output_file.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            shutil.copy2(self.staged_output, transfer_file)
            os.replace(transfer_file, self.output_file)
            return self.output_file.is_file() and self.output_file.stat().st_size > 0
        except (OSError, RuntimeError, ValueError) as error:
            self.append_log(f"Could not save the output: {error}")
            return False
        finally:
            try:
                transfer_file.unlink(missing_ok=True)
            except (OSError, RuntimeError, ValueError):
                pass

    def cleanup_work_dir(self):
        if self.work_dir is not None:
            remove_job_directory(
                self.work_dir,
                self.app_dir / ".runtime" / "work",
            )
        self.work_dir = None
        self.staged_output = None

    def finish_operation(self, status, message, progress=0, output_ready=False):
        self.validation_timer.stop()
        self.running = False
        self.obfuscate_button.setText("Obfuscate")
        self.set_controls_enabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(progress)
        self.status_label.setText(status)
        self.append_log(message)
        self.open_folder_button.setEnabled(output_ready)
        self.cleanup_work_dir()
        self.process = None
        self.validation_process = None
        self.active_target = None
        self.cancel_requested = False

    def process_finished(self, exit_code, exit_status):
        if self.process is None or not self.running:
            return
        self.pending_process_result = (exit_code, exit_status)
        self.process_log_final_requested = True
        if self.read_process_output(final=True):
            self.complete_process_finished()

    def complete_process_finished(self):
        if self.pending_process_result is None:
            return
        exit_code, exit_status = self.pending_process_result
        self.pending_process_result = None
        self.process_log_final_requested = False
        finished_process = self.process
        self.process = None
        if finished_process is not None:
            finished_process.deleteLater()

        if self.cancel_requested:
            self.finish_operation("Cancelled", "Obfuscation cancelled.")
        elif exit_status != QProcess.NormalExit or exit_code != 0:
            self.finish_operation(
                "Failed",
                f"Hercules exited with code {exit_code}.",
            )
        else:
            staged_size = self.staged_output_size()
            if staged_size is None:
                self.finish_operation(
                    "Failed",
                    "Obfuscation did not produce a valid output.",
                )
            else:
                self.start_output_validation(staged_size)

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.read_process_output(final=True)
            self.pending_process_result = None
            self.process_log_final_requested = False
            failed_process = self.process
            self.process = None
            if failed_process is not None:
                failed_process.deleteLater()
            self.finish_operation(
                "Failed",
                "Could not start Lua. Run installer.bat again.",
            )
        elif self.running and error != QProcess.Crashed:
            self.append_log(f"Process error: {error}")

    def open_output_folder(self):
        folder = (
            self.output_file.parent
            if self.output_file is not None
            else self.output_folder
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def dragEnterEvent(self, event: QDragEnterEvent):
        if self.running:
            event.ignore()
            return
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() in {".lua", ".luau", ".txt"}:
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        if self.running:
            event.ignore()
            return
        urls = event.mimeData().urls()
        if urls:
            self.set_source_file(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent):
        self.level_dropdown.hide_popup()
        self.target_dropdown.hide_popup()
        self.stale_cleanup_timer.stop()
        self.validation_timer.stop()
        self.cancel_requested = True
        for process in (self.validation_process, self.process):
            if process and process.state() != QProcess.NotRunning:
                process.kill()
                process.waitForFinished(1000)
        self.cleanup_work_dir()
        event.accept()


def run_self_test(output_dir):
    assert APP_VERSION == "1.0.15"
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    checks = []

    assert PRESET_MAP == {
        "Low": "light",
        "Medium": "balanced",
        "High": "maximum",
    }
    assert TARGET_MAP == {"Lua 5.4": "lua", "Roblox Luau": "luau"}
    checks.append("target and protection presets are stable")

    window = LuaObfuscator()
    try:
        assert window.windowTitle() == APP_TITLE
        assert window.lua_path is not None and window.lua_path.is_file()
        assert window.cli_path is not None and window.cli_path.is_file()
        assert not window.running
        assert window.process is None
        assert window.validation_process is None
        assert window.validation_timer.isSingleShot()
        checks.append("window and local engine paths initialize without user files")

        engine_args = build_obfuscation_arguments(
            window.cli_path.name,
            "input.lua",
            "lua",
            "light",
        )
        assert engine_args == [
            "-E",
            window.cli_path.name,
            "input.lua",
            "--target",
            "lua",
            "--light",
            "--no-watermark",
        ]

        hostile_environment = os.environ.copy()
        hostile_environment.update(
            {
                "LUA_INIT": "error('LUA_INIT must be ignored')",
                "LUA_PATH": "C:\\untrusted\\?.lua",
                "LUA_CPATH": "C:\\untrusted\\?.dll",
            }
        )
        isolated_probe = subprocess.run(
            [str(window.lua_path), "-E", "-e", "io.write('isolated')"],
            cwd=str(window.lua_path.parent),
            env=hostile_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            creationflags=window._creation_flags(),
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert isolated_probe.returncode == 0
        assert isolated_probe.stdout == "isolated"
        checks.append("private Lua ignores user startup and module-path settings")

        validation_buffer = bytearray()
        validation_dropped = extend_bounded_bytes(
            validation_buffer,
            b"x" * (VALIDATION_LOG_MAX_BYTES + 257),
            VALIDATION_LOG_MAX_BYTES,
        )
        assert len(validation_buffer) == VALIDATION_LOG_MAX_BYTES
        assert validation_dropped == 257
        checks.append("syntax-check diagnostics stay bounded")

        valid_source = output_dir / f"valid-{uuid.uuid4().hex}.lua"
        valid_source.write_text("return true\n", encoding="utf-8")
        window.set_source_file(valid_source)
        assert window.source_file == valid_source
        missing_source = output_dir / f"missing-{uuid.uuid4().hex}.lua"
        window.set_source_file(missing_source)
        assert window.source_file is None
        assert window.output_file is None
        assert window.file_path_label.text() == "Choose a file or drag it here"
        window.staged_output = missing_source
        assert window.staged_output_size() is None
        window.staged_output = None
        checks.append("invalid replacement paths clear stale source selections safely")

        oversized = "HEAD" + "x" * LOG_MESSAGE_MAX_CHARS + "TAIL"
        bounded = truncate_log_message(oversized)
        assert len(bounded) <= LOG_MESSAGE_MAX_CHARS
        assert bounded.startswith("HEAD") and bounded.endswith("TAIL")
        assert "characters truncated" in bounded

        with tempfile.TemporaryFile() as captured_stream:
            captured_stream.write(
                b"HEAD"
                + b"x"
                * (
                    CAPTURED_LOG_HEAD_BYTES
                    + CAPTURED_LOG_TAIL_BYTES
                    + 257
                )
                + b"TAIL"
            )
            captured = read_bounded_log_stream(captured_stream)
        assert captured.startswith("HEAD") and captured.endswith("TAIL")
        assert "captured bytes truncated" in captured

        window.log_box.clear()
        window.last_log_message = ""
        window.append_log("<b>literal console text</b>")
        assert window.log_box.toPlainText() == "<b>literal console text</b>"
        window.log_box.clear()
        window.last_log_message = ""
        for index in range(LOG_DOCUMENT_MAX_BLOCKS + 25):
            window.append_log(f"[bounded entry {index}]")
        document_text = window.log_box.toPlainText()
        assert window.log_box.document().blockCount() <= LOG_DOCUMENT_MAX_BLOCKS
        assert "[bounded entry 0]" not in document_text
        assert f"[bounded entry {LOG_DOCUMENT_MAX_BLOCKS + 24}]" in document_text

        window.log_box.clear()
        window.last_log_message = ""
        window.reset_process_log_capture()
        window.consume_process_log_text(
            "H" * PROCESS_LOG_HEAD_CHARS
            + "M" * (PROCESS_LOG_TAIL_CHARS + 257)
        )
        window.finalize_process_log_capture()
        process_text = window.log_box.toPlainText()
        assert "257 process output characters truncated" in process_text
        assert process_text.endswith("M" * PROCESS_LOG_TAIL_CHARS)
        checks.append("bounded logs retain useful head and tail output")
    finally:
        window.close()

    with tempfile.TemporaryDirectory(prefix="fleece-lua-stale-work-") as temp_root:
        work_root = Path(temp_root) / "work"
        work_root.mkdir()
        now = time.time()
        for index in range(WORK_CLEANUP_REMOVE_LIMIT + 2):
            stale = work_root / f"job-stale-{index:02d}"
            stale.mkdir()
            (stale / "input.lua").write_text("return true", encoding="utf-8")
            old_time = now - WORK_CLEANUP_MIN_AGE_SECONDS - 60
            os.utime(stale, (old_time, old_time))
        fresh = work_root / "job-fresh"
        fresh.mkdir()
        unrelated = work_root / "keep-me"
        unrelated.mkdir()

        removed = cleanup_stale_work_directories(work_root, current_time=now)
        assert removed == WORK_CLEANUP_REMOVE_LIMIT
        assert fresh.is_dir() and unrelated.is_dir()
        remaining_stale = list(work_root.glob("job-stale-*"))
        assert len(remaining_stale) == 2
        assert cleanup_stale_work_directories(work_root, current_time=now) == 2
        assert not list(work_root.glob("job-stale-*"))
        assert not remove_job_directory(unrelated, work_root)
        outside = Path(temp_root) / "outside"
        outside.mkdir()
        linked_job = work_root / "job-linked"
        try:
            os.symlink(outside, linked_job, target_is_directory=True)
        except (NotImplementedError, OSError):
            pass
        else:
            assert not remove_job_directory(linked_job, work_root)
            assert outside.is_dir()
    checks.append("stale work cleanup is age-, name-, and count-bounded")

    if NATIVE_KERNEL32 is not None:
        test_name = rf"Local\FleeceLuaObfuscatorSelfTest-{uuid.uuid4().hex}"
        first_status, first_handle = _try_create_named_mutex(test_name)
        try:
            second_status, second_handle = _try_create_named_mutex(test_name)
            if second_handle:
                NATIVE_KERNEL32.CloseHandle(second_handle)
            assert first_status == "acquired" and second_status == "exists"
        finally:
            if first_handle:
                NATIVE_KERNEL32.CloseHandle(first_handle)
        checks.append("a second app-instance mutex is rejected")

    marker = output_dir / "self-test-passed.txt"
    marker.write_text("\n".join(checks) + "\n", encoding="utf-8")
    print(f"Lua Obfuscator self-test passed ({len(checks)} checks).")
    return 0


def main():
    if os.name != "nt":
        show_native_setup_error("Lua Obfuscator supports 64-bit Windows only.")
        return 1

    diagnostic_mode = "--self-test" in sys.argv
    if diagnostic_mode:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    else:
        if not acquire_app_mutex():
            show_native_setup_error("Lua Obfuscator is already open.")
            return 1
        if SETUP_LOCK_DIR.is_dir():
            show_native_setup_error(
                "Lua Obfuscator setup is currently running.\n\n"
                "Let Installer.bat finish, then open the app again."
            )
            return 1

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "fleece.lua-obfuscator"
        )
    except (AttributeError, OSError):
        pass

    app = QApplication(sys.argv)
    app.setApplicationVersion(APP_VERSION)
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName("Fleece")
    app.setStyle("Fusion")
    sys.excepthook = handle_unhandled_exception

    if diagnostic_mode:
        index = sys.argv.index("--self-test")
        output = (
            sys.argv[index + 1]
            if index + 1 < len(sys.argv)
            else RUNTIME_DIR / "self-test"
        )
        try:
            return run_self_test(output)
        except Exception:
            traceback.print_exc()
            return 1

    window = LuaObfuscator()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
