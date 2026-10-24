# 工具箱 / 内置工具 / 技能 / MCP / 连接器 源码知识库

> 源文件（行号以工作树 2026-10-24、提交 ac177ca 实读为准）：
> `LightAgent/tools.py`(412 行)、`LightAgent/builtin_tools/nos.py`(182 行)、`LightAgent/builtin_tools/python_executor.py`(816 行)、`LightAgent/builtin_tools/safe_expression.py`(173 行)、`LightAgent/skill_tools.py`(115 行)、`LightAgent/skills.py`(274 行)、`LightAgent/mcp_client_manager.py`(284 行)、`LightAgent/connectors.py`(370 行)。
> 行号均为真实 def/class 行号。核心装配点在 `core.py`（见各节"与其他模块的关系"）。

---

# tools.py（LightAgent/tools.py）

## 模块概览

工具体系的三件套：`ToolRegistry` 是集中式工具注册表（同一份 tool_info 同时维护"名字→函数"、"名字→元数据"、"OpenAI function-calling schema"三个视图）；`ToolLoader` 从 `tools/` 目录按文件名动态 import 工具函数（带路径逃逸防护与缓存）；`AsyncToolDispatcher` 是统一调度入口，按函数类型（协程/异步生成器/同步生成器/普通函数）分派执行，并在执行前做必填参数与类型校验。所有工具（本地注册、内置工具、技能工具、MCP 远程工具）最终都汇入 ToolRegistry，再由 dispatcher 执行。

## 类与符号清单

- `_TOOL_NAME_PATTERN` (L23)：模块级正则 `[A-Za-z_][A-Za-z0-9_]*`，工具名/加载名合法性基准。
- `_SUPPORTED_TOOL_PARAM_TYPES` (L24)：允许的参数类型集合（string/integer/number/boolean/array/object）。
- `ToolRegistry` (L27-L222)：工具注册表，三视图集中管理。
- `ToolLoader` (L225-L279)：`tools/*.py` 动态 import 加载器（缓存 + 安全校验）。
- `AsyncToolDispatcher` (L282-L412)：异步工具调度器，dispatch 统一入口。

## 关键方法

### ToolRegistry

- `__init__` (L30) — 初始化 `function_mappings`（名→函数）、`function_info`（名→tool_info）、`openai_function_schemas`（OpenAI schema 列表）、`_registration_counts`（同名不同函数注册计数）。
- `register_tool` (L37) — 登记单个工具；调用者：core.py:282、299、451、457、1392、1398（Agent 构造与 load_tools）、mcp_client_manager **不经过它**（直接写内部字段）。它调用：无外部依赖。
- `register_tools` (L90) — 批量注册，任一失败整体返回 False。
- `validate_tool_info` (L99, staticmethod) — 对一份 tool_info 做结构化诊断（tool_name 正则/描述非空/参数名重复/参数类型合法/required 为 bool）；调用者：`validate_tools` (L180)、connectors.py:200。
- `validate_tools` (L176) — 遍历已注册工具做诊断，并额外报告"同名工具被注册多次"（L181-188）；调用者：core.py:400。
- `get_tools` (L191) — 返回 OpenAI schema 的 deepcopy；调用者：core.py:396、710。
- `get_tools_str` (L195) — schema 格式化 JSON 字符串（用于工具反思 prompt）；调用者：core.py:2851。
- `filter_tools` (L199) — 按模型工具反思输出（可含 ```json 代码块）过滤 schema 子集；调用者：core.py:2921。

### ToolLoader

- `load_tool` (L240) — 单工具加载：名字安全校验 → 缓存命中 → 拼路径并防目录逃逸（L250 `startswith(tools_directory + os.sep)`）→ `importlib.util.spec_from_file_location` 动态加载（L256-258）→ 取与文件同名的可调用且带 `tool_info` 的函数（L261-263）；调用者：`load_tools` (L278)、core.py:450（Agent.load_tools）。
- `_is_safe_tool_name` (L270, staticmethod) — 只允许字母数字下划线的工具名。
- `load_tools` (L274) — 批量加载，跳过已缓存。

### AsyncToolDispatcher

- `dispatch` (L295) — 调度核心：查 `function_mappings`（未找到→格式化 LA-TOOL 错误串 L309-310）→ `_validate_tool_params` 前置校验（L315）→ 四路分派（协程 await L320-322 / 异步生成器原样返回 L323-326 / 同步生成器原样返回 L327-329 / 普通函数直接调用 L334-336）→ 非生成器结果经 `_serialize_result` 转字符串（L339）→ 异常捕获为 LA 错误码 + traceback 字符串（L340-341）。调用者：core.py:2091、2376（run 工具循环，经 `run_async_safely`）、capabilities.py:636（ToolCapabilityProvider.invoke）。
- `_serialize_result` (L343) — None→成功提示；dict/list→JSON；其余→str()。
- `_validate_tool_params` (L352) — 按 tool_info 校验必填参数存在（L367-368）与声明类型匹配（L369-375），错误以 LA-TOOL 错误码字符串返回（不抛异常）。
- `_matches_declared_type` (L379, staticmethod) — 类型宽容匹配：integer 排除 bool（L395）、number 接受 int/float、未知类型放行（L404）。
- `async_stream_generator` (L406) / `stream_generator` (L410) — 生成器透传包装器，**当前仓库内无调用点**（预留接口）。

## 关键机制细节

### register_tool 登记流程 (L37-L88)

1. 无 `tool_info` 属性直接返回 False（L43-44）——"函数 + tool_info 属性"是全框架统一的工具定义协议。
2. 取 `tool_info["tool_name"]`；用 `_registration_counts` 统计同名**不同函数**的注册次数（L47-52）：首次置 1，同函数重复注册不计数，不同函数 +1。
3. 直接覆盖写 `function_info[name]` 与 `function_mappings[name]`（L55-56）——**同名后注册者赢，不报错**。
4. 由 `tool_params` 构建 OpenAI schema（L58-78）：每个参数剥掉 `name`/`required` 两键后作为 property（L62-63），`required=True` 的参数名进 `required` 数组。
5. 先从 `openai_function_schemas` 删除同名旧 schema（L82-85），再 append 新 schema（L87）——保证 schema 视图与映射视图一致。

### dispatch 查找与执行流程 (L295-L341)

见上方关键方法。要点：生成器**不被消费**，原样交还调用方（L330-332、L331 的注释块是历史收集逻辑残留）；消费责任在 core.py:2105-2113（`isinstance(tool_response, Generator)` 后逐 chunk 拼接）。所有失败路径都返回**错误字符串**而非抛异常，保证工具循环不中断。

## 与其他模块的关系

| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| ToolRegistry.register_tool:37 | core.py:273-283 | 构造时注册内置工具（safe_expression/upload_file_to_oss 常驻；python 三件套需 `enable_unsafe_python`） |
| ToolRegistry.register_tool:37 | core.py:296-303 | 技能发现后注册 create_skill_tools 产出的 4 个技能工具 |
| ToolRegistry (字段直写):— | mcp_client_manager.py:127-150 | MCP 管理器绕过 register_tool 直接写 function_info/function_mappings/openai_function_schemas |
| ToolRegistry.validate_tool_info:99 | connectors.py:200 | 连接器校验复用同一套 tool_info 诊断 |
| AsyncToolDispatcher.dispatch:295 | core.py:2091,2376 | run 主循环执行 LLM 选择的工具 |
| AsyncToolDispatcher.dispatch:295 | capabilities.py:640-641 | 能力系统 ToolCapabilityProvider 的执行后端 |
| ToolLoader.load_tool:240 | core.py:450 | Agent.load_tools 按名字加载 tools/ 目录工具 |
| errors.format_error_code / format_lightagent_error | tools.py:19 | 调度失败的统一 LA-TOOL 错误码 |

## 阅读陷阱

1. **同名工具静默覆盖**：register_tool 对同名工具直接覆盖三个视图并返回 True，不抛错；重复注册只有事后 `validate_tools` 才能诊断出来（L181-188）。
2. **生成器透传**：dispatch 对 async/sync 生成器"只返回不消费"，被注释掉的收集代码（L323-326、L330-332）是历史残留，别误以为 dispatch 会拼好完整字符串；真正逐 chunk 消费在 core.py:2105-2113（流式分支第二处 core.py:2413）。
3. **错误即字符串**：工具未找到/参数校验失败/执行异常都返回带 LA-TOOL 错误码的字符串，调用方无法用异常分支区分失败。
4. **`async_stream_generator`/`stream_generator` 目前无人调用**，core 是自己直接迭代 Generator 的。

## 高频符号中文短语表

- `ToolRegistry` (L27)：集中工具注册表，三视图同步
- `ToolRegistry.register_tool` (L37)：登记函数并生成 OpenAI 模式
- `ToolRegistry.validate_tool_info` (L99)：tool_info 静态诊断器
- `ToolRegistry.filter_tools` (L199)：按反思结果过滤工具集
- `ToolLoader` (L225)：tools 目录动态导入加载器
- `ToolLoader.load_tool` (L240)：按名加载并缓存单工具
- `AsyncToolDispatcher` (L282)：工具统一调度入口
- `AsyncToolDispatcher.dispatch` (L295)：查表校验后分派执行
- `_serialize_result` (L343)：任意结果转字符串
- `_validate_tool_params` (L352)：必填与类型前置校验
- `_matches_declared_type` (L379)：宽容的声明类型匹配

---

# builtin_tools/nos.py（LightAgent/builtin_tools/nos.py）

## 模块概览

内置"文件上传"工具：把本地文件上传到阿里云 OSS（走 boto3 的 S3 兼容协议 + v4 签名），默认用文件 MD5 重命名以实现幂等去重，可选保留原名、前缀目录、公共读 ACL。这是 builtin_tools 里唯一的云存储工具，Agent 构造时默认注册（core.py:273）。

## 类与符号清单

- `ALIYUN_OSS_CONFIG` (L8-L13)：模块级默认配置字典（占位密钥 + endpoint + bucket），建议由环境变量覆盖。
- `_get_oss_client` (L16-L49)：构造 boto3 S3 兼容客户端。
- `_calculate_md5` (L52-L66)：分块计算文件 MD5。
- `upload_file_to_oss` (L69-L166)：工具函数本体；tool_info 定义在 L170-L182。

## 关键方法

- `_get_oss_client` (L16) — 参数 > 模块配置兜底；AK/SK 缺失抛 ValueError 并提示环境变量 `ALIYUN_OSS_ACCESS_KEY_ID` / `ALIYUN_OSS_ACCESS_KEY_SECRET`（L34-35）；`import boto3` 延迟到调用时（L37，未安装则由上层 ImportError 分支兜住）；调用者：`upload_file_to_oss` (L121)。它调用：boto3.client（s3v4 签名）。
- `_calculate_md5` (L52) — 4096 字节分块流式哈希；调用者：upload_file_to_oss L111、L154。
- `upload_file_to_oss` (L69) — 完整上传流程（见下）；被 core.py:273 注册进 ToolRegistry，经 dispatch 由模型调用。

## 关键机制细节

### 上传流程 (L95-L157)

1. 前置检查：路径存在且是文件（L97-101），否则返回中文错误字符串。
2. 命名策略：`preserve_original_name=False`（默认）时以 MD5+原扩展名作为 OSS key（L108-112）——同名内容天然去重。
3. `prefix` 自动补 `/` 拼接完整 key（L115-117）。
4. `public_read=True` 时上传参数追加 `ACL: public-read`（L124-126）。
5. `client.upload_file` 上传后按 endpoint 拼 `{base_url}/{bucket}/{key}` 生成访问 URL（L138-144）。
6. 返回 JSON 字符串（success/file_url/bucket/key/original_filename/oss_filename/file_size/md5，L146-157）。

### 安全与限制

- **对模型只暴露 1 个参数**：tool_info 仅声明 `file_path`（L174-181）；bucket/AK/SK/endpoint 等敏感参数只能由代码侧传入或环境变量提供，模型无法指定目标桶。
- 源码中的 AK/SK 是占位星号（L9-10），不构成凭据泄漏。
- **无文件大小/类型限制、无路径白名单**——file_path 可以是宿主机任意可读文件（这是该工具的最大安全面）。
- ImportError 单独捕获，提示 `pip install boto3` 或 `LightAgent[oss]`（L159-164）。

## 与其他模块的关系

| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| upload_file_to_oss:69 | core.py:73（import）、core.py:273（注册） | Agent 构造时默认注册的内置工具 |
| upload_file_to_oss.tool_info:170 | tools.py ToolRegistry.register_tool:37 | 以"函数+tool_info"协议登记 |
| upload_file_to_oss:69 | AsyncToolDispatcher.dispatch:295 | 由 dispatch 按普通同步函数调用 |

## 阅读陷阱

1. **模型只能传 file_path**，其余参数虽在函数签名里但不在 tool_info 中——画架构图时不要把 bucket/endpoint 画成模型可控输入。
2. 默认 MD5 重命名意味着"上传后 OSS 上的文件名 ≠ 本地文件名"，看结果 JSON 里的 `oss_filename`/`file_url` 才是真实位置。
3. `public_read` 会把文件设为公共可读，且该能力对模型不可见、由代码侧决定。
4. boto3 是可选依赖，未安装时工具返回安装提示字符串而非报错崩溃。

## 高频符号中文短语表

- `ALIYUN_OSS_CONFIG` (L8)：OSS 默认配置占位字典
- `_get_oss_client` (L16)：建 S3 兼容客户端
- `_calculate_md5` (L52)：流式计算文件 MD5
- `upload_file_to_oss` (L69)：上传文件到阿里云 OSS

---

# builtin_tools/python_executor.py（LightAgent/builtin_tools/python_executor.py）

## 模块概览

内置"Python 代码执行"三件套（执行代码串 / 执行 .py 文件 / 流式执行），是框架中最重的内置工具：多层输入清洗（dict/JSON/markdown 代码块）→ AST 静态安全检查（黑名单模块、危险内置、动态派发逃逸）→ 临时目录隔离执行（可选独立 venv 装依赖）→ 超时与输出捕获。同时导出 `UNSAFE_PYTHON_TOOL_NAMES` 供 core 的沙箱策略门控。**默认不注册**，需 `enable_unsafe_python=True`（core.py:274-279），且运行期还需显式 SandboxProvider（core.py:1276-1299）。

## 类与符号清单

- `_DANGEROUS_MODULES` (L23-L36)：禁止 import 的模块黑名单（os/sys/socket/subprocess/ctypes/importlib/shutil/pickle/pty/glob/shelve/`__builtins__`）。
- `_DANGEROUS_BUILTINS` (L37)：禁止调用的内置（`__import__`/compile/eval/exec/input/open/raw_input）。
- `_DANGEROUS_ATTRIBUTES` (L38)：危险属性名（compile/eval/exec/popen/system）。
- `_PROCESS_ATTRIBUTES` (L39)：subprocess 进程 API 名（Popen/call/check_call/check_output/run）。
- `_DANGEROUS_DYNAMIC_ATTRIBUTES` (L40)：以上三类并集，用于 getattr/attrgetter 动态派发拦截。
- `UNSAFE_PYTHON_TOOL_NAMES` (L41-L45)：三个不安全工具名的 frozenset，供 core.py:71/1286 做 requires_sandbox 判定。
- `_parse_code_parameter` (L71-L121)：从 str/dict/list 等各种形态中提取代码串。
- `_clean_code_string` (L140-L202)：修复 JSON 转义/引号/双花括号/JSON 包装。
- `_extract_code_from_text` (L205-L233)：从 markdown 代码块/内联代码中提取代码。
- `_literal_string` (L236-L253)：AST 节点求字面字符串（常量、常量变量、字符串加法、纯字面 f-string）。
- `_resolved_name` (L256-L277)：解析调用目标的点分全名（考虑 import 别名、常量下标、getattr 派发）。
- `_dynamic_dispatch` (L280-L296)：识别 `getattr(x, "attr")` / `attrgetter("attr")(x)` 式动态属性访问。
- `_collect_static_bindings` (L299-L329)：收集 import 别名与字符串常量绑定（3 轮迭代求别名传递闭包）。
- `_safe_import_check` (L332-L397)：AST 静态安全检查核心，返回 (是否安全, 错误信息)。
- `_install_requirements` (L400-L448)：在目标 venv 里先升级 pip（60s 超时）再逐个装依赖（每个 120s 超时）。
- `execute_python_code` (L451-L574)：执行代码串；tool_info L724-L755。
- `execute_python_file` (L577-L612)：执行 .py 文件；tool_info L757-L789。
- `execute_python_code_stream` (L615-L720)：流式执行（生成器）；tool_info L791-L816。

## 关键方法

- `_parse_code_parameter` (L71) — dict 时按 code/script/python_code/source/content/program 键序提取（L90-98），单键 dict 直接取值（L100-104），list 全字符串则换行拼接（L115-116）；调用者：`execute_python_code` (L472)、`execute_python_code_stream` (L631)。
- `_clean_code_string` (L140) — 六步清洗（见陷阱）；调用者：execute_python_code L475、execute_python_code_stream L632。
- `_extract_code_from_text` (L205) — 优先 ```` ```python ```` 块，其次通用 ``` 块，再次内联反引号，全无则原文；调用者同上（L478、L633）。
- `_safe_import_check` (L332) — `ast.parse` 后遍历：Import/ImportFrom 根模块命中 `_DANGEROUS_MODULES` 拒绝（L346-354）；`from builtins import eval` 式拒绝（L355-358）；普通调用解析全名后比对危险名（L359-383）；getattr/attrgetter 动态派发拦截（L365-367、L372-378）；下标访问 `mod["Popen"]` 拦截（L385-388）；裸名字引用危险内置拦截（L390-393）；SyntaxError 视为不安全（L394-395）。调用者：execute_python_code L485、execute_python_code_stream L640。
- `_install_requirements` (L400) — subprocess 逐包装依赖，pip 升级 60s / 单包 120s 超时；调用者：execute_python_code L523、execute_python_code_stream L674。
- `execute_python_code` (L451) — 主执行路径：解析→清洗→提取→安全检查（任一步失败返回错误串）→ `tempfile.TemporaryDirectory(prefix="lightagent_python_")` 作工作目录（L490）→ 有 requirements 时在临时目录内建 venv 并装依赖（L500-525），否则用 `sys.executable`（L534）→ `subprocess.run(cmd, timeout=timeout, cwd=tmpdir, env={} if venv_path else os.environ.copy())`（L545-553）→ 拼接 stdout/stderr/退出码返回（L555-569）；TimeoutExpired 返回超时提示（L571-572）。调用者：core.py:66（import 注册）、`execute_python_file` (L612)。
- `execute_python_file` (L577) — 校验存在与 .py 后缀（L595-599）→ 读文件内容 → 注入 `sys.argv` 前导码支持 args（L609-610）→ 委托 execute_python_code。
- `execute_python_code_stream` (L615) — 同样的清洗/检查/venv 流程，但用 `subprocess.Popen` 行缓冲流式读 stdout（L688-707），按 `chunk_size`（默认 100 字符）攒块 yield；`process.wait(timeout)` 超时则 kill（L714-718）。是**同步生成器**工具，dispatch 会原样透传，core 逐 chunk 消费。

## 关键机制细节

### 代码执行沙箱的安全边界（超时/隔离/限制）

1. **静态 AST 黑名单**（_safe_import_check, L332-L397）：不是真沙箱，是"执行前源码审查"。覆盖了别名绕过（`import os as o`→别名解析 L303-309）、常量拼接绕过（`attr = "pop" + "en"`→常量传播 L299-329）、getattr/attrgetter 动态派发（L280-296）、下标取函数（L385-388）。
2. **文件系统隔离**：代码写入临时目录并在其中执行（cwd=tmpdir，L551/L695），执行完目录删除；但这只是工作目录隔离，代码本身仍能以相对/绝对路径触碰宿主文件系统——前提是绕过了 open 的黑名单。
3. **超时**：代码执行默认 30s（tool_info 声明，模型可传 timeout 参数）；依赖安装 pip 升级 60s、单包 120s；流式版 wait 超时后 kill 进程（L717）。
4. **环境隔离**：使用 venv 时子进程 `env={}` 清空环境变量（L552）——切断宿主凭据；无 venv 时继承完整 `os.environ`（注意：此时子进程能看到宿主所有环境变量，包括 API key）。
5. **依赖隔离**：requirements 会触发在临时目录里 `python -m venv` 新建虚拟环境（L503-509），Windows/Unix 分支取不同 pip/python 路径（L515-520）。
6. **框架层双重门控**：构造期需 `enable_unsafe_python=True` 才注册（core.py:274-279）；运行期 `_prepare_tool_call`（core.py:1276）检查工具名 ∈ UNSAFE_PYTHON_TOOL_NAMES 且无 SandboxProvider 时直接拒绝执行（requires_sandbox 判定在 core.py:1286）。
7. **明确不是容器级沙箱**：无 seccomp/namespace/资源限额，子进程与宿主共享内核与文件系统权限。

## 与其他模块的关系

| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| execute_python_code:451 / execute_python_file:577 / execute_python_code_stream:615 | core.py:66-72（import）、core.py:274-279（条件注册） | enable_unsafe_python 开关控制是否注册 |
| UNSAFE_PYTHON_TOOL_NAMES:40 | core.py:71、core.py:1286 | _prepare_tool_call 据此要求显式 SandboxProvider |
| execute_python_code_stream:615 | tools.py AsyncToolDispatcher.dispatch:327-329 | 同步生成器被 dispatch 透传，core.py:2105 逐 chunk 消费 |
| 三工具 tool_info:724/757/791 | tools.py ToolRegistry.register_tool:37 | 以"函数+tool_info"协议登记 |

## 阅读陷阱

1. **_clean_code_string 是有损清洗**（L157-169）：无条件把 `\\n→\n`、`\"→"`、`\\\\→\`——若模型生成的代码本意就是字面反斜杠序列（正则、Windows 路径），会被悄悄改坏。
2. **venv 与非 venv 两条路径的安全差异**：有 requirements 时子进程 env 为空（较干净），无 requirements 时继承完整宿主环境变量——后者反而更"暴露"。
3. **execute_python_file 没有目录限制**：file_path 可指向宿主任意 .py 文件，且会先读入内容再走代码串路径（等于绕过文件直接执行任意代码，仍受 AST 检查约束）。
4. AST 检查是黑名单而非能力白名单：合法代码可以自由做网络外的事只要不 import 黑名单模块（例如调用已注入的 C 扩展），不要在架构图上把它画成"安全沙箱"，应画成"静态审查 + 临时目录 + 超时"。

## 高频符号中文短语表

- `UNSAFE_PYTHON_TOOL_NAMES` (L41)：三个高风险工具名集合
- `_safe_import_check` (L332)：AST 静态危险导入审查
- `_collect_static_bindings` (L299)：收集别名与常量防绕过
- `_dynamic_dispatch` (L280)：识别 getattr 动态派发逃逸
- `_parse_code_parameter` (L71)：多形态代码参数提取
- `_clean_code_string` (L140)：转义与 JSON 包装清洗
- `_extract_code_from_text` (L205)：markdown 代码块提取
- `_install_requirements` (L400)：venv 内带超时装依赖
- `execute_python_code` (L451)：临时目录隔离子进程执行
- `execute_python_file` (L577)：读取并执行 py 文件
- `execute_python_code_stream` (L615)：Popen 流式执行代码

---

# builtin_tools/safe_expression.py（LightAgent/builtin_tools/safe_expression.py）

## 模块概览

内置"安全表达式计算"工具：一个**纯数据表达式**求值器——自写 AST 递归解释器，只允许常量、列表/元组/集合/字典字面量与白名单算术/一元/比较/布尔运算符，禁止名字、调用、属性访问，并施加节点数/集合长度/字符串长度/整数位宽四重资源上限。它不执行 Python、不触碰文件/网络/进程，是 Agent 构造时**默认注册**的两个内置工具之一（core.py:273），承担"算个数学式子"这类最低风险需求。

## 类与符号清单

- `SafeExpressionError` (L10-L11)：ValueError 子类，表达式超出安全子集时抛出。
- 资源上限常量 (L14-L17)：`_MAX_NODES=128`、`_MAX_COLLECTION_ITEMS=64`、`_MAX_STRING_LENGTH=4096`、`_MAX_INTEGER_BITS=4096`（防内存炸弹/大整数 DoS）。
- `_BINARY_OPERATORS` / `_UNARY_OPERATORS` / `_COMPARISON_OPERATORS` (L19-L44)：ast 运算符到 operator 函数的白名单映射（含 In/NotIn/Is/IsNot）。
- `_validate_value` (L47-L54)：对求值结果做长度/位宽校验。
- `_evaluate` (L57-L133)：递归求值核心。
- `evaluate_safe_expression` (L136-L146)：入口——parse(mode="eval") + 节点数检查 + 求值。
- `safe_expression` (L149-L155)：工具包装器（返回 repr 字符串）；tool_info L158-L170。

## 关键方法

- `_validate_value` (L47) — 按类型检查上限；调用者：`_evaluate` 各分支（L61、L69、L80、L86、L95）。
- `_evaluate` (L57) — 分派规则：Constant 仅允许 str/int/float/bool/None（L58-61）；List/Tuple/Set 长度受限（L63-69）；Dict 禁止 `**` 解包（L74-75）、键必须可哈希（L76-79）；UnaryOp/BinOp 只查白名单（L82-97）；BoolOp 手工实现 and/or 短路（L99-116）；Compare 支持链式比较、逐段短路（L118-131）；**其余一切节点抛 SafeExpressionError**（L133）。调用者：`evaluate_safe_expression` (L146) 及自身递归。
- `evaluate_safe_expression` (L136) — 校验非空字符串 → `ast.parse(expression, mode="eval")` → `ast.walk` 计节点数 >128 拒绝（L144-145）→ 求值；调用者：`safe_expression` (L152)。
- `safe_expression` (L149) — 工具外壳：捕获 SafeExpressionError 返回"安全表达式错误：…"字符串，成功返回 `repr(value)`；被 core.py:273 默认注册、经 dispatch 调用。

## 关键机制细节

### 安全边界

- **白名单而非黑名单**（与 python_executor 相反）：未知 AST 节点一律拒绝（L133），Name/Call/Attribute 节点根本不在处理分支里，天然无访问面。
- **资源上限**（L14-17）：AST 节点 ≤128（防超长表达式）、集合 ≤64 项、字符串 ≤4096 字符、整数 ≤4096 位（防 `9**9**9…` 位爆炸）。上限在**每次中间结果**上都检查（_validate_value 嵌在各分支里）。
- **无副作用**：不 import os/socket/subprocess，无任何 IO。

## 与其他模块的关系

| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| safe_expression:149 | core.py:74（import）、core.py:273（默认注册） | 常驻内置工具 |
| safe_expression.tool_info:158 | tools.py ToolRegistry.register_tool:37 | "函数+tool_info"协议登记 |
| safe_expression:149 | AsyncToolDispatcher.dispatch:334-339 | 同步普通函数路径，结果转字符串 |

## 阅读陷阱

1. **f-string 不支持**：JoinedStr 节点没进白名单，会命中 L133 兜底拒绝。
2. **除零/类型错会转成 SafeExpressionError**（L94-97、L126-129），工具层再转错误字符串——链路上没有任何裸异常逃出。
3. 返回值是 `repr()`，字符串结果会带引号（如 `'abc'`），与多数工具返回裸字符串不同。
4. 它与 python_executor 是**互补而非递进**关系：一个零执行面但只算数据，一个全功能但需沙箱门控。

## 高频符号中文短语表

- `SafeExpressionError` (L10)：安全子集越界异常
- `_evaluate` (L57)：白名单 AST 递归求值
- `evaluate_safe_expression` (L136)：入口解析与资源上限检查
- `safe_expression` (L149)：受限表达式计算工具

---

# skill_tools.py（LightAgent/skill_tools.py）

## 模块概览

技能系统的"工具外壳"工厂：`create_skill_tools(skill_manager)` 用闭包把 SkillManager 的四个操作（列技能/激活技能/执行脚本/读参考文档）包装成带 `tool_info` 的普通工具函数并返回列表，供 core 注册进 ToolRegistry。它是 SkillManager 与工具体系之间唯一的桥——模型不直接接触 SkillManager 对象，只通过这 4 个工具间接使用技能。

## 类与符号清单

- `create_skill_tools` (L13-L115)：唯一模块级函数（工厂），返回 4 个工具函数列表。

## 关键方法

- `list_skills` (L16-L32, tool_info L35-L40) — 遍历 `skill_manager.skills`，返回每个技能的 name/description/has_scripts/has_references/has_assets 的 JSON；无参数。它调用：SkillManager.skills（属性访问）。
- `activate_skill` (L42-L56, tool_info L58-L65) — 调 `skill_manager.activate_skill(skill_name)`，把技能 SKILL.md 的正文指令装入上下文；异常捕获为"激活技能失败"字符串。它调用：skills.py:activate_skill (L142)；调用点：模型经 dispatch，以及系统提示里引导模型主动调用（core.py:671）。
- `execute_skill_script` (L67-L79, tool_info L81-L90) — 调 `skill_manager.execute_script(skill_name, script_name, args)`；注意**无 try/except**，SkillManager 侧已把异常转为错误字符串。它调用：skills.py:execute_script (L177)。
- `read_skill_reference` (L92-L103, tool_info L105-L113) — 调 `skill_manager.read_reference(skill_name, ref_path)` 读取 references/ 下文档。它调用：skills.py:read_reference (L217)。
- 返回值 (L115) — `[list_skills, activate_skill, execute_skill_script, read_skill_reference]`。

## 关键机制细节

### 技能→工具注册流程（与 core/skills 协作）

1. core.py:264 构造 `SkillManager(skills_directories)`；core.py:291 `discover_skills()` 扫描各目录的 `SKILL.md` 仅载元数据。
2. core.py:296-303：若有技能，调 `create_skill_tools(self.skill_manager)` 工厂生成 4 个闭包工具，逐个 `tool_registry.register_tool(tool_func)` 并写入 `loaded_tools`。
3. core.py:667-671：`get_skills_xml()` 把技能元数据注入 system prompt 的 `<available_skills>`，并指示模型"需求匹配时先用 activate_skill 加载完整指令"——即**渐进式披露**：提示词只放元数据，正文按需经工具加载。

### 安全边界（委托给 SkillManager 实现）

路径穿越防护与脚本沙箱都在 skills.py 侧（见下节）；本模块闭包本身不做校验，只做参数透传。

## 与其他模块的关系

| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| create_skill_tools:13 | core.py:46（import）、core.py:297（调用） | Agent 构造时按技能发现结果创建工具 |
| list_skills:16 / activate_skill:42 / execute_skill_script:67 / read_skill_reference:92 | skills.py SkillManager 各方法 | 闭包捕获 skill_manager 实例做透传 |
| 4 个工具函数 | tools.py ToolRegistry.register_tool:37 | 以"函数+tool_info"协议登记 |
| activate_skill 工具:42 | core.py:671 系统提示引导 | 提示词明示模型先激活技能再执行 |

## 阅读陷阱

1. **没有 read_skill_asset 工具**：SkillManager 有 `read_asset` (skills.py:240) 但工厂没包装它——资源文件对模型不可直接读取（留给脚本用）。
2. 4 个工具的 tool_info 均无 `tool_title` 之外校验需求，`execute_skill_script` 的 `args` 是可选 array——模型不传时闭包默认 None。
3. 工厂模式意味着**每次 Agent 构造都产生新的函数对象**，同名工具跨 Agent 实例不共享（每个 Agent 有自己的 ToolRegistry）。
4. `list_skills` 返回的是注册表快照 JSON，技能冲突（同名遮蔽）信息不在此暴露，要看 `SkillManager.list_conflicts`。

## 高频符号中文短语表

- `create_skill_tools` (L13)：SkillManager 工具外壳工厂
- `list_skills` (L16)：列出技能元数据快照
- `activate_skill` (L42)：激活技能装入完整指令
- `execute_skill_script` (L67)：执行技能 scripts 脚本
- `read_skill_reference` (L92)：读取技能 references 文档

---

# skills.py（LightAgent/skills.py）

## 模块概览

技能系统的核心：`Skill` 数据类描述一个技能目录（含 SKILL.md 元数据 + 可选 scripts/references/assets 子目录），`SkillManager` 负责多目录技能发现（支持同名遮蔽与冲突记录）、YAML frontmatter 解析、按需激活（剥 frontmatter 取正文指令）、技能清单 XML 生成（注入系统提示）、以及脚本执行/参考文档/资源文件读取——后三者都带"根目录内"路径校验。技能被设计为**渐进式披露**：发现时只读元数据，激活时才载入全文。

## 类与符号清单

- `Skill` (L21-L31)：@dataclass（装饰器 L20），字段 name/description/path/instructions/has_scripts/has_references/has_assets/source_directory/precedence。
- `SkillManager` (L34-L274)：技能管理器。

## 关键方法

- `__init__` (L37) — `skills_directories`（默认 `["skills"]`）、`skills: Dict[str, Skill]`、`skill_conflicts` 列表、logger。
- `discover_skills` (L43) — 按目录顺序枚举子目录，找到含 `SKILL.md` 的目录则 `_load_skill_metadata`；记录 `source_directory` 与 `precedence`（目录序号）；**同名技能后者覆盖前者并把冲突记入 skill_conflicts**（L63-72，规则注释 "later skills_directories entry wins"）；单技能解析失败仅记 ERROR 日志不中断（L77-79）。调用者：core.py:291。它调用：`_load_skill_metadata` (L59)。
- `list_conflicts` (L83) — 返回遮蔽冲突的确定性诊断副本。
- `discover_project_instructions` (L87) — 自工作目录向上到根收集 AGENTS.md（默认），按根→叶拼接并限 100k 字符（超限抛 ValueError）；框架内无其他调用点（供外部/测试使用）。
- `_load_skill_metadata` (L110) — 正则剥 YAML frontmatter（L118）→ `yaml.safe_load` → 必填 name/description 校验（L125-126）→ 探测 scripts/references/assets 三个可选子目录（L129-131）→ 构造 Skill（不读正文）；调用者：discover_skills (L59)。
- `activate_skill` (L142) — 校验技能名存在 → 重读 SKILL.md → 正则剥 frontmatter 只留正文（L154）→ 存入 `skill.instructions` 并返回；调用者：skill_tools.py:53（activate_skill 工具）、knowledge.py:366 经能力适配器反射调用。
- `get_skills_xml` (L160) — 生成 `<available_skills><skill><name/><description/><location/>` XML 清单供系统提示；调用者：core.py:668。
- `execute_script` (L177) — 脚本执行（带沙箱，见下）；调用者：skill_tools.py:79。
- `read_reference` (L217) — references/ 根内路径校验（`is_relative_to`，L227）后读文本；调用者：skill_tools.py:103。
- `read_asset` (L240) — assets/ 根内路径校验（L250）后读**二进制**返回 bytes；无工具包装（见 skill_tools 陷阱）。它调用：无框架内调用点。
- `_log` (L256) — 兼容 LoggerManager 与标准 logging 的统一日志；调用者：本类各处。

## 关键机制细节

### 技能发现/加载流程

1. 多目录按序扫描（L49-53），每个候选必须是"目录 + SKILL.md"。
2. 元数据阶段零正文读取：frontmatter 解析失败或缺字段直接抛 ValueError（L120、L126），被 discover_skills 捕获记日志跳过。
3. 同名冲突：后目录优先（precedence 大者胜），被遮蔽者路径记入 `skill_conflicts`（L63-72），`list_conflicts` 可事后审计。

### 技能脚本沙箱（execute_script, L177-L215）

- **路径边界**：`scripts_root = Path(skill.path, "scripts").resolve()`，脚本路径 resolve 后必须 `is_relative_to(scripts_root)`（L183-188）——阻断 `../` 穿越。
- **执行隔离**：`tempfile.TemporaryDirectory()` 临时目录作为 cwd（L195-202）——脚本不能依赖技能目录内相对路径产物。
- **超时**：硬编码 `timeout=30`（L200），超时返回 "Script execution timeout (30s)"（L212-213）。
- **输出**：stdout + "STDERR:" 段拼接返回（L204-206），DEBUG 日志截断 200 字符（L209）。
- **无扩展名/解释器白名单**：直接 `[str(script_path)] + args` 执行（L197）——依赖文件自身的可执行位/shebang（Windows 下按关联打开，行为有平台差异）。

## 与其他模块的关系

| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| SkillManager:34 | core.py:45（import）、core.py:264（实例化） | 每个 Agent 持有自己的 SkillManager |
| discover_skills:43 | core.py:291 | 构造期自动发现 |
| get_skills_xml:160 | core.py:667-671 | 技能清单注入 system prompt |
| activate_skill:142 | skill_tools.py:53 | activate_skill 工具的后端 |
| execute_script:177 | skill_tools.py:79 | execute_skill_script 工具的后端 |
| read_reference:217 | skill_tools.py:103 | read_skill_reference 工具的后端 |
| Skill:21 | connectors.py:17（import）、connectors.py:249-252 | 连接器校验 Skill 实例的 name/description/path |
| SkillManager.skills / activate_skill | knowledge.py:363-367 | 能力适配器 skill.* 反射调用 |

## 阅读陷阱

1. **同名技能"后者赢"**：与直觉的"先到先得"相反，skills_directories 列表中靠后的目录会遮蔽靠前的（L69 规则字符串写明）；发现返回值 `discovered` 里**包含被遮蔽的 Skill 对象**，但 `self.skills` 字典里没有——统计数量时两处会不一致。
2. `activate_skill` 把正文缓存在 `skill.instructions` 属性上（L155），但没有工具能读它——`list_skills` 不返回 instructions，正文只经 activate_skill 的**返回值**进对话上下文。
3. `execute_script` 用 `subprocess.run([脚本路径])` 直接执行，30s 超时硬编码不可配；脚本若依赖自身目录下的文件会因 cwd=临时目录而找不到。
4. `discover_project_instructions` 与技能发现无关（读的是 AGENTS.md 链），名字里却带 discover——易与 discover_skills 混淆。

## 高频符号中文短语表

- `Skill` (L20)：技能元数据数据类
- `SkillManager` (L34)：技能发现/激活/执行管理器
- `discover_skills` (L43)：多目录扫描 SKILL.md 元数据
- `_load_skill_metadata` (L110)：解析 frontmatter 与可选目录
- `activate_skill` (L142)：剥头装正文按需激活
- `get_skills_xml` (L160)：生成技能清单 XML
- `execute_script` (L177)：临时目录+30s 超时跑脚本
- `read_reference` (L217)：根内校验读参考文档
- `read_asset` (L240)：根内校验读二进制资源
- `list_conflicts` (L83)：同名遮蔽冲突审计

---

# mcp_client_manager.py（LightAgent/mcp_client_manager.py）

## 模块概览

MCP（Model Context Protocol）客户端管理器：按 `mcpServers` 配置逐个建立到 MCP 服务器的会话（支持 stdio 子进程、SSE、Streamable HTTP 三种传输），`list_tools` 拉取远端工具清单，把每个远端工具适配成"带 tool_info 的 partial 包装函数"直接写入 ToolRegistry（含 OpenAI schema），并提供按需重连的工具调用通道、命名空间防冲突、错误记录（含 Bearer/sk- 凭据脱敏）。是框架连接外部工具生态的唯一出口。

## 类与符号清单

- `MCPClientManager` (L26-L284)：唯一类。
- 模块级导入 (L14-L20)：`ClientSession`/`StdioServerParameters`/`sse_client`/`stdio_client`；`streamablehttp_client` 旧版 SDK 缺失时置 None（L17-20 兼容降级）。

## 关键方法

- `__init__` (L29) — 持有 config（含 `mcpServers` 字典）、tool_registry 引用、`exit_stack`（AsyncExitStack 统一清理）、`server_sessions`（服务器名→ClientSession）、`last_mcp_errors`、`credential_provider`、`_registered_tools`（服务器名→公开工具名集合）、`_tool_owners`（工具名→服务器名）。
- `_create_session` (L40) — 建立单服务器会话（三种传输选择，见下节）；末尾 `session.initialize()`（L78）并登记 `server_sessions[server_name]`（L79）。调用者：`register_mcp_tool` (L100)、`call_tool` (L225)。它调用：streamablehttp_client / sse_client / stdio_client + ClientSession。
- `cleanup` (L81) — 关闭 exit_stack、清空 server_sessions、重建空栈；调用者：register_mcp_tool L162、call_tool L238/L246。
- `register_mcp_tool` (L88) — 注册主流程（见下节）；调用者：core.py:471（setup_mcp）、`refresh_tools` (L178/L185)。
- `refresh_tools` (L165) — 先摘除某服务器（或全部）已注册工具（从 registry 三个视图 + 两本账删除，L168-176），再重注册；指定单服务器时用"临时 disabled 标记"技巧只连一个（L179-187）。
- `_public_tool_name` (L189) — 计算公开工具名：默认裸原名；`namespace_tools` 开启或**与其他服务器的工具撞名**时用 `{namespace}__{tool}` 命名空间化（L192-197）。
- `_call_tool_wrapper` (L199) — partial 绑定的适配器：把模型 kwargs 转成 `call_tool(tool_name, arguments, target_server)`；调用者：register_mcp_tool L128（作为 function_mappings 的值，最终由 AsyncToolDispatcher.dispatch 调用）。它调用：`call_tool` (L201)。
- `call_tool` (L207) — 通用调用：筛启用的服务器（可按 target_server 过滤，L216-217）→ 每服务器按 `reconnect_attempts` 重试（L220-221）→ 无会话则 `_create_session`（L223-226）→ `list_tools` 确认工具存在 → `_validate_arguments` 必填校验 → `session.call_tool` 执行（L237）→ `cleanup()` 后返回 `{server, tool, result: result.content[0].text}`（L238-243）；全失败抛 ValueError（错误详情见 `_format_tool_not_found`，L250）。
- `_validate_arguments` (L252) — 只查 required 字段存在性（L254-257）。
- `_record_error` (L259) — 把服务器名/阶段/异常类型/脱敏消息记入 last_mcp_errors。
- `_format_tool_not_found` (L268) — 无错误时"未找到"；有错误时拼前 3 条 MCP 诊断（L272-278）——**把真实连接/执行失败与"工具不存在"区分开**。
- `_sanitize_error_message` (L281, staticmethod) — 正则抹掉 `Bearer xxx` 与 `sk-...` 凭据（L282-283）。

## 关键机制细节

### stdio 与 SSE（及 Streamable HTTP）两种/三种连接的差异 (L40-L79)

选择逻辑：先看 `config["transport"]` 是否为 streamable-http 系（L49-50）；否则 **有 `url` 键 → SSE**（L57），**有 `command` 键 → stdio**（L66）。

| 维度 | stdio (L67-L76) | SSE (L57-L65) | Streamable HTTP (L50-L56) |
|---|---|---|---|
| 配置键 | `command` + `args` + 可选 `env` | `url` + 可选 `headers` | `transport: "http"` + `url` + `headers` |
| 传输形态 | 本地子进程 stdin/stdout 管道（`StdioServerParameters` + `stdio_client`） | 远端 HTTP EventSource 长连接（`sse_client`） | 远端 HTTP 流式（`streamablehttp_client`） |
| 流对象 | `stdio, write = transport` 两元组（L74） | streams 直接解包给 ClientSession（L64） | `streams[:2]` 取前两个（L55） |
| headers/凭据 | **不支持**（credential_provider 注入的 headers 在 stdio 分支被忽略） | 支持，注入 headers（L42-48、L59-62） | 支持，同 SSE |
| 兼容性 | 全版本 MCP SDK | 全版本 | 旧 SDK 缺类时抛 RuntimeError（L51-52） |
| 典型用途 | 本地工具进程（文件系统、git 等） | 远端托管 MCP 服务 | 新版远端协议 |

credential_provider 统一注入点在 L42-48：`resolver(server_name, config)` 可同步可异步（`inspect.isawaitable` 判断），返回的 headers 合并进 config headers（仅对两个 HTTP 系传输生效）。

### 注册流程 (register_mcp_tool, L88-L163)

1. 清空 last_mcp_errors，筛出未 `disabled` 的服务器（L90-96）。
2. 逐服务器：`_create_session` → `session.list_tools()`（L100-101）。
3. 逐工具：`_public_tool_name` 算公开名 → 由 inputSchema 的 properties/required 构建 `tool_info["tool_params"]`（缺 type 默认 "string"，L118-124）→ **直接写** `tool_registry.function_info/function_mappings`（后者是 `partial(self._call_tool_wrapper, tool_name=原名, target_server=服务器)`，L127-132）→ 手工拼 OpenAI schema append 进 `openai_function_schemas`（L135-150）→ 记账 `_registered_tools`/`_tool_owners`（L151-152）。
4. 单工具/单服务器失败均 `_record_error` 后 continue，不中断整体（L155-160）。
5. **结尾调用 `cleanup()`**（L162）——注册完立即断开全部会话。

### 调用期连接策略

注册时建过的会话不保留：`call_tool` 每次发现无会话就现连（L223-226），调用完（无论成败）`cleanup()`（L238、L246）——**"一调一连一断"**，重试由 `reconnect_attempts` 控制。这意味着高频调用场景每调一次都付一次连接建立成本。

## 与其他模块的关系

| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| MCPClientManager:26 | core.py:44（import）、core.py:470（setup_mcp 实例化） | Agent.setup_mcp 持有 mcp_client |
| register_mcp_tool:88 | core.py:471 | setup_mcp 触发注册 |
| function_mappings 值 partial→_call_tool_wrapper:199 | tools.py AsyncToolDispatcher.dispatch:320-322 | 包装函数是协程，dispatch await 之 |
| 直写 function_info/mappings/schemas:127-150 | tools.py ToolRegistry:27 | 绕过 register_tool 的直写通道 |
| _public_tool_name:189 | tools.py ToolRegistry.function_mappings:32 | 撞名检测依据注册表现状 |
| refresh_tools:165 | 自身 register_mcp_tool:178/185 | 摘除后重注册 |

## 阅读陷阱

1. **注册完就断连**：register_mcp_tool 结尾 cleanup()（L162）会关掉刚建的所有会话，`self.session`/`server_sessions` 清空——别以为注册成功后会话还活着；真正调用靠 call_tool 现连。
2. **绕过 register_tool 直写注册表**（L127-150）：MCP 工具不走 ToolRegistry.register_tool，因此不触发其"同名覆盖"逻辑；撞名由 `_public_tool_name` 命名空间化解决，且只在"撞了别家"时加前缀。
3. **一个 self.session 字段服务多服务器**：`_create_session` 每次覆盖 `self.session`（L56/65/76），权威数据是 `server_sessions` 字典（L79）；看代码时别把 self.session 当成"当前唯一会话"。
4. inputSchema 解析很浅：嵌套 object/array 的子结构、enum 等都会丢失（只取顶层 type/description=L121-123 的 title），复杂参数的模型可见描述会失真；`result.content[0].text` 只取第一段内容（L242），多段 content 会被丢弃。

## 高频符号中文短语表

- `MCPClientManager` (L26)：MCP 服务器连接与工具桥接
- `_create_session` (L40)：三传输建会话并初始化
- `cleanup` (L81)：关闭全部 MCP 会话资源
- `register_mcp_tool` (L88)：拉取远端工具并登记注册表
- `refresh_tools` (L165)：摘旧注册后重连刷新
- `_public_tool_name` (L189)：撞名时加命名空间前缀
- `_call_tool_wrapper` (L199)：kwargs 转发的适配闭包
- `call_tool` (L207)：按需重连调用远端工具
- `_validate_arguments` (L252)：必填参数存在性校验
- `_record_error` (L259)：记录脱敏 MCP 诊断
- `_sanitize_error_message` (L281)：抹除 Bearer/sk- 凭据

---

# connectors.py（LightAgent/connectors.py）

## 模块概览

"连接器"是一份**纯元数据清单**（ConnectorManifest）：把现成的工具函数、技能、MCP 服务器配置、钩子、记忆适配器、可选依赖、本地文档打包成一个可声明、可离线校验的发布单元。`ConnectorValidator` 对清单做**零副作用**的静态校验（不启动 MCP 服务、不 import 可选 SDK、不执行任何工具/钩子），输出结构化的 ConnectorValidationReport（error/warning 诊断列表）。它复用 ToolRegistry 的 tool_info 诊断与 skills.Skill 类型，是扩展生态的"准入检查器"而非运行时组件。

## 类与符号清单

- 清单/诊断用正则与黑名单表 (L21-L58)：`_CONNECTOR_NAME_PATTERN`、`_VERSION_PATTERN`（语义版本）、`_EXTRA_NAME_PATTERN`、`_REQUIREMENT_PATTERN`、`_SECRET_FIELD_PATTERN`（api_key/token/secret/password/authorization）、`_PLACEHOLDER_PATTERN`（${}/{}/<...>/your_/replace_/env:）、`_UNSAFE_IMPORT_HINTS`（ctypes/importlib/os/pickle/pty/shutil/socket/subprocess 及风险说明）、`_NETWORK_IMPORT_HINTS`（aiohttp/httpx/requests/urllib）、`_HOOK_PHASES`（18 个生命周期钩子名）。
- `_as_tuple` (L61-L68)：把 None/单值/序列统一成 tuple（manifest 的 __post_init__ 用）。
- `ConnectorManifest` (L72-L94)：@dataclass(frozen)（装饰器 L71），字段 name/version/description/tools/skills/mcp_servers/hooks/memory_adapters/extras/docs；类 docstring 明示"构造或校验清单绝不启动 MCP 服务器、不导入可选 SDK、不调用工具或钩子"（L73-77）。
- `ConnectorDiagnostic` (L98-L116)：@dataclass(frozen)，单条诊断（connector/level/field/message/component）+ to_dict。
- `ConnectorValidationReport` (L120-L143)：@dataclass(frozen)，诊断集合 + `valid`/`errors`/`warnings` 属性 + to_dict。
- `ConnectorValidator` (L146-L351)：校验器（全部静态/实例小方法）。
- `validate_connector` (L354-L361)：模块级便捷入口，new 一个 Validator 跑 validate。

## 关键方法

- `ConnectorValidator.validate` (L152) — 类型守卫（非 Manifest 直接报错返回，L153-160）后依序调用 8 个校验子方法收集诊断；调用者：validate_connector (L361)。
- `_validate_identity` (L179) — name 匹配 `[A-Za-z][A-Za-z0-9._-]*`、version 语义版本、description 非空（warning 级）。
- `_validate_tools` (L188) — 每个工具必须可调用且有 tool_info；复用 `ToolRegistry.validate_tool_info`（L200）逐条转诊断；统计同名工具重复（L207-209）；随后调 `_validate_tool_source`。
- `_validate_tool_source` (L212) — `inspect.getsource` + `ast.parse` 静态扫描工具源码：import 命中 `_UNSAFE_IMPORT_HINTS`/`_NETWORK_IMPORT_HINTS` 发 warning（L229-242），动态 `__import__` 发 warning（L243-244）；解析失败静默跳过（L216-217）。
- `_validate_skills` (L246) — 接受 Skill 实例或本地路径字符串；统一解析到 base_path 下，检查 SKILL.md 文件真实存在（L261-263）。
- `_validate_mcp_servers` (L266) — 每个服务器配置必须**恰好**定义 `url` 或 `command` 之一（L277-280，两者都有/都无都报错）；stdio 的 args 必须是序列（L281-286）；递归扫密钥。
- `_scan_secrets` (L290) — 键名命中 `_SECRET_FIELD_PATTERN` 且值非占位符形式时发 warning"应使用环境/配置占位"（L297-299）。
- `_validate_hooks` (L302) — 钩子要么可调用，要么实现 `_HOOK_PHASES` 中至少一个生命周期方法（L303-308）。
- `_validate_memory_adapters` (L311) — 必须实现 `store(data, user_id)` 与 `retrieve(query, user_id)`（L317-320）。
- `_validate_extras` (L323) — extra 名与 pip requirement 串格式校验。
- `_validate_docs` (L338) — 无文档发 warning；远程 http(s) 文档发 warning"离线无法验证"；本地文档文件必须存在（L342-351）。

## 关键机制细节

### 离线校验的边界承诺

- 整个模块无网络/子进程/动态导入执行——校验只做：正则、AST 源码阅读（不执行）、文件存在性检查（L261、L347-351）。
- 诊断分级：error 使 `report.valid=False`（L127-128）；warning 不影响有效性。
- `base_path`（L149-150）决定相对路径（skills/docs）的解析根。

### 与 ToolRegistry / Skill 的复用关系

- 工具合法性完全复用 `ToolRegistry.validate_tool_info`（tools.py:99）——连接器不另立 tool_info 标准。
- Skill 实例来自 `skills.py:21`——校验其 name/description 非空与路径下 SKILL.md 存在。

## 与其他模块的关系

| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| ConnectorManifest.skills:83 | skills.py Skill:21 | 清单引用技能实例或路径 |
| _validate_tools→ToolRegistry.validate_tool_info:200 | tools.py ToolRegistry.validate_tool_info:99 | 复用工具元数据诊断 |
| ConnectorManifest.mcp_servers:84 | mcp_client_manager 的 mcpServers 配置 | 清单声明的服务器配置与 MCP 管理器消费的 config 同构（url/command/args/env） |
| ConnectorManifest.tools:82 | ToolRegistry.register_tool:37（经 core 装配） | 清单中的工具最终仍以"函数+tool_info"注册进 registry |
| ConnectorManifest.hooks:85 | hooks.py HookManager 生命周期阶段 | _HOOK_PHASES 名单与钩子系统阶段对应 |
| validate_connector:354 | __init__.py:66-70 | 顶层导出给外部打包者使用 |

## 阅读陷阱

1. **ConnectorManifest 不是运行时对象**：它不会自己"连上"任何东西——把 tools/skills/mcp_servers 真正装配进 Agent 仍是 core.py 的事，清单只是可校验的声明。
2. mcp_servers 校验强制"url 与 command 二选一"（L279-280）——同时给 url 和 command 是错误配置，这与 mcp_client_manager 的"先 transport 后 url 再 command"选择序不冲突但口径更严。
3. `_validate_tool_source` 的 import 扫描只发 **warning**（L229-244）：工具 import os/socket 不会让清单失效，只是提示"需用策略与隔离保护"。
4. AST 扫描的是 `inspect.getsource` 能拿到的源码——C 扩展、内置函数或 lambda 链上的工具拿不到源码时静默跳过（L216-217），不是零风险通过，是"无法审查"。

## 高频符号中文短语表

- `ConnectorManifest` (L71)：扩展组件声明式清单
- `ConnectorDiagnostic` (L97)：单条校验诊断
- `ConnectorValidationReport` (L119)：诊断汇总与 valid 判定
- `ConnectorValidator` (L146)：零副作用离线校验器
- `validate` (L152)：八项校验调度入口
- `_validate_tools` (L188)：工具可调用与元数据校验
- `_validate_tool_source` (L212)：工具源码 AST 风险扫描
- `_validate_mcp_servers` (L266)：url/command 二选一校验
- `_scan_secrets` (L290)：凭据占位符合规扫描
- `validate_connector` (L354)：清单校验便捷入口
