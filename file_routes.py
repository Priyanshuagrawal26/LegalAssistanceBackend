import os
import tempfile
import fitz as pymupdf
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from azure.storage.blob import BlobServiceClient
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from docx import Document

load_dotenv()

router = APIRouter(prefix="/files", tags=["Files"])

# ------------------ AZURE CONFIG ------------------
BLOB_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = os.getenv("AZURE_BLOB_CONTAINER_NAME", "file-uploads")

VISION_ENDPOINT = os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT")
VISION_KEY = os.getenv("AZURE_FORM_RECOGNIZER_KEY")

if not BLOB_CONN_STR:
    raise ValueError("AZURE_STORAGE_CONNECTION_STRING not set")

# ------------------ BLOB CLIENT ------------------
blob_service = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
container_client = blob_service.get_container_client(CONTAINER_NAME)

try:
    container_client.create_container()
except Exception:
    pass

# ------------------ OCR CLIENT ------------------
vision_client = ImageAnalysisClient(
    endpoint=VISION_ENDPOINT,
    credential=AzureKeyCredential(VISION_KEY)
)

# =================================================
#               UPLOAD FILE
# =================================================
@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        blob_client = container_client.get_blob_client(file.filename)
        blob_client.upload_blob(file_bytes, overwrite=True)

        extracted_text = None

        if file.filename.lower().endswith(".pdf"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            with open(tmp_path, "rb") as f:
                result = vision_client.analyze(
                    image_data=f,
                    visual_features=[VisualFeatures.READ]
                )

            if result.read and result.read.blocks:
                extracted_text = "\n".join(
                    line.text
                    for block in result.read.blocks
                    for line in block.lines
                )

            os.remove(tmp_path)

        return {
            "status": "success",
            "file_name": file.filename,
            "blob_url": blob_client.url,
            "ocr_text": extracted_text
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =================================================
#               VIEW FILE
# =================================================
@router.get("/view")
def view_file(filename: str, format: str = "html"):
    try:
        blob_client = container_client.get_blob_client(filename)
        if not blob_client.exists():
            raise HTTPException(status_code=404, detail="File not found")

        file_bytes = blob_client.download_blob().readall()
        text_content = ""

        if filename.lower().endswith(".txt"):
            text_content = file_bytes.decode("utf-8", errors="ignore")

        elif filename.lower().endswith(".html"):
            html = file_bytes.decode("utf-8", errors="ignore")
            return HTMLResponse(html) if format != "txt" else PlainTextResponse(html)

        elif filename.lower().endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(file_bytes)
                path = tmp.name
            doc = Document(path)
            text_content = "\n".join(p.text for p in doc.paragraphs)
            os.remove(path)

        elif filename.lower().endswith(".pdf"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_bytes)
                path = tmp.name
            pdf = pymupdf.open(path)
            for page in pdf:
                text_content += page.get_text()
            pdf.close()
            os.remove(path)

            if not text_content.strip():
                text_content = "No readable text found in PDF."

        else:
            text_content = file_bytes.decode("utf-8", errors="ignore")

        if format == "txt":
            return PlainTextResponse(text_content)

        return HTMLResponse(
            f"<pre style='white-space: pre-wrap'>{text_content}</pre>"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
 