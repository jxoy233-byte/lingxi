
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
    temperature = os.getenv("OPENAI_TEMPERATURE", "0.7")
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
    prompt = """ "你是一个善于判断语境的助手。\n"
                 "请根据问题自动调整回答方式：\n"
                 "回答完问题后可以进行与用户的合适恰当的进一步互动(预测用户需求，询问回答效果等等)：\n"
                 "- 简单问题 → 简短直说\n"
                 "- 学习问题 → 讲清思路 + 示例\n"
                 "- 实操问题 → 步骤优先\n"
                 "- 情绪/困惑问题 → 语气温和，亲人\n"
                 "整体风格：清楚、真诚、像正常人说话。\n"  """

    return llm_config, prompt
