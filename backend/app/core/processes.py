"""Windows process-tree ownership established atomically by CreateProcess.

Job objects are lifecycle/resource controls, not an OS security sandbox.
Unsupported platforms fail closed until an equivalent supervisor is verified.
"""

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import ROOT


class ProcessGuardError(RuntimeError):
    pass


class ProcessTimeout(ProcessGuardError):
    pass


class ProcessOutputLimit(ProcessGuardError):
    pass


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def process_environment(temporary, extra=None):
    """No database, storage, mail, journal or control credentials by inheritance."""
    temporary = Path(temporary).resolve()
    if not temporary.is_relative_to(ROOT):
        raise ValueError("PROCESS_TEMP_MUST_BE_PROJECT_LOCAL")
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "COMSPEC", "PATHEXT", "LANG", "LC_ALL", "TZ"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(TEMP=str(temporary), TMP=str(temporary), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    env.update(extra or {})
    return env


def run_contained(
    arguments, *, cwd, env, timeout, output_limit=32 * 1024 * 1024, memory_limit=None, on_started=None
):
    """Capture bounded output; kill all descendants on timeout, exit or parent death.

    Secrets belong in an explicit environment, never in arguments or exceptions.
    on_started is an internal lifecycle observer, not a shell/command hook.
    """
    if os.name != "nt":
        raise ProcessGuardError("PROCESS_CONTAINMENT_PLATFORM_NOT_VERIFIED")
    executable, cwd = Path(arguments[0]).resolve(), Path(cwd).resolve()
    if not executable.is_relative_to(ROOT) or not cwd.is_relative_to(ROOT):
        raise ValueError("PROCESS_PATH_MUST_BE_PROJECT_LOCAL")
    if timeout <= 0 or output_limit <= 0:
        raise ValueError("PROCESS_LIMIT_INVALID")
    if any("\0" in key or "=" in key or "\0" in str(value) for key, value in env.items()):
        raise ValueError("PROCESS_ENVIRONMENT_INVALID")
    return _windows_run(
        [str(executable), *map(str, arguments[1:])], cwd, env, timeout, output_limit, memory_limit, on_started
    )


def _windows_run(arguments, cwd, env, timeout, output_limit, memory_limit, on_started):
    import ctypes
    import msvcrt
    from ctypes import wintypes as w

    import win32job

    class StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", w.DWORD),
            ("lpReserved", w.LPWSTR),
            ("lpDesktop", w.LPWSTR),
            ("lpTitle", w.LPWSTR),
            ("dwX", w.DWORD),
            ("dwY", w.DWORD),
            ("dwXSize", w.DWORD),
            ("dwYSize", w.DWORD),
            ("dwXCountChars", w.DWORD),
            ("dwYCountChars", w.DWORD),
            ("dwFillAttribute", w.DWORD),
            ("dwFlags", w.DWORD),
            ("wShowWindow", w.WORD),
            ("cbReserved2", w.WORD),
            ("lpReserved2", ctypes.POINTER(w.BYTE)),
            ("hStdInput", w.HANDLE),
            ("hStdOutput", w.HANDLE),
            ("hStdError", w.HANDLE),
        ]

    class StartupInfoEx(ctypes.Structure):
        _fields_ = [("StartupInfo", StartupInfo), ("lpAttributeList", w.LPVOID)]

    class ProcessInfo(ctypes.Structure):
        _fields_ = [
            ("hProcess", w.HANDLE),
            ("hThread", w.HANDLE),
            ("dwProcessId", w.DWORD),
            ("dwThreadId", w.DWORD),
        ]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.InitializeProcThreadAttributeList.argtypes = [
        w.LPVOID,
        w.DWORD,
        w.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    api.InitializeProcThreadAttributeList.restype = w.BOOL
    api.UpdateProcThreadAttribute.argtypes = [
        w.LPVOID,
        w.DWORD,
        ctypes.c_size_t,
        w.LPVOID,
        ctypes.c_size_t,
        w.LPVOID,
        w.LPVOID,
    ]
    api.UpdateProcThreadAttribute.restype = w.BOOL
    api.DeleteProcThreadAttributeList.argtypes = [w.LPVOID]
    api.CreateProcessW.argtypes = [
        w.LPCWSTR,
        w.LPWSTR,
        w.LPVOID,
        w.LPVOID,
        w.BOOL,
        w.DWORD,
        w.LPVOID,
        w.LPCWSTR,
        w.LPVOID,
        w.LPVOID,
    ]
    api.CreateProcessW.restype = w.BOOL
    api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    api.WaitForSingleObject.restype = w.DWORD
    api.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    api.GetExitCodeProcess.restype = w.BOOL
    api.CloseHandle.argtypes = [w.HANDLE]
    api.CloseHandle.restype = w.BOOL

    job = win32job.CreateJobObject(None, "")
    limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    limits["BasicLimitInformation"]["LimitFlags"] = (
        win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    )
    limits["BasicLimitInformation"]["ActiveProcessLimit"] = 8
    if memory_limit:
        limits["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY | win32job.JOB_OBJECT_LIMIT_JOB_MEMORY
        )
        limits["ProcessMemoryLimit"] = limits["JobMemoryLimit"] = memory_limit

    owned, readers = set(), []
    buffers, overflow, io_error = [bytearray(), bytearray()], threading.Event(), threading.Event()
    attribute_initialized, attributes, process = False, None, ProcessInfo()
    exit_code = w.DWORD()

    def close_fd(fd):
        if fd in owned:
            owned.remove(fd)
            os.close(fd)

    def drain(fd, index):
        try:
            while chunk := os.read(fd, 65536):
                room = max(0, output_limit - len(buffers[index]))
                buffers[index].extend(chunk[:room])
                if len(chunk) > room:
                    overflow.set()
        except OSError:
            io_error.set()
        finally:
            os.close(fd)

    try:
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        # The job handle itself must never be inherited: its final owner is this parent.
        os.set_handle_inheritable(int(job), False)
        out_read, out_write = os.pipe()
        owned.update((out_read, out_write))
        err_read, err_write = os.pipe()
        owned.update((err_read, err_write))
        null_input = os.open(os.devnull, os.O_RDONLY | os.O_BINARY)
        owned.add(null_input)
        handles = [msvcrt.get_osfhandle(fd) for fd in (null_input, out_write, err_write)]
        for handle in handles:
            os.set_handle_inheritable(handle, True)
        inherited = (w.HANDLE * len(handles))(*handles)
        job_list = (w.HANDLE * 1)(int(job))
        size = ctypes.c_size_t()
        api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        if not size.value:
            raise ProcessGuardError("PROCESS_ATTRIBUTE_SIZE_FAILED")
        attributes = ctypes.create_string_buffer(size.value)
        if not api.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)):
            raise ProcessGuardError("PROCESS_ATTRIBUTE_INIT_FAILED")
        attribute_initialized = True
        # Public Win32 attribute values: HANDLE_LIST and JOB_LIST, respectively.
        for key, value in ((0x20002, inherited), (0x2000D, job_list)):
            if not api.UpdateProcThreadAttribute(attributes, 0, key, value, ctypes.sizeof(value), None, None):
                raise ProcessGuardError("PROCESS_ATTRIBUTE_UPDATE_FAILED")
        startup = StartupInfoEx()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.StartupInfo.dwFlags = 0x100 | 0x1  # USESTDHANDLES, USESHOWWINDOW (hidden)
        startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = handles
        startup.lpAttributeList = ctypes.addressof(attributes)
        block = (
            "\0".join(
                f"{key}={value}" for key, value in sorted(env.items(), key=lambda item: item[0].upper())
            )
            + "\0\0"
        )
        environment = ctypes.create_unicode_buffer(block)
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(arguments))
        flags = 0x80000 | 0x400 | 0x08000000  # extended startup, Unicode environment, no window
        if not api.CreateProcessW(
            arguments[0],
            command,
            None,
            None,
            True,
            flags,
            environment,
            str(cwd),
            ctypes.byref(startup),
            ctypes.byref(process),
        ):
            raise ProcessGuardError(f"PROCESS_START_FAILED_{ctypes.get_last_error()}")
        for fd in (null_input, out_write, err_write):
            close_fd(fd)
        if on_started:
            on_started(process.dwProcessId)
        for index, fd in enumerate((out_read, err_read)):
            thread = threading.Thread(target=drain, args=(fd, index), daemon=True)
            thread.start()
            owned.remove(fd)  # The reader thread exclusively closes this descriptor.
            readers.append(thread)
        deadline = time.monotonic() + timeout
        while True:
            if overflow.is_set():
                raise ProcessOutputLimit("PROCESS_OUTPUT_LIMIT")
            if time.monotonic() >= deadline:
                raise ProcessTimeout("PROCESS_TIMEOUT")
            state = api.WaitForSingleObject(process.hProcess, 25)
            if state == 0:
                break
            if state != 258:
                raise ProcessGuardError("PROCESS_WAIT_FAILED")
        if not api.GetExitCodeProcess(process.hProcess, ctypes.byref(exit_code)):
            raise ProcessGuardError("PROCESS_EXIT_STATUS_FAILED")
    finally:
        # Also kills descendants that outlive a normally completed primary process.
        job.Close()
        if process.hProcess:
            api.WaitForSingleObject(process.hProcess, 5000)
            api.CloseHandle(process.hProcess)
        if process.hThread:
            api.CloseHandle(process.hThread)
        if attribute_initialized:
            api.DeleteProcThreadAttributeList(attributes)
        for fd in tuple(owned):
            close_fd(fd)
        for thread in readers:
            thread.join(timeout=5)
    if overflow.is_set():
        raise ProcessOutputLimit("PROCESS_OUTPUT_LIMIT")
    if io_error.is_set() or any(thread.is_alive() for thread in readers):
        raise ProcessGuardError("PROCESS_PIPE_DRAIN_FAILED")
    return ProcessResult(exit_code.value, bytes(buffers[0]), bytes(buffers[1]))
