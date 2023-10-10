from django.db import connection


__all__ = ['db_connection_healthy']


def db_connection_healthy() -> bool:
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
