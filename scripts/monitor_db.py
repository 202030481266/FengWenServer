"""
PostgreSQL 数据库监控脚本
监控连接数、查询性能、锁等待等
"""

import os
import sys
import logging
from datetime import datetime

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


def check_connections():
    """检查数据库连接状态"""
    engine = get_engine()

    with engine.connect() as conn:
        # 当前连接数
        result = conn.execute(text("""
                                   SELECT count(*) as total_connections,
                                          count(*)    FILTER (WHERE state = 'active') as active_connections, count(*) FILTER (WHERE state = 'idle') as idle_connections, count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction
                                   FROM pg_stat_activity
                                   WHERE datname = current_database()
                                   """))

        row = result.fetchone()
        logger.info(f"Connections - Total: {row.total_connections}, Active: {row.active_connections}, "
                    f"Idle: {row.idle_connections}, Idle in transaction: {row.idle_in_transaction}")

        # 最大连接数
        result = conn.execute(text("SHOW max_connections"))
        max_conn = result.fetchone()[0]

        usage_percent = (row.total_connections / int(max_conn)) * 100
        logger.info(f"Connection usage: {usage_percent:.1f}% ({row.total_connections}/{max_conn})")

        if usage_percent > 80:
            logger.warning(f"High connection usage: {usage_percent:.1f}%")

        return {
            "total": row.total_connections,
            "active": row.active_connections,
            "idle": row.idle_connections,
            "max": int(max_conn),
            "usage_percent": usage_percent
        }


def check_slow_queries(threshold_ms=1000):
    """检查慢查询"""
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(text(f"""
            SELECT 
                pid,
                now() - pg_stat_activity.query_start AS duration,
                query,
                state
            FROM pg_stat_activity
            WHERE (now() - pg_stat_activity.query_start) > interval '{threshold_ms} milliseconds'
            AND state != 'idle'
            AND query NOT ILIKE '%pg_stat_activity%'
            ORDER BY duration DESC
            LIMIT 10
        """))

        slow_queries = []
        for row in result:
            duration_seconds = row.duration.total_seconds() if row.duration else 0
            logger.warning(f"Slow query (PID: {row.pid}, Duration: {duration_seconds:.2f}s): "
                           f"{row.query[:100]}...")
            slow_queries.append({
                "pid": row.pid,
                "duration_seconds": duration_seconds,
                "query": row.query[:200],
                "state": row.state
            })

        if not slow_queries:
            logger.info(f"No queries slower than {threshold_ms}ms")

        return slow_queries


def check_locks():
    """检查数据库锁"""
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(text("""
                                   SELECT blocked_locks.pid         AS blocked_pid,
                                          blocked_activity.usename  AS blocked_user,
                                          blocking_locks.pid        AS blocking_pid,
                                          blocking_activity.usename AS blocking_user,
                                          blocked_activity.query    AS blocked_query,
                                          blocking_activity.query   AS blocking_query
                                   FROM pg_catalog.pg_locks blocked_locks
                                            JOIN pg_catalog.pg_stat_activity blocked_activity
                                                 ON blocked_activity.pid = blocked_locks.pid
                                            JOIN pg_catalog.pg_locks blocking_locks
                                                 ON blocking_locks.locktype = blocked_locks.locktype
                                                     AND blocking_locks.database IS NOT DISTINCT
                                   FROM blocked_locks.database
                                       AND blocking_locks.relation IS NOT DISTINCT
                                   FROM blocked_locks.relation
                                       AND blocking_locks.page IS NOT DISTINCT
                                   FROM blocked_locks.page
                                       AND blocking_locks.tuple IS NOT DISTINCT
                                   FROM blocked_locks.tuple
                                       AND blocking_locks.virtualxid IS NOT DISTINCT
                                   FROM blocked_locks.virtualxid
                                       AND blocking_locks.transactionid IS NOT DISTINCT
                                   FROM blocked_locks.transactionid
                                       AND blocking_locks.classid IS NOT DISTINCT
                                   FROM blocked_locks.classid
                                       AND blocking_locks.objid IS NOT DISTINCT
                                   FROM blocked_locks.objid
                                       AND blocking_locks.objsubid IS NOT DISTINCT
                                   FROM blocked_locks.objsubid
                                       AND blocking_locks.pid != blocked_locks.pid
                                       JOIN pg_catalog.pg_stat_activity blocking_activity
                                   ON blocking_activity.pid = blocking_locks.pid
                                   WHERE NOT blocked_locks.granted
                                   """))

        locks = []
        for row in result:
            logger.warning(f"Lock detected - Blocked PID: {row.blocked_pid} by PID: {row.blocking_pid}")
            logger.warning(f"  Blocked query: {row.blocked_query[:100]}...")
            logger.warning(f"  Blocking query: {row.blocking_query[:100]}...")
            locks.append({
                "blocked_pid": row.blocked_pid,
                "blocking_pid": row.blocking_pid,
                "blocked_query": row.blocked_query[:200],
                "blocking_query": row.blocking_query[:200]
            })

        if not locks:
            logger.info("No lock conflicts detected")

        return locks


def check_table_bloat():
    """检查表膨胀"""
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(text("""
                                   SELECT schemaname,
                                          tablename,
                                          pg_size_pretty(pg_relation_size(schemaname || '.' || tablename)) AS table_size,
                                          n_dead_tup,
                                          n_live_tup,
                                          CASE
                                              WHEN n_live_tup > 0
                                                  THEN round(100.0 * n_dead_tup / n_live_tup, 2)
                                              ELSE 0
                                              END                                                          AS dead_tuple_percent
                                   FROM pg_stat_user_tables
                                   WHERE n_dead_tup > 1000
                                   ORDER BY dead_tuple_percent DESC
                                   """))

        bloated_tables = []
        for row in result:
            if row.dead_tuple_percent > 10:
                logger.warning(f"Table {row.tablename} has {row.dead_tuple_percent}% dead tuples "
                               f"({row.n_dead_tup} dead / {row.n_live_tup} live)")
                bloated_tables.append({
                    "table": row.tablename,
                    "size": row.table_size,
                    "dead_tuples": row.n_dead_tup,
                    "live_tuples": row.n_live_tup,
                    "dead_percent": row.dead_tuple_percent
                })

        if not bloated_tables:
            logger.info("No significant table bloat detected")

        return bloated_tables


def check_cache_hit_ratio():
    """检查缓存命中率"""
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(text("""
                                   SELECT sum(heap_blks_read) as heap_read,
                                          sum(heap_blks_hit)  as heap_hit,
                                          CASE
                                              WHEN sum(heap_blks_hit) + sum(heap_blks_read) > 0
                                                  THEN round(100.0 * sum(heap_blks_hit) /
                                                             (sum(heap_blks_hit) + sum(heap_blks_read)), 2)
                                              ELSE 0
                                              END             as cache_hit_ratio
                                   FROM pg_statio_user_tables
                                   """))

        row = result.fetchone()
        cache_hit_ratio = row.cache_hit_ratio or 0

        logger.info(f"Cache hit ratio: {cache_hit_ratio}%")

        if cache_hit_ratio < 90:
            logger.warning(f"Low cache hit ratio: {cache_hit_ratio}% (should be > 90%)")

        return {
            "heap_read": row.heap_read,
            "heap_hit": row.heap_hit,
            "cache_hit_ratio": cache_hit_ratio
        }


def generate_report():
    """生成完整的监控报告"""
    logger.info("=" * 60)
    logger.info(f"Database Monitoring Report - {datetime.now()}")
    logger.info("=" * 60)

    report = {
        "timestamp": datetime.now().isoformat(),
        "connections": check_connections(),
        "slow_queries": check_slow_queries(),
        "locks": check_locks(),
        "table_bloat": check_table_bloat(),
        "cache_hit_ratio": check_cache_hit_ratio()
    }

    # 检查是否需要告警
    alerts = []

    if report["connections"]["usage_percent"] > 80:
        alerts.append(f"High connection usage: {report['connections']['usage_percent']:.1f}%")

    if report["slow_queries"]:
        alerts.append(f"Found {len(report['slow_queries'])} slow queries")

    if report["locks"]:
        alerts.append(f"Found {len(report['locks'])} lock conflicts")

    if report["cache_hit_ratio"]["cache_hit_ratio"] < 90:
        alerts.append(f"Low cache hit ratio: {report['cache_hit_ratio']['cache_hit_ratio']}%")

    if alerts:
        logger.warning("ALERTS:")
        for alert in alerts:
            logger.warning(f"  - {alert}")
    else:
        logger.info("All checks passed - No issues detected")

    logger.info("=" * 60)

    return report


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description='Database monitoring script')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--connections', action='store_true', help='Check connections only')
    parser.add_argument('--slow-queries', action='store_true', help='Check slow queries only')
    parser.add_argument('--locks', action='store_true', help='Check locks only')
    parser.add_argument('--bloat', action='store_true', help='Check table bloat only')
    parser.add_argument('--cache', action='store_true', help='Check cache hit ratio only')

    args = parser.parse_args()

    if args.connections:
        result = check_connections()
    elif args.slow_queries:
        result = check_slow_queries()
    elif args.locks:
        result = check_locks()
    elif args.bloat:
        result = check_table_bloat()
    elif args.cache:
        result = check_cache_hit_ratio()
    else:
        result = generate_report()

    if args.json:
        print(json.dumps(result, indent=2, default=str))