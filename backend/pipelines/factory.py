from streaming.asr_azure import StreamingASR
from streaming.llm_api import StreamingLLM
from streaming.tts_azure import StreamingTTS
from .w1_baseline import W1Baseline
from .w2_full_stream import W2FullStreaming
from .w3_secure_stream import W3SecureStreaming

_pipelines = {}


def init_pipelines(asr: StreamingASR, llm: StreamingLLM, tts: StreamingTTS):
    global _pipelines
    _pipelines = {
        "w1": W1Baseline(asr, llm, tts),
        "w2": W2FullStreaming(asr, llm, tts),
        "w3": W3SecureStreaming(asr, llm, tts),
    }


def get_pipeline(name: str):
    return _pipelines.get(name)


def list_pipelines():
    return {k: v.description for k, v in _pipelines.items()}
