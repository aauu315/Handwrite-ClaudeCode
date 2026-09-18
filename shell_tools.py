import os
import subprocess


WORKSPACE = os.path.abspath(".")
DEFAULT_TIMEOUT_SECONDS = 30


def run_shell(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return (
            f"命令超时：运行超过 {DEFAULT_TIMEOUT_SECONDS} 秒，"
            f"已停止等待。\n"
            f"命令：{command}"
        )
    except Exception as error:
        return (
            f"执行命令时发生错误：{error}\n"
            f"命令：{command}"
        )

    stdout = result.stdout or "（无标准输出）"
    stderr = result.stderr or "（无标准错误）"

    return (
        f"命令：{command}\n"
        f"退出码：{result.returncode}\n"
        f"标准输出：\n{stdout}\n"
        f"标准错误：\n{stderr}"
    )