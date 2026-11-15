"""Tools for developing the program: live checks, an automatic explorer and a dev mode.

Never imported by the program itself, so none of this ships in the release builds.
"""
import os

os.environ.setdefault("FT_STILL", "1")  # No gliding: the tools look right after each move.
