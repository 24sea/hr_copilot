# Backend/config.py
# Minimal, dependency-free config so your app runs without pydantic.
import os

class Settings:
    # default identical to previous behavior
    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    # CLEAR_LEAVES_ON_START accepts "1","true","yes" (case-insensitive)
    CLEAR_LEAVES_ON_START: bool = os.getenv("CLEAR_LEAVES_ON_START", "false").lower() in {"1","true","yes"}

# module-level settings object (imported elsewhere as `from .config import settings`)
settings = Settings()
