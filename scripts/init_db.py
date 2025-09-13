"""
数据库初始化脚本
用于创建数据库表和初始数据
"""

import logging
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def init_database():
    """初始化数据库"""
    from src.fengwen2.database import engine, create_tables, check_database_connection
    from src.fengwen2.database import SessionLocal, SiteConfig

    logger.info("Starting database initialization...")

    # 1. 检查数据库连接
    if not check_database_connection():
        logger.error("Cannot connect to database. Please check your configuration.")
        return False

    # 2. 创建表
    try:
        create_tables()
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating tables: {e}")
        return False

    # 3. 插入初始配置数据（如果需要）
    try:
        db = SessionLocal()

        # 检查是否已有配置
        existing_config = db.query(SiteConfig).first()
        if not existing_config:
            # 添加默认配置
            default_configs = [
                SiteConfig(
                    config_key="site_title",
                    config_value="Astrology Fortune",
                    updated_at=datetime.utcnow()
                ),
                SiteConfig(
                    config_key="maintenance_mode",
                    config_value="false",
                    updated_at=datetime.utcnow()
                ),
                SiteConfig(
                    config_key="max_records_per_email",
                    config_value="10",
                    updated_at=datetime.utcnow()
                )
            ]

            for config in default_configs:
                db.add(config)

            db.commit()
            logger.info("Default configurations added")
        else:
            logger.info("Configurations already exist, skipping...")

        db.close()

    except Exception as e:
        logger.error(f"Error adding initial data: {e}")
        return False

    # 4. 验证表创建
    try:
        with engine.connect() as conn:
            # 检查表是否存在
            if engine.dialect.name == 'postgresql':
                result = conn.execute(text("""
                                           SELECT table_name
                                           FROM information_schema.tables
                                           WHERE table_schema = 'public'
                                           """))
            else:  # SQLite
                result = conn.execute(text("""
                                           SELECT name
                                           FROM sqlite_master
                                           WHERE type = 'table'
                                           """))

            tables = [row[0] for row in result]
            logger.info(f"Created tables: {tables}")

            # 验证必要的表是否存在
            required_tables = ['astrology_records', 'site_config', 'products', 'translation_pairs']
            missing_tables = [t for t in required_tables if t not in tables]

            if missing_tables:
                logger.error(f"Missing required tables: {missing_tables}")
                return False

    except Exception as e:
        logger.error(f"Error verifying tables: {e}")
        return False

    logger.info("Database initialization completed successfully!")
    return True


def reset_database(confirm=False):
    """重置数据库（删除所有表后重新创建）"""
    if not confirm:
        response = input("WARNING: This will delete all data! Type 'YES' to confirm: ")
        if response != 'YES':
            logger.info("Database reset cancelled")
            return False

    from src.fengwen2.database import drop_tables

    logger.warning("Resetting database...")

    try:
        drop_tables()
        logger.info("All tables dropped")

        return init_database()

    except Exception as e:
        logger.error(f"Error resetting database: {e}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Database initialization script')
    parser.add_argument('--reset', action='store_true', help='Reset database (delete all data)')
    parser.add_argument('--force', action='store_true', help='Skip confirmation prompts')

    args = parser.parse_args()

    if args.reset:
        success = reset_database(confirm=args.force)
    else:
        success = init_database()

    sys.exit(0 if success else 1)
