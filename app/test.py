import string
import random
def random_code_init(seed):
    b = string.digits + string.ascii_letters  # 构建密码池
    password = ""
    random.seed(seed)
    for i in range(0, 6):
        password = password + random.choice(b)
    return password
print(random_code_init(19))