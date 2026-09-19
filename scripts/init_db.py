"""
背备不悲 · 数据库初始化脚本

作用：连接 Linux 虚拟机里的 MySQL，创建 beibei 库，并依次执行
      docs/sql/schema.sql 与 docs/sql/init_data.sql，最后校验表数量。

用法（在项目根目录执行）：
    D:\\conda-envs\\beibei\\python.exe scripts\\init_db.py
    D:\\conda-envs\\beibei\\python.exe scripts\\init_db.py --drop     # 先删库再重建
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pymysql

# Windows 控制台默认 GBK，直接 print ✓/✗/中文 会抛 UnicodeEncodeError，强制 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError, ValueError):
        pass

# ---------------------------------------------------------------------------
#  配置（与 beibei-agent/.env 保持一致）
# ---------------------------------------------------------------------------
MYSQL_HOST = "192.168.1.100"
MYSQL_PORT = 3306
MYSQL_USER = "root"
MYSQL_PASSWORD = "your-mysql-password"  # 来自 mysql 容器的 MYSQL_ROOT_PASSWORD
MYSQL_DB = "beibei"

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "docs" / "sql"

EXPECTED_TABLES = [
    "bb_user", "bb_knowledge_base", "bb_document", "bb_doc_chunk", "bb_tag",
    "bb_chunk_tag", "bb_question", "bb_question_option", "bb_question_tag",
    "bb_paper", "bb_paper_item", "bb_exam_record", "bb_answer_item",
    "bb_mistake", "bb_review_log", "bb_ai_provider", "bb_model_route",
    "bb_prompt_template", "bb_ai_call_log", "bb_async_task", "bb_setting",
]


def split_sql(text: str) -> list[str]:
    """
    按分号拆 SQL 语句，正确跳过字符串、反引号、注释里的分号。
    比 pymysql 的 MULTI_STATEMENTS 更好排错：能定位到具体是哪条语句失败。
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    quote: str | None = None

    while i < n:
        ch = text[i]

        # 行注释 --
        if quote is None and ch == "-" and text[i:i + 2] == "--":
            while i < n and text[i] != "\n":
                i += 1
            continue

        # 块注释 /* */
        if quote is None and text[i:i + 2] == "/*":
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue

        # 转义字符（仅单引号字符串内生效）
        if quote == "'" and ch == "\\":
            buf.append(text[i:i + 2])
            i += 2
            continue

        if quote is None and ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue

        if quote is not None and ch == quote:
            # SQL 里的 '' 表示一个单引号
            if text[i:i + 2] == quote * 2:
                buf.append(quote * 2)
                i += 2
                continue
            quote = None
            buf.append(ch)
            i += 1
            continue

        if quote is None and ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def execute_file(cursor, path: Path, *, verbose: bool = True) -> int:
    raw = path.read_text(encoding="utf-8")
    statements = split_sql(raw)
    done = 0
    for idx, stmt in enumerate(statements, start=1):
        preview = re.sub(r"\s+", " ", stmt)[:78]
        try:
            cursor.execute(stmt)
            done += 1
            if verbose:
                print(f"    [{idx:>3}/{len(statements)}] OK   {preview}")
        except Exception as exc:  # noqa: BLE001
            print(f"    [{idx:>3}/{len(statements)}] FAIL {preview}")
            print(f"          → {type(exc).__name__}: {exc}")
            raise
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 beibei 数据库")
    parser.add_argument("--drop", action="store_true", help="先 DROP DATABASE 再重建")
    parser.add_argument("--quiet", action="store_true", help="不逐条打印 SQL")
    args = parser.parse_args()
    verbose = not args.quiet

    print("=" * 74)
    print("  背备不悲 · 数据库初始化")
    print("=" * 74)
    print(f"  目标: {MYSQL_USER}@{MYSQL_HOST}:{MYSQL_PORT}")
    print(f"  库名: {MYSQL_DB}")
    print(f"  脚本: {SQL_DIR}")
    print("=" * 74)

    # ---------- 连接（不指定库）----------
    try:
        conn = pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
            password=MYSQL_PASSWORD, charset="utf8mb4",
            connect_timeout=10, autocommit=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\n✗ 无法连接 MySQL: {type(exc).__name__}: {exc}")
        print("  排查：1) 虚拟机是否开机  2) 端口 3306 是否可达  3) 密码是否正确")
        return 1
    print("\n✓ 已连接 MySQL")

    with conn.cursor() as cursor:
        cursor.execute("SELECT VERSION()")
        print(f"  服务器版本: {cursor.fetchone()[0]}")

        # ---------- 建库 ----------
        if args.drop:
            print(f"\n[0/3] DROP DATABASE {MYSQL_DB}（--drop 指定）")
            cursor.execute(f"DROP DATABASE IF EXISTS `{MYSQL_DB}`")

        print(f"\n[1/3] 建表 schema.sql")
        schema = SQL_DIR / "schema.sql"
        if not schema.exists():
            print(f"  ✗ 找不到 {schema}")
            return 1
        execute_file(cursor, schema, verbose=verbose)

        print(f"\n[2/3] 初始化数据 init_data.sql")
        data = SQL_DIR / "init_data.sql"
        if not data.exists():
            print(f"  ✗ 找不到 {data}")
            return 1
        execute_file(cursor, data, verbose=verbose)

        # ---------- 校验 ----------
        print(f"\n[3/3] 校验")
        cursor.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
            (MYSQL_DB,),
        )
        found = {row[0] for row in cursor.fetchall()}
        missing = [t for t in EXPECTED_TABLES if t not in found]
        extra = sorted(found - set(EXPECTED_TABLES))

        print(f"  表数量: {len(found)} / 期望 {len(EXPECTED_TABLES)}")
        if missing:
            print(f"  ✗ 缺表: {', '.join(missing)}")
        if extra:
            print(f"  · 额外表: {', '.join(extra)}")

        for table in ("bb_ai_provider", "bb_prompt_template", "bb_setting", "bb_model_route", "bb_user"):
            cursor.execute(f"SELECT COUNT(*) FROM `{MYSQL_DB}`.`{table}`")
            print(f"    {table:<22} {cursor.fetchone()[0]} 行")

    conn.close()

    ok = not missing
    print("\n" + "=" * 74)
    print("  ✓ 初始化成功" if ok else "  ✗ 初始化未完成，请检查上面的 FAIL 行")
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
