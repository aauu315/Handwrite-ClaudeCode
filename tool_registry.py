from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from anthropic.types import ToolParam

import file_tools
import shell_tools


PermissionType = Literal["read_only", "mutating", "shell", "delegate"]


@dataclass(frozen=True)
class ToolSpec:
    """一个工具的执行函数、模型描述和权限类型。"""

    name: str
    function: Callable[..., Any]
    permission: PermissionType
    description: str
    input_schema: dict

    def to_tool_param(self) -> ToolParam:
        """生成发送给模型的工具声明。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


_TOOL_REGISTRY: dict[str, ToolSpec] = {}


def calculator(expression: str) -> int | float:
    """计算简单的数学表达式。仅用于本教程的固定示例。"""
    return eval(expression, {"__builtins__": {}}, {})


def get_current_time() -> str:
    """获取当前时间。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def register_tool(spec: ToolSpec) -> None:
    """注册一个完整工具；名称重复或配置缺失时立即报错。"""
    if not spec.name:
        raise ValueError("工具名称不能为空。")
    if spec.name in _TOOL_REGISTRY:
        raise ValueError(f"工具 '{spec.name}' 已经注册。")
    if not callable(spec.function):
        raise TypeError(f"工具 '{spec.name}' 没有可调用的 Python 函数。")
    if spec.permission not in {"read_only", "mutating", "shell", "delegate"}:
        raise ValueError(f"工具 '{spec.name}' 的权限类型无效。")
    if spec.input_schema.get("type") != "object":
        raise ValueError(f"工具 '{spec.name}' 的 input_schema 必须描述对象。")

    _TOOL_REGISTRY[spec.name] = spec


def get_tool(tool_name: str) -> ToolSpec | None:
    """按名称取得一个工具；未注册时返回 None。"""
    return _TOOL_REGISTRY.get(tool_name)


def get_all_tool_names() -> set[str]:
    """返回主 Agent 当前能够使用的全部工具名。"""
    return set(_TOOL_REGISTRY)


def get_read_only_tool_names() -> set[str]:
    """从注册表自动找出可以交给只读子 Agent 的工具。"""
    return {
        name
        for name, spec in _TOOL_REGISTRY.items()
        if spec.permission == "read_only"
    }


def get_tool_definitions(
    allowed_tool_names: set[str] | None = None,
) -> list[ToolParam]:
    """生成发送给模型的工具声明，可按 Agent 权限范围筛选。"""
    return [
        spec.to_tool_param()
        for name, spec in _TOOL_REGISTRY.items()
        if allowed_tool_names is None or name in allowed_tool_names
    ]


def register_spawn_agent(function: Callable[..., Any]) -> None:
    """在 Agent 循环定义完成后注册派发子 Agent 的工具。"""
    register_tool(
        ToolSpec(
            name="spawn_agent",
            function=function,
            permission="delegate",
            description=(
                "派出一名只读调查员，独立调查一个边界明确的子任务，"
                "只把有依据的简洁结论带回主对话。"
                "适用于需要阅读多个文件或调查独立模块的任务；简单问题不要派。"
                "调查员不能修改文件、运行命令或继续派出调查员。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "写清调查目标、范围，以及需要返回的发现和文件依据。",
                    },
                },
                "required": ["task"],
            },
        )
    )


register_tool(
    ToolSpec(
        name="calculator",
        function=calculator,
        permission="read_only",
        description=(
            "功能：计算由数字、括号和基础算术运算符组成的简单数学表达式。"
            "适用：当用户明确要求进行数值计算，或完成任务需要得到准确的算术结果时使用。"
            "不适用：不要用于查询时间、读取文件、解释数学概念或处理非算术任务。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的数学表达式字符串，例如：12 * (3 + 4)。",
                }
            },
            "required": ["expression"],
        },
    )
)

register_tool(
    ToolSpec(
        name="get_current_time",
        function=get_current_time,
        permission="read_only",
        description=(
            "功能：返回运行此程序的计算机当前本地日期和时间。"
            "适用：当用户询问现在几点、今天的日期，或任务需要当前本地时间时使用。"
            "不适用：不要用于查询历史时间、未来时间、其他时区时间或进行日期推算。"
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
)

register_tool(
    ToolSpec(
        name="list_files",
        function=file_tools.list_files,
        permission="read_only",
        description=(
            "功能：按glob模式列出工作区里的文件名，例如'*.py'、[**/*.md'。只返回文件名，不读内容。"
            "适用：想知道有哪些文件、文件在哪时用它。"
            "不适用：不要用于读取文件内容、执行文件或访问工作区外的路径。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "要匹配的文件名模式，可以使用通配符，例如：*.py、**/*.md。",
                }
            },
            "required": ["pattern"],
        },
    )
)

register_tool(
    ToolSpec(
        name="read_file",
        function=file_tools.read_file,
        permission="read_only",
        description=(
            "功能：读取指定 UTF-8 文本文件，并返回文件的完整内容。"
            "想改一个文件之前必须先读一遍，否则会被edit_file拒绝。"
            "适用：当用户明确要求查看某个文本文件，或回答问题必须读取指定文件时使用。"
            "不适用：不要用于读取目录、二进制文件、用户未授权或与当前任务无关的敏感文件。"
        ),
        input_schema={
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
    )
)

register_tool(
    ToolSpec(
        name="write_file",
        function=file_tools.write_file,
        permission="mutating",
        description=(
            "功能：将指定内容写入 UTF-8 文本文件，新建或覆盖原有内容。"
            "适用：当用户明确要求创建新文件或完全重写小规模文件时使用。"
            "不适用：不要用于编辑文件的部分内容，需要进行部分编辑时请使用 edit_file"
        ),
        input_schema={
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
                    "description": "要写入文件的文本内容。",
                },
            },
            "required": ["path", "content"],
        },
    )
)

register_tool(
    ToolSpec(
        name="edit_file",
        function=file_tools.edit_file,
        permission="mutating",
        description=(
            "功能：在已读取的文本文件中查找指定字符串，并将其替换为新的字符串。"
            "适用：当用户明确要求修改文件内容，或任务需要更新文件中的特定文本时使用。"
            "不适用：不要用于编辑未读取的文件、二进制文件或用户未授权的敏感文件。"
        ),
        input_schema={
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
                    "description": "要替换的旧字符串，必须在文件中唯一出现。",
                },
                "new_string": {
                    "type": "string",
                    "description": "用于替换的新的字符串。",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    )
)

register_tool(
    ToolSpec(
        name="run_shell",
        function=shell_tools.run_shell,
        permission="shell",
        description=(
            "功能：在当前项目目录中执行一条系统命令，"
            "返回退出码、标准输出和标准错误。"
            "适用：运行测试、执行脚本、检查项目状态，以及验证代码修改是否正确。"
            "判断：退出码 0 通常表示成功；非 0 表示失败，"
            "失败时应先阅读标准错误，再决定下一步。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的完整命令，例如 pytest、python example.py。",
                }
            },
            "required": ["command"],
        },
    )
)

register_tool(
    ToolSpec(
        name="read_memory",
        function=file_tools.read_memory,
        permission="read_only",
        description=(
            "读取本项目的长期记忆。记忆也会自动加入系统上下文；"
            "只有需要明确核对记忆原文时才调用。"
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
)

register_tool(
    ToolSpec(
        name="write_memory",
        function=file_tools.write_memory,
        permission="mutating",
        description=(
            "向本项目的固定记忆文件追加一条带日期的长期记忆。"
            "仅记录下次会话仍有用的用户偏好、项目约定或反复遇到的坑。"
            "不要记录临时任务进度、完整文件内容、密码或 API Key。"
            "写入前会请求用户确认。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "一条简短、明确、适合跨会话保存的事实或约定。",
                },
            },
            "required": ["content"],
        },
    )
)
