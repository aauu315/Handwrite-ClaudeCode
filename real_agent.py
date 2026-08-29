import os

import anthropic


def calculator(expression: str):
    """计算简单的数学表达式。仅用于本教程的固定示例。"""
    return eval(expression, {"__builtins__": {}}, {})


tools = [
    {
        "name": "calculator",
        "description": "计算一个简单的数学表达式，例如 12 * (3 + 4)。",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的数学表达式",
                }
            },
            "required": ["expression"],
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

messages = [
    {
        "role": "user",
        "content": "帮我算 12 * (3 + 4)，再把结果加 100",
    }
]

while True:
    response = client.messages.create(
        model="deepseek-v4-flash",
        max_tokens=1024,
        tools=tools,
        messages=messages,
    )

    # 每一轮都把模型的完整输出保存到对话历史中。
    messages.append(
        {
            "role": "assistant",
            "content": [block.model_dump() for block in response.content],
        }
    )

    if response.stop_reason == "end_turn":
        for block in response.content:
            if block.type == "text":
                print("最终回答：", block.text)
        break

    if response.stop_reason != "tool_use":
        raise RuntimeError(f"模型以未知原因结束：{response.stop_reason}")

    tool_results = []

    for block in response.content:
        if block.type == "text":
            print("[think] 模型边说边想：", block.text)
        elif block.type == "tool_use":
            print(f"[call] 模型要调用 {block.name}，参数 {block.input}")

            if block.name != "calculator":
                raise RuntimeError(f"未知工具：{block.name}")

            output = calculator(**block.input)
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
