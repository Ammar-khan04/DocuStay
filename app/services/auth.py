"""Module A: Auth service (JWT, password hashing)."""
from datetime import datetime, timedelta
import bcrypt
import jwt
from app.config import get_settings
from app.models.user import User, UserRole

settings = get_settings()


def _pwd_bytes(password: str, max_len: int = 72) -> bytes:
    return password.encode("utf-8")[:max_len]


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_pwd_bytes(plain), hashed.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(_pwd_bytes(password), bcrypt.gensalt()).decode("utf-8")


def create_access_token(user_id: int, email: str, role: UserRole) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    # PyJWT expects "sub" to be a string
    payload = {"sub": str(user_id), "email": email, "role": role.value, "exp": expire}
    raw = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return raw if isinstance(raw, str) else raw.decode("utf-8")


def create_pending_owner_token(pending_id: int, email: str) -> str:
    """JWT for pending owner flow (email verified, identity + POA not done yet). sub='pending', pending_id in payload."""
    expire_minutes = getattr(settings, "jwt_pending_owner_expire_minutes", None) or settings.jwt_access_token_expire_minutes
    expire = datetime.utcnow() + timedelta(minutes=expire_minutes)
    payload = {"sub": "pending", "pending_id": pending_id, "email": email, "role": "owner", "exp": expire}
    raw = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return raw if isinstance(raw, str) else raw.decode("utf-8")


def decode_token(token: str) -> dict | None:
    payload, _ = decode_token_with_error(token)
    return payload


def create_password_reset_token(user_id: int, email: str, role: UserRole, reset_secret: str) -> str:
    """JWT for one-time password reset. Expires in 1 hour. reset_secret must match user.password_reset_token in DB; cleared after use."""
    expire_minutes = 60
    expire = datetime.utcnow() + timedelta(minutes=expire_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role.value,
        "type": "password_reset",
        "reset_secret": reset_secret,
        "exp": expire,
    }
    raw = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return raw if isinstance(raw, str) else raw.decode("utf-8")


def decode_token_with_error(token: str) -> tuple[dict | None, str | None]:
    """Decode JWT; returns (payload, error_message)."""
    if not token or not isinstance(token, str):
        return None, "empty token"
    token = token.strip()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload, None
    except jwt.ExpiredSignatureError as e:
        return None, str(e)
    except jwt.PyJWTError as e:
        return None, str(e)
