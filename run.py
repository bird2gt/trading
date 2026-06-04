"""Compatibility entrypoint for the profile-based MT4 runner."""

import sys

from run_mt4 import main


if __name__ == "__main__":
    # Line-buffer stdout so print() lands in the log immediately when redirected
    # to a file (otherwise it buffers and the log looks frozen).
    sys.stdout.reconfigure(line_buffering=True)
    main()
