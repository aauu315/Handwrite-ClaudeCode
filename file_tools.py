import glob
import os
import re
from datetime import date
from pathlib import Path

from path_access import is_within, request_read, request_write, resolve_path
from tool_errors import ToolError

_read_files = set()  # 记录已读取的文件路径

PROJECT_ROOT = Path(__file__).resolve().parent
MEMORY_PATH = PROJECT_ROOT / "memory" / "MEMORY.md"


def list_files(pattern: str = "*", directory: str = ".") -> str:
    """在指定目录内按 glob 模式列出名称；枚举外部目录前先询问。"""
    pattern_path = Path(pattern)
    if (
        pattern_path.is_absolute()
        or pattern_path.drive
        or ".." in pattern_path.parts
    ):
        raise ToolError(
            "pattern 只能描述 directory 内的匹配规则；"
            "要搜索其他目录，请使用 directory 参数。"
        )

    base = request_read(directory, is_directory=True)
    if not base.is_dir():
        raise ToolError(f"不是目录：{base}")

    matcher = re.compile(glob.translate(pattern, recursive=True))
    # 没有 ** 时，只遍历模式可能匹配到的层级。
    max_depth = None if "**" in pattern_path.parts else len(pattern_path.parts) - 1
    matches: list[str] = []
    for current, subdirectories, filenames in base.walk(
        top_down=True, follow_symlinks=False
    ):
        safe_subdirectories: list[str] = []
        for name in subdirectories:
            candidate = current / name
            if candidate.is_symlink() or candidate.is_junction():
                continue
            if not is_within(candidate.resolve(), base):
                continue
            relative_name = candidate.relative_to(base).as_posix()
            if matcher.fullmatch(relative_name):
                matches.append(relative_name + "/")
            safe_subdirectories.append(name)
        depth = len(current.relative_to(base).parts)
        subdirectories[:] = (
            [] if max_depth is not None and depth >= max_depth
            else safe_subdirectories
        )

        for name in filenames:
            candidate = current / name
            if not is_within(candidate.resolve(), base):
                continue
            relative_name = candidate.relative_to(base).as_posix()
            if matcher.fullmatch(relative_name):
                matches.append(relative_name)

    if not matches:
        return f"在 '{base}' 下没有匹配 '{pattern}' 的文件。"
    return f"在 '{base}' 下匹配的文件：\n" + "\n".join(sorted(matches))

MAX_READ_LINES = 400    # 一次最多读这么多行

def read_file(path: str, start_line: int = 1) -> str:
    """从指定行开始读取最多 400 行，并返回总行数和续读位置。"""
    if type(start_line) is not int or start_line < 1:
        raise ToolError("start_line 必须是从 1 开始的整数。")

    full = str(request_read(path))
    end_line = start_line + MAX_READ_LINES - 1
    shown: list[str] = []
    total_lines = 0

    try:
        with open(full, encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                total_lines = line_number
                if start_line <= line_number <= end_line:
                    shown.append(f"{line_number:>4}\t{line}")
        _read_files.add(full)  # 记录已读取的文件
    except FileNotFoundError:
        raise ToolError(f"找不到文件 '{path}'。") from None

    if total_lines == 0:
        return "文件为空，共 0 行。"
    if start_line > total_lines:
        return f"文件共 {total_lines} 行；从第 {start_line} 行起没有更多内容。"

    last_line = min(end_line, total_lines)
    result = (
        f"文件共 {total_lines} 行；本次读取第 {start_line}-{last_line} 行：\n"
        + "".join(shown)
    )
    if last_line < total_lines:
        result += (
            f"\n... ( truncated after {MAX_READ_LINES} lines )"
            f"\n还有未读取内容；继续调用 "
            f"read_file(path={path!r}, start_line={last_line + 1})。"
        )
    return result

def write_file(path: str, content: str) -> str:
    full = str(request_write(
        path, "write_file", {"path": path, "content": content}
    ))

    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)

    with open(full, "w", encoding="utf-8") as f:
        f.write(content)

    return f"已写入 '{path}' ({len(content)} 个字符)。"

def edit_file(path: str, old_string: str, new_string: str) -> str:
    full = str(resolve_path(path))
    if full not in _read_files:
        raise ToolError(
            f"文件 '{path}' 不在已读取的文件列表中，无法编辑。"
            "请先使用 read_file 读取该文件。"
        )
    text = open(full, "r", encoding="utf-8").read()
    count = text.count(old_string)
    if count == 0:
        raise ToolError(
            f"在文件 '{path}' 中未找到要替换的内容，"
            "请先使用 read_file 看清内容，再原样复制。"
        )
    if count > 1:
        raise ToolError(
            f"在文件 '{path}' 中 old_string 出现 {count} 次，无法确定改哪个，"
            "请把它写长点、带上唯一的上下文。"
        )
    approved = str(request_write(
        path,
        "edit_file",
        {"path": path, "old_string": old_string, "new_string": new_string},
    ))
    if approved != full:
        raise ToolError("文件路径在检查和确认之间发生变化，请重新读取后再编辑。")
    with open(full, "w", encoding="utf-8") as f:
            f.write(text.replace(old_string, new_string))
    return f"已修改 '{path}'：替换了 1 处。"


def read_memory() -> str:
    """读取长期记忆；文件尚不存在时返回空字符串。"""
    full = MEMORY_PATH

    try:
        with open(full, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""

def write_memory(content: str) -> str:
    """向固定的长期记忆文件追加一条带日期的记录。"""
    content = " ".join(content.split())
    if not content:
        raise ToolError("记忆内容不能为空。")

    full = MEMORY_PATH
    os.makedirs(os.path.dirname(full), exist_ok=True)

    with open(full, "a+", encoding="utf-8") as f:
        f.seek(0)
        existing = f.read()
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(f"- [{date.today().isoformat()}] {content}\n")

    return f"已将一条长期记忆追加到 '{MEMORY_PATH}'。"
