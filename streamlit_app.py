#!/usr/bin/env python
"""Streamlit entry point for cloud deployment.

Streamlit Cloud expects streamlit_app.py or app.py in the root.
This redirects to ui/app.py which has the actual UI code.
"""

import sys
from pathlib import Path

# Add ui/ to path so imports work
sys.path.insert(0, str(Path(__file__).parent / "ui"))

# Import and run the Streamlit app
from app import *  # noqa
