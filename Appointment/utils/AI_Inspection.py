from Appointment.config import appointment_config as CONFIG
from Appointment.models import AI_Inspection_Info, Room
from Appointment.utils.log import logger
import os
import json
import requests
from django.utils import timezone

# 模型人设：只返回“合规/不合规”，JSON格式
SYSTEM_PROMPT = (
    "你是一个审查学生预约功能房间信息的老师，请审核以下预约信息，审核要求是预约事由和房间用途匹配，且不能包含政治敏感信息和色情内容。"
    "你的输出必须严格为JSON，字段为："
    '{"decision": 0 或 1, "reason":"一句话理由"}'
    "其中 0 代表不允许预约，1 代表允许预约"
)


def _call_glm_decision(text: str, timeout: int = 30) -> tuple[str, str]:
    """
    调用智谱 HTTP 接口，返回 0 或 1，超时/网络错误报出异常。
    """
    ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    MODEL = "glm-4.5-flash"
    api_key = CONFIG.GLM_API_KEY
    if not api_key:
        raise RuntimeError("缺少参数 API_KEY")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "temperature": 0.2,  # 可调
        "top_p": 0.7,        # 可调
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"待审核文本：\n{text}"},
        ],
    }

    resp = requests.post(ENDPOINT, headers=headers,
                         json=payload, timeout=timeout)
    if resp.status_code != 200:
        # 把上游错误透出一小段，便于排查
        if resp.status_code == 400:
            return False, "请勿在预约理由中包含敏感词汇！"
        raise RuntimeError(f"Upstream {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    try:
        content_str = data["choices"][0]["message"]["content"]
        obj = json.loads(content_str)
    except Exception as e:
        raise RuntimeError(f"Bad JSON content from provider: {e}; raw={data}")

    decision = obj.get("decision")
    reason = obj.get("reason", "")
    if decision not in (0, 1):
        raise ValueError(f"unexpected decision: {decision};obj={obj}")
    if not isinstance(reason, str):
        reason = str(reason)
    if decision == 1:
        return True, reason
    else:
        return False, reason


def Ollama_Inspection(room_name, reason, user) -> tuple[bool, str]:
    # Ollama 审核功能接口，将预约房间（名称）和事由发送至 API，然后接收判断结果（合格/不合格）
    # 完整的处理办法（需要在API调用失败时抛出错误）
    try:
        response = requests.post(
            CONFIG.Ollama_ADDR + "/api/generate",
            json={
                "model": "gpt-oss:20b",
                "prompt": f"你是一个审查学生预约功能房间信息的老师，请审核以下预约信息，审核要求是预约事由和房间用途匹配，且不能包含政治敏感信息和色情内容。房间名称：{room_name}。事由：{reason}。如果审核通过，只输出 1，不通过，则输出 0，然后接一个空格，在空格后输出不通过的原因，原因尽量简要；如无法判断，默认不通过",
                "stream": False,
                "think": False
            }
        )  # GPT-OSS:20b 实测效果最好
        response.raise_for_status()  # 如果响应状态码不是 200，将抛出异常
        result = response.json()
        # 根据上述格式解析 response 部分，给出返回值
        output = result.get("response", "").strip()
        if output.startswith("1"):
            AI_Inspection_Info.objects.create(
                Iperson=user,
                Iroom=Room.objects.get(Rtitle=room_name),
                Ireason=reason,
                Iresult=AI_Inspection_Info.Result.APPROVED
            )
            return True, "Approved"
        elif output.startswith("0"):
            why = output[1:].strip()  # 获取不通过的原因
            AI_Inspection_Info.objects.create(
                Iperson=user,
                Iroom=Room.objects.get(Rtitle=room_name),
                Ireason=reason,
                Iresult=AI_Inspection_Info.Result.NOT_APPROVED,
                Idetail=why
            )
            return False, "房间用途不合规：" + why if why else "Not approved"
        else:
            logger.error(
                f"AI Inspection failed: Unexpected response format {output}")
            return False, "Unexpected response format"

    except requests.RequestException as e:
        # 处理请求异常
        # Idetail 最多记录 500 字符
        AI_Inspection_Info.objects.create(
            Iperson=user,
            Iroom=Room.objects.get(Rtitle=room_name),
            Ireason=reason,
            Iresult=AI_Inspection_Info.Result.NOT_APPROVED,
            Idetail=f"Request failed: {str(e)[:480]}"
        )

        # 错误信息需记入日志
        logger.error(f"AI Inspection failed: {str(e)}")

        return False, f"发生错误，请稍后再试或联系管理员！"


def GLM_Inspection(room_name, reason, user) -> tuple[bool, str]:
    # GLM 审核

    # 组装要审核的文本
    content = f"房间：{room_name}\n事由：{reason}"
    # 超时时间可从配置读取，默认30秒
    timeout = CONFIG.GLM_Timeout
    try:
        decision, why = _call_glm_decision(content, timeout=timeout)
        passed = (decision == 1)
        # 返回是否通过和理由 True通过，False不通过
        if passed:
            AI_Inspection_Info.objects.create(
                Iperson=user,
                Iroom=Room.objects.get(Rtitle=room_name),
                Ireason=reason,
                Iresult=AI_Inspection_Info.Result.APPROVED
            )
            return True, "合规"
        else:
            AI_Inspection_Info.objects.create(
                Iperson=user,
                Iroom=Room.objects.get(Rtitle=room_name),
                Ireason=reason,
                Iresult=AI_Inspection_Info.Result.NOT_APPROVED,
                Idetail=why
            )
            return False, f"房间用途不合规：{why or '无具体理由'}"

    except Exception as e:
        # API 调用失败：不通过并附带错误信息
        # Idetail 最多记录 500 字符
        AI_Inspection_Info.objects.create(
            Iperson=user,
            Iroom=Room.objects.get(Rtitle=room_name),
            Ireason=reason,
            Iresult=AI_Inspection_Info.Result.NOT_APPROVED,
            Idetail=f"Request failed: {str(e)[:480]}"
        )

        # 错误信息需记入日志
        logger.error(f"AI Inspection failed: {str(e)}")

        return False, f"发生错误，请稍后再试或联系管理员！"


def AI_Inspection(room_name, reason, user) -> tuple[bool, str]:
    # AI 审核功能接口，将预约房间（名称）和事由发送至 API，然后接收判断结果（合格/不合格）
    # Additional：最好能在不合格时附带理由

    if not CONFIG.AI_Inspection_Enabled:
        # 默认通过
        return True, "AI Inspection is disabled"

    # reason 长度限制在 250 字符以内
    if len(reason) > 250:
        AI_Inspection_Info.objects.create(
            Iperson=user,
            Iroom=Room.objects.get(Rtitle=room_name),
            Ireason=reason[:250],
            Iresult=AI_Inspection_Info.Result.NOT_APPROVED,
            Idetail="事由过长，超过250字符"
        )
        return False, "事由过长，请限制在250字符以内!"

    # 获取该用户上一次提交审核记录的时间，若距离现在不足 1 分钟，则拒绝本次审核
    last_record = AI_Inspection_Info.objects.filter(
        Iperson=user).order_by('-Itimestamp').first()
    if last_record:
        if (timezone.now() - last_record.Itimestamp).total_seconds() < 60:
            return False, "请勿频繁提交审核请求，请稍后再试!"

    # 在此处实现 API 的调用，并处理 API 调用失败的情况
    if CONFIG.AI_Inspection_Method == "Ollama":
        return Ollama_Inspection(room_name, reason, user)

    if CONFIG.AI_Inspection_Method == "GLM":
        return GLM_Inspection(room_name, reason, user)

    return False, "AI Inspection method is not recognized"
