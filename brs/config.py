import os

def env(key, default=None):
    v = os.environ.get(key)
    return v if v not in (None, "") else default

DATABASE_URL = env("DATABASE_URL", "sqlite:///local.db")
SECRET_KEY = env("SECRET_KEY", "dev-secret")
ENCRYPTION_KEY = env("ENCRYPTION_KEY")

# Worker defaults
POLL_SECONDS = int(env("POLL_SECONDS", "20"))
MAX_MINUTES = int(env("MAX_MINUTES", "120"))
ACCEPT_AT_LEAST = env("ACCEPT_AT_LEAST", "true").lower() in ("1","true","yes","y")
VERBOSE = env("VERBOSE", "true").lower() in ("1","true","yes","y")
SCAN_DEBUG = env("SCAN_DEBUG", "true").lower() in ("1","true","yes","y")
LIMIT_DEBUG_ROWS = int(env("LIMIT_DEBUG_ROWS", "25"))
