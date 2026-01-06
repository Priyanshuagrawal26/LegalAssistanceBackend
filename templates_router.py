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
import io
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
logger.setLevel(logging.DEBUG)  # Changed to DEBUG for more info
 
# Add console handler if not present
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
 
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
 
client = AIProjectClient(
    endpoint=os.getenv("AGENT_ENDPOINT"),
    credential=DefaultAzureCredential(),
)
 
VECTOR_STORE_ID = os.getenv("LEGAL_KB_ID", "constitution_vectorstore")
 
 
def upload_pdf_to_agent(file_bytes: bytes, filename: str) -> dict:
    """
    Upload PDF bytes to Azure AI Agent and add to vector store.
   
    Args:
        file_bytes: The raw file content as bytes
        filename: The original filename (e.g., "Rent Deed.pdf")
   
    Returns:
        dict with success status and file_id
    """
    try:
        logger.info(f"📤 Step 1: Uploading {filename} to Files API...")
        logger.info(f"   File size: {len(file_bytes)} bytes")
 
        # ⭐ KEY FIX: Convert bytes to file-like object with a name
        file_stream = io.BytesIO(file_bytes)
        file_stream.name = filename  # SDK needs this for the filename!
 
        # Upload file to Azure AI
        uploaded_file = client.agents.files.upload_and_poll(
            file=file_stream,
            purpose="assistants"
        )
 
        file_id = uploaded_file.id
        logger.info(f"✅ File uploaded! file_id={file_id}")
 
        # ⭐ Step 2: Add to vector store (YOUR SCRIPT HAD THIS!)
        logger.info(f"📤 Step 2: Adding file to vector store '{VECTOR_STORE_ID}'...")
 
        batch = client.agents.vector_store_file_batches.create_and_poll(
            vector_store_id=VECTOR_STORE_ID,
            file_ids=[file_id]
        )
 
        logger.info(f"✅ File added to vector store successfully!")
        logger.info(f"   Batch status: {batch.status if hasattr(batch, 'status') else 'completed'}")
 
        return {
            "success": True,
            "file_id": file_id,
            "vector_store_id": VECTOR_STORE_ID,
            "message": "File uploaded and added to vector store"
        }
 
    except Exception as e:
        logger.error(f"❌ Upload failed: {e}", exc_info=True)
        return {
            "success": False,
            "file_id": None,
            "error": str(e)
        }
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
    user_id = request.state.user_id
 
    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id in token")
 
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
 
    template_id = str(ObjectId())
    blob_name = f"{user_id}/{template_id}_{file.filename}"
 
    logger.info(f"[UPLOAD] Uploading template: {blob_name}")
    logger.info(f"[UPLOAD] template_id={template_id}, file_name={file.filename}")
 
    container_client.get_blob_client(blob_name).upload_blob(
        file_bytes, overwrite=True
    )
 
    template = {
        "template_id": template_id,
        "file_name": file.filename,
        "blob_name": blob_name,
        "uploaded_at": int(time.time()),
        "status": "pending",
    }
 
    logger.info(f"[UPLOAD] Template document: {template}")
 
    result = users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$push": {"templates": template}},
        upsert=True
    )
 
    logger.info(f"[UPLOAD] MongoDB update result: matched={result.matched_count}, modified={result.modified_count}")
 
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

    # -------------------------------------------------
    # 1. Fetch USER's own templates
    # -------------------------------------------------
    user_doc = users_collection.find_one(
        {"_id": ObjectId(user_id)},
        {"templates": 1, "_id": 0}
    )

    user_templates = user_doc.get("templates", []) if user_doc else []

    formatted_user_templates = [
        {
            "template_id": t.get("template_id"),
            "file_name": t.get("file_name"),
            "blob_name": t.get("blob_name"),
            "uploaded_at": t.get("uploaded_at"),
            "status": t.get("status", "unknown"),
            "source": "user"   # 👈 helpful for frontend (optional)
        }
        for t in user_templates
    ]

    # -------------------------------------------------
    # 2. Fetch ADMIN approved templates (GLOBAL)
    # -------------------------------------------------
    admin_cursor = users_collection.find(
        {
            "roles": {"$in": ["admin"]},
            "templates.status": "approved"
        },
        {
            "templates": 1,
            "_id": 0
        }
    )

    admin_templates = []

    for admin_doc in admin_cursor:
        for t in admin_doc.get("templates", []):
            if t.get("status") == "approved":
                admin_templates.append({
                    "template_id": t.get("template_id"),
                    "file_name": t.get("file_name"),
                    "blob_name": t.get("blob_name"),
                    "uploaded_at": t.get("uploaded_at"),
                    "status": t.get("status"),
                    "source": "admin"   # 👈 helpful for frontend (optional)
                })

    # -------------------------------------------------
    # 3. Merge (admin + user)
    # -------------------------------------------------
    templates = admin_templates + formatted_user_templates

    return {
        "status": "success",
        "templates": templates
    }

 
 
# ============================================================
# FETCH TEMPLATE CONTENT
# ============================================================
def normalize_pdf_html(html: str) -> str:
    html = re.sub(r'style="[^"]*"', '', html)
    html = re.sub(r'<span[^>]*>', '<span>', html)
    return html
@router.get("/view/{template_id}")
def view_template(
    template_id: str,
    request: Request,
    user=Depends(get_current_user)
):
    logger.info(f"[VIEW] Fetching template: {template_id}")

    user_id = request.state.user_id
    roles = request.state.roles or []

    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    # =====================================================
    # 0. USER EDITED VERSION (HIGHEST PRIORITY)
    # =====================================================
    if ObjectId.is_valid(user_id):
        edited_doc = users_collection.find_one(
            {"_id": ObjectId(user_id), "templates.template_id": template_id},
            {"templates.$": 1}
        )

        if edited_doc and edited_doc.get("templates"):
            user_template = edited_doc["templates"][0]

            if "edited_blob" in user_template:
                logger.info("[VIEW] Serving USER EDITED version")

                edited_blob_client = container_client.get_blob_client(
                    user_template["edited_blob"]
                )

                edited_html = edited_blob_client.download_blob().readall().decode("utf-8")

                return {
                    "template_id": template_id,
                    "file_name": user_template["file_name"],
                    "content": edited_html,
                    "edited": True
                }

    template = None

    # =====================================================
    # 1. ADMIN → GLOBAL ACCESS
    # =====================================================
    if "admin" in roles:
        logger.info("[VIEW] ADMIN MODE: global template search")

        pipeline = [
            {"$unwind": "$templates"},
            {"$match": {"templates.template_id": template_id}},
            {"$project": {"_id": 0, "template": "$templates"}}
        ]

        result = list(users_collection.aggregate(pipeline))
        if not result:
            raise HTTPException(status_code=404, detail="Template not found")

        template = result[0]["template"]

    # =====================================================
    # 2. USER → OWN TEMPLATE
    # =====================================================
    else:
        if not ObjectId.is_valid(user_id):
            raise HTTPException(status_code=400, detail="Invalid user_id")

        user_doc = users_collection.find_one(
            {"_id": ObjectId(user_id)},
            {"templates": 1}
        )

        if user_doc:
            template = next(
                (t for t in user_doc.get("templates", [])
                 if t.get("template_id") == template_id),
                None
            )

        # =====================================================
        # 3. USER → ADMIN APPROVED TEMPLATE
        # =====================================================
        if not template:
            logger.info("[VIEW] USER MODE: checking admin-approved templates")

            pipeline = [
                {"$match": {"roles": {"$in": ["admin"]}}},
                {"$unwind": "$templates"},
                {
                    "$match": {
                        "templates.template_id": template_id,
                        "templates.status": "approved"
                    }
                },
                {"$project": {"_id": 0, "template": "$templates"}}
            ]

            result = list(users_collection.aggregate(pipeline))
            if not result:
                raise HTTPException(status_code=404, detail="Template not found")

            template = result[0]["template"]

    # =====================================================
    # 4. FETCH ORIGINAL FILE CONTENT
    # =====================================================
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
    user_id = request.state.user_id
 
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
 
    container_client.get_blob_client(template["blob_name"]).delete_blob()
 
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
 
    edited_blob_name = f"{user_id}/{template_id}_edited.html"
 
    blob_client = container_client.get_blob_client(edited_blob_name)
    blob_client.upload_blob(content.encode("utf-8"), overwrite=True)
 
    users_collection.update_one(
        {"_id": ObjectId(user_id), "templates.template_id": template_id},
        {"$set": {"templates.$.edited_blob": edited_blob_name}}
    )
 
    return {
        "status": "success",
        "message": "Template saved",
        "edited_blob": edited_blob_name
    }
 
 
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
 
        return response
 
    except Exception as e:
        logger.error(f"[TOKEN][USER] Failed to fetch token usage | user_id={user_id}", exc_info=True)
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
                # Log each template for debugging
                logger.debug(f"[ADMIN][TEMPLATES] Template: {t}")
               
                results.append({
                    "id": t.get("template_id"),
                    "title": t.get("file_name"),
                    "description": "User uploaded legal template",
                    "status": t.get("status", "pending"),
                    "uploadDate": t.get("uploaded_at"),
                    "downloads": 0,
                    "user": {
                        "id": user_id,
                        "email": user_email,
                        "name": user_name
                    },
                    "blob_name": t.get("blob_name"),
                    "file_name": t.get("file_name"),  # Also include file_name explicitly
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
 
 
# ============================================================
# HELPER: Find template across all users
# ============================================================
def find_template_globally(template_id: str):
    """
    Find a template by template_id across all users.
    Returns (user_id, template) tuple or (None, None) if not found.
    """
    pipeline = [
        {"$unwind": "$templates"},
        {"$match": {"templates.template_id": template_id}},
        {
            "$project": {
                "user_id": {"$toString": "$_id"},
                "template": "$templates"
            }
        }
    ]
   
    result = list(users_collection.aggregate(pipeline))
   
    if result:
        return result[0]["user_id"], result[0]["template"]
    return None, None
 
 
@router.post("/approve-template", response_model=TemplateActionResponse)
def approve_template(
    user_id: str = Query(..., description="User ID"),
    template_id: str = Query(..., description="Template ID"),
    admin: dict = Depends(require_admin)
):
    admin_email = admin.get("email", "admin")
    now = int(time.time())
 
    logger.info(f"=" * 60)
    logger.info(f"[APPROVE] Starting approval process")
    logger.info(f"[APPROVE] user_id={user_id}")
    logger.info(f"[APPROVE] template_id={template_id}")
    logger.info(f"[APPROVE] admin={admin_email}")
 
    # Validate ObjectId
    if not ObjectId.is_valid(user_id):
        logger.error(f"[APPROVE] Invalid user_id format: {user_id}")
        raise HTTPException(400, "Invalid user_id format")
 
    # Fetch user document with all templates
    user_doc = users_collection.find_one(
        {"_id": ObjectId(user_id)},
        {"templates": 1, "email": 1}
    )
 
    if not user_doc:
        logger.error(f"[APPROVE] User not found: {user_id}")
        raise HTTPException(404, "User not found")
 
    logger.info(f"[APPROVE] User found: {user_doc.get('email', 'no-email')}")
    logger.info(f"[APPROVE] User has {len(user_doc.get('templates', []))} templates")
 
    # Find the specific template
    templates = user_doc.get("templates", [])
    template = None
   
    for t in templates:
        logger.debug(f"[APPROVE] Checking template: id={t.get('template_id')}, file={t.get('file_name')}")
        if t.get("template_id") == template_id:
            template = t
            break
 
    if not template:
        logger.error(f"[APPROVE] Template not found: {template_id}")
        logger.error(f"[APPROVE] Available template_ids: {[t.get('template_id') for t in templates]}")
        raise HTTPException(404, "Template not found")
 
    # Log template details
    logger.info(f"[APPROVE] Template found!")
    logger.info(f"[APPROVE] Template keys: {list(template.keys())}")
    logger.info(f"[APPROVE] Template data: {template}")
 
    current_status = template.get("status", "pending")
    logger.info(f"[APPROVE] Current status: {current_status}")
 
    if current_status != "pending":
        raise HTTPException(400, f"Template already {current_status}")
 
    # Get blob_name and file_name with fallbacks
    blob_name = template.get("blob_name")
    filename = template.get("file_name")
 
    logger.info(f"[APPROVE] blob_name={blob_name}")
    logger.info(f"[APPROVE] file_name={filename}")
 
    if not blob_name or not filename:
        # Try to reconstruct blob_name if possible
        if filename and not blob_name:
            blob_name = f"{user_id}/{template_id}_{filename}"
            logger.warning(f"[APPROVE] Reconstructed blob_name: {blob_name}")
       
        if not filename and blob_name:
            # Try to extract filename from blob_name
            filename = blob_name.split("/")[-1].split("_", 1)[-1] if "/" in blob_name else blob_name
            logger.warning(f"[APPROVE] Extracted filename from blob_name: {filename}")
 
        if not blob_name or not filename:
            logger.error(f"[APPROVE] Cannot proceed without blob_name and file_name")
            logger.error(f"[APPROVE] Template keys: {list(template.keys())}")
            raise HTTPException(
                400,
                f"Template is missing blob_name or file_name. "
                f"Available fields: {list(template.keys())}"
            )
 
    # Check if blob exists
    try:
        blob_client = container_client.get_blob_client(blob_name)
 
        if not blob_client.exists():
            logger.error(f"[APPROVE] Blob does not exist: {blob_name}")
            raise HTTPException(404, f"Blob not found in storage: {blob_name}")
 
        file_bytes = blob_client.download_blob().readall()
        logger.info(f"[APPROVE] Downloaded blob: {len(file_bytes)} bytes")
 
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[APPROVE] Blob download failed: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to download file from storage: {str(e)}")
 
    # Upload to AI Foundry / Vector Store
    agent_file_id = None
    try:
        upload_result = upload_pdf_to_agent(file_bytes, filename)
 
        if upload_result and upload_result.get("success"):
            agent_file_id = upload_result.get("file_id")
            logger.info(f"[APPROVE] Uploaded to AI KB | file_id={agent_file_id}")
        else:
            logger.warning(f"[APPROVE] AI KB upload returned no file_id, continuing approval")
 
    except Exception as e:
        logger.error(f"[APPROVE] AI KB upload failed: {e}", exc_info=True)
        # Don't fail the approval
 
    # Update MongoDB
    update_fields = {
        "templates.$.status": "approved",
        "templates.$.reviewed_at": now,
        "templates.$.reviewed_by": admin_email
    }
   
    if agent_file_id:
        update_fields["templates.$.agent_file_id"] = agent_file_id
 
    # Also ensure blob_name and file_name are set (in case they were missing)
    update_fields["templates.$.blob_name"] = blob_name
    update_fields["templates.$.file_name"] = filename
 
    update_result = users_collection.update_one(
        {"_id": ObjectId(user_id), "templates.template_id": template_id},
        {
            "$set": update_fields,
            "$inc": {
                "templates_approved": 1,
                "templates_pending": -1
            }
        }
    )
 
    logger.info(f"[APPROVE] MongoDB update: matched={update_result.matched_count}, modified={update_result.modified_count}")
 
    if update_result.modified_count == 0:
        logger.error(f"[APPROVE] Database update failed - no documents modified")
        raise HTTPException(500, "Database update failed")
 
    logger.info(f"[APPROVE] ✅ Template approved successfully!")
    logger.info(f"=" * 60)
 
    return TemplateActionResponse(
        status="success",
        message="Template approved successfully",
        template_id=template_id,
        action="approved",
        processed_by=admin_email,
        processed_at=now
    )

@router.post("/reject-template", response_model=TemplateActionResponse)
def reject_template(
    user_id: str = Query(..., description="User ID"),
    template_id: str = Query(..., description="Template ID"),
    admin: dict = Depends(require_admin)
):
    admin_email = admin.get("email", "admin")
    now = int(time.time())

    logger.info(
        f"[REJECT] Admin {admin_email} rejecting template: "
        f"user={user_id}, template={template_id}"
    )

    # ----------------------------
    # Validate user_id
    # ----------------------------
    if not ObjectId.is_valid(user_id):
        raise HTTPException(400, "Invalid user_id format")

    # ----------------------------
    # Fetch user
    # ----------------------------
    user_doc = users_collection.find_one(
        {"_id": ObjectId(user_id)},
        {"templates": 1}
    )

    if not user_doc:
        raise HTTPException(404, "User not found")

    templates = user_doc.get("templates", [])
    template = next(
        (t for t in templates if t.get("template_id") == template_id),
        None
    )

    if not template:
        raise HTTPException(404, "Template not found")

    current_status = template.get("status", "pending")

    # ----------------------------
    # Status validation
    # ----------------------------
    if current_status != "pending":
        raise HTTPException(
            400,
            f"Template is already '{current_status}'. Cannot reject."
        )

    # ----------------------------
    # UPDATE — ONLY ALLOWED FIELD
    # ----------------------------
    update_result = users_collection.update_one(
        {
            "_id": ObjectId(user_id),
            "templates.template_id": template_id
        },
        {
            "$set": {
                "templates.$.status": "rejected"
            }
        }
    )

    if update_result.modified_count == 0:
        raise HTTPException(500, "Failed to update template status")

    logger.info(
        f"[REJECT] ❌ Template {template_id} rejected by {admin_email}"
    )

    return TemplateActionResponse(
        status="success",
        message="Template rejected",
        template_id=template_id,
        action="rejected",
        processed_by=admin_email,
        processed_at=now
    )
 
# ============================================================
# DEBUG ENDPOINT - Check template data
# ============================================================
@router.get("/debug/template/{template_id}")
def debug_template(
    template_id: str,
    admin: dict = Depends(require_admin)
):
    """Debug endpoint to check what data exists for a template."""
   
    pipeline = [
        {"$unwind": "$templates"},
        {"$match": {"templates.template_id": template_id}},
        {
            "$project": {
                "_id": 0,
                "user_id": {"$toString": "$_id"},
                "user_email": "$email",
                "template": "$templates"
            }
        }
    ]
   
    result = list(users_collection.aggregate(pipeline))
   
    if not result:
        return {"found": False, "message": "Template not found"}
   
    data = result[0]
    template = data["template"]
   
    return {
        "found": True,
        "user_id": data["user_id"],
        "user_email": data.get("user_email"),
        "template_id": template.get("template_id"),
        "file_name": template.get("file_name"),
        "blob_name": template.get("blob_name"),
        "status": template.get("status"),
        "all_fields": list(template.keys()),
        "full_template": template
    }