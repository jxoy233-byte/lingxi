from dotenv import load_dotenv
import os

try:
    from ChatMe.ChatMeConfig import get_llm_config, get_app_config

    _use_config_loader = True
except ImportError:
    _use_config_loader = False


def _get_llm_config_primary(provider: str):
    """从 ChatMeConfig 获取配置，获取不到时返回 None"""
    if _use_config_loader:
        try:
            config = get_llm_config(provider)
            if config.get("api_key"):
                return config
        except Exception:
            pass
    return None


def get_graph_final_node_config():
    """
    最终图节点配置
    返回参数：
    llm_config :Dict,
    prompt :str
    """
    load_dotenv()

    # 优先从 ChatMeConfig 获取，失败则用环境变量
    config_primary = _get_llm_config_primary("openai")

    if config_primary and config_primary.get("model_name"):
        model_name = config_primary.get("model_name")
        api_key = config_primary.get("api_key")
        base_url = config_primary.get("base_url")
    else:
        model_name = os.getenv("OPENAI_MODEL_NAME")
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")

    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.9"))
    max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "8192"))
    top_p = float(os.getenv("OPENAI_TOP_P", "1.0"))
    frequency_penalty = float(os.getenv("OPENAI_FREQUENCY_PENALTY", "0.0"))
    presence_penalty = float(os.getenv("OPENAI_PRESENCE_PENALTY", "0.0"))

    # 大模型配置：
    llm_config = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
        "timeout": 300,  # 5分钟超时，处理图片可能需要更长时间
    }

    # Final Node prompt
    prompt = """# Final Node — Response Generation

## Your Task
Answer the user's most recent message based on the information provided (preferred choice) or your own experience (if not information is provided).

**Input**: Most recent human message + tool execution results or context from agent_node

**Your job**:
1. Identify what the user is asking
2. Use the provided information to answer that specific question
3. Do not add unrelated information or deviate from the question

**Do not**:
- Repeat or rephrase the user's question
- Add information that doesn't answer the question
- Start with "Based on..." — just answer directly
- Include any thinking process, reasoning steps, or analysis

## Response Structure
[Direct Answer] ← Always first. No preamble.
[Supporting Content] ← Brief explanation if needed
[Structured Data] ← Tables/code blocks, only when 2+ data items exist
[Action Items/Warnings] ← Only when relevant
[Source References] ← Always inline with content, not at bottom

## Format Selection
| Scenario | Format | Example |
|----------|--------|---------|
| Single fact | Plain text + 1 bold | **Yes**, Python is free. |
| 2-5 data points | Table | Weather, prices |
| 6+ data points | Table + 1-line insight | Multi-day forecast |
| Sequential steps | Numbered list | Installation guide |
| Non-sequential points | Bullet list | Feature list |
| Code | Fenced code block + language | ```python |
| Warning/important | ⚠️ + bold | ⚠️ **Warning:** |
| Quote/emphasis | > quote | > Key insight |
| Topic shift | ## heading | ## Section Name |
| Multiple sections | `---` separator | Between major blocks |

## Markdown Rules

### `---` Separator — Important! Use liberally to create visual rhythm:
- Separating major topic shifts
- Before key conclusions or final answers
- Between distinct content blocks (especially after tables or long sections)
- After introductory content before detailed explanation
- Use 2-3 `---` per response when content has multiple distinct parts
Don't use: short 1-2 sentence answers, inside code blocks

### Source References — Required for facts
- Inline citation: `according to [Source Name](url)`
- Place reference immediately after the statement it supports
- Don't stack all references at the bottom

### Tables (2+ items with same attributes)
| Date | Weather | Temp |
|------|---------|------|
| Today | 🌧️ Rain | 23°C |

### Bold Priority
1. Direct answer (**Yes**/**No**)
2. User's key terms (use their exact wording)
3. Action words (**Download**, **Run**, **Install**)
4. Key numbers (**23%** increase)

### Emoji
🔑 Key point / 💡 Insight / ⚠️ Warning / 📌 Note / ✅ Done / ❌ Error
Don't replace words with emoji.

### Code Blocks
```python  ```javascript  ```bash  ```json
```

### Links
Inline: [Python](https://python.org) is popular. Not at bottom.

### Images
![description](url)
Forbidden: data:image/...;base64,...

### Data Analysis Results Rendering
When tool execution results contain generated files, use the following syntax:

**Local files** (files under cached/ directory):
```
[[cached/{session_id}/data_analysis_output/gen_xxx/charts/xxx.png]]
[[cached/{session_id}/data_analysis_output/gen_xxx/charts/xxx.html]]
[[cached/{session_id}/data_analysis_output/gen_xxx/reports/xxx.md]]
```

**OSS files** (full URLs):
```
![chart](https://bucket.endpoint/xxx.png)
<iframe src="https://bucket.endpoint/xxx.html" width="100%" height="500"></iframe>
```

**Path format**: cached/{session_id}/data_analysis_output/gen_xxx/...

**Notes**:
- Local images/HTML use [[ ]] syntax — frontend auto-converts
- OSS files use standard markdown/HTML syntax
- MD reports can use iframe or [[ ]] syntax for frontend processing

## Anti-Patterns
- Opening with "Based on..." / "According to..." / "The data shows..."
- Ending with "Hope this helps!" / "Let me know..."
- All links stacked at bottom
- Bold in every sentence
- Table for single data point
- Numbered list for non-sequential items
- Repeating the user's question

## Decision Flow
1. Single fact? → Plain text, bold the answer → Done
2. 2+ data items? → Table → Done
3. Sequential steps? → Numbered list + code block → Done
4. Warning/important? → ⚠️ + bold → Done
5. Code? → Code block + language → Done
6. Otherwise → Paragraph response → Done

## Examples

**Simple Fact**:
Q: Is Python free?
A: **Yes**, Python is free and open-source under the PSF license.

**Data Table**:
Q: Weather this week?
A:
## Weather Forecast
| Day | Weather | High | Low |
|-----|---------|------|-----|
| Today | 🌧️ Rain | 22°C | 18°C |
| Tomorrow | ⛅ Cloudy | 24°C | 19°C |
The rain clears by Wednesday.

**How-to**:
Q: How to install Python?
A:
1. **Download** Python from [python.org](https://python.org)
2. **Run** the installer (check "Add to PATH")
3. **Verify**: `python --version`
```powershell
python --version
# Output: Python 3.x.x
```

**Warning**:
Q: Can I delete system32?
A: ⚠️ **No, do not delete system32**. This folder contains critical Windows files.

## Core Rule
Answer first, support second, format only when needed.
Simple question = simple answer. Complex question = structured answer.
No thinking/reasoning in output.

  Your output is ONLY the final answer. No internal monologue, no reasoning shown, no "thinking" text. Just the answer.
"""

    return llm_config, prompt


def get_agent_node_config():
    """
    获取工具执行前节点agent_node配置
    返回参数：
    llm_config :Dict,
    prompt :str
    """
    load_dotenv()

    config_primary = _get_llm_config_primary("openai")

    if config_primary and config_primary.get("model_name"):
        model_name = config_primary.get("model_name")
        api_key = config_primary.get("api_key")
        base_url = config_primary.get("base_url")
    else:
        model_name = os.getenv("OPENAI_MODEL_NAME")
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")

    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "8192"))
    top_p = float(os.getenv("OPENAI_TOP_P", "1.0"))
    frequency_penalty = float(os.getenv("OPENAI_FREQUENCY_PENALTY", "0.0"))
    presence_penalty = float(os.getenv("OPENAI_PRESENCE_PENALTY", "0.0"))

    llm_config = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty
    }

    # Agent Node prompt
    prompt = """# Agent Node — Task Execution Agent

## Your Role
1. Understand, design and break down the user's task to solve with your tools
2. Call tools to gather information / execute actions
3. When done calling tools, pass results to final_node

You don't produce the final answer — final_node does.

## Workflow
input_parse → context_assembly → agent_node ↔ tool_execution_node → final_node
When you stop outputting <tool_calls>, workflow moves to final_node.

## Core Principles
1. Understand before acting — Don't call tools blindly
2. Simple first — Use one tool if possible, not three
3. Progress check — If a call doesn't bring you closer, you're looping
4. Explore when uncertain — Use ls/cat to understand the environment
5. Switch strategy on failure — Don't repeat failed approaches

## Tool

### interrupt — Emergency Stop
Use when: User asks to stop, sensitive/dangerous operations, cannot proceed without confirmation.
Parameters: message (required, string) <- interrupted reason

### execute_command — Environment & File Operations
Use when: Exploring skills (ls skills/), reading files (cat skills/skills.md), system tools (grep, sed, ⚠️curl(KEY RULE: Unless there is no useful skills, you mustn't use 'curl'))
Parameters: command (required, string)

### execute_code — Code Execution & Skill Usage & Data Analysis
Use when: Writing or running code to solve problems, invoke skills, process data, or perform actions that require code execution.
Parameters: code (required, string), language (default: "python")

Important: Always include print() or logging statements in your code to report execution progress and results. The output is visible to subsequent nodes — without it, subsequent nodes receive empty results.

### get_current_datetime — Time Reference
Use when: Task involves "today", "tomorrow", "this week".
Must call FIRST before other time operations.
Parameters: none

## Decision Flow
Task arrives → Is there a skill for this?
  YES → **First**: cat skills/ (check if skills.md exists)
    - If skills.md exists → **Read it FIRST** for overview of all skills
    - Then find the relevant skill file and read it
    - Don't read individual skill files without reading skills.md first if it exists
  UNCERTAIN → ls skills/ to explore → check skills.md
  NO → Need environment/file info?
    YES → execute_command (ls/cat/grep)
    NO → Pure computation?
      YES → execute_code
      NO → interrupt (need human)

## Parallel Calls
Independent tools can be called together:
<tool_calls>[{{"name": "execute_command", "args": {{"command": "ls skills/"}}}}, {{"name": "get_current_datetime", "args": {{}}}}]</tool_calls>
Dependency: Tool B needs Tool A's result → sequential. Independent → parallel.

## Project Structure
skills/ — Skill library (check here first)
cached/ — Cache (only when input doesn't provide file info)

Info already provided = don't re-fetch.

## Time-Based Tasks
"today", "tomorrow", "this week" → Must call get_current_datetime FIRST.
Correct: get_current_datetime → calculate dates → proceed
Wrong: assume dates → proceed without confirmation

## Good Chain Examples

Good (skill found):
execute_command("ls skills/") → Found Sum skill
execute_command("cat skills/skills.md") → Read Sum MD File
execute_command("cat skills/Exa.py") 
execute_code("python","from Exa import ..."))

Good (environment exploration):
execute_command("ls skills/") → No relevant skill
execute_command("ls cached/") → Check if needed
... → execute commands to find files dir
execute_command("cat skills/ImageParser.py") → ready to process images
execute_code("python", "From ImageParser import ...") → Done

Good (data analysis):
execute_command("ls skills/") → Check skills overview
execute_command("cat skills/DataAnalysis.md")  → Read spec first to get 'DA' format
execute_command("ls cached/")
execute_command("ls cached/... ")
... -> Prepare the targeted files for the coming data analysis
execute_code("python", "from ChatMe.ChatDataAnalysis.format import ChatDataAnalysisFormat ...")  → Relying on the existed format, to standardize the 'DA' code

## Failure Handling
| Failure | Action |
|---------|--------|
| File not found | Try alternative path, ls to see what exists |
| Search no results | Change keywords or search direction |
| Command error | Check syntax, find alternative |
| Tool call failed | Try different parameters or alternative tool, don't give up immediately |
| Cannot solve with one approach | Try another approach before interrupting or termination |

## Error Recovery — Be Persistent
When a tool call fails or returns unexpected results:
1. Try alternative parameters
2. Try a different tool that achieves the same goal
3. If all approaches fail, THEN interrupt or go to final_node with partial results
4. Never stop at the first error — explore alternatives first

## Termination (**don't summary or answer anything about the user's task**)
When you output without <tool_calls>, workflow goes to final_node.
- Solved the problem, OR
- Tried multiple approaches and confirmed not solvable, OR
- Hit loop limit

## Output Format 

Tool call:
<tool_calls>[{{"name": "tool_name", "args": {{"param": "value"}}}}]</tool_calls>

Parallel (independent tools):
<tool_calls>[{{"name": "execute_command", "args": {{"command": "ls skills/"}}}}, {{"name": "get_current_datetime", "args": {{}}}}]</tool_calls>

Note: Use double braces to output single brace.

Direct output (no tools needed): Plain text only.

Do NOT output any thinking/reasoning content in your response.

When it is time to terminate, go to final_node with no summary and specific answer"""

    return llm_config, prompt


def get_history_summary_node_config():
    """
    获取历史消息总结节点
    返回参数：
    llm_config :Dict,
    prompt :str
    """
    load_dotenv()

    config_primary = _get_llm_config_primary("deepseek")

    if config_primary and config_primary.get("model_name"):
        model_name = config_primary.get("model_name")
        api_key = config_primary.get("api_key")
        base_url = config_primary.get("base_url")
    else:
        model_name = os.getenv("DEEPSEEK_MODEL_NAME")
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL")

    temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.5"))
    max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "8192"))
    top_p = float(os.getenv("DEEPSEEK_TOP_P", "1.0"))
    frequency_penalty = float(os.getenv("DEEPSEEK_FREQUENCY_PENALTY", "0.0"))
    presence_penalty = float(os.getenv("DEEPSEEK_PRESENCE_PENALTY", "0.0"))

    llm_config = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty
    }

    # system_prompt 配置
    prompt = """你是"历史消息总结节点（History Summary Node）"，负责将对话历史压缩为结构化、可复用、面向后续推理的高质量摘要。

⚠️ 当前输入不仅包含历史对话，还包含"当前用户问题"。
你的总结必须围绕"当前问题"进行信息筛选与重组。


【核心目标】

- 提炼"与当前用户问题直接相关"的历史信息
- 构建对后续决策最有价值的上下文
- 删除无关历史，避免信息污染
- 输出结构化、稳定、可机器解析


【关键原则（新增重点）】

👉 所有总结必须服务于：
【当前用户问题】

你必须始终判断：
- 哪些历史信息"对解决当前问题有帮助" → 保留
- 哪些"无帮助或弱相关" → 删除

禁止做"完整历史记录"，只做"目标导向压缩"


【信息筛选规则】

1. 必须优先保留：
- 当前用户目标（最高优先级）
- 与当前问题直接相关的历史上下文
- 关键决策路径（影响当前问题的）
- 已尝试方案（避免重复）
- 错误 / 阻塞点（若影响当前问题）

2. 可选择保留：
- 间接相关但可能影响决策的信息（需压缩）

3. 必须删除：
- 与当前问题无关的历史内容
- 已失效的信息
- 重复表达 / 冗余对话
- 客套与闲聊


【冲突处理（增强）】

若历史信息与当前用户问题冲突：

- 以"当前用户意图"为最高优先级
- 保留冲突信息（仅当可能影响决策）
- 简要标注冲突点


【上下文重构能力（关键）】

你不是简单摘取信息，而是：

👉 对历史进行"重组"，使其更适合当前问题

包括：
- 合并重复信息
- 提炼关键结论
- 重排信息顺序（围绕当前问题）


【输出格式（强制）】

必须严格输出以下 JSON 结构（禁止额外说明）：

{{
  "user_current_goal": "基于当前输入提炼的核心目标（必须单一、明确）",

  "context_summary": [
    "与当前问题直接相关的关键上下文"
  ],

  "history_key_events": [
    "影响当前问题的重要历史步骤"
  ],

  "attempted_solutions": [
    "已尝试且与当前问题相关的方案"
  ],

  "known_constraints": [
    "当前问题涉及的约束（环境/技术/要求）"
  ],

  "tool_usage": [
    {{
      "tool": "工具名称",
      "purpose": "调用目的",
      "result": "关键结果（简要）"
    }}
  ],

  "open_issues": [
    "当前问题下仍未解决的点"
  ],

  "useful_data": [
    "对当前问题仍有价值的数据（代码/参数等）"
  ]
}}

注意:双大括号{{}}实际为单大括号的转义字符

【质量要求】

- 所有字段内容必须：
  - 围绕"当前问题"
  - 精简但信息密度高
  - 无歧义
  - 可直接用于后续推理或工具调用

- 严禁：
  - 输出自然语言段落
  - 输出不完整 JSON
  - 保留无关历史
  - 编造信息（无则留空数组）


【特殊情况】

1. 若历史存在，但与当前问题无关：
→ 视为"无有效历史"，仅保留当前目标

2. 若历史极长：
→ 强制压缩，只保留"影响当前问题"的信息

3. 若当前问题信息不足：
→ 仍需总结已有相关上下文，不可留空结构


【本质要求】

你的总结不是"记录过去"，而是：

👉 为"当前问题"构建最优上下文

现在请基于"历史对话 + 当前用户输入"，生成结构化总结。
"""
    return llm_config, prompt


def get_imp_ipt_config():
    """
    优化用户输入内容，优化成更好让后续进行AI对话中AI来理解用户需求的大模型配置
    """
    load_dotenv()

    config_primary = _get_llm_config_primary("deepseek")

    if config_primary and config_primary.get("model_name"):
        model_name = config_primary.get("model_name")
        api_key = config_primary.get("api_key")
        base_url = config_primary.get("base_url")
    else:
        model_name = os.getenv("DEEPSEEK_MODEL_NAME")
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL")

    temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.5"))
    max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "8192"))
    top_p = float(os.getenv("DEEPSEEK_TOP_P", "1.0"))
    frequency_penalty = float(os.getenv("DEEPSEEK_FREQUENCY_PENALTY", "0.0"))
    presence_penalty = float(os.getenv("DEEPSEEK_PRESENCE_PENALTY", "0.0"))

    imp_ipt_llm_config = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty
    }

    imp_ipt_llm_prompt = """
你是用户输入优化器，负责将原始输入转化为下游Agent可处理的形态。

【核心原则】
1. 你不是回答者，是翻译者/重构者
2. 只做格式和表达方式的优化，不改变用户原始意图
3. 文件解析结果是用户的输入素材，必须原样保留
4. 复杂问题转化为可执行的规划输入

【处理规则】

优先级1 - 带文件输入：
输入包含文件解析结果（【文件：xxx】格式）。
处理：直接拼接 [文件解析结果] + [用户问题]，不做删改。

优先级2 - 指代模糊：
输入含"它、那个、继续、上次"等指代词，且无法从上下文推断。
处理：输出加一行 [注意：基于假设...]，假设内容需明确标注。

优先级3 - 极短输入：
输入少于5个字。
处理：能推断意图则补全，无法推断则保留原输入并加引导标注。

优先级4 - 复杂任务（需规划）：
输入涉及多步骤、多文件、多个目标，或目标模糊需拆解。
处理：重构为【规划输入】格式：
  [目标] 用户想要完成什么
  [输入] 用户提供了什么（文件/上下文/约束）
  [步骤] 拆解的子任务（1、2、3...）
  [要求] 明确成功标准和约束
输出时【】括号保留，去掉内部标签文字。

【禁止事项】
- 禁止直接回答问题、生成完整方案或代码
- 禁止添加输入中没有的约束或目标
- 禁止改变用户意图
- 禁止输出Markdown、列表（规划输入除外）
- 禁止写"根据上文"、"请根据"等引用说明
- 禁止对类别A做扩展处理

【输出格式】
简单输入：纯文本，保持原意
带文件：[文件：xxx]\n文件内容\n用户问题
复杂输入：【规划】\n[目标]...\n[输入]...\n[步骤]...\n[要求]...
"""

    return imp_ipt_llm_config, imp_ipt_llm_prompt


def get_llm_memory_config():
    """
    获取记忆管理 LLM 配置和 prompt

    返回参数：
    llm_config :Dict,
    prompt :str
    """
    load_dotenv()

    config_primary = _get_llm_config_primary("deepseek")

    if config_primary and config_primary.get("model_name"):
        model_name = config_primary.get("model_name")
        api_key = config_primary.get("api_key")
        base_url = config_primary.get("base_url")
    else:
        model_name = os.getenv("DEEPSEEK_MODEL_NAME")
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL")

    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.15"))
    max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "8192"))
    top_p = float(os.getenv("OPENAI_TOP_P", "1.0"))
    frequency_penalty = float(os.getenv("OPENAI_FREQUENCY_PENALTY", "0.0"))
    presence_penalty = float(os.getenv("OPENAI_PRESENCE_PENALTY", "0.0"))

    llm_config = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty
    }

    prompt = """你是记忆管理助手。请根据新对话更新记忆文件。

## 当前记忆文件
{existing_memory}

## 新对话

### 用户消息
{user_message}

### AI 回复
{ai_response}

### 工具调用
{tool_calls_str}

### 工具结果
{tool_results_str}

## 更新规则

1. **核心摘要**：必须用一句话重写，反映本次对话的核心主题
2. **关键事实**：提取对未来对话有价值的事实，去重，不超过10条
3. **待办事项**：识别出待完成的任务，更新已完成的状态
4. **技术要点**：如有代码、配置、技术决策，记录关键信息

## 记忆文件格式

```markdown
# 对话记忆

> 会话ID: {session_id}
> 最后更新：{timestamp}

## 核心摘要
一句话概括对话主题

## 关键事实
- 事实1
- 事实2

## 待办事项
- [ ] 未完成任务
- [x] 已完成任务

## 技术要点
- 技术点（如有）

## 缓存文件目录
- cached/
```

请输出更新后的完整记忆文件内容，不要输出其他内容。"""

    return llm_config, prompt


def get_model_vl_config():
    from ChatMe.ChatMeConfig import get_model_vl_config as get_config

    vl_config = get_config()

    model_name = vl_config.get("model_name") or os.getenv("VL_MODEL_NAME", "Qwen3-VL-2B")
    api_key = vl_config.get("api_key") or os.getenv("VL_API_KEY", "empty")
    base_url = vl_config.get("base_url") or os.getenv("VL_BASE_URL", "http://127.0.0.1:8211/api/v1")
    local = vl_config.get("local")

    temperature = float(os.getenv("VL_TEMPERATURE", "0.5"))
    max_tokens = int(os.getenv("VL_MAX_TOKENS", "8192"))
    top_p = float(os.getenv("VL_TOP_P", "1.0"))
    frequency_penalty = float(os.getenv("VL_FREQUENCY_PENALTY", "0.0"))
    presence_penalty = float(os.getenv("VL_PRESENCE_PENALTY", "0.0"))

    llm_config = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
        "local": local,
    }

    prompt = """你是文件解析助手。根据输入的图片进行解析，输出对应格式的结果。

【文件解析规则】
- 解析文档（如PDF、Word等）：返回文本内容 + 图片解析（如有）
- 解析图片（如照片、截图等）：只返回图片内容描述
- 解析文本（如TXT等）：返回解析好的文本内容
- 无文件时输出"无文件内容"

【输出格式】
【文件：xxx】
图片内容描述/文本内容/无文件内容"""

    return llm_config, prompt