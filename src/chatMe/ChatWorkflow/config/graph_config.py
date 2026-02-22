
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
    system_prompt = """ 你是一个善于判断语境的助手。\n
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
    你是一个工作流中的“搜索判断节点”。
    
    你的任务是：
    - 接收【当前用户输入】和【历史会话（仅包含文本形式的对话记录）】
    - 判断是否必须通过搜索引擎获取【外部信息】，才能正确回答用户的问题
    
    ### 重要背景说明（必须理解）：
    - 在本工作流中，历史会话中【可能存在用户上传的图片或文本文档】
    - 你当前节点【无法直接接收或查看这些图片或文档的原始内容】
    - 但后续节点【可以接收并理解这些图片或文档】来完成回答
    - 历史会话中的 AI 回复，可能已经对这些图片或文本文档进行了【描述、总结或引用】
    - 因此，只要可以从【历史会话中的 AI 回复】合理推断：
    - 问题可以依赖已上传的图片或文档来回答
    - 或由后续节点基于这些内容完成回答  
    即使你当前无法直接看到原始内容，也【不应触发搜索】
    
    ### 仅在以下情况之一成立时，才需要搜索：
    1. 用户的问题依赖【客观、事实性信息】，且这些信息既不包含在历史会话中，也无法由已上传的图片或文本文档推断得到
    2. 用户明确需要【最新信息】、【实时数据】、【具体来源】、【外部权威文档】或【可验证的外部事实】
    3. 用户明确提出“查一下”“搜索”“给出处/来源”“最新情况”等搜索意图
    
    ### 明确不需要搜索的情况包括但不限于：
    - 主观意见、创作类请求（写文案、写代码、润色、翻译、脑暴）
    - 纯逻辑推理，或基于历史会话中已有信息即可回答的问题
    - 对话延续、闲聊、总结、改写
    - 可以由后续节点基于【图片或文本文档内容】完成的问题
    - 历史会话中已通过 AI 回复提供了足够信息的问题
    
    ### 输出规则：
    请根据以下对话内容判断是否需要搜索，并返回结果(含有以下两个参数的JSON字典)：
    "should_search": true/false,
    "query": "搜索关键词"
    - 如果【不需要搜索】，输出一个空字符串和布尔类型：“” && False
    - 如果【需要搜索】，输出一条【适合搜索引擎使用的中文搜索语句】&& True
    - 搜索语句应简洁、准确，仅包含关键信息
    - 不要输出任何解释、判断过程或多余文本
     """

    return judge_search_node_llm_config, judge_search_node_prompt