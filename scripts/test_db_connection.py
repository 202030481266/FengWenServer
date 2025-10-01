#!/usr/bin/env python3
"""
数据库连接测试脚本
用于测试 check_database_connection 函数是否正常工作
"""

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 设置日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """测试数据库连接"""
    logger.info("=" * 60)
    logger.info("开始测试数据库连接...")
    logger.info("=" * 60)
    
    try:
        # 导入数据库模块
        from src.fengwen2.database import check_database_connection, DATABASE_URL
        
        # 显示数据库配置（隐藏密码）
        if DATABASE_URL:
            # 隐藏密码部分
            safe_url = DATABASE_URL
            if '@' in safe_url and '://' in safe_url:
                parts = safe_url.split('://')
                if len(parts) == 2:
                    protocol = parts[0]
                    rest = parts[1]
                    if '@' in rest:
                        credentials, host_part = rest.split('@', 1)
                        if ':' in credentials:
                            user = credentials.split(':')[0]
                            safe_url = f"{protocol}://{user}:****@{host_part}"
            logger.info(f"数据库连接字符串: {safe_url}")
        else:
            logger.warning("未找到数据库连接字符串")
        
        logger.info("-" * 60)
        
        # 测试连接
        logger.info("正在测试数据库连接...")
        result = check_database_connection()
        
        logger.info("-" * 60)
        
        if result:
            logger.info("✅ 数据库连接成功！")
            logger.info("=" * 60)
            return 0
        else:
            logger.error("❌ 数据库连接失败！")
            logger.error("请检查：")
            logger.error("  1. 数据库服务是否运行")
            logger.error("  2. .env 文件中的数据库配置是否正确")
            logger.error("  3. 网络连接是否正常")
            logger.error("  4. 数据库用户权限是否正确")
            logger.info("=" * 60)
            return 1
            
    except ImportError as e:
        logger.error(f"❌ 导入模块失败: {e}")
        logger.error("请确保已安装所有依赖: pip install -e .")
        return 1
    except Exception as e:
        logger.error(f"❌ 发生错误: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

