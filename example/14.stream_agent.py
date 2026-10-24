import os
from pathlib import Path

from dotenv import load_dotenv
from LightAgent import LightAgent

# 从同目录下的 .env 文件加载 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL
load_dotenv(Path(__file__).with_name(".env"))

# Initialize Agent
agent = LightAgent(
    model=os.getenv("MODEL_NAME"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
)

# Run Agent in streaming mode
response = agent.run("who are you?", stream=True)

# 逐个打印增量内容（返回的是 OpenAI 兼容 chunk）
for chunk in response:
    delta = None
    if getattr(chunk, "choices", None): # 流式的`run()`返回的generator, 包含来自`_run_stream_logic`中的各种yield, 必须要检查是否有choices属性
        delta = chunk.choices[0].delta.content
    if delta:
        print(delta, end="", flush=True)
print()
