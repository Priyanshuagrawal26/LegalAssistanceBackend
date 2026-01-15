import os
import tempfile
import asyncio
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import fitz as pymupdf
import docx
import json
from auth.routes import router as auth_router
from auth.middleware import JWTMiddleware
from fastapi.responses import FileResponse
# ---------------------- AUTH + SESSION ----------------------
from auth.routes import router as auth_router
from auth.middleware import JWTMiddleware
from routes.chat_routes import router as chat_router
from models.user import UserModel
import re
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from bson import ObjectId
# -------------------------- AZURE ---------------------------
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from services.history import get_or_create_thread, save_message
import logging
from routes.templates_router import router as templates_router
from auth.db import users_collection
from dotenv import load_dotenv
from routes.admin_users import router as admin_users_router
from tools.serpapi import serpapi_search
from tools.logger import get_logger, user_id_ctx
from middleware.logging_middleware import RequestLoggingMiddleware
from tools.decorators import log_function_call

# -------------------------------------------------
# ENV & LOGGER
# -------------------------------------------------
load_dotenv()
logger = get_logger("app")

# ================================================================
#                     INIT FASTAPI APP
# ================================================================
app = FastAPI()

app.add_middleware(RequestLoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://lexiaifrontend.azurewebsites.net",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(JWTMiddleware)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(templates_router)
app.include_router(admin_users_router)

project_client = None
legal_agent = None

# ================================================================
#                        Azure Setup
# ================================================================
@app.on_event("startup")
async def startup_event():
    global project_client, legal_agent

    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("azure.identity").setLevel(logging.WARNING)
    logging.getLogger("azure.core").setLevel(logging.WARNING)

    try:
        project_client = AIProjectClient(
            endpoint=os.getenv("AGENT_ENDPOINT"),
            credential=DefaultAzureCredential()
        )

        legal_agent = project_client.agents.get_agent(
            agent_id=os.getenv("LEGAL_AGENT_ID")
        )

        logger.info("✅ Azure AI Agent initialized at startup")
    except Exception as e:
        logger.critical(f"Failed to initialize Azure AI Agent: {e}", exc_info=True)


# ================================================================
#                     DOCUMENT PROCESSING
# ================================================================
@log_function_call
def extract_text_from_pdf(file_path: str) -> str:
    try:
        text = ""
        with pymupdf.open(file_path) as pdf:
            for page in pdf:
                text += page.get_text()
        return text
    except Exception as e:
        logger.error(f"Error processing PDF: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {e}")

@log_function_call
def extract_pdf_block(text: str):
    """Extracts content inside [PDF_DOCUMENT] tags."""
    match = re.search(r"\[PDF_DOCUMENT\](.*?)\[/PDF_DOCUMENT\]", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


@log_function_call
def create_pdf_from_text(text: str, output_path: str):
    """Creates a PDF file from plain text."""
    try:
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
    except Exception as e:
        logger.error(f"Error creating PDF: {e}", exc_info=True)
        raise e

@log_function_call
def extract_text_from_docx(file_path: str) -> str:
    try:
        doc = docx.Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        logger.error(f"Error processing DOCX: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing DOCX: {e}")


@log_function_call
def extract_text_from_txt(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error processing TXT: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing TXT: {e}")


@log_function_call
def extract_text(file_path: str, filename: str) -> str:
    ext = filename.lower().split(".")[-1]
    if ext == "pdf": return extract_text_from_pdf(file_path)
    if ext in ["doc", "docx"]: return extract_text_from_docx(file_path)
    if ext == "txt": return extract_text_from_txt(file_path)
    return ""


# ================================================================
#                           MAIN ENDPOINT
# ================================================================
@app.post("/query")
async def query_endpoint(
    request: Request,
    question: str = Form(...),
    thread_id: Optional[str] = Form(None),
    user_file: Optional[UploadFile] = File(None)
):
    logger.info("📩 /query endpoint hit")
    
    if not legal_agent:
        logger.error("Legal agent not initialized")
        raise HTTPException(status_code=503, detail="AI Service is currently unavailable. Please try again later.")

    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        logger.warning("Unauthorized access attempt to /query")
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Update context var for logging
    user_id_ctx.set(str(user_id))

    # ----------------------------
    # 2. Extract upload file text (optional)
    # ----------------------------
    extra_context = ""

    if user_file:
        with tempfile.NamedTemporaryFile(delete=False,
                                         suffix=os.path.splitext(user_file.filename)[1]) as tmp:
            tmp.write(await user_file.read())
            tmp_path = tmp.name

        try:
            file_text = extract_text(tmp_path, user_file.filename)
            extra_context = f"\n\nUser provided document context:\n{file_text[:3000]}"
        except Exception as e:
            logger.error(f"Failed to extract text from uploaded file: {e}", exc_info=True)
            pass 
        finally:
            os.remove(tmp_path)

    user_prompt = question + extra_context

    # ----------------------------
    # 3. Azure Thread
    # ----------------------------
    try:
        if thread_id:
            thread = project_client.agents.threads.get(thread_id=thread_id)
        else:
            thread = project_client.agents.threads.create()
        thread_id = thread.id
    except Exception as e:
        logger.error(f"Failed to get/create Azure thread: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Azure Agent Thread Error")

    # ----------------------------
    # 4. Save user message
    # ----------------------------
    try:
        await get_or_create_thread(thread_id, user_id, question)
        await save_message(
            thread_id=thread_id,
            user_id=user_id,
            sender="user",
            message=question
        )
    except Exception as e:
        logger.error(f"Database error saving message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database Error")

    # ----------------------------
    # 5. Send Azure request
    # ----------------------------
    project_client.agents.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_prompt
    )

    run = project_client.agents.runs.create(
       thread_id=thread_id,
       agent_id=legal_agent.id
    )
  
    while run.status in ["queued", "in_progress", "requires_action"]:

     if run.status == "requires_action":
        tool_outputs = []

        for tool_call in run.required_action.submit_tool_outputs.tool_calls:

            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            logger.info(f"🛠 Executing tool: {function_name} | function_arg={arguments}")

            if function_name == "serpapi_search":
                try:
                    output = serpapi_search(**arguments)
                except Exception as e:
                    logger.error(f"Tool execution failed: {function_name} error={e}", exc_info=True)
                    output = {"error": str(e)}

                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                     "output": json.dumps(output, ensure_ascii=False)
                })

        run = project_client.agents.runs.submit_tool_outputs(
            thread_id=thread_id,
            run_id=run.id,
            tool_outputs=tool_outputs
        )

     else:
        await asyncio.sleep(1)  # Add sleep to avoid busy-wait and high CPU usage
        run = project_client.agents.runs.get(
            thread_id=thread_id,
            run_id=run.id
        )
    

    # ----------------------------
    # 6. Token Usage Tracking
    # ----------------------------
    usage = run.usage or {}
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

    logger.info(f"[TOKEN USAGE] prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}")

    # Update user's total token usage
    try:
        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$inc": {
                    "token_usage.prompt_tokens": prompt_tokens,
                    "token_usage.completion_tokens": completion_tokens,
                    "token_usage.total_tokens": total_tokens
                }
            }
        )
    except Exception as e:
        logger.error(f"Failed to save token usage: {e}", exc_info=True)

    if run.status == "failed":
        logger.error(f"Agent run failed: {run.last_error}")
        raise HTTPException(status_code=500, detail="Agent run failed")

    # ----------------------------
    # 7. Read agent's message
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
            break

    # ----------------------------
    # 8. Detect Optional PDF
    # ----------------------------
    pdf_content = extract_pdf_block(reply_text)
    if pdf_content:
        pdf_path = f"generated_{thread_id}.pdf"
        try:
            create_pdf_from_text(pdf_content, pdf_path)
            pdf_files.append(f"download/{pdf_path}")
        except Exception as e:
            logger.error(f"Failed to generate PDF: {e}", exc_info=True)

    # ----------------------------
    # 9. Save agent reply
    # ----------------------------
    try:
        await save_message(
            thread_id=thread_id,
            user_id=user_id,
            sender="agent",
            message=reply_text
        )
    except Exception as e:
        logger.error(f"Failed to save agent message: {e}", exc_info=True)

    clean_text = re.sub(
        r"\[PDF_DOCUMENT\](.*?)\[/PDF_DOCUMENT\]",
        "",
        reply_text,
        flags=re.DOTALL
    ).strip()

    return {
        "answer": clean_text,
        "pdf_files": pdf_files,
        "thread_id": thread_id,
        "status": "success",
        "token_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens
        }
    }