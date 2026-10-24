"""PyInstaller entry point for the standalone md-maker executable."""

import sys

from md_maker.cli import main

sys.exit(main())
