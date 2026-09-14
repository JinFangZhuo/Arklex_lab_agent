"""An Arklex agent for a simulated laboratory equipment desk."""
"""LabBook application; activate a locally prepared, pinned Arklex source tree."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
vendor = ROOT / ".vendor" / "arklex"
if vendor.is_dir():
    sys.path.insert(0, str(vendor))
os.environ.setdefault("MYSQL_LAZY_LOAD", "true")
os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
