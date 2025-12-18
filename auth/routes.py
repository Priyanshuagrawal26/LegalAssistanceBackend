from fastapi import APIRouter, Response, Request, HTTPException, status
from fastapi.responses import HTMLResponse
from .models import SignUpRequestDTO, UserDTO,SignUpResponse, ForgotPasswordDTO, ResetPasswordDTO, LoginDTO, LoginResponseDTO, VerifyOtpDTO, ResendOtpDTO
from .services import AuthService
from .utils import verify_captcha
import os


router = APIRouter(prefix="/auth", tags=["Auth"])


# Signup
@router.post("/signup", response_model=SignUpResponse, status_code=status.HTTP_201_CREATED)
async def signup(data: SignUpRequestDTO):
    # await verify_captcha(data.captcha_token)
    await AuthService.sign_up(data)   # <-- MUST await because it's async
    return {"message": "OTP sent to email"}

@router.post("/signup/verify", response_model=dict)
async def verify_signup(data: VerifyOtpDTO):
    user = AuthService.verify_register(data)
    return {"message": "Registration complete", "user": user}




@router.post("/login", status_code=202)
async def login(data: LoginDTO):
    # await verify_captcha(data.captcha_token)
    result = await AuthService.login(data)
    return result



@router.post("/login/verify", response_model=LoginResponseDTO)
async def verify_login(data: VerifyOtpDTO, response: Response):
    tokens = AuthService.verify_login(data)
    response.set_cookie("refreshToken", tokens["refresh_token"], httponly=True, secure=True, samesite="none", path="/")
    print("Login verified for:")
    return LoginResponseDTO(access_token=tokens["access_token"],)


@router.post("/login/resend-otp", status_code=202)
async def resend_otp(payload: ResendOtpDTO):
    try:
        await AuthService.resend_otp(payload)
        return {"message": "OTP resent to email"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error while resending OTP")
    
  
# Refresh token endpoint
@router.post("/refresh", response_model=LoginResponseDTO)
async def refresh(request: Request):
    token = request.cookies.get("refreshToken")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")
    new_access = AuthService.refresh_token(token)
    return {"access_token": new_access}


# Forgot password
@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(data: ForgotPasswordDTO):
    await AuthService.forgot_password(data)
    return {"message": "OTP sent to your email."}


# Reset password
@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(data: ResetPasswordDTO):
    await AuthService.reset_password(data)
    return {"message": "Password has been reset successfully."}


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


