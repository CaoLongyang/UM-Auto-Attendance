from sign_in import start_sign_in

# 1. 随便选一个你想测试的课程网址（从你 config.py 里抄一个过来）
test_url = "https://spectrum.um.edu.my/mod/attendance/view.php?id=1069466"

print("--- 启动暴力测试模式 ---")
print(f"目标网址：{test_url}")
print("程序将立即启动，不看时间，不看星期几！")

# 2. 直接开跑！
start_sign_in(test_url)

print("--- 测试流程结束 ---")