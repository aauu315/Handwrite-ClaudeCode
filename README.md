# Handwrite Claude Code

这是一个跟随教程学习、理解并手写简化版 Claude Code Agent 的练习项目。项目从一个预设决策流程的假 Agent 开始，逐步替换为能够调用真实大模型与本地工具的 Agent 循环。

## 学习来源

本项目学习并参考了 Bilibili 教程：[《手写一个 Claude Code》](https://www.bilibili.com/video/BV1Ycup6VEvG/)。感谢原作者的讲解。

当前只学习完课程第 1 节，仓库内容是我在学习过程中完成的代码练习和理解记录，并非教程作者的官方代码仓库。

## 当前状态

- `fake_agent.py`：使用预先写好的决策，模拟“模型决定调用工具 → 工具返回结果 → 模型给出最终答案”的 Agent 循环。
- `real_agent.py`：通过 DeepSeek 的 Anthropic 兼容接口调用真实模型，并把 `calculator` 注册为可调用工具。
- 已实现多轮工具调用：模型可以先计算 `12 * (3 + 4)`，再继续计算并输出最终答案。
- 使用 `uv` 管理 Python 项目和依赖。

## 运行环境

- Python 3.13 或更高版本
- [uv](https://docs.astral.sh/uv/)
- DeepSeek API Key

安装依赖：

```text
uv sync
```

运行不需要 API 的模拟版本：

```text
uv run python fake_agent.py
```

运行真实模型版本前，需要在当前终端设置环境变量。

CMD：

```text
set "ANTHROPIC_API_KEY=你的DeepSeek_API_Key"
uv run python real_agent.py
```

PowerShell：

```text
$env:ANTHROPIC_API_KEY="你的DeepSeek_API_Key"
uv run python real_agent.py
```

DeepSeek 的 Anthropic 兼容地址已经在 `real_agent.py` 中显式配置。请勿把真实 API Key 写入代码或提交到 GitHub。

## 学习计划

1. 完整看完《手写一个 Claude Code》课程。
2. 逐节补充和整理项目代码。
3. 在理解 Agent 循环、工具调用和对话历史后，独立完成一个可实际使用的 Demo。

## 说明

当前的 `calculator` 为教学示例，使用受限的 `eval` 计算简单表达式，不应直接用于处理不可信输入。项目仍处于学习阶段，接口和目录结构可能随着课程进度继续调整。
