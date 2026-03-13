from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.schemas import (
    PasswordReset,
    PasswordResetRequest,
    TokenRequest,
    UserLogin,
    UserRegister,
    UserResponse,
)
from app.auth.service import (
    authenticate_user,
    create_access_token,
    register_user,
    request_password_reset,
    reset_password,
    verify_email,
)
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    try:
        user = await register_user(db, data.email, data.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return user


@router.post("/login")
async def login(data: UserLogin, response: Response, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, data.email, data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(user.id)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # Set True in production (HTTPS)
        path="/",
        max_age=3600,
    )
    return {"message": "Login successful", "email": user.email}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/verify-email")
async def verify_email_endpoint(data: TokenRequest, db: AsyncSession = Depends(get_db)):
    success = await verify_email(db, data.token)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )
    return {"message": "Email verified"}


@router.post("/request-password-reset")
async def request_reset(data: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    await request_password_reset(db, data.email)
    # Always return 200 — don't leak whether email exists
    return {"message": "If the email exists, a reset link has been sent"}


@router.post("/reset-password")
async def do_reset(data: PasswordReset, db: AsyncSession = Depends(get_db)):
    success = await reset_password(db, data.token, data.new_password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    return {"message": "Password reset successful"}
