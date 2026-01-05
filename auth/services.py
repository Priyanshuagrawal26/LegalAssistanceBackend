import logging
import random
import string
import time
import bcrypt
from typing import List, Optional, Dict, Any
from fastapi import HTTPException, status

# Local imports
from .models import (
    SignUpRequestDTO, VerifyOtpDTO, LoginDTO, LoginResponseDTO,
    ResendOtpDTO, ForgotPasswordDTO, ResetPasswordDTO
)
from .jwt_service import JWTService
from .db import users_collection, PyObjectId

# Adjust import paths for your project
from utils1.templates import verify_otp_template
from utils1.email_utils import _send_email
from models.user import UserModel, TokenUsage, UserTemplate

# Logging Configuration
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

jwt_service = JWTService()

OTP_EXPIRY_SECONDS = 10 * 60  # 10 minutes default


def _generate_otp(length: int = 6) -> str:
    """Generates a random numeric OTP."""
    return ''.join(random.choices(string.digits, k=length))
class AuthService:

    @staticmethod
    async def sign_up(signup: Any) -> None:
        """
        Registers a new user, hashes the password, and sends a verification OTP.
        """
        try:
            existing = users_collection.find_one({"email": signup.email})
            if existing:
                raise HTTPException(status_code=400, detail="Email already registered")

            now = int(time.time())
            otp = _generate_otp()
            hashed = bcrypt.hashpw(signup.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

            # Create User using UserModel
            new_user = UserModel(
                email=signup.email,
                full_name=signup.full_name,
                roles=["user"],
                password_hash=hashed,
                is_verified=False,
                created_at=now,
                otp=otp,
                otp_expiry=now + OTP_EXPIRY_SECONDS,
                templates=[],
                token_usage=TokenUsage()
            )

            # Insert into MongoDB
            users_collection.insert_one(new_user.dict(by_alias=True))

            # Send OTP via Email
            if verify_otp_template and _send_email:
                html = verify_otp_template(name=signup.full_name or signup.email, otp=otp)
                await _send_email(signup.email, "Verify Your Email", html)

            logger.info(f"[SIGNUP] OTP for {signup.email}: {otp}")

        except HTTPException:
            raise
        except Exception:
            logger.exception("Error in sign_up")
            raise HTTPException(status_code=500, detail="Internal server error during signup")

    @staticmethod
    def verify_register(data: Any) -> Dict[str, Any]:
        """
        Verify OTP produced at signup, initialize missing fields, and mark user verified.
        """
        user = users_collection.find_one({"email": data.email})
        now = int(time.time())

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if user.get("is_verified"):
            return {"message": "Already verified"}

        if user.get("otp") != data.otp or now > user.get("otp_expiry", 0):
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")

        # Logic to handle migration/missing fields for new UserModel
        update_fields = {"is_verified": True}

        if "templates" not in user:
            update_fields["templates"] = []

        if "token_usage" not in user:
            update_fields["token_usage"] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        # Remove otp fields upon successful verification
        unset_fields = {"otp": "", "otp_expiry": ""}

        users_collection.update_one(
            {"_id": user["_id"]},
            {"$set": update_fields, "$unset": unset_fields}
        )

        return {
            "email": user["email"],
            "full_name": user.get("full_name"),
            "roles": user.get("roles", [])
        }

    @staticmethod
    async def login(creds: Any) -> Dict[str, str]:
        """
        Step 1: Validate credentials and role.
        Step 2: Ensure migration fields exist.
        Step 3: Generate and send OTP for 2FA.
        """
        logger.info(f"[LOGIN] Attempt: {creds.email}")

        try:
            user = users_collection.find_one({"email": creds.email})
            if not user:
                raise HTTPException(status_code=401, detail="Invalid credentials")

            # Ensure Model Fields Exist (Migration check during login)
            update_fields = {}
            if "templates" not in user:
                update_fields["templates"] = []
            if "token_usage" not in user:
                update_fields["token_usage"] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            if update_fields:
                users_collection.update_one({"_id": user["_id"]}, {"$set": update_fields})

            # Password Check
            if not bcrypt.checkpw(creds.password.encode("utf-8"), user["password_hash"].encode("utf-8")):
                raise HTTPException(status_code=401, detail="Invalid credentials")

            # Verification Check
            if not user.get("is_verified", False):
                raise HTTPException(status_code=403, detail="Account not verified")

            # Role Check
            req_role = creds.type.lower().strip()
            if req_role not in [r.lower() for r in user.get("roles", [])]:
                raise HTTPException(status_code=403, detail="Invalid role")

            # Generate OTP
            otp = _generate_otp()
            expiry = int(time.time()) + OTP_EXPIRY_SECONDS

            users_collection.update_one(
                {"_id": user["_id"]},
                {"$set": {"otp": otp, "otp_expiry": expiry}}
            )

            # Send Email
            if verify_otp_template and _send_email:
                html = verify_otp_template(name=user.get("full_name", user["email"]), otp=otp)
                await _send_email(user["email"], "Your Login OTP", html)
            else:
                logger.info(f"[DEV MODE] OTP for {creds.email} = {otp}")

            return {"message": "OTP sent"}

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"[LOGIN] Unexpected error: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @staticmethod
    def verify_login(data: Any) -> Dict[str, str]:
        """
        Verify login OTP and issue JWT tokens.
        """
        try:
            user = users_collection.find_one({"email": data.email})
            now = int(time.time())

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            # OTP Check
            if user.get("otp") != data.otp or now > user.get("otp_expiry", 0):
                raise HTTPException(status_code=400, detail="Invalid or expired OTP")

            # Role Check
            req_role = data.type.lower()
            if req_role not in [r.lower() for r in user.get("roles", [])]:
                raise HTTPException(status_code=403, detail="Invalid role")

            # Clear OTP from DB
            users_collection.update_one(
                {"_id": user["_id"]},
                {"$unset": {"otp": "", "otp_expiry": ""}}
            )

            # Generate JWTs
            access = jwt_service.create_access_token(
               subject=str(user["_id"]),
               roles=user.get("roles", ["user"]),   # ✅ FIX
               user_type=req_role,
               email=user["email"]
            ) 
            refresh = jwt_service.create_refresh_token(
                subject=str(user["_id"]),
                roles=user.get("roles", ["user"]),
                user_type=req_role
            )

            return {
                "access_token": access,
                "refresh_token": refresh
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"[VERIFY LOGIN] Error: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @staticmethod
    async def resend_otp(payload: Any) -> Dict[str, str]:
        """
        Resends a fresh OTP code to the user's email.
        """
        try:
            user = users_collection.find_one({"email": payload.email})
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            otp = _generate_otp()
            expiry = int(time.time()) + OTP_EXPIRY_SECONDS
            users_collection.update_one({"_id": user["_id"]}, {"$set": {"otp": otp, "otp_expiry": expiry}})

            if verify_otp_template and _send_email:
                html = verify_otp_template(name=user.get("full_name", user["email"]), otp=otp)
                await _send_email(payload.email, "Your OTP Code", html)

            return {"message": "OTP resent"}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error in resend_otp")
            raise HTTPException(status_code=500, detail="Internal server error")

    @staticmethod
    def refresh_token(token: str) -> str:
        """
        Validates a refresh token and generates a new access token.
        """
        try:
            payload = jwt_service.verify_refresh_token(token)
            user_id = payload.get("sub")
            user_type = payload.get("type", "user")

            user = users_collection.find_one({"_id": PyObjectId.validate(user_id)})
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            return jwt_service.create_access_token(
                subject=str(user["_id"]),
                roles=user.get("roles", ["user"]),
                user_type=user_type,
                email=user.get("email")
            )
        except Exception:
            logger.exception("Token refresh failed")
            raise HTTPException(status_code=401, detail="Invalid refresh token")

    @staticmethod
    async def forgot_password(data: Any) -> Dict[str, str]:
        """
        Initiates the password reset process by sending an OTP.
        """
        try:
            user = users_collection.find_one({"email": data.email, "roles": data.type})
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            reset_token = _generate_otp()
            expiry = int(time.time()) + OTP_EXPIRY_SECONDS

            users_collection.update_one(
                {"_id": user["_id"]},
                {"$set": {"reset_token": reset_token, "reset_token_expiry": expiry}}
            )

            if verify_otp_template and _send_email:
                html = verify_otp_template(name=user.get("full_name", user["email"]), otp=reset_token)
                await _send_email(data.email, "Password Reset Code", html)

            return {"message": "Reset token sent to your email."}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error in forgot_password")
            raise HTTPException(status_code=500, detail="Internal server error")

    @staticmethod
    async def reset_password(data: Any) -> Dict[str, str]:
        """
        Validates the reset token and updates the user's password.
        """
        try:
            user = users_collection.find_one({"email": data.email, "roles": {"$in": [data.type]}})
            now = int(time.time())

            if not user or user.get("reset_token") != data.reset_token or now > user.get("reset_token_expiry", 0):
                raise HTTPException(status_code=400, detail="Invalid or expired reset token")

            if data.new_password != data.confirm_password:
                raise HTTPException(status_code=400, detail="Passwords do not match")

            hashed = bcrypt.hashpw(data.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

            users_collection.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {"password_hash": hashed},
                    "$unset": {"reset_token": 1, "reset_token_expiry": 1}
                }
            )

            return {"message": "Password reset successful."}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error in reset_password")
            raise HTTPException(status_code=500, detail="Internal server error")