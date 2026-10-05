"""Shell-out helpers.

Every command string runs through the user's login shell (`bash -lc`), the
Linux counterpart of the macOS app's `zsh -lc`. Health probes and actions run
in their own process group so a timeout can kill the whole tree.
"""
import os
import signal
import subprocess
import time

from .config import logs_directory


def _popen(cmd):
    return subprocess.Popen(
        ["/bin/bash", "-lc", cmd],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True)


def _collect(p, timeout):
    """communicate() with a hard kill of the whole process group on timeout."""
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, (out or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            out, _ = p.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            out = b""
        return -9, (out or b"").decode("utf-8", "replace")


def run(cmd, wait=True):
    """Fire-and-forget (used for mutex-group stops, like the macOS app)."""
    try:
        p = _popen(cmd)
    except OSError:
        return
    if wait:
        p.wait()


def run_captured(cmd, timeout=5.0):
    """Returns (exit, output); used for modeGet."""
    try:
        p = _popen(cmd)
    except OSError:
        return -1, ""
    return _collect(p, timeout)


def run_logged(cmd, timeout=5.0):
    """Run and append to the health log; returns the exit code."""
    try:
        p = _popen(cmd)
    except OSError:
        return -1
    exit_code, out = _collect(p, timeout)
    line = (f"[{int(time.time())}] exit={exit_code} "
            f"args=/bin/bash -lc {cmd} out={out[:2000]}\n")
    append_to_log(logs_directory() + "/hummin-menubar-health.log", line)
    return exit_code


def append_to_log(path, text):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
