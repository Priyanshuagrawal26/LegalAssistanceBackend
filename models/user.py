from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from bson import ObjectId
import time

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate
    
    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


# ------------------------------ TEMPLATE MODEL ------------------------------
class UserTemplate(BaseModel):
    template_id: str
    file_name: str
    blob_name: str
    uploaded_at: int
    status: str = "pending"
    agent_file_id: Optional[str] = None

# ------------------------------ DOWNLOAD LOG MODEL --------------------------
class DownloadLog(BaseModel):
    template_id: str
    file_name: str
    downloaded_at: int = Field(default_factory=lambda: int(time.time()))


# ------------------------------ TOKEN USAGE MODEL ---------------------------
class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# ------------------------------ MAIN USER MODEL -----------------------------
class UserModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")

    email: EmailStr
    full_name: str

    roles: List[str] = ["user"]
    password_hash: str

    is_verified: bool = False
    created_at: int

    # OTP
    otp: Optional[str] = None
    otp_expiry: Optional[int] = None

    # Reset Password
    reset_token: Optional[str] = None
    reset_token_expiry: Optional[int] = None

    # Templates Array
    templates: List[UserTemplate] = []

    # Recent Downloads
    recent_downloads: List[DownloadLog] = []

    # Token Usage
    token_usage: TokenUsage = TokenUsage()

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
