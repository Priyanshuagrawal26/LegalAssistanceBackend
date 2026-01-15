from datetime import datetime
from db import chat_threads
from db import chat_messages
from tools.logger import get_logger
from tools.decorators import log_function_call

logger = get_logger("history_service")

@log_function_call
async def get_or_create_thread(thread_id: str, user_id: str, question: str):
    try:
        thread = await chat_threads.find_one({
            "thread_id": thread_id,
            "user_id": user_id
        })

        if not thread:
            await chat_threads.insert_one({
                "thread_id": thread_id,
                "user_id": user_id,
                "title": question[:50],
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
            logger.info(f"Created new thread: {thread_id} for user: {user_id}")
    except Exception as e:
        logger.error(f"Failed to get/create thread: {e}", exc_info=True)
        raise e
        
@log_function_call
async def save_message(thread_id, user_id, sender, message):
    try:
        await chat_messages.insert_one({
            "thread_id": thread_id,
            "user_id": user_id,
            "sender": sender,
            "message": message,
            "created_at": datetime.utcnow()
        })
    except Exception as e:
        logger.error(f"Failed to save message to thread {thread_id}: {e}", exc_info=True)
        raise e