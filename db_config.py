"""Shared DB config loaded from .env (see .env.example)."""
import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "127.0.0.1"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "database": os.getenv("DB_NAME", "cse_db"),
    "user":     os.getenv("DB_USER", "cse"),
    "password": os.getenv("DB_PASSWORD", ""),
}
