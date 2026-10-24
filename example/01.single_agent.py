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

# Run Agent
response = agent.run("Hello, who are you?")
print(response)
