from sqlalchemy import Column, Integer, String, Text

from src.fengwen2.database import Base


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