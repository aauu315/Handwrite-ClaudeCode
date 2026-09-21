import os
import traceback
import anthropic
from anthropic.types import MessageParam, ToolParam, ToolResultBlockParam, Message

from datetime import datetime
from pprint import pprint

from build_context import build_context
import file_tools
import shell_tools
from permissions import ask_user, check_permission
from tool_errors import ToolError



def calculator(expression: str) -> int | float:
    """计算简单的数学表达式。仅用于本教程的固定示例。"""
    return eval(expression, {"__builtins__": {}}, {})


def get_current_time() -> str:
    """获取当前时间"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

MAX_AGENT_ROUNDS: int | None = None
COMPRESSION_TRIGGER_TOKENS = 30_000
KEEP_RECENT_MESSAGES = 4
SUMMARY_MODEL = "deepseek-v4-flash"

COMPRESSION_PROMPT = """
你正在压缩一段 Agent 的较早对话历史。

请只输出一段简洁、准确、可以供 Agent 继续工作的摘要，不要继续执行任务。

摘要必须保留：
1. 用户最初的目标和后来补充的要求。
2. 用户明确提出的限制、偏好和禁止事项。
3. 已经查明的关键事实和已经作出的决定。
4. 已经读取或修改过的重要文件及其作用。
5. 已经执行的重要命令、结果和错误。
6. 已经完成的工作。
7. 尚未完成的事项和下一步应该做什么。

不要编造历史中没有的信息。
可以删除寒暄、重复解释、已经被证明无效的尝试和冗长工具输出。
"""

TOOL_FUNCTIONS = {
    "calculator": calculator,
    "get_current_time": get_current_time,
    "list_files": file_tools.list_files,
    "read_file": file_tools.read_file,
    "write_file": file_tools.write_file,
    "edit_file": file_tools.edit_file,
    "run_shell": shell_tools.run_shell,
}


def run_tool(tool_name: str, tool_input: dict) -> tuple[str, bool]:
    """执行已经通过权限检查的工具，并把意外异常转换为失败结果。"""
    try:
        func = TOOL_FUNCTIONS[tool_name]
        output = func(**tool_input)
        return str(output), False
    except ToolError as error:
        return str(error), True
    except Exception:
        error_traceback = traceback.format_exc()
        return (
            f"工具 '{tool_name}' 执行时发生异常：\n{error_traceback}",
            True,
        )


def print_messages(label: str, history: list[MessageParam]) -> None:
    """用容易阅读的格式完整打印当前对话历史。"""
    print(f"\n--- {label} ---")
    pprint(history, sort_dicts=False, width=100)


def response_token_count(response: Message) -> int:
    """返回一次模型调用的输入和输出 token 总数。"""
    return response.usage.input_tokens + response.usage.output_tokens


def contains_tool_result(message: MessageParam) -> bool:
    """判断一条消息中是否包含工具执行结果。"""
    content = message["content"]

    if isinstance(content, str):
        return False

    return any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def compress_messages(
    history: list[MessageParam],
    current_tokens: int,
) -> tuple[list[MessageParam], int]:
    """超过触发线时，将较旧历史压缩成一条摘要消息。"""
    if current_tokens < COMPRESSION_TRIGGER_TOKENS:
        return history, 0

    if len(history) <= KEEP_RECENT_MESSAGES:
        return history, 0

    cut_index = len(history) - KEEP_RECENT_MESSAGES

    # 不要把 assistant 的 tool_use 和紧随其后的 user tool_result 分开。
    if contains_tool_result(history[cut_index]):
        cut_index -= 1

    if cut_index <= 0:
        return history, 0

    old_messages = history[:cut_index]
    recent_messages = history[cut_index:]

    summary_response: Message = client.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=1024,
        system=COMPRESSION_PROMPT,
        messages=old_messages,
    )

    summary_text = "\n".join(
        block.text
        for block in summary_response.content
        if block.type == "text"
    ).strip()

    if not summary_text:
        raise RuntimeError("上下文压缩失败：模型没有返回摘要文本。")

    summary_message: MessageParam = {
        "role": "user",
        "content": (
            "以下是较早对话的压缩摘要。请把它当作已发生的历史，"
            "继续完成尚未结束的任务：\n\n"
            f"{summary_text}"
        ),
    }

    compressed_history = [summary_message, *recent_messages]
    compression_tokens = response_token_count(summary_response)

    print(
        f"[compact] 已将 {len(old_messages)} 条旧消息压缩成 1 条摘要，"
        f"保留最近 {len(recent_messages)} 条原始消息。"
    )
    print(f"[compact] 压缩后共有 {len(compressed_history)} 条消息。")
    print(f"[compact] 摘要调用消耗 {compression_tokens} tokens。")
    print("[compact] 摘要内容：")
    print(summary_text)

    return compressed_history, compression_tokens


tools: list[ToolParam] = [
    {
        "name": "calculator",
        "description": (
            "功能：计算由数字、括号和基础算术运算符组成的简单数学表达式。"
            "适用：当用户明确要求进行数值计算，或完成任务需要得到准确的算术结果时使用。"
            "不适用：不要用于查询时间、读取文件、解释数学概念或处理非算术任务。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的数学表达式字符串，例如：12 * (3 + 4)。",
                }
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_current_time",
        "description": (
            "功能：返回运行此程序的计算机当前本地日期和时间。"
            "适用：当用户询问现在几点、今天的日期，或任务需要当前本地时间时使用。"
            "不适用：不要用于查询历史时间、未来时间、其他时区时间或进行日期推算。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_files",
        "description": (
            "功能：按glob模式列出工作区里的文件名，例如'*.py'、[**/*.md'。只返回文件名，不读内容。"
            "适用：想知道有哪些文件、文件在哪时用它。"
            "不适用：不要用于读取文件内容、执行文件或访问工作区外的路径。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "要匹配的文件名模式，可以使用通配符，"
                        "例如：*.py、**/*.md。"
                    ),
                }
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "功能：读取指定 UTF-8 文本文件，并返回文件的完整内容。想改一个文件之前必须先读一遍，否则会被edit_file拒绝。"
            "适用：当用户明确要求查看某个文本文件，或回答问题必须读取指定文件时使用。"
            "不适用：不要用于读取目录、二进制文件、用户未授权或与当前任务无关的敏感文件。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "要读取的文本文件路径，可以是相对路径或绝对路径，"
                        "例如：README.md。"
                    ),
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "功能：将指定内容写入 UTF-8 文本文件，新建或覆盖原有内容。"
            "适用：当用户明确要求创建新文件或完全重写小规模文件时使用。"
            "不适用：不要用于编辑文件的部分内容，需要进行部分编辑时请使用 edit_file"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "要写入的文本文件路径，可以是相对路径或绝对路径，"
                        "例如：output.txt。"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "要写入文件的文本内容。"
                    ),
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "功能：在已读取的文本文件中查找指定字符串，并将其替换为新的字符串。"
            "适用：当用户明确要求修改文件内容，或任务需要更新文件中的特定文本时使用。"
            "不适用：不要用于编辑未读取的文件、二进制文件或用户未授权的敏感文件。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "要编辑的文本文件路径，可以是相对路径或绝对路径，"
                        "例如：config.txt。"
                    ),
                },
                "old_string": {
                    "type": "string",
                    "description": (
                        "要替换的旧字符串，必须在文件中唯一出现。"
                    ),
                },
                "new_string": {
                    "type": "string",
                    "description": (
                        "用于替换的新的字符串。"
                    ),
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "run_shell",
        "description": (
            "功能：在当前项目目录中执行一条系统命令，"
            "返回退出码、标准输出和标准错误。"
            "适用：运行测试、执行脚本、检查项目状态，"
            "以及验证代码修改是否正确。"
            "判断：退出码 0 通常表示成功；非 0 表示失败，"
            "失败时应先阅读标准错误，再决定下一步。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "要执行的完整命令，例如 pytest、"
                        "python example.py。"
                    ),
                }
            },
            "required": ["command"],
        },
    }

]


if not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError(
        "没有找到 ANTHROPIC_API_KEY。请先在当前终端设置 DeepSeek API Key。"
    )


client = anthropic.Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    # 显式指定 DeepSeek 的 Anthropic 兼容地址，不使用其他全局 base URL。
    base_url="https://api.deepseek.com/anthropic",
)

messages: list[MessageParam] = [
    {
        "role": "user",
        "content": input("请输入你的问题或任务描述："),
    }
]

round_number = 0
current_tokens = 0
total_tokens = 0

if MAX_AGENT_ROUNDS is not None and MAX_AGENT_ROUNDS <= 0:
    raise ValueError("MAX_AGENT_ROUNDS 必须是正整数或者 None。")

while True:
    round_number += 1

    messages, compression_tokens = compress_messages(
        messages,
        current_tokens,
    )
    total_tokens += compression_tokens

    system, messages = build_context(messages)
    response: Message = client.messages.create(
        model="deepseek-v4-flash",
        max_tokens=1024,
        system=system,
        tools=tools,
        messages=messages,
    )

    current_tokens = response_token_count(response)
    total_tokens += current_tokens

    print(f"\n========== 第 {round_number} 轮模型响应 ==========")
    print("stop_reason:", response.stop_reason)
    print("当前轮 token 用量:", current_tokens)
    print("本次会话累计 token 用量:", total_tokens)
    
    # 每一轮都把模型的完整输出保存到对话历史中。
    messages.append(
        {
            "role": "assistant",
            "content": response.content,
        }
    )

    if response.stop_reason == "end_turn":
        for block in response.content:
            if block.type == "text":
                print("最终回答：", block.text)
        #print_messages("\n最终对话历史", messages)
        break

    elif response.stop_reason == "max_tokens":
        print_messages("\n当前对话历史", messages)
        print("[警告] 单轮回应达到最大tokens，模型输出被截断，可能未完成回答。")
        break

    if response.stop_reason != "tool_use":
        print_messages("\n最终对话历史", messages)
        raise RuntimeError(f"模型以未知原因结束：{response.stop_reason}")
        
    tool_results: list[ToolResultBlockParam] = []

    for block in response.content:
        if block.type == "text":
            print("[think] 模型边说边想：", block.text)
        elif block.type == "tool_use":
            print(f"[call] 模型要调用 {block.name}，参数 {block.input}")

            decision = check_permission(block.name, block.input)
            is_error = False

            if decision == "deny":
                output = (
                    "这次工具调用已被安全策略拒绝。"
                    "请不要重复尝试同一种危险操作，请改用更安全的做法。"
                )
                is_error = True
            elif decision == "confirm" and not ask_user(
                block.name, block.input
            ):
                output = (
                    "用户拒绝了这次工具调用。"
                    "请不要重复尝试同一种操作，请改用更安全的做法。"
                )
                is_error = True
            else:
                output, is_error = run_tool(block.name, block.input)

            print("[recv] 工具返回：", output)

            tool_result: ToolResultBlockParam = {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(output),
            }
            if is_error:
                tool_result["is_error"] = True
            tool_results.append(tool_result)

    # 工具结果必须回传对应的 tool_use_id，模型才能知道结果属于哪个请求。
    messages.append({"role": "user", "content": tool_results})

    if MAX_AGENT_ROUNDS is not None and round_number >= MAX_AGENT_ROUNDS:
        print("达到最大执行轮数，任务尚未完成。")
        print_messages("当前对话历史", messages)
        break
