from fastapi import APIRouter, Request, HTTPException
from bson import ObjectId
from db import chat_messages, chat_threads
from tools.logger import get_logger, user_id_ctx
from tools.decorators import log_function_call

logger = get_logger("chat_routes")

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.get("/threads")
@log_function_call
async def get_user_threads(request: Request):
    user = request.state.user
    if not user:
        logger.warning("Unauthorized access to get_user_threads")
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user.get("sub")
    user_id_ctx.set(str(user_id))
    
    try:
        # SAFE: _id is always indexed in Cosmos
        cursor = chat_threads.find(
            {"user_id": user_id}
        ).sort("_id", -1)

        threads = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            threads.append(doc)

        return threads
    except Exception as e:
        logger.error(f"Failed to fetch threads for user {user_id}: {e}", exc_info=True)
        raise e


# ===============================
# GET THREAD MESSAGES
# ===============================
@router.get("/messages/{thread_id}")
@log_function_call
async def get_thread_messages(thread_id: str, request: Request):
    user = request.state.user
    if not user:
         logger.warning("Unauthorized access to get_thread_messages")
         raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user.get("sub")
    user_id_ctx.set(str(user_id))

    try:
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
    except Exception as e:
        logger.error(f"Failed to fetch messages for thread {thread_id}: {e}", exc_info=True)
        raise e