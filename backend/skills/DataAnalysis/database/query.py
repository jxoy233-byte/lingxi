"""Read-only database access used by the DataAnalysis skill."""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .config import load_database_config

_MAX_ROWS = 10_000
_QUERY_TIMEOUT_SECONDS = 30
_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|call|replace)\b",
    re.IGNORECASE,
)


def _validate_sql(sql: str) -> str:
    sql = sql.strip()
    if not sql:
        raise ValueError("SQL 不能为空")
    if sql.count(";") > 1 or (";" in sql and not sql.rstrip().endswith(";")):
        raise ValueError("只允许执行一条 SQL")
    sql = sql.rstrip(";").strip()
    if not re.match(r"^(select|with|explain|pragma)\b", sql, re.IGNORECASE):
        raise ValueError("只允许 SELECT/WITH/EXPLAIN，SQLite 可使用只读 PRAGMA")
    if _FORBIDDEN_SQL.search(sql):
        raise ValueError("SQL 包含不允许的写操作或管理操作")
    return sql


def _limit_sql(sql: str) -> str:
    if re.search(r"\blimit\s+\d+\b", sql, re.IGNORECASE):
        return sql
    return f"SELECT * FROM ({sql}) AS _chatme_result LIMIT {_MAX_ROWS + 1}"


def query_sql(alias: str, sql: str, max_rows: int = _MAX_ROWS) -> dict[str, Any]:
    """Run a bounded read-only SQL query and return rows plus metadata."""
    config = load_database_config(alias)
    engine = str(config.get("engine", "")).lower()
    sql = _validate_sql(sql)
    max_rows = max(1, min(int(max_rows), _MAX_ROWS))
    bounded_sql = _limit_sql(sql).replace(str(_MAX_ROWS + 1), str(max_rows + 1), 1)

    if engine == "sqlite":
        database = config.get("database") or config.get("path")
        if not database:
            raise ValueError("SQLite 配置缺少 database/path")
        connection = sqlite3.connect(f"file:{Path(database).resolve()}?mode=ro", uri=True, timeout=_QUERY_TIMEOUT_SECONDS)
        try:
            connection.execute("PRAGMA query_only = ON")
            cursor = connection.execute(bounded_sql)
            columns = [item[0] for item in cursor.description or []]
            rows = [dict(zip(columns, row)) for row in cursor.fetchmany(max_rows + 1)]
        finally:
            connection.close()
    elif engine == "mysql":
        import pymysql
        connection = pymysql.connect(
            host=config.get("host", "127.0.0.1"), port=int(config.get("port", 3306)),
            user=config.get("user"), password=config.get("password"),
            database=config.get("database"), connect_timeout=10, read_timeout=_QUERY_TIMEOUT_SECONDS,
            write_timeout=_QUERY_TIMEOUT_SECONDS, cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(bounded_sql)
                rows = list(cursor.fetchmany(max_rows + 1))
                columns = [item[0] for item in cursor.description or []]
        finally:
            connection.close()
    elif engine in {"postgres", "postgresql"}:
        import psycopg
        connection = psycopg.connect(
            host=config.get("host", "127.0.0.1"), port=int(config.get("port", 5432)),
            user=config.get("user"), password=config.get("password"), dbname=config.get("database"),
            connect_timeout=10, options=f"-c statement_timeout={_QUERY_TIMEOUT_SECONDS * 1000}",
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(bounded_sql)
                columns = [item.name for item in cursor.description or []]
                rows = [dict(zip(columns, row)) for row in cursor.fetchmany(max_rows + 1)]
        finally:
            connection.close()
    else:
        raise ValueError("query_sql 只支持 sqlite、mysql、postgresql")

    truncated = len(rows) > max_rows
    return {"alias": alias, "columns": columns, "rows": rows[:max_rows], "row_count": len(rows[:max_rows]), "truncated": truncated}


def query_mongo(alias: str, collection: str, operation: str = "find", **kwargs: Any) -> dict[str, Any]:
    """Run a bounded structured Mongo read operation; JavaScript is unsupported."""
    config = load_database_config(alias)
    if str(config.get("engine", "")).lower() not in {"mongo", "mongodb"}:
        raise ValueError("该数据源不是 MongoDB")
    if operation not in {"find", "aggregate", "count_documents", "distinct", "list_collections"}:
        raise ValueError("Mongo 只支持 find、aggregate、count_documents、distinct、list_collections")
    pipeline = kwargs.get("pipeline", [])
    forbidden = {"$out", "$merge", "$where", "$function", "$accumulator", "mapReduce", "eval"}
    if any(stage_key in forbidden for stage in pipeline if isinstance(stage, dict) for stage_key in stage):
        raise ValueError("Mongo 查询包含不允许的写入或脚本操作")

    from pymongo import MongoClient
    client = MongoClient(config.get("uri"), serverSelectionTimeoutMS=10_000, timeoutMS=_QUERY_TIMEOUT_SECONDS * 1000)
    try:
        database = client[config.get("database")]
        if operation == "list_collections":
            rows = [{"name": name} for name in database.list_collection_names()]
        else:
            collection_obj = database[collection]
            if operation == "find":
                rows = list(collection_obj.find(kwargs.get("filter", {}), kwargs.get("projection"), limit=_MAX_ROWS + 1))
            elif operation == "aggregate":
                rows = list(collection_obj.aggregate(pipeline, maxTimeMS=_QUERY_TIMEOUT_SECONDS * 1000))[:_MAX_ROWS + 1]
            elif operation == "count_documents":
                rows = [{"count": collection_obj.count_documents(kwargs.get("filter", {}), maxTimeMS=_QUERY_TIMEOUT_SECONDS * 1000)}]
            else:
                rows = [{"values": collection_obj.distinct(kwargs.get("key"), kwargs.get("filter", {}))}]
    finally:
        client.close()
    truncated = len(rows) > _MAX_ROWS
    return {"alias": alias, "rows": rows[:_MAX_ROWS], "row_count": min(len(rows), _MAX_ROWS), "truncated": truncated}


def save_query_result(result: dict[str, Any], path: str | Path) -> str:
    """Save a query result as JSON without logging connection details."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    return str(target)
