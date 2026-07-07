"""
Safety filter for shipbuilding QA system.
Blocks out-of-domain and sensitive questions before they reach the LLM.
"""

SAFETY_KEYWORDS = {
    "sensitive": [
        "拆除安全装置", "绕过安全规范", "关闭报警", "屏蔽传感器",
        "禁用安全系统", "跳过检测", "伪造证书", "非法改装",
        "破坏设备", "制造事故", "恶意代码", "入侵系统",
    ],
    "out_of_domain": [
        "天气", "股票", "电影", "美食", "体育", "音乐",
        "政治", "历史人物", "娱乐新闻", "游戏攻略",
    ],
}

SAFETY_RESPONSE = "抱歉，我无法回答该问题。请咨询船舶建造相关的技术问题。"


def contains_keyword(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    for kw in keywords:
        if kw in text_lower:
            return True
    return False


def check_safety(text: str) -> dict:
    result = {"safe": True, "reason": "", "response": ""}

    if contains_keyword(text, SAFETY_KEYWORDS["sensitive"]):
        result["safe"] = False
        result["reason"] = "sensitive"
        result["response"] = SAFETY_RESPONSE
        return result

    if contains_keyword(text, SAFETY_KEYWORDS["out_of_domain"]):
        result["safe"] = False
        result["reason"] = "out_of_domain"
        result["response"] = SAFETY_RESPONSE
        return result

    return result
