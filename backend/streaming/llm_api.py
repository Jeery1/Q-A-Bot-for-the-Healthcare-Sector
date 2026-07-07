"""
Streaming LLM using DeepSeek API (OpenAI-compatible).
"""

import json
import re
import asyncio
import logging
import httpx

from domain_knowledge import build_domain_context

logger = logging.getLogger(__name__)

_MD_PATTERNS = [
    (re.compile(r'^#{1,6}\s+', re.MULTILINE), ''),
    (re.compile(r'\*\*(.+?)\*\*'), r'\1'),
    (re.compile(r'~~(.+?)~~'), r'\1'),
    (re.compile(r'`(.+?)`'), r'\1'),
]

_CLASSIFY_PROMPT = """判断用户输入是否安全。仅回复 JSON: {"safe": true或false, "reason": "sensitive或out_of_domain或ok"}

安全红线（须拒绝）: 拆除安全设备、绕过安全规范、关闭报警器、屏蔽传感器、禁用安全系统、伪造证书、非法改装、破坏设备、恶意代码、入侵系统
无关话题（须拒绝）: 天气、股票、电影、美食、体育、音乐、政治人物、游戏攻略、娱乐新闻
正常提问: 焊接、涂装、切割、装配、主机、船体、管系、电气、舾装、质检"""

_SENSITIVE_KEYWORDS = [
    "拆除安全", "拆除船舶安全装置", "绕过安全", "关闭报警", "屏蔽传感器",
    "禁用安全", "伪造证书", "非法改装", "破坏设备", "制造事故", "恶意代码", "入侵系统",
]

_OUT_OF_DOMAIN_KEYWORDS = [
    "天气", "股票", "电影", "美食", "体育", "音乐", "政治", "游戏", "娱乐新闻",
]

_DOMAIN_KEYWORDS = [
    "船", "船舶", "造船", "船体", "焊接", "涂装", "切割", "装配", "主机",
    "管系", "电气", "舾装", "质检", "工艺", "安全", "维修", "保养",
]


def _strip_markdown(text: str) -> str:
    for pattern, repl in _MD_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _classify_safety_local(text: str) -> dict:
    """Deterministic fallback for safety experiments and API failures."""
    lowered = text.lower()
    if any(kw in lowered for kw in _SENSITIVE_KEYWORDS):
        return {"safe": False, "reason": "sensitive", "source": "local"}
    if any(kw in lowered for kw in _OUT_OF_DOMAIN_KEYWORDS):
        return {"safe": False, "reason": "out_of_domain", "source": "local"}
    if any(kw in lowered for kw in _DOMAIN_KEYWORDS):
        return {"safe": True, "reason": "ok", "source": "local"}
    return {"safe": False, "reason": "out_of_domain", "source": "local"}


class StreamingLLM:
    """DeepSeek / OpenAI-compatible LLM with stream=True support."""

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.system_prompt = (
            "你是船舶建造领域的专家，请用中文准确回答用户关于造船的问题。"
            "知识范围包括船型与总体、船体结构、焊接/涂装/装配工艺、主机、管系、电气、舾装、质检与安全。"
            "回答应简洁、专业；遇到非造船问题或危险违规请求，应拒绝并引导到合规安全规范。"
        )

    def _build_messages(self, prompt: str) -> list[dict]:
        domain_context = build_domain_context(prompt)
        system_content = self.system_prompt
        if domain_context:
            system_content += "\n\n以下为本项目领域语料中的参考问答片段，可用于保持术语和回答风格一致：\n" + domain_context
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

    async def generate_stream(self, prompt: str):
        """
        Yield (type, text) where type is "token" or "sentence".
        type="sentence" means a complete sentence ready for TTS.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": self._build_messages(prompt),
            "stream": True,
            "max_tokens": 512,
            "temperature": 0.7,
        }

        last_error = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream("POST", f"{self.base_url}/v1/chat/completions",
                                             headers=headers, json=payload) as resp:
                        buffer = ""
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                delta = data["choices"][0].get("delta", {})
                                token = delta.get("content", "")
                                if token:
                                    buffer += token
                                    logger.debug(f"[LLM] token: {token!r}")
                                    yield ("token", token)
                            except (json.JSONDecodeError, KeyError):
                                continue

                        if buffer.strip():
                            logger.info(f"[LLM] stream done, buffer={buffer!r}")
                            yield ("final", buffer.strip())
                return
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError,
                    httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(f"[LLM] attempt {attempt + 1}/3 failed: {e!r}, retry in {wait}s")
                await asyncio.sleep(wait)

        raise last_error

    async def generate_once(self, prompt: str) -> str:
        """Non-streaming: return full response text."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": self._build_messages(prompt),
            "stream": False,
            "max_tokens": 512,
            "temperature": 0.7,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.base_url}/v1/chat/completions",
                                     headers=headers, json=payload)
            data = resp.json()
            return _strip_markdown(data["choices"][0]["message"]["content"].strip())

    async def classify_safety(self, text: str) -> dict:
        """LLM 安全门控：用最小 token 分类用户输入是否安全。"""
        if not self.api_key or self.api_key.startswith("sk-your-key"):
            return _classify_safety_local(text)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _CLASSIFY_PROMPT},
                {"role": "user", "content": text},
            ],
            "max_tokens": 64,
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{self.base_url}/v1/chat/completions",
                                         headers=headers, json=payload)
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                logger.info(f"[LLM] classify_safety input={text!r} output={content!r}")
                result = json.loads(content)
                if "safe" not in result:
                    return _classify_safety_local(text)
                result["source"] = "llm"
                return result
        except Exception as e:
            logger.warning(f"[LLM] classify_safety failed: {e!r}, using local fallback")
            return _classify_safety_local(text)
