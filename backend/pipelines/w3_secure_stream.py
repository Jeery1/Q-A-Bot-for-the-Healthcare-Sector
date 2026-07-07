"""
W3 — 安全全流式

- 基于 W2 全流式管线
- 新增 LLM 安全门控: ASR 完成后先用小开销 LLM 分类，不安全直接短路
- 安全/无关话题：播放固定安全提示，不调用主 LLM
"""

import time
import base64
import asyncio
import logging
import httpx
from .base import BasePipeline, PipelineResult, TimingMetrics
from streaming.asr_azure import StreamingASR
from streaming.llm_api import StreamingLLM, _strip_markdown
from streaming.tts_azure import StreamingTTS
from sentence_splitter import SentenceSplitter

logger = logging.getLogger(__name__)

SAFETY_RESPONSES = {
    "sensitive": "检测到不安全输入，已拒绝回答。请遵守船舶建造安全规范。",
    "out_of_domain": "抱歉，我只能回答船舶建造相关的问题。请咨询焊接、涂装、船体、主机等技术话题。",
}


class W3SecureStreaming(BasePipeline):
    name = "w3"
    description = "安全流式 — W2全流式 + LLM安全门控（敏感/无关话题短路）"

    def __init__(self, asr: StreamingASR, llm: StreamingLLM, tts: StreamingTTS):
        self.asr = asr
        self.llm = llm
        self.tts = tts

    async def run(self, audio_bytes: bytes) -> PipelineResult:
        async def _chunks():
            yield (audio_bytes, False)
            yield (b"", True)

        class _Null:
            async def send_json(self, data):
                pass

        return await self.run_stream(_chunks(), _Null())

    async def run_stream(self, audio_chunk_iter, ws):
        t = TimingMetrics()
        t_start = time.perf_counter()
        asr_text = ""

        warmup_task = asyncio.create_task(self._warmup_llm())

        async def _audio_gen():
            async for chunk, is_last in audio_chunk_iter:
                yield chunk

        # ── 流式 ASR ────────────────────────────────────
        async for etype, text in self.asr.transcribe_stream(_audio_gen()):
            if etype == "partial":
                await ws.send_json({"type": "asr_partial", "text": text})
            elif etype == "final":
                asr_text = text
                await ws.send_json({"type": "asr_final", "text": text})

        t.asr = time.perf_counter() - t_start
        if not asr_text.strip():
            await ws.send_json({"error": "未识别到语音"})
            return PipelineResult(error="未识别到语音", timings=t)

        await warmup_task

        # ── 安全门控 ───────────────────────────────────
        safety = await self.llm.classify_safety(asr_text)
        is_safe = safety.get("safe", True)
        logger.info(f"[W3] safety check: safe={is_safe} reason={safety.get('reason')} "
                    f"input={asr_text!r}")

        sentence_queue = asyncio.Queue()
        output_queue = asyncio.Queue()
        seq_counter = 0
        first_audio_recorded = False
        filler_done = False

        async def _tts_synthesizer():
            nonlocal seq_counter
            while True:
                sent = await sentence_queue.get()
                if sent is None:
                    sentence_queue.task_done()
                    break
                sent = _strip_markdown(sent)
                if not sent.strip():
                    sentence_queue.task_done()
                    continue
                seq = seq_counter
                seq_counter += 1
                try:
                    audio_chunk = await self.tts.synthesize_once(sent)
                    audio_b64 = base64.b64encode(audio_chunk).decode()
                    await output_queue.put((seq, audio_b64, sent))
                except RuntimeError as e:
                    if "close" in str(e).lower():
                        logger.warning(f"[W3] ws closed, synthesizer stopping")
                        sentence_queue.task_done()
                        break
                    logger.error(f"[W3] TTS error for sentence {sent!r}: {e!r}")
                    await output_queue.put((seq, None, sent))
                except Exception as e:
                    logger.error(f"[W3] TTS error for sentence {sent!r}: {e!r}")
                    await output_queue.put((seq, None, sent))
                sentence_queue.task_done()

        async def _output_sender():
            nonlocal first_audio_recorded, filler_done
            buffer = {}
            next_seq = 0
            while True:
                seq, audio_b64, sent = await output_queue.get()
                if seq is None:
                    break
                buffer[seq] = (audio_b64, sent)
                while next_seq in buffer:
                    audio_b64, sent = buffer.pop(next_seq)
                    if audio_b64 is not None:
                        if filler_done and not first_audio_recorded:
                            t.first_audio = time.perf_counter() - t_start
                            first_audio_recorded = True
                        else:
                            filler_done = True
                        try:
                            await ws.send_json({"type": "tts_chunk", "data": audio_b64, "text": sent})
                        except RuntimeError as e:
                            if "close" in str(e).lower():
                                logger.warning(f"[W3] ws closed, output sender stopping")
                                return
                            logger.error(f"[W3] send error: {e!r}")
                    next_seq += 1

        TTS_WORKERS = 3
        synthesizer_tasks = [asyncio.create_task(_tts_synthesizer()) for _ in range(TTS_WORKERS)]
        sender_task = asyncio.create_task(_output_sender())

        await sentence_queue.put("好的，正在为您查询。")

        if not is_safe:
            reason = safety.get("reason", "out_of_domain")
            response = SAFETY_RESPONSES.get(reason, SAFETY_RESPONSES["out_of_domain"])
            logger.info(f"[W3] blocked: reason={reason}")
            await ws.send_json({"type": "answer", "text": response, "safe": False})
            await sentence_queue.put(response)
            for _ in range(TTS_WORKERS):
                await sentence_queue.put(None)
            await asyncio.gather(*synthesizer_tasks)
            await output_queue.put((None, None, None))
            await sender_task

            t.total = time.perf_counter() - t_start
            logger.info(f"[W3-block] total={t.total:.2f}s  first_audio={t.first_audio or 0:.2f}s")
            await ws.send_json({"type": "done", "safe": False, "reason": reason})
            return PipelineResult(
                asr_text=asr_text,
                answer_text=response,
                timings=t,
                metrics={"safe": False, "intercept_reason": reason, "safety_source": safety.get("source")},
            )

        # ── 流式 LLM → 句级切分 → 流式 TTS ──────────────
        splitter = SentenceSplitter()
        full_answer = ""
        t_llm_start = time.perf_counter()
        first_token = True

        logger.info(f"[W3] LLM start, prompt={asr_text!r}")
        token_count = 0
        sentence_count = 0

        async for etype, text in self.llm.generate_stream(asr_text):
            if etype == "token":
                if first_token:
                    t.llm_ttfb = time.perf_counter() - t_llm_start
                    first_token = False
                full_answer += text
                token_count += 1
                logger.debug(f"[W3] token#{token_count}: {text!r}")
                await ws.send_json({"type": "llm_token", "text": text})

                sentences = splitter.feed(text)
                if sentences:
                    logger.debug(f"[W3] sentences: {sentences}")
                for sent in sentences:
                    sentence_count += 1
                    logger.debug(f"[W3] tts_chunk#{sentence_count}: {sent!r}")
                    await sentence_queue.put(sent)

        logger.info(f"[W3] LLM done: {token_count} tokens, {sentence_count} sentences, full={full_answer!r}")

        for sent in splitter.flush():
            sentence_count += 1
            await sentence_queue.put(sent)

        for _ in range(TTS_WORKERS):
            await sentence_queue.put(None)
        await asyncio.gather(*synthesizer_tasks)
        await output_queue.put((None, None, None))
        await sender_task

        t.llm = time.perf_counter() - t_llm_start
        t.total = time.perf_counter() - t_start

        logger.info(f"[W3] asr={t.asr:.2f}s  llm_ttfb={t.llm_ttfb:.2f}s  "
                    f"total={t.total:.2f}s  first_audio={t.first_audio or 0:.2f}s")

        await ws.send_json({
            "type": "done",
            "timings": {"asr": round(t.asr, 2), "llm": round(t.llm, 2),
                        "total": round(t.total, 2)}
        })

        return PipelineResult(
            asr_text=asr_text,
            answer_text=full_answer,
            timings=t,
            metrics={"safe": True, "intercept_reason": "ok", "safety_source": safety.get("source")},
        )

    async def _warmup_llm(self):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.head(self.llm.base_url, timeout=2.0)
        except Exception:
            pass
