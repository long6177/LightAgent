# LightAgent 学习总结：从 `run()` 主循环到运行时、会话与记忆

> 复习镜像 · 2026-10-24
>
> 第二版（同日）：修正“架构图已全部学过”的过度假设；补充各模块的“设计智慧”与思维导图笔记对照。
>
> 第三版：根据自我评估，把第 7 节（能力与策略）从“已学”降级为“未学”；移除其中未验证的机制细节，改为定位 + 待学清单。
>
> 第四版（2026-10-24）：三篇记忆文档已读完，更新 8.2 / 8.3 状态与读后记；memcode 仍未读。
>
> 证据来源：当前工作区 `LightAgent/`、`docs/`、`tests/` 里的注释（未提交改动）、`notes/01`、`notes/02`，以及 `notes/architecture/` 中我**实际看过的那部分**架构图与思维导图笔记。
>
> 说明：`notes/architecture/` 里共有 34 张图，但**我只精读过其中一部分，不能把“图存在”当成“我学过”**。本文只把与注释、笔记、思维导图能相互印证的内容当作已学证据，其余一律降级为“知道存在/待学”。

---

## 0. 怎么用这份总结

### 0.1 证据分级

本文对每个结论标注了把握程度，避免把“推演”误当成“读过代码”：

| 标记 | 含义 | 典型来源 |
| --- | --- | --- |
| ✅ | **注释实证**：我在工作区源码/文档/测试里写过注释，理解经过自己复述 | `git diff` 中新增的中文注释、docstring |
| 📝 | **笔记/图谱实证**：我写过专门的分析笔记，或**确认看过**并能复述的架构图 | `notes/01`、`notes/02`、`notes/architecture/` 中实际参考的部分 |
| 🧭 | **配套印证**：通过文档、测试或示例反推，读过但未必逐行注释 | `docs/*.md`、`tests/*.py`、`example/*.py` |
| ○ | **尚未展开**：知道它存在，但没有系统学习 | 第 7 节（整节待学）、第 14 节 |

> 另：每节末尾的“设计智慧”段落属于**理解性评论**，不是源码事实；它回答的是“为什么这样设计、代价是什么”，方便复习时把**机制和动机一起想起来。**
>
> 本文唯一整节按 ○ 处理的是第 7 节（能力与策略）：它不是“已学”，只是待学定位；其余章节才按 ✅/📝/🧭 分级。

### 0.2 推荐复习路径

```text
第 1 遍（10 分钟）：第 1 节全景图 + 第 12 节坑清单 + 第 13 节速查表
第 2 遍（40 分钟）：第 2~6 节，按“执行链 → 工具 → 会话 → 运行时 → 记忆”顺序；第 7 节只作待学清单
第 3 遍（按需）    ：第 8~10 节的 docs / tests / examples 足迹 + 第 14 节待办
```

最省力的自测方式：看完每一节后，合上文档，尝试回答该节末尾的“自检问题”。

### 0.3 一句话主线

> LightAgent 是一个**以同步 `run()` 为主循环**的 Agent 框架，围绕主循环外挂了四套横向能力：工具生态、事件溯源会话、可插拔记忆、运行时；另外还有一层能力/策略——那一层我目前只知道定位，尚未系统学（见第 7 节）。它的大多数复杂设计，都是在这条同步主循环与异步/持久化/安全边界之间做适配。

### 0.4 读完应该能做到

- 画出 `run()` 的九阶段执行链，并指出同步/异步、流式/非流式在哪些点分叉；
- 说清四类工具在 `dispatch()` 里的不同命运，以及为什么异步生成器不等于端到端流式；
- 解释 `SessionEvent → ContextProjector → messages/trace` 的投影关系，以及三种 Store 的差异；
- 解释 Runtime 如何从 Session 恢复 Inbox/Goal/Budget/Job，以及 Job lease/fencing 保护什么、不保护什么；
- 解释记忆的读、写、过滤、晋升四条路径，以及 `injectable` 的含义；
- 说清 Capability / Policy 大概负责什么，并明确知道**自己还没学过**（第 7 节），不把“知道名字”冒充成“掌握机制”；
- 知道哪些模块还没学，下一步该补什么；
- 对每个已学模块，能说出**至少一条“为什么这样设计”和一条“代价是什么”**（见各节末尾的“设计智慧”与第 11.1 节）。

### 0.5 文档地图

```text
0  怎么用（证据分级、复习路径）
1  全景（时间线、注释热力表、模块地图、四条主线）
2  主执行链 run()（九阶段、双循环、同步/异步、设计智慧）
3  工具模块（注册/加载/调度、四类工具、生成器边界、设计智慧）
4  会话模块（事件溯源、Store、投影、压缩、设计智慧）
5  Runtime（Inbox/Goal/Budget/Job/Subagent、恢复语义、设计智慧）
6  记忆模块（读/写/晋升/过滤、策略与后端、设计智慧）
7  能力与策略（**尚未系统学**：仅定位 + 待学清单，不写机制详解）
8  docs 足迹（runtime_v010、文档地图）
9  tests 足迹（fake client、失败注入、测试地图、环境坑）
10 examples 足迹（DeepSeek、mem0/Qdrant 踩坑）
11 横向主题 + 设计智慧总览（十条框架设计原则）
12 坑清单（13 条，已剔除未验证的能力层推测）
13 复习速查表（30 个已学符号；能力/策略符号暂不列入）
14 尚未展开与下一步
15 附录（注释统计、前序笔记、图集、思维导图、命令、注释摘录、边界）
```

---

## 1. 全景：学习轨迹与模块地图

### 1.1 时间线（从 git 历史与笔记日期还原）

| 时间 | 动作 | 产出 |
| --- | --- | --- |
| 2026-09 上旬 | 开始系统读源码，逐步沉淀架构图集（**图集是学习资产，不代表每张都精读过**） | `notes/architecture/` 早期图 |
| 09-28 | 全量重建图谱，给节点加源码锚点 | 24 张图重建提交 |
| 10-09 | 补 runtime、event flow、session event-sourcing | 图 25、26、27 |
| 10-10 | 画 runtime 设计全景 | 图 28 |
| 10-11 | 写 `run` 同步/异步架构分析；画 run callchain | `notes/01`；图 29 |
| 10-12 | run callchain 拆成 29 总览 + 30~33 分场景 | 4 张 sequence 图 |
| 10-13 | 总结异步生成器工具的价值与边界 | `notes/02` |
| 10-14 | 修正 session sequence | 图 12 |
| 10-17~18 | 补 memory 读写剖面、protocol 记忆类型、memory callchain | 图 08、34 |
| 学习全程 | 用 XMind 维护一份学习导图 | 222 节点、6 个分支；memory + runtime 占约 78%（见 15.4） |
| 10-24 | 汇总本总结 | 本文 |

这条时间线说明我的学习不是“按目录顺序读”，而是**沿着问题走**：先抓住主循环，再追同步/异步边界，然后向外扩到会话、运行时、记忆。

### 1.2 注释足迹热力表（未提交改动，936 行新增）

| 文件 | 新增行 | 我重点注释的内容 | 证据 |
| --- | ---: | --- | --- |
| `LightAgent/core.py` | 191 | `run` 阶段、`_record_trace` 映射、记忆读写/晋升、非流式与流式主循环 | ✅ |
| `LightAgent/protocol.py` | 303 | 记忆协议、`MemoryScope`、候选/晋升/准入决策、`MemoryPolicy` 全链路 | ✅ |
| `LightAgent/session.py` | 159 | 事件模型、append/fork/replay、Store 协议与三实现、投影、上下文压缩 | ✅ |
| `LightAgent/tools.py` | 66 | 注册表、加载器、调度器四类工具、参数校验 | ✅ |
| `LightAgent/runtime.py` | 33 | Inbox 幂等、`open_session` 恢复、`_append` 事件镜像 | ✅ |
| `LightAgent/capabilities.py` | 20 | 只有名词级注释，**未系统学**（第 7 节按待学处理） | ○ |
| `LightAgent/shared_memory.py` | 2 | 定位：轻量原型而非生产后端 | ✅ |
| `docs/runtime_v010.md` | 11 | Runtime 长任务状态、fencing epoch、MCP 兼容性 | ✅ |
| `tests/test_v065_core.py` | 22 | 假客户端注入、Arrange-Act-Assert | ✅ |
| `tests/test_v010_session.py` | 5 | JSONL 损坏检测、原子保存失败注入 | ✅ |
| `example/01,02,03,06` | 121 | DeepSeek 接入、mem0 配置踩坑、流式消费、会话导出 | ✅ |
| `example/14.stream_agent.py` | 新增文件 | 流式 chunk 的 `delta.content` 消费方式 | ✅ |

> 说明：新增行包含代码调整与注释，评论性行粗略统计为 core 54、protocol 42、session 47、tools 22、tests 12、examples 24、docs 4。这个分布基本就是我的学习重心；`capabilities.py` 虽然也有 20 行改动，但只到框架级注释，不能算掌握。

### 1.3 模块地图

```text
                           ┌──────────────────────────────┐
                           │  examples / docs / tests      │  ← 使用面与验证面
                           └──────────────┬───────────────┘
                                          │
┌─────────────────────────────────────────▼─────────────────────────────────────────┐
│                              LightAgent (core.py)                                  │
│  run() ──► _begin_session_run ──► hooks/guardrails ──► memory ──► model request     │
│    │                                   │                                          │
│    ├── _core_run_logic ──► _run_non_stream_logic ──┐                               │
│    │                       _run_stream_logic ──────┤                               │
│    │                                               ▼                               │
│    │                                   AsyncToolDispatcher.dispatch                 │
│    │                                               │                               │
│    ├── arun()/astream() ──► to_thread 适配层        │                               │
│    └── _record_trace ──► Session 事件镜像           │                               │
└───────┬───────────────────────────┬─────────────────┬──────────────────────────────┘
        │                           │                 │
        ▼                           ▼                 ▼
┌───────────────┐         ┌──────────────────┐  ┌──────────────────┐
│ tools.py      │         │ session.py       │  │ protocol.py      │
│ 注册/加载/调度 │         │ 事件溯源 + 投影   │  │ 记忆契约/策略     │
└───────────────┘         └────────┬─────────┘  └────────┬─────────┘
                                   │                     │
                          ┌────────▼─────────┐   ┌───────▼─────────┐
                          │ runtime.py       │   │ shared_memory.py│
                          │ Inbox/Goal/Budget│   │ 内存型记忆原型   │
                          │ Job/Subagent     │   └─────────────────┘
                          └────────┬─────────┘
                                   │
                          ┌────────▼─────────┐
                          │ capabilities.py  │
                          │ Provider/Policy  │
                          └──────────────────┘
```

> 说明：图中 `capabilities.py` 仅仅表示“它在这个架构位置”，**不代表我学过**；这一层在第 7 节按待学处理。

### 1.4 四条贯穿主线

1. **执行链**：`run()` → `_core_run_logic()` → 非流式/流式循环 → 工具调度 → 再次模型请求。
2. **状态链**：一切运行事实先变成 `SessionEvent`，再由 `ContextProjector` 投影回消息、运行时状态和 trace。
3. **策略链**：Hook / Guardrail 我已经接触；Capability Policy / Permission / Approval 属于第 7 节的待学内容——先知道它们处在这条链上，但不假装理解细节。
4. **接口链**：`Protocol` + 适配器支撑第三方替换；工具和记忆的协议我实际读过，Provider 只在运行时/导图里见过、还没深究。

---

## 2. 主执行链：`run()` 的完整解剖 ✅📝

对应文件：[`LightAgent/core.py`](../LightAgent/core.py)；对应笔记：[`notes/01`](01_项目的run函数相关的同步异步架构设计_20261011_161110.md)。

前置知识：读这一节前最好熟悉 Chat Completions 的 request/response 形状（`choices[0].message`、`delta`、`tool_calls`、`finish_reason`、`usage`）。导图里也专门写了这一点——core 的阅读门槛主要在模型接口协议，而不在 Python 语法。

### 2.1 入口契约

`run()` 同时承担同步入口、流式入口和非流式入口，返回类型是三者联合：

```python
Union[Generator[str, None, None], str, RunResult]
```

参数组合有严格校验（这是复习时容易忘的细节）：

| 组合 | 是否允许 | 说明 |
| --- | --- | --- |
| `stream=False, result_format="str"` | ✅ | 默认，返回字符串 |
| `stream=False, result_format="object"` | ✅ | 返回 `RunResult` |
| `stream=False, result_format="dict"` | ✅ | 返回字典 |
| `stream=False, result_format="event"` | ❌ | 事件格式只对流式生效 |
| `stream=True, result_format="str"` | ✅ | 返回**生成器**，yield 原始 chunk |
| `stream=True, result_format="event"` | ✅ | 返回生成器，yield **`StreamEvent`** |
| `stream=True, result_format="object/dict"` | ❌ | 流式不做整体对象 |

此外 `max_tool_iterations` 必须 ≥ 1；未传时沿用 `max_retry`（保持旧行为）。

### 2.2 一次 `run()` 的九个阶段

下面是我理解的执行顺序（简化但保留关键分支）：

```text
1. 初始化运行标识
   traceid / _current_run_id / user / metadata / cancellation_token / idempotency_key
   → 创建 TraceRecorder，重置本轮计数器

2. 打开运行时会话 _begin_session_run()
   → runtime.open_session(session_id, ...)
   → ContextProjector().messages(current) 得到 projected_history
   → 设置 _current_session_id / _current_turn_id / runtime.context
   → 记录 turn.started、message.received

3. 运行前 Hook：before_run
   → 可 block，可改写 query

4. 输入 Guardrail：check_input
   → 可 block，可改写 query

5. 选择本轮工具
   → 运行时 tools → 临时注册表 → runtime_tools
   → 若传 light_swarm，先尝试任务转移（handoff）并可能直接返回

6. 组装 system prompt + 记忆上下文
   → 名称/指令/身份/日期时间/skills
   → _add_memory_context(query, user_id)   ← run() 里唯一直接“用记忆”的位置
   → Tree-of-Thought（可选）

7. 组装 chat_params
   → messages = [system] + history + [user]
   → metadata 合并进请求参数
   → tools 优先级：active_tools > runtime_tools > 初始化注册的工具

8. 首次模型请求
   → _prepare_model_request()：取消检查 → 上下文压缩 → before_model_request Hook
     → 预算 model_calls → 记录 model.requested（含完整 messages 快照）→ 计时
   → client.chat.completions.create(**chat_params)
   → _complete_model_request()：延迟、usage、预算 tokens、model.completed/failed

9. 交给核心逻辑并收口
   → _core_run_logic(response, stream, max_retry, effective_max_tool_iterations)
   → 非流式：_run_non_stream_logic / 流式：_run_stream_logic
   → _format_run_result 或 _stream_as_events
```

**值得记住的点**：`history` 的默认值不是“永远空列表”，而是：

```python
history = projected_history if history is None and session_id is not None else (history or [])
```

也就是说，只有显式传了 `session_id` 且没手写 `history` 时，才从会话事件里投影历史；否则使用调用方传入的历史（或空）。

### 2.3 `_begin_session_run()`：main loop 与 runtime 的接缝

这个函数虽然只有十几行，但把三件事同时做完了：

1. 通过 `runtime.open_session()` 打开或新建会话；
2. 用 `ContextProjector().messages()` 从事件流投影出“此前对话”；
3. 把本次运行的 `turn_id`、`run_id`、`metadata` 写进 `runtime.context`，并记录 `turn.started` 与 `message.received`。

它意味着：**`run()` 不是直接操作 `Session`，而是操作 `runtime`，由 `runtime` 管理“当前活动会话”**。`core.py` 与 `session.py` 之间因此多了一层生命周期管理。

### 2.4 记忆注入的位置

`_add_memory_context()` 的注释我写得很明确：整个 `run()` 只在进入模型前访问一次记忆模块。它做三件事（详见第 6 节）：

1. 检索 user scope 的相关记忆，拼到 query 前；
2. **把当前 query 也写回记忆**（默认 `source="user", scope="user"`）；
3. 若 `self_learning=True`，再检索 agent scope 的 reflection 记忆，拼成补充信息并写回。

因此，**记忆不是主循环每一轮都参与**，而是首轮请求(`turn_started`)前的一次性上下文增强；工具循环里的二次模型请求不会再次注入记忆。

### 2.5 非流式工具循环 `_run_non_stream_logic()`

外层 `for _ in range(max_retry)`，每轮检查“最新 response 有没有 tool_calls”：

```text
有 tool_calls
  ├─ 把 assistant tool_calls 消息 append 进 messages
  ├─ 逐个 tool_call：
  │    ├─ json.loads(arguments)；失败 → LA-JSON 错误作为 role=tool 消息回填
  │    ├─ _prepare_tool_call()：取消 → 策略 → 预算 → guardrail → hook
  │    ├─ run_async_safely(dispatch(name, args))
  │    ├─ 若返回 Generator：累积所有 chunk（finish 工具特殊处理 delta.content）
  │    ├─ after_tool_result hook
  │    ├─ 记录 tool_result trace
  │    └─ 将结果作为 role=tool 消息 append，必须带 tool_call_id
  └─ 回到循环顶部，准备下一轮模型请求

无 tool_calls
  ├─ 取 message.content
  ├─ _apply_output_guardrails()
  ├─ 记录 model_response
  └─ 返回最终文本（或 finish 工具时提前结束）
```

这里有一个历史演进痕迹，我在注释里特意保留：

```python
# tool_response = asyncio.run(...)                      # 第一版
# tool_response = await self.tool_dispatcher.dispatch() # 第二版
tool_response = run_async_safely(self.tool_dispatcher.dispatch(...))  # 第三版
```

它说明“同步主循环调用异步工具”的解决方案迭代过三次，最终落点是 `run_async_safely()` 的线程桥接。

### 2.6 流式工具循环 `_run_stream_logic()`

流式分支的骨架是“外层 `for max_retry` + 内层 `while True`”，每一轮处理一次模型流：

```text
for chunk in response:              # 同步迭代 SyncStream[ChatCompletionChunk]
    yield chunk                     # 原样把 chunk 交给调用方
    累积 content / reasoning_content
    从 delta.tool_calls 逐片累积 name / id / arguments
    if finish_reason 到达:
        处理 usage
        无工具调用 → 记录 model_response → _finish_run(success) → return
        有工具调用 → 进入下面的工具执行分支
```

两个关键细节：

1. **工具参数必须拼接**：流式响应会把一个 JSON 参数拆成很多片，所以是 `tool_calls[i]["arguments"] += delta.function.arguments`，不是覆盖。
2. **`yield` 的不止字符串**：模型 chunk 是 `ChatCompletionChunk` 对象；工具调用阶段还会 yield `{“name”, “title”, “arguments”}` 这样的字典；工具结果阶段也会 yield 字典。调用方不能无条件按字符串消费。

工具执行发生在“本轮模型流结束”之后：若工具返回生成器，其 chunk 会被继续 yield（若是 `ChatCompletionChunk` 则原样透传，否则包成 `tool_output` 字典）；随后才发起下一轮模型流。所以流式协议里实际混着“模型 chunk、工具调用信息、工具输出”三类数据。

这也是 `run(stream=True)` 的类型标注 `Generator[str, None, None]` 与实际产出不完全一致的原因——运行时不强制检查类型标注，IDE 提示是“名义类型”，真实协议要按分支看。

### 2.7 收口：`_finish_run()`、`_format_run_result()`、`_stream_as_events()`

- `_finish_run()`：统一结算。它会消费运行时长预算、触发 `on_error`/`after_run` Hook、记录 `run_end` trace，并补记 **`turn.completed`/`turn.failed`** 会话事件。
- `_format_run_result()`：把最终内容转成 `str` / `RunResult` / `dict`；顺带通过 `text.startswith("[LA-")` 识别错误码。
- `_stream_as_events()`：把“混合 yield 的流”包装成 `StreamEvent`；其中 `ChatCompletionChunk` 会作为 `type="content"` 的 `data` 原样透传，消费方仍需进一步处理。

### 2.8 同步/异步四象限（来自 notes/01 的核心结论）

| 调用方式 | 入口 | 实际执行位置 | 对调用方是否阻塞 |
| --- | --- | --- | --- |
| 同步非流式 | `agent.run(...)` | 当前线程 | 是 |
| 同步流式 | `agent.run(..., stream=True)` | 当前线程，迭代时推进 | 每次 `next()` 阻塞 |
| 异步非流式 | `await agent.arun(...)` | 线程池中的 `run()` | 否（事件循环不被占用） |
| 异步流式 | `async for ... in agent.astream(...)` | 每次 `to_thread(next, ...)` 推进同步生成器 | 否 |

两个桥接函数方向相反，不能混：

- `asyncio.to_thread()`：**异步 → 同步**，把同步 `run()` 丢到工作线程；
- `run_async_safely()`：**同步 → 异步**，让同步主循环能等待 `dispatch()` 协程；若当前线程已有事件循环，则另起单线程 + `asyncio.run()`。

结论仍然是 notes/01 的那句话：这是**兼容型过渡架构**，不是全链路原生异步。

### 2.9 本章的坑

1. **`Generator[str, ...]` 标注不可信**：流式实际 yield `ChatCompletionChunk` / `dict`。写消费代码时必须判类型、判 `choices`。
2. **异步生成器工具在旧版 `dispatch()` 里被 `str()` 洗成占位符**：这是 issue #107 的根因，我在流式分支的 `combined_response = str(tool_response)` 旁边写了 `issue #1` 注释。修复后由 `dispatch()` 内部缓冲收集再序列化。
3. **`astream()` 的 `finally` 必须关闭同步生成器**：消费者提前 `break` 时，`stream_result` 可能没被耗尽；`to_thread(close)` 用来释放资源。
4. **`arun()` 非流式路径的线程语义**：`run()` 被移到无事件循环的工作线程后，`run_async_safely()` 通常会走 `asyncio.run()` 分支，不会再额外开第二个线程。
5. **`_prepare_model_request()` 每次请求前都可能压缩上下文**：压缩发生在 Hook 之前，Hook 看到的是压缩后的 `params`。

### 2.10 设计智慧：为什么主循环要长成这样

- **把“兼容”当一等约束，而不是技术债**：同步 `run()` 是既成事实，重写成原生异步会同时改动模型客户端、工具、Hook、Session、Swarm。项目选择“同步核心 + 异步外壳”，让旧代码零迁移、新能力渐进接入。代价是线程切换、跨线程取消/超时更复杂，也拿不到全链路异步的并发收益——这是清醒的取舍，不是“没设计好”。
- **一次运行，两种投影**：trace 服务调试与指标，session 服务持久化与回放。同源双写的好处是排查时能互相印证；代价是映射表要长期维护，字段漂移会产生“trace 有、session 没有”的不一致。
- **流式协议向后兼容优先于纯度**：同一个生成器里混着模型 chunk、工具调用信息、工具输出。框架保住了旧调用方的消费方式，把“判类型”的复杂度转移给消费者——这是一种典型的“库作者替用户扛迁移成本，但把协议复杂度留给用户”的折中。
- **生成器惰性执行是特性，不是 bug**：创建不等于运行，包装层才有机会插入取消、关闭、重试和超时。理解这一点，才能解释 `astream()` 为什么要 `to_thread(next)` 并 `finally close`。
- **`run_async_safely()` 是“现实补丁”的范本**：不是追求架构纯粹，而是承认 FastAPI/Jupyter 等宿主已有事件循环的事实，用线程隔离做最小修复。工程上，能局部解决的问题不要上升为全局重构。

### 2.11 自检问题

- 为什么 `run()` 要在第一次模型请求前记录 `model.requested` 的完整 `messages` 快照？
- 非流式路径里，工具参数 JSON 解析失败后，为什么错误也要以 `role="tool"` 消息回填？
- `arun(stream=True)` 返回的到底是协程结果还是异步生成器？真正的执行从哪一刻开始？

---

## 3. 工具模块：注册、加载、调度 ✅📝

对应文件：[`LightAgent/tools.py`](../LightAgent/tools.py)；补充笔记：[`notes/02`](02_异步生成器工具的价值与边界_20261013.md)。

### 3.1 三件套

```text
ToolLoader ── 从 tools/*.py 动态 import（安全校验 + 缓存）
     │
     │ register_tool()
     ▼
ToolRegistry ── function_mappings / function_info / openai_function_schemas
     │
     │ 注入 mappings + info
     ▼
AsyncToolDispatcher ── 统一 async 调用入口，兼容四类工具
```

### 3.2 `ToolRegistry`：三个容器 + 一个诊断计数

| 容器 | 内容 | 给谁看 |
| --- | --- | --- |
| `function_mappings` | `name -> callable` | 调度器执行时用 |
| `function_info` | `name -> tool_info` | 参数校验、标题、描述 |
| `openai_function_schemas` | OpenAI tools 数组 | 发给模型看 |

注册逻辑的几个细节（都写过注释）：

- `register_tool()` 只接受带 `tool_info` 属性的函数；
- 同名工具注册时，旧 schema 会被**先删后加**，即“最新覆盖”；
- `_registration_counts` 只在“同名但不同函数对象”时递增，用于 `validate_tools()` 报“同名工具被注册多次”的错误；
- `filter_tools()` 接受模型输出的 JSON（可能带 Markdown 代码块），按名称过滤 schema，这是 Tree-of-Thought 选工具用的。

### 3.3 `ToolLoader`

- `tools/*.py` 动态 import（**根据目录`tool_directory`**)；
- 只允许字母/数字/下划线工具名（`_is_safe_tool_name`），防止路径穿越；
- `loaded_tools` 做进程内缓存；
- 加载后必须能在模块里找到同名且带 `tool_info` 的可调用对象，否则抛 `AttributeError`。

### 3.4 `AsyncToolDispatcher.dispatch()`：四类工具一张表

| 工具形态 | 判定 | dispatch 行为 | 返回给上层 |
| --- | --- | --- | --- |
| 普通同步函数 | `else` | 直接调用 | 序列化后的字符串 |
| 普通异步函数 | `iscoroutinefunction` | `await` | 序列化后的字符串 |
| 同步生成器 | `isgeneratorfunction` | **透传** `Generator` | 生成器（调用方消费） |
| 异步生成器 | `isasyncgenfunction` | `[chunk async for ...]` 全量收集 | 单 chunk 原值 / 多 chunk 拼接字符串 |

调用前还有三道闸门：

1. `is_unsafe_python_tool()` → 拒绝遗留 Python 执行器工具（`LA-SANDBOX`）；
2. `_validate_tool_params()` → 必填参数与基础类型校验；
3. `_serialize_result()` → dict/list 转 JSON，None 转固定提示，其余 `str()`。

### 3.5 生成器边界：为什么 `dispatch()` 是 `async` 却不等于“全异步”

`dispatch()` 本身是协程，只说明“它可以被 `await`”，不说明它调用的工具都是异步的。普通同步工具在 `dispatch()` 内直接调用；如果它执行长 I/O 或 CPU 计算，会阻塞承载 `dispatch()` 的事件循环。**只是当前常见路径里，这个事件循环位于工作线程（`run_async_safely` 创建的），所以阻塞的不是调用方主事件循环。**

我在 `notes/02` 里给出的判断公式仍然成立：

```text
异步生成器的价值 = 分段产生的结果 × 逐段消费的调用链
```

当前 `dispatch()` 对异步生成器是“内部逐段读、出口一次性汇总”，所以它保留了工具实现的自然接口，但没有端到端实时收益；同步生成器反而是透传的。

### 3.6 本章的坑

1. 同名工具会被静默覆盖，只有 `validate_tools()` 才会报告历史重名；
2. 工具返回生成器时，非流式循环会自行累积，流式循环则可能继续往下透传，两条路径行为不同；
3. 异步生成器在被 `dispatch()` 消费前不能离开事件循环；旧实现的 `str()` 占位符问题就是在这里暴露的；
4. `dispatch()` 的异常不会向上抛，而是被格式化成字符串返回给模型——这提高了鲁棒性，但模糊了“工具真的失败”和“工具返回错误文本”的边界。

### 3.7 设计智慧：工具系统为什么这样分层

- **一个工具，三类消费者**：调度器要可调用对象，校验器要参数元数据，模型要 OpenAI schema。把三者拆成 `function_mappings` / `function_info` / `openai_function_schemas`，比“一个万能 dict”更清晰，也让每类消费者只依赖自己需要的形状。
- **“最新覆盖 + 诊断报告”而不是“重复即报错”**：注册阶段保证可用性（后注册生效），诊断阶段保留可观测性（`validate_tools()` 报告历史重名）。这是“运行时宽容、检查时严格”的经典组合。
- **统一 async 入口封装异构性**：调用方只需要 `await dispatch(...)`，四类工具的差异被关在边界内。好的边界设计不是消灭差异，而是让差异只在一个地方出现。
- **异步生成器必须缓冲，是协议约束不是实现偷懒**：OpenAI 的 tool 消息要求 content 是字符串，模型不可能消费一个活的 `AsyncGenerator`。**所以“缓冲后序列化”是当前协议下的必然**；真正的端到端流式需要模型协议本身支持工具流式结果。
- **错误字符串化让 Agent 能自愈**：工具失败不抛给主循环，而是变成模型可读的 tool 消息，模型可以改参数重试。代价是“真失败”和“返回错误文本”在语义上被抹平，需要靠 trace/错误码补回可观测性。

### 3.8 自检问题

- 如果一个工具既想支持流式输出，又希望结果能被模型当作一次工具结果消费，应该选同步生成器还是异步生成器？
- `_registration_counts` 为什么不能简单地用 `function_mappings` 的长度代替？
- `dispatch()` 内普通同步工具阻塞的到底是哪个线程？取决于谁在调用 `dispatch()`？

---

## 4. 会话模块：事件溯源是状态总线 ✅

对应文件：[`LightAgent/session.py`](../LightAgent/session.py)。

一句话定位（导图原话的整理）：**session.py 整体只做一件事——把 Agent 的每一步记成不可变事件（`SessionEvent`），再从事件流投影出各种状态视图。** 事件的主要来源是 `runtime.py`，所以读 session 时最好同时看 runtime 的 `_append()`。

### 4.1 `SessionEvent`：一条不可变的“事实”

语义上它是 append-only 的事件记录，实现上不是 `frozen dataclass`（这点要分清）。关键字段：

| 字段 | 含义 | 备注 |
| --- | --- | --- |
| `type` | 事件类型 | 如 `run.started`、`tool.completed` |
| `session_id` | 所属会话 | 构造时强校验 |
| `data` | 业务数据 | 构造时经 `_json_safe()` 脱敏 |
| `event_id` | 事件唯一 ID | 默认 uuid |
| `sequence` | 会话内单调递增序号 | **从 1 开始**，`next_sequence` 基于最后一个事件 +1 |
| `turn_id` / `step_id` | 对话轮次/步骤 | `turn_id` 由 `_begin_session_run` 生成 |
| `run_id` / `agent_id` | 运行/代理归属 | 支持多 Agent |
| `parent_event_id` | 事件父子关系 | 为因果链预留 |
| `schema_version` | 事件版本 | 配合迁移注册表 |

`_json_safe()` 会把敏感 key（token、api_key、password 等）替换成 `[redacted]`，并对值做递归 JSON 化。**会话持久化前先脱敏**是这里的安全边界。

### 4.2 `Session` 的操作面

| 方法 | 作用 | 我的理解 |
| --- | --- | --- |
| `append(...)` | 构造并追加事件 | 自动分配 `sequence`，更新 `updated_at` |
| `append_event(event)` | 追加已构造事件 | 校验 `session_id`、`sequence` 连续、`event_id` 唯一 |
| `page(after, limit)` | 按序号分页读取 | 用于增量消费/外部读取 |
| `checkpoint(label)` | 记录检查点 | 只存“检查点事件”，不复制业务数据 |
| `fork(through_sequence)` | 从历史位置分叉 | 复制事件、生成新 ID、写入来源 lineage |
| `replay()` | 汇总各 turn 状态 | completed / incomplete / failed |
| `validate()` | 校验不变量 | 序号从 1 连续、event_id 唯一 |
| `to_dict()/from_dict()` | 序列化 | 配合 Store 和 `export_session()` |

`fork()` 的语义值得单独记：**复制的是投影所需的事件，不是“当前对象快照”**；每条复制事件都会带上 `source_session_id`、`source_event_id`、`source_sequence`，所以可以追溯分叉来源。

### 4.3 `SessionStore` 协议与三种实现

`SessionStore` 是 `typing.Protocol`，不是抽象基类。这意味着第三方后端**不需要继承**框架类，只要方法形状匹配即可（我在注释里专门写了这一点）。

| 实现 | 持久化 | 并发/安全 | 适合 |
| --- | --- | --- | --- |
| `InMemorySessionStore` | 进程内 dict | `RLock`；拒绝用更旧的事件序列覆盖 | 测试、短生命周期 |
| `JsonlSessionStore` | 每会话一个 `.jsonl` | 文件锁 + 临时文件 + `fsync` + `os.replace` 原子替换；拒绝不安全 session_id | 本地调试、人类可读 |
| `SqliteSessionStore` | SQLite 两张表 | WAL、事务、`RLock`、外键级联删除 | 需要可靠持久化 |

共同不变量：

1. `save()` 前先 `session.validate()`；
2. 不允许把事件序列“回退”（InMemory 显式拒绝旧序列）；
3. SQLite/JSONL 读取时重建 `Session` 会再次经过 `SessionEvent.from_dict()` 的校验；InMemory 存的是 `deepcopy`，不经过反序列化，但保存时会 `validate()`；
4. `Jsonl` 损坏/截断必须报错，而不是静默返回半个会话。

### 4.4 `ContextProjector`：从事件回投影

这是“事件溯源”真正发挥作用的地方：

- `messages(session, turn_id)`：优先从 `message.received` / `assistant.completed` / `model.completed` / `tool.completed` 重建消息；若无法重建，则回退到最近一次 `model.requested` 中保存的完整 `messages` 快照；
- `model_request(session, sequence)`：返回某次真实请求的完整消息快照；
- `trace(session, turn_id)`：从带 `trace_type` 的事件重建 trace 视图。

关键理解：**同一份事件流，可以投影出三种视图**——对话消息、模型请求原始参数、运行 trace。`model.requested` 里保存 `messages` 快照，是为了保证“即使后续投影规则变化，也能还原当时实际发给模型的内容”。

### 4.5 上下文预算与压缩

`ContextBudget`（依赖无关的字符估算，`chars_per_token=4.0`）：

```text
estimate = int(len(json.dumps(messages)) / chars_per_token) + 1
fits     = estimate <= max_tokens - reserved_output_tokens
```

`ContextCompactor` 的两条入口：

| 入口 | 触发 | 行为 |
| --- | --- | --- |
| `compact_session()`（core 公开 API） | 用户主动调用 | 固定 `max_messages` 裁剪，并写 `context.compacted` 事件 |
| `_compact_model_context()`（每次请求前） | 预算超限时自动 | `compact_to_budget()`：从当前消息数往下试，直到满足预算 |

裁剪规则（都写过注释）：

1. 先 `_spill_tool_results()`：超过 `max_inline_tool_chars` 的 `tool` 消息，内容替换为 `tool-result:sha256:<digest>` 引用，完整内容进入 `spilled`；
2. 保留第一条 `system` 消息；
3. 保留最近的 `keep_count` 条非 system 消息；
4. 如果留下的第一条是 `tool` 消息，继续往前弹出——因为 `tool` 消息依赖前面的 `assistant.tool_calls` 和 `tool_call_id`，脱离上下文会破坏协议；
5. 可选 `summarizer` 对被移除消息生成摘要，作为一条带 `metadata.compacted` 的 system 消息插入。

### 4.6 `core.py` ↔ `session.py` 的桥

`_record_session_event()` 负责“追加事件 + 保存会话”，并且**吞掉存储异常**：失败只写 `_session_store_error` 和日志，不中断主循环。理由是会话存储是旁路，不能因为磁盘问题让 Agent 崩溃。

`_record_trace()` 是更上层的映射器，把同一次运行事实同时投影到 trace 和 session：

| trace 事件 | session 事件 |
| --- | --- |
| `run_start` | `run.started` |
| `model_request` | `model.requested`（额外保存 messages 快照） |
| `model_response` | `assistant.completed` |
| `tool_call` | `tool.requested` |
| `tool_result` | `tool.completed` |
| `guardrail_block` / `hook_block` | `policy.blocked` |
| `error` | `error.recorded` |
| `run_end` | `run.completed` / `run.failed` |

未命中映射的事件统一落到 `trace.recorded`，并附带 `trace_type` / `trace_data`，所以 `ContextProjector.trace()` 才能还原 trace 视图。

**SessionEvent vs TraceEvent（思维导图里专门辨析过）**：两者都是“事件记录”，但定位不同——`Session` 是**产品功能**（持久化、恢复、审计、回放），`TraceRecorder` 更像**调试开关**（默认关闭，用于观测与导出）。`_record_trace()` 同时写两者，但生命周期和消费方不同：Session 事件要长期落盘，trace 可以随进程丢弃。理解这一点，才不会把 trace 当成“另一个 session”。

### 4.7 本章的坑

1. `SessionEvent` 虽被描述为 “immutable fact”，但类本身是可变的；真正的不可变性靠 append-only 使用约定和 `validate()` 保证。
2. `sequence` 从 1 开始，不是 0；`page(after=0)` 能拿到第一条。
3. JSONL 保存失败不能破坏旧文件：实现依赖临时文件 + `os.replace`；测试用 monkeypatch 注入 `os.replace` 失败来验证这一点。
4. SQLite 读取也必须重新跑 `SessionEvent.from_dict()`，否则损坏数据可能绕过校验。
5. 压缩不是“删旧消息”这么简单：`tool` 消息与 `assistant.tool_calls` 的配对关系必须保住。

### 4.8 设计智慧：事件溯源在 Agent 框架里的价值

- **把“状态”降级为“视图”**：Session 不存“当前消息列表”，只存“发生过什么”；消息、trace、runtime 状态都是投影。好处是同一份事实能**服务回放、审计、压缩、fork**；代价是投影要写对、存储会增长、读取要重算。
- ==**多维归属**==**让“切面”成为可能**：事件带 `turn_id/run_id/agent_id`，才能按轮次重放、按运行过滤、按 Agent 汇总。如果只有 `session_id`，多 Agent 与多轮调试会非常痛苦。
- **`Protocol` 换实现，而不是换基类**：InMemory/JSONL/SQLite 三种 Store 共存，第三方也能接。代价是运行期没有强制接口校验，需要测试和类型检查兜底。
- **原子写 + 拒绝旧序列 = 把“部分成功”变成“全有或全无”**：会话最怕半截状态；临时文件 + `os.replace`、以及旧序列保护，都是在存储层守住一致性。
- **快照回退是“规则演化”的审计锚点**：`ContextProjector` 会随版本改变投影逻辑，而 `model.requested` 保存的是当时真实发出的 messages。规则可以变，历史事实不能变。
- **压缩时协议完整性优先于压缩率**：宁可多留几条消息，也不能让 `tool` 消息失去配对的 `tool_call_id`。`spill` 用 SHA-256 引用保留可追溯性，是“删内容但留线索”的折中。

### 4.9 自检问题

- 为什么 `Session.fork()` 要为新事件生成新 `event_id`，而不能直接复用原事件？
- `ContextProjector.messages()` 有了“事件重建”路径，为什么还需要 `model.requested` 快照回退？
- `_compact_model_context()` 在 Hook 之前执行，这会带来什么可观测性影响？

---

## 5. Runtime 模块：会话之上的长期状态 ✅

对应文件：[`LightAgent/runtime.py`](../LightAgent/runtime.py)；对应文档：[`docs/runtime_v010.md`](../docs/runtime_v010.md)。

### 5.1 `AgentRuntime` 的组成

思维导图里对 Runtime 的定位很准确：**它把 Agent 从“一次性的模型调用函数”提升为“可以长期运行、暂停、恢复、审计和治理的任务执行单元”**。这句话是整个模块的设计目的，比“runtime.py 有哪些类”更重要。

```text
AgentRuntime
├── session_store      # SessionStore
├── registry           # CapabilityRegistry
├── session            # 当前活动 Session
├── context            # RuntimeContext（runtime/session/agent/turn/run）
├── inbox              # AgentInbox：有序、幂等消息
├── goals              # GoalManager：PENDING/ACTIVE/COMPLETED/BLOCKED/CANCELLED
├── budget             # BudgetManager：五维预算
├── jobs               # JobManager：后台协程 + lease + fencing
├── subagents          # SubagentManager：权限只收紧
├── progress           # ProgressTracker：停滞检测
└── _append()          # 所有子管理器的事件 → Session
```

关键设计：**所有子管理器的状态变化都通过 `_append()` 写成 Session 事件**。所以“恢复会话”不是恢复一堆内存对象，而是**从事件流重建 Inbox/Goal/Budget/Job。**

导图里还有一个很关键的辨析：**状态 vs 事实**。runtime 属性（inbox/goals/budget/jobs/...）是“状态/结果”，Session 事件是“事实/历史”；状态由事实重放得到。记住这个区分，就能理解为什么 runtime 的每个方法最后都要落到一条事件上。

### 5.2 `open_session()` 的恢复语义

`open_session()` 做四件事：

1. 有 `session_id` 则从 store 读，否则新建并写 `session.started`；
2. 绑定 `security_context`（v0.11）：校验其 `session_id` 与当前会话一致后，转换成 `RuntimeContext`；
3. 依次 `restore` Inbox、Goals、Budget、Jobs；
4. `jobs.mark_interrupted()`：上次运行中仍在 PENDING/RUNNING 的 Job 标记为 `interrupted`。

最后一步很关键：**恢复会话不等于恢复后台任务**；**框架选择保守地中断**，而不是假装任务还在跑。

### 5.3 `AgentInbox`：有序 + 幂等

- `enqueue(message_type, content, message_id=...)`：如果 `message_id` 已存在，直接返回旧消息，不重复入队；
- 状态机：`PENDING → CLAIMED → COMPLETED / REJECTED`；
- `claim_next(safe_boundary=True)`：`steering` 类型消息默认只在安全边界被领取；
- `restore(session)`：从 `inbox.*` 事件按 `message_id` 去重、按 `created_at` 排序重建。

这套设计对应的是“外部可以向正在运行的 Agent 投递消息，但不能破坏一次运行的原子性”。

### 5.4 Goal / Budget / Progress

- **Goal**：`create → activate → complete/block/cancel`，每次迁移都写事件，可恢复。
- **Budget**：五维 `model_calls / tool_calls / tokens / seconds / cost`。`consume()` 先算候选值，再逐维检查，**任一维超限就整次拒绝**，不会出现“部分扣减”；`remaining()` 只返回剩余量；`restore()` 取最后一条 `budget.consumed` 事件。
- **ProgressTracker**：记录输出/工具/参数，检测重复工具调用或停滞，写 `progress.stalled` 类事件，供外部中断或提示。

### 5.5 `JobManager`：后台任务的三道保险

| 机制 | 解决的问题 | 细节 |
| --- | --- | --- |
| `idempotency_key` | 重复提交 | 已存在则返回旧 `JobRecord`，不重复调度 |
| `CancellationToken` 子令牌 | 取消传播 | `parent.child()`，父取消可传播，子不能反向控制父 |
| `lease_seconds` + `fencing epoch` | 迟到 worker | 租约过期后结果不发布，Job 变 `interrupted`；`resume()` 递增 epoch，`renew_lease(expected_epoch=...)` 拒绝旧 epoch |

`_execute()` 的关键检查点：开始前查 token、查 lease；结果发布前再查一次 token 和 lease。即使任务跑完了，只要租约已过期，结果也不会被写入。

`finally` 里还会向 Inbox 投递 `job_completion` 消息，这是“后台任务完成 → 主循环可感知”的桥。

### 5.6 `SubagentManager`

- 注册子 Agent 时有数量/深度限制；
- 子 Agent 拿到的是**只能收紧的权限快照**（`PermissionSet.narrow()`；`PermissionSet` 的细节属于第 7 节待学，这里只记结论方向）；
- `tree()` 可查看层级；
- `cancel()` 可批量取消后代；
- 父取消通过协作式 token 传播。

### 5.7 本章的坑

1. Job 的 `start()` 需要正在运行的事件循环（`asyncio.get_running_loop()`），在纯同步上下文里不能直接起 Job。
2. fencing epoch 只能保护“运行时状态不被迟到 worker 覆盖”，**不能回滚已经发生的外部副作用**（这是 docs 里的原话，也是设计边界）。
3. `BudgetManager.restore()` 只回放最后一条 usage 快照，不重放每一次扣减；所以事件设计必须是“消费后写全量使用量”，而不是“增量记账”。
4. `_append()` 要求已经 `open_session()`，否则抛 `RuntimeError`；runtime 的所有子管理器都依赖这个前提。

### 5.8 设计智慧：Runtime 为什么是“状态机集合”

- **Runtime 不拥有真相，Session 才是**：Inbox/Goal/Budget/Job 都是内存视图，事件流才是可恢复的事实来源。这样重启、fork、审计都自然成立；代价是每个状态变化都必须记得写事件。
- **保守恢复 = 不假装任务还活着**：把上次未完成的 Job 标记 `interrupted`，而不是自动续跑。自动续跑可能重复外部副作用；让用户显式 `resume()` 是更安全的默认值。
- **Inbox 的幂等 + 安全边界**：外部 steering 可以进入运行，但不能在任意时刻打断原子步骤；`message_id` 幂等让“重试投递”不会产生重复指令。
- **预算先算候选再提交**：任何一维超限就整次拒绝，避免“扣了一半”的脏账本。这是财务系统里常见的“事务性预算”思想。
- **lease + fencing 是对抗“迟到 worker”的逻辑时钟**：epoch 递增让旧 worker 的结果失效。它的边界也很诚实——只能保护运行时状态，不能回滚已经发生的外部副作用。
- **子 Agent 权限只收紧**：父权限是上限，`narrow()` 拒绝扩权。组合式系统里，“可组合”必须建立在“不可提权”之上。
- **ProgressTracker 把“循环卡死”变成可观测事件**：Agent 最危险的失败之一是原地打转；把重复工具/无变化输出显式记录，才能被外部策略中断。

### 5.9 自检问题

- 恢复 Session 时，为什么 Job 被标记 `interrupted` 而不是继续执行？
- 如果 `consume(tokens=...)` 超限，`usage` 是否已经被改变？为什么这样设计？
- Inbox 的 `message_id` 幂等与 Job 的 `idempotency_key` 幂等，解决的是同一层问题吗？

---

## 6. 记忆模块：读写、过滤、晋升 ✅

对应文件：[`LightAgent/protocol.py`](../LightAgent/protocol.py)（契约与策略）、[`LightAgent/core.py`](../LightAgent/core.py)（流程编排）、[`LightAgent/shared_memory.py`](../LightAgent/shared_memory.py)（内置后端）。

先记住导图里的一组定位：**Session 是会话级短期记忆**（按 `session_id` 存/恢复），**Memory 是用户级长期记忆**（按 `user_id` 存/检索）。两者都叫“记忆”，但生命周期、隔离维度和存储后端完全不同。

### 6.1 六个对象先分清

| 对象 | 角色 | 一句话 |
| --- | --- | --- |
| `MemoryProtocol` | 后端接口 | `store(data, user_id)` / `retrieve(query, user_id)` |
| `MemoryScope` | 记忆标签 | 来源 source + 作用域 scope + agent + trace + 置信度 + 信任等级 |
| `MemoryAdmissionDecision` | 写入决策 | 是否允许写入、最终写入值、拒绝原因 |
| `MemoryCandidate` | 候选记忆 | 默认 **non-injectable**，等待晋升 |
| `MemoryPolicy` | 安全策略 | 决定“哪些能读、哪些能写、哪些能晋升” |
| `MemoryPromotionDecision` | 晋升决策 | `approve / reject / rewrite / keep` |

最容易混的是 **source 与 scope**：

- `source`：这条记忆**从哪来**（`user` / `reflection` / `delegation` / `tool`）；
- `scope`：这条记忆**给谁用**（`user` / `agent` / `shared` / `internal`）。

### 6.2 读路径

```text
_add_memory_context(query, user_id)
  ├─ memory_user_id = policy.scoped_user_id(user_id)      # namespace 隔离
  ├─ _retrieve_memory_with_hooks(source="user", scope="user")
  │    ├─ before_memory_retrieve hook（可 block / 改 query / 改 user）
  │    ├─ memory.retrieve(query, user_id)
  │    ├─ after_memory_retrieve hook（可 block / 改 memories）
  │    └─ _filter_memory_results → policy.allows_result() 逐条过滤
  ├─ 把命中的记忆拼成 "##用户偏好 ..."
  ├─ _store_memory_with_policy(data=query, source="user", scope="user")
  └─ if self_learning:
       同理检索/写入 agent scope、source="reflection"
       → 拼成 "##问题相关补充信息 ..."
```

重要边界：**检索结果先过 `MemoryPolicy`，再进入 prompt**。过滤发生在 hook 之后，所以 hook 不能绕过策略，只能进一步改写或阻断。

### 6.3 写路径

```text
_store_memory_with_policy(data, memory_user_id, original_user_id, source, scope)
  ├─ memory is None → False
  ├─ before_memory_write hook（可 block / 改 data）
  ├─ memory_policy.allows_write(data, context, write_count, recent_fingerprints)
  │    ├─ 写入次数上限
  │    ├─ 最小长度 / 拒绝正则
  │    ├─ 重复指纹（scope-aware）
  │    └─ memory_write_admission 回调（可 allow/deny/改写）
  ├─ 组装 MemoryScope(...).to_metadata()
  ├─ if _requires_memory_promotion(source, scope):
  │       → _handle_memory_promotion_candidate(...)   # 走第 6.4 节
  └─ else:
        _store_memory_record()  # 真正调用后端 store
        after_memory_write hook
        更新 _memory_write_count / _memory_write_fingerprints
        记录 memory_write trace
```

注意：`allows_write()` 返回的 `decision.value` 可以**改写要写入的文本**（清洗），所以“策略”不仅是 allow/deny，也是内容变换。

### 6.4 晋升路径

`_requires_memory_promotion(source, scope)` 只是初筛：当 `require_promotion_for_internal_memory=True` 且 source/scope 落在内部记忆集合里时，才返回 True。具体集合（源码里写死的）是：

- `internal_sources = {reflection, delegation, self_learning, agent, derived, swarm, trace, tool}`
- `internal_scopes = {agent, delegation, shared, internal, swarm, flow}`

只要 `source` 命中前者**或** `scope` 命中后者，这条记忆就会被当作“内部记忆”，进入显式晋升流程。真正逻辑在 `_handle_memory_promotion_candidate()`：

```text
构造 MemoryCandidate(status="candidate", injectable=False)
  → 记录 memory_promotion_required trace
  → before_memory_promote hook（可 block / 改 candidate）
  → memory_policy.allows_promotion(candidate, context)
  → _apply_memory_promotion_decision(decision)
       ├─ reject/keep：更新 status，injectable=False，upsert 候选
       └─ approve/rewrite：
             metadata 更新 promotion_status="promoted"
             injectable=True
             _store_memory_record(...)
             upsert 候选
             after_memory_write hook（晋升后的写入生命周期）
```

这里我写过一句强调：**只要被 promoted，就标记 `injectable=True`**。这是“内部记忆（如反思）默认不可注入，必须显式审核后才能进入 prompt”的核心开关。

### 6.5 过滤：`MemoryPolicy.allows_result()`

对每条检索结果依次检查（任何一步失败即拒绝）：

1. 是否 dict（不是则按 `allow_unattributed_results` 放行/拒绝）；
2. 是否被明确标记不可注入（`injectable=false`）；
3. 是否处于 `candidate/kept/rejected/blocked` 等未完成状态；
4. 用户归属是否匹配（`original_user_id` 或 `scoped_user_id`）；
5. source / scope / agent_name / trust_level 是否在允许白名单；
6. confidence 是否 ≥ `min_confidence`；
7. 是否过期（`enforce_expires_at`）。

字段读取用 `_get_value()`：先读顶层，再读 `metadata`，并对 `source/memory_source`、`confidence/score/trust_score`、`expires_at/expiresAt` 等同义字段做兼容。这是为了适配不同记忆后端的返回结构。

### 6.6 后端与适配器边界

- `SharedMemoryPool`：**轻量内存原型**，按 user 分区、按 token 重叠排序、保留 provenance；不是生产级持久化后端。我在类注释里专门补了这一点。
- 外部后端（mem0、ClawMem、Memcode、vector memory）：只要实现 `store` / `retrieve`，就能接入；`MemoryPolicy` 在框架侧做统一过滤，不依赖后端配合。
- `MemoryProviderAdapter`：把记忆能力注册进 `CapabilityRegistry`，让记忆也能走统一的 Policy/audit 管线（Policy 细节属于第 7 节待学内容）。

### 6.7 本章的坑

1. `MemoryPolicy` 不负责存储/检索，只负责准入与过滤；不要把它当成“记忆后端”。
2. `namespace` 只影响 `scoped_user_id`，不会自动改写后端里的历史数据；切换 namespace 等于换一套隔离空间。
3. 写入指纹是 scope-aware 的：同一文本在不同用户/来源/作用域下不算重复。
4. 晋升失败（reject/keep）不是异常，而是正常决策结果；候选仍会 `upsert` 保留，供后续查询/人工晋升。
5. `allows_write()` 和 `allows_promotion()` 的“失败关闭”语义不同：写入回调异常 → 拒绝写入；晋升回调异常 → 返回 `keep`（保留候选但不可注入）。

### 6.8 设计智慧：记忆模块的安全观

- **存储与治理分离**：后端只负责 `store/retrieve`，是否允许读、写、晋升由框架的 `MemoryPolicy` 统一决定。这样换后端不换安全语义，安全策略也不会散落在各适配器里。
- **默认不可注入，是一种“反自我污染”设计**：模型自己反思出来的记忆**默认是 `non-injectable candidate`**。如果直接回灌 prompt，模型会不断强化自己的偏见和幻觉；显式晋升（approve/rewrite）才把“候选证据”升级为“可信上下文”。
- **source 与 scope 正交**：来源回答“谁说的”，作用域回答“给谁用”。两者分开后，才能表达“这是反思产生的、只给这个 Agent 用”的记忆。
- **namespace 是逻辑隔离，不是物理隔离**：`scoped_user_id` 在框架侧加前缀，让同一个后端能服务多租户；但它不加密、不鉴权，真正的隔离仍要靠后端或部署。
- **过滤必须在进入 prompt 之前**：Hook 可以改写/阻断检索结果，但最终仍要过 `allows_result()`。这是“可扩展性不能削弱安全底线”的体现。
- **失败关闭 + 保守决策**：写入回调异常就拒绝写入，晋升回调异常就 `keep`（保留候选但不可注入）。宁可少记一条，也不让不可信内容进入上下文。
- **指纹去重是 scope-aware 的**：同一句话在不同用户/来源/作用域下是不同记忆。去重不能跨语义空间做，否则会误删合法记忆。

### 6.9 自检问题

- 为什么反思记忆默认是 `non-injectable candidate`，而不是直接写进用户记忆？
- 读路径里，为什么 `allows_result()` 要在 `after_memory_retrieve` hook 之后执行？
- 如果第三方记忆后端返回的字段名与框架约定不同，框架在哪一层做兼容？

> 延伸阅读（已读，2026-10-24）：[`memory_admission.md`](../docs/memory_admission.md)、[`memory_trace_swarm_boundaries.md`](../docs/memory_trace_swarm_boundaries.md)、[`memory_security.md`](../docs/memory_security.md)。读后记见 8.3：三篇主要是对源码阶段理解的确认，不是新增机制。

---

## 7. 能力与策略：尚未系统学习（只有框架级印象）○

对应文件：[`LightAgent/capabilities.py`](../LightAgent/capabilities.py)；**证据状态：○ 待学，不是已掌握**。

我还没有认真学过这一节。判断依据：

- 工作区 `capabilities.py` 只有 20 行新增、约 6 行注释，基本停留在“名词级”；
- 思维导图里 Capability / Policy 只作为 runtime 分支下的两句话，没有展开；
- 自己回顾时也确认：能说出“这层大概干嘛”，但说不清具体机制。

所以本节不写“机制详解”，只记三件事：我现在知道什么、我还没学什么、下次怎么学。

### 7.1 我现在知道的（只到定位）

- **两句话定位**：Capability 描述“能做什么”，Policy 决定“现在允不允许做”。
- 能力由 Provider 提供；导图里列了 Tool / Memory / MCP / Workflow 等 Provider。
- 一次能力调用大致要经过 `PolicyEngine.evaluate()`；在 `run()` 的工具路径里能看到 `_prepare_tool_call()` 调用 `policy_engine.evaluate_sync()`，并把结果写成 `policy.decision` 事件。
- 有作用域概念（default / runtime / session / agent），但具体优先级与冲突规则我还没验证。
- ⚠️ 以上只是“知道名字 + 知道调用点”，不等于掌握实现；本节其余内容一律留白。

### 7.2 我还没学的（下次的清单）

- `CapabilitySpec` 的字段语义与风险分级；
- `CapabilityRegistry` 的 scope 优先级、同 scope 冲突与 `conflicts()`；
- `PermissionSet.allows()` / `narrow()` 的“只收紧”规则；
- `PolicyEngine` 的有序执行、fail-closed、参数改写与异常处理；
- `invoke()` 的 `resolve → policy → audit → provider → timeout/output_limit` 全链路；
- Provider 适配器（Tool / Memory / Skill / MCP / Workflow）如何把旧 API 接进注册表；
- `security.py` 的 `SecurityContext`、`CapabilityGate`、`ApprovalToken`（v0.11）。

### 7.3 为什么值得学（当前只是假设，未验证）

- Agent 框架的“治理层”通常就在这里：模型不可信，能力要有风险标签、权限快照、审批和审计。
- 组合系统里，“子只能收紧不能扩权”是最小权限原则的落地方式。
- 这层和已接触的 `runtime`、`memory policy`、`hooks` 相接（`guardrails` 只用过调用点、没看内部实现），是理解“策略如何串起来”的关键缺口。

> 注意：上面是学习动机和假设，不是我已经验证过的结论。正式学的时候以源码和 `test_v010_capabilities.py` / `test_v011_security.py` 为准。

### 7.4 下次学习路线（按调用链，不按类名）

1. 从 `core._prepare_tool_call()` 的调用点进入，跟到 `capabilities.PolicyEngine.evaluate_sync()`；
2. 看 `PolicyRequest` / `PolicyDecision` → `PermissionSet`，理解“允许 / 拒绝 / 需审批”；
3. 看 `CapabilitySpec` / `CapabilityRegistry.resolve()`，理解 scope 与冲突；
4. 看 `invoke()` 全链路和 `audit`；
5. 最后补 `security.py` 的 `SecurityContext` / `CapabilityGate` / `ApprovalToken`；
6. 对照 `test_v010_capabilities.py`（10 个测试）与 `test_v011_security.py`（7 个测试）验证理解。

### 7.5 学习前的问题（不是掌握检验）

- 为什么能力需要“风险等级”，而不是只有“允许 / 禁止”？
- 同 scope 冲突为什么选择“最新注册获胜”，代价是什么？
- 为什么 `PermissionSet` 要设计成只能收紧？谁在使用这个约束？
- `PolicyEngine` 为什么要 fail-closed？哪些异常会被吞掉？
- `security.py` 的 `ApprovalToken` 和 `PolicyDecision.approval` 是什么关系？

---

## 8. `docs/` 足迹：文档是代码的“外部说明”

### 8.1 我实际注释过的文档：`docs/runtime_v010.md`

只有这一份文档被我直接加了注释，但信息量很集中（另外三篇记忆文档已读但未加注释，见 8.3）：

| 注释点 | 学到的内容 |
| --- | --- |
| `acceptance_criteria` | Goal 的验收标准是持久化字段 |
| `goals.activate()` | 状态迁移 `PENDING → ACTIVE` |
| `inbox.enqueue()` | 投递 steering 消息带 `message_id`，幂等 |
| `runtime.pause()` | 暂停会追加 `session.paused` 事件 |
| Runtime 段落 | 有序幂等 Inbox、Goal、五维预算、进度检测、Job、子 Agent 权限收紧 |
| fencing epoch | 可理解为版本号；`interrupted` Job 恢复时 epoch 递增 |
| MCP 段落 | stdio/SSE 兼容 + Streamable HTTP、重连、工具刷新、命名空间隔离、凭据 Header |

### 8.2 docs 地图（按与已学模块的相关度）

| 文档 | 对应模块 | 我的状态 |
| --- | --- | --- |
| [`runtime_v010.md`](../docs/runtime_v010.md) | session / runtime | ✅ 注解过；其中 Capabilities 段落我没深入 |
| [`tools.md`](../docs/tools.md) | tools / 生成器 / 注册 | 🧭 与 notes/02 对照读过 |
| [`memory_admission.md`](../docs/memory_admission.md) | MemoryPolicy 写入准入 | ✅ 已读（第 1 篇，2026-10-24） |
| [`memory_trace_swarm_boundaries.md`](../docs/memory_trace_swarm_boundaries.md) | memory / trace / swarm 边界 | ✅ 已读（第 2 篇，2026-10-24） |
| [`memory_security.md`](../docs/memory_security.md) | 记忆安全边界 | ✅ 已读（第 3 篇，2026-10-24） |
| [`memcode_memory_adapter.md`](../docs/memcode_memory_adapter.md) | 记忆适配器示例 | ○ 未读；**暂缓**，等要写适配器时再看 |
| [`tracing.md`](../docs/tracing.md) | TraceRecorder / 导出 | 🧭 读过但未深入 |
| [`runtime_hooks.md`](../docs/runtime_hooks.md) | Hook 生命周期 | 🧭 读过 |
| [`runtime_hook_recipes.md`](../docs/runtime_hook_recipes.md) | Hook 实战配方 | 🧭 读过 |
| [`public_api_compatibility.md`](../docs/public_api_compatibility.md) | 兼容边界 | 🧭 读过 |
| [`error_handling.md`](../docs/error_handling.md) | 错误码与异常 | 🧭 读过 |
| [`FAQ.md`](../docs/FAQ.md) | 常见问题 | ○ 未系统读 |
| [`lightflow.md`](../docs/lightflow.md) / [`lightdag.md`](../docs/lightdag.md) | 工作流/DAG | ○ 未展开 |
| [`connectors.md`](../docs/connectors.md) | 连接器 | ○ 未展开 |
| [`guardrails.md`](../docs/guardrails.md) | Guardrail | 🧭 用过但未读实现 |
| [`human_review.md`](../docs/human_review.md) | 人工审批 | ○ 未展开 |
| [`evaluation.md`](../docs/evaluation.md) | 评测 | ○ 未展开 |
| [`model_providers.md`](../docs/model_providers.md) | 模型接入 | 🧭 用过 DeepSeek/OpenRouter |
| [`shared_memory_pool.md`](../docs/shared_memory_pool.md) | 共享记忆池 | 🧭 与 `shared_memory.py` 对照 |
| [`vector_memory_adapter.md`](../docs/vector_memory_adapter.md) 等三个 adapter 文档 | 记忆适配器 | ○ 未展开 |
| [`python_executor_security.md`](../docs/python_executor_security.md) | 执行器沙箱 | 🧭 从测试反推 |
| [`security_shared_graph_memory_validation.md`](../docs/security_shared_graph_memory_validation.md) | 图记忆安全 | ○ 未展开 |
| [`multi_agent_failure_map.md`](../docs/multi_agent_failure_map.md) | 多 Agent 故障图谱 | ○ 未展开 |
| [`browser_use.md`](../docs/browser_use.md) | 浏览器工具 | ○ 未展开 |
| [`lightdag_v011_development_plan.zh-CN.md`](../docs/lightdag_v011_development_plan.zh-CN.md) | v0.11 设计 | ○ 未展开 |

> 复习建议：docs 不要按字母顺序读。先读与当前代码路径对应的文档（runtime_v010 → tools → memory_admission → memory_security），再读边界类（public_api_compatibility、error_handling），最后读扩展类（flow/dag/connectors）。

### 8.3 记忆四篇文档：阅读状态与读后记

**2026-10-24 已读完前三篇**（`memory_admission`、`memory_trace_swarm_boundaries`、`memory_security`）；`memcode` 仍未读，继续暂缓。

读后自评：这三篇基本是“确认”，而不是“新学”——能懂的部分大多在读源码时已经体会过；文档的主要价值是把散落在 `MemoryPolicy`、`MemoryScope`、`core` 里的点组织成规则，并补上默认行为和边界说明。没有出现需要推翻已有理解、重画架构的内容。

| 顺序 | 文档 | 状态（2026-10-24） | 读后回看：确认/补强了什么 | 读法 |
| ---: | --- | --- | --- | --- |
| 1 | [`memory_admission.md`](../docs/memory_admission.md) | ✅ 已读 | 写入闸门的完整顺序：基础质量检查（长度/正则/次数/重复指纹）先于 `memory_write_admission`；callback 的返回值如何被归一化；`require_write_admission=True` 时缺失回调、返回 `None`、抛异常都失败关闭；写次数、重复指纹、晋升、trace 事件 | 对照 `core._store_memory_with_policy`、`protocol.allows_write` / `_coerce_write_decision` 与 `test_memory_policy.py` |
| 2 | [`memory_trace_swarm_boundaries.md`](../docs/memory_trace_swarm_boundaries.md) | ✅ 已读（重点前三节） | trace / user memory / reflection memory / swarm state 的寿命与存储边界；`MemoryScope` 字段约定；过滤缺字段即拒绝；trace hierarchy（`parent_trace_id` / `run_group_id`）；“不要把 trace 摘要当用户记忆” | 对照第 4.6 节（Session vs Trace）与第 6 节；LightSwarm 段只取“委派结果是候选证据”的原则 |
| 3 | [`memory_security.md`](../docs/memory_security.md) | ✅ 已读 | 记忆投毒威胁模型；namespace/tenant 隔离；provenance 与 trust；写入 admission + 读取过滤的双重防线；**框架策略不能替代后端/适配器安全**的责任边界 | 先有 1、2 的基础；Mem0 Graph 段只读原则，adversarial matrix 先跳过 |
| 4 | [`memcode_memory_adapter.md`](../docs/memcode_memory_adapter.md) | ○ 未读，暂缓 | 写第三方适配器时才需要：provenance 保留、fail-before-provider、不 fallback、异步 ingest 与删除边界 | 等要写适配器或比较 mem0/Memcode 边界时再读 |

一句话结论：**前三篇读完后，第 6 节的“读 / 写 / 过滤 / 晋升”四条路径都能对应到文档章节，理解从“源码点状记忆”变成了“有边界的流程”；`memcode` 仍属于适配器层，暂不影响记忆架构主线。**

> 版本提示：`memory_admission.md` 提到 v0.8.2 / v0.9.5 的默认行为，`memory_security.md` 提到 Mem0 Graph。当前代码是 v0.11.0，读的时候以源码和测试为准；文档里的“默认行为”语义基本仍成立。

---

## 9. `tests/` 足迹：用测试反推设计

### 9.1 我注释过的两个测试文件

**`tests/test_v065_core.py`**：核心价值是“如何在不发真实请求的情况下测 `run()`”：

- `StaticCompletions` / `ToolCallCompletions` 等假客户端，形态是 `SimpleNamespace(choices=[...])`，只实现 `run()` 需要的字段；
- `attach_client(agent, completions)` 把 `agent.client` 替换成假客户端，因为 `run()` 只依赖 `client.chat.completions.create` 这一条接口；
- 每个测试显式分 `Arrange / Act / Assert` 三段，便于确认“我到底在验证哪个行为”。

这让我理解了一个设计事实：**`run()` 对模型客户端的依赖面很窄**，所以测试可以极轻量地注入假对象，不必 mock 整个 OpenAI SDK。

**`tests/test_v010_session.py`**：核心价值是“如何测持久化的失败路径”：

- `test_jsonl_store_rejects_truncated_event`：截断 JSONL，验证读取时报错；
- `test_jsonl_atomic_save_failure_preserves_previous_session`：monkeypatch `session_module.os.replace` 抛 `OSError`，验证旧会话没有被破坏；
- `test_in_memory_store_rejects_stale_session_save`：旧序列不能覆盖新序列；
- `test_compaction_spills_large_tool_results_and_meets_budget`：压缩与预算联动。

这组测试直接对应第 4 节的存储不变式，是复习会话模块时最好的“可执行文档”。

### 9.2 测试套件地图（按模块归类，便于按需跑）

| 主题 | 代表文件 | 主要验证 |
| --- | --- | --- |
| 核心 run / 格式 | `test_v065_core.py` | 返回格式、流式、工具循环、参数校验 |
| run + session 集成 | `test_v010_core_integration.py` | turn 平衡、模型请求快照、astream 关闭、compact |
| session | `test_v010_session.py` | 三 Store、fork、replay、损坏检测、压缩 |
| runtime | `test_v010_runtime.py`、`test_v011_runtime.py` | Inbox/Goal/Budget/Job/Subagent、lease/fencing |
| capabilities | `test_v010_capabilities.py` | scope 优先级、Permission、Policy、timeout |
| memory | `test_memory_policy.py`（31 个）、`test_shared_memory_pool.py` | 过滤、准入、晋升、hook 生命周期 |
| tools | `test_tool_schema_validation.py`、`test_asyncgen_tool_dispatch.py` | 注册诊断、生成器工具消费 |
| hooks/guardrails | `test_v070_tracing.py`、`test_policy_hooks.py`、`test_guardrails.py` | Hook 生命周期、失败关闭、改写 |
| tracing | `test_v070_tracing.py`、`test_v096_tracing.py` | trace 事件、usage、导出 |
| security | `test_v0101_security.py`、`test_v011_security.py` | 遗留执行器拦截、SecurityContext、ApprovalToken |
| 其他扩展 | `test_lightflow.py`、`test_lightdag.py`、`test_connectors.py`、`test_mcp_client_manager.py` | 尚未深入学习 |

### 9.3 本地跑测试的两个环境坑

1. **临时目录权限**：若 pytest 报“无权访问系统临时目录”，加 `--basetemp .pytest-tmp`。
2. **`NO_PROXY` 里的 `[::1]`**：本机 `NO_PROXY=localhost,127.0.0.1,::1,[::1]` 会让 httpx 0.28 把 `[::1]` 当成带端口的 URL 解析，报 `InvalidURL: Invalid port: ':1]'`，导致大量 `LightAgent(...)` 初始化失败（109 failed / 262 passed）。这不是代码回归，是环境变量与 httpx 的兼容问题。

   处理方式二选一：

   ```powershell
   # 方式 A：移除带方括号的 IPv6 项
   Remove-Item Env:NO_PROXY -ErrorAction SilentlyContinue
   $env:NO_PROXY = 'localhost,127.0.0.1'
   
   # 方式 B：在测试 runner 内、import httpx 之前清空所有 proxy 变量
   ```

   清理后当前分支基线为 **371 passed / 1 skipped**。上游 v0.11.0 的基线是 **365 passed / 1 skipped**（skip 为 mem0 graph security opt-in 测试，需 `LIGHTAGENT_RUN_MEM0_GRAPH_SECURITY=1`），不是故障。两者差值来自当前学习分支额外保留的测试。

### 9.4 用测试复习的方法

- 想确认某个行为“到底是不是这样”，优先找对应测试，而不是只看实现；
- 想理解失败路径，优先读带 `pytest.raises` 和 `monkeypatch` 的测试；
- 想练习写测试，从 `test_v065_core.py` 的 fake client 模式开始，成本最低。

---

## 10. `examples/` 与实机接入的足迹

> 这一节不属于三大目录，但它是“代码真的跑起来”的证据，复习时能补上只看源码得不到的体感。

### 10.1 DeepSeek 接入（01/02/06/14）

改造点很一致：

- `load_dotenv(Path(__file__).with_name(".env"))`，从同目录 `.env` 读 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `MODEL_NAME`；
- 模型、api_key、base_url 全部改为环境变量，避免把密钥写进代码；
- `example/02` 打开 `debug=True, log_level="debug"` 方便观察工具调用；
- `example/06` 用 `session_id` 显式续聊，并 `export_session()` 打印事件类型；
- `example/14` 演示流式消费：`chunk.choices[0].delta.content`，并且**先判断 `getattr(chunk, "choices", None)`**，因为流里可能混入非 chunk 的 yield。

### 10.2 mem0 接入的踩坑（`example/03.memory_mem0.py`）

这是我花时间最多、也最值得复习的“框架边界”案例：

| 坑 | 现象 | 解决 |
| --- | --- | --- |
| `MEM0_DIR` 设置时机 | 默认写 `~/.mem0`，跨项目互相污染 | 必须在 `import mem0` **之前**设 `os.environ["MEM0_DIR"]` |
| OpenRouter 隐式行为 | 只要环境里有 `OPENROUTER_API_KEY`，mem0 的 openai provider 会自动指向 OpenRouter | 显式配置 `openrouter_base_url`，并注意 free 模型与 embedding 共用额度 |
| Qdrant 连接 | 带 api_key 时可能被切成 TLS，或 401 | 用 `http://127.0.0.1:6333` 显式 URL；传 `api_key`；`on_disk=True` 省内存 |
| 维度类型 | 环境变量读出来是字符串 | `EMBED_DIMS = int(...)`，同时用于 embedder 和 vector_store |
| mem0 版本差异 | 2.x 不再接受顶层 `user_id` | `m.search(query, filters={"user_id": user_id})` |

更重要的收获不是这些配置细节，而是一个判断：**框架定义的 `MemoryProtocol` 只是最小接口，适配器内部的第三方库行为差异（版本、隐式 provider、配置字段）必须由适配器自己吸收**。这也是 `MemoryProtocol` 用 `Protocol` 而不是继承的原因——第三方实现可以是“薄包装”，也可以是“厚适配”。

---

## 11. 横向主题与设计智慧

1. **兼容优先的渐进式架构**
   `run()` 是同步核心，`arun()`/`astream()` 是适配层；不是“全异步重构”，而是“先保住旧 API，再逐步引入原生异步 Provider/Job”。理解这一点，很多“看起来别扭”的实现就顺了。

2. **事件溯源是统一状态总线**
   Session 不存“消息列表”，存“发生了什么”。消息、trace、runtime 状态、压缩结果、记忆候选都能从事件流投影出来。`_record_trace()` 是“同一事实写两个视角”的映射器。

3. **策略分层，逐层收窄（部分待学）**
   从已接触的 Guardrail / Hook 能看到“策略放在模型之外”的思路；Capability Policy / Permission / Approval 属于第 7 节的待学内容，先记住方向，机制等学完再补。

4. **协议化 + 适配器，避免继承耦合**
   `MemoryProtocol`、`SessionStore` 是我实际读过的 Protocol；`CapabilityProvider` 从命名看也是同类风格，但我还没系统学，暂不作为掌握证据。框架依赖“方法形状”而不是继承，代价是运行期缺少强制校验，需要测试兜底。

5. **确定性优先的预算与压缩**
   `BudgetManager` 先算候选再提交；`ContextBudget` 用字符估算而不是 tokenizer；`ContextCompactor` 用确定性规则裁剪并保留可追溯的 SHA-256 引用。这些设计牺牲精度，换取“无外部依赖 + 可复现”。

6. **生成器的消费边界决定流式价值**
   异步生成器只在“结果天然分段 + 调用链逐段消费”时才有实时收益；当前 `dispatch()` 是内部汇总，同步生成器才是透传。这个判断在 notes/02 里已经写透。

7. **三视角可观测性同源**
   同一次运行事实，可以从三个视角看：`TraceRecorder`（运行内 trace）、`Session`（持久化事件）、`CapabilityRegistry` 的 audit（安全审计，属于第 7 节待学内容）。前两者我实际用过；audit 只从命名和文档知道存在，尚未验证。

8. **学习方法的收获**（这一条不是代码结论，但同样重要）
   - **注释驱动**：只在真正读懂的位置写中文注释，注释就是“理解锚点”；回看 diff 比回看整份源码高效得多。
   - **图文双视图**：架构图负责“空间定位”，笔记负责“因果/时序解释”，两者互补。
   - **测试反推**：用测试理解失败路径与边界条件，尤其是 `pytest.raises` 和 `monkeypatch` 场景。
   - **实机踩坑**：只有把 DeepSeek、mem0、Qdrant 真正接起来，才会遇到“文档没写、代码也没写”的版本/环境问题，这些是框架适配器存在的原因。

### 11.1 设计智慧总览：一个 Agent 框架真正难的地方

把前面各节的设计取舍再抽一层，我认为 LightAgent 体现出的“框架设计智慧”主要是这十条（其中涉及能力/策略层的几条来自调用点与文档，尚未系统验证，等第 7 节学完再回来修订）：

1. **框架的核心不是“调模型”，而是“编排 + 状态 + 策略 + 扩展点”**。`run()` 只是入口，真正决定框架能不能长期用的是：状态如何持久化、权限如何收窄、第三方如何接入。
2. **真相与视图分离**：Session 事件是真相，内存对象、消息列表、trace 都是视图。凡是“视图化”的状态，就必须能从事件重建；凡是不能重建的，就不该成为关键状态。
3. **模型是不可信组件**：模型会幻觉、会重复、会调用危险工具。所以预算、策略、guardrail、审批、超时、输出截断都必须放在模型之外，而不是指望模型自觉。
4. **默认失败关闭（fail-closed）**：我在记忆写入、沙箱拦截、Hook / 策略调用点看到的默认值都是“拒绝 / 保守”；能力层审批异常的细节还没验证，但“默认拒绝”这个方向值得记住。安全系统的默认值比 happy path 更重要。
5. **兼容性是产品能力，不是妥协**：同步核心 + 异步外壳、旧 Stream 协议、旧 API 保留，都是为了不让已有用户为框架升级买单。代价要明说，但不能假装不存在。
6. **用确定性规则兜底不确定性**：预算用整数/浮点账本，压缩用字符估算和固定裁剪规则，晋升用显式决策，都是“可复现优先于最优”。Agent 系统里，可解释、可回放往往比“聪明”更重要。
7. **幂等与 fencing 是长任务的入场券**：只要允许重试、后台任务、分布式 worker，就必须回答“重复提交怎么办”“迟到的 worker 怎么办”。Inbox 的 `message_id`、Job 的 `idempotency_key` / lease epoch 就是答案。
8. **边界处做转换，核心保持简单**：`dispatch()` 吸收四类工具差异，Provider 适配器吸收第三方后端差异，`to_thread` 吸收同步/异步差异。核心主循环因此可以保持“读起来像普通同步代码”。
9. **可观测性要三视角同源**：trace 看“这一步做了什么”，session 看“持久化了什么”；audit 属于能力层，我还没学，只知道它存在。前两者共享同一批事实，排查时才能对得上账。
10. **诚实标注“不能做什么”**：fencing 不能回滚外部副作用；异步生成器不等于端到端流式；压缩会损失信息。能力层的 `PermissionSet` 边界我还没系统验证，因此不把“它只保护什么”写成结论——**没学的地方就留白，也是这份总结的一部分**。

再往深一层想，Agent 框架和普通后端框架最大的不同是：**它把“不确定性”放进了执行链**。模型输出不确定、工具行为不确定、任务长度不确定、外部副作用不确定。LightAgent 的很多设计——事件溯源、预算、幂等、fencing、晋升审核、失败关闭——本质上都是在给不确定性加“可恢复的边界”。理解了这一点，再去看具体模块，就不会只记住“有个类叫 X”，而能理解“它为什么必须存在”。

---

## 12. 坑清单：复习时优先看这些

| # | 现象/结论 | 根因 | 正确理解 | 位置 |
| --- | --- | --- | --- | --- |
| 1 | 流式 `run()` 的 yield 不全是字符串 | 模型 chunk + 工具调用信息 + 工具结果混流 | 消费时判类型、判 `choices` | `core._run_stream_logic` |
| 2 | 异步生成器工具结果变成 `<async_generator object>` | 旧逻辑对返回值直接 `str()` | dispatch 内部缓冲收集再序列化 | issue #107 / `tools.dispatch` |
| 3 | `arun()` 看起来“不阻塞”，但内部仍会等线程 | `to_thread` 只是不占用事件循环线程 | `future.result()` 类等待仍存在 | `core.arun/astream` |
| 4 | `run(stream=True)` 返回生成器，但创建时没执行 | 生成器惰性执行 | 真正开始于第一次 `next()`/迭代 | `core.run` |
| 5 | Session 保存失败却不让 Agent 崩 | `_record_session_event` 吞异常 | 存储是旁路，错误记入 `_session_store_error` | `core._record_session_event` |
| 6 | 压缩后 `tool` 消息和 `tool_call_id` 对不上 | 裁剪边界没有考虑协议配对 | 保留的 `tool` 开头消息继续前移 | `session.ContextCompactor.compact` |
| 7 | JSONL 会话文件被截断后仍能读 | 读取缺少完整性校验 | `JsonlSessionStore.get()` 校验 header/事件 | `session.py` |
| 8 | 同名工具 schema 被静默覆盖 | 注册表“最新获胜” | 用 `validate_tools()` 查诊断 | `tools.ToolRegistry` |
| 9 | Job 恢复后结果“突然”没发布 | lease 过期 / fencing epoch 失效 | 结果发布前二次检查 lease | `runtime.JobManager` |
| 10 | 反思记忆写入后检索不到 | 默认是 non-injectable candidate | 需要 promotion/approve 才 `injectable=True` | `core._handle_memory_promotion_candidate` |
| 11 | 记忆过滤“看起来配置了却不生效” | 字段名/大小写/嵌套位置不兼容 | `_get_value` 支持顶层与 metadata 同义字段 | `protocol.MemoryPolicy` |
| 12 | `NO_PROXY` 导致大量测试初始化失败 | `[::1]` 被 httpx 当 URL 解析 | 清理 `NO_PROXY` 中的方括号项 | 环境 |
| 13 | mem0 换项目后 schema 冲突 | `MEM0_DIR` 在 import 后才设置无效 | import 前设置 | `example/03` |

> 原本还有一条 `CapabilityRegistry` scope 的“坑”，但那属于我尚未系统验证的能力层，已从坑清单移除，改放到第 7 节待学清单。

---

## 13. 复习速查表：已学符号 → 文件 → 一句话

| 符号 | 位置 | 一句话 |
| --- | --- | --- |
| `run()` | `core.py` | 同步主入口，九阶段执行链 |
| `arun()` | `core.py` | 非流式 `to_thread(run)`；流式转 `astream` |
| `astream()` | `core.py` | 用 `to_thread(next)` 把同步生成器适配成异步迭代 |
| `run_async_safely()` | `core.py` | 同步调用异步协程；有 loop 时另起线程 + `asyncio.run` |
| `_core_run_logic()` | `core.py` | 按 `stream` 分流，不负责异步 |
| `_run_non_stream_logic()` | `core.py` | 工具循环，最多 `max_retry` 轮 |
| `_run_stream_logic()` | `core.py` | 同步迭代模型流，累积 chunk 与 tool_calls |
| `_record_trace()` | `core.py` | trace 事件 → session 事件的映射器 |
| `_record_session_event()` | `core.py` | 追加事件 + 保存会话，异常旁路 |
| `_prepare_model_request()` | `core.py` | 压缩、Hook、预算、记录请求快照 |
| `_prepare_tool_call()` | `core.py` | 取消→Policy→预算→Guardrail→Hook（Policy 细节待学） |
| `_begin_session_run()` | `core.py` | 打开 runtime 会话并投影历史 |
| `ToolRegistry` | `tools.py` | 名称→函数/信息/schema 三容器 |
| `ToolLoader` | `tools.py` | 动态 import + 名称安全 + 缓存 |
| `AsyncToolDispatcher.dispatch()` | `tools.py` | 四类工具统一调度入口 |
| `SessionEvent` | `session.py` | append-only 事实，带 sequence/turn/run/agent |
| `Session` | `session.py` | append/checkpoint/fork/replay/validate |
| `SessionStore` | `session.py` | Protocol；InMemory/Jsonl/Sqlite 三实现 |
| `ContextProjector` | `session.py` | 事件流 → 消息/请求快照/trace |
| `ContextBudget` / `ContextCompactor` | `session.py` | 字符估算预算 + 确定性裁剪 + SHA-256 spill |
| `AgentRuntime` | `runtime.py` | session + registry + inbox/goal/budget/job/subagent |
| `AgentInbox` | `runtime.py` | 有序幂等消息，steering 安全边界 |
| `BudgetManager` | `runtime.py` | 五维预算，候选验证后提交 |
| `JobManager` | `runtime.py` | idempotency + cancellation child + lease/fencing |
| `MemoryProtocol` | `protocol.py` | 最小记忆后端接口 |
| `MemoryScope` | `protocol.py` | source/scope/agent/trace/confidence 标签 |
| `MemoryCandidate` | `protocol.py` | 默认不可注入的候选记忆 |
| `MemoryPromotionDecision` | `protocol.py` | approve/reject/rewrite/keep |
| `MemoryAdmissionDecision` | `protocol.py` | 写入准入结果与改写值 |
| `MemoryPolicy` | `protocol.py` | 读过滤/写准入/晋升审核的规则集合 |

> 能力 / 策略相关符号（`CapabilitySpec`、`CapabilityRegistry`、`PermissionSet`、`PolicyEngine`）我**尚未系统学**，暂不放进速查表，避免制造“已掌握”的错觉；它们统一收在第 7 节的待学清单里。

---

## 14. 尚未展开与下一步

### 14.1 还没系统学的模块

- `capabilities.py`（Capability / Policy / Permission）与 `security.py`（SecurityContext / CapabilityGate / ApprovalToken）：**第 7 节明确未学**，目前只知道定位与调用点；
- `review.py`（人工审批）、`flow.py`（LightFlow 工作流编排）、`lightdag` 相关：只读过文档标题和测试名；
- `knowledge.py` / RAG、`mcp_client_manager.py`：知道入口，没跟完整链路；
- `connectors.py`、`skills.py`、`skill_tools.py`、`guardrails.py` 的实现细节；
- `tracing.py` 的 TraceRecorder / exporter；
- `evaluation.py`、`cancellation.py`、`errors.py` 的完整语义。

### 14.2 建议的下一步

1. **先补 `capabilities.py`，再补 `security.py`**：能力/策略层我还没系统学，而 `SecurityContext` / `CapabilityGate` 依赖它；顺序不能反，也不要把“知道定位”当成“已经会”。
2. **补 `guardrails.py`**：`_prepare_tool_call` 里已经见过调用点，但没看内部决策模型。
3. **做一个端到端练习**：用 `SqliteSessionStore` + `MemoryPolicy` + 自定义 Provider，跑一条“带工具、带记忆、带会话恢复”的链路，观察事件流。
4. **复现一次 Job lease/fencing 场景**：用 `test_v011_runtime.py` 为模板，理解“结果不发布”的边界。
5. **整理一份“事件类型字典”**：把 `run.* / model.* / tool.* / memory.* / job.* / inbox.* / goal.* / budget.*` 事件列全，复习时非常有用的索引。
6. **贡献候选**：`investigate/tool-result-hash-retrieval` 分支已经在探索“超大工具结果用 hash 引用替代”的方向；若继续做，需要先确认与 `ContextCompactor._spill_tool_results()` 的边界。

### 14.3 复习节奏建议

- 每周一次“只看图 + 速查表”的 10 分钟回顾；
- 每月一次“挑一个模块，从事件流角度重讲一遍”；
- 每次改代码前，先问：这个改动落在执行链、状态链、策略链、接口链的哪一条上？

---

## 15. 附录

### 15.1 工作区注释统计（截至 2026-10-24）

```text
修改文件：15 个
新增行：936
删除行：212
其中 LightAgent/ 7 个文件、docs/ 1 个、tests/ 2 个、example/ 4 个、.gitignore 1 个
```

按新增行规模排序：`protocol.py` > `core.py` > `session.py` > `example/` > `tools.py` > `runtime.py` > `capabilities.py`；按纯注释行排序则是 `core.py` > `session.py` > `protocol.py` > `example/` > `tools.py`。这与“记忆 → 主循环 → 会话 → 工具 → 运行时”的学习重心一致；`capabilities.py` 虽然在新增行里排最后，但只有名词级注释，**不能算学过**。

### 15.2 两篇前序笔记的定位

- [`notes/01`](01_项目的run函数相关的同步异步架构设计_20261011_161110.md)：回答了“`run`/`arun`/`astream`/`run_async_safely` 之间到底是什么关系”，结论是“同步核心 + 双向适配层”。
- [`notes/02`](02_异步生成器工具的价值与边界_20261013.md)：回答了“异步生成器工具到底解决了什么问题、边界在哪”，结论是“分段产生 × 逐段消费”。

本文不重复这两篇的完整推导，只保留结论并把它们放回模块地图里。

### 15.3 架构图集：是资产，不是“已读清单”

`notes/architecture/` 目前共有 34 张 HTML 图，覆盖：总览（01-02）、主循环/工具调用/MCP/Swarm/LightFlow（03-07）、记忆（08）、工具生成器（09）、流式/审批/会话时序（10-12）、请求与知识数据流（13-14）、各类生命周期（15-19）、调度管线与注册表（20-21）、Python 执行器与工具生命周期（22-23）、技能工具（24）、运行时（25）、事件流（26）、会话 lineage（27）、运行时全景（28）、run 调用链（29-33）、记忆调用链（34）。配套还有 `notes/architecture/_kb/` 下的四份知识库。

**但必须说清楚：这些图我只看过其中一部分，很多图并没有精读过。** 图集是学习资产，不是学习凭证；本文不会因为“某张图存在”就推断“我已经掌握对应模块”。实际使用原则是：

- 只有能和源码注释、`notes/01`、`notes/02`、测试或思维导图相互印证的内容，才按“已学”写入；
- 图集在本文中只作为“空间定位/辅助回忆”的索引，不作为独立证据；
- 没看过的图对应的模块，统一放在第 14 节的“尚未展开”，而不是默认已掌握。

复习时的正确用法：先用图快速定位，再回本文看解释，最后回代码确认；**不要用“图上有”代替“我懂了”**。导图里实际只引用过 34 号图（见 15.4），不能据此推断其它图也看过。

### 15.4 思维导图笔记对照

除了工作区注释，我还在 XMind 里维护过一份学习导图（`临时中转.xmind`，单 Sheet「逻辑图」）。用 `xmind` 技能解析后：**222 个节点、最大 9 级、2 条 notes、0 个 markers / labels / 链接**。它的价值不是“证明我学过什么”，而是**暴露我当时的知识组织方式**。

#### 结构概览

根节点 `中心主题` → 唯一一级分支 `04-LightAgent` → 6 个二级分支：

| 分支 | 节点数 | 最大额外层级 | 主要内容 | 对应本文 |
| --- | ---: | ---: | --- | --- |
| Agent测试 | 4 | 2 | Fake Model、`test_v065_core.py`、篡改 client | 第 9 节 |
| 1. core.py 核心 | 14 | 3 | `_core_run_logic` 双路径、`run_async_safely` 两种 asyncio 情形、`run/arun/astream` 调用链（写“见note/”） | 第 2 节 + `notes/01` |
| 2. tool模块 | 10 | 4 | `ToolRegister` / `ToolLoader` / `AsyncToolDispatcher`；调度器按返回值分 4 类 | 第 3 节 |
| 3. session 模块 | 19 | 3 | 事件溯源定位、`SessionEvent` vs `TraceEvent`、`append/append_event/checkpoint/fork/replay/validate` | 第 4 节 |
| 4. runtime 模块 | 71 | 6 | 9 个运行时属性、事件溯源 4 条好处、常见事件、Capability/Policy（仅两句定位） | 第 5 节；能力/策略见第 7 节待学 |
| 5. memory 模块 | 102 | 7 | 短期/长期记忆、Mem0、记忆三层（Backend/Policy/Orchestration）、字段级对象、两条调用链 | 第 6 节 |

节点分布很能说明问题：**memory 102 个（约 46%）+ runtime 71 个（约 32%），合计约 78%**；core/tool/session 则停在“要点 + 名词”级。导图里 memory 唯一展开到字段级（`MemoryScope` 8 字段、`MemoryCandidate` 13 字段、`MemoryPromotionDecision` 4 字段 + 5 个构造方法），runtime 展开了 9 个属性、4 条事件溯源收益和事件类型。

#### 导图帮我校准的几点

1. **记忆是当时最重、也最绕的部分**：导图里专门写了“记忆模块相关代码太绕，专门用笔记梳理调用链”，并给出检索链 4 步、持久化链 8 步。这解释了为什么本文第 6 节要按“读/写/晋升/过滤”拆开讲，而不是按类名罗列。
2. **core/tool/session 在导图里偏“框架级”**：core 只到 `_core_run_logic` 双路径和 `run_async_safely` 两情形，tool 只到调度器四分类，session 只到方法清单。后续工作区注释把 core 的 `_record_trace`、session 的 Store 协议与压缩、tools 的注册诊断补到了代码级——**导图 + 注释要合起来看，才是完整理解**。
3. **三个概念值得长期保留**：`SessionEvent` 是产品事件、`TraceEvent` 是调试开关；`MemoryPolicy` 是“看门人”（判断要不要存，但不负责存）；内部记忆的判定由 `internal_sources` / `internal_scopes` 两个集合决定。这三点已经回填到第 4.6、6.1、6.4 节。
4. **能力/策略在导图里也只有名词级**：runtime 分支只写了“Capability 描述能做什么、Policy 决定允不允许做”和几个 Provider 名称，没有展开 `capabilities.py`。这与我“第 7 节还没认真学”的自我判断一致，所以本文第 7 节只保留待学清单，不写机制详解。

#### 一个必须说清的边界

导图里**没有任何“已学/未学/待办/看过/没看”标记**，所以它不能证明我掌握到哪一步，更不能反推我看了哪些架构图。全文检索下来，导图只在 memory 分支的一条 note 里引用过 **`notes/architecture/34-memory-callchain.html`**（而且是“建议基于这张图去读源码”的语气），以及 core 分支写过一次“见 note/”；**没有出现 08、25、29 等其它图号**。

因此本文对图集的处理是：

- 34 号图可以视为“我当时知道它、并被建议用它复习记忆链路”，但**不等于我已经精读完**；
- 其余图没有任何来自导图的证据，一律不按“已学”处理；
- 导图本身也只是“知识组织证据”，概念写得浅不等于掌握；最终仍以代码注释、测试与实机验证为准。

> 小校正：导图里有少量笔误（如 `agnet`、`agent_time`、`SesssionEvent`、`AsyncToolDispather`、`_retireve_memory_hooks`、`slef.memory_policy` 等），本文按源码统一校正；导图的“知识骨架”保留，具体符号名以代码为准。

### 15.5 复现本文证据的命令

```bash
# 查看全部学习注释（工作区未提交改动）
git diff

# 只看新增行统计
git diff --stat

# 跑测试（先处理 NO_PROXY 中的 [::1]，再执行）
# PowerShell:
#   Remove-Item Env:NO_PROXY -ErrorAction SilentlyContinue
#   $env:NO_PROXY = 'localhost,127.0.0.1'
$env:PYTHONPATH = '.'
./.venv/Scripts/python.exe -m pytest -q --basetemp .pytest-tmp
```

### 15.6 注释摘录：我当时的原话

这些是从工作区 diff 里摘出来的注释原文，复习时读它们比读本文更快进入状态：

| 当时写下的注释 | 位置 | 它证明了什么 |
| --- | --- | --- |
| “解决了 `run()` 这样的同步入口如何安全调用异步函数的问题……**同步API内部桥接异步**是Agent框架的通用难题” | `core.run_async_safely` | 理解了双向桥接的动机 |
| “整个 run() 仅在这里访问了记忆模块” | `core._add_memory_context` | 记住了记忆注入的唯一入口 |
| “`upsert = update + insert`” | `core._upsert_memory_candidate` | 用一句话抓住了候选列表的更新语义 |
| “issue #1: 万一tool_response是 `AsyncGenerator`, 这里就会变成占位符placeholder” | `core._run_stream_logic` | 独立定位过异步生成器 bug |
| “(注意! 这里是拼接`arguments`，因为LLM的流式响应会把较长的工具调用参数会分多次传输)” | `core._run_stream_logic` | 理解了流式工具参数协议 |
| “这里其实和函数签名的`Generator[str, None, None]`不太匹配……但类型标注在运行时不会被强制检查” | `core._run_stream_logic` | 分清了名义类型与真实协议 |
| “`Protocol`的价值在于: 第三方用户可以自己实现一个存储后端, 不必修改和继承LightAgent的类” | `session.SessionStore` | 理解了 Protocol 风格接口 |
| “避免把留下来的非system的消息的第一条是tool消息, 因为tool消息可能是很长的工具调用结果, 依赖前面的assistant tool_call, tool_call_id” | `session.ContextCompactor.compact` | 抓住了裁剪的协议约束 |
| “只要是被promoted的记忆, 都会被标记为 injectable=True” | `core._apply_memory_promotion_decision` | 记住了晋升的判定开关 |
| “inbox已经收到过这个message_id的消息了, 不再重复enqueue” | `runtime.AgentInbox.enqueue` | 理解了 Inbox 幂等 |
| “fencing epoch 可以理解成是版本号码, 处于`interrupted`的job在恢复时, 会有更大的版本号” | `docs/runtime_v010.md` | 用类比吃透了 lease/fencing |
| “普通函数 - 直接调用 - (会阻塞dispather所在的工作线程)” | `tools.AsyncToolDispatcher.dispatch` | 分清“async def”与“不阻塞” |

### 15.7 本文的边界

- 以 `LightAgent/`、`docs/`、`tests/` 的工作区注释为主要依据；另外读过三篇记忆文档（`memory_admission`、`memory_trace_swarm_boundaries`、`memory_security`，未加注释，见 8.3）。
- `flow.py`、`knowledge.py`、`mcp_client_manager.py` 等模块只是“知道存在”，不代表已掌握。
- **第 7 节（能力与策略）整节按“未学”处理**：只有定位与调用点，不包含机制结论；不要因为文档里写了标题就以为已经掌握。
- 部分结论来自对代码的静态阅读和推演，未逐条跑测试验证；第 12 节的坑大多有注释或测试支撑，但仍建议复习时回代码确认行号与行为。
- 版本以当前分支（`study/agent-runtime`，基于 v0.11.0）为准；上游后续版本可能改变细节。

---

> 最后留一句给自己：这份总结的价值不在于“覆盖了多少符号”，而在于能否用**执行链、状态链、策略链、接口链**四条线，把任何一个新模块快速挂到已有的心智模型上。下次学新模块时，先问它属于哪条链、改动哪条边界，再读代码。
