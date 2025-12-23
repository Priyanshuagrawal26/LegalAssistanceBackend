import os
import time
import tempfile
import logging
import fitz 

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import PlainTextResponse

from dotenv import load_dotenv

from bson import ObjectId
from pymongo import MongoClient

from docx import Document
from pypdf import PdfReader

from azure.storage.blob import BlobServiceClient
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential

from fastapi import Depends, Request
from auth.middleware import get_current_user

# ============================================================
# ENV + LOGGER
# ============================================================
load_dotenv()

logger = logging.getLogger("templates")
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/templates", tags=["Templates"])


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
        "uploaded_at": int(time.time())
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
    """
    List templates for the authenticated user.
    Token is automatically extracted via middleware + dependency.
    """

    user_id = request.state.user_id   # middleware already set this

    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id in token")

    user_doc = users_collection.find_one(
        {"_id": ObjectId(user_id)},
        {"templates": 1, "_id": 0}
    )

    templates = user_doc.get("templates", []) if user_doc else []

    return {
        "status": "success",
        "templates": templates
    }

# ============================================================
# FETCH TEMPLATE CONTENT (ALWAYS TEXT)
@router.get("/view/{template_id}")
def view_template(
    template_id: str,
    request: Request,
    user=Depends(get_current_user)
):
    print("\n================ VIEW TEMPLATE DEBUG ================")

    print("USER STATE RECEIVED =", request.state.__dict__)
    user_id = request.state.user_id

    if not user_id:
        print("❌ ERROR: user_id missing from token")
        raise HTTPException(status_code=401, detail="User not authenticated")

    print("✔ USER ID =", user_id)

    if not ObjectId.is_valid(user_id):
        print("❌ ERROR: Invalid user_id format")
        raise HTTPException(status_code=400, detail="Invalid user_id in token")

    # Fetch user
    user_doc = users_collection.find_one(
        {"_id": ObjectId(user_id)},
        {"templates": 1}
    )

    if not user_doc:
        print("❌ ERROR: User not found in DB")
        raise HTTPException(status_code=404, detail="User not found")

    print("✔ USER TEMPLATES COUNT =", len(user_doc.get("templates", [])))

    # Find template
    template = next(
        (t for t in user_doc.get("templates", []) if t["template_id"] == template_id),
        None
    )

    if not template:
        print("❌ ERROR: Template not found with ID =", template_id)
        raise HTTPException(status_code=404, detail="Template not found")

    print("✔ TEMPLATE FOUND:", template)

    # ⭐⭐⭐ NEW LOGIC: RETURN EDITED HTML IF EXISTS
    if "edited_blob" in template:
        try:
            print("✔ FOUND EDITED HTML VERSION — USING edited_blob =", template["edited_blob"])

            edited_blob_client = container_client.get_blob_client(template["edited_blob"])
            edited_html = edited_blob_client.download_blob().readall().decode("utf-8")

            print("✔ EDITED HTML LENGTH =", len(edited_html))

            return {
                "template_id": template_id,
                "file_name": template["file_name"],
                "content": edited_html,
                "edited": True
            }

        except Exception as e:
            print("❌ Failed to load edited blob, falling back to original:", e)


    # ⭐ Continue with ORIGINAL file extraction logic (unchanged)
    blob_path = template["blob_name"]
    print("✔ BLOB PATH =", blob_path)

    blob_client = container_client.get_blob_client(blob_path)
    file_bytes = blob_client.download_blob().readall()

    print("✔ FILE SIZE =", len(file_bytes), "bytes")

    if len(file_bytes) == 0:
        print("❌ ERROR: Blob file is EMPTY")
        return {"content": "<p>File is empty</p>"}

    file_name = template["file_name"]
    ext = file_name.rsplit(".", 1)[-1].lower()

    print("✔ FILE NAME =", file_name)
    print("✔ EXT =", ext)

    # ================= TXT =====================
    if ext == "txt":
        content = file_bytes.decode("utf-8", errors="ignore")
        print("✔ TXT CONTENT LENGTH =", len(content))

    # ================= DOCX ====================
    elif ext == "docx":
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            tmp.write(file_bytes)
            path = tmp.name

        doc = Document(path)
        parts = [p.text for p in doc.paragraphs]
        print("✔ DOCX PARAGRAPH COUNT =", len(parts))

        content = "<br>".join(parts)

        os.remove(path)

    # ================= PDF =====================
    elif ext == "pdf":
        print("✔ STARTING PDF EXTRACTION")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_bytes)
            pdf_path = tmp.name

        import fitz
        doc = fitz.open(pdf_path)

        html_content = ""
        for i, page in enumerate(doc):
            extracted = page.get_text("html")
            print(f"✔ PAGE {i+1} HTML LENGTH =", len(extracted))
            html_content += extracted

        doc.close()
        os.remove(pdf_path)

        print("✔ TOTAL PDF HTML LENGTH =", len(html_content))

        if not html_content.strip():
            print("⚠ PDF IS LIKELY SCANNED — Running OCR")

            ocr_text = ocr_extract(file_bytes)
            print("✔ OCR TEXT LENGTH =", len(ocr_text))

            html_content = "<br>".join(ocr_text.split("\n"))

        content = html_content

    else:
        print("❌ Unsupported file type:", ext)
        content = "Unsupported file type"

    # FINAL VALIDATION
    if not content or not content.strip():
        print("⚠ CONTENT EMPTY — Returning fallback message")
        content = "<p>No extractable content found.</p>"

    print("✔ FINAL CONTENT LENGTH =", len(content))
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
