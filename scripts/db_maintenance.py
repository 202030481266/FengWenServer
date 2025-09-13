#!/usr/bin/env python3
"""
PostgreSQL 数据库维护脚本
建议通过 cron 定期运行
"""

import logging
import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_engine():
    """获取数据库引擎"""
    db_user = os.getenv("DB_USER", "astrology_user")
    db_password = os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "astrology_db")

    database_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    return create_engine(database_url)


def vacuum_analyze():
    """执行 VACUUM ANALYZE 优化数据库"""
    logger.info("Starting VACUUM ANALYZE...")
    engine = get_engine()

    try:
        with engine.connect() as conn:
            # 需要 autocommit 模式来执行 VACUUM
            conn.execute(text("COMMIT"))
            conn.execute(text("VACUUM ANALYZE"))
            logger.info("VACUUM ANALYZE completed successfully")
    except Exception as e:
        logger.error(f"VACUUM ANALYZE failed: {e}")
        raise


def clean_old_records(days=90):
    """清理旧的未购买记录"""
    logger.info(f"Cleaning unpurchased records older than {days} days...")
    engine = get_engine()

    try:
        with engine.connect() as conn:
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            # 删除旧的未购买记录
            result = conn.execute(
                text("""
                     DELETE
                     FROM astrology_records
                     WHERE is_purchased = false
                       AND created_at < :cutoff_date
                     """),
                {"cutoff_date": cutoff_date}
            )

            deleted_count = result.rowcount
            conn.commit()

            logger.info(f"Deleted {deleted_count} old unpurchased records")

    except Exception as e:
        logger.error(f"Failed to clean old records: {e}")
        raise


def analyze_table_sizes():
    """分析表大小和行数"""
    logger.info("Analyzing table sizes...")
    engine = get_engine()

    try:
        with engine.connect() as conn:
            # 获取表大小信息
            result = conn.execute(text("""
                                       SELECT schemaname,
                                              tablename,
                                              pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS size,
                    n_live_tup AS row_count
                                       FROM pg_stat_user_tables
                                       ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
                                       """))

            logger.info("Table sizes:")
            for row in result:
                logger.info(f"  {row.tablename}: {row.size} ({row.row_count} rows)")

    except Exception as e:
        logger.error(f"Failed to analyze table sizes: {e}")
        raise


def check_index_usage():
    """检查索引使用情况"""
    logger.info("Checking index usage...")
    engine = get_engine()

    try:
        with engine.connect() as conn:
            # 查找未使用的索引
            result = conn.execute(text("""
                                       SELECT schemaname,
                                              tablename,
                                              indexname,
                                              idx_scan as index_scans
                                       FROM pg_stat_user_indexes
                                       WHERE schemaname = 'public'
                                       ORDER BY idx_scan ASC
                                       """))

            logger.info("Index usage (low usage indexes might be candidates for removal):")
            for row in result:
                logger.info(f"  {row.tablename}.{row.indexname}: {row.index_scans} scans")

    except Exception as e:
        logger.error(f"Failed to check index usage: {e}")
        raise


def backup_database(backup_dir="/var/backups/postgresql"):
    """创建数据库备份"""
    import subprocess
    from datetime import datetime

    logger.info("Starting database backup...")

    db_name = os.getenv("DB_NAME", "astrology_db")
    db_user = os.getenv("DB_USER", "astrology_user")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")

    # 确保备份目录存在
    os.makedirs(backup_dir, exist_ok=True)

    # 生成备份文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"{db_name}_{timestamp}.sql.gz")

    # 设置 PGPASSWORD 环境变量
    env = os.environ.copy()
    env['PGPASSWORD'] = os.getenv("DB_PASSWORD")

    try:
        # 使用 pg_dump 创建备份并压缩
        dump_cmd = [
            "pg_dump",
            "-h", db_host,
            "-p", db_port,
            "-U", db_user,
            "-d", db_name,
            "--no-password"
        ]

        # 通过管道压缩
        with open(backup_file, 'wb') as f:
            dump_process = subprocess.Popen(
                dump_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env
            )

            gzip_process = subprocess.Popen(
                ["gzip", "-9"],
                stdin=dump_process.stdout,
                stdout=f,
                stderr=subprocess.PIPE
            )

            dump_process.stdout.close()
            gzip_output, gzip_error = gzip_process.communicate()

            if gzip_process.returncode != 0:
                raise Exception(f"Backup failed: {gzip_error.decode()}")

        # 检查备份文件大小
        file_size = os.path.getsize(backup_file)
        logger.info(f"Backup completed: {backup_file} ({file_size:,} bytes)")

        # 清理旧备份（保留最近7天）
        clean_old_backups(backup_dir, days=7)

    except Exception as e:
        logger.error(f"Backup failed: {e}")
        raise


def clean_old_backups(backup_dir, days=7):
    """清理旧的备份文件"""
    logger.info(f"Cleaning backups older than {days} days...")

    cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)

    for filename in os.listdir(backup_dir):
        if filename.endswith('.sql.gz'):
            file_path = os.path.join(backup_dir, filename)
            if os.path.getmtime(file_path) < cutoff_time:
                os.remove(file_path)
                logger.info(f"Removed old backup: {filename}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Database maintenance script')
    parser.add_argument('--vacuum', action='store_true', help='Run VACUUM ANALYZE')
    parser.add_argument('--clean', action='store_true', help='Clean old records')
    parser.add_argument('--analyze', action='store_true', help='Analyze table sizes')
    parser.add_argument('--check-indexes', action='store_true', help='Check index usage')
    parser.add_argument('--backup', action='store_true', help='Create database backup')
    parser.add_argument('--all', action='store_true', help='Run all maintenance tasks')

    args = parser.parse_args()

    if args.all or (not any(vars(args).values())):
        # 运行所有维护任务
        vacuum_analyze()
        clean_old_records()
        analyze_table_sizes()
        check_index_usage()
        backup_database()
    else:
        if args.vacuum:
            vacuum_analyze()
        if args.clean:
            clean_old_records()
        if args.analyze:
            analyze_table_sizes()
        if args.check_indexes:
            check_index_usage()
        if args.backup:
            backup_database()

    logger.info("Maintenance completed")


if __name__ == "__main__":
    main()
