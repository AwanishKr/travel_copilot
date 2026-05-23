"""Shared test helpers — colours, pass/fail printers, sys.path setup."""
import os
import sys

# Make backend/ importable from tests/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend"))

# Load .env from project root so MAPPLS_KEY etc. are available without inline export
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", ".env"))
except ImportError:
    pass

OK  = "\033[92m✅\033[0m"
ERR = "\033[91m❌\033[0m"
SKP = "\033[93m⏭ \033[0m"
HDR = "\033[1m"
DIM = "\033[2m"
END = "\033[0m"


def header(title: str):
    print(f"\n{HDR}=== {title} ==={END}")

def ok(msg: str):
    print(f"  {OK} {msg}")

def err(msg: str):
    print(f"  {ERR} {msg}")

def skip(msg: str):
    print(f"  {SKP} {msg}")

def dim(msg: str):
    print(f"  {DIM}{msg}{END}")