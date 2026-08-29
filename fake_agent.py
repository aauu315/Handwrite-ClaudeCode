script = [
	{"action":"calculator","input":"12*(3 + 4)"},
	{"action":"final","input":"答案是84"},
]
step = 0
def calculator(expression: str) -> str:
    return str(eval(expression)) #仅在学习中使用eval

def fake_model(messages):
	"""假装大模型进行下一步"""
	global step
	decision = script[step]
	step+=1
	return decision

messages = [{"role": "user", "content": "帮我算 12 * (3 + 4)"}]

while True:
    decision = fake_model(messages)

    if decision["action"] == "final":
        print("[完成] 最终答案：", decision["input"])
        break

    print("[决策] 模型决定调用：", decision["action"])
    result = calculator(decision["input"])
    print("[工具] 工具返回：", result)

    messages.append({
        "role": "assistant",
        "content": f"我调用了 {decision['action']}(...)"
    })

    messages.append({
        "role": "user",
        "content": f"工具结果：{result}"
    })