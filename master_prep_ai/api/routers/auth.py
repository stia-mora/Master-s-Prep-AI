"""Authentication routes for local Master Prep AI users."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from master_prep_ai.auth import (
    AuthUser,
    clear_cookie,
    get_auth_store,
    issue_cookie,
    require_current_user,
)

router = APIRouter()


class AuthCredentials(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


@router.get("/bootstrap")
async def bootstrap() -> dict[str, bool]:
    return {"has_users": get_auth_store().has_users()}


@router.post("/register-first-admin")
async def register_first_admin(payload: AuthCredentials, response: Response) -> dict[str, object]:
    store = get_auth_store()
    user = store.create_first_admin(payload.email, payload.password, payload.display_name)
    token = store.create_session(user.user_id)
    issue_cookie(response, token)
    return {"user": user.to_dict()}


@router.post("/register")
async def register(payload: AuthCredentials, response: Response) -> dict[str, object]:
    store = get_auth_store()
    user = store.create_user(payload.email, payload.password, payload.display_name)
    token = store.create_session(user.user_id)
    issue_cookie(response, token)
    return {"user": user.to_dict()}


@router.post("/login")
async def login(payload: AuthCredentials, response: Response) -> dict[str, object]:
    store = get_auth_store()
    user = store.authenticate(payload.email, payload.password)
    if user is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = store.create_session(user.user_id)
    issue_cookie(response, token)
    return {"user": user.to_dict()}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    get_auth_store().revoke_session(request.cookies.get("master_prep_ai_session") or "")
    clear_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(user: AuthUser = Depends(require_current_user)) -> dict[str, object]:
    return {"user": user.to_dict()}


@router.post("/change-password")
async def change_password(payload: ChangePasswordRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, bool]:
    get_auth_store().change_password(user.user_id, payload.current_password, payload.new_password)
    return {"ok": True}