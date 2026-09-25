import os
import traceback
from dataclasses import dataclass
from pathlib import Path
import anthropic
from dotenv import load_dotenv
from anthropic.types import (
    Message,
    MessageParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlock,
)

from pprint import pprint

from build_context import build_context
from permissions import ask_user, check_tool_call
from tool_errors import ToolError
from tool_registry import (
    ToolSpec,
    get_all_tool_names,
    get_read_only_tool_names,
    get_tool,
    get_tool_definitions,
    register_spawn_agent,
)

MAX_AGENT_ROUNDS: int | None = None
CHILD_MAX_ROUNDS = 10
COMPRESSION_TRIGGER_TOKENS = 30_000
KEEP_RECENT_MESSAGES = 4
SUMMARY_MODEL = "deepseek-v4-flash"


@dataclass
class AgentState:
    round_number: int = 0
    current_tokens: int = 0
    total_tokens: int = 0


class GenerationInterrupted(Exception):
    """表示用户中断了当前 Agent 的执行。"""

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

def run_tool(tool: ToolSpec, tool_input: dict) -> tuple[str, bool]:
    """执行已经通过权限检查的工具，并把意外异常转换为失败结果。"""
    try:
        output = tool.function(**tool_input)
        return str(output), False
    except GenerationInterrupted:
        raise
    except ToolError as error:
        return str(error), True
    except Exception:
        error_traceback = traceback.format_exc()
        return (
            f"工具 '{tool.name}' 执行时发生异常：\n{error_traceback}",
            True,
        )


def execute_tool_uses(
    tool_use_blocks: list[ToolUseBlock],
    allowed_tool_names: set[str],
) -> tuple[list[ToolResultBlockParam], bool]:
    """统一检查并执行一组工具调用，为每个调用生成对应结果。"""
    tool_results: list[ToolResultBlockParam] = []
    interrupted_during_tool = False

    for block in tool_use_blocks:
        print(f"[call] 模型要调用 {block.name}，参数 {block.input}")

        try:
            if interrupted_during_tool:
                output = "前一个工具调用已被中断，本工具没有执行。"
                is_error = True
            else:
                tool = get_tool(block.name)
                decision, reason = check_tool_call(
                    tool,
                    block.input,
                    allowed_tool_names,
                )

                if decision in {"deny", "invalid"}:
                    output = reason
                    is_error = True
                elif decision == "confirm" and not ask_user(
                    block.name,
                    block.input,
                ):
                    output = (
                        "用户拒绝了这次工具调用。"
                        "请不要重复尝试同一种操作，请改用更安全的做法。"
                    )
                    is_error = True
                else:
                    if tool is None:
                        raise RuntimeError("权限检查允许了一个未注册的工具。")
                    output, is_error = run_tool(tool, block.input)
        except GenerationInterrupted:
            output = "用户中断了子 Agent 的生成。"
            is_error = True
            interrupted_during_tool = True
        except KeyboardInterrupt:
            output = (
                "用户中断了工具执行。工具可能已经产生了部分外部效果，"
                "继续前应先检查当前状态。"
            )
            is_error = True
            interrupted_during_tool = True

        print("[recv] 工具返回：", output)

        tool_result: ToolResultBlockParam = {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": str(output),
        }
        if is_error:
            tool_result["is_error"] = True
        tool_results.append(tool_result)

    return tool_results, interrupted_during_tool


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


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError(
        "没有找到 ANTHROPIC_API_KEY。请在项目根目录的 .env 中设置 DeepSeek API Key。"
    )


client = anthropic.Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    # 显式指定 DeepSeek 的 Anthropic 兼容地址，不使用其他全局 base URL。
    base_url="https://api.deepseek.com/anthropic",
)

def run_agent_loop(
    messages: list[MessageParam],
    available_tools: list[ToolParam],
    allowed_tool_names: set[str],
    max_rounds: int | None,
    state: AgentState | None = None,
) -> str | None:
    """运行一份独立的对话历史，完成时返回最终文字。"""
    if max_rounds is not None and max_rounds <= 0:
        raise ValueError("max_rounds 必须是正整数或者 None。")

    if state is None:
        state = AgentState()

    while True:
        state.round_number += 1

        compressed_messages, compression_tokens = compress_messages(
            messages,
            state.current_tokens,
        )
        messages[:] = compressed_messages
        state.total_tokens += compression_tokens

        system, messages = build_context(messages)

        print(f"\n========== 第 {state.round_number} 轮模型响应 ==========")

        printed_text = False

        try:
            with client.messages.stream(
                model="deepseek-v4-flash",
                max_tokens=1024,
                system=system,
                tools=available_tools,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
                    printed_text = True

                response: Message = stream.get_final_message()
        except KeyboardInterrupt as error:
            if printed_text:
                print()

            print("[中断] 当前生成已停止，半截回复没有写入对话历史。")
            raise GenerationInterrupted from error

        if printed_text:
            print()

        state.current_tokens = response_token_count(response)
        state.total_tokens += state.current_tokens
        
        print("stop_reason:", response.stop_reason)
        

        if response.stop_reason == "max_tokens":
            tool_use_blocks = [
                block
                for block in response.content
                if block.type == "tool_use"
            ]

            if tool_use_blocks:
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                    }
                )

                tool_results, interrupted_during_tool = execute_tool_uses(
                    tool_use_blocks,
                    allowed_tool_names,
                )

                messages.append(
                    {
                        "role": "user",
                        "content": tool_results,
                    }
                )

                if interrupted_during_tool:
                    raise GenerationInterrupted

            print_messages("\n当前对话历史", messages)
            print("[警告] 单轮回应达到最大tokens，模型输出被截断，可能未完成回答。")
            return None


        # 每一轮都把模型的完整输出保存到对话历史中。
        messages.append(
            {
                "role": "assistant",
                "content": response.content,
            }
        )

        if response.stop_reason == "end_turn":
            final_text = "\n".join(
                block.text
                for block in response.content
                if block.type == "text"
            ).strip()
            #print_messages("当前对话历史", messages)
            return final_text

        if response.stop_reason != "tool_use":
            print_messages("\n最终对话历史", messages)
            raise RuntimeError(f"模型以未知原因结束：{response.stop_reason}")

        tool_use_blocks = [
            block
            for block in response.content
            if block.type == "tool_use"
        ]
        tool_results, interrupted_during_tool = execute_tool_uses(
            tool_use_blocks,
            allowed_tool_names,
        )

        # 工具结果必须回传对应的 tool_use_id，模型才能知道结果属于哪个请求。
        messages.append({"role": "user", "content": tool_results})

        print("当前轮 token 用量:", state.current_tokens)
        print("本次会话累计 token 用量:", state.total_tokens)

        if interrupted_during_tool:
            raise GenerationInterrupted
        
        if max_rounds is not None and state.round_number >= max_rounds:
            print("达到最大执行轮数，任务尚未完成。")
            print_messages("当前对话历史", messages)
            return None


def spawn_agent(task: str) -> str:
    """用全新历史运行一名只读调查员，只返回最终结论。"""
    if not task.strip():
        raise ToolError("调查任务不能为空。")

    child_messages: list[MessageParam] = [
        {
            "role": "user",
            "content": (
                "请只读调查下面的任务。最后简要说明关键发现、对应文件或函数，"
                "以及尚未确认的地方；不要复制大段文件原文。\n\n"
                f"任务：{task}"
            ),
        }
    ]
    read_only_tool_names = get_read_only_tool_names()
    child_tools = get_tool_definitions(read_only_tool_names)
    result = run_agent_loop(
        messages=child_messages,
        available_tools=child_tools,
        allowed_tool_names=read_only_tool_names,
        max_rounds=CHILD_MAX_ROUNDS,
    )
    if not result:
        raise ToolError("调查员未能完成任务。")
    return result


register_spawn_agent(spawn_agent)


def main() -> None:
    messages: list[MessageParam] = []
    state = AgentState()
    main_tool_names = get_all_tool_names()
    main_tools = get_tool_definitions(main_tool_names)

    while True:
        try:
            user_input = input(
                "\n请输入问题或任务描述（直接回车退出）："
            ).strip()
        except KeyboardInterrupt:
            print("\n程序已退出。")
            break

        if not user_input:
            print("程序已退出。")
            break

        messages.append({"role": "user", "content": user_input})

        while True:
            try:
                run_agent_loop(
                    messages=messages,
                    available_tools=main_tools,
                    allowed_tool_names=main_tool_names,
                    max_rounds=MAX_AGENT_ROUNDS,
                    state=state,
                )
                break
            except GenerationInterrupted:
                try:
                    follow_up = input(
                        "补充要求（直接回车则让模型重新评估）："
                    ).strip()
                except KeyboardInterrupt:
                    print("\n程序已退出。")
                    return

                if follow_up:
                    retry_instruction = follow_up
                else:
                    retry_instruction = (
                        "上一次生成在完成前被中断，未完成内容没有保存在历史中。"
                        "请从头重新评估当前任务，先考虑可行方案，"
                        "再选择合适的方法继续。"
                    )

                messages.append(
                    {
                        "role": "user",
                        "content": retry_instruction,
                    }
                )


if __name__ == "__main__":
    main()
