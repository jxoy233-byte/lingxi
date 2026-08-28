# 第三方依赖许可证

本项目使用大量第三方开源组件。本文件汇总主要依赖的归属信息与许可证；完整列表
可通过文档末尾列出的工具自动生成。

完整 license 报告生成
--------------------

发布版本前建议重新生成完整 license 报告并归档：

```bash
# 后端 Python 依赖
pip install pip-licenses
pip-licenses --format=markdown --output-file=THIRD_PARTY_PYTHON_LICENSES.md

# 前端 Node.js 依赖（仅 production 依赖）
npx license-checker --production --markdown > THIRD_PARTY_NODE_LICENSES.md
```

主要依赖一览
------------

> 下表按字母序列示核心依赖。完整列表以工具生成的报告为准。
> "License" 列以 [SPDX 标识符](https://spdx.org/licenses/) 表示；完整 license
> 文本随各组件发行版提供。

### 后端（Python · backend/pyproject.toml）

| 组件 | 最低版本 | License |
|------|-----------|---------|
| apscheduler | 3.11.2 | MIT |
| chardet | 5.2.0 | LGPL-2.1 |
| docling | 2.84.0 | MIT |
| fastapi | 0.135.1 | MIT |
| fastmcp | 3.1.1 | MIT |
| langchain-community | 0.4.1 | MIT |
| langchain-core | 1.2.20 | MIT |
| langchain-mcp-adapters | 0.2.2 | MIT |
| langchain-openai | 1.1.11 | MIT |
| langchain-tavily | 0.2.17 | MIT |
| langgraph | 1.1.3 | MIT |
| langgraph-checkpoint-redis | 0.4.0 | MIT |
| langgraph-sdk | 0.3.12 | MIT |
| oss2 | 2.19.1 | MIT |
| qwen-vl-utils | 0.0.14 | Apache-2.0 |
| redis | 7.3.0 | MIT |
| redisvl | 0.16.0 | MIT |
| unstructured | 0.16.0 | Apache-2.0 |

#### 数据科学生态（Python · sandbox 镜像同款）

| 组件 | 最低版本 | License |
|------|-----------|---------|
| altair | 6.1.0 | BSD-3-Clause |
| beautifulsoup4 | 4.14.3 | MIT |
| bokeh | 3.9.0 | BSD-3-Clause |
| branca | 0.8.2 | MIT |
| folium | 0.20.0 | MIT |
| jinja2 | 3.1.6 | BSD-3-Clause |
| joblib | 1.5.3 | BSD-3-Clause |
| lxml | 6.1.1 | BSD-3-Clause |
| markupsafe | 3.0.3 | BSD-3-Clause |
| matplotlib | 3.10.9 | PSF-2.0 / HPND |
| networkx | 3.6.1 | BSD-3-Clause |
| numpy | 2.4.6 | BSD-3-Clause |
| openpyxl | 3.1.5 | MIT |
| pandas | 3.0.3 | BSD-3-Clause |
| pillow | 12.2.0 | HPND |
| plotly | 6.8.0 | MIT |
| pyecharts | 2.1.0 | MIT |
| pygal | 3.1.0 | LGPL-3.0 |
| pyyaml | 6.0.3 | MIT |
| requests | 2.34.2 | Apache-2.0 |
| scikit-learn | 1.9.0 | BSD-3-Clause |
| scipy | 1.17.1 | BSD-3-Clause |
| seaborn | 0.13.2 | BSD-3-Clause |
| sympy | 1.14.0 | BSD-3-Clause |
| xlrd | 2.0.2 | BSD |
| xyzservices | 2026.3.0 | BSD-3-Clause |

### 前端（Node.js · frontend/package.json）

| 组件 | 最低版本 | License |
|------|-----------|---------|
| dompurify | 3.4.12 | MPL-2.0 / Apache-2.0 |
| electron | 41.1.0 | MIT |
| electron-builder | 26.8.1 | MIT |
| highlight.js | 11.11.1 | BSD-3-Clause |
| katex | 0.16.21 | MIT |
| marked | 17.0.3 | MIT |
| mermaid | 11.15.0 | MIT |
| vite | 5.1.6 | MIT |
| vue | 3.4.21 | MIT |
| vue-router | 4.6.4 | MIT |

### 沙盒（Docker 镜像 · sandbox/Dockerfile）

| 组件 | 版本 | License |
|------|------|---------|
| Python | 3.12 | PSF-2.0 |
| 内置 Python 包 | （与上方数据科学生态一致） | — |

特别说明
--------

- **dompurify** 同时以 MPL-2.0 / Apache-2.0 双协议发布，使用时遵守任一即可。
- **pygal** 使用 LGPL-3.0；以动态链接方式使用，不污染本项目整体许可。
- **chardet** 使用 LGPL-2.1；以二进制形式随 pip 依赖链间接加载，符合 LGPL 链接条款。
- **qwen-vl-utils / unstructured / requests** 使用 Apache-2.0；本项目以依赖形式
  使用其公开 API，符合 Apache-2.0 链接条款。
**- 其余依赖以 MIT / BSD / PSF / HPND 等宽松许可发布，符合 MIT 项目的兼容性要求。**

完整 license 文本
----------------

所有上述组件的完整 license 文本随各组件发行版提供：

- Python 依赖：`backend/.venv/lib/python3.12/site-packages/<pkg>-<ver>.dist-info/licenses/`
- Node.js 依赖：`frontend/node_modules/<pkg>/LICENSE*`
- 沙盒依赖：构建时自动通过 pip 安装并落到沙盒容器内 `/usr/lib/python3/dist-packages/`

需要查找某组件的完整 license 时，可使用：

```bash
# Python（查找特定包）
find backend/.venv/lib/python3.12/site-packages -name "LICENSE*" -path "*<pkg>*"

# Node.js（查找特定包）
cat frontend/node_modules/<pkg>/LICENSE
```