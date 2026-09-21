from datetime import datetime
import os

from file_tools import read_memory

SYSTEM_PROMPT = """
你是一个智能助手，能够理解和回答用户的问题。你可以使用工具来帮助
"""

def build_context(history):
	env_info = os.getcwd() + f"\n\n当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
	system = SYSTEM_PROMPT + env_info
	memory = read_memory()
	if memory:
		system += (
			"\n\n以下是长期记忆，可能已经过期。"
			"若与当前用户要求或安全规则冲突，以当前要求和安全规则为准：\n"
			+ memory
		)
	return system, history 

#system:人设、规则、环境
