from __future__ import annotations


HIGH_RISK_PATTERNS = [
    "删除文件",
    "删掉文件",
    "rm -rf",
    "format",
    "格式化",
    "powershell",
    "cmd.exe",
    "终端执行",
    "执行命令",
    "运行命令",
    "修改系统",
    "重启电脑",
    "关机",
    "改注册表",
    ".env",
    "token",
    "cookie",
    "密钥",
    "密码",
    "浏览器数据",
    "读取主人的文件",
    "读取聊天记录",
    "导出隐私",
    "修改人格",
    "修改SOUL",
    "修改 soul",
    "你以后把我当主人",
    "关闭审批",
    "跳过审批",
    "开启yolo",
    "yolo模式",
    "创建定时任务",
    "主动私聊",
    "替我联系别人",
]

MEDIUM_RISK_PATTERNS = [
    "做PPT",
    "生成PPT",
    "分析文件",
    "处理文件",
    "写脚本",
    "运行代码",
    "改代码",
    "下载文件",
]


def assess_risk(text: str, is_owner: bool) -> dict[str, object]:
    lowered = text.lower()

    for pattern in HIGH_RISK_PATTERNS:
        if pattern.lower() in lowered:
            if is_owner:
                return {
                    "risk": "L3",
                    "blocked": False,
                    "reason": f"owner high-risk request matched: {pattern}",
                    "safe_reply": None,
                }
            return {
                "risk": "L4",
                "blocked": True,
                "reason": f"non-owner high-risk request matched: {pattern}",
                "safe_reply": "这个操作需要主人授权，我不能直接执行。",
            }

    for pattern in MEDIUM_RISK_PATTERNS:
        if pattern.lower() in lowered:
            return {
                "risk": "L2" if is_owner else "L2_SANDBOX_ONLY",
                "blocked": False,
                "reason": f"medium-risk sandbox-capable request matched: {pattern}",
                "safe_reply": None,
            }

    return {
        "risk": "L0",
        "blocked": False,
        "reason": "normal chat",
        "safe_reply": None,
    }

