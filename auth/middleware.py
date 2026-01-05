import logging
from typing import Dict, List
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException

from .jwt_service import JWTService

# ============================================================
# LOGGING SETUP
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("auth")

# ============================================================
# SECURITY OBJECTS
# ============================================================
bearer = HTTPBearer(auto_error=False)
jwt_service = JWTService()

# ============================================================
# JWT MIDDLEWARE (ONLY PLACE TOKEN IS VERIFIED)
# ============================================================
class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger.debug(f"Incoming request: {request.method} {request.url}")

        try:
            # Allow preflight requests
            if request.method == "OPTIONS":
                return await call_next(request)

            creds: HTTPAuthorizationCredentials = await bearer(request)

            if creds:
                try:
                    payload = jwt_service.verify_access_token(creds.credentials)

                    # Attach decoded payload to request.state
                    request.state.user = payload
                    request.state.user_id = payload.get("sub")
                    request.state.roles = payload.get("roles", [])
                    request.state.user_type = payload.get("type")
                    request.state.user_email = payload.get("email")

                    logger.info(
                        f"Authenticated user | user_id={request.state.user_id} | roles={request.state.roles}"
                    )

                except FastAPIHTTPException as e:
                    logger.warning(f"JWT verification failed: {e.detail}")
                    return JSONResponse(
                        status_code=e.status_code,
                        content={"detail": e.detail}
                    )

                except Exception as e:
                    logger.error("Unexpected JWT error", exc_info=True)
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "Invalid access token"}
                    )

            return await call_next(request)

        except Exception as e:
            logger.critical("Unhandled auth middleware error", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Authentication middleware failure"}
            )

# ============================================================
# DEPENDENCY: GET CURRENT USER (NO TOKEN VERIFICATION HERE)
# ============================================================
async def get_current_user(request: Request) -> Dict:
    """
    Returns decoded JWT payload injected by middleware.
    """
    if not hasattr(request.state, "user"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return request.state.user

# ============================================================
# ROLE-BASED ACCESS CONTROL
# ============================================================
def require_roles(*allowed_roles: str):
    def dependency(payload: Dict = Depends(get_current_user)):
        roles: List[str] = payload.get("roles", [])

        if not any(role in roles for role in allowed_roles):
            logger.warning(
                f"Access denied | user_roles={roles} | required={allowed_roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient privileges"
            )

        return payload  # 🔥 CRITICAL FIX

    return dependency

# ============================================================
# ADMIN GUARD
# ============================================================
require_admin = require_roles("admin")
