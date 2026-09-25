import inspect
from pprint import pformat
from typing import get_type_hints

from tool_registry import ToolSpec


# 只对完整命令进行匹配；稍微复杂的命令交给用户确认。
SAFE_SHELL_COMMANDS = {
    "dir",
    "git diff",
    "git diff --cached",
    "git status",
    "git status --porcelain",
    "git status --short",
    "python --version",
}


# 教学用的最低限度硬拒绝，不是完整的危险命令识别器。
HARD_DENY_COMMANDS = {
    "del /s /q c:\\",
    "format c:",
    "rd /s /q c:\\",
    "remove-item $home -recurse -force",
    "remove-item c:\\ -recurse -force",
    "rm -rf /",
    "rm -rf ~",
}


def normalize_command(command: str) -> str:
    """统一命令的大小写和多余空格，方便进行名单匹配。"""
    return " ".join(command.strip().lower().split())


def validate_tool_input(
    tool: ToolSpec,
    tool_input: dict,
) -> str | None:
    """第一步：检查参数能否安全地传给已经注册的工具函数。"""
    if not isinstance(tool_input, dict):
        return "工具参数必须是一个对象。"

    try:
        bound_arguments = inspect.signature(tool.function).bind(**tool_input)
    except TypeError as error:
        return f"工具 '{tool.name}' 的参数不完整或不匹配：{error}"

    try:
        type_hints = get_type_hints(tool.function)
    except (NameError, TypeError):
        type_hints = {}

    for parameter_name, value in bound_arguments.arguments.items():
        expected_type = type_hints.get(parameter_name)
        if isinstance(expected_type, type) and not isinstance(value, expected_type):
            return (
                f"工具 '{tool.name}' 的参数 '{parameter_name}' 类型错误："
                f"应为 {expected_type.__name__}，实际为 {type(value).__name__}。"
            )

    return None


def check_permission(tool: ToolSpec, tool_input: dict) -> str:
    """第二步：按注册的权限类型决定自动允许、询问用户或拒绝。"""
    if tool.permission == "read_only":
        return "allow"

    if tool.permission == "mutating":
        return "confirm"

    if tool.permission == "delegate":
        return "allow"

    if tool.permission != "shell":
        return "deny"

    command = normalize_command(str(tool_input.get("command", "")))
    if command in HARD_DENY_COMMANDS:
        return "deny"
    if command in SAFE_SHELL_COMMANDS:
        return "allow"
    return "confirm"


def check_tool_call(
    tool: ToolSpec | None,
    tool_input: dict,
    allowed_tool_names: set[str],
) -> tuple[str, str]:
    """第三步：统一检查工具注册、Agent 范围、参数和操作权限。"""
    if tool is None:
        return "deny", "程序没有注册模型请求的工具。"

    if tool.name not in allowed_tool_names:
        return "deny", f"当前 Agent 无权使用工具 '{tool.name}'。"

    validation_error = validate_tool_input(tool, tool_input)
    if validation_error:
        return "invalid", validation_error

    decision = check_permission(tool, tool_input)
    if decision == "deny":
        return (
            "deny",
            "这次工具调用已被安全策略拒绝。"
            "请不要重复尝试同一种危险操作，请改用更安全的做法。",
        )

    return decision, ""


def ask_user(tool_name: str, tool_input: dict) -> bool:
    """显示工具名和参数；只有明确输入 y 或 yes 才允许执行。"""
    print("\n========== 权限确认 ==========")
    print("Agent 想执行工具：", tool_name)
    print("工具参数：")
    print(pformat(tool_input, sort_dicts=False, width=100))

    answer = input("是否允许执行？只有输入 y 才允许 [y/N]：")
    return answer.strip().lower() in {"y", "yes"}
