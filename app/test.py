import string #string module里包含了阿拉伯数字,ascii码,特殊符号
import random #需要利用到choice

a = int(input('请输入要求的密码长度'))
b = string.digits + string.ascii_letters  #构建密码池
password = "" #命名一个字符串

for i in range(0,a):  #for loop 指定重复次数
    password = password + random.choice(b)   #从密码池中随机挑选内容构建密码
print(password)   #输出密码