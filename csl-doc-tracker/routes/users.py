"""
User management API routes.
- /api/me — current user profile + change password
- /api/users — admin CRUD
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

import auth

router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────────
class ChangePasswordReq(BaseModel):
    current_password: str
    new_password: str

class CreateUserReq(BaseModel):
    username: str
    email: str
    password: str
    role: str = "rep"
    rep_name: Optional[str] = None

class UpdateUserReq(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    rep_name: Optional[str] = None
    is_active: Optional[bool] = None

class ResetPasswordReq(BaseModel):
    new_password: str


def _get_user(request: Request) -> dict | None:
    return getattr(request.state, "user", None)


def _require_admin(request: Request):
    user = _get_user(request)
    if not user or user.get("role") != "admin":
        return JSONResponse({"error": "admin required"}, status_code=403)
    return None


# ── /api/me ──────────────────────────────────────────────────────────────
@router.get("/api/me")
def get_me(request: Request):
    user = _get_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    full = auth.get_user(user["user_id"])
    if not full:
        return JSONResponse({"error": "user not found"}, status_code=404)
    return {
        "id": full["id"],
        "username": full["username"],
        "email": full["email"],
        "role": full["role"],
        "rep_name": full["rep_name"],
    }


@router.post("/api/me/change-password")
def change_my_password(request: Request, body: ChangePasswordReq):
    user = _get_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if len(body.new_password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters"}, status_code=400)
    ok = auth.change_password(user["user_id"], body.current_password, body.new_password)
    if not ok:
        return JSONResponse({"error": "Current password is incorrect"}, status_code=400)
    return {"ok": True}


# ── /api/users (admin) ───────────────────────────────────────────────────
@router.get("/api/users")
def list_users(request: Request):
    err = _require_admin(request)
    if err:
        return err
    users = auth.list_users()
    # Serialize datetimes
    for u in users:
        for k in ("created_at", "last_login"):
            if u.get(k):
                u[k] = u[k].isoformat()
    return users


@router.post("/api/users")
def create_user(request: Request, body: CreateUserReq):
    err = _require_admin(request)
    if err:
        return err
    if len(body.password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters"}, status_code=400)
    try:
        user = auth.create_user(body.username, body.email, body.password, body.role, body.rep_name)
        for k in ("created_at", "last_login"):
            if user.get(k):
                user[k] = user[k].isoformat()
        return user
    except Exception as e:
        if "duplicate key" in str(e).lower():
            return JSONResponse({"error": "Username already exists"}, status_code=409)
        raise


@router.patch("/api/users/{user_id}")
def update_user(request: Request, user_id: int, body: UpdateUserReq):
    err = _require_admin(request)
    if err:
        return err
    user = auth.update_user(user_id, **body.dict(exclude_none=True))
    if not user:
        return JSONResponse({"error": "user not found"}, status_code=404)
    for k in ("created_at", "last_login"):
        if user.get(k):
            user[k] = user[k].isoformat()
    return user


@router.post("/api/users/{user_id}/reset-password")
def reset_password(request: Request, user_id: int, body: ResetPasswordReq):
    err = _require_admin(request)
    if err:
        return err
    if len(body.new_password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters"}, status_code=400)
    ok = auth.admin_reset_password(user_id, body.new_password)
    if not ok:
        return JSONResponse({"error": "user not found"}, status_code=404)
    return {"ok": True}


@router.delete("/api/users/{user_id}")
def deactivate_user(request: Request, user_id: int):
    err = _require_admin(request)
    if err:
        return err
    user = _get_user(request)
    if user["user_id"] == user_id:
        return JSONResponse({"error": "Cannot deactivate yourself"}, status_code=400)
    result = auth.update_user(user_id, is_active=False)
    if not result:
        return JSONResponse({"error": "user not found"}, status_code=404)
    return {"ok": True}
