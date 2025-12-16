from datetime import datetime
from db import chat_threads
from db import chat_messages

async def get_or_create_thread(thread_id: str, user_id: str, question: str):
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
        
async def save_message(thread_id, user_id, sender, message):
    await chat_messages.insert_one({
        "thread_id": thread_id,
        "user_id": user_id,
        "sender": sender,
        "message": message,
        "created_at": datetime.utcnow()
    })