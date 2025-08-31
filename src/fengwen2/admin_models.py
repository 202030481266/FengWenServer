from typing import Optional

from pydantic import BaseModel, EmailStr
from sqlalchemy import Column, Integer, String, Text

from src.fengwen2.database import Base

# SQLAlchemy models (database tables)
class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    image_url = Column(String)
    redirect_url = Column(String)

class TranslationPair(Base):
    __tablename__ = "translation_pairs"
    
    id = Column(Integer, primary_key=True, index=True)
    chinese_text = Column(Text, nullable=False)
    english_text = Column(Text, nullable=False)

# Pydantic models (API request/response models)
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

class TranslationPairRequest(BaseModel):
    chinese_text: str
    english_text: str

class TranslationPairUpdate(BaseModel):
    chinese_text: str
    english_text: str