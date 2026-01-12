from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from typing import Dict, Any

class PendingTemplateDTO(BaseModel):
    user_id: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    template_id: str
    file_name: str
    blob_name: Optional[str] = None
    file_size: Optional[int] = None
    uploaded_at: int
    text_preview: Optional[str] = None
    text_length: int = 0
 
 
class PendingTemplatesResponse(BaseModel):
    pending_templates: List[PendingTemplateDTO]
    total_count: int
    page: int
    limit: int
    total_pages: int
 
 
class PendingTemplateDetailResponse(BaseModel):
    user_id: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    template_id: str
    file_name: str
    blob_name: Optional[str] = None
    file_size: Optional[int] = None
    status: str
    uploaded_at: int
    extracted_text: str = ""
    text_length: int = 0
 
 
# ============================================================
#                    ADMIN - TEMPLATE ACTIONS
# ============================================================
 
class ApproveTemplateRequest(BaseModel):
    user_id: str
    template_id: str
 
 
class RejectTemplateRequest(BaseModel):
    user_id: str
    template_id: str
    reason: str = Field(..., min_length=5, description="Reason for rejection (min 5 characters)")
 
 
class TemplateActionResponse(BaseModel):
    status: str
    message: str
    template_id: str
    action: str
    processed_by: Optional[str] = None
    processed_at: Optional[int] = None
    reason: Optional[str] = None
 
 
class BulkApproveRequest(BaseModel):
    templates: List[ApproveTemplateRequest]
 
 
class BulkRejectRequest(BaseModel):
    templates: List[RejectTemplateRequest]
 
 
class BulkActionResponse(BaseModel):
    status: str
    approved_count: Optional[int] = None
    rejected_count: Optional[int] = None
    failed_count: int = 0
    details: Dict[str, Any]
 