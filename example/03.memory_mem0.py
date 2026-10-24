# Enable Memory Module

# Or use a custom memory module, here is an example with mem0 https://github.com/mem0ai/mem0/
import os
from pathlib import Path

# mem0 默认把 history.db / config.json 写到 ~/.mem0。
# 必须在 import mem0 之前设置 MEM0_DIR：这个目录是 mem0 的 memory/setup.py 在导入时算好的，
# 事后再改环境变量不生效。指到项目目录可以避免跨项目、跨 mem0 版本互相踩 schema。
os.environ.setdefault("MEM0_DIR", str(Path(__file__).resolve().parent / ".mem0"))

from mem0 import Memory
from LightAgent import LightAgent
from loguru import logger

from dotenv import load_dotenv
# 从同目录下的 .env 文件加载 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / QDRANT_API_KEY
load_dotenv(Path(__file__).with_name(".env"))

# 维度必须转 int：环境变量读出来都是字符串
EMBED_DIMS = int(os.getenv("OPENROUTER_EMBEDDING_DIMS", "2048"))

class CustomMemory:
    """ The protocol `protocol.py:MemoryProtocol`'s implementation ()"""
    def __init__(self):
        self.memories = []
        # os.environ["OPENAI_API_KEY"] = "your_api_key"
        # os.environ["OPENAI_BASE_URL"] = "http://your_base_url/v1"
        # Initialize Mem0
        config = {
            "version": "v1.1",

            # mem0 需要 LLM 做记忆抽取，这里直接走 OpenRouter。
            # 0.1.70 的 openai provider 有个隐藏行为：只要环境里存在 OPENROUTER_API_KEY，
            # 它就自动把 client 指到 OpenRouter（base_url 取 config.openrouter_base_url，
            # 默认 https://openrouter.ai/api/v1）。既然本来就要用 OpenRouter，正好利用这一点。
            # 注意 :free 模型和 embedding 共用同一个免费额度池，50 次/天，容易打满。
            "llm": {
                "provider": "openai",
                "config": {
                    "model": os.getenv("OPENROUTER_LLM_MODEL"),
                    "api_key": os.getenv("OPENROUTER_API_KEY"),
                    "openrouter_base_url": os.getenv("OPENROUTER_EMBEDDING_BASE_URL"),
                },
            },

            "embedder": {
                "provider": "openai",
                "config": {
                    "model": os.getenv("OPENROUTER_EMBEDDING_MODEL_NAME"),
                    "api_key": os.getenv("OPENROUTER_API_KEY"),
                    # 只写到 /v1，SDK 自己会拼 /embeddings
                    "openai_base_url": os.getenv("OPENROUTER_EMBEDDING_BASE_URL"),
                    "embedding_dims": EMBED_DIMS,
                },
            },

            "vector_store": {
                "provider": "qdrant",
                "config": {
                    # 先运行 ssh -N -L 6333:127.0.0.1:6333 aliyun-ecs-hnujl
                    # 用 url 而不是 host/port：显式 http:// 才不会在带 api_key 时被客户端切换成 TLS。
                    # （新版 mem0 可以用 "https": False，但 0.1.70 的配置模型不接受这个字段）
                    "url": "http://127.0.0.1:6333",
                    "api_key": os.getenv("QDRANT_API_KEY"),  # 服务端开了 api key，不传会 401
                    "collection_name": "lightagent_memories",
                    "embedding_model_dims": EMBED_DIMS,
                    "on_disk": True,  # 向量落盘，服务器只有 1.8G 内存
                },
            }
        }
        self.m = Memory.from_config(config_dict=config) # self.m 是 mem0提供的接口对象，开发者可以使用 mem0 提供的接口来实现存储和检索记忆的功能

    def store(self, data: str, user_id):
        """
        Store memory. Developers can modify the internal implementation of the storage method; the current example is the mem0 method for adding memory.

        Args:
            data (str): The memory data to be stored.
            user_id (str): The user ID associated with the memory.
        """
        result = self.m.add(data, user_id=user_id) # `add`, `search`, `update`, `delete`这些都是 mem0提供的接口
        return result

    def retrieve(self, query: str, user_id):
        """Retrieve related memory. Developers can modify the internal implementation of the retrieval method; the current example is the mem0 method for searching memory."""
        # mem0 2.x 不再接受顶层 user_id，必须放进 filters，否则 ValueError
        result = self.m.search(query, filters={"user_id": user_id})
        return result

agent = LightAgent(
        role="Please remember that you are LightAgent, a useful assistant to help users use multiple tools.",  # system role description
        model=os.getenv("MODEL_NAME"),  # Supported models: openai, chatglm, deepseek, qwen, etc.
        api_key=os.getenv("DEEPSEEK_API_KEY"),  # Replace with your large language model provider API Key
        base_url=os.getenv("DEEPSEEK_BASE_URL"),  # Replace with your large language model provider api url
        memory=CustomMemory(),  # Enable memory function
        tree_of_thought=False,  # Enable Chain of Thought
    )

# Memory-enabled test & if tools need to be added, you can add tools to the agent for memory-enabled tool calls

user_id = "user_01"
logger.info("\n======== first conversation ===========")
query = "Introduce me to the attractions in Sanya. Many of my friends have traveled to Sanya, and I want to visit too. (Just response me with five short sentences)"
print(agent.run(query, stream=False, user_id=user_id))
logger.info("\n=========== next conversation ===========")
query = "Where should I travel? Just response me with five short sentences"
print(agent.run(query, stream=False, user_id=user_id))