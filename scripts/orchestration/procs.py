"""開発機のプロセス一覧（pid・親pid・実行ファイル名・コマンドライン）。

ロックの破棄の記録（scripts/lockrun.py）と定期確認（core.py）が使う。飽和した機械へプロセスを
足さないため、外部コマンドを起こさずにOSから直接読む。取れないOSではNoneを返す。
"""

import os
from dataclasses import dataclass


@dataclass
class Proc:
    pid: int
    ppid: int
    name: str
    cmdline: str | None


def processes() -> dict[int, Proc] | None:
    try:
        if os.name == "nt":
            return _windows()
        if os.path.isdir("/proc"):
            return _linux()
    except OSError:
        return None
    return None


def ancestors(procs: dict[int, Proc], pid: int) -> list[Proc]:
    out, seen = [], {pid}
    p = procs.get(pid)
    while p is not None and p.ppid not in seen:
        seen.add(p.ppid)
        p = procs.get(p.ppid)
        if p is not None:
            out.append(p)
    return out


def _linux() -> dict[int, Proc]:
    out = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8", errors="replace") as f:
                stat = f.read()
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                raw = f.read()
        except OSError:
            continue
        # 2番目の欄（実行ファイル名）は括弧で囲まれ、空白や括弧を含みうる。
        name = stat[stat.index("(") + 1:stat.rindex(")")]
        ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        cmdline = raw.replace(b"\0", b" ").decode("utf-8", "replace").strip() or None
        out[int(entry)] = Proc(int(entry), ppid, name, cmdline)
    return out


def _windows() -> dict[int, Proc]:
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.Process32FirstW.argtypes = kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (None, wintypes.HANDLE(-1).value):
        raise OSError("CreateToolhelp32Snapshotに失敗")
    out = {}
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            pid = entry.th32ProcessID
            out[pid] = Proc(pid, entry.th32ParentProcessID, entry.szExeFile, _windows_cmdline(kernel32, pid))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return out


def _windows_cmdline(kernel32, pid: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]

    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtQueryInformationProcess.argtypes = [
            wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        size = wintypes.ULONG(0)
        # 60 = ProcessCommandLineInformation。1回目で必要な大きさを受け取る。
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(size))
        if size.value == 0:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if ntdll.NtQueryInformationProcess(handle, 60, buf, size, ctypes.byref(size)) != 0:
            return None
        us = UnicodeString.from_buffer(buf)
        return ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer else None
    finally:
        kernel32.CloseHandle(handle)
