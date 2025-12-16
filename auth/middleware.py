
import logging
from typing import Dict, List
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from jwt import ExpiredSignatureError, InvalidTokenError
from .jwt_service import JWTService
from fastapi.exceptions import HTTPException as FastAPIHTTPException

# ----------------------------
# Logging Setup
# ----------------------------
logging.basicConfig(
    level=logging.INFO,  # Change to DEBUG if you want more detailed logs
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("auth")

# ----------------------------
# Security Objects
# ----------------------------
bearer = HTTPBearer(auto_error=False)
jwt_service = JWTService()


class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger.debug(f"Incoming request: {request.method} {request.url}")

        try:
            if request.method == "OPTIONS":
                return await call_next(request)
            creds: HTTPAuthorizationCredentials = await bearer(request)
            if creds:
                logger.debug("Authorization header detected, verifying token...")
                try:
                    payload = jwt_service.verify_access_token(creds.credentials)

                    request.state.user_id = payload.get("sub")
                    request.state.roles = payload.get("roles", [])
                    request.state.user_type = payload.get("type")
                    request.state.user_email = payload.get("email")

                    # 🔥 FIX: Add this
                    request.state.user = payload

                    logger.info(
                        f"Authenticated user (middleware): user_id={request.state.user_id}, "
                        f"roles={request.state.roles}, type={request.state.user_type}"
                    )

                except FastAPIHTTPException as e:
                    logger.warning(f"Token verification failed (HTTPException): {e.detail}")
                    return JSONResponse(status_code=e.status_code, content={"detail": e.detail})

                except Exception as e:
                    logger.error(f"Unexpected error verifying token: {e}", exc_info=True)
                    return JSONResponse(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        content={"detail": "Error verifying access token"}
                    )

            else:
                logger.debug("No Authorization header found; continuing as guest.")

            response = await call_next(request)
            logger.debug("Request processed successfully.")
            return response

        except Exception as e:
            logger.critical(f"Unhandled exception in JWT middleware: {e}", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal server error in authentication middleware"}
            )



async def get_current_user(req: Request, creds=Depends(bearer)) -> Dict:
    logger.debug("Executing get_current_user dependency...")

    if not creds:
        logger.info("Missing authentication credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        logger.debug("Verifying access token inside get_current_user...")
        payload = jwt_service.verify_access_token(creds.credentials)

        req.state.user_id = payload.get("sub")
        req.state.roles = payload.get("roles", [])
        # req.state.user_type = payload.get("type")
        req.state.user_email = payload.get("email")

        logger.info(
            f"User authenticated via dependency: user_id={req.state.user_id}, "
            f"roles={req.state.roles}, email={req.state.user_email}"
        )
        return payload

    except ExpiredSignatureError:
        logger.warning("Token expired during get_current_user")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    except InvalidTokenError:
        logger.warning("Invalid token provided to get_current_user")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    except Exception as e:
        logger.error(f"Token validation failed in get_current_user: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Token validation failed")


def require_roles(*allowed_roles: str):
    def dependency(payload=Depends(get_current_user)):
        logger.debug(f"Checking required roles: {allowed_roles}")

        try:
            roles: List[str] = payload.get("roles", [])

            if not any(r in roles for r in allowed_roles):
                logger.warning(
                    f"Access denied: user_roles={roles}, required_roles={allowed_roles}"
                )
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient privileges")

            logger.info(f"Role check passed: user_roles={roles}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error during role verification: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Role verification failed")

    return dependency
