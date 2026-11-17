"""pytest bootstrap: never call real LLM/DB/Redis/hosts from developer .env."""

import os

os.environ["APP_ENV"] = "testing"
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["CROSS_ENCODER_FORCE"] = "false"
os.environ["LOCAL_EMBEDDING_FORCE"] = "false"
os.environ["UNSTRUCTURED_FORCE"] = "false"
os.environ["EMBEDDING_API_KEY"] = ""
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/local/test.db"
os.environ["REDIS_URL"] = ""
os.environ["QDRANT_URL"] = ""
os.environ["LOG_LEVEL"] = "WARNING"
# Ops plane: fixtures only. Redis is absent in tests, so confirmations use the
# explicitly-test-only memory store; nothing may fall back silently.
os.environ["OPS_TOOL_BACKEND"] = "mock"
os.environ["PENDING_STORE_BACKEND"] = "memory"
os.environ["OPS_DEFAULT_HOST"] = "lab-node-1"

from pathlib import Path

Path("data/local").mkdir(parents=True, exist_ok=True)
