"""Zero-setup launcher.

`python wxcc-export.py ...` works right after `git clone`, with no
PYTHONPATH and no `pip install -e .` - it just puts src/ on sys.path and
hands off to the real CLI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from wxcc_export.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
