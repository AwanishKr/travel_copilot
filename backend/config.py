import os
from dotenv import load_dotenv

load_dotenv()

LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "http://localhost:11434")
LLM_MODEL    = os.getenv("LLM_MODEL", "qwen2.5:3b")

GOOGLE_PLACES_KEY = os.getenv("GOOGLE_PLACES_KEY", "")
ORS_KEY           = os.getenv("ORS_KEY", "")      # openrouteservice.org — free (fallback)
MAPPLS_KEY        = os.getenv("MAPPLS_KEY", "")    # mappls.com — India routing

SESSION_TTL = int(os.getenv("SESSION_TTL", 1800))
