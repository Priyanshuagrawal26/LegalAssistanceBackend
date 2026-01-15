from fastapi import APIRouter, Response, Request, HTTPException, status
from fastapi.responses import HTMLResponse
from .models import SignUpRequestDTO, UserDTO,SignUpResponse, ForgotPasswordDTO, ResetPasswordDTO, LoginDTO, LoginResponseDTO, VerifyOtpDTO, ResendOtpDTO
from .services import AuthService
from .utils import verify_captcha
import os
from tools.logger import get_logger, user_id_ctx
from tools.decorators import log_function_call

logger = get_logger("auth_routes")

router = APIRouter(prefix="/auth", tags=["Auth"])


# Signup
@router.post("/signup", response_model=SignUpResponse, status_code=status.HTTP_201_CREATED)
@log_function_call
async def signup(data: SignUpRequestDTO):
    # await verify_captcha(data.captcha_token)
    try:
        await AuthService.sign_up(data)   # <-- MUST await because it's async
        return {"message": "OTP sent to email"}
    except Exception as e:
        logger.error(f"Signup failed for {data.email}: {e}", exc_info=True)
        raise e

@router.post("/signup/verify", response_model=dict)
@log_function_call
async def verify_signup(data: VerifyOtpDTO):
    try:
        user = AuthService.verify_register(data)
        if user:
             user_id_ctx.set(str(user.get("_id")))
        return {"message": "Registration complete", "user": user}
    except Exception as e:
        logger.error(f"Signup verify failed: {e}", exc_info=True)
        raise e


@router.post("/login", status_code=202)
@log_function_call
async def login(data: LoginDTO):
    # await verify_captcha(data.captcha_token)
    try:
        result = await AuthService.login(data)
        return result
    except Exception as e:
        logger.error(f"Login failed for {data.email}: {e}", exc_info=True)
        raise e


@router.post("/login/verify", response_model=LoginResponseDTO)
@log_function_call
async def verify_login(data: VerifyOtpDTO, response: Response):
    try:
        tokens = AuthService.verify_login(data)

        # Set refresh cookie
        response.set_cookie(
            key="refreshToken",
            value=tokens["refresh_token"],
            httponly=True,
            secure=True,
            samesite="none",
            path="/"
        )
        
        # We don't have user object here directly nicely, but verify_login might return it? 
        # Typically verify_login returns tokens. One token is access token.
        return LoginResponseDTO(
            access_token=tokens["access_token"]
        )
    except Exception as e:
        logger.error(f"Login verify failed: {e}", exc_info=True)
        raise e

@router.post("/login/resend-otp", status_code=202)
@log_function_call
async def resend_otp(payload: ResendOtpDTO):
    try:
        await AuthService.resend_otp(payload)
        return {"message": "OTP resent to email"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resend OTP failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error while resending OTP")
    
  
# Refresh token endpoint
@router.post("/refresh", response_model=LoginResponseDTO)
@log_function_call
async def refresh(request: Request):
    try:
        token = request.cookies.get("refreshToken")
        if not token:
            logger.warning("Refresh token missing")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")
        new_access = AuthService.refresh_token(token)
        return {"access_token": new_access}
    except Exception as e:
         logger.error(f"Token refresh failed: {e}", exc_info=True)
         raise e


# Forgot password
@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@log_function_call
async def forgot_password(data: ForgotPasswordDTO):
    try:
        await AuthService.forgot_password(data)
        return {"message": "OTP sent to your email."}
    except Exception as e:
        logger.error(f"Forgot password flow failed for {data.email}: {e}", exc_info=True)
        raise e


# Reset password
@router.post("/reset-password", status_code=status.HTTP_200_OK)
@log_function_call
async def reset_password(data: ResetPasswordDTO):
    try:
        await AuthService.reset_password(data)
        return {"message": "Password has been reset successfully."}
    except Exception as e:
        logger.error(f"Reset password failed: {e}", exc_info=True)
        raise e


@router.get("/captcha-test", response_class=HTMLResponse, summary="Get a test page to generate reCAPTCHA tokens")
async def captcha_test():
    """
    A simple page with a reCAPTCHA widget so you can grab a valid token from your browser console.
    """
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <title>reCAPTCHA Test</title>
      <script src="https://www.google.com/recaptcha/api.js" async defer></script>
    </head>
    <body>
      <h3>Click the checkbox, then open your console to copy the token.</h3>
      <form id="testForm">
        <div class="g-recaptcha" data-sitekey="{os.getenv("CAPTCHA_SITE_KEY")}"></div>
        <button type="submit">Get Token</button>
      </form>
      <script>
        document.getElementById('testForm').addEventListener('submit', function(e) {{
          e.preventDefault();
          const token = grecaptcha.getResponse();
          console.log('Valid captcha_token:', token);
          alert('Token logged to console — copy/paste it into Swagger or Postman.');
        }});
      </script>
    </body>
    </html>
    """
