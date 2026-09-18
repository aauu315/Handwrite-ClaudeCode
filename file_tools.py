import glob as _glob
import os

from tool_errors import ToolError

WORKSPACE = os.path.abspath(".")
_read_files = set()  # 记录已读取的文件路径
def list_files(pattern:str = "*") -> str:
	"""
	列出当前工作目录及其子目录中匹配指定模式的文件。
	只返回文件名，不读内容
	"""
	matches = _glob.glob(pattern,
					   	  root_dir = WORKSPACE, recursive=True)
	if not matches:
		return f"没有匹配'{pattern}'的文件。"
	return "匹配的文件:\n" + "\n".join(matches)	

MAX_READ_LINES = 400    # 一次最多读这么多行

def read_file(path: str) -> str:
    full = _safe_path(path)            
    try:
        with open(full, encoding="utf-8") as f:
            lines = f.readlines()
            _read_files.add(full)  # 记录已读取的文件
    except FileNotFoundError:
        raise ToolError(f"找不到文件 '{path}'。") from None

    truncated = len(lines) > MAX_READ_LINES
    shown = lines[:MAX_READ_LINES]
    body = "".join(f"{i+1:>4}\t{ln}"
                   for i, ln in enumerate(shown))
    if truncated:
        body += f"\n... ( truncated after {MAX_READ_LINES} lines )"
    return body

def write_file(path: str, content: str) -> str:
    full = _safe_path(path)

    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)

    with open(full, "w", encoding="utf-8") as f:
        f.write(content)

    return f"已写入 '{path}' ({len(content)} 个字符)。"

def _safe_path(path: str):
    full = os.path.abspath(os.path.join(WORKSPACE, path))
    if os.path.commonpath([full, WORKSPACE]) != WORKSPACE:
        raise ToolError(f"路径 '{path}' 越出了工作目录，已拒绝。")
    return full

def edit_file(path: str, old_string: str, new_string: str) -> str:
    full = _safe_path(path)
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
    with open(full, "w", encoding="utf-8") as f:
            f.write(text.replace(old_string, new_string))
    return f"已修改 '{path}'：替换了 1 处。"
