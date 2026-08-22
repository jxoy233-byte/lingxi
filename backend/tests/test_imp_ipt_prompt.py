"""
测试 PROMPT_INPUT_PARSE / llm_imp_ipt 的优化效果。
用 ChatMeConfig + get_imp_ipt_config() 完全相同的 prompt + LLM 配置，
对若干真实输入做优化，看输出是否符合预期。

用例覆盖：
  1. Slash 命令（不能动前缀，只优化 args）
  2. 指代模糊（追加 [Note: assuming ...]）
  3. 极短输入（<5字 原样保留）
  4. 复杂任务（重构为 [目标]/[输入]/[步骤]/[要求]）
  5. 引用上下文（去 <quote> 标记，保留内容）
  6. 普通口语化输入（优化为清晰可执行表达）
  7. 中英混排 / 翻译兜底（保持原语言）
  8. 含文件解析结果（不删改）
"""
import asyncio
import os
import sys
from pathlib import Path

# 强制把 ChatMeConfig 指向项目的 .chatme（不污染用户配置）
os.chdir(Path(__file__).resolve().parents[1])
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage

from ChatMe.ChatMeConfig.core import ChatMeConfig
from ChatMe.ChatWorkflow.config.graph_config import (
    get_imp_ipt_config,
    distinguish_extra_body,
)


CASES = [
    # 1. Slash 命令 — 前缀一字不改，args 可优化
    {
        "label": "[Slash] /[DataAnalysis] 看销售趋势",
        "input": "/[DataAnalysis] 看销售趋势",
        "expect": "前缀 /[DataAnalysis] 完整保留；后面变成清晰指令",
    },
    # 2. 指代模糊 — 追加 [Note: assuming ...]
    {
        "label": "[指代模糊] 它怎么了",
        "input": "它怎么了",
        "expect": "原句保留 + 追加一行 [Note: assuming ...]",
    },
    # 3. 极短输入 — 原样保留
    {
        "label": "[极短] 好的",
        "input": "好的",
        "expect": "原样输出，不加任何解释",
    },
    # 4. 复杂任务 — 拆解为 [目标]/[输入]/[步骤]/[要求]
    {
        "label": "[复杂] 帮我把 sales.csv 三个品类的趋势画成折线图，标注同比，导出一页总结",
        "input": "帮我把 sales.csv 三个品类的趋势画成折线图，标注同比，导出一页总结",
        "expect": "重构为规划输入格式（[目标]/[输入]/[步骤]/[要求]）",
    },
    # 5. 引用上下文 — 去掉 <quote>，保留内容
    {
        "label": "[引用] <quote>...长引用...</quote> 基于这个写个测试",
        "input": "<quote>\n## User\n帮我看看数据库连接\n</quote>\n\n基于这个写个测试",
        "expect": "去掉 <quote> 标记，引用内容作为上下文保留",
    },
    # 6. 普通口语化 — 优化为清晰可执行
    {
        "label": "[口语化] 嗯那个数据分析你能给我看看最近那个报表吧",
        "input": "嗯那个数据分析你能给我看看最近那个报表吧",
        "expect": "去掉语气词、改成清晰指令",
    },
    # 7. 中英混排 — 保持原语言（不要翻译成英文）
    {
        "label": "[中英混排] search for 销售趋势 并画出趋势图",
        "input": "search for 销售趋势 并画出趋势图",
        "expect": "保持中英混合原样，不全翻译成一种语言",
    },
    # 8. 文件输入 — 保留文件标记
    {
        "label": "[文件] [文件：report.csv]\n<content>...</content>\n总结这份报告",
        "input": "[文件：report.csv]\n<content>\nQ1 销售 100 万\nQ2 销售 150 万\n</content>\n\n总结这份报告",
        "expect": "保留文件标记，不删改内容",
    },
]


async def main():
    # 复用项目 ChatMeConfig 拿主用 LLM
    cfg = ChatMeConfig()
    chain = cfg.get_llm_providers_chain()
    if not chain:
        print("ERROR: llm_providers 没配置有效项，先在 .chatme/config.json 配一下")
        sys.exit(1)
    primary = chain[0]

    # 完全复刻 ChatWorkflow.__init__ 里的 llm_imp_ipt 配置
    llm_config = {
        "model": primary["model_name"],
        "api_key": primary["api_key"],
        "base_url": primary["base_url"],
        "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.3")),
        "max_tokens": int(os.getenv("OPENAI_MAX_TOKENS", "4096")),
        "top_p": float(os.getenv("OPENAI_TOP_P", "1.0")),
        "timeout": int(os.getenv("OPENAI_TIMEOUT", "60")),
        "max_retries": 3,
        "model_kwargs": {"stream_options": {"include_usage": True}},
        "extra_body": distinguish_extra_body(primary["model_name"]),
    }
    print(f"使用 LLM: {primary['model_name']} @ {primary['base_url']}")
    print(f"temperature={llm_config['temperature']} max_tokens={llm_config['max_tokens']}")
    print()

    # 直接拿 get_imp_ipt_config 返回的 prompt
    _, prompt_str = get_imp_ipt_config()
    prompt = ChatPromptTemplate.from_messages([
        ("system", prompt_str),
        ("human", "{user_input}"),
    ])
    llm = ChatOpenAI(**llm_config)
    chain_pipe = prompt | llm

    results = []
    for i, case in enumerate(CASES, 1):
        print(f"{'='*80}")
        print(f"用例 {i}: {case['label']}")
        print(f"输入:   {case['input']!r}")
        print(f"预期:   {case['expect']}")
        try:
            resp = await chain_pipe.ainvoke({"user_input": case["input"]})
            output = resp.content if hasattr(resp, "content") else str(resp)
            print(f"输出:   {output!r}")
            results.append({
                **case,
                "output": output,
                "ok": True,
            })
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
            results.append({**case, "output": None, "ok": False, "error": str(e)})
        print()

    print(f"{'='*80}")
    print("汇总:")
    ok_count = sum(1 for r in results if r["ok"])
    print(f"  成功 {ok_count}/{len(results)}")
    if ok_count < len(results):
        print("  失败用例:")
        for r in results:
            if not r["ok"]:
                print(f"    - {r['label']}: {r.get('error', '')}")


if __name__ == "__main__":
    asyncio.run(main())