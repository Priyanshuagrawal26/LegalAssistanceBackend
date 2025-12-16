from pymongo import MongoClient
import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv("MONGO_URI")
client = AsyncIOMotorClient(MONGO_URI)
db = client["Legal"]  # database name

chat_threads = db.chat_threads
chat_messages = db.chat_messages
