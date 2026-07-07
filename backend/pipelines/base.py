from dataclasses import dataclass, field
from typing import Optional, AsyncIterator


@dataclass
class TimingMetrics:
    asr: float = 0.0
    llm: float = 0.0
    llm_ttfb: float = 0.0
    tts: float = 0.0
    total: float = 0.0
    first_audio: Optional[float] = None

    def __str__(self):
        parts = [f"ASR={self.asr:.1f}s", f"LLM={self.llm:.1f}s",
                 f"TTS={self.tts:.1f}s", f"total={self.total:.1f}s"]
        if self.first_audio is not None:
            parts.append(f"first_audio={self.first_audio:.1f}s")
        return "  ".join(parts)


@dataclass
class PipelineResult:
    asr_text: str = ""
    answer_text: str = ""
    tts_audio: bytes = b""
    timings: TimingMetrics = field(default_factory=TimingMetrics)
    metrics: dict = field(default_factory=dict)
    error: Optional[str] = None


class BasePipeline:
    name: str = "base"
    description: str = ""

    async def run(self, audio_bytes: bytes) -> PipelineResult:
        """Non-streaming: full audio in, result out."""
        raise NotImplementedError

    async def run_stream(self, audio_chunk_iter, ws):
        """
        Streaming: feed audio chunks iteratively, send intermediate results via ws.
        Returns the final PipelineResult.
        """
        raise NotImplementedError
