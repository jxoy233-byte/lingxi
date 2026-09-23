# 灵析 Lingxi

## 宣传公告

> **灵析（Lingxi）** —— 说人话就能做数据分析的 AI 工作台。
>
> 一句话 / 一份文件 / 一个数据库丢进去，多智能体自动编排搜索、写码、跑沙盒、出图出报告；全程对话式推进，代码执行弹窗审批、环境隔离可控。LangGraph 驱动，Web 与桌面端开箱即用。
>
> **你的数据，你问；剩下的交给它。**

完整说明见 [`../README.md`](../README.md)。

---

## 特色 · 全键盘交互

不只是点按钮——输入、审批、文件管理、配置、预览都能键盘走完。应用内输入 `/help` 可随时调出速查表。

| 场景 | 按键 | 作用 |
| --- | --- | --- |
| 任意位置（无弹窗） | <kbd>/</kbd> <kbd>/</kbd>（500ms 内双击） | 聚焦输入框；在输入框内按 <kbd>/</kbd> 不拦截，正常输入 |
| 输入框 | <kbd>Enter</kbd> / <kbd>Ctrl</kbd>+<kbd>Enter</kbd> | 发送 / 换行 |
| 输入框 | <kbd>↑</kbd> <kbd>↓</kbd> <kbd>Tab</kbd> / <kbd>Enter</kbd> / <kbd>Esc</kbd> | `/` 命令面板选取 / 确认 / 关闭；<kbd>Backspace</kbd> 在行首吞掉命令 chip |
| 审批 | <kbd>1</kbd>–<kbd>4</kbd> | 一键触发四档：拒绝 / 仅本次 / 反馈 / 批准（无需再回车） |
| 审批 | <kbd>←</kbd> <kbd>↑</kbd> <kbd>→</kbd> <kbd>↓</kbd> / <kbd>Enter</kbd> / <kbd>Esc</kbd> | 移动高亮 / 确认当前项 / 拒绝；反馈框内 <kbd>Enter</kbd> 提交、<kbd>Shift</kbd>+<kbd>Enter</kbd> 换行 |
| 文件树（焦点在文件区且非输入态） | <kbd>F2</kbd> / <kbd>Delete</kbd> / <kbd>F5</kbd> | 重命名 / 删除（macOS 另支持 <kbd>⌘</kbd>+<kbd>⌫</kbd>）/ 刷新文件树 |
| 文件树 | <kbd>⌘/Ctrl</kbd>+<kbd>C</kbd> <kbd>X</kbd> <kbd>V</kbd> <kbd>D</kbd> <kbd>A</kbd> | 复制 / 剪切 / 粘贴 / 生成副本 / 全选，修饰键与删除键按平台自动切换 |
| 文件树 | <kbd>⌘/Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>N</kbd>（加 <kbd>Alt</kbd> 为新建文件） | 新建文件夹 |
| 文件树 | 方向键 / <kbd>Shift</kbd>+方向键 / <kbd>Enter</kbd> / <kbd>空格</kbd>（macOS） | 移动焦点 / 范围选择 / 打开 / 快速查看 |
| 文件预览 | <kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>W</kbd>；<kbd>←</kbd> <kbd>→</kbd> <kbd>Home</kbd> <kbd>End</kbd> | 关闭当前 tab / 切换 tab |
| 设置弹窗 · 配置向导 · 历史版本面板 | <kbd>↑</kbd> <kbd>↓</kbd>（设置内 <kbd>Home</kbd> <kbd>End</kbd>）/ <kbd>Tab</kbd> / <kbd>Enter</kbd> / <kbd>Esc</kbd> | 切 tab 或步骤 / 切字段 / 确认 / 关闭 |
| 会话标题 · 确认弹窗 | <kbd>Enter</kbd> / <kbd>Esc</kbd> | 保存·确认 / 取消 |

**设计取向**：焦点策略向系统文件管理器看齐（点文件 → 焦点落到父目录，粘贴目标用蓝竖线显式标记）；修饰键、删除键、快速查看均按平台自动切换；快捷键在输入框 / 文本域聚焦时一律让出原生行为，不抢键。

---

## 硬性依赖

| 依赖 | 版本 / 要求 | 用途 |
| --- | --- | --- |
| **Python** | 3.12+ | 后端运行时（`backend/pyproject.toml` 声明 `requires-python >=3.12`） |
| **uv** | 最新 | Python 包管理与虚拟环境（`uv sync` / `uv run`） |
| **Docker + Docker Compose** | 可用即可 | Redis 服务（48211）+ 代码沙盒镜像 `chatme-python-sandbox:latest` |
| **Node.js** | 18+ | 前端构建与 Electron 桌面端 |
| **OpenAI 兼容 LLM** | `api_key` + `base_url` + `model_name` | 唯一的硬性外部服务；缺失则工作流无法运行 |
| **内存** | 4GB+ | 沙盒容器池 + 文件解析 |

### 可选（不配也能跑）

- **搜索源 Key**：Bocha / Exa / Tavily 任一即可启用联网搜索。
- **本地 VL 模型**：图片解析走本地 Qwen3-VL；不启用则回落到主 LLM。

> 沙盒不可用时会自动降级到本机 venv 执行，但**不推荐**——代码隔离与权限审批是核心安全边界。
