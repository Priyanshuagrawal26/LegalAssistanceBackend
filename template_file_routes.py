import os
import tempfile
import logging
import fitz as pymupdf  # PyMuPDF
from fastapi.security import HTTPBearer
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pymongo import MongoClient
from azure.storage.blob import BlobServiceClient
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
import mimetypes
from dotenv import load_dotenv
from docx import Document

# -------------------------------------------------
# ENV & LOGGER
# -------------------------------------------------
load_dotenv()

logger = logging.getLogger("templates")
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/templates", tags=["Templates"])

# ================== AZURE CONFIG ==================
BLOB_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = os.getenv("AZURE_BLOB_CONTAINER_NAME", "file-uploads")

FORM_ENDPOINT = os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT")
FORM_KEY = os.getenv("AZURE_FORM_RECOGNIZER_KEY")

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
users_collection = db.users
 

if not BLOB_CONN_STR:
    logger.critical("AZURE_STORAGE_CONNECTION_STRING missing")
    raise ValueError("AZURE_STORAGE_CONNECTION_STRING not set")

if not FORM_ENDPOINT or not FORM_KEY:
    logger.critical("Form Recognizer credentials missing")
    raise ValueError("Form Recognizer credentials missing")

# ================== BLOB CLIENT ==================
blob_service = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
container_client = blob_service.get_container_client(CONTAINER_NAME)

try:
    container_client.create_container()
    logger.info(f"Blob container '{CONTAINER_NAME}' created")
except Exception:
    logger.info(f"Blob container '{CONTAINER_NAME}' already exists")

# ================== FORM RECOGNIZER ==================
form_recognizer_client = DocumentAnalysisClient(
    endpoint=FORM_ENDPOINT,
    credential=AzureKeyCredential(FORM_KEY)
)

FOLDER_NAME = "user_templates"
bearer_scheme = HTTPBearer()

def text_to_html(text: str) -> str:
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    html = ""
    for line in lines:
        html += f"<p>{line}</p>\n"

    return html

# =================================================
#               UPLOAD FILE
# =================================================
@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    logger.info(f"Upload request received: {file.filename}")

    file_bytes = await file.read()

    if not file_bytes:
        logger.warning("Uploaded file is empty")
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    blob_path = f"{FOLDER_NAME}/{file.filename}"
    blob_client = container_client.get_blob_client(blob_path)

    blob_client.upload_blob(file_bytes, overwrite=True)

    logger.info(
        f"File uploaded successfully | "
        f"name={file.filename} | size={len(file_bytes)} bytes | path={blob_path}"
    )

    return {
        "status": "success",
        "file_name": file.filename,
        "blob_path": blob_path,
        "blob_url": blob_client.url
    }

# =================================================
#        VIEW FILE → ALWAYS TEXT (NO DOWNLOAD)
# =================================================
@router.get("/view")
def view_file(filename: str):
    logger.info(f"View file request: {filename}")

    try:
        blob_path = f"{FOLDER_NAME}/{filename}"
        blob_client = container_client.get_blob_client(blob_path)

        if not blob_client.exists():
            raise HTTPException(status_code=404, detail="File not found")

        file_bytes = blob_client.download_blob().readall()
        ext = filename.lower().split(".")[-1]

        text = ""

        # TXT / HTML
        if ext in ["txt", "html"]:
            text = file_bytes.decode("utf-8", errors="ignore")

        # DOCX
        elif ext == "docx":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(file_bytes)
                path = tmp.name

            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.remove(path)

        # PDF
        elif ext == "pdf":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_bytes)
                pdf_path = tmp.name

            pdf = pymupdf.open(pdf_path)
            for page in pdf:
                text += page.get_text()
            pdf.close()

            if not text.strip():
                with open(pdf_path, "rb") as f:
                    poller = form_recognizer_client.begin_analyze_document(
                        model_id="prebuilt-read",
                        document=f
                    )
                    result = poller.result()

                for page in result.pages:
                    for line in page.lines:
                        text += line.content + "\n"

            os.remove(pdf_path)

        # IMAGES
        elif ext in ["jpg", "jpeg", "png"]:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                tmp.write(file_bytes)
                img_path = tmp.name

            with open(img_path, "rb") as f:
                poller = form_recognizer_client.begin_analyze_document(
                    model_id="prebuilt-read",
                    document=f
                )
                result = poller.result()

            for page in result.pages:
                for line in page.lines:
                    text += line.content + "\n"

            os.remove(img_path)

        else:
            text = "Unsupported file type"

        # 🔥 CONVERT TEXT → HTML
        html = text_to_html(text)

        return PlainTextResponse(
            html,
            media_type="text/html; charset=utf-8"
        )

    except Exception as e:
        logger.exception("View error")
        raise HTTPException(status_code=500, detail=str(e))
# =================================================
#               LIST FILES
# =================================================
@router.get("/list")
def list_files():
    logger.info("List templates request")

    blobs = container_client.list_blobs(
        name_starts_with=f"{FOLDER_NAME}/"
    )

    files = [
        blob.name.replace(f"{FOLDER_NAME}/", "")
        for blob in blobs
    ]

    logger.info(f"Templates found: {len(files)}")
    return files
