"""Lifetime management for trusted local analysis process trees.

Windows children enter a kill-on-close Job Object before their first instruction.
POSIX children enter a new session/process group. These are lifetime controls,
not a security boundary: remote services and deliberately detached POSIX jobs
require adapter-specific cancellation.
"""
from contextlib import contextmanager
import os
import signal
import subprocess
import time

from .io import ClosureError


class _WindowsJob:
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c = c
        self.api = c.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([c.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Thread32First": ([w.HANDLE, c.c_void_p], w.BOOL),
            "Thread32Next": ([w.HANDLE, c.c_void_p], w.BOOL),
            "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "ResumeThread": ([w.HANDLE], w.DWORD),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result

        class BasicLimits(c.Structure):
            _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64),
                        ("flags", w.DWORD), ("min_working_set", c.c_size_t),
                        ("max_working_set", c.c_size_t), ("active_limit", w.DWORD),
                        ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class ExtendedLimits(c.Structure):
            _fields_ = [("basic", BasicLimits), ("io_counters", c.c_uint64 * 6),
                        ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                        ("peak_process_memory", c.c_size_t), ("peak_job_memory", c.c_size_t)]

        class Accounting(c.Structure):
            _fields_ = [("user_time", c.c_int64), ("kernel_time", c.c_int64),
                        ("period_user_time", c.c_int64), ("period_kernel_time", c.c_int64),
                        ("page_faults", w.DWORD), ("total", w.DWORD),
                        ("active", w.DWORD), ("terminated", w.DWORD)]

        class ThreadEntry(c.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("thread", w.DWORD),
                        ("process", w.DWORD), ("base_priority", w.LONG),
                        ("delta_priority", w.LONG), ("flags", w.DWORD)]

        self.Accounting, self.ThreadEntry = Accounting, ThreadEntry
        self.handle = self._check(self.api.CreateJobObjectW(None, None))
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            self._check(self.api.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)))
        except BaseException:
            self.api.CloseHandle(self.handle)
            self.handle = None
            raise

    def _check(self, value):
        if not value:
            raise self.c.WinError(self.c.get_last_error())
        return value

    def attach_and_resume(self, process):
        c, api = self.c, self.api
        handle = self._check(api.OpenProcess(0x0101, False, process.pid))  # SET_QUOTA | TERMINATE
        try:
            self._check(api.AssignProcessToJobObject(self.handle, handle))
        finally:
            api.CloseHandle(handle)
        # Popen closes its primary-thread handle. Enumerate only the freshly
        # created suspended process; it has not executed or spawned other threads.
        snapshot = api.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        matches = []
        try:
            entry = self.ThreadEntry()
            entry.size = c.sizeof(entry)
            present = api.Thread32First(snapshot, c.byref(entry))
            while present:
                if entry.process == process.pid:
                    matches.append(entry.thread)
                entry.size = c.sizeof(entry)
                present = api.Thread32Next(snapshot, c.byref(entry))
        finally:
            api.CloseHandle(snapshot)
        if len(matches) != 1:
            raise OSError("Cannot identify the suspended analysis's initial thread")
        thread = self._check(api.OpenThread(0x0002, False, matches[0]))  # THREAD_SUSPEND_RESUME
        try:
            if api.ResumeThread(thread) == 0xFFFFFFFF:
                raise c.WinError(c.get_last_error())
        finally:
            api.CloseHandle(thread)

    def close(self):
        if self.handle is None:
            return
        handles = []
        try:
            # Job accounting reaches zero before all terminating processes have
            # released inherited file handles. Hold waitable handles as well.
            capacity = 64
            while True:
                buffer = self.c.create_string_buffer(8 + capacity * self.c.sizeof(self.c.c_size_t))
                if self.api.QueryInformationJobObject(self.handle, 3, buffer, len(buffer), None):
                    count = self.c.c_uint32.from_buffer(buffer, 4).value
                    for index in range(count):
                        pid = self.c.c_size_t.from_buffer(buffer, 8 + index*self.c.sizeof(self.c.c_size_t)).value
                        handle = self.api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
                        if handle:
                            handles.append(handle)
                        elif self.c.get_last_error() != 87:  # Process already exited.
                            raise self.c.WinError(self.c.get_last_error())
                    break
                if self.c.get_last_error() != 234 or capacity >= 65536:  # ERROR_MORE_DATA
                    raise self.c.WinError(self.c.get_last_error())
                capacity *= 2
            self._check(self.api.TerminateJobObject(self.handle, 1))
            deadline = time.monotonic() + 5
            while True:
                accounting = self.Accounting()
                self._check(self.api.QueryInformationJobObject(
                    self.handle, 1, self.c.byref(accounting), self.c.sizeof(accounting), None))
                if not accounting.active:
                    break
                if time.monotonic() >= deadline:
                    raise OSError("Analysis process tree did not terminate within cleanup deadline")
                time.sleep(0.01)
            for handle in handles:
                remaining = max(0, int((deadline-time.monotonic())*1000))
                if self.api.WaitForSingleObject(handle, remaining) != 0:
                    raise OSError("Analysis descendant did not release its resources within cleanup deadline")
        finally:
            for handle in handles:
                self.api.CloseHandle(handle)
            self.api.CloseHandle(self.handle)
            self.handle = None


@contextmanager
def managed_process(command, **kwargs):
    process, job = None, None
    try:
        try:
            if os.name == "nt":
                job = _WindowsJob()
                process = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW | 0x00000004,
                                           **kwargs)  # CREATE_SUSPENDED
                job.attach_and_resume(process)
            else:
                process = subprocess.Popen(command, start_new_session=True, **kwargs)
        except OSError as exc:
            raise ClosureError(f"Cannot establish analysis process lifetime controls: {exc}", "RUN_SETUP") from exc
        yield process
    finally:
        try:
            if job:
                job.close()
            elif process:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except OSError as exc:
            raise ClosureError(f"Analysis process cleanup failed: {exc}", "RUN_CLEANUP") from exc
        finally:
            if process:
                # Also covers a suspended child whose job assignment failed.
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired as exc:
                    raise ClosureError("Analysis wrapper did not terminate within cleanup deadline", "RUN_CLEANUP") from exc
