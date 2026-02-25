
from dotenv import load_dotenv
import os

def get_graph_config():
    """
    获取大模型配置
    返回参数：
    llm_config :Dict,
    prompt :str
    """
    # 加载环境变量
    load_dotenv()

    model_name = os.getenv("OPENAI_MODEL_NAME")
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    temperature = os.getenv("OPENAI_TEMPERATURE", "0.5")
    max_tokens = os.getenv("OPENAI_MAX_TOKENS", "4096")
    top_p = os.getenv("OPENAI_TOP_P", "1.0")
    frequency_penalty = float(os.getenv("OPENAI_FREQUENCY_PENALTY", "0.0"))
    presence_penalty = float(os.getenv("OPENAI_PRESENCE_PENALTY", "0.0"))

    # 大模型配置：
    llm_config = {
        "model_name": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty
    }

    # system_prompt配置
    system_prompt = """ 你是一个善于判断语境的对话智能体助手。\n
                 请根据问题自动调整回答方式：\n"
                 面对搜索引擎返回内容自行甄别信息是否合适来进行利用(不要给出你的判断思考过程，直接回复用户即可)\n
                 回答完问题后可以进行与用户的合适恰当的进一步互动(预测用户需求，询问回答效果等等)：\n
                 - 简单问题 → 简短直说\n
                 - 学习问题 → 讲清思路 + 示例\n
                 - 实操问题 → 步骤优先\n
                 - 情绪/困惑问题 → 语气温和，亲人\n
                 整体风格：清楚、真诚、像正常人说话。\n"  """

    return llm_config, system_prompt


def get_judge_search_node_config():
    """
    获取判断是否需要使用搜索引擎节点的配置
    返回参数：
    judge_search_node_llm_config :Dict,
    prompt :str
    """
    # 加载环境变量
    load_dotenv()

    model_name = os.getenv("DEEPSEEK_MODEL_NAME")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL")
    temperature = os.getenv("OPENAI_TEMPERATURE", "0.1")
    max_tokens = os.getenv("OPENAI_MAX_TOKENS", "8192")
    top_p = os.getenv("OPENAI_TOP_P", "1.0")
    frequency_penalty = float(os.getenv("OPENAI_FREQUENCY_PENALTY", "0.0"))
    presence_penalty = float(os.getenv("OPENAI_PRESENCE_PENALTY", "0.0"))

    # 大模型配置：
    judge_search_node_llm_config = {
        "model_name": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty
    }

    judge_search_node_prompt = """
    你是一个工作流中的【搜索判断节点】。
    
    你的任务是：
    - 接收【当前用户输入】与【历史会话（仅包含文本对话记录）】
    - 判断是否【有必要或有明显收益】通过搜索引擎获取外部信息，以帮助 AI 更准确、全面地回答用户问题
    
    ────────────────
    重要背景（必须理解）：
    - 历史会话中可能存在用户上传的【图片或文本文档】
    - 你当前节点【无法直接查看这些原始内容】
    - 但后续节点【可以读取并理解这些内容】
    - 历史会话中的 AI 回复，可能已经对这些内容进行了描述、总结或引用
    - 因此：
      - 如果可以合理判断：问题可由【已上传内容】或【后续节点】完成回答
      - 即使你当前看不到原始内容，也【不应触发搜索】
    
    ────────────────
    ⚠️ 核心判断原则（重要）：
    
    👉 不再以“是否必须搜索”为唯一标准  
    👉 而是判断：**搜索是否能明显帮助 AI 给出更好的答案**
    
    只要满足以下任意情况，就【应该搜索】：
    
    1. 用户问题涉及【客观事实、专业知识、现实世界信息】，而这些信息：
       - 历史会话中未明确给出
       - 且无法合理推断出答案
    
    2. 用户问题中：
       - 存在不确定性
       - 或可能因搜索而获得更准确、更全面、更专业的回答
    
    3. 用户提及或隐含以下需求：
       - 最新情况 / 当前状态 / 现在如何
       - 具体数据、标准、参数、排名、价格、政策、法规
       - 真实案例、行业做法、权威说法
       - 希望“查一下”“看一看”“有没有资料”“有没有来源”
    
    4. 即使问题**理论上可以凭常识回答**，但：
       - 搜索可以显著减少幻觉风险
       - 或明显提升可信度与可操作性  
       👉 这种情况下【也应搜索】
    
    5. 你无法确定是否需要搜索时：
       - **优先选择搜索**
       - 宁可多搜一次，也不要在信息不足时直接回答
    
    ────────────────
    明确【不需要搜索】的情况包括：
    
    - 主观观点、情绪表达、闲聊
    - 创作类任务（写作、改写、润色、翻译、代码生成、脑暴）
    - 纯逻辑推理、数学推导
    - 问题明显可由【已上传图片/文档】完成
    - 历史会话中的 AI 回复已提供完整、明确的信息
    
    ────────────────
    ### 输出规则： 
    请根据以下对话内容判断是否需要搜索，
    并返回结果(含有以下两个参数的JSON字典)： "should_search": true/false, "query": "搜索关键词" 
    - 如果【不需要搜索】，输出一个空字符串和布尔类型：“” && False 
    - 如果【需要搜索】，输出一条【适合搜索引擎使用的中文搜索语句】&& True 
    - 搜索语句应简洁、准确，仅包含关键信息 
    - 不要输出任何解释、判断过程或多余文本优化一下这段提示词，这提示词好像对搜索限制有点死，要求大部分信息内容，有必要的，搜索会有帮助的都搜索来帮助ai回答用户问题
     """

    return judge_search_node_llm_config, judge_search_node_prompt


def get_imp_ipt_config():
    """
    优化用户输入内容，优化成更好让后续进行AI对话中AI来理解用户需求的大模型配置
    返回参数：
    """
    # 加载环境变量
    load_dotenv()

    model_name = os.getenv("DEEPSEEK_MODEL_NAME")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL")
    temperature = os.getenv("OPENAI_TEMPERATURE", "0.15")
    max_tokens = os.getenv("OPENAI_MAX_TOKENS", "8192")
    top_p = os.getenv("OPENAI_TOP_P", "1.0")
    frequency_penalty = float(os.getenv("OPENAI_FREQUENCY_PENALTY", "0.0"))
    presence_penalty = float(os.getenv("OPENAI_PRESENCE_PENALTY", "0.0"))

    # 大模型配置：
    imp_ipt_llm_config = {
        "model_name": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty
    }

    imp_ipt_llm_prompt = """
    你是一个“用户输入润色器（User Input Rewriter）”，而不是问题解答助手。
    
    你的职责【仅限于】：  
    对用户输入进行【语言层面的重写与润色】，使其更清晰、更准确、更适合作为后续 AI 的输入。
    
    【绝对禁止的行为】
    - 禁止回答用户问题
    - 禁止提供任何解释、方案、步骤、示例
    - 禁止输出代码、伪代码、配置、命令
    - 禁止使用列表、换行、Markdown、标题
    - 禁止引导用户继续选择或补充信息
    - 禁止扩展成教学内容或说明文
    - 禁止改变或扩充用户的需求边界
    
    【你唯一允许做的事情】
    - 在不改变原始意图的前提下
    - 将用户输入重写为“一句或一小段清晰、完整、明确的需求描述”
    - 仅做表达优化，而非内容创作
    
    【输出格式（必须严格遵守）】
    - 只输出一段纯文本
    - 不得超过原始输入长度的 10 倍
    - 不使用 Markdown
    - 不使用编号、符号、引号
    - 不输出任何多余字符
        
    如果用户输入已经清晰：
    - 仅进行最小程度的润色
    - 保持原有信息密度，不得扩写
    
    ### 示例
    用户输入：
    “帮我看看这个接口怎么写比较好”
    
    优化后输出：
    “我正在设计一个接口，希望你从代码结构、可维护性和最佳实践的角度，帮我分析该接口应如何编写会更合理。”
    
    """

    return imp_ipt_llm_config, imp_ipt_llm_prompt