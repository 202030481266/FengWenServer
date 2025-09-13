from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr
from sqlalchemy import Column, Integer, String, Text, DateTime, Index

from src.fengwen2.database import Base


# SQLAlchemy models (database tables)
class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    image_url = Column(String(500))  # URL may be very long
    redirect_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 添加表级配置
    __table_args__ = (
        Index('idx_product_name', 'name'),
    )


class TranslationPair(Base):
    __tablename__ = "translation_pairs"

    id = Column(Integer, primary_key=True, index=True)
    chinese_text = Column(Text, nullable=False)
    english_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# Pydantic models (API request/response models)
class UserInfoRequest(BaseModel):
    name: str
    email: EmailStr
    birth_date: str  # YYYY-MM-DD format
    birth_time: str  # HH:MM format
    gender: str  # "Male" or "Female"

    class Config:
        # Pydantic v2 配置
        str_strip_whitespace = True  # 自动去除字符串两端空白
        str_min_length = 1  # 确保字符串不为空


class UserInfoWithVerificationRequest(BaseModel):
    name: str
    email: EmailStr
    birth_date: str  # YYYY-MM-DD format
    birth_time: str  # HH:MM format
    gender: str  # "Male" or "Female"
    verification_code: str

    class Config:
        str_strip_whitespace = True
        str_min_length = 1


class EmailRequest(BaseModel):
    email: EmailStr

    class Config:
        str_strip_whitespace = True


class VerificationRequest(BaseModel):
    email: EmailStr
    code: str

    class Config:
        str_strip_whitespace = True
        str_min_length = 1


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    image_url: Optional[str] = None
    redirect_url: Optional[str] = None

    class Config:
        str_strip_whitespace = True


class TranslationPairRequest(BaseModel):
    chinese_text: str
    english_text: str

    class Config:
        str_strip_whitespace = True
        str_min_length = 1


class TranslationPairUpdate(BaseModel):
    chinese_text: str
    english_text: str

    class Config:
        str_strip_whitespace = True
        str_min_length = 1


class CreatePaymentLinkRequest(BaseModel):
    record_id: int


class PaymentLinkResponse(BaseModel):
    shopify_url: str
