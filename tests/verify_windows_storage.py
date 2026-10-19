"""Reproduce a transient Windows reader lock during atomic result replacement."""
import ctypes
from ctypes import wintypes
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mock_cli", PACKAGE / "mock/cli.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


@unittest.skipUnless(os.name == "nt", "Real Windows file-sharing contract")
class ReaderLock(unittest.TestCase):
    def test_reader_releases_replace_lock_without_losing_result(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        (PACKAGE / "work").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="reader-lock-", dir=PACKAGE / "work") as tmp:
            target = Path(tmp) / "result.json"
            cli.write(target, {"old": True})
            # Share reads/writes, but withhold FILE_SHARE_DELETE just as a reader can.
            handle = kernel.CreateFileW(str(target), 0x80000000, 0x1 | 0x2, None, 3, 0, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
            probe = Path(tmp) / "probe.json"
            probe.write_text("{}", encoding="utf-8")
            try:
                with self.assertRaises(PermissionError):
                    os.replace(probe, target)
            except BaseException:
                kernel.CloseHandle(handle)
                raise
            finally:
                probe.unlink(missing_ok=True)
            timer = threading.Timer(.15, lambda: kernel.CloseHandle(handle))
            timer.start()
            try:
                cli.write(target, {"한글": "새 평가 결과", "complete": True})
            finally:
                timer.join()
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"한글": "새 평가 결과", "complete": True})
            self.assertEqual(list(Path(tmp).iterdir()), [target])


if __name__ == "__main__":
    unittest.main()
