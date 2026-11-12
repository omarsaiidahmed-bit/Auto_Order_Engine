"""Desktop launcher for the packaged Auto-Order app.

The frozen executable is built with ``--noconsole``, so this module is the
whole user interface of the installation:

1. it starts Streamlit **in this same process**, bound to ``127.0.0.1`` only,
2. a background thread waits until the server answers ``/_stcore/health``,
3. that thread then opens the default browser on the app,
4. the process keeps serving the app until it is stopped.

Double-clicking the shortcut again does not start a second server: if the app
is already answering it just raises the browser again.  ``AutoOrder.exe --stop``
shuts the running instance down (the uninstaller uses it), and
``AutoOrder.exe --selftest`` checks that the bundled runtime is complete.

Everything here is standard library, so the launcher itself cannot fail on a
missing third-party package; only :mod:`streamlit.web.cli` is imported, and the
frozen build always carries it.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

APP_NAME = "AutoOrder"
HOST = "127.0.0.1"
DEFAULT_PORT = 8501
HEALTH_PATH = "/_stcore/health"
#: How long the browser waits for Streamlit to boot before we call it a failure.
STARTUP_TIMEOUT = 90.0

#: Named Windows event used by ``--stop``.  The kernel deletes it with the last
#: handle, so it can never go stale or point at a recycled process id.
STOP_EVENT_NAME = "Local\\AutoOrder.Stop"
EVENT_MODIFY_STATE = 0x0002
INFINITE = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Paths and diagnostics
# ---------------------------------------------------------------------------
def app_data_dir() -> Path:
    """Per-user folder for the log and the pid file (always writable)."""
    base = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("APPDATA")
        or os.environ.get("TEMP")
        or str(Path.home())
    )
    folder = Path(base) / APP_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def bundle_dir() -> Path:
    """Folder that carries ``app.py`` -- ``sys._MEIPASS`` once frozen."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def log_path() -> Path:
    """Where everything Streamlit writes ends up when there is no console."""
    return app_data_dir() / "launcher.log"


def attach_log() -> None:
    """Give the windowed build somewhere to write.

    A ``--noconsole`` executable has ``sys.stdout``/``sys.stderr`` set to
    ``None``; Streamlit logs to them on every request, so without this redirect
    the first log line would raise.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return

    stream = open(log_path(), "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def show_error(message: str) -> None:
    """Show a blocking message box -- there is no console to print to."""
    print(message, file=sys.stderr)
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    except Exception:  # noqa: BLE001 - not Windows, or no GUI available
        pass


# ---------------------------------------------------------------------------
# Server helpers
# ---------------------------------------------------------------------------
def base_url(port: int) -> str:
    """Address of the app on the loopback interface."""
    return f"http://{HOST}:{port}"


def health_url(port: int) -> str:
    """Streamlit's readiness probe."""
    return base_url(port) + HEALTH_PATH


def open_browser(url: str) -> None:
    """Open the default browser (skipped when ``AUTOORDER_NO_BROWSER`` is set)."""
    if os.environ.get("AUTOORDER_NO_BROWSER", "").strip().lower() in {"1", "true", "yes"}:
        print(f"AUTOORDER_NO_BROWSER is set, not opening {url}", file=sys.stderr)
        return
    webbrowser.open(url)


def is_running(port: int) -> bool:
    """True when a Streamlit server answers on ``port``."""
    try:
        with urlopen(health_url(port), timeout=1.0) as response:
            return response.status == 200 and response.read().strip() == b"ok"
    except (URLError, OSError, ValueError):
        return False


def free_port(preferred: int) -> int:
    """Return ``preferred`` when it is free, otherwise any free port."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return sock.getsockname()[1]
    raise RuntimeError("no free TCP port is available")


def pid_path() -> Path:
    """Location of the instance record used by ``--stop``."""
    return app_data_dir() / f"{APP_NAME.lower()}.pid"


def write_pid(port: int) -> None:
    """Record the port so a second launch can find the running app."""
    pid_path().write_text(
        json.dumps({"pid": os.getpid(), "port": port}),
        encoding="utf-8",
    )


def running_port() -> int | None:
    """Port of an instance started earlier, if it is still answering."""
    candidates: list[int] = []
    try:
        record = json.loads(pid_path().read_text(encoding="utf-8"))
        candidates.append(int(record["port"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    candidates.append(DEFAULT_PORT)

    for port in candidates:
        if is_running(port):
            return port
    return None


def stop_running_instance() -> int:
    """Ask the running instance to exit and wait until it stops answering."""
    if not request_stop():
        # Nothing is running (or we are not on Windows): just drop a stale record.
        pid_path().unlink(missing_ok=True)
        return 0

    try:
        port = int(json.loads(pid_path().read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        port = DEFAULT_PORT

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline and is_running(port):
        time.sleep(0.2)
    pid_path().unlink(missing_ok=True)
    return 0


def _load_kernel32():
    """Load ``kernel32`` with the prototypes the stop event needs."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateEventW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def start_stop_watcher() -> None:
    """Exit as soon as another process signals the stop event.

    ``AutoOrder.exe --stop`` (used by the uninstaller) sets the event; the
    watcher then ends the process immediately.  Doing this through a named
    kernel object means ``--stop`` also works while Streamlit is still booting,
    and a crashed run leaves nothing behind that could kill an unrelated
    process later.
    """
    if os.name != "nt":
        return

    kernel32 = _load_kernel32()
    handle = kernel32.CreateEventW(None, True, False, STOP_EVENT_NAME)
    if not handle:
        print("could not create the stop event", file=sys.stderr)
        return

    def watch() -> None:
        kernel32.WaitForSingleObject(handle, INFINITE)
        os._exit(0)

    threading.Thread(target=watch, name="stop-watcher", daemon=True).start()


def request_stop() -> bool:
    """Signal a running instance to exit; ``False`` when none is running."""
    if os.name != "nt":
        return False

    kernel32 = _load_kernel32()
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, STOP_EVENT_NAME)
    if not handle:
        return False
    try:
        kernel32.SetEvent(handle)
    finally:
        kernel32.CloseHandle(handle)
    return True


def streamlit_args(script: Path, port: int) -> list[str]:
    """Command line handed to Streamlit's own CLI.

    The theme is repeated here because the frozen bundle cannot see the
    project's ``.streamlit/config.toml``; keeping the values in one place per
    build is intentional.
    """
    return [
        "streamlit",
        "run",
        str(script),
        f"--server.port={port}",
        f"--server.address={HOST}",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--server.maxUploadSize=200",
        "--browser.gatherUsageStats=false",
        "--global.developmentMode=false",
        "--client.toolbarMode=minimal",
        "--theme.base=light",
        "--theme.primaryColor=#4A7BA7",
        "--theme.backgroundColor=#F4F7FB",
        "--theme.secondaryBackgroundColor=#EAF1F8",
        "--theme.textColor=#1F2937",
    ]


def wait_until_ready(port: int) -> bool:
    """Poll the health endpoint until the app answers or we give up."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if is_running(port):
            return True
        time.sleep(0.25)
    return False


# ---------------------------------------------------------------------------
# Frozen build self-test
# ---------------------------------------------------------------------------
def _selftest() -> int:
    """Check that the frozen runtime carries everything the app needs.

    Useful after building the installer: ``AutoOrder.exe --selftest`` returns
    0 when the bundled Python can import the whole ``core`` package and can
    write and read an ``.xlsx`` file, and writes the details to the log.
    """
    passed: list[str] = []
    failed: list[str] = []

    def check(name: str, func) -> None:
        try:
            detail = func()
        except BaseException as exc:  # noqa: BLE001 - report, never crash
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
        else:
            passed.append(f"{name}: {detail}")

    def require(path: Path) -> str:
        if not path.is_file():
            raise FileNotFoundError(path)
        return f"{path.stat().st_size:,} bytes"

    check("bundle", lambda: str(bundle_dir()))
    for relative in (
        "app.py",
        "app_config.py",
        "company_logo.png",
        "core/__init__.py",
    ):
        check(f"file {relative}", lambda p=bundle_dir() / relative: require(p))

    check("pandas", lambda: __import__("pandas").__version__)
    check("numpy", lambda: __import__("numpy").__version__)
    check("openpyxl", lambda: __import__("openpyxl").__version__)
    check("xlsxwriter", lambda: __import__("xlsxwriter").__version__)
    check("pyarrow", lambda: __import__("pyarrow").__version__)

    def import_core() -> str:
        from core import (  # noqa: F401 - imported for the side effect
            aggregation,
            audit,
            demand,
            exporter,
            ingestion,
            merges,
            normalize,
            notes,
            quantity,
            substitutes,
            supply_chain,
        )

        return "11 modules"

    def excel_roundtrip() -> str:
        import tempfile

        import pandas as pd

        frame = pd.DataFrame({"كود": [1, 2], "الاسم": ["أ", "ب"]})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "probe.xlsx"
            frame.to_excel(path, index=False)
            back = pd.read_excel(path)
        if len(back) != len(frame):
            raise AssertionError(f"read back {len(back)} of {len(frame)} rows")
        return "xlsx write + read ok"

    check("core package", import_core)
    check("excel", excel_roundtrip)

    def app_script() -> str:
        """Run the real app script inside the frozen runtime (no browser)."""
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(bundle_dir() / "app.py"), default_timeout=300)
        at.run()
        if at.exception:
            first = at.exception[0]
            raise AssertionError(f"{len(at.exception)} exception(s), first: {first.value}")
        return f"app.py rendered, {len(at.markdown)} markdown blocks"

    check("app script", app_script)

    for line in passed:
        print(line)
    for line in failed:
        print(f"FAILED {line}")
    if failed:
        print(f"SELFTEST FAILED ({len(failed)} problem(s))")
        return 1
    print(f"SELFTEST OK ({len(passed)} checks)")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """Start the server, open the browser and then serve until stopped."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    attach_log()

    if "--stop" in arguments:
        return stop_running_instance()
    if "--selftest" in arguments:
        return _selftest()

    script = bundle_dir() / "app.py"
    if not script.is_file():
        show_error(f"app.py is missing next to the launcher:\n{script}")
        return 2

    # ``core`` and ``app_config`` are shipped as plain folders beside app.py.
    if str(script.parent) not in sys.path:
        sys.path.insert(0, str(script.parent))

    existing = running_port()
    if existing is not None:
        # Already open from an earlier double-click: just show it again.
        open_browser(base_url(existing))
        return 0

    # Let ``--stop`` reach us from the moment we own a port, even while
    # Streamlit is still starting up.
    start_stop_watcher()
    port = free_port(DEFAULT_PORT)

    def open_when_ready() -> None:
        if not wait_until_ready(port):
            show_error(
                f"{APP_NAME} did not answer on {base_url(port)} after "
                f"{STARTUP_TIMEOUT:.0f}s.\n\nLog: {log_path()}"
            )
            return
        write_pid(port)
        open_browser(base_url(port))

    opener = threading.Thread(target=open_when_ready, name="browser-opener", daemon=True)
    opener.start()

    # Streamlit has to own the main thread: its bootstrap installs signal
    # handlers, which Python only allows on the main thread.
    try:
        from streamlit.web import cli as stcli

        sys.argv = streamlit_args(script, port)
        stcli.main()
    except SystemExit:
        pass
    except BaseException as exc:  # noqa: BLE001 - the log is the only trace
        traceback.print_exc()
        show_error(
            f"{APP_NAME} could not start.\n\n{type(exc).__name__}: {exc}\n\nLog: {log_path()}"
        )
        return 1
    finally:
        pid_path().unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
