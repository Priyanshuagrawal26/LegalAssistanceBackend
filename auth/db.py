import os
import pymongo
from bson import ObjectId
from fastapi import HTTPException, status
from dotenv import load_dotenv

load_dotenv()

client = pymongo.MongoClient(os.getenv("MONGO_URI"))
db = client[os.getenv("MONGO_DB_NAME", "Legal_Assistance")]

# Access your "users" collection
users_collection = db["users"]

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        try:
            return ObjectId(str(v))
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Invalid ID"
            )
