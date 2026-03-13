import secrets
from datetime import datetime, timedelta
from uuid import UUID

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: UUID) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


async def register_user(db: AsyncSession, email: str, password: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise ValueError("Email already registered")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        tos_accepted_at=datetime.utcnow(),
        email_verification_token=generate_token(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # MVP: log verification URL to stdout
    print(f"[EMAIL STUB] Verify email: http://localhost:5173/verify?token={user.email_verification_token}")

    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


async def verify_email(db: AsyncSession, token: str) -> bool:
    result = await db.execute(
        select(User).where(User.email_verification_token == token)
    )
    user = result.scalar_one_or_none()
    if not user:
        return False
    user.email_verified = True
    user.email_verification_token = None
    await db.commit()
    return True


async def request_password_reset(db: AsyncSession, email: str) -> None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return  # Don't leak whether email exists

    user.password_reset_token = generate_token()
    user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
    await db.commit()

    # MVP: log reset URL to stdout
    print(f"[EMAIL STUB] Reset password: http://localhost:5173/reset-password?token={user.password_reset_token}")


async def reset_password(db: AsyncSession, token: str, new_password: str) -> bool:
    result = await db.execute(
        select(User).where(User.password_reset_token == token)
    )
    user = result.scalar_one_or_none()
    if not user:
        return False
    if user.password_reset_expires and user.password_reset_expires < datetime.utcnow():
        return False

    user.hashed_password = hash_password(new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    await db.commit()
    return True
