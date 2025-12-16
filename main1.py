import os
import tempfile
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import fitz as pymupdf
import docx
from auth.routes import router as auth_router
from auth.middleware import JWTMiddleware
from fastapi.responses import FileResponse
# ---------------------- AUTH + SESSION ----------------------
from auth.routes import router as auth_router
from auth.middleware import JWTMiddleware
from chat_routes import router as chat_router

import re
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# -------------------------- AZURE ---------------------------
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from history import get_or_create_thread, save_message
import logging
from file_routes import router as file_router

logger = logging.getLogger("app")
logger.setLevel(logging.INFO)


# ================================================================
#                     INIT FASTAPI APP
# ================================================================
app = FastAPI()

 
app.add_middleware(
    CORSMiddleware,
allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        # Add the other person's frontend URL here
    ],
    allow_credentials=True,
  # Must be False with "*"
    allow_methods=["*"],
    allow_headers=[
    "Authorization",
    "Content-Type",
    "Accept",
    "Origin",
    "User-Agent",
    "X-Requested-With"],

)

app.add_middleware(JWTMiddleware)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(file_router)



# ================================================================
#                        Azure Setup
# ================================================================
project_client = AIProjectClient(
    endpoint="https://agenticainew.services.ai.azure.com/api/projects/agenticaitest",
    credential=DefaultAzureCredential()
)

# Legal Template Generator Agent
LEGAL_AGENT_ID = "asst_fwWdgF8Cgictvs1r3xnbNCNa"
legal_agent = project_client.agents.get_agent(agent_id=LEGAL_AGENT_ID)


# ================================================================
#                     DOCUMENT PROCESSING
# ================================================================
def extract_text_from_pdf(file_path: str) -> str:
    try:
        text = ""
        with pymupdf.open(file_path) as pdf:
            for page in pdf:
                text += page.get_text()
        return text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {e}")

def extract_pdf_block(text: str):
    """Extracts content inside [PDF_DOCUMENT] tags."""
    match = re.search(r"\[PDF_DOCUMENT\](.*?)\[/PDF_DOCUMENT\]", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def create_pdf_from_text(text: str, output_path: str):
    """Creates a PDF file from plain text."""
    c = canvas.Canvas(output_path, pagesize=letter)
    width, height = letter

    y = height - 40
    for line in text.split("\n"):
        c.drawString(40, y, line)
        y -= 15

        if y < 40:
            c.showPage()
            y = height - 40

    c.save()

def extract_text_from_docx(file_path: str) -> str:
    try:
        doc = docx.Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing DOCX: {e}")


def extract_text_from_txt(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing TXT: {e}")


def extract_text(file_path: str, filename: str) -> str:
    ext = filename.lower().split(".")[-1]
    if ext == "pdf": return extract_text_from_pdf(file_path)
    if ext in ["doc", "docx"]: return extract_text_from_docx(file_path)
    if ext == "txt": return extract_text_from_txt(file_path)
    return ""


# ================================================================
#                         MAIN ENDPOINT
@app.post("/query")
async def query_endpoint(
    request: Request,
    question: str = Form(...),
    thread_id: Optional[str] = Form(None),
    user_file: Optional[UploadFile] = File(None)
):
    logger.info("📩 /query endpoint hit")

    # ----------------------------
    # 1. Get user ID from JWT
    # ----------------------------
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # ----------------------------
    # 2. Extract file content
    # ----------------------------
    extra_context = ""

    if user_file:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=os.path.splitext(user_file.filename)[1]
        ) as tmp:
            content = await user_file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            file_text = extract_text(tmp_path, user_file.filename)
            extra_context = f"\n\nUser-provided document context:\n{file_text[:3000]}"
        finally:
            os.remove(tmp_path)

    user_prompt = question + extra_context

    # ----------------------------
    # 3. Azure thread management
    # ----------------------------
    if thread_id:
        thread = project_client.agents.threads.get(thread_id=thread_id)
    else:
        thread = project_client.agents.threads.create()

    thread_id = thread.id

    # ----------------------------
    # 4. Store thread + user message
    # ----------------------------
    await get_or_create_thread(thread_id, user_id, question)

    await save_message(
        thread_id=thread_id,
        user_id=user_id,
        sender="user",
        message=question
    )

    # ----------------------------
    # 5. Send message to Azure Agent
    # ----------------------------
    project_client.agents.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_prompt
    )

    run = project_client.agents.runs.create_and_process(
        thread_id=thread_id,
        agent_id=legal_agent.id
    )

    if run.status == "failed":
        raise HTTPException(status_code=500, detail="Agent run failed")

    # ----------------------------
    # 6. Read agent reply
    # ----------------------------
    messages = project_client.agents.messages.list(
        thread_id=thread_id,
        order=ListSortOrder.ASCENDING
    )

    reply_text = ""
    pdf_files = []

    for msg in messages:
        if msg.run_id == run.id and getattr(msg, "text_messages", None):
            reply_text = msg.text_messages[-1].text.value.strip()

    # ----------------------------
    # 7. Optional PDF detection
    # ----------------------------
    pdf_content = extract_pdf_block(reply_text)
    if pdf_content:
        pdf_path = f"generated_{thread_id}.pdf"
        create_pdf_from_text(pdf_content, pdf_path)
        pdf_files.append(f"download/{pdf_path}")

    # ----------------------------
    # 8. Save agent response
    # ----------------------------
    await save_message(
        thread_id=thread_id,
        user_id=user_id,
        sender="agent",
        message=reply_text
    )

    clean_text = re.sub(
        r"\[PDF_DOCUMENT\](.*?)\[/PDF_DOCUMENT\]",
        "",
        reply_text,
        flags=re.DOTALL
    ).strip()

    # ----------------------------
    # 9. Final response
    # ----------------------------
    return {
        "answer": clean_text,
        "pdf_files": pdf_files,
        "thread_id": thread_id,
        "status": "success"
    }
