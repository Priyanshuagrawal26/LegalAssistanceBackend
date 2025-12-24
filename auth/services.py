# services.py
import logging
import random
import string
import time
import bcrypt
from fastapi import HTTPException, status

from typing import List, Optional, Dict, Any

from .models import (
    SignUpRequestDTO, VerifyOtpDTO, LoginDTO, LoginResponseDTO,
    ResendOtpDTO, ForgotPasswordDTO, ResetPasswordDTO
)
from .jwt_service import JWTService
from .db import users_collection, PyObjectId

# adjust import paths for your project:
# these were used in your original file; update if located elsewhere
from utils1.templates import verify_otp_template
from utils1.email_utils import _send_email


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

jwt_service = JWTService()

OTP_EXPIRY_SECONDS = 10 * 60  # 10 minutes default


def _generate_otp(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))


class AuthService:
    @staticmethod
    async def sign_up(signup: SignUpRequestDTO) -> None:
        """
        Create user (unverified) and send OTP to email.
        """
        try:
            existing = users_collection.find_one({"email": signup.email})
            if existing:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

            hashed = bcrypt.hashpw(signup.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            otp = _generate_otp()
            now = int(time.time())

            user_doc = {
                "email": signup.email,
                "full_name": signup.full_name,
                "roles": ["user"],
                "password_hash": hashed,
                "is_verified": False,
                "otp": otp,
                "otp_expiry": now + OTP_EXPIRY_SECONDS,
                "created_at": now
            }

            users_collection.insert_one(user_doc)

            if verify_otp_template and _send_email:
                html = verify_otp_template(name=signup.full_name or signup.email, otp=otp)
                await _send_email(signup.email, "Verify Your Email", html)
            else:
                # fallback: log OTP for dev (remove in prod)
                logger.info(f"Sign-up OTP for {signup.email}: {otp}")

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error in sign_up")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error during signup")

    @staticmethod
    def verify_register(data: VerifyOtpDTO) -> Dict[str, Any]:
        """
        Verify OTP produced at signup and mark user verified.
        """
        user = users_collection.find_one({"email": data.email})
        now = int(time.time())

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if user.get("is_verified"):
            return {"message": "Already verified"}

        if user.get("otp") != data.otp or now > user.get("otp_expiry", 0):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OTP")

        users_collection.update_one({"_id": user["_id"]}, {"$set": {"is_verified": True}, "$unset": {"otp": "", "otp_expiry": ""}})
        # return user summary
        return {"email": user["email"], "full_name": user.get("full_name"), "roles": user.get("roles", [])}

    @staticmethod
    async def login(creds: LoginDTO) -> None:
        """
        Step 1: Validate user, password, and requested role.
        Step 2: Generate OTP and send it to email.
        """
        logger.info(f"[LOGIN] Login attempt for email: {creds.email}, requested_type: {creds.type}")

        try:
            # ---------------------- FIND USER ----------------------
            user = users_collection.find_one({"email": creds.email})
            if not user:
                logger.warning(f"[LOGIN] No user found with email: {creds.email}")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

            logger.info(f"[LOGIN] User found: {creds.email}")

            # ---------------------- PASSWORD CHECK ----------------------
            stored_hash = user.get("password_hash", "").encode("utf-8")
            if not bcrypt.checkpw(creds.password.encode("utf-8"), stored_hash):
                logger.warning(f"[LOGIN] Wrong password for {creds.email}")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

            logger.info(f"[LOGIN] Password OK for {creds.email}")

            # ---------------------- VERIFIED CHECK ----------------------
            if not user.get("is_verified", False):
                logger.warning(f"[LOGIN] Unverified account: {creds.email}")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account not verified")

            # ---------------------- ROLE CHECK ----------------------
            requested_role = creds.type.lower().strip()
            actual_roles = [r.lower() for r in user.get("roles", [])]

            if requested_role not in actual_roles:
                logger.warning(
                    f"[LOGIN] Role mismatch for {creds.email}. "
                    f"Requested: {requested_role}, Allowed: {actual_roles}"
                )
                raise HTTPException(status_code=403, detail="Invalid role for this user")

            logger.info(f"[LOGIN] Role OK: {requested_role}")

            # ---------------------- OTP GENERATE ----------------------
            otp = _generate_otp()
            expiry = int(time.time()) + OTP_EXPIRY_SECONDS

            users_collection.update_one(
                {"_id": user["_id"]},
                {"$set": {"otp": otp, "otp_expiry": expiry}}
            )

            logger.info(f"[LOGIN] OTP generated for {creds.email} exp={expiry}")

            # ---------------------- SEND OTP ----------------------
            if verify_otp_template and _send_email:
                html = verify_otp_template(name=user.get("full_name", user["email"]), otp=otp)
                await _send_email(user["email"], "Your Login OTP", html)
                logger.info(f"[LOGIN] OTP email sent to {creds.email}")
            else:
                logger.info(f"[LOGIN] OTP in logs for {creds.email}: {otp}")

            return {"message": "OTP sent to email"}

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"[LOGIN] Unexpected login error for {creds.email}: {e}")
            raise HTTPException(status_code=500, detail="Internal server error during login")
        

    @staticmethod
    def verify_login(data: VerifyOtpDTO) -> Dict[str, str]:
        """
        Verify login OTP and issue access + refresh tokens.
        Returns dict with access_token and refresh_token
        """
        try:
            user = users_collection.find_one({"email": data.email})
            now = int(time.time())

            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            stored_otp = user.get("otp")
            otp_expiry = user.get("otp_expiry", 0)

            if not stored_otp or stored_otp != data.otp or now > otp_expiry:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OTP")
            
            requested_role = data.type.lower()
            actual_roles = [r.lower() for r in user.get("roles", [])]

            if requested_role not in actual_roles:
               raise HTTPException(
                  status_code=403,
                  detail="Invalid role for this user"
              )

            # Clear OTP
            users_collection.update_one({"_id": user["_id"]}, {"$unset": {"otp": "", "otp_expiry": ""}})
            
            access = jwt_service.create_access_token(subject=str(user["_id"]), roles=[requested_role], user_type=requested_role, email=user["email"])
            refresh = jwt_service.create_refresh_token(subject=str(user["_id"]), roles=[requested_role], user_type=requested_role)

            return {"access_token": access, "refresh_token": refresh}

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Unexpected error in verify_login")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error during OTP verification")

    @staticmethod
    async def resend_otp(payload: ResendOtpDTO) -> None:
        """
        Resend OTP for the given user email (used for both signup and login flows).
        Enforce rate limiting / cooldown in production.
        """
        try:
            user = users_collection.find_one({"email": payload.email})
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

            otp = _generate_otp()
            expiry = int(time.time()) + OTP_EXPIRY_SECONDS
            users_collection.update_one({"_id": user["_id"]}, {"$set": {"otp": otp, "otp_expiry": expiry}})

            if verify_otp_template and _send_email:
                html = verify_otp_template(name=user.get("full_name", user["email"]), otp=otp)
                await _send_email(payload.email, "Your OTP Code", html)
            else:
                logger.info(f"Resend OTP for {payload.email}: {otp}")

            return {"message": "OTP resent"}

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error in resend_otp")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error while resending OTP")

    @staticmethod
    def refresh_token(token: str) -> str:
        """
        Verify refresh token and issue a new access token.
        """
        try:
            payload = jwt_service.verify_refresh_token(token)
            user_id = payload.get("sub")
            user_type = payload.get("type", "user")

            if not user_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token payload")

            user = users_collection.find_one({"_id": PyObjectId.validate(user_id)})
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

            roles = user.get("roles", ["user"])
            new_access = jwt_service.create_access_token(subject=str(user["_id"]), roles=roles, user_type=user_type, email=user.get("email"))
            return new_access
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error in refresh_token")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error during token refresh")

    @staticmethod
    async def forgot_password(data: ForgotPasswordDTO) -> Dict[str, str]:
        """
        Generate reset token for password reset and send email.
        """
        try:
            user = users_collection.find_one({"email": data.email, "roles": data.type})
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            reset_token = _generate_otp()  # Using 6-digit token
            expiry = int(time.time()) + OTP_EXPIRY_SECONDS

            users_collection.update_one(
                {"_id": user["_id"]},
                {"$set": {"reset_token": reset_token, "reset_token_expiry": expiry}}
            )

            if verify_otp_template and _send_email:
                html = verify_otp_template(
                    name=user.get("full_name", user["email"]),
                    otp=reset_token
                )
                await _send_email(data.email, "Password Reset Code", html)
            else:
                logger.info(f"RESET TOKEN for {data.email}: {reset_token}")

            return {"message": "Reset token sent to your email."}

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error in forgot_password")
            raise HTTPException(500, "Internal server error during forgot-password")


    @staticmethod
    async def reset_password(data: ResetPasswordDTO) -> Dict[str, str]:
        """
        Validate reset token and update password.
        """
        try:
            user = users_collection.find_one({
    "email": data.email,
    "roles": {"$in": [data.type]}
})
            now = int(time.time())

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            stored_token = user.get("reset_token")
            expiry = user.get("reset_token_expiry", 0)

            # Validate token
            if not stored_token or stored_token != data.reset_token or now > expiry:
                raise HTTPException(status_code=400, detail="Invalid or expired reset token")

            # Validate password match
            if data.new_password != data.confirm_password:
                raise HTTPException(status_code=400, detail="Passwords do not match")

            # Hash new password
            hashed = bcrypt.hashpw(
                data.new_password.encode("utf-8"),
                bcrypt.gensalt()
            ).decode("utf-8")

            # Update password + clear reset token
            users_collection.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {"password_hash": hashed},
                    "$unset": {
    "reset_token": 1,
    "reset_token_expiry": 1
}
                }
            )

            return {"message": "Password reset successful."}

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error in reset_password")
            raise HTTPException(500, "Internal server error during password reset")
