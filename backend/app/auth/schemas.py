from pydantic import BaseModel, EmailStr, field_validator
from uuid import UUID
from datetime import datetime


class UserRegister(BaseModel):
    email: EmailStr
    password: str
    tos_accepted: bool

    @field_validator("tos_accepted")
    @classmethod
    def tos_must_be_accepted(cls, v):
        if not v:
            raise ValueError("Terms of Service must be accepted")
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    email_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenRequest(BaseModel):
    token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordReset(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v
