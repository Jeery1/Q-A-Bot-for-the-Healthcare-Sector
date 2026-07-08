"""
Streaming LLM using DeepSeek API (OpenAI-compatible).
"""

import json
import re
import asyncio
import logging
import httpx

logger = logging.getLogger(__name__)

_MD_PATTERNS = [
    (re.compile(r'^#{1,6}\s+', re.MULTILINE), ''),
    (re.compile(r'\*\*(.+?)\*\*'), r'\1'),
    (re.compile(r'~~(.+?)~~'), r'\1'),
    (re.compile(r'`(.+?)`'), r'\1'),
]

_CLASSIFY_PROMPT = """判断用户输入是否安全。仅回复 JSON: {"safe": true或false, "reason": "sensitive或out_of_domain或ok"}

安全红线（须拒绝）: 非法行医、开具假处方、泄露病人隐私、非法器官交易、使用违禁药物、伪造医疗记录、教唆自残、提供自杀方法
无关话题（须拒绝）: 天气、股票、电影、美食、体育、音乐、政治人物、游戏攻略、娱乐新闻
正常提问: 内科、外科、儿科、妇产科、骨科、皮肤科、心血管、消化、呼吸、神经科、营养、康复、预防保健、疫苗接种、药物、常见病、慢性病、急救"""

_SENSITIVE_KEYWORDS = [
    "非法行医", "无证行医", "假处方", "病人隐私", "器官交易",
    "违禁药物", "伪造病历", "教唆自残", "自杀方法", "毒品制作",
]

_OUT_OF_DOMAIN_KEYWORDS = [
    "天气", "股票", "电影", "美食", "体育", "音乐", "政治", "游戏", "娱乐新闻",
]

_DOMAIN_KEYWORDS = [
    "内科", "外科", "儿科", "妇产科", "骨科", "皮肤科", "心血管", "消化", "呼吸",
    "神经科", "眼科", "耳鼻喉", "口腔", "营养", "康复", "预防保健", "疫苗",
    "药物", "药品", "常见病", "慢性病", "急救", "体检", "症状", "诊断", "治疗",
    "医院", "手术", "中医", "西医", "养生", "心理健康", "健康", "医疗",
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

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-chat", retriever=None, rag_top_k: int = 3):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.retriever = retriever
        self.rag_top_k = rag_top_k
        self._last_rag_docs = []
        self.system_prompt = (
            "你是健康与医疗领域的智能助手，请用中文准确回答用户关于健康和医疗的问题。"
            "知识范围包括内科、外科、儿科、妇产科、骨科、皮肤科、神经科、心血管、消化、呼吸等常见科室，"
            "以及常见病防治、慢性病管理、营养膳食、康复护理、预防保健、疫苗接种、心理健康、药物常识、急救知识等。"
            "回答应简洁、专业、通俗易懂；请始终在回答末尾提醒用户：本回答仅供参考，不能替代专业医生的诊断与治疗。"
            "遇到超出医疗健康范围的问题或危险违规请求，应礼貌拒绝并引导到合规方向。"
        )

    async def _build_messages(self, prompt: str) -> list[dict]:
        system_content = self.system_prompt
        rag_context = await self._build_rag_context(prompt)
        if rag_context:
            system_content += "\n\n以下为医疗知识库中检索到的相关参考信息，请参考这些信息回答问题：\n" + rag_context
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

    async def _build_rag_context(self, prompt: str) -> str:
        self._last_rag_docs = []
        if not self.retriever or not self.retriever.is_ready():
            logger.debug(f"[RAG] retriever not ready, skipping")
            return ""
        try:
            docs = await asyncio.to_thread(
                self.retriever.retrieve, prompt, top_k=self.rag_top_k
            )
            self._last_rag_docs = docs
            if not docs:
                logger.info(f"[RAG] query={prompt!r} => 0 results")
                return ""
            logger.info(f"[RAG] query={prompt!r} => {len(docs)} results:")
            blocks = []
            for i, doc in enumerate(docs):
                q_short = doc['question'][:60]
                a_short = doc['answer'][:80]
                logger.info(f"[RAG]   [{i + 1}] score={doc['score']:.4f} | Q: {q_short}... | A: {a_short}...")
                blocks.append(
                    f"[参考{i + 1}]\n问：{doc['question']}\n答：{doc['answer']}"
                )
            return "\n\n".join(blocks)
        except Exception as e:
            logger.warning(f"RAG retrieval failed: {e}")
            return ""

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
            "messages": await self._build_messages(prompt),
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
            "messages": await self._build_messages(prompt),
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
