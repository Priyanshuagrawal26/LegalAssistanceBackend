from fastapi import APIRouter, Depends, HTTPException, Request, status
from bson import ObjectId
from typing import List
import time

from auth.middleware import get_current_user
from auth.db import users_collection

router = APIRouter(prefix="/admin/users", tags=["Admin Users"])

def ensure_admin(user: dict):
    roles = [r.lower() for r in user.get("roles", [])]
    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Admin access required")
 
@router.get("")
def list_all_users(
    request: Request,
    user=Depends(get_current_user)
):
    """
    Admin-only: Return all users with stats
    """
    ensure_admin(user)

    cursor = users_collection.find(
        {},
        {
            "email": 1,
            "full_name": 1,
            "roles": 1,
            "is_verified": 1,
            "created_at": 1,
            "templates": 1,
            "token_usage": 1,
        }
    )

    users = []

    for u in cursor:
        templates = u.get("templates", [])
        token_usage = u.get("token_usage", {})

        # Status mapping (frontend-compatible)
        if not u.get("is_verified"):
            status = "inactive"
        else:
            status = "active"

        users.append({
            "id": str(u["_id"]),
            "name": u.get("full_name", "—"),
            "email": u["email"],
            "role": u.get("roles", ["user"])[0],
            "status": status,
            "joinDate": u.get("created_at", int(time.time())),
            "templatesCount": len(templates),
            "tokenUsage": {
                "used": token_usage.get("total_tokens", 0),
                "limit": 100000  # static for now, can be dynamic later
            }
        })
    
    return {
        "status": "success",
        "users": users
    }

@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    request: Request,
    user=Depends(get_current_user)
):
    """
    Admin-only: Permanently delete a user
    - Admin users cannot be deleted
    - Admin cannot delete himself
    """
    ensure_admin(user)

    # ----------------------------
    # Validate user_id
    # ----------------------------
    if not ObjectId.is_valid(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID"
        )

    target_user_id = ObjectId(user_id)

    # ----------------------------
    # Prevent admin deleting himself
    # ----------------------------
    if str(target_user_id) == user.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin cannot delete himself"
        )

    # ----------------------------
    # Fetch target user
    # ----------------------------
    target_user = users_collection.find_one({"_id": target_user_id})

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # ----------------------------
    # Prevent deleting admin users
    # ----------------------------
    target_roles = [r.lower() for r in target_user.get("roles", [])]

    if "admin" in target_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin users cannot be deleted"
        )

    # ----------------------------
    # Delete user
    # ----------------------------
    users_collection.delete_one({"_id": target_user_id})

    return {
        "status": "success",
        "message": "User deleted successfully",
        "user": {
            "id": user_id,
            "email": target_user.get("email"),
            "name": target_user.get("full_name"),
        }
    }
