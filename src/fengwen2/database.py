import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, Index, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# backup config
if not DATABASE_URL:
    DB_TYPE = os.getenv("DB_TYPE", "postgresql")
    DB_USER = os.getenv("DB_USER", "astrology_user")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "your_secure_password")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "astrology_db")

    if DB_TYPE == "sqlite":
        # Use for development
        DATABASE_URL = f"sqlite:///./astrology.db"
    else:
        DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=os.getenv("DB_ECHO", "false").lower() == "true"
    )
else:
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
        echo=os.getenv("DB_ECHO", "false").lower() == "true",  # SQL 日志
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000"  # 30秒查询超时
        }
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class AstrologyRecord(Base):
    __tablename__ = "astrology_records"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), index=True, nullable=False)  # PostgreSQL recommend length
    name = Column(String(255), nullable=False)
    birth_date = Column(DateTime, nullable=False)
    birth_time = Column(String(10), nullable=False)  # Birth time (hours:minutes)
    gender = Column(String(10), nullable=False)  # Male/Female
    lunar_date = Column(String(50))

    # Store astrology API results
    full_result_zh = Column(Text)
    full_result_en = Column(Text)

    # Payment status
    is_purchased = Column(Boolean, default=False, nullable=False)
    shopify_order_id = Column(String(255))

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # improve performance for query
    __table_args__ = (
        Index('idx_email_created', 'email', 'created_at'),
        Index('idx_purchased_created', 'is_purchased', 'created_at'),
    )


class SiteConfig(Base):
    __tablename__ = "site_config"

    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(100), unique=True, nullable=False, index=True)
    config_value = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


def create_tables():
    """创建所有表"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        raise


def drop_tables():
    """删除所有表（谨慎使用）"""
    try:
        Base.metadata.drop_all(bind=engine)
        logger.info("Database tables dropped successfully")
    except Exception as e:
        logger.error(f"Error dropping database tables: {e}")
        raise


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection():
    """检查数据库连接是否正常"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False
