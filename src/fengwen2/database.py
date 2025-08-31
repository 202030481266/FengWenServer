import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./astrology.db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class AstrologyRecord(Base):
    __tablename__ = "astrology_records"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)  # Not unique, allow multiple entries per email
    name = Column(String, nullable=False)
    birth_date = Column(DateTime, nullable=False)
    birth_time = Column(String, nullable=False)  # Birth time (hours:minutes)
    gender = Column(String, nullable=False)  # Male/Female
    lunar_date = Column(String)

    # Store astrology API results
    full_result_zh = Column(Text)
    full_result_en = Column(Text)

    # Payment status
    is_purchased = Column(Boolean, default=False)
    shopify_order_id = Column(String)

    created_at = Column(DateTime, nullable=False)


class SiteConfig(Base):
    __tablename__ = "site_config"

    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String, unique=True, nullable=False)
    config_value = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False)


def create_tables():
    from src.fengwen2.admin_models import Product, TranslationPair
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
