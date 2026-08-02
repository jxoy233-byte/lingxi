# DataAnalysis 数据库分析（动态加载文档）

本文件是 DataAnalysis skill 的子模块文档。只有当用户提出数据库相关分析需求时，才加载本文件。

## 加载方式

在主 `SKILL.md` 中不会默认展示数据库相关函数。DataAnalysis agent 识别到以下关键词时，必须先执行：

```python
cmd("cat /skills/DataAnalysis/database/SKILL.md")
```

然后再按本文件中的流程操作。

关键词示例：

- 数据库、SQL、数据表、MySQL、PostgreSQL、MongoDB、SQLite
- “分析一下我们销售库的订单数据”
- “查一下某张表”
- “从 MongoDB 取一下事件数据”

## 范围

支持 MySQL、SQLite、PostgreSQL、MongoDB。配置保存到 `skills/DataAnalysis/database/.runtime/`，跨会话共享；其他 skill 目录仍保持只读。

只读分析。所有写操作被拦截：SQL `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCANT/GRANT/REVOKE/MERGE/CALL/REPLACE`，以及 MongoDB `$out/$merge/$where/$function/$accumulator/mapReduce/eval` 一律拒绝。

## 标准执行流程

### 第一步：检查已有数据源

```python
from skills.DataAnalysis import list_database_configs

print(list_database_configs())
```

返回值不包含密码、URI 或连接配置完整内容。

### 第二步：缺少配置时主动中断询问

如果没有合适的数据源，必须先中断当前任务，询问用户：

- 数据库类型：mysql / sqlite / postgresql / mongodb
- MySQL / PostgreSQL：host、port、database、user、password
- SQLite：database 文件路径
- MongoDB：uri 或 host、port、database、user、password
- 可选的 alias 和 description

### 第三步：保存配置

```python
from skills.DataAnalysis import save_database_config

save_database_config(
    alias="sales",
    engine="mysql",
    host="host.docker.internal",
    port=3306,
    database="sales",
    user="readonly_user",
    password="<用户提供的密码>",
    description="销售只读数据库",
)
```

禁止把密码打印到日志、报告或 Markdown。

### 第四步：探索表结构

不要一开始猜表名或写业务查询。先列出表，再看字段，最后取样例。

SQLite：

```python
from skills.DataAnalysis import query_sql

tables = query_sql(
    "local_sqlite",
    "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name",
)
print(tables["rows"])

columns = query_sql(
    "local_sqlite",
    "SELECT name, type, notnull, pk FROM pragma_table_info('orders') ORDER BY cid",
)
print(columns["rows"])

sample = query_sql("local_sqlite", "SELECT * FROM orders LIMIT 20")
print(sample["columns"])
print(sample["rows"])
```

MySQL：

```python
tables = query_sql(
    "sales",
    """
    SELECT table_name, table_type
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
    ORDER BY table_name
    """,
)
print(tables["rows"])

columns = query_sql(
    "sales",
    """
    SELECT table_name, column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
    ORDER BY table_name, ordinal_position
    """,
)
print(columns["rows"])
print(query_sql("sales", "SELECT * FROM orders LIMIT 20")["rows"])
```

PostgreSQL：

```python
tables = query_sql(
    "analytics_pg",
    """
    SELECT table_name, table_type
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name
    """,
)
print(tables["rows"])

columns = query_sql(
    "analytics_pg",
    """
    SELECT table_name, column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema = 'public'
    ORDER BY table_name, ordinal_position
    """,
)
print(columns["rows"])
print(query_sql("analytics_pg", "SELECT * FROM orders LIMIT 20")["rows"])
```

MongoDB：

```python
from skills.DataAnalysis import query_mongo

collections = query_mongo(
    "events_mongo", collection="", operation="list_collections"
)
print(collections["rows"])

sample = query_mongo(
    "events_mongo",
    collection="events",
    operation="find",
    filter={},
    projection={"_id": 0, "event_type": 1, "created_at": 1, "amount": 1},
)
print(sample["rows"][:5])
```

### 第五步：写业务查询

拿到结构后才写业务 SQL。例如 PostgreSQL 按月统计订单：

```python
sql = """
SELECT
    DATE_TRUNC('month', created_at) AS month,
    COUNT(*) AS order_count,
    SUM(amount) AS total_amount,
    AVG(amount) AS average_amount
FROM orders
WHERE created_at >= CURRENT_DATE - INTERVAL '6 months'
GROUP BY DATE_TRUNC('month', created_at)
ORDER BY month
"""
result = query_sql("analytics_pg", sql, max_rows=1000)
print(result["columns"])
print(result["rows"][:5])
```

MongoDB 聚合示例：

```python
summary = query_mongo(
    "events_mongo",
    collection="events",
    operation="aggregate",
    pipeline=[
        {"$match": {"event_type": {"$exists": True}}},
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 100},
    ],
)
print(summary["rows"])
```

### 第六步：将查询结果交给 DataAnalysis

```python
import pandas as pd
from skills.DataAnalysis import ChatDataAnalysisFormat
from skills.DataAnalysis.format.database import save_database_result

df = pd.DataFrame(result["rows"])
raw_path = save_database_result(da, result, "database_raw.json")
csv_path = da.save_data(df.to_csv(index=False), "database_data.csv")
summary_path = da.save_data(
    df.describe(include="all").to_csv(),
    "database_summary.csv",
)
```

如果 `result["truncated"]` 为 `True`，说明结果达到上限，不能视为完整数据集。应缩小时间范围、字段范围或使用聚合统计，不要反复拉取整表。

## 注意事项

- SQL 方言与 `engine` 一一对应，不要混用。
- 整个数据库分析过程以只读为前提；遇到只读拦截时调整 SQL，而不是换路径。
- 不要使用 `cmd` 手动调用 `psql` / `mysql` / `mongosh` 等客户端绕过 skill 函数。
- 默认最多返回 10000 行/文档。需要更完整结果时收紧 WHERE/GROUP BY 条件。
