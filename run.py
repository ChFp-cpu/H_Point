import asyncio
import hashlib
import os
import threading
from pathlib import Path
from dotenv import load_dotenv

# The local .env is the project's source of runtime settings.  In particular,
# it must win over stale Windows user variables such as WEB_PUBLIC_URL=0.0.0.0.
load_dotenv(override=True)

class SingleInstance:
    """Keep exactly one Telegram polling process per project directory."""

    def __init__(self, identity="hpoint"):
        # The command can be invoked from any PowerShell folder.  The project
        # directory is the only stable identity for this installation.
        project = str(Path(__file__).resolve().parent).encode("utf-8")
        self._name = f"{identity}-{hashlib.sha256(project).hexdigest()[:16]}"
        self._handle = None
        self._file = None

    def acquire(self):
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_mutex = kernel32.CreateMutexW
            create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
            create_mutex.restype = wintypes.HANDLE
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle.restype = wintypes.BOOL

            handle = create_mutex(None, False, f"Local\\{self._name}")
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                close_handle(handle)
                return False
            self._handle = handle

            # A file-region lock is a second, independent process barrier.
            # It prevents duplicate polling even if a shell launches this
            # script with a different working directory or mutex handling is
            # altered by an embedding environment.
            import msvcrt
            lock_path = Path(__file__).resolve().parent / f".{self._name}.lock"
            self._file = lock_path.open("a+b")
            if self._file.tell() == 0:
                self._file.write(b"0")
                self._file.flush()
            self._file.seek(0)
            try:
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self._file.close()
                self._file = None
                close_handle(self._handle)
                self._handle = None
                return False
            return True

        import fcntl

        lock_path = Path(__file__).resolve().parent / f".{self._name}.lock"
        self._file = lock_path.open("a+")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._file.close()
            self._file = None
            return False
        return True

    def release(self):
        if self._file is not None:
            if os.name == "nt":
                import msvcrt
                self._file.seek(0)
                try:
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            self._file.close()
            self._file = None
        if self._handle is not None:
            import ctypes
            from ctypes import wintypes
            close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle.restype = wintypes.BOOL
            close_handle(self._handle)
            self._handle = None


def stop_server(server, thread):
    if server is not None:
        server.shutdown()
    if thread is not None:
        thread.join(timeout=5)
    if server is not None:
        server.server_close()


def run_with_bot(web, bot_main):
    """Run the legacy all-in-one local mode: website plus polling."""
    server = None
    thread = None
    try:
        # Bind before polling so an unavailable web port fails startup clearly
        # instead of leaving the Telegram bot running without its website.
        server = web.create_server()
        thread = threading.Thread(target=server.serve_forever, name="hpoint-web")
        thread.start()
        print("H-Point started")
        print(f"Website: {os.getenv('WEB_PUBLIC_URL','http://127.0.0.1:8080')}")
        print("Telegram bot: polling")
        asyncio.run(bot_main())
    finally:
        stop_server(server, thread)


async def run_website_only(web, bot_token, bot_username):
    """Run the website without getUpdates; an optional bot client sends notices."""
    server = None
    thread = None
    notifier = None
    try:
        if bot_token:
            from aiogram import Bot
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode

            notifier = Bot(
                token=bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            # This client only sends messages. It never calls getUpdates, so a
            # separately started run_bot.py can own Telegram polling.
            web.configure_telegram_notifications(notifier, bot_username or None)

        server = web.create_server()
        thread = threading.Thread(target=server.serve_forever, name="hpoint-web")
        thread.start()
        print("H-Point website started")
        print(f"Website: {os.getenv('WEB_PUBLIC_URL','http://127.0.0.1:8080')}")
        print("Telegram bot: disabled in this process (start python run_bot.py separately)")
        await asyncio.Event().wait()
    finally:
        stop_server(server, thread)
        if notifier is not None:
            await notifier.session.close()


def main():
    # Import after dotenv and before hpoint.web: that module opens the database
    # during import, so production configuration must be validated first.
    from hpoint.config import BOT_TOKEN, BOT_USERNAME, RUN_TELEGRAM_BOT, validate_production_config

    try:
        validate_production_config()
        from hpoint import web

        if not RUN_TELEGRAM_BOT:
            asyncio.run(run_website_only(web, BOT_TOKEN, BOT_USERNAME))
            return 0

        if not BOT_TOKEN:
            print("ERROR: BOT_TOKEN is not set. Set it in .env before starting Telegram polling.")
            return 1

        instance = SingleInstance()
        if not instance.acquire():
            print("Telegram polling is already running in this project folder. Close the other run.py or run_bot.py window first.")
            return 2
        try:
            from hpoint.main import main as bot_main
            run_with_bot(web, bot_main)
        finally:
            instance.release()
    except KeyboardInterrupt:
        pass
    finally:
        print("H-Point stopped")

    return 0

if __name__=="__main__":
    raise SystemExit(main())
