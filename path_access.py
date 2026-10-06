"""解析文件路径，并管理本次运行期间的工作区外读取授权。"""

from pathlib import Path
from pprint import pformat

from tool_errors import ToolError


# 工作区由启动程序时的终端当前目录决定。
WORKSPACE = Path.cwd().resolve()
_read_grants: set[Path] = set()


def resolve_path(path: str) -> Path:
    """相对路径以工作区为起点；解析 ..、符号链接和目录联接。"""
    return (WORKSPACE / path).resolve()


def is_within(path: Path, directory: Path) -> bool:
    """目标就是 directory，或位于 directory 的下级。"""
    return path == directory or directory in path.parents


def request_read(path: str, *, is_directory: bool = False) -> Path:
    """工作区内直接读取；工作区外询问一次或授予本次运行的目录读取权。"""
    target = resolve_path(path)
    if is_within(target, WORKSPACE):
        return target
    if any(is_within(target, granted) for granted in _read_grants):
        return target

    session_scope = target if is_directory else target.parent
    print("\n========== 工作区外读取权限 ==========")
    print(f"实际路径：{target}")
    print(f"本次运行期间可授权的目录：{session_scope}")
    choice = input(
        "只允许这次输入 1；本次运行期间允许该目录输入 2；其他输入拒绝："
    ).strip()
    if choice == "1":
        return target
    if choice == "2":
        _read_grants.add(session_scope)
        return target
    raise ToolError(f"用户拒绝读取工作区外的路径：{target}")


def request_write(path: str, operation: str, tool_input: dict) -> Path:
    """每次写入或编辑都单独确认；读取授权不会授予修改权。"""
    target = resolve_path(path)
    location = "工作区内" if is_within(target, WORKSPACE) else "工作区外"
    print("\n========== 文件修改权限 ==========")
    print(f"操作：{operation}")
    print(f"位置：{location}")
    print(f"实际路径：{target}")
    print("工具参数：")
    print(pformat(tool_input, sort_dicts=False, width=100))
    answer = input("是否允许这次修改？只有输入 y 才允许 [y/N]：")
    if answer.strip().lower() not in {"y", "yes"}:
        raise ToolError(f"用户拒绝修改文件：{target}")
    return target
