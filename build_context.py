from datetime import datetime
import os

SYSTEM_PROMPT = """
你是一个智能助手，能够理解和回答用户的问题。你可以使用工具来帮助
"""

def build_context(history):
	env_info = os.getcwd() + f"\n\n当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
	system = SYSTEM_PROMPT + env_info
	return system, history 

#system:人设、规则、环境