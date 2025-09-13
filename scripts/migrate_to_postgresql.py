"""
从 SQLite 迁移到 PostgreSQL 的脚本
只在需要迁移现有数据时使用
"""

import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_data():
    """从 SQLite 迁移数据到 PostgreSQL"""

    # SQLite 源数据库
    sqlite_url = "sqlite:///./astrology.db"
    sqlite_engine = create_engine(sqlite_url)
    SqliteSession = sessionmaker(bind=sqlite_engine)
    sqlite_db = SqliteSession()

    # PostgreSQL 目标数据库
    pg_user = os.getenv("DB_USER", "astrology_user")
    pg_password = os.getenv("DB_PASSWORD")
    pg_host = os.getenv("DB_HOST", "localhost")
    pg_port = os.getenv("DB_PORT", "5432")
    pg_name = os.getenv("DB_NAME", "astrology_db")

    pg_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_name}"
    pg_engine = create_engine(pg_url)
    PgSession = sessionmaker(bind=pg_engine)
    pg_db = PgSession()

    try:
        # 导入模型
        from src.fengwen2.database import AstrologyRecord, SiteConfig, Base
        from src.fengwen2.admin_models import Product, TranslationPair

        # 在 PostgreSQL 中创建表
        Base.metadata.create_all(bind=pg_engine)
        logger.info("PostgreSQL tables created")

        # 迁移 AstrologyRecord
        records = sqlite_db.query(AstrologyRecord).all()
        logger.info(f"Found {len(records)} astrology records to migrate")

        for record in records:
            new_record = AstrologyRecord(
                email=record.email,
                name=record.name,
                birth_date=record.birth_date,
                birth_time=record.birth_time,
                gender=record.gender,
                lunar_date=record.lunar_date,
                full_result_zh=record.full_result_zh,
                full_result_en=record.full_result_en,
                is_purchased=record.is_purchased,
                shopify_order_id=record.shopify_order_id,
                created_at=record.created_at
            )
            pg_db.add(new_record)

        # 迁移 SiteConfig
        configs = sqlite_db.query(SiteConfig).all()
        logger.info(f"Found {len(configs)} site configs to migrate")

        for config in configs:
            new_config = SiteConfig(
                config_key=config.config_key,
                config_value=config.config_value,
                updated_at=config.updated_at
            )
            pg_db.add(new_config)

        # 迁移 Product
        products = sqlite_db.query(Product).all()
        logger.info(f"Found {len(products)} products to migrate")

        for product in products:
            new_product = Product(
                name=product.name,
                image_url=product.image_url,
                redirect_url=product.redirect_url
            )
            pg_db.add(new_product)

        # 迁移 TranslationPair
        translations = sqlite_db.query(TranslationPair).all()
        logger.info(f"Found {len(translations)} translation pairs to migrate")

        for translation in translations:
            new_translation = TranslationPair(
                chinese_text=translation.chinese_text,
                english_text=translation.english_text
            )
            pg_db.add(new_translation)

        # 提交所有更改
        pg_db.commit()
        logger.info("Migration completed successfully!")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        pg_db.rollback()
        raise

    finally:
        sqlite_db.close()
        pg_db.close()


if __name__ == "__main__":
    response = input("This will migrate data from SQLite to PostgreSQL. Continue? (yes/no): ")
    if response.lower() == 'yes':
        migrate_data()
    else:
        logger.info("Migration cancelled")
