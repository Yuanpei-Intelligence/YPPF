"""Email transport for purpose-labelled verification codes."""
import json
from datetime import datetime

import requests

from app.config import CONFIG


def send_code_email(person_name: str, email: str, token: str, *, title: str) -> None:
    message = (
        f"<h3><b>亲爱的{person_name}同学：</b></h3><br/>"
        f"您好！本次{title}验证码为：<br/>"
        f'<p style="color:orange">{token}</p>'
        f"验证码有效期为{CONFIG.password_reset_token_seconds}秒，"
        "只能使用一次；重新获取后旧码失效。<br/>"
        "<br/>元培学院开发组<br/>"
        + datetime.now().strftime("%Y年%m月%d日")
    )
    post_data = json.dumps({
        "sender": "元培学院开发组",
        "toaddrs": [email],
        "subject": f"YPPF{title}",
        "content": message,
        "html": True,
        "private_level": 0,
        "secret": CONFIG.email.hasher.encode(message),
    })
    response = requests.post(
        CONFIG.email.url,
        post_data,
        timeout=6,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or result.get("status") != 200:
        raise RuntimeError("Verification email service rejected delivery")
