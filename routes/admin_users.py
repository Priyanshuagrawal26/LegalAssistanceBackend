from fastapi import APIRouter, Depends, HTTPException, Request, status
from bson import ObjectId
from typing import List
import time

from auth.middleware import get_current_user
from auth.db import users_collection
from tools.logger import get_logger, user_id_ctx
from tools.decorators import log_function_call

logger = get_logger("admin_users")

router = APIRouter(prefix="/admin/users", tags=["Admin Users"])

def ensure_admin(user: dict):
    roles = [r.lower() for r in user.get("roles", [])]
    if "admin" not in roles:
        logger.warning(f"Access denied: User {user.get('email')} is not admin")
        raise HTTPException(status_code=403, detail="Admin access required")
 
@router.get("")
@log_function_call
def list_all_users(
    request: Request,
    user=Depends(get_current_user)
):
    """
    Admin-only: Return all users with stats
    """
    ensure_admin(user)
    user_id_ctx.set(str(user.get("sub")))

    try:
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
                status_val = "inactive"
            else:
                status_val = "active"

            users.append({
                "id": str(u["_id"]),
                "name": u.get("full_name", "—"),
                "email": u["email"],
                "role": u.get("roles", ["user"])[0],
                "status": status_val,
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
    except Exception as e:
        logger.error(f"Failed to list users: {e}", exc_info=True)
        raise e

@router.delete("/{user_id}")
@log_function_call
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
    user_id_ctx.set(str(user.get("sub")))

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
        logger.warning(f"Admin {user.get('email')} attempted to delete themselves")
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
        logger.warning(f"Attempt to delete admin user {target_user.get('email')}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin users cannot be deleted"
        )

    # ----------------------------
    # Delete user
    # ----------------------------
    try:
        users_collection.delete_one({"_id": target_user_id})
        logger.info(f"User {target_user.get('email')} deleted by admin {user.get('email')}")

        return {
            "status": "success",
            "message": "User deleted successfully",
            "user": {
                "id": user_id,
                "email": target_user.get("email"),
                "name": target_user.get("full_name"),
            }
        }
    except Exception as e:
        logger.error(f"Failed to delete user {user_id}: {e}", exc_info=True)
        raise e

@router.get("/dashboard/stats")
@log_function_call
def admin_dashboard_stats(user=Depends(get_current_user)):
    """
    Admin dashboard statistics:
    - total users
    - total templates
    - approved templates
    - pending templates
    - rejected templates
    """
    ensure_admin(user)
    user_id_ctx.set(str(user.get("sub")))

    try:
        # ----------------------------
        # TOTAL USERS
        # ----------------------------
        total_users = users_collection.count_documents({})

        # ----------------------------
        # AGGREGATE TEMPLATE STATS
        # ----------------------------
        pipeline = [
            {"$unwind": {"path": "$templates", "preserveNullAndEmptyArrays": False}},
            {
                "$group": {
                    "_id": "$templates.status",
                    "count": {"$sum": 1}
                }
            }
        ]

        result = list(users_collection.aggregate(pipeline))

        total_templates = 0
        approved = 0
        pending = 0
        rejected = 0

        for r in result:
            status_key = (r["_id"] or "").lower()
            count = r["count"]

            total_templates += count

            if status_key == "approved":
                approved = count
            elif status_key == "pending":
                pending = count
            elif status_key == "rejected":
                rejected = count

        return {
            "status": "success",
            "data": {
                "users": total_users,
                "templates": {
                    "total": total_templates,
                    "approved": approved,
                    "pending": pending,
                    "rejected": rejected
                }
            }
        }

    except Exception as e:
        logger.error(f"Failed to load admin dashboard stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load admin dashboard stats"
        )