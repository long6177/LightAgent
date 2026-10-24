import os
from loguru import logger
from LightAgent import LightAgent, LightSwarm
import os
from pathlib import Path

from dotenv import load_dotenv
# 从同目录下的 .env 文件加载 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL
load_dotenv(Path(__file__).with_name(".env"))

agent = LightAgent(
        name="Agent A",  # 代理名称
        instructions="You are a helpful agent.",  # 角色描述
        role="Please remember that you are LightAgent, a useful assistant to help users use multiple tools.",  # system role description
        model=os.getenv("MODEL_NAME"),  # 支持的模型：openai, chatglm, deepseek, qwen 等 qwen-turbo-2024-11-01 \ step-1-flash
        api_key=os.getenv("DEEPSEEK_API_KEY"),  # 替换为你的 API Key
        base_url=os.getenv("DEEPSEEK_BASE_URL"),  # api url
        debug=True,
        log_level="DEBUG",
        log_file="example.log"
    )


# 模拟历史对话
history = [
    {"role": "user", "content": "以后叫我 小明"},
    {"role": "assistant", "content": "好的，我会记住的，小明。"},
]


user_id = "test_user_2"
query = "我是谁? 你怎么得知的?"
response = agent.run(query, history=history, stream=True, user_id=user_id, session_id="test_session_2")  # 使用 agent 运行查询
for chunk in response:
    print(chunk.choices[0].delta, end="\n", flush=True)

session_event_stream = agent.export_session(session_id="test_session_2")  # 导出会话历史到 JSON 文件

# 打印会话事件流
for event in session_event_stream['events']:
    print(event['type'])