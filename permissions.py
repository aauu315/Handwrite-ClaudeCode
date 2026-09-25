from pprint import pformat


READ_ONLY_TOOLS = {
    "calculator",
    "get_current_time",
    "list_files",
    "read_file",
    "read_memory",
}

MUTATING_TOOLS = {
    "write_file",
    "edit_file",
    "write_memory",
}

KNOWN_TOOLS = READ_ONLY_TOOLS | MUTATING_TOOLS | {"run_shell", "spawn_agent"}


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


def check_permission(tool_name: str, tool_input: dict) -> str:
    """返回 allow、confirm 或 deny，决定一次工具调用能否执行。"""
    if tool_name not in KNOWN_TOOLS:
        return "deny"

    if tool_name in READ_ONLY_TOOLS:
        return "allow"

    if tool_name in MUTATING_TOOLS:
        return "confirm"

    if tool_name == "spawn_agent":
        return "allow"

    command = normalize_command(str(tool_input.get("command", "")))
    if command in HARD_DENY_COMMANDS:
        return "deny"
    if command in SAFE_SHELL_COMMANDS:
        return "allow"
    return "confirm"


def ask_user(tool_name: str, tool_input: dict) -> bool:
    """显示工具名和参数；只有明确输入 y 或 yes 才允许执行。"""
    print("\n========== 权限确认 ==========")
    print("Agent 想执行工具：", tool_name)
    print("工具参数：")
    print(pformat(tool_input, sort_dicts=False, width=100))

    answer = input("是否允许执行？只有输入 y 才允许 [y/N]：")
    return answer.strip().lower() in {"y", "yes"}
