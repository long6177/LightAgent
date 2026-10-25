# 主流 Agent 框架/SDK：超长工具结果与「模型驱动取回」能力调研

> 调研问题：当工具结果太长、被截断、或被替换成占位符/引用 ID 时，**模型**（而非框架代码）有没有一条通道能主动取回完整内容？
>
> 每条结论均力求基于一手来源（GitHub 源码 / 官方文档）。无法核实处标注「未验证」。
> 调研日期：2026-10-15。

---

## 1. 汇总表

| 框架/SDK | 机制 | 模型能否取回完整结果 | 关键来源 |
|---|---|---|---|
| **LangChain (Python)** | `ToolMessage.artifact`（完整结果存 artifact）；`SummarizationMiddleware`（摘要压缩）；`ContextEditingMiddleware`（占位符清除） | **不能**（仅框架/应用侧可编程访问） | [ToolMessage 源码](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/messages/tool.py) |
| **deepagents** | `FilesystemMiddleware` 自动卸载大工具结果到文件系统 + `read_file` 工具；`SummarizationMiddleware` 归档历史 | **能**（模型调 `read_file`，分页读取） | [filesystem.py 源码](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/filesystem.py) |
| **LlamaIndex** | `ToolOutput.content` vs `ToolOutput.raw_output` 分离 | **不能**（`raw_output` 仅供应用侧使用） | [tool types 源码](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/tools/types.py) |
| **OpenAI Agents SDK** | `ToolOutputTrimmer`（旧轮次大输出替换为预览，有损不可逆） | **不能**（无任何存储/取回路径） | [tool_output_trimmer.py 源码](https://github.com/openai/openai-agents-python/blob/main/src/agents/extensions/tool_output_trimmer.py) |
| **OpenAI Responses API** | 服务端 compaction（`truncation="auto"`，截断式）；code interpreter 产物以 `file_id` 引用 | **不能**（模型无工具可回取被截断的工具结果） | [上下文压缩说明](https://www.sitepoint.com/openai-agentic-primitives-guide-skills-shell-compaction/) |
| **Claude Code (Anthropic)** | Bash 输出超限后落盘到 session 目录，给出文件路径 + 预览，模型自行 `Read`/`Grep` | **能**（成功命令的结果；失败命令无路径） | [Claude Code 工具参考](https://code.claude.com/docs/zh-TW/tools-reference) |
| **Anthropic API** | context editing `clear_tool_uses_20250919`（服务端清除并替换为占位符）；`memory_20250818` 记忆工具 | **不能**回取已清除内容；但可用 memory 工具**事前**持久化 | [Context editing 官方文档](https://platform.claude.com/docs/en/build-with-claude/context-editing) |
| **MCP 规范** | 工具结果可含 `resource_link` / embedded `resource`（URI 引用） | **部分/取决于客户端**（模型需经客户端 `resources/read` 取回） | [MCP Tools 规范](https://modelcontextprotocol.io/specification/latest/server/tools) |
| **Gemini CLI / Codex CLI / Vercel AI SDK** | 截断+落盘行为 | **未验证** | 见文末存疑清单 |

---

## 2. 各对象细节

### 2.1 LangChain (Python) —— `ToolMessage.artifact`

**机制名称**：`ToolMessage.artifact`（完整结果与模型可见内容分离）。

**怎么工作**：
`ToolMessage` 是工具执行结果回传给模型的消息。它有两个"结果"字段：`content`（字符串化输出，发送给模型）与 `artifact`。`artifact` 的官方定义为"工具执行的产物，**不打算发送给模型**"，只在"仅一部分输出作为 message content 传给模型、但完整输出在代码其他部分仍需要"时使用。例如 Bash 工具把 `stdout` 放进 `content`，把完整 `{stdout, stderr, artifacts}` 放进 `artifact`。`artifact` 可由应用代码通过 `message.artifact` 编程访问。

**关键判断**：**仅框架侧**。源码 docstring 明确 "not meant to be sent to the model"，且没有任何内建工具让模型按 ID 取回 artifact。模型看不到它、也无法请求它。

**相关中间件（均为框架侧、有损）**：
- `SummarizationMiddleware`：token 超阈值时用 LLM 摘要替换旧消息；deepagents 文档明确对比指出 **"LangChain drops evicted messages with no recovery path"**（LangChain 丢弃被淘汰消息且无恢复路径）。
- `ContextEditingMiddleware`：实现类似 Anthropic `clear_tool_uses_20250919` 的策略，把被清除的 `ToolMessage.content` 替换为占位符（默认 `"[cleared]"`），并写入元数据；对象在进入模型前被就地修改；同样**无回取通道**。

**一手来源**：
- 源码：`libs/core/langchain_core/messages/tool.py` — https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/messages/tool.py
- API 参考：https://python.langchain.com/api_reference/core/messages/langchain_core.messages.tool.ToolMessage.html
- MCP 适配器行为（secondary，说明 structuredContent → artifact 不发给模型）：https://forum.langchain.com/t/why-can-the-model-see-the-structured-content-returned-by-the-mcp-tool/3076
- 中间件列表（secondary）：https://deepwiki.com/lwtaiyty/langchain/6.3-built-in-middleware

---

### 2.2 deepagents（LangChain 官方 Deep Agents SDK）—— 大工具结果卸载 + 文件系统取回

**机制名称**：Tool Result Offloading（`FilesystemMiddleware` 自动卸载）。

**怎么工作**：
`create_deep_agent` 默认内置上下文压缩。当**工具调用结果超过 20,000 tokens（默认）** 时，`FilesystemMiddleware` 会把完整结果写入后端文件系统（路径形如 `/large_tool_results/{tool_call_id}`），并在对话中把该结果**替换为「文件路径引用 + 前 10 行预览」**。模型随后可调用内建 **`read_file` 工具（支持 `offset`/`limit` 分页）**、或 `grep`/`glob` 搜索，按需取回被卸载的完整内容。此外，**超大的工具输入**（write_file/edit_file 参数）在会话上下文超过模型窗口 85% 时也会被截断为磁盘指针；`SummarizationMiddleware` 在 85% 阈值时把旧消息归档到 `/conversation_history/{thread_id}.md`，摘要中嵌入该路径，模型仍可用 `read_file` 重新打开。

**默认阈值（源码）**：
- `NUM_CHARS_PER_TOKEN = 4`（约 4 字符 = 1 token）
- `tool_token_limit_before_evict: int | None = 20000`（工具结果卸载阈值）
- `human_message_token_limit_before_evict: int | None = 50000`（人类消息卸载阈值）
- `TOOLS_EXCLUDED_FROM_EVICTION`：`ls, glob, grep, read_file, edit_file, write_file, delete`（自带截断或永不超限的工具不参与卸载）
- 摘要触发：模型 `max_input_tokens` 的 85%；不可用时回退 170,000 tokens / 保留 6 条消息。

**关键判断**：**模型驱动**。这是少数真正给模型提供"取回通道"的实现——模型自己决定何时调 `read_file` 读回完整内容。

**一手来源**：
- 源码：`libs/deepagents/deepagents/middleware/filesystem.py` — https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/filesystem.py
- 官方文档（Context engineering in Deep Agents）：https://docs.langchain.com/oss/python/deepagents/context-engineering
- 官方博客（Context Management for Deep Agents）：https://www.langchain.com/blog/context-management-for-deepagents
- 官方博客（Context Engineering with Deep Agents）：https://www.langchain.com/blog/context-engineering-deep-agents-remember
- 摘要中间件 API 参考：https://reference.langchain.com/python/deepagents/middleware/summarization/

---

### 2.3 LlamaIndex —— `ToolOutput.raw_output`

**机制名称**：`ToolOutput`（`content` 与 `raw_output` 分离）。

**怎么工作**：
`ToolOutput` 字段：`blocks`（内容块）、`tool_name`、`raw_input`、`raw_output`、`is_error`。其中 `content` 是**属性（property）**，把 `blocks` 中的 `TextBlock` 文本拼接为字符串；`raw_output` 是"底层函数未经处理的返回值（unprocessed return value）"。`FunctionTool.call()` 里默认构造为 `ToolOutput(content=str(raw_output), raw_input=..., raw_output=raw_output)`——即 `content`（模型看到的）与 `raw_output`（原始对象）分离。语义上与 LangChain `artifact` 类似。

**关键判断**：**不存在模型驱动的取回**。`raw_output` 只是应用侧持有的原始返回值，LlamaIndex 没有内建工具让模型按引用取回。历史上还曾因 `str(Document)` 截断导致 Agent 死循环（issue #19585），说明其默认把 `str()` 结果作为模型可见内容。

**一手来源**：
- 源码（ToolOutput 定义）：`llama-index-core/llama_index/core/tools/types.py` — https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/tools/types.py
- 源码（FunctionTool.call）：https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/tools/function_tool.py
- API 参考：https://docs.llamaindex.org.cn/en/stable/api_reference/tools/function
- 相关 issue（Document 截断修复）：https://github.com/run-llama/llama_index/issues/19585

---

### 2.4 OpenAI Agents SDK —— `ToolOutputTrimmer`

**机制名称**：Tool Output Trimmer（`call_model_input_filter`）。

**怎么工作**：
一个内建的 `CallModelInputFilter`，在**每次模型调用前**运行，采用滑动窗口：最近 `recent_turns`（默认 2）条 user 消息及其之后的所有 items 永不修改；更早轮次中**字符数超过 `max_output_chars`（默认 500）** 的工具输出会被替换为一段紧凑预览，保留 `preview_chars`（默认 200）个字符（结构化输出仅保留文本部分，图片/文件等不透明 payload 被丢弃）。可经 `trimmable_tools` 限定只修剪特定工具。

**关键判断**：**不存在取回通道**（有损且不可逆）。源码为破坏性替换 `trimmed_item["output"] = summary`，**没有任何备份/归档/落盘逻辑**，被裁掉的内容对模型不可见，也无法经任何接口取回；唯一的记录是一条不含内容的 debug 日志。

**Response API 侧**：
- 服务端 compaction（`truncation="auto"`）是**截断式**（truncation-based）而非无损摘要——直接丢弃旧上下文，客户端无需管理滑动窗口。模型无工具可回取被丢弃的工具结果。
- code interpreter 生成的产物（图表/CSV）以 `file_id` 引用，可通过 Files API **由应用**下载——这是应用侧引用，不是模型可调用的取回工具。
- "Programmatic Tool Calling" 会把中间结果保留在托管运行时内，但那发生在**单次程序执行内部**，不是跨轮次的模型取回。

**一手来源**：
- 源码：`src/agents/extensions/tool_output_trimmer.py` — https://github.com/openai/openai-agents-python/blob/main/src/agents/extensions/tool_output_trimmer.py
- API 参考：https://openai.github.io/openai-agents-python/ref/extensions/tool_output_trimmer
- Responses API compaction / file 产物（secondary 指南）：https://www.sitepoint.com/openai-agentic-primitives-guide-skills-shell-compaction/
- 官方 function calling 指南：https://developers.openai.com/api/docs/guides/function-calling （未描述大输出存储/取回机制）

---

### 2.5 Anthropic / Claude

#### 2.5.1 Claude Code —— Bash 超长输出落盘 + 模型可读回

**机制名称**：Bash 工具输出截断 + session 文件落盘。

**怎么工作**：命令完成后，Claude Code 会把输出与内联上限比较：
- **有效结果（成功命令）**：内联最多约 **30,000 字符**（默认）；超过该值，则给 Claude **保存在 session 目录中的文件路径**（文件超过 64 MiB 的部分被截断），外加最多 **前 2,000 字符的预览**；Claude 在需要其余内容时**读取或搜索该文件**。
- **失败结果**：内联最多约 **10,000 字符**；超过则给出该大小的**头尾摘录，且没有文件路径**。

相关配置：`BASH_MAX_OUTPUT_LENGTH`（默认 30,000，硬上限 150,000）控制"从工作文件读回"的窗口；`bashOutputMaxChars`（Claude Code v2.1.261+，4,000–128,000）调整有效结果的内联上限并同步调整读回窗口。

**关键判断**：**模型驱动（部分）**。对**成功命令**，模型拿到保存文件的路径后，会自己决定用 `Read`/`Grep` 去读回完整内容——这是一条真实的模型驱动取回通道。但对**失败命令**，只给头尾摘录、**不给文件路径**，模型无从取回中间部分。

**一手来源**：
- Claude Code 工具参考（官方，含上表）：https://code.claude.com/docs/zh-TW/tools-reference （英文版：https://code.claude.com/docs/en/tools-reference）
- 佐证（secondary，说明成功/失败两种上限与落盘）：https://omidsaffari.com/blog/claude-code-tool-output-limits-2-1-261 、https://www.getclaudeskills.com/blog/claude-code-bashoutputmaxchars-taskoutputmaxchars-settings

#### 2.5.2 Anthropic API —— context editing 与 memory tool

**机制名称**：Context editing（`clear_tool_uses_20250919`）+ Memory tool（`memory_20250818`）。

**怎么工作**：
context editing 是 beta 功能（beta header `context-management-2025-06-27`），在**服务端、提示词到达模型之前**生效。`clear_tool_uses_20250919` 在上下文增长超过阈值（默认 trigger 100,000 input tokens、keep 3 个最近 tool-use/result 对）时，按时间顺序清除**最旧的工具结果**，并用**占位符文本**替换，让 Claude 知道该内容已被移除；可选 `clear_tool_inputs` 同时清除工具调用参数。**客户端保留完整未修改历史**。官方建议与 memory tool 配对：Claude 会在临近清除阈值时被警告，可**在清除前**把重要结论写入 memory 文件，之后再查回。

**关键判断**：被清除的工具结果 **模型不能取回**（它已从模型可见上下文中移除，仅客户端本地仍有）。但 memory tool 提供了一条**模型驱动的事前持久化/事后取回**路径——这是"预防性"而非"回取被删内容"。

**一手来源**：
- 官方文档 Context editing：https://platform.claude.com/docs/en/build-with-claude/context-editing
- 佐证（secondary，含参数默认值与应用效果）：https://github.com/0xdarkmatter/claude-mods/blob/main/skills/claude-api-ops/references/compaction.md

---

### 2.6 MCP（Model Context Protocol）—— `resource_link` / embedded resource

**机制名称**：工具结果中的资源引用内容类型。

**怎么工作**：
MCP「Tools」规范规定，工具结果 `content` 字段可包含多种内容项：text、image、audio、**resource_link**、**embedded resource**（`type: "resource"`）。其中：
- **Resource Links**：工具**可以（MAY）**返回指向 Resources 的链接，"a URI that **can be subscribed to or fetched by the client**"；规范特别注明"工具返回的资源链接**不保证**出现在 `resources/list` 结果中"。
- **Embedded Resources**：资源可被内嵌（含 URI/mimeType/text），使用内嵌资源的服务器 **SHOULD** 实现 resources 能力。

**关键判断**：**部分 / 取决于客户端**。规范层面提供了"工具结果引用一个资源、随后再取回"的原语（URI + `resources/read`），但是否把 `resources/read` 暴露为**模型可调用**的工具，取决于客户端实现（规范说链接由 **client** 订阅/获取，而非直接由模型）。因此 MCP 本身不保证"模型驱动取回"，只提供了可选的机制基座。

**一手来源**：
- MCP 规范 Tools（最新版）：https://modelcontextprotocol.io/specification/latest/server/tools
- MCP 规范 Tools（2026-07-28 中文）：http://mcp-docs.cn/specification/2026-07-28/server/tools
- 教学说明（secondary）：https://mcp-fundamentals.epicai.pro/04

---

## 3. 横向对比与结论要点

1. **「完整结果另存 + 引用 ID」是普遍做法，但「模型可取回」是少数。** LangChain `artifact`、LlamaIndex `raw_output`、OpenAI `ToolOutputTrimmer`、Anthropic context editing 都属于**框架/服务端侧、对模型不可见**的处理；它们要么保留完整内容给应用代码（artifact/raw_output），要么直接有损丢弃（trimmer/context editing）。
2. **真正实现「模型驱动取回」的是文件系统路线**：deepagents 的 `FilesystemMiddleware`（默认 20,000 token 卸载阈值，路径引用 + `read_file` 分页）与 Claude Code 的 Bash 落盘（成功结果给路径 + 模型 `Read`）。共同点：把大结果**落到模型可访问的文件系统**，并给模型**一个文件路径 + 读取工具**。
3. **纯粹的 hash/ID 引用若无配套读取工具，模型无法取回。** 上述可取的实现都配了 `read_file`/`Read` 之类工具；单纯给一个引用 ID（如 SHA-256）而不提供读取通道，属于"仅框架侧"，模型拿不到。

**对 LightAgent 的启示（供团队判断）**：若 LightAgent 把 SHA-256 作为超长工具结果的引用 ID 但未提供"按 hash 读回"的工具，则其行为等价于 LangChain `artifact` / LlamaIndex `raw_output`（框架侧引用），**模型不可取回**；要对齐 deepagents 的能力，需要显式提供 `read_file`/按 hash 读取的工具 + 在对话中给出可访问路径/ID。

---

## 4. 术语出处：「context offloading」

- "offloading"（工具结果卸载）这一术语在 **LangChain 官方博客**中被明确使用：*"Context Engineering with Deep Agents: How To Remember Without Keeping Everything In Context"* 一节的标题即为 "**Tool Result Offloading**"，并描述"when a tool result exceeds roughly 20,000 tokens, the full result is written to `/large_tool_results/{tool_call_id}` ... The model sees only a short preview ... plus the file path"。
- 同一系列文章将其归纳为三大上下文压缩技术：Offloading large tool results、Offloading large tool inputs、Summarization。
- 来源：https://www.langchain.com/blog/context-engineering-deep-agents-remember ；https://www.langchain.com/blog/context-management-for-deepagents
- 注：是否由 LangChain 首创该术语**未验证**（未检索到更早的权威出处）。

---

## 5. 未能核实 / 存疑清单

1. **Gemini CLI 的截断+落盘行为**：未核实。未找到一手来源说明其工具输出超限后是否落盘、模型能否读回。
2. **OpenAI Codex CLI 的截断行为**：未核实。
3. **Vercel AI SDK 的工具结果引用机制**：未核实（仅有 Anthropic provider 的 contextManagement 透传说明）。
4. **「context offloading」术语的最早出处**：仅确认 LangChain 博客在广泛使用；是否为该术语首创**未验证**。
5. **Claude Code 失败命令路径**：官方表中失败结果"没有文件路径"，但第三方文章提示 `bashOutputMaxChars` 是否也影响失败场景**未官方确认**（标注为"treat the failure path as unchanged unless confirmed"）。
6. **MCP `resources/read` 是否被主流客户端暴露给模型**：规范只定义"client 获取资源"，**未验证**具体客户端（如 Claude Desktop、VS Code）是否把 `resources/read` 作为模型可调用工具，因此"模型驱动取回"在 MCP 上仍属**客户端相关、未坐实**。
7. **LangChain 源码精确行号**：本文引用的是 `master` 分支文件级链接；因分支会移动，未固定到具体 commit 行号。
8. **OpenAI Responses API 官方文档原文**：`function-calling` 指南未涉及大输出存储/取回；compaction 的细节部分依赖 secondary 指南，**官方原始页面未逐字核对**。
