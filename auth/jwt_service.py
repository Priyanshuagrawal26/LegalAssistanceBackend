# jwt_service.py
import time
from typing import Any, Dict, List
import os
from dotenv import load_dotenv
import jwt
from jwt import PyJWTError
from fastapi import HTTPException, status

load_dotenv()

def _to_int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    try:
        return int(v) if v is not None else default
    except Exception:
        return default

ACCESS_EXPIRES = _to_int_env("ACCESS_TOKEN_EXPIRES", 3600)        # in seconds
REFRESH_EXPIRES = _to_int_env("REFRESH_TOKEN_EXPIRES", 7 * 24 * 3600)  # default 7 days
SECRET_KEY = os.getenv("SECRET_KEY", "please-change-me")

class JWTService:
    def create_access_token(self, subject: str, roles: str, user_type: str, email: str) -> str:
        now = int(time.time())
        payload: Dict[str, Any] = {
            "sub": subject,
            "roles": roles,
            "type": user_type,
            "email": email,
            "iat": now,
            "exp": now + ACCESS_EXPIRES
        }
        return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    def create_refresh_token(self, subject: str, roles: List[str], user_type: str) -> str:
        now = int(time.time())
        payload: Dict[str, Any] = {
            "sub": subject,
            "roles": roles,
            "type": user_type,
            "iat": now,
            "exp": now + REFRESH_EXPIRES
        }
        return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    def verify_refresh_token(self, token: str) -> Dict[str, Any]:
        try:
            return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except PyJWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    def verify_access_token(self, token: str) -> Dict[str, Any]:
        try:
            return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except PyJWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
