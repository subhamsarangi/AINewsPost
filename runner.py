#!/usr/bin/env python
"""Run Streamlit UI directly (no Docker).

For local: uv run python runner.py
For Streamlit Cloud: Use streamlit run ui/app.py directly
"""

import subprocess
import sys

subprocess.run([sys.executable, "-m", "streamlit", "run", "ui/app.py"])
