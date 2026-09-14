import os
import anthropic
from anthropic.types import MessageParam, ToolParam, ToolResultBlockParam

from datetime import datetime
from pprint import pprint

from build_context import build_context




def calculator(expression: str) -> int | float:
    """计算简单的数学表达式。仅用于本教程的固定示例。"""
    return eval(expression, {"__builtins__": {}}, {})


def get_current_time() -> str:
    """获取当前时间"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def read_file(file_path: str) -> str:
    """读取文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return f"错误：文件 {file_path} 未找到，请确认路径是否正确。"
    except Exception as e:
        return f"读取文件时发生错误：{e}"


TOOL_FUNCTIONS = {
    "calculator": calculator,
    "get_current_time": get_current_time,
    "read_file": read_file,
}

def print_messages(label: str, history: list[MessageParam]) -> None:
    """用容易阅读的格式完整打印当前对话历史。"""
    print(f"\n--- {label} ---")
    pprint(history, sort_dicts=False, width=100)


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
        "name": "read_file",
        "description": (
            "功能：读取指定 UTF-8 文本文件，并返回文件的完整内容。"
            "适用：当用户明确要求查看某个文本文件，或回答问题必须读取指定文件时使用。"
            "不适用：不要用于读取目录、二进制文件、用户未授权或与当前任务无关的敏感文件。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "要读取的文本文件路径，可以是相对路径或绝对路径，"
                        "例如：README.md。"
                    ),
                }
            },
            "required": ["file_path"],
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
        "content": "帮我算 12 * (3 + 4)，顺便查一下现在的时间",
    }
]

round_number = 0

while True:
    round_number += 1
    system, messages = build_context(messages)
    response = client.messages.create(
        model="deepseek-v4-flash",
        max_tokens=1024,
        system=system,
        tools=tools,
        messages=messages,
    )

    print(f"\n========== 第 {round_number} 轮模型响应 ==========")
    print("stop_reason:", response.stop_reason)
    
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
        #print_messages("最终对话历史", messages)
        break

    if response.stop_reason != "tool_use":
        raise RuntimeError(f"模型以未知原因结束：{response.stop_reason}")

    tool_results: list[ToolResultBlockParam] = []

    for block in response.content:
        if block.type == "text":
            print("[think] 模型边说边想：", block.text)
        elif block.type == "tool_use":
            print(f"[call] 模型要调用 {block.name}，参数 {block.input}")

            func = TOOL_FUNCTIONS[block.name]
            output = func(**block.input)

            print("[recv] 工具返回：", output)

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                }
            )

    # 工具结果必须回传对应的 tool_use_id，模型才能知道结果属于哪个请求。
    messages.append({"role": "user", "content": tool_results})
