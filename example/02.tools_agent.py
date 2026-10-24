import os
from pathlib import Path

from dotenv import load_dotenv
from LightAgent import LightAgent

# 从同目录下的 .env 文件加载 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL
load_dotenv(Path(__file__).with_name(".env"))


# # Define Tool
# def get_weather(city_name: str) -> str:
#     """
#     Get the current weather for `city_name`
#     """
#     return f"Query result: {city_name} is sunny."


# # Define tool information inside the function
# get_weather.tool_info = {
#     "tool_name": "get_weather",
#     "tool_description": "Get current weather information for the specified city.",
#     "tool_params": [
#         {"name": "city_name", "description": "The name of the city to query", "type": "string", "required": True},
#     ]
# }

# tools = [get_weather] # 逻辑在 core.py : LightAgent.load_tools中, 输入tools列表中是callable, 那么直接注册(ToolRegister)
tools = ["get_weather"] # 如果是字符串, 那就先通过 ToolLoader 进行解析和加载, 然后再注册

# Initialize Agent
agent = LightAgent(model=os.getenv("MODEL_NAME"),
                   api_key=os.getenv("DEEPSEEK_API_KEY"),
                   base_url=os.getenv("DEEPSEEK_BASE_URL"),
                   tools=tools,
                   debug=True, # 调试模式, 能记录日志
                )  # 日志级别（INFO, DEBUG, ERROR）, 这里最高打印出 debug

# Run Agent
response = agent.run("Please check the weather in Shanghai.")
print(response)
