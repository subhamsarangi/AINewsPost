#!/usr/bin/env python
"""Streamlit entry point.

Streamlit Cloud looks for streamlit_app.py or app.py.
This file imports and runs ui/app.py.
"""

import sys
import os
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))

# Ensure secrets are loaded (Streamlit Cloud uses .streamlit/secrets.toml)
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

try:
    # Now import ui/app, which does all the Streamlit setup
    import app  # noqa
except Exception as e:
    import streamlit as st
    st.error(f"Failed to load app: {e}")
    st.exception(e)
    st.stop()


