from fastapi import APIRouter, Request, HTTPException
from bson import ObjectId
from db import chat_messages, chat_threads
router = APIRouter(prefix="/chat", tags=["Chat"])

@router.get("/threads")
async def get_user_threads(request: Request):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user.get("sub")

    # SAFE: _id is always indexed in Cosmos
    cursor = chat_threads.find(
        {"user_id": user_id}
    ).sort("_id", -1)

    threads = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        threads.append(doc)

    return threads


# ===============================
# GET THREAD MESSAGES
# ===============================
@router.get("/messages/{thread_id}")
async def get_thread_messages(thread_id: str, request: Request):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user.get("sub")

    # ✅ SAFE: sorting by _id instead of created_at
    cursor = chat_messages.find({
        "thread_id": thread_id,
        "user_id": user_id
    }).sort("_id", 1)

    messages = []
    async for msg in cursor:
        msg["_id"] = str(msg["_id"])
        messages.append(msg)

    return messages