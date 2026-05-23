"""pytest configuration — set up sys.path and environment."""
import os
import sys

# Make backend/ importable from tests/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend"))
sys.path.insert(0, os.path.dirname(__file__))

# Load .env from project root so MAPPLS_KEY etc. are available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", ".env"))
except ImportError:
    pass
