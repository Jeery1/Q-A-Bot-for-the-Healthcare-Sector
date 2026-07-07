"""
W2 — 全流式

- 并行预热: ASR 进行时预建 LLM HTTP 连接
- ASR: 流式 (partial 实时推送)
- LLM: 流式 (逐 token 推送)
- TTS: 句级切分 → 逐句合成 → 实时推送
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


class W2FullStreaming(BasePipeline):
    name = "w2"
    description = "全流式 — 并行预热 + 流式ASR → 流式LLM → 句级切分 → 流式TTS"

    def __init__(self, asr: StreamingASR, llm: StreamingLLM, tts: StreamingTTS):
        self.asr = asr
        self.llm = llm
        self.tts = tts

    # ── experiment 用 (非流式汇总) ──────────────────────────

    async def run(self, audio_bytes: bytes) -> PipelineResult:
        async def _chunks():
            yield (audio_bytes, False)
            yield (b"", True)

        class _Null:
            async def send_json(self, data):
                pass

        return await self.run_stream(_chunks(), _Null())

    # ── WebSocket 实时流式 ──────────────────────────────────

    async def run_stream(self, audio_chunk_iter, ws):
        t = TimingMetrics()
        t_start = time.perf_counter()
        asr_text = ""

        # 并行预热：ASR 进行时预连 LLM API
        warmup_task = asyncio.create_task(self._warmup_llm())

        async def _audio_gen():
            async for chunk, is_last in audio_chunk_iter:
                yield chunk

        # 流式 ASR ────────────────────────────────────────
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

        await warmup_task  # 确保预热完成

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
                        logger.warning(f"[W2] ws closed, synthesizer stopping")
                        sentence_queue.task_done()
                        break
                    logger.error(f"[W2] TTS error for sentence {sent!r}: {e!r}")
                    await output_queue.put((seq, None, sent))
                except Exception as e:
                    logger.error(f"[W2] TTS error for sentence {sent!r}: {e!r}")
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
                                logger.warning(f"[W2] ws closed, output sender stopping")
                                return
                            logger.error(f"[W2] send error: {e!r}")
                    next_seq += 1

        TTS_WORKERS = 3
        synthesizer_tasks = [asyncio.create_task(_tts_synthesizer()) for _ in range(TTS_WORKERS)]
        sender_task = asyncio.create_task(_output_sender())

        await sentence_queue.put("好的，正在为您查询。")

        # 流式 LLM → 句级切分 → 流式 TTS ─────────────────
        splitter = SentenceSplitter()
        full_answer = ""
        t_llm_start = time.perf_counter()
        first_token = True

        logger.info(f"[W2] LLM start, prompt={asr_text!r}")
        token_count = 0
        sentence_count = 0

        async for etype, text in self.llm.generate_stream(asr_text):
            if etype == "token":
                if first_token:
                    t.llm_ttfb = time.perf_counter() - t_llm_start
                    first_token = False
                full_answer += text
                token_count += 1
                logger.debug(f"[W2] token#{token_count}: {text!r}")
                await ws.send_json({"type": "llm_token", "text": text})

                sentences = splitter.feed(text)
                if sentences:
                    logger.debug(f"[W2] sentences: {sentences}")
                for sent in sentences:
                    sentence_count += 1
                    logger.debug(f"[W2] tts_chunk#{sentence_count}: {sent!r}")
                    await sentence_queue.put(sent)

        logger.info(f"[W2] LLM done: {token_count} tokens, {sentence_count} sentences, full={full_answer!r}")

        # 兜底发送剩余文本
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

        logger.info(f"[W2-stream] asr={t.asr:.2f}s  llm_ttfb={t.llm_ttfb:.2f}s  "
                    f"total={t.total:.2f}s  first_audio={t.first_audio:.2f}s")

        await ws.send_json({
            "type": "done",
            "timings": {"asr": round(t.asr, 2), "llm": round(t.llm, 2),
                        "total": round(t.total, 2)}
        })

        return PipelineResult(asr_text=asr_text, answer_text=full_answer, timings=t)

    # ── 并行预热 ──────────────────────────────────────────

    async def _warmup_llm(self):
        """ASR 进行时预建 LLM API 连接，减少 DNS/TCP/TLS 延迟。"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.head(self.llm.base_url, timeout=2.0)
        except Exception:
            pass
