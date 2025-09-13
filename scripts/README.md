# 数据库脚本使用指南

## 目录
1. [脚本概览](#脚本概览)
2. [环境准备](#环境准备)
3. [init_db.py - 数据库初始化](#init_dbpy---数据库初始化)
4. [db_maintenance.py - 数据库维护](#db_maintenancepy---数据库维护)
5. [monitor_db.py - 数据库监控](#monitor_dbpy---数据库监控)
6. [migrate_to_postgresql.py - 数据迁移](#migrate_to_postgresqlpy---数据迁移)
7. [自动化配置](#自动化配置)
8. [常见问题解决](#常见问题解决)

---

## 脚本概览

| 脚本名称 | 用途 | 使用频率 | 运行时机 |
|---------|------|---------|---------|
| `init_db.py` | 初始化数据库表结构 | 一次性 | 首次部署或重置数据库时 |
| `db_maintenance.py` | 数据库维护和优化 | 定期 | 每天/每周自动运行 |
| `monitor_db.py` | 监控数据库状态 | 按需/定期 | 排查问题或定期健康检查 |
| `migrate_to_postgresql.py` | SQLite 到 PostgreSQL 迁移 | 一次性 | 需要迁移现有数据时 |

---

## 环境准备

### 1. 确保脚本可执行

```bash
# 进入项目目录
cd ~/FengWenServer

# 创建脚本目录（如果不存在）
mkdir -p scripts

# 设置执行权限
chmod +x scripts/*.py
```

### 2. 验证环境配置

```bash
# 检查 .env 文件是否正确配置
cat .env | grep DB_

# 应该看到类似：
# DB_TYPE=postgresql
# DB_USER=astrology_user
# DB_PASSWORD=your_password
# DB_HOST=localhost
# DB_PORT=5432
# DB_NAME=astrology_db
```

### 3. 测试数据库连接

```bash
# 使用 Python 测试连接
python -c "
from dotenv import load_dotenv
import os
load_dotenv()
print('Database URL:', os.getenv('DATABASE_URL', 'Not set'))
print('DB Type:', os.getenv('DB_TYPE', 'Not set'))
"
```

---

## init_db.py - 数据库初始化

### 用途
- 创建所有数据库表
- 插入初始配置数据
- 验证表结构完整性

### 基本用法

```bash
# 1. 首次初始化（创建所有表）
python scripts/init_db.py

# 输出示例：
# 2025-01-13 10:00:00 - init_db - INFO - Starting database initialization...
# 2025-01-13 10:00:00 - database - INFO - Database connection successful
# 2025-01-13 10:00:01 - database - INFO - Database tables created successfully
# 2025-01-13 10:00:01 - init_db - INFO - Default configurations added
# 2025-01-13 10:00:01 - init_db - INFO - Created tables: ['astrology_records', 'site_config', 'products', 'translation_pairs']
# 2025-01-13 10:00:01 - init_db - INFO - Database initialization completed successfully!
```

### 高级用法

```bash
# 2. 重置数据库（删除所有表后重新创建）
python scripts/init_db.py --reset

# 会提示确认：
# WARNING: This will delete all data! Type 'YES' to confirm: YES

# 3. 强制重置（跳过确认，用于自动化脚本）
python scripts/init_db.py --reset --force
```

### 使用场景

1. **首次部署**
   ```bash
   # 新环境部署时运行一次
   python scripts/init_db.py
   ```

2. **开发环境重置**
   ```bash
   # 清空所有测试数据，重新开始
   python scripts/init_db.py --reset --force
   ```

3. **验证表结构**
   ```bash
   # 运行脚本会自动验证所有必要的表是否存在
   python scripts/init_db.py
   # 如果表已存在，会跳过创建
   ```

### 故障排查

```bash
# 如果初始化失败，检查：
# 1. 数据库服务是否运行
sudo systemctl status postgresql

# 2. 数据库是否存在
sudo -u postgres psql -c "\l" | grep astrology_db

# 3. 用户权限是否正确
sudo -u postgres psql -d astrology_db -c "\du" | grep astrology_user
```

---

## db_maintenance.py - 数据库维护

### 用途
- 执行 VACUUM 优化表空间
- 清理旧的未购买记录
- 分析表大小和使用情况
- 检查索引使用率
- 创建数据库备份

### 基本用法

```bash
# 1. 运行所有维护任务
python scripts/db_maintenance.py --all

# 输出示例：
# 2025-01-13 02:00:00 - db_maintenance - INFO - Starting VACUUM ANALYZE...
# 2025-01-13 02:00:05 - db_maintenance - INFO - VACUUM ANALYZE completed successfully
# 2025-01-13 02:00:05 - db_maintenance - INFO - Cleaning unpurchased records older than 90 days...
# 2025-01-13 02:00:06 - db_maintenance - INFO - Deleted 42 old unpurchased records
# 2025-01-13 02:00:06 - db_maintenance - INFO - Table sizes:
# 2025-01-13 02:00:06 - db_maintenance - INFO -   astrology_records: 1.2 MB (1543 rows)
# 2025-01-13 02:00:07 - db_maintenance - INFO - Backup completed: /var/backups/postgresql/astrology_db_20250113_020007.sql.gz (524,288 bytes)
```

### 单独运行各项任务

```bash
# 2. VACUUM ANALYZE（优化查询性能）
python scripts/db_maintenance.py --vacuum
# 建议：每周运行一次

# 3. 清理旧记录（默认清理90天前的未购买记录）
python scripts/db_maintenance.py --clean
# 建议：每月运行一次

# 4. 分析表大小
python scripts/db_maintenance.py --analyze
# 输出每个表的大小和行数

# 5. 检查索引使用情况
python scripts/db_maintenance.py --check-indexes
# 显示未使用或低使用率的索引

# 6. 创建备份
python scripts/db_maintenance.py --backup
# 备份保存到 /var/backups/postgresql/
```

### 自定义备份目录

```bash
# 修改脚本中的备份路径
# 编辑 scripts/db_maintenance.py
# 找到 backup_database 函数
# 修改 backup_dir 参数

# 或者创建软链接
sudo mkdir -p /your/backup/path
sudo ln -s /your/backup/path /var/backups/postgresql
```

### 备份管理

```bash
# 查看所有备份
ls -lh /var/backups/postgresql/

# 恢复备份（需要先停止应用）
gunzip -c /var/backups/postgresql/astrology_db_20250113_020007.sql.gz | psql -U astrology_user -d astrology_db

# 手动删除旧备份
find /var/backups/postgresql/ -name "*.sql.gz" -mtime +30 -delete
```

### 使用建议

| 任务 | 建议频率 | 最佳时间 | 影响 |
|-----|---------|---------|------|
| VACUUM | 每周 | 凌晨低峰期 | 轻微性能影响 |
| 清理旧记录 | 每月 | 月初凌晨 | 删除数据操作 |
| 分析表 | 按需 | 任何时间 | 只读操作，无影响 |
| 检查索引 | 每月 | 任何时间 | 只读操作，无影响 |
| 备份 | 每天 | 凌晨1-3点 | IO密集，影响性能 |

---

## monitor_db.py - 数据库监控

### 用途
- 检查数据库连接状态
- 识别慢查询
- 检测锁冲突
- 监控表膨胀
- 计算缓存命中率

### 基本用法

```bash
# 1. 生成完整监控报告
python scripts/monitor_db.py

# 输出示例：
# ============================================================
# Database Monitoring Report - 2025-01-13 15:30:00
# ============================================================
# 2025-01-13 15:30:00 - monitor_db - INFO - Connections - Total: 15, Active: 3, Idle: 12, Idle in transaction: 0
# 2025-01-13 15:30:00 - monitor_db - INFO - Connection usage: 15.0% (15/100)
# 2025-01-13 15:30:00 - monitor_db - INFO - No queries slower than 1000ms
# 2025-01-13 15:30:00 - monitor_db - INFO - No lock conflicts detected
# 2025-01-13 15:30:00 - monitor_db - INFO - Cache hit ratio: 98.5%
# 2025-01-13 15:30:00 - monitor_db - INFO - All checks passed - No issues detected
# ============================================================
```

### 单项检查

```bash
# 2. 只检查连接状态
python scripts/monitor_db.py --connections
# 显示当前连接数、活跃连接、空闲连接等

# 3. 检查慢查询（默认阈值：1秒）
python scripts/monitor_db.py --slow-queries
# 列出所有执行超过1秒的查询

# 4. 检查锁冲突
python scripts/monitor_db.py --locks
# 显示被阻塞的查询和阻塞源

# 5. 检查表膨胀
python scripts/monitor_db.py --bloat
# 显示死元组比例高的表

# 6. 检查缓存命中率
python scripts/monitor_db.py --cache
# 显示缓存命中率，应该 > 90%
```

### JSON 输出（用于集成监控系统）

```bash
# 7. 输出 JSON 格式
python scripts/monitor_db.py --json > db_status.json

# JSON 结构：
{
  "timestamp": "2025-01-13T15:30:00",
  "connections": {
    "total": 15,
    "active": 3,
    "idle": 12,
    "max": 100,
    "usage_percent": 15.0
  },
  "slow_queries": [],
  "locks": [],
  "table_bloat": [],
  "cache_hit_ratio": {
    "heap_read": 10234,
    "heap_hit": 502341,
    "cache_hit_ratio": 98.5
  }
}
```

### 集成到监控系统

```bash
# 1. Zabbix 集成示例
# 创建用户参数
echo "UserParameter=db.connections,python /path/to/scripts/monitor_db.py --json | jq '.connections.usage_percent'" >> /etc/zabbix/zabbix_agentd.conf

# 2. Prometheus 集成（使用 node_exporter）
# 创建文本收集器脚本
cat > /var/lib/node_exporter/db_metrics.prom << EOF
#!/bin/bash
python /path/to/scripts/monitor_db.py --json | python -c "
import json, sys
data = json.load(sys.stdin)
print(f'db_connections_usage {data[\"connections\"][\"usage_percent\"]}')
print(f'db_cache_hit_ratio {data[\"cache_hit_ratio\"][\"cache_hit_ratio\"]}')
print(f'db_slow_queries_count {len(data[\"slow_queries\"])}')
print(f'db_locks_count {len(data[\"locks\"])}')
"
EOF
```

### 告警阈值建议

| 指标 | 警告阈值 | 严重阈值 | 处理建议 |
|-----|---------|---------|---------|
| 连接使用率 | > 70% | > 90% | 增加 max_connections 或优化连接池 |
| 慢查询数 | > 5 | > 10 | 优化查询或添加索引 |
| 锁冲突 | > 0 | > 3 | 检查事务设计，减少锁持有时间 |
| 缓存命中率 | < 95% | < 90% | 增加 shared_buffers 或优化查询 |
| 死元组比例 | > 20% | > 50% | 运行 VACUUM |

---

## migrate_to_postgresql.py - 数据迁移

### 用途
- 从 SQLite 迁移到 PostgreSQL
- 保留所有现有数据
- 一次性迁移脚本

### 前提条件

```bash
# 1. 确保 SQLite 数据库文件存在
ls -la astrology.db

# 2. 确保 PostgreSQL 已配置好
python scripts/init_db.py  # 先创建表结构

# 3. 备份 SQLite 数据库
cp astrology.db astrology.db.backup
```

### 使用方法

```bash
# 运行迁移
python scripts/migrate_to_postgresql.py

# 提示确认：
# This will migrate data from SQLite to PostgreSQL. Continue? (yes/no): yes

# 输出示例：
# 2025-01-13 16:00:00 - migrate - INFO - PostgreSQL tables created
# 2025-01-13 16:00:00 - migrate - INFO - Found 1543 astrology records to migrate
# 2025-01-13 16:00:02 - migrate - INFO - Found 3 site configs to migrate
# 2025-01-13 16:00:02 - migrate - INFO - Found 10 products to migrate
# 2025-01-13 16:00:02 - migrate - INFO - Found 50 translation pairs to migrate
# 2025-01-13 16:00:03 - migrate - INFO - Migration completed successfully!
```

### 验证迁移结果

```bash
# 1. 检查记录数
psql -U astrology_user -d astrology_db -c "SELECT COUNT(*) FROM astrology_records;"

# 2. 对比数据
# SQLite
sqlite3 astrology.db "SELECT COUNT(*) FROM astrology_records;"

# PostgreSQL
psql -U astrology_user -d astrology_db -c "SELECT COUNT(*) FROM astrology_records;"

# 3. 验证应用运行正常
python src/fengwen2/main.py
curl http://localhost:8000/health
```

---

## 自动化配置

### 1. Crontab 配置

```bash
# 编辑 crontab
crontab -e

# 添加以下内容：
# ====== 数据库维护任务 ======
# 路径变量
PROJECT_DIR=/path/to/your/project

# 每天凌晨1点备份
0 1 * * * cd $PROJECT_DIR && python scripts/db_maintenance.py --backup >> /var/log/db_backup.log 2>&1

# 每天凌晨2点运行完整维护（周日除外）
0 2 * * 1-6 cd $PROJECT_DIR && python scripts/db_maintenance.py --vacuum >> /var/log/db_maintenance.log 2>&1

# 每周日凌晨2点运行全面维护
0 2 * * 0 cd $PROJECT_DIR && python scripts/db_maintenance.py --all >> /var/log/db_maintenance_full.log 2>&1

# 每月1号清理旧数据
0 0 1 * * cd $PROJECT_DIR && python scripts/db_maintenance.py --clean >> /var/log/db_clean.log 2>&1

# 每30分钟监控一次（生产环境）
*/30 * * * * cd $PROJECT_DIR && python scripts/monitor_db.py --json >> /var/log/db_monitor.json 2>&1

# 每小时检查慢查询
0 * * * * cd $PROJECT_DIR && python scripts/monitor_db.py --slow-queries >> /var/log/db_slow_queries.log 2>&1
```

### 2. Systemd 定时器（替代 crontab）

```bash
# 创建 service 文件
sudo cat > /etc/systemd/system/db-maintenance.service << EOF
[Unit]
Description=Database Maintenance
After=postgresql.service

[Service]
Type=oneshot
User=your_user
WorkingDirectory=/path/to/your/project
ExecStart=/usr/bin/python3 /path/to/your/project/scripts/db_maintenance.py --all
StandardOutput=append:/var/log/db_maintenance.log
StandardError=append:/var/log/db_maintenance.log
EOF

# 创建 timer 文件
sudo cat > /etc/systemd/system/db-maintenance.timer << EOF
[Unit]
Description=Run Database Maintenance Daily
Requires=db-maintenance.service

[Timer]
OnCalendar=daily
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# 启用定时器
sudo systemctl daemon-reload
sudo systemctl enable db-maintenance.timer
sudo systemctl start db-maintenance.timer

# 查看定时器状态
sudo systemctl list-timers
```

### 3. 日志轮转配置

```bash
# 创建 logrotate 配置
sudo cat > /etc/logrotate.d/db-scripts << EOF
/var/log/db_*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 644 your_user your_group
}

/var/log/db_monitor.json {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 your_user your_group
}
EOF
```

---

## 常见问题解决

### 1. 权限问题

```bash
# 错误：Permission denied
# 解决：
chmod +x scripts/*.py
# 或使用 python 直接运行
python scripts/init_db.py
```

### 2. 找不到模块

```bash
# 错误：ModuleNotFoundError: No module named 'src.fengwen2'
# 解决：确保在项目根目录运行
cd /path/to/your/project
python scripts/init_db.py

# 或添加 Python 路径
export PYTHONPATH=/path/to/your/project:$PYTHONPATH
```

### 3. 数据库连接失败

```bash
# 错误：psycopg2.OperationalError: FATAL: password authentication failed
# 解决：
# 1. 检查 .env 文件密码
cat .env | grep DB_PASSWORD

# 2. 验证数据库用户密码
psql -U astrology_user -d astrology_db -h localhost
# 输入密码测试

# 3. 重置密码
sudo -u postgres psql
ALTER USER astrology_user WITH PASSWORD 'new_password';
\q

# 4. 更新 .env 文件
vi .env
# 修改 DB_PASSWORD=new_password
```

### 4. VACUUM 失败

```bash
# 错误：ERROR: VACUUM cannot run inside a transaction block
# 解决：脚本已处理，如果仍有问题，手动运行：
psql -U astrology_user -d astrology_db -c "VACUUM ANALYZE;"
```

### 5. 备份失败

```bash
# 错误：pg_dump: command not found
# 解决：安装 postgresql-client
sudo dnf install postgresql

# 错误：could not open output file: Permission denied
# 解决：创建备份目录并设置权限
sudo mkdir -p /var/backups/postgresql
sudo chown your_user:your_group /var/backups/postgresql
```

### 6. 监控显示高连接数

```bash
# 问题：连接数接近上限
# 临时解决：
# 1. 查看所有连接
psql -U postgres -d astrology_db -c "SELECT * FROM pg_stat_activity;"

# 2. 终止空闲连接
psql -U postgres -d astrology_db -c "
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE datname = 'astrology_db' 
AND state = 'idle' 
AND state_change < now() - interval '10 minutes';"

# 永久解决：
# 1. 增加最大连接数
sudo vi /var/lib/pgsql/data/postgresql.conf
# max_connections = 200

# 2. 优化应用连接池
# 在 database.py 中调整 pool_size
```

### 7. 脚本执行日志查看

```bash
# 查看最近的维护日志
tail -n 100 /var/log/db_maintenance.log

# 实时监控日志
tail -f /var/log/db_monitor.json | jq '.'

# 搜索错误
grep ERROR /var/log/db_*.log

# 查看特定日期的日志
grep "2025-01-13" /var/log/db_maintenance.log
```

---

## 最佳实践建议

### 开发环境
```bash
# 使用 SQLite 快速开发
DB_TYPE=sqlite
# 定期同步到 PostgreSQL 测试
python scripts/migrate_to_postgresql.py
```

### 测试环境
```bash
# 使用 PostgreSQL，与生产保持一致
DB_TYPE=postgresql
# 每天重置数据
0 0 * * * python scripts/init_db.py --reset --force
```

### 生产环境
```bash
# 完整的维护计划
# 1. 每天备份
# 2. 每周 VACUUM
# 3. 每月清理
# 4. 持续监控
# 5. 告警通知
```

### 性能优化时机
- 当缓存命中率 < 95% 时，考虑增加 shared_buffers
- 当慢查询 > 5个/小时 时，分析并优化查询
- 当连接数 > 70% 时，优化连接池或增加 max_connections
- 当表膨胀 > 30% 时，执行 VACUUM FULL（注意：会锁表）

---

## 快速参考卡片

```bash
# ===== 日常运维命令 =====
# 检查状态
python scripts/monitor_db.py

# 手动备份
python scripts/db_maintenance.py --backup

# 清理优化
python scripts/db_maintenance.py --vacuum

# ===== 故障处理命令 =====
# 检查慢查询
python scripts/monitor_db.py --slow-queries

# 检查锁
python scripts/monitor_db.py --locks

# 重建索引
psql -U astrology_user -d astrology_db -c "REINDEX DATABASE astrology_db;"

# ===== 紧急恢复命令 =====
# 从备份恢复
gunzip -c /var/backups/postgresql/astrology_db_latest.sql.gz | psql -U astrology_user -d astrology_db

# 重置数据库
python scripts/init_db.py --reset --force
```