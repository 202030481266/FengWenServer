from typing import Optional

from pydantic import BaseModel, EmailStr


class UserInfoRequest(BaseModel):
    name: str
    email: EmailStr
    birth_date: str  # YYYY-MM-DD format
    birth_time: str  # HH:MM format
    gender: str  # "Male" or "Female"

class UserInfoWithVerificationRequest(BaseModel):
    name: str
    email: EmailStr
    birth_date: str  # YYYY-MM-DD format
    birth_time: str  # HH:MM format
    gender: str  # "Male" or "Female"
    verification_code: str

class EmailRequest(BaseModel):
    email: EmailStr

class VerificationRequest(BaseModel):
    email: EmailStr
    code: str

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    image_url: Optional[str] = None
    redirect_url: Optional[str] = None

class TranslationPair(BaseModel):
    chinese_text: str
    english_text: str

class TranslationPairUpdate(BaseModel):
    chinese_text: str
    english_text: str