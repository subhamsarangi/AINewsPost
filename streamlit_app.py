#!/usr/bin/env python
"""Streamlit entry point.

Streamlit Cloud looks for streamlit_app.py or app.py.
This file imports and runs ui/app.py.
"""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))

# Now import ui/app, which does all the Streamlit setup
import app  # noqa


