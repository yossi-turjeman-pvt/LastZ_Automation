"""
DEPRECATED — this file is kept only as a compatibility shim.

Run the automation with:
    python -m lastz

Or import directly:
    from lastz.cli import main
"""
import warnings
warnings.warn(
    "lastz_auto_master.py is deprecated. Use 'python -m lastz' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from lastz.cli import main

if __name__ == "__main__":
    main()
