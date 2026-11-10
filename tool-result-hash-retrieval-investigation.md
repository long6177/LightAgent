# 超长工具结果的 SHA-256 引用：模型有没有取回通道

- 日期：2026-10-15
- 代码基线：`8318a5d`（v0.11.0，`main` == `upstream/main`，工作树干净）
- 分支 / 工作树：`investigate/tool-result-hash-retrieval` / `.worktrees/investigate-tool-result-hash/`
- 配套材料：`external-frameworks-research.md`（外部框架一手资料调研，含全部来源 URL）

## 结论速览

1. 待验证说法基本成立，但要补两个边界：模型侧确实没有任何取回通道；完整内容并没有丢（保留在会话事件里）；另有一条只在开发者侧可用的旁路（`session.search`），框架不会把它接到模型面前。
2. 这个机制对长任务 Agent 有实际价值。业界前沿已经从"超限就丢/摘要"转向"卸载到外部 + 按需取回"（deepagents、Claude Code 是明确先例）。
3. 主流框架里"完整结果另存 + 引用"很普遍，"模型能取回"是少数。LangChain 核心的 `ToolMessage.artifact` 明确不发给模型；但 LangChain 官方同门的 deepagents 提供 `read_file` 取回。LlamaIndex、OpenAI Agents SDK、Anthropic context editing 都不给模型取回通道。
4. 取回机制只有一种站得住的形态：**模型主动调用取回工具**（不存在字面意义的"自动召回"），与 deepagents / Claude Code 的做法同构；配套必须把取回工具本身排除出 spill，否则会形成"取回→再 spill→再取回"循环（第四节）。
5. 提 feat PR 可行。建议先开 issue 对齐接口设计，PR 压到最小范围：一个 opt-in 的按引用取回工具 + 占位符附提示 + 自包含测试 + docs。
6. 上游贡献政策核查（第六节）：**没有"禁止外部贡献者增加机制/功能"的条款**；约束集中在"小而聚焦、别堆 core.py、向后兼容、安全敏感区附 security note、更新文档"，feature 需 issue 先行。外部贡献者的 feat PR 有多例合并先例。

## 一、验证：模型能不能取回完整工具结果

### 1.1 机制现状（代码事实，行号 @ 8318a5d）

spill 逻辑在 `LightAgent/session.py:802-822`：

- **触发条件**：**`role == "tool"` 且字符串内容长度超过 `max_inline_tool_chars`（默认 12000 字符，`session.py:748`）。**
- 处理方式：计算 SHA-256 → `reference = "tool-result:sha256:<digest>"`（`session.py:813`）→ 原文连同 reference/digest/size 放进 `spilled` 列表（`session.py:814-819`）→ 模型侧消息内容替换为占位符 `[Tool result stored outside context: <reference>, N chars]`（`session.py:820`）→ 消息 `metadata.content_reference` 写入 reference（`session.py:821`）。
- 触发时机：只有两处。一是手动调用 `agent.compact_session()`（`core.py:812`）；二是配置了 `context_budget` 且请求前估算超预算的自动压缩（`core.py:1107-1117`）。不配 budget、不手动压缩，就不发生 spill。
- **spilled 的去向：两处调用点都把完整 `spilled` 列表记录成 `context.compacted` 会话事件（`core.py:827/834`、`core.py:1116`）。完整内容就在事件数据里。**

模型可见的工具面：

- 模型收到的工具清单 = `tool_registry.get_tools()`（`core.py:705`），没有别的来源。
- 默认注册的工具：`safe_expression`、`upload_file_to_oss`（`core.py:269`），可选 Python 执行器；发现技能时另有 **`list_skills / activate_skill / execute_skill_script / read_skill_reference`**（只读技能目录文档）；以及用户自加工具、MCP 工具。
- 没有任何"按 reference / hash 取回"的工具。全仓 grep `content_reference` 只有 `session.py:821` 一处写入，无任何读取方。
- 占位符文本本身不含"怎么取回"的任何提示：没有工具名，没有调用建议。

### 1.2 两个必须说清的边界

边界 A：完整内容并没有丢，spill 是"按请求生成的视图"，不是销毁。

- **`tool_result` 追踪事件把完整 output 写入 `tool.completed` 会话事件**（`core.py:2044` 等）。
- 带 `session_id` 运行时，**每轮 run 会从会话事件重新投影历史消息（`core.py:567-577`、`core.py:630`），完整工具输出会重新进入消息列表；再次超预算时才重新 spill（同一内容 hash 稳定，前后两次 digest 一致）**。
- 内容跨不跨进程取决于 store：默认 `InMemorySessionStore`（`runtime.py:909`），进程结束就没了；换 Jsonl/Sqlite store 才是持久的。

边界 B：有一条开发者侧旁路，但不成机制。

- `SessionSearchProvider`（`knowledge.py:302-338`）提供 `session.search`：对 session 事件 JSON 做字面子串搜索，返回带 citation（`session:<id>:<seq>`）的事件数据。spill 的完整内容和 digest 字符串都在 `context.compacted` 事件数据里，所以拿 digest 去搜能命中。
- 但它
  - （1）是 capability，走 `agent.invoke_capability()` 给开发者用，不会自动变成模型工具；
  - （2）需要持久化 store；
  - （3）官方文档只把它作为"跨 Session 字面搜索"介绍（`docs/runtime_v010.md:149`）。要模型用上它，应用得自己包装注册——框架没做这一步。

- 同仓库还有一个可参照的既有实现：LightDAG 的 `LocalArtifactStore`（`LightAgent/dag/artifacts.py`）是内容寻址存储，带 `read(manifest, ctx)` 读回与 SHA-256 完整性校验。但它服务 DAG 任务产物，和 session spill 之间没有任何代码连接（互不引用）。

### 1.3 判定

- "没有实现'模型根据这个 hash 自动取回原始工具结果'的机制"：成立。
- "没有任何可能让 LLM 取回完整结果"：在"没有内置机制"这一层成立。严格说不是"内容不可恢复"，而是"模型手里只有一个死引用"。开发者理论上可以用现有积木自建旁路，但框架层面没有提供。
- 一个容易被忽略的点：框架连"告诉模型可以取"都没有做，占位符里既没有工具名也没有操作提示。

## 二、这个机制对现在的 Agent 应用意味着什么

**压缩策略分两代。** 第一代是有损压缩：超限直接丢（OpenAI Agents SDK 的 ToolOutputTrimmer、Anthropic context editing 的服务端清除），或用 LLM 摘要顶替（LangChain SummarizationMiddleware）。代价是信息永久消失——Agent 忘了之前查到的内容，就重复调工具、编答案。第二代是把内容搬到上下文外面、按需搬回来（deepagents 的 `/large_tool_results/` + `read_file`；Claude Code 的 Bash 输出落盘 + `Read`）。压缩从"信息损失"变成"信息换载"。

**为什么值得做。** 长任务 Agent（编码、检索、数据分析、深度工具链）现在很常见，单次工具输出动辄几十 KB，超限是常态而非边角情况。一旦触发有损策略，任务越长、失误越靠后越贵。取回通道让模型能在需要细节时拿回原文，而不是靠一个占位符硬撑。

**和 LightAgent 自身的契合度。** 这个仓库已经通过事件溯源把完整内容存下来了——`tool.completed` 和 `context.compacted` 两个事件里都有原文，reference 格式稳定，sha256 可直接做查询键。差的就是一条"模型能读回来"的通路。对它的架构来说，这是低成本补齐，不是另起炉灶。roadmap 里 v0.10 Milestone 4 的设计原文是 "Spill oversized tool results outside the prompt while retaining event-backed references and integrity metadata"（`roadmap.md:811`）——把 references 做成可读取的句柄是这句话的自然延伸。

**边界也要说清楚。** 回取必然是"模型主动调用一个工具"，不存在字面意义的自动回填（自动回填等于没压缩）。所以它需要：占位符里给一句取回提示（工具可用时）；取回带分页/上限，避免把刚压下去的上下文一次灌回来；内容可能含敏感数据，读取动作适合接入已有的 capability/policy 机制。小任务、小结果场景用不到这套，收益随任务长度和输出体积增长。

## 三、其它框架的现状（摘要，逐条来源见 `external-frameworks-research.md`）

| 框架/SDK | 机制 | 模型能否取回 | 来源 |
|---|---|---|---|
| LangChain (Python) | `ToolMessage.artifact`（完整结果双轨存放，文档明确"not meant to be sent to the model"）；SummarizationMiddleware / ContextEditingMiddleware 有损 | 不能（仅应用侧可编程访问） | [tool.py 源码](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/messages/tool.py) |
| deepagents（LangChain 官方） | `FilesystemMiddleware`：工具结果超 20000 token 写入 `/large_tool_results/{tool_call_id}`，替换为路径 + 前 10 行预览；模型用内建 `read_file`（支持 offset/limit）取回 | 能（模型驱动，分页） | [filesystem.py 源码](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/filesystem.py) |
| LlamaIndex | `ToolOutput.content` 与 `raw_output` 分离 | 不能（raw_output 仅应用侧） | [types.py 源码](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/tools/types.py) |
| OpenAI Agents SDK | `ToolOutputTrimmer`：旧轮次大输出破坏性替换为 200 字符预览，无任何归档 | 不能（不可逆） | [tool_output_trimmer.py 源码](https://github.com/openai/openai-agents-python/blob/main/src/agents/extensions/tool_output_trimmer.py) |
| Anthropic API | context editing（`clear_tool_uses`）服务端清除 + 占位符；配套 memory tool 做"清除前"持久化 | 不能回取已清除内容 | [官方文档](https://platform.claude.com/docs/en/build-with-claude/context-editing) |
| Claude Code | Bash 超长输出落盘 session 目录，给路径 + 预览，模型自己 Read/Grep（成功命令给路径；失败只给头尾摘录） | 能（部分） | [工具参考](https://code.claude.com/docs/en/tools-reference) |
| MCP 规范 | 工具结果可含 `resource_link` / embedded resource | 部分（规范只说 client 获取，是否暴露给模型取决于客户端） | [Tools 规范](https://modelcontextprotocol.io/specification/latest/server/tools) |

三点归纳：

1. "完整结果另存 + 引用 ID"是普遍做法，但"模型可取回"是少数派。
2. 实现取回的两家走的都是文件系统路线：落到模型可访问的文件，给路径，配一个读取工具。给纯 hash 引用而不配读取工具，等价于 LangChain 的 artifact——模型拿不到。
3. 因此"给 spill 加一条读取通道"不是自创路线，有明确的业界先例；但先例里能取回的引用形态是"路径 + 读取工具"，不是"hash 本身可解"。

## 四、机制形态：模型主动调工具召回（2026-10-15 讨论）

### 4.1 为什么这是唯一站得住的形态

模型能触发外部动作的通道只有工具调用。"框架自动把内容塞回去"等于没压缩（塞回去上下文又满了），而"现在需不需要细节"只有模型自己知道。所以凡是实现了取回的系统都是同一形状：**留下引用 → 提供读取工具 → 模型自主决定何时调**。判断权在模型，框架只负责让引用可解；不存在字面意义的"自动召回"。

### 4.2 这与主流一致

（每条的来源见第三节表格与 `external-frameworks-research.md`）

- deepagents：卸载 + 占位符给路径和预览 + 内建 `read_file`（offset/limit 分页）——与本方案同构；
- Claude Code：Bash 超长输出落盘、给路径，模型自己 `Read`/`Grep`；
- Anthropic memory tool：官方建议"清除前写入 memory、之后查回"，也是模型主动召回（预防型）；
- 反例恰好说明差异：LangChain `artifact`、LlamaIndex `raw_output` 只做了"另存"、没配取回工具；OpenAI trimmer 连另存都没有。主流的分水岭不在"要不要取回通道"，而在"引用 + 工具 + 提示"这套有没有配齐。

### 4.3 必须带的配套：取回工具自身排除出 spill

否则会出现循环：模型取回长内容 → 该工具的结果又超 `max_inline_tool_chars` → 又被 spill 成占位符 → 模型再取回……deepagents 源码里有 `TOOLS_EXCLUDED_FROM_EVICTION`（把 `read_file`、`grep`、`glob` 等"自带截断 / 永不超限"的工具排除在卸载之外）就是防这个的。对应到 LightAgent：取回工具要强制分页 + 硬上限，且其结果不参与 `_spill_tool_results`。

### 4.4 其它工程配套

- 工具可用时，占位符文本附一句取回提示（否则模型不知道有这个通道）；
- 取回作用域限当前会话；
- 查不到 reference 时返回明确错误；
- 入参直接采用现有 reference 格式 `tool-result:sha256:<digest>`，不新造 ID 体系。

## 五、给上游提 feat PR 的可行性

### 有利因素

- 设计契合：roadmap Milestone 4 的"event-backed references"已经把 reference 定为可追踪对象；实现侧内容已存进事件。补一个读取工具是小增量。
- 有业界先例背书（deepagents、Claude Code），issue 里可以引用，降低维护者的接受成本。
- 仓库内有现成模式：会话绑定的工具用闭包构造（`create_skill_tools(self.skill_manager)` 在 `core.py:296-300`），"按 reference 从当前会话的 `context.compacted` 事件读回"完全可以用同样模式实现，不引入新概念。
- 已有一个功能形态的对照：`LocalArtifactStore.read()`（DAG 子系统）证明仓库接受"内容寻址 + 读回 + 完整性校验"这套思路。

### 风险与约束

- 性质是 feature（新增 API/工具），不是 bugfix。上一个 asyncgen PR 是 bugfix 小修、零返工合并；feature 的上游处理周期和审查强度都会更高。上游 issue 历史里，feature 类需求（如 #70、#75）都经过了先开 issue 讨论的流程。
- 上游对 core 的态度偏保守：roadmap 明确说核心保持轻量，可选能力放 Provider（`roadmap.md:715-721` 附近的 Compatibility Boundary 一节）。工具放哪、默认开不开，需要维护者拍板。
- 安全面：spill 的完整内容可能包含敏感数据；取回工具等于给模型一个把已移出上下文的内容重新拉回来的入口。需要明确作用域（限当前会话）、可选 policy/审批、返回大小上限。
- 命名要准确：不存在"自动取回"，机制必然是模型主动调用取回工具。issue/PR 描述里要写清楚，避免被理解成"框架自动回填"而被否。

### 建议路径

1. **先 issue、后 PR。** issue 内容：现状（引用即死引用，附代码位置）、动机（long-horizon 任务的信息损失）、业界对照（deepagents / Claude Code 链接）、接口草案、安全考虑、测试计划。
2. **PR 形态压到最小**（若维护者认可）：
   - 一个 opt-in 的会话绑定工具（机制形态与防循环配套见第四节），按 `tool-result:sha256:<digest>`（或完整 reference）从当前会话的 `context.compacted` 事件中定位 spill 项，支持 offset/size 分页返回；
   - 工具可用时，占位符文本追加一句取回提示；
   - 自包含测试（可扩展 `tests/test_v010_session.py:70` 的既有 spill 测试）；
   - docs（`docs/runtime_v010.md` 的 "Context And Knowledge" 一节，`docs/runtime_v010.md:130`）。
3. **备选退路**：如果维护者希望 core 保持最小，就退到"可选 Provider / 示例层"的形态——把读取逻辑做成一个可选工具模块，由用户显式注册。

### 判定

可行，且方向有业界验证；建议走"issue 先行 + 最小 PR"。主要不确定性不在技术，而在维护者对 core 扩张的态度——issue 阶段就能试出来。

## 六、上游贡献政策核查：对 PR 有什么限制

> 核查时间 2026-10-15。上游 HEAD 仍是 `8318a5d`；自 v0.11.0 发布后 CONTRIBUTING / roadmap / `.github/` 均无改动，下述即现行规则。

### 6.1 明文规则

总基调（README 原文）："We welcome any form of contribution"。**没有任何"外部贡献者不得增加功能/机制"的条款**；限制全部是形态与范围层面的：

| 来源 | 规则 |
|---|---|
| CONTRIBUTING | "values small, focused changes that preserve the lightweight core and keep existing APIs compatible" |
| CONTRIBUTING | 默认 `agent.run()` / `stream=True` 行为须向后兼容（除非显式批准并记录） |
| CONTRIBUTING | "Prefer focused modules and tests over adding more logic to `LightAgent/core.py`" |
| CONTRIBUTING | memory / MCP / **tool loading** / code execution 类改动，PR 必须附简短 security note |
| CONTRIBUTING | 行为、配置、公共 API 变化要同步更新 README 或 `docs/` |
| CONTRIBUTING §3 | 第三方服务类贡献：披露利益关系、给官方文档、提供可复现证据；"Maintainers may decline or remove..." |
| SECURITY.md | 敏感区要 extra review，其中包括 **"tracing and logs that may capture tool arguments or outputs"** 与"动态工具加载" |
| roadmap | "Not planned for the core repository"：marketplace、托管 review UI / observability dashboard、外部 API 捆绑；厂商型提案走外部 connector（#26、#50 即按此关闭） |
| roadmap | 版本方向原文含 **"...long-task control + recoverable context + stable APIs"** |
| PR 模板 | Summary / Compatibility（两项勾选）/ Tests（compileall + 指定测试）/ Notes（迁移·安全·文档影响） |
| feature 模板 | Problem / Proposed solution / Alternatives / Additional context |

### 6.2 实际执行尺度（截至 2026-10-15 的 PR/issue 历史）

外部贡献者的 PR 不仅被合并，还有多次直接改核心、加功能的先例：

- **合并先例（增功能 / 改核心类）**：#52 LiteLLM provider（feat）、#106 Memcode 适配器（feat，+466 行 / 4 文件）、#80 保留 LightSwarm 运行上下文（只动 `core.py` + 1 个测试，+96/-13）、#71 流式 tool loop 重试上限（对应 feature 请求 #70）。
- **合并先例（fix/docs 类）**：#108（asyncgen，本账号）、#109、#95、#85、#67、#66、#74、#72、#60、#56。
- **被关闭的外部 PR**：#96 Parallel Search MCP 集成、#89 OrcaRouter provider 文档——都命中"第三方托管服务"条款；#97/#98/#99（LightFlow 修复）——维护者认可问题存在，但要求把语义显式化并补测试，数轮迭代后仍未合并。**没有一例以"不允许外部加功能"为由关闭。**
- **维护者对 feature 提议的标准动作**（issue #75 原话）：认可方向 →"维护侧将其作为 P1 enhancement 纳入后续版本，并**开放贡献**"→ 给出"小而兼容"的首个 PR 范围清单 →"欢迎按上述范围提交一个聚焦 PR，并在描述中关联 #75"。该 issue 于 2026-07-10 15:48 随维护者自己的 v0.9.4 发布 PR（#78，含 Tool Diagnostics）一并关闭——维护侧有时会自己快速实现，提 issue 后要跟进。
- **当前开放的外部 PR**：#115（feat(tools)，10-07 创建）、#116（docs，10-13 创建），尚无维护者评论——近期外部 PR 的 review 排期大约 1 周量级。

### 6.3 对本项目（取回工具）的直接含义

- 不撞任何红线：不是第三方服务、不是托管大件、不是 marketplace 类；方向落在 roadmap 明文的 "recoverable context" 里。
- 必须满足的形态（逐条对照 CONTRIBUTING 与模板）：
  1. 小而聚焦：工具本体放独立模块（别堆进 `core.py`），注册走现有入口，附聚焦测试；
  2. 默认行为不变：opt-in 注册；若改占位符文案（给模型加取回提示），按"行为变化"在 docs 记录；
  3. PR 里主动附 security note（命中 "tool loading" 与 "tracing 可能捕获工具输出" 两个敏感区）；
  4. 更新 `docs/runtime_v010.md` 的 Context And Knowledge 一节；
  5. 先开 feature issue（照模板四栏），PR 描述关联 issue；PR 模板四区块照填。
- 预期节奏：issue 响应通常 1 天内；PR 若触及核心语义，参考 #97-99 案例，做好补充测试、文档与多轮迭代的准备。

## 附录 A：代码锚点（@ 8318a5d）

| 位置 | 内容 |
|---|---|
| `session.py:748` | `max_inline_tool_chars` 默认 12000 |
| `session.py:754` / `session.py:792` | spill 的两处调用点（compact / compact_to_budget） |
| `session.py:802-822` | `_spill_tool_results` 全文：digest、reference、占位符、metadata |
| `core.py:269-303` | 默认内置工具注册（无取回工具） |
| `core.py:567-577`、`core.py:630` | session 模式下从事件投影历史 |
| `core.py:705` | 模型工具清单来源 = tool_registry |
| `core.py:812-834` | `compact_session()` 记录 spilled 到 `context.compacted` |
| `core.py:1107-1117` | 自动压缩路径，同样记录 spilled |
| `core.py:2044` 等 | `tool_result` 追踪事件携带完整 output |
| `knowledge.py:302-338` | `SessionSearchProvider`（session.search，开发者侧） |
| `runtime.py:909` | 默认 InMemorySessionStore |
| `dag/artifacts.py` | LocalArtifactStore：内容寻址 + read-back（DAG 子系统，未接入 spill） |
| `roadmap.md:811` | Milestone 4 原文："retaining event-backed references and integrity metadata" |
| `tests/test_v010_session.py:70` | 既有 spill 测试（断言完整内容保留在 spilled、消息被替换） |

## 附录 B：未核实清单

- Gemini CLI / OpenAI Codex CLI / Vercel AI SDK 的截断落盘行为（见 `external-frameworks-research.md` 末尾清单）。
- MCP `resources/read` 是否被主流客户端暴露为模型可调用工具（规范只说 client 获取）。
- 上游是否已有人提过类似需求：检查过全部 40 条 issue 标题与状态，未见相关条目（最近 issue #117 为文档类、#100 为安全披露）。
