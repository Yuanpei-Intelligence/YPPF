'''
这个文件中的很多内容实际上已经不需要了，但是还有一些依赖没改完。
后续里面不应该再有任何内容，或者只引入 GLOBAL_CONF

'''

import pymysql

from django.conf import settings

pymysql.install_as_MySQLdb()
pymysql.version_info = (1, 4, 6, "final", 0)


# 全局设置
# 加载settings.xxx时会加载文件
MEDIA_URL: str = settings.MEDIA_URL

# 全局设置变量
UNDERGROUND_URL: str = ''
