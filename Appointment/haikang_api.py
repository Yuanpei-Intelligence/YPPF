import json
from dataclasses import dataclass
from typing import NewType

from extern.haikang.HCNetSDK import *

from Appointment.config import appointment_config


UserId = NewType('UserId', int)
AccessHandle = NewType('AccessHandle', int)


class HaikangAPIError(Exception):
    pass


@dataclass
class EntranceGuardLoginDuck:
    door_id: int
    ip: str
    port: int
    username: str
    password: str

class EntranceGuard():

    def __init__(self, door_id: int, sdk: 'WrappedHaikangSDK', uid: UserId):
        self.door_id = str(door_id)
        self._SDK = sdk
        self._uid = uid

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self._SDK.logout_device(self._uid)

    def query_users(self, employee_ids: list[int]) -> list[dict]:
        handle = self._SDK.get_user_query_handle(self._uid)
        resp = self._SDK.access_user_json_api(handle, {
            "UserInfoSearchCond": {
                "searchID": "123", # TODO: What is this?
                "searchResultPosition": 0,
                "maxResults": max(30, len(employee_ids)),
                "EmployeeNoList": [
                    {
                        "employeeNo":  employee_id
                    } for employee_id in employee_ids
                ]
            }
        })
        resp = json.loads(resp.decode())
        if "UserInfoSearch" not in resp or "UserInfo" not in resp["UserInfoSearch"]:
            raise HaikangAPIError(f"Failed to query users: {employee_ids}")
        return resp["UserInfoSearch"]["UserInfo"]

    def _modify_users(self, employee_ids: list[int], grant: bool):
        # TODO: check batch limit?
        # API may not guarantee to return all results at once
        u_lists = self.query_users(employee_ids)
        failed_list = []
        handle = self._SDK.get_user_modify_handle(self._uid)
        for u_info in u_lists:
            u_info['doorRight'] = '1' if grant else ''
            succeed = False
            try:
                resp = self._SDK.access_user_json_api(handle, {"userInfo": u_info})
                resp = json.loads(resp.decode())
                succeed = resp.get('statusString') == 'OK'
            except HaikangAPIError as e:
                resp = str(e)
            if not succeed:
                failed_list.append((u_info['employeeNo'], u_info['name'], resp))
        if failed_list:
            raise HaikangAPIError(f"Failed to modify users: {failed_list}")

    def grant_access(self, employee_ids: list[int]):
        return self._modify_users(employee_ids, True)

    def revoke_access(self, employee_ids: list[int]):
        return self._modify_users(employee_ids, False)


class WrappedHaikangSDK:
    def __init__(self, lib_path: str, log_path: str):
        self._SDK = cdll.LoadLibrary(lib_path)
        self._SDK.NET_DVR_Init()
        self._SDK.NET_DVR_SetLogToFile(3, log_path.encode(), False)

    @property
    def last_error(self):
        return self._SDK.NET_DVR_GetLastError()

    def get_entrace_guard_device(self, duck: EntranceGuardLoginDuck) -> EntranceGuard:
        login_info = NET_DVR_USER_LOGIN_INFO()
        login_info.bUseAsynLogin = 0  # 同步登录方式
        login_info.sDeviceAddress = bytes(duck.ip, "ascii")
        login_info.wPort = duck.port
        login_info.sUserName = bytes(duck.username, "ascii")
        login_info.sPassword = bytes(duck.password, "ascii")
        login_info.byLoginMode = 0
        _dev_info = NET_DVR_DEVICEINFO_V40()
        uid = self._SDK.NET_DVR_Login_V40(byref(login_info), byref(_dev_info))
        if uid < 0:
            raise RuntimeError(f"Login failed: {self.last_error}")
        return EntranceGuard(duck.door_id, self, uid)

    def logout_device(self, uid: UserId):
        self._SDK.NET_DVR_Logout(uid)

    def __get_user_handle(self, uid: UserId, macro: int, cmd: bytes) -> int:
        cmd_buf = create_string_buffer(cmd)
        # Maybe not necessary, just allocate a big buffer
        dummy_out_buf = create_string_buffer(0x4000)
        handle = self._SDK.NET_DVR_StartRemoteConfig(
            uid, macro, cmd_buf,
            len(cmd) + 1, None, dummy_out_buf)
        if handle < 0:
            raise HaikangAPIError(f"Failed to get user handle: {self.last_error}")
        return handle

    def get_user_query_handle(self, uid: UserId) -> AccessHandle:
        cmd = b"POST /ISAPI/AccessControl/UserInfo/Search?format=json"
        return self.__get_user_handle(uid, NET_DVR_JSON_CONFIG, cmd)

    def get_user_modify_handle(self, uid: UserId) -> AccessHandle:
        cmd = b"PUT /ISAPI/AccessControl/UserInfo/Modify?format=json"
        return self.__get_user_handle(uid, NET_DVR_JSON_CONFIG, cmd)

    def access_user_json_api(self, handle: AccessHandle, json_obj: dict) -> bytes:
        out_buf = create_string_buffer(0x4000)
        datalen = create_string_buffer(0x10)
        payload = json.dumps(json_obj).encode()
        json_buf = create_string_buffer(payload)
        err = self._SDK.NET_DVR_SendWithRecvRemoteConfig(
            handle,
            json_buf,
            len(payload) + 1,
            out_buf,
            0x4000,
            datalen
        )
        if err < 0:
            raise HaikangAPIError(f"Failed to access user json api: {self.last_error}")
        return out_buf.value


HaikangSDK = WrappedHaikangSDK(
    appointment_config.haikang_lib_path,
    appointment_config.haikang_log_path)
