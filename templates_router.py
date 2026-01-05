import os
import time
import tempfile
import re
import logging
import fitz 
from datetime import datetime, timedelta
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import PlainTextResponse
from template_models import TemplateActionResponse
from dotenv import load_dotenv

from bson import ObjectId
from pymongo import MongoClient
import azure.ai.agents.models as models
from docx import Document
from pypdf import PdfReader
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from auth.db import users_collection
import time
from fastapi import Depends, Request
from auth.middleware import get_current_user, require_admin

# ============================================================
# ENV + LOGGER
# ============================================================
load_dotenv()

logger = logging.getLogger("templates")
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/templates", tags=["Templates"])

project_client = AIProjectClient(
    endpoint=os.getenv("AGENT_ENDPOINT"),
    credential=DefaultAzureCredential(),
)

AGENT_ID = os.getenv("LEGAL_AGENT_ID")
VECTOR_STORE_ID = os.getenv("LEGAL_KB_ID")
# ============================================================
# ENV CONFIG
# ============================================================
BLOB_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = os.getenv("AZURE_BLOB_CONTAINER_NAME", "templates")

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME")

FORM_ENDPOINT = os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT")
FORM_KEY = os.getenv("AZURE_FORM_RECOGNIZER_KEY")

if not all([BLOB_CONN_STR, MONGO_URI, DB_NAME, FORM_ENDPOINT, FORM_KEY]):
    raise RuntimeError("Missing one or more required environment variables")


# ============================================================
# AZURE CLIENTS
# ============================================================
blob_service = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
container_client = blob_service.get_container_client(CONTAINER_NAME)

try:
    container_client.create_container()
except Exception:
    pass

form_client = DocumentAnalysisClient(
    endpoint=FORM_ENDPOINT,
    credential=AzureKeyCredential(FORM_KEY)
)

# ============================================================
# MONGO CLIENT
# ============================================================
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
users_collection = db.users

def upload_pdf_to_agent(file_bytes: bytes, filename: str):
    """Uploads PDF bytes to Azure AI Foundry Agent and stores in vector DB."""

    try:
        # Step 1 — Upload file to Azure Assistants File API
        upload = project_client.agents.files.upload_and_poll(
            file=file_bytes,
            purpose="assistants"
        )

        file_id = upload.id
        print(f"✅ Uploaded to Assistant File API: {filename}, file_id={file_id}")

        # Step 2 — Add uploaded file to the vector store
        batch = project_client.agents.vector_store_file_batches.create_and_poll(
            vector_store_id=VECTOR_STORE_ID,
            file_ids=[file_id],
        )

        print("✅ Added to Vector Store:", VECTOR_STORE_ID)
        return True

    except Exception as e:
        print("❌ Error uploading PDF to knowledge base:", e)
        return False

# ============================================================
# OCR HELPER
# ============================================================
def ocr_extract(file_bytes: bytes) -> str:
    poller = form_client.begin_analyze_document(
        model_id="prebuilt-read",
        document=file_bytes
    )
    result = poller.result()
    return result.content.strip() if result and result.content else ""

@router.get("/downloads/recent")
async def get_recent_downloads(request: Request, user=Depends(get_current_user)):
    user_id = request.state.user_id

    user_doc = users_collection.find_one(
        {"_id": ObjectId(user_id)},
        {"recent_downloads": 1, "_id": 0}
    )

    return {
        "downloads": user_doc.get("recent_downloads", []) if user_doc else []
    }

@router.post("/download/log")
async def log_download(request: Request, data: dict, user=Depends(get_current_user)):
    user_id = request.state.user_id

    if not data.get("template_id") or not data.get("file_name"):
        raise HTTPException(status_code=400, detail="Missing template_id or file_name")

    # 🕒 Generate IST timestamp
    ist_timestamp = int((datetime.utcnow() + timedelta(hours=5, minutes=30)).timestamp())

    entry = {
        "template_id": data["template_id"],
        "file_name": data["file_name"],
        "downloaded_at": ist_timestamp
    }

    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$push": {"recent_downloads": {"$each": [entry], "$slice": -20}}}
    )

    return {"message": "Download logged"}
# ============================================================
# UPLOAD TEMPLATE
# ============================================================
@router.post("/upload")
async def upload_template(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(get_current_user)
):
    user_id = request.state.user_id  # extracted by JWT middleware

    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id in token")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    template_id = str(ObjectId())
    blob_name = f"{user_id}/{template_id}_{file.filename}"

    logger.info(f"Uploading: {blob_name}")

    container_client.get_blob_client(blob_name).upload_blob(
        file_bytes, overwrite=True
    )

    template = {
        "template_id": template_id,
        "file_name": file.filename,
        "blob_name": blob_name,
        "uploaded_at": int(time.time()),
        "status": "pending",     # 🆕 Added status field
        # allowed values → pending, approved, rejected
    }

    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$push": {"templates": template}},
        upsert=True
    )

    return {
        "status": "success",
        "message": "Template uploaded",
        "template": template
    }

# ============================================================
# LIST TEMPLATES
# ============================================================
@router.get("/list")
def list_templates(request: Request, user=Depends(get_current_user)):

    user_id = request.state.user_id

    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id in token")

    user_doc = users_collection.find_one(
        {"_id": ObjectId(user_id)},
        {"templates": 1, "_id": 0}
    )

    templates = user_doc.get("templates", []) if user_doc else []

    # Format correctly
    formatted = [
        {
            "template_id": t.get("template_id"),
            "file_name": t.get("file_name"),
            "blob_name": t.get("blob_name"),
            "uploaded_at": t.get("uploaded_at"),
            "status": t.get("status", "unknown")
        }
        for t in templates
    ]

    return {
        "status": "success",
        "templates": formatted
    }
# ============================================================
# FETCH TEMPLATE CONTENT (ALWAYS TEXT)
def normalize_pdf_html(html: str) -> str:
    # Remove font-size, font-family, line-height, etc.
    html = re.sub(r'style="[^"]*"', '', html)
    html = re.sub(r'<span[^>]*>', '<span>', html)
    return html

@router.get("/view/{template_id}")
def view_template(
    template_id: str,
    request: Request,
    user=Depends(get_current_user)
):
    print("\n================ VIEW TEMPLATE DEBUG ================")

    user_id = request.state.user_id
    roles = request.state.roles or []

    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    print("✔ USER ID =", user_id)
    print("✔ ROLES =", roles)

    # -------------------------------------------------
    # 🔥 ADMIN: SEARCH TEMPLATE ACROSS ALL USERS
    # -------------------------------------------------
    if "admin" in roles:
        print("✔ ADMIN MODE: searching template globally")

        pipeline = [
        {"$unwind": "$templates"},
        {"$match": {"templates.template_id": template_id}},
        {
            "$project": {
                "_id": 0,
                "template": "$templates"
            }
        }
        ]

        result = list(users_collection.aggregate(pipeline))

        if not result:
            print("❌ ADMIN: Template not found globally")
            raise HTTPException(status_code=404, detail="Template not found")

        template = result[0]["template"]
    # -------------------------------------------------
    # 👤 USER: SEARCH ONLY OWN TEMPLATES
    # -------------------------------------------------
    else:
        if not ObjectId.is_valid(user_id):
            raise HTTPException(status_code=400, detail="Invalid user_id")

        user_doc = users_collection.find_one(
            {"_id": ObjectId(user_id)},
            {"templates": 1}
        )

        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        template = next(
            (t for t in user_doc.get("templates", []) if t["template_id"] == template_id),
            None
        )

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

    print("✔ TEMPLATE FOUND:", template)

    # -------------------------------------------------
    # EDITED VERSION CHECK
    # -------------------------------------------------
    if "edited_blob" in template:
        try:
            edited_blob_client = container_client.get_blob_client(template["edited_blob"])
            edited_html = edited_blob_client.download_blob().readall().decode("utf-8")

            return {
                "template_id": template_id,
                "file_name": template["file_name"],
                "content": edited_html,
                "edited": True
            }
        except Exception:
            pass

    # -------------------------------------------------
    # ORIGINAL FILE EXTRACTION
    # -------------------------------------------------
    blob_client = container_client.get_blob_client(template["blob_name"])
    file_bytes = blob_client.download_blob().readall()

    file_name = template["file_name"]
    ext = file_name.rsplit(".", 1)[-1].lower()

    if ext == "txt":
        content = file_bytes.decode("utf-8", errors="ignore")

    elif ext == "docx":
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            tmp.write(file_bytes)
            path = tmp.name

        doc = Document(path)
        content = "<br>".join(p.text for p in doc.paragraphs)
        os.remove(path)

    elif ext == "pdf":
        import fitz
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_bytes)
            pdf_path = tmp.name

        doc = fitz.open(pdf_path)
        raw_html = "".join(page.get_text("html") for page in doc)
        doc.close()
        os.remove(pdf_path)
        content = normalize_pdf_html(raw_html)


    else:
        content = "Unsupported file type"

    if not content.strip():
        content = "<p>No extractable content found.</p>"

    print("================ END VIEW TEMPLATE DEBUG ================\n")

    return {
        "template_id": template_id,
        "file_name": file_name,
        "content": content,
        "edited": False
    }



# ============================================================
# DELETE TEMPLATE
# ============================================================
@router.delete("/{template_id}")
def delete_template(
    template_id: str,
    request: Request,
    user=Depends(get_current_user)
):
    user_id = request.state.user_id  # Extracted from JWT

    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id in token")

    user_doc = users_collection.find_one(
        {"_id": ObjectId(user_id)},
        {"templates": 1}
    )

    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    template = next(
        (t for t in user_doc.get("templates", []) if t["template_id"] == template_id),
        None
    )

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Delete file from Azure Blob
    container_client.get_blob_client(template["blob_name"]).delete_blob()

    # Remove from MongoDB
    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$pull": {"templates": {"template_id": template_id}}}
    )

    return {
        "status": "success",
        "message": "Template deleted",
        "template_id": template_id
    }

@router.post("/save/{template_id}")
async def save_template(
    template_id: str,
    request: Request,
    content: str = Form(...),
    user=Depends(get_current_user)
):
    user_id = request.state.user_id

    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")

    # New blob where edited HTML will be saved
    edited_blob_name = f"{user_id}/{template_id}_edited.html"

    blob_client = container_client.get_blob_client(edited_blob_name)
    blob_client.upload_blob(content.encode("utf-8"), overwrite=True)

    # Save the edited blob in DB (without touching original blob)
    users_collection.update_one(
        {"_id": ObjectId(user_id), "templates.template_id": template_id},
        {"$set": {"templates.$.edited_blob": edited_blob_name}}
    )

    return {
        "status": "success",
        "message": "Template saved",
        "edited_blob": edited_blob_name
    }
@router.post("/approve-template", response_model=TemplateActionResponse)
def approve_template(
    user_id: str = Query(...),
    template_id: str = Query(...),
    admin: dict = Depends(require_admin)
):
    admin_email = admin.get("email", "admin")
    now = int(time.time())

    # -------------------------------------------------------
    # 🔍 1. Fetch user + template
    # -------------------------------------------------------
    user_doc = users_collection.find_one(
        {"_id": ObjectId(user_id), "templates.template_id": template_id},
        {"templates.$": 1}
    )

    if not user_doc or not user_doc.get("templates"):
        raise HTTPException(404, "Template not found")

    template = user_doc["templates"][0]

    if template["status"] != "pending":
        raise HTTPException(400, f"Template already {template['status']}")

    blob_name = template.get("blob_name")
    filename = template.get("file_name")

    if not blob_name:
        raise HTTPException(400, "Template has no blob_name")

    # -------------------------------------------------------
    # 📥 2. Download file from Azure Blob Storage
    # -------------------------------------------------------
    try:
        blob_client = container_client.get_blob_client(blob_name)

        if not blob_client.exists():
            raise HTTPException(404, "Blob not found in storage")

        file_bytes = blob_client.download_blob().readall()
        logger.info(f"📥 Downloaded PDF from blob: {blob_name}")

    except Exception as e:
        logger.error("Blob download failed:", exc_info=True)
        raise HTTPException(500, "Cannot download file from storage")

    # -------------------------------------------------------
    # 📤 3. Upload file to AI Foundry Vector Store
    # -------------------------------------------------------
    try:
        upload_result = upload_pdf_to_agent(file_bytes, filename)

        if not upload_result or "file_id" not in upload_result:
            raise HTTPException(500, "Failed to upload file to AI knowledge base")

        agent_file_id = upload_result["file_id"]

        logger.info(f"📤 Uploaded to AI KB: file_id={agent_file_id}")

    except Exception as e:
        logger.error("AI Knowledge upload failed:", exc_info=True)
        raise HTTPException(500, "AI knowledge base upload failed")

    # -------------------------------------------------------
    # 📝 4. Update MongoDB (store KB file id + approved status)
    # -------------------------------------------------------
    users_collection.update_one(
        {"_id": ObjectId(user_id), "templates.template_id": template_id},
        {
            "$set": {
                "templates.$.status": "approved",
                "templates.$.reviewed_at": now,
                "templates.$.reviewed_by": admin_email,
                "templates.$.agent_file_id": agent_file_id  # ⭐ store file id for later deletion
            }
        }
    )

    logger.info(f"✔ Template approved and stored in KB: template={template_id}")

    # -------------------------------------------------------
    # 🎯 5. Return response
    # -------------------------------------------------------
    return TemplateActionResponse(
        status="success",
        message="Template approved & uploaded to knowledge base",
        template_id=template_id,
        action="approved",
        processed_by=admin_email,
        processed_at=now
    )


@router.post("/reject-template", response_model=TemplateActionResponse)
def reject_template(
    user_id: str = Query(..., description="User ID"),
    template_id: str = Query(..., description="Template ID"),
    reason: str = Query(..., min_length=5, description="Rejection reason (min 5 characters)"),
    admin: dict = Depends(require_admin)
):
    """
    Reject a pending template.
    - Only updates DB status (NO BLOB DELETE)
    - Adds rejection reason + reviewer info
    - Updates admin notifications
    """
    admin_email = admin.get("email", "admin")
    now = int(time.time())

    logger.info(f"❌ Admin {admin_email} rejecting template: user={user_id}, template={template_id}")
    logger.info(f"📝 Reason: {reason}")

    # Validate user_id
    if not ObjectId.is_valid(user_id):
        raise HTTPException(400, "Invalid user_id format")

    # Validate reason
    if len(reason.strip()) < 5:
        raise HTTPException(400, "Rejection reason must be at least 5 characters")

    # Fetch user + template
    user_doc = users_collection.find_one(
        {"_id": ObjectId(user_id), "templates.template_id": template_id},
        {"templates.$": 1}
    )

    if not user_doc or not user_doc.get("templates"):
        raise HTTPException(404, "Template not found")

    template = user_doc["templates"][0]
    current_status = template.get("status")

    if current_status != "pending":
        raise HTTPException(
            400,
            f"Template is already {current_status}. Cannot reject."
        )

    # ✔️ Only update DB status. Do not delete blob.
    update_result = users_collection.update_one(
        {
            "_id": ObjectId(user_id),
            "templates.template_id": template_id
        },
        {
            "$set": {
                "templates.$.status": "rejected",
                "templates.$.rejection_reason": reason.strip(),
                "templates.$.reviewed_at": now,
                "templates.$.reviewed_by": admin_email
            },
            "$inc": {
                "templates_rejected": 1,
                "templates_pending": -1
            }
        }
    )

    if update_result.modified_count == 0:
        raise HTTPException(500, "Failed to update template status")

    logger.info(f"❌ Template {template_id} rejected successfully by {admin_email}")

    return TemplateActionResponse(
        status="success",
        message="Template rejected",
        template_id=template_id,
        action="rejected",
        reason=reason.strip(),
        processed_by=admin_email,
        processed_at=now
    )

@router.get("/user/token-usage")
async def get_user_token_usage(request: Request, user=Depends(get_current_user)):
    user_id = request.state.user_id
    logger.info(f"[TOKEN][USER] Fetch request received | user_id={user_id}")

    try:
        user_doc = users_collection.find_one(
            {"_id": ObjectId(user_id)},
            {"token_usage": 1, "_id": 0}
        )

        if not user_doc:
            logger.warning(f"[TOKEN][USER] User not found | user_id={user_id}")
            raise HTTPException(status_code=404, detail="User not found")

        token_usage = user_doc.get("token_usage", {})

        response = {
            "used": token_usage.get("total_tokens", 0),
            "prompt_tokens": token_usage.get("prompt_tokens", 0),
            "completion_tokens": token_usage.get("completion_tokens", 0),
            "limit": 100000,
            "last_updated": datetime.utcnow().isoformat()
        }

        logger.info(
            f"[TOKEN][USER] Returning token usage | "
            f"user_id={user_id}, used={response['used']}"
        )

        return response

    except Exception as e:
        logger.error(
            f"[TOKEN][USER] Failed to fetch token usage | user_id={user_id}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to fetch token usage")

@router.get("/admin/token-usage", dependencies=[Depends(require_admin)])
async def get_admin_token_usage():
    pipeline = [
        {
            "$group": {
                "_id": None,
                "total_prompt_tokens": {"$sum": "$token_usage.prompt_tokens"},
                "total_completion_tokens": {"$sum": "$token_usage.completion_tokens"},
                "total_tokens": {"$sum": "$token_usage.total_tokens"},
                "active_users": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$token_usage.total_tokens", 0]},
                            1,
                            0
                        ]
                    }
                }
            }
        }
    ]

    result = list(users_collection.aggregate(pipeline))

    if not result:
        return {
            "total_tokens": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "active_users": 0
        }

    data = result[0]
    data.pop("_id", None)
    return data

@router.get("/admin/templates/all")
def get_all_templates_admin(
    request: Request,
    admin: dict = Depends(require_admin)
):
    admin_email = admin.get("email", "admin")
    logger.info(f"[ADMIN][TEMPLATES] Fetch all templates | admin={admin_email}")

    try:
        cursor = users_collection.find(
            {"templates": {"$exists": True, "$ne": []}},
            {
                "email": 1,
                "full_name": 1,
                "templates": 1
            }
        )

        results = []

        for user in cursor:
            user_id = str(user["_id"])
            user_email = user.get("email")
            user_name = user.get("full_name")

            for t in user.get("templates", []):
                results.append({
                    "id": t.get("template_id"),
                    "title": t.get("file_name"),
                    "description": "User uploaded legal template",
                    "status": t.get("status", "pending"),
                    "uploadDate": t.get("uploaded_at"),
                    "downloads": 0,  # future: derive from analytics
                    "user": {
                        "id": user_id,
                        "email": user_email,
                        "name": user_name
                    },
                    "blob_name": t.get("blob_name"),
                    "edited_blob": t.get("edited_blob"),
                })

        logger.info(f"[ADMIN][TEMPLATES] Total templates returned = {len(results)}")

        return {
            "status": "success",
            "count": len(results),
            "templates": results
        }

    except Exception as e:
        logger.error("[ADMIN][TEMPLATES] Failed to fetch templates", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch templates")