"""
W1 — Baseline (非流式)

Non-streaming pipeline using online APIs sequentially.
- ASR: Azure Speech streaming (partial results)
- LLM: DeepSeek generate_once
- TTS: Azure TTS synthesize_once
"""

import time
import logging
import base64
from .base import BasePipeline, PipelineResult, TimingMetrics
from streaming.asr_azure import StreamingASR
from streaming.llm_api import StreamingLLM
from streaming.tts_azure import StreamingTTS

logger = logging.getLogger(__name__)


class W1Baseline(BasePipeline):
    name = "w1"
    description = "基线 — 完整音频 → 流式ASR → 完整LLM → (先显示) → 完整TTS"

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
        """Accumulate audio, one-shot ASR, LLM, send text, then TTS."""
        t = TimingMetrics()
        t_start = time.perf_counter()

        chunks = []
        async for chunk, is_last in audio_chunk_iter:
            chunks.append(chunk)
        audio_bytes = b"".join(chunks)

        t0 = time.perf_counter()
        asr_text = await self.asr.transcribe_once(audio_bytes)
        t.asr = time.perf_counter() - t0
        await ws.send_json({"type": "asr_final", "text": asr_text})

        if not asr_text.strip():
            await ws.send_json({"error": "未识别到语音"})
            return PipelineResult(error="未识别到语音", timings=t)

        t0 = time.perf_counter()
        answer_text = await self.llm.generate_once(asr_text)
        t.llm = time.perf_counter() - t0
        await ws.send_json({"type": "answer", "text": answer_text})

        t0 = time.perf_counter()
        tts_audio = await self.tts.synthesize_once(answer_text)
        t.tts = time.perf_counter() - t0
        audio_b64 = base64.b64encode(tts_audio).decode()
        await ws.send_json({"type": "audio", "data": audio_b64,
                            "timings": {"asr": round(t.asr, 2), "llm": round(t.llm, 2),
                                        "tts": round(t.tts, 2),
                                        "total": round(time.perf_counter() - t_start, 2)}})

        t.total = time.perf_counter() - t_start
        t.first_audio = t.total

        logger.info(f"[W1] asr={t.asr:.2f}s  llm={t.llm:.2f}s  tts={t.tts:.2f}s  "
                    f"total={t.total:.2f}s  first_audio={t.first_audio:.2f}s")

        return PipelineResult(asr_text=asr_text, answer_text=answer_text,
                              tts_audio=tts_audio, timings=t)
