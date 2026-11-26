"""Windows long-path support for the deep PBIR directory tree.

PBIR nests a report as::

    <out>/<project>/<project>.Report/definition/pages/<page>/visuals/<20-hex-id>/visual.json

That is roughly 110 characters of structure before the output directory is
counted, and page names come from Tableau dashboard titles. On Windows, unless
the machine has ``LongPathsEnabled`` set in the registry, the Win32 API caps a
path at 260 characters (``MAX_PATH``) and generation dies partway through with::

    [WinError 206] The filename or extension is too long

Prefixing an absolute path with ``\\\\?\\`` opts that single call out of the
``MAX_PATH`` limit, raising it to roughly 32,767 characters. The prefix is
applied only at the syscall boundary and only when a path is long enough to be
at risk, so ordinary runs behave exactly as before and the paths stored in
variables, reports and logs stay readable.

Use :func:`makedirs` and :func:`lp_open` in place of ``os.makedirs`` and
``open`` anywhere the PBIR tree is written.
"""

from __future__ import annotations

import builtins
import os
import sys

__all__ = [
    "strip_lp", "lp_glob",
    "lp", "makedirs", "lp_open", "listdir", "isdir", "isfile", "exists",
    "remove", "rmdir", "walk", "rmtree", "copy2", "at_risk",
    "LONG_PATH_THRESHOLD", "MAX_PATH",
]

MAX_PATH = 260

# Engage the prefix well before MAX_PATH so that a directory created just under
# the limit still has room for the file name written inside it.
LONG_PATH_THRESHOLD = 200

_PREFIX = "\\\\?\\"
_UNC_PREFIX = "\\\\?\\UNC\\"


def _is_windows() -> bool:
    return sys.platform == "win32"


def lp(path):
    """Return *path* in a form the OS will accept regardless of length.

    On Windows, returns the ``\\\\?\\``-prefixed absolute path when *path* is
    long enough to risk ``MAX_PATH``; otherwise returns *path* unchanged. On
    every other platform this is the identity function.

    The extended-length form requires a fully qualified path with backslash
    separators and no ``.`` or ``..`` components, so the path is normalised
    before the prefix is attached.
    """
    if not path or not _is_windows():
        return path
    if isinstance(path, bytes):
        return path
    text = os.fspath(path)
    if text.startswith(_PREFIX):
        return text
    try:
        absolute = os.path.abspath(text)
    except (OSError, ValueError):
        return path
    if len(absolute) < LONG_PATH_THRESHOLD:
        return path
    absolute = absolute.replace("/", "\\")
    if absolute.startswith("\\\\"):
        # \\server\share\... -> \\?\UNC\server\share\...
        return _UNC_PREFIX + absolute[2:]
    return _PREFIX + absolute


def makedirs(path, mode=0o777, exist_ok=False):
    """``os.makedirs`` that survives paths longer than ``MAX_PATH``."""
    return os.makedirs(lp(path), mode=mode, exist_ok=exist_ok)


def lp_open(path, *args, **kwargs):
    """``open`` that survives paths longer than ``MAX_PATH``."""
    return builtins.open(lp(path), *args, **kwargs)


# ── Read / traversal / cleanup wrappers ─────────────────────────────
# Directory listing is the other call that fails outright on a long path:
# os.listdir raises WinError 3 ("cannot find the path") rather than a
# length error, which makes the cause easy to misread.

def listdir(path):
    """``os.listdir`` that survives long paths. Returns bare entry names."""
    return os.listdir(lp(path))


def isdir(path):
    return os.path.isdir(lp(path))


def isfile(path):
    return os.path.isfile(lp(path))


def exists(path):
    return os.path.exists(lp(path))


def remove(path):
    return os.remove(lp(path))


def rmdir(path):
    return os.rmdir(lp(path))


def walk(path, *args, **kwargs):
    """``os.walk`` that descends into long paths.

    The yielded *root* has any extended-length prefix stripped back off, so
    callers that do ``relpath``, ``basename`` or plain string comparison
    against the original directory keep working unchanged. Re-attaching the
    prefix for the actual file access is the job of the wrappers above.
    """
    for root, dirs, files in os.walk(lp(path), *args, **kwargs):
        yield strip_lp(root), dirs, files


def rmtree(path, *args, **kwargs):
    import shutil
    return shutil.rmtree(lp(path), *args, **kwargs)


def copy2(src, dst, *args, **kwargs):
    import shutil
    return shutil.copy2(lp(src), lp(dst), *args, **kwargs)


def strip_lp(path):
    """Remove an extended-length prefix so paths stay readable in reports."""
    if not isinstance(path, str):
        return path
    if path.startswith(_UNC_PREFIX):
        return "\\\\" + path[len(_UNC_PREFIX):]
    if path.startswith(_PREFIX):
        return path[len(_PREFIX):]
    return path


def lp_glob(pattern, *, recursive=False):
    """``glob.glob`` that sees past ``MAX_PATH``.

    Plain ``glob`` does not raise on an over-long pattern — it quietly matches
    nothing, so a validator sweeping a deep project reports "no files" instead
    of an error. Glob with the prefix attached, then strip it back off so the
    returned paths stay readable; every file access in this package goes
    through the wrappers above, which re-attach it as needed.
    """
    import glob as _glob
    matches = _glob.glob(lp(pattern), recursive=recursive)
    return [strip_lp(m) for m in matches]


def at_risk(path, headroom=60):
    """True when *path* is close enough to ``MAX_PATH`` to be worth warning about.

    Used by the CLI pre-flight. *headroom* is the space the deepest PBIR file
    name needs below the directory the caller passes in.
    """
    if not path or not _is_windows():
        return False
    try:
        return len(os.path.abspath(os.fspath(path))) + headroom > MAX_PATH
    except (OSError, ValueError, TypeError):
        return False
