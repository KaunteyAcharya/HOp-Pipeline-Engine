"""Entry point for Streamlit Community Cloud: always runs the SYNTHETIC demo (no API keys needed)."""

import os
import runpy
from pathlib import Path

os.environ["HOSTOP_DEMO"] = "1"
runpy.run_path(str(Path(__file__).parent / "dashboard" / "app.py"), run_name="__main__")
