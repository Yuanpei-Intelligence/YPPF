import pymysql
import json

pymysql.install_as_MySQLdb()
pymysql.version_info = (1, 4, 6, "final", 0)


def load_local_json(path="./local_json.json"):
    with open(path, encoding="utf_8") as f:
        local_dict = json.load(f)
    return local_dict


local_dict = load_local_json()
