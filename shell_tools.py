"""Shell 命令的输出保存与分段读取。"""

import atexit
import locale
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from path_access import WORKSPACE
from tool_errors import ToolError


DEFAULT_TIMEOUT_SECONDS = 30
MAX_STREAM_BYTES = 10 * 1024 * 1024
PREVIEW_CHARACTERS = 8_000
PAGE_CHARACTERS = 8_000
OUTPUT_DIRECTORY_NAME = ".agent-shell-output"
_ENCODING = locale.getpreferredencoding(False)


@dataclass(frozen=True)
class ShellOutput:
    directory: Path
    returncode: int | None
    status: str
    incomplete: bool


_outputs: dict[str, ShellOutput] = {}
_session_directory: Path | None = None


def _output_directory() -> Path:
    """只建立本次进程专用的目录，不碰其他进程留下的文件。"""
    global _session_directory
    if _session_directory is None:
        base = WORKSPACE / OUTPUT_DIRECTORY_NAME
        base.mkdir(exist_ok=True)
        if base.resolve() != base:
            raise ToolError("Shell 输出目录指向了工作区中的其他位置或工作区外，已拒绝使用。")
        _session_directory = base / f"session-{uuid4().hex}"
        _session_directory.mkdir()
    return _session_directory


def cleanup_shell_outputs() -> None:
    """正常退出时仅删除本进程的输出目录。"""
    global _session_directory
    directory = _session_directory
    if directory is None:
        return

    base = (WORKSPACE / OUTPUT_DIRECTORY_NAME).resolve()
    workspace = WORKSPACE.resolve()
    if (
        base.parent != workspace
        or directory.is_symlink()
        or directory.resolve().parent != base
        or not directory.name.startswith("session-")
    ):
        return

    # Windows 的子进程刚退出时，文件句柄可能还要片刻才会释放。
    for attempt in range(20):
        try:
            shutil.rmtree(directory)
            break
        except PermissionError:
            if attempt == 19:
                print(f"[shell] 无法自动清理仍被占用的临时目录：{directory}")
                return
            time.sleep(0.1)
    _session_directory = None
    _outputs.clear()
    try:
        base.rmdir()  # 仅当它已为空时删除；保留其他进程或原有文件。
    except OSError:
        pass


atexit.register(cleanup_shell_outputs)


def _stop_process(process: subprocess.Popen) -> bool:
    """尽量停止命令及子进程；返回是否确认整棵进程树已停止。"""
    tree_stopped = True
    if os.name == "nt":
        # shell=True 可能派生子进程，Windows 上尝试停止整棵进程树。
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        tree_stopped = result.returncode == 0
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()
    return tree_stopped


def _read_piece(path: Path, max_chars: int, cursor: int = 0) -> tuple[str, str | None]:
    """按文本流的位置续读；cursor 只是本次进程产生的文本位置。"""
    with path.open("r", encoding=_ENCODING, errors="replace") as stream:
        stream.seek(cursor)
        content = stream.read(max_chars)
        next_position = stream.tell()
        has_more = bool(stream.read(1))
    return content, str(next_position) if has_more else None


def _tail_excerpt(path: Path, max_bytes: int = 1_024) -> str:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - max_bytes))
        return stream.read().decode(_ENCODING, errors="replace")


def _preview(path: Path, max_chars: int) -> str:
    content, cursor = _read_piece(path, max_chars)
    if not content:
        return "（无输出）"
    if cursor is None:
        return content
    return f"{content}\n[预览到此为止；可用 read_shell_output 从 cursor={cursor} 继续读取]"


def _brief_error(path: Path) -> str:
    lines = [line.strip() for line in _tail_excerpt(path).splitlines() if line.strip()]
    return lines[-1][-240:] if lines else ""


def run_shell(command: str) -> str:
    """执行一次命令，保存输出并向模型返回有限预览。"""
    output_id = uuid4().hex
    directory = _output_directory() / output_id
    directory.mkdir()
    stdout_path = directory / "stdout.txt"
    stderr_path = directory / "stderr.txt"
    status = "完成"
    incomplete = False
    child_processes_may_continue = False
    returncode: int | None = None

    try:
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=str(WORKSPACE),
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=(os.name != "nt"),
            )
            deadline = time.monotonic() + DEFAULT_TIMEOUT_SECONDS
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        status = "超时"
                        incomplete = True
                        child_processes_may_continue = not _stop_process(process)
                        break
                    if (
                        stdout_file.tell() > MAX_STREAM_BYTES
                        or stderr_file.tell() > MAX_STREAM_BYTES
                    ):
                        status = "输出超过保存上限"
                        incomplete = True
                        child_processes_may_continue = not _stop_process(process)
                        break
                    time.sleep(0.05)
            except KeyboardInterrupt:
                _stop_process(process)
                raise
            returncode = process.returncode
    except OSError as error:
        status = "启动失败"
        incomplete = True
        stderr_path.write_text(str(error), encoding=_ENCODING)

    for path in (stdout_path, stderr_path):
        if path.stat().st_size > MAX_STREAM_BYTES:
            with path.open("r+b") as stream:
                stream.truncate(MAX_STREAM_BYTES)
            incomplete = True
            status = (
                "超时且输出超过保存上限"
                if status == "超时" else "输出超过保存上限"
            )

    if status == "完成" and returncode != 0:
        status = "失败"

    if child_processes_may_continue:
        status += "（子进程可能仍在运行）"

    _outputs[output_id] = ShellOutput(directory, returncode, status, incomplete)

    stderr_size = stderr_path.stat().st_size
    stdout_size = stdout_path.stat().st_size
    if status == "完成":
        stdout_budget, stderr_budget = 6_000, 2_000
    else:
        stdout_budget, stderr_budget = 2_000, 6_000
    if stderr_size == 0:
        stdout_budget = PREVIEW_CHARACTERS
    if stdout_size == 0:
        stderr_budget = PREVIEW_CHARACTERS

    detail = _brief_error(stderr_path)
    detail_label = "错误输出摘要"
    if not detail and status != "完成":
        detail = _brief_error(stdout_path)
        detail_label = "输出末尾摘录"

    print(f"[shell] {status}；退出码：{returncode if returncode is not None else '未知'}")
    if detail and status != "完成":
        print(f"[shell] {detail_label}：{detail}")
    print(f"[shell] 完整输出目录：{directory}")
    print("[shell] 本次程序正常退出时会自动清理该目录；若文件仍被占用，会提示留下的位置。")

    output = (
        f"命令：{command}\n状态：{status}\n退出码：{returncode if returncode is not None else '未知'}\n"
        f"output_id：{output_id}\n完整输出目录：{directory}\n"
        f"完整输出：{'否（命令未完整完成）' if incomplete else '是'}\n"
        "如需后续内容，调用 read_shell_output(output_id, stream, cursor)。\n"
        f"标准输出预览：\n{_preview(stdout_path, stdout_budget)}\n"
        f"标准错误预览：\n{_preview(stderr_path, stderr_budget)}"
    )
    if status != "完成":
        raise ToolError(output)
    return output


def read_shell_output(output_id: str, stream: str, cursor: str = "0") -> str:
    """续读已保存的 stdout 或 stderr，不重新执行命令。"""
    result = _outputs.get(output_id)
    if result is None:
        raise ToolError("未知或已清理的 output_id。请先调用 run_shell。")
    if stream not in {"stdout", "stderr"}:
        raise ToolError("stream 只能是 stdout 或 stderr。")
    if not cursor.isdecimal():
        raise ToolError("cursor 必须是上次返回的非负整数文本。")
    try:
        content, next_cursor = _read_piece(
            result.directory / f"{stream}.txt", PAGE_CHARACTERS, int(cursor)
        )
    except (OSError, ValueError) as error:
        raise ToolError(f"无法读取输出：{error}") from error
    return (
        f"output_id：{output_id}\nstream：{stream}\n状态：{result.status}\n"
        f"完整输出：{'否' if result.incomplete else '是'}\n"
        f"内容：\n{content if content else '（没有更多内容）'}\n"
        f"next_cursor：{next_cursor if next_cursor is not None else '无'}"
    )
