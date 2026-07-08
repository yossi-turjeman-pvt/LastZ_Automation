"""
DEPRECATED — this file is kept only as a compatibility shim.

Import from the package instead:
    from lastz.watcher import run_watcher_loop
"""
import warnings
warnings.warn(
    "lastz_watcher.py is deprecated. "
    "Use 'from lastz.watcher import run_watcher_loop'.",
    DeprecationWarning,
    stacklevel=2,
)

from lastz.watcher import run_watcher_loop

if __name__ == "__main__":
    run_watcher_loop()
