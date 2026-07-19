"""
ChatWorkflow 通用 helper —— 所有**纯函数 / 与类状态无关**的工具函数集中在这里。

包含四组：
1. `get_message_content_string`  : BaseMessage.content → str（处理 str / list / dict 三种 content 形态）
2. `filter_thinking_content`     : 过滤 AI 回复里的思考标签（含 MiniMax-M3 方括号包装的伪 tool_call 块兜底）
3. `get_message_role`            : BaseMessage → role 字符串（用于思维链日志统一格式）
4. `format_thinking_chain`       : List[BaseMessage] → `[(role, msg), ...]` 单行字符串

> ⚠️ **filter 同步约定**（详见 CLAUDE.md 第 7.1 条）：
> `filter_thinking_content` 必须在 `helpers.py` 和 `Memory/core.py` **两处**保持一致；
> 新增 MiniMax-M3 输出格式时必须同步更新两处。

为什么抽到 module-level 函数：
- 这些 helper 都不依赖 ChatWorkflow 实例状态，pure function
- 多处复用（core.py 5+ 处，Memory/core.py 1 处）
- 单元测试不依赖 ChatWorkflow 初始化（不需要 mock LLM / Redis）
- 降低 ChatWorkflow 类的方法数量，让 `_create_graph_core2` 内部节点函数更聚焦
"""
import re
from typing import Callable, List

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from .config.models import AIMessageType


# =========================================================================
# 1. BaseMessage.content → str
# =========================================================================

def get_message_content_string(message: BaseMessage) -> str:
    """
    提取消息内容为字符串。处理 LangChain 三种 content 形态：
    - str    : 直接返回
    - list   : 多模态（text / image_url 等），仅取 type=='text' 的项拼接
    - dict   : {type: 'text'|'tool', text|content: ...}
    """
    content_string = ""

    if not message:
        return content_string

    message_content = message.content

    if isinstance(message_content, str):
        content_string = message_content
    elif isinstance(message_content, list):
        for item in message_content:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "text":
                    content_string += item.get("text", "")
            elif isinstance(item, str):
                content_string += item + "\n"
    elif isinstance(message_content, dict):
        msg_type = message_content.get("type")
        if msg_type == "text":
            content_string = message_content.get("text", "")
        elif msg_type == "tool":
            content_string = message_content.get("content", "")

    return content_string


# =========================================================================
# 2. 过滤 AI 回复中的思考过程 + MiniMax-M3 伪 tool_call 块
# =========================================================================

# 7 个变体的 regex（拆开维护，避开反向引用 / 嵌套量词的坑）
_FILTER_PATTERNS = [
    # 通用思考标签
    r'<thinking>.*?</thinking>',
    r'<thought>.*?</thought>',
    r'<reasoning>.*?</reasoning>',
    r'<think>.*?</think>',
    # ⚠️ MiniMax-M3 工具调用方括号包装：[</tool_call>] / [/tool_calls] / [<]tool_call[>] / [<]tool_calls[>]
    # 两种位置会出现：① 作为孤立标记（下面的 wrapper pattern 直接清掉）；
    # ② 跟在裸的 <tool_call>/<tool_calls> 开头后面当闭合（这种情况下 wrapper 必须被允许作为
    # </tool_call(s)> 的可选外壳，否则会留下半截 tool_call 块）。
    # 关键顺序：先跑 tool_call 块整匹配（含 wrapper 闭合），wrapper 正则放后面做兜底。
    # 否则 wrapper 先剥 → tool_call 块找不到闭合 → 留下 <tool_call>\n<invoke>...</invoke> 这种半截垃圾。
    # 单/复数都吃：`<tool_call>` / `<tool_calls>` 都允许作为开闭标签（实测 M3 两种都会输出）。
    # ⛔ (?!\s*<invoke) 跳过含真 <invoke> 的块：M3 偶发只把 tool_call 序列化到 content、不填结构化 tool_calls 字段，
    # 此时若 filter 把整块剥光 → _parse_content_to_tool_calls 拿到空 content → AIMessage.content='' & tool_calls=[]
    # → 路由进 should_end_node 后陷入 retry 空转。保留含 <invoke> 的真块让 parse 提 tool_calls，wrapper-only 碎块（deb
    # ris）继续由这条 pattern 兜底清掉。 [\s\S]*? 替代 .*? 以跨行匹配（M3 输出 <tool_calls> 与 </tool_calls> 之间常含 \n）。
    r'<tool_calls?>(?!\s*<invoke)[\s\S]*?\[?</?tool_calls?>\]?',
    # 方括号包装的孤标记（裸的 <tool_call> 块吃不到这些）
    r'\[</?tool_calls?>\]',
    r'\[<\]tool_calls?\[>\]',
    # 方括号包装的 invoke 块：[<invoke name="cmd">][<command>...</command>][</invoke>]
    # 拆开匹配，避免反向引用 / 非贪婪嵌套
    r'\[<invoke [^>\]]+>\]',
    r'\[</invoke>\]',
    r'\[<(\w+)>[^<]*</\1>\]',
    # M3 在 </tool_calls> 之后多余的左括号（不破坏合法的 <tool_calls> 块本身）
    r'</tool_calls?>\s*\[+',
    # 孤立开标签（无闭合）—— M3 第一次调用工具时 content 里只剩开标签的场景。
    # 整块 pattern `<tool_calls?>.*?\[?</?tool_calls?>\]?` 因为找不到 `</tool_calls?>` 的 `<`
    # 会整体匹配失败；这条兜底吃掉 `<tool_calls>\n` 这种纯开标签。
    # 放在最后跑：整块 pattern 先吃掉完整块，剩下的孤立开标签由这条兜底。
    r'<tool_calls?>\s*\n?',
]


def filter_thinking_content(ai_response: AIMessage) -> AIMessage:
    """
    过滤掉 AI 回复中的思考过程内容。

    支持格式：
    - `<thinking>...</thinking>` / `<thought>...</thought>` / `<reasoning>...</reasoning>` / `<think>...</think>`
    - MiniMax-M3 工具调用方括号包装：`[</tool_call>]` / `[/tool_calls]` / `[<]tool_call[>]` / `[<]tool_calls[>]`
    - MiniMax-M3 裸 tool_call 块：``<tool_call>...[<invoke name="cmd">][<command>...</command>][</invoke>]</tool_call>``
    - 关键顺序：先跑 tool_call 块整匹配（含 wrapper 闭合），wrapper 正则放后面做兜底

    Returns:
        新的 AIMessage（保留 additional_kwargs / response_metadata / id / usage_metadata / tool_calls）
    """
    content = ai_response.content
    if not content:
        return ai_response

    if isinstance(content, str):
        for pattern in _FILTER_PATTERNS:
            content = re.sub(pattern, '', content, flags=re.DOTALL)

    return AIMessage(
        content=content,
        additional_kwargs=ai_response.additional_kwargs,
        response_metadata=ai_response.response_metadata,
        id=ai_response.id,
        usage_metadata=getattr(ai_response, "usage_metadata", None),
        tool_calls=getattr(ai_response, "tool_calls", []) or [],
    )


# =========================================================================
# 3. 消息角色分类（用于思维链日志）
# =========================================================================

def get_message_role(m: BaseMessage) -> str:
    """
    给消息分类角色，用于思维链日志统一格式。

    Role 分类：
    - system     : SystemMessage（系统提示 / 摘要 / Warning / 中断原因）
    - human      : HumanMessage（用户输入，含 imp_ipt 标记）
    - agent      : AIMessage (REASONING)  —— agent_node 输出（带 tool_calls）
    - final_node : AIMessage (SUMMARY)    —— final_node 输出（最终回复）
    - tool       : ToolMessage（工具返回）
    - unknown    : 其他
    """
    if isinstance(m, SystemMessage):
        return "system"
    if isinstance(m, HumanMessage):
        return "human"
    if isinstance(m, AIMessage):
        if m.additional_kwargs.get("type") == AIMessageType.SUMMARY.value:
            return "final_node"
        return "agent"
    if isinstance(m, ToolMessage):
        return "tool"
    return "unknown"


# =========================================================================
# 4. 思维链格式化
# =========================================================================

def format_thinking_chain(
    messages: List[BaseMessage],
    content_extractor: Callable[[BaseMessage], str] = get_message_content_string,
    max_chars: int = 0,
) -> str:
    """
    格式化消息链为 `[(role, msg), ...]` 统一格式，给 AI 思维链日志用。

    示例输出（单行）：
        [(system, '你是一个助手...'), (human, '分析 sales.csv'), (agent, ''), (tool, '5万行...'), (final_node, '已生成图表')]

    Args:
        messages: 消息列表
        content_extractor: 提取消息内容为 str 的函数（默认用本模块的 get_message_content_string）
        max_chars: 单条消息内容最大字符数（0 = 不截断）。截断超出加 '... [truncated N chars]'。
                   默认 0（不截断，让日志完整；如要控制日志体积可设 500~2000）。

    Returns:
        单行字符串，调用方自行加 \\n 换行
    """
    items = []
    for m in messages:
        role = get_message_role(m)
        content = content_extractor(m)
        if max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars] + f"... [truncated {len(content) - max_chars} chars]"
        items.append(f"({role}, {content!r})")
    return "[" + ", ".join(items) + "]"
