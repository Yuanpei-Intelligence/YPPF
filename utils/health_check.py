from django.db import connection


def db_conn_check() -> bool:
    '''
    django健康状态检查函数
    尝试执行数据库操作，若成功返回True，不成功返回False
    '''
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchall()
        return True
    except:
        return False
