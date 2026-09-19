"""
背备不悲 · 通用 SQL 脚本执行器

用途：把 docs/sql/*.sql 直接灌进 MySQL，省得手动开 Navicat 粘贴。
支持多语句（MULTI_STATEMENTS），因此脚本里可以写 CREATE DATABASE / USE。

用法：
    python scripts/apply_sql.py docs/sql/interview.sql
    python scripts/apply_sql.py docs/sql/schema.sql docs/sql/init_data.sql
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymysql
from pymysql.constants import CLIENT

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "beibei-agent"))

from app.config import get_settings  # noqa: E402


def apply_file(path: Path, settings) -> int:
    sql = path.read_text(encoding="utf-8")
    if not sql.strip():
        print(f"  {path.name}: 空文件，跳过")
        return 0

    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        charset="utf8mb4",
        client_flag=CLIENT.MULTI_STATEMENTS,
        autocommit=True,
    )
    statements = 0
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            while cur.nextset():
                pass
            statements = 1
    finally:
        conn.close()
    print(f"  {path.name}: 执行完成（{len(sql)} 字符）")
    return statements


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("用法: python scripts/apply_sql.py <file.sql> [file2.sql ...]")
        return 2

    settings = get_settings()
    print(f"目标库: {settings.mysql_host}:{settings.mysql_port}/{settings.mysql_db}")
    for arg in args:
        path = Path(arg)
        if not path.is_absolute():
            path = ROOT / arg
        if not path.exists():
            print(f"  [跳过] 文件不存在: {path}")
            return 1
        apply_file(path, settings)
    print("全部执行完毕")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
