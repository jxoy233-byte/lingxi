---
name: skillforge
description: 动态创建新 skill；给一段 Python wrapper 代码 + 描述，落到 /skills/<name>/，立即被 find_skill 发现（无需重启）
mount: rw
aliases: [SkillForge, create_skill, new_skill, forge, 创建技能, 新建技能, 制作技能, 自定义技能]
module: skills.SkillForge
---

# SkillForge

动态创建新 skill。`functions_py` 是 Python wrapper —— 内部可调任意技术栈（REST API / CLI / 数据库），写出来能用就行。创建后立即被 `find_skill` 发现（registry mtime 自动重扫，无需重启）。

## 调用方式

必须 `code(..., local=True)` —— 写入主进程文件系统。

```python
from skills.SkillForge import create_skill
print(create_skill(
    name="weather",
    description="天气查询",
    functions_py='def get_weather(city): return f"{city}: 晴"',
    aliases=["天气"],
))
# → Created skill 'weather' at .../skills/weather
```

## 函数

### `create_skill(name, description, functions_py, aliases=None, skill_md_body="", overwrite=False)`

| 参数 | 说明 |
|---|---|
| `name` | skill 名（字母 / 数字 / 下划线；保留名 `SkillForge` / `_xxx` 不可用） |
| `description` | 写入 frontmatter + 默认 SKILL.md；被 find_skill 关键词检索 |
| `functions_py` | `__init__.py` 完整内容（Python wrapper 代码） |
| `aliases` | 别名列表（find_skill 关键词匹配） |
| `skill_md_body` | 自定义 SKILL.md 正文（不含 frontmatter）；空=自动生成 |
| `overwrite` | True 覆盖同名 skill，默认 False |

返回 `Created skill 'X' at ...` 或 `[BadRequest] / [Exists]` 错误描述。

### `list_skills()`

列出 `/skills/` 下所有 skill 目录。

### `read_skill(name)`

读现有 skill 的 `SKILL.md` + `__init__.py` 完整内容（用于复制格式 / 修改前参考）。
