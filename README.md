# Handwrite Claude Code

一个跟随教程学习、逐步手写简化版 Claude Code Agent 的练习项目：从零实现「模型 → 工具调用 → 工具结果 → 模型继续」的完整 Agent 循环，并补上权限确认、上下文压缩、子 Agent、长期记忆等工程细节。

## 学习来源

参考 Bilibili 教程：[《手写一个 Claude Code》](https://www.bilibili.com/video/BV1Ycup6VEvG/)。

仓库内容是学习过程中自己写的练习代码，不是教程作者的官方仓库。

## 功能特性

- **真实 Agent 循环**：调用 DeepSeek 的 Anthropic 兼容接口，支持多轮工具调用。
- **流式输出**：模型回复逐字打印，`Ctrl+C` 可中断生成，半截回复不写入历史。
- **权限系统**：按工具类型自动放行 / 询问用户 / 硬拒绝。
- **工具注册表**：每个工具集中声明函数、描述、参数 schema 和权限类型。
- **上下文压缩**：历史超过 token 阈值时，自动把旧消息压缩成摘要再继续。
- **子 Agent**：主 Agent 可以派出只读调查员，只把结论带回主对话。
- **长期记忆**：把跨会话有用的约定写入 `memory/MEMORY.md`，并自动注入系统提示。
- **路径与命令护栏**：文件操作限制在工作目录内，只允许读取过的文件被编辑，shell 命令有白名单和超时。

## 目录结构

```text
.
├── real_agent.py       # Agent 主循环、上下文压缩、子 Agent、交互入口
├── build_context.py    # 组装系统提示：人设 + 工作目录 + 当前时间 + 长期记忆
├── tool_registry.py    # 工具注册表与全部内置工具声明
├── file_tools.py       # 文件读写、目录列举、长期记忆读写
├── shell_tools.py      # 执行系统命令
├── permissions.py      # 参数校验与权限决策
├── path_access.py      # 路径解析、工作区边界与读取/修改授权
├── tool_errors.py      # 可预期错误的统一异常类型
├── memory/MEMORY.md    # 长期记忆文件
└── tests/              # pytest 单元测试
```

## 模块说明

### real_agent.py

- `AgentState`：记录当前轮次、本会话单轮 token 和累计 token 用量。
- `run_agent_loop()`：核心循环。每轮先做上下文压缩，再组装 system 并流式请求模型，然后按 `stop_reason` 分派：
  - `end_turn`：返回最终文字；
  - `tool_use`：执行工具、回填 `tool_result` 后继续下一轮；
  - `max_tokens`：尽力执行已产出的工具调用，然后提示输出被截断并结束；
  - 其他：打印历史并报错。
- `execute_tool_uses()`：统一做权限检查、用户确认和工具执行，为每个调用生成对应结果。
- `run_tool()`：把 `ToolError` 和意外异常都转换成模型可读的失败结果，保留完整 traceback。
- `compress_messages()`：超过 `COMPRESSION_TRIGGER_TOKENS` 时，把较早历史交给摘要模型压缩成一条消息，仅保留最近 `KEEP_RECENT_MESSAGES` 条原始消息，并避免拆开 `tool_use` 与紧随其后的 `tool_result`。
- `spawn_agent()`：用全新历史运行只读调查员，工具集由注册表自动筛出，最多 `CHILD_MAX_ROUNDS` 轮，失败时返回 `ToolError`。
- `main()`：多轮对话入口，处理中断后的补充要求或重新评估。

### tool_registry.py

`ToolSpec` 描述一个工具（`name`、`function`、`permission`、`description`、`input_schema`）。注册时校验名称唯一、函数可调用、权限类型合法、schema 必须是对象。提供的查询方法有：

- `get_tool()`：按名称取工具；
- `get_all_tool_names()`：主 Agent 可用工具；
- `get_read_only_tool_names()`：只读工具，用于子 Agent 白名单；
- `get_tool_definitions()`：生成发送给模型的工具声明，可按权限范围筛选。

### 其他模块

- `file_tools.py`：`list_files()` 按 glob 列文件名；`read_file()` 带行号输出，一次最多 400 行；`write_file()` 自动建目录；`edit_file()` 要求目标字符串唯一出现且文件已被读过；路径一律经 `path_access.py` 解析并限制在工作区内；`read_memory()` / `write_memory()` 维护带日期的 `memory/MEMORY.md`。
- `shell_tools.py`：`run_shell()` 在当前工作目录执行命令，30 秒超时，返回退出码、标准输出与标准错误，非 0 退出码抛 `ToolError`。
- `permissions.py`：见下方权限模型。
- `path_access.py`：解析相对/绝对路径、判定目标是否在工作区内，并负责工作区外读取授权与文件修改确认。
- `build_context.py`：拼接系统提示，长期记忆以「可能过期」的提示附加在最后。
- `tool_errors.py`：`ToolError`，表示可预期、能直接讲给模型听的业务错误。

## 内置工具

| 工具 | 权限类型 | 作用 |
| --- | --- | --- |
| `calculator` | read_only | 计算简单数学表达式（教学用） |
| `get_current_time` | read_only | 返回本机当前日期时间 |
| `list_files` | read_only | 按 glob 模式列出工作区文件 |
| `read_file` | read_only | 读取 UTF-8 文本文件 |
| `read_memory` | read_only | 读取长期记忆原文 |
| `write_file` | mutating | 新建或整体覆盖文件 |
| `edit_file` | mutating | 对已读文件做唯一匹配替换 |
| `write_memory` | mutating | 追加一条长期记忆 |
| `run_shell` | shell | 执行系统命令 |
| `spawn_agent` | delegate | 派出只读调查员子 Agent |

## 权限模型

每次工具调用都经过 `check_tool_call()` 的三步检查：

1. **工具与范围**：工具未注册、或不在当前 Agent 允许的名单里 → 直接拒绝。
2. **参数校验**：用签名绑定和类型注解检查参数是否完整、类型是否正确，不合法则标记为 `invalid`。
3. **操作权限**：按 `permission` 字段决策。

| 权限类型 | 决策 |
| --- | --- |
| `read_only` | 自动允许 |
| `delegate` | 自动允许（子 Agent 自身只能拿到只读工具） |
| `mutating` | 弹窗询问用户 |
| `shell` | 命中硬拒绝名单 → 拒绝；命中安全命令白名单 → 允许；其余 → 询问用户 |

确认环节只有明确输入 `y` 或 `yes` 才放行，被拒绝时会把「请改用更安全的做法」回传给模型。

`write_file` 与 `edit_file` 的确认不发生在分发层：`check_permission()` 对它们直接返回 `allow`，真正写盘前由 `path_access.request_write()` 逐次询问，避免同一操作被询问两次。

## 运行环境

- Python 3.13 或更高版本
- [uv](https://docs.astral.sh/uv/)
- 一个 DeepSeek API Key

依赖（`anthropic`、`python-dotenv`）由 `pyproject.toml` 管理：

```text
uv sync
```

在项目根目录创建 `.env`：

```text
ANTHROPIC_API_KEY=你的DeepSeek_API_Key
```

启动前会加载 `.env` 并强制要求该变量存在；DeepSeek 的 Anthropic 兼容地址 `https://api.deepseek.com/anthropic` 已写死在 `real_agent.py` 中，不会读取其他全局 base URL 配置。

启动：

```text
uv run python real_agent.py
```

之后直接输入问题或任务，输入空行退出。生成过程中按 `Ctrl+C` 可以中断，中断后可以补充要求，或直接回车让模型重新评估。

## 安全说明

- **API Key 只放在 `.env`**，不要写进代码或提交到仓库。
- `calculator` 使用受限 `eval`，只是教学示例，不要用于不可信输入。
- shell 白名单和硬拒绝名单是教学用的最低限度护栏，不是完整的危险命令识别器。
- `run_shell` 使用 `shell=True`，只适合在本地学习和受控环境使用。
- 工具的写操作会有确认步骤，但仍建议在 Git 仓库中运行，方便回滚。

## 测试

```text
uv run pytest
```

## 学习计划

1. 完整看完《手写一个 Claude Code》课程。
2. 按课程进度逐节补充和重构代码。
3. 在理解 Agent 循环、工具调用和对话历史后，独立完成一个可实际使用的 Agent Demo。

项目仍处于学习阶段，接口和目录结构可能继续调整。
