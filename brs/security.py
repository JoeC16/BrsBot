from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import generate_password_hash, check_password_hash
from .config import ENCRYPTION_KEY

# For local dev convenience. In production (Render), ENCRYPTION_KEY is provided via env.
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()

fernet = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)

def encrypt(s: str) -> bytes:
    return fernet.encrypt(s.encode())

def decrypt(b: bytes) -> str:
    try:
        return fernet.decrypt(b).decode()
    except InvalidToken:
        return ""

hash_password = generate_password_hash
verify_password = check_password_hash
