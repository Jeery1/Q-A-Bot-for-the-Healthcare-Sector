"""
FastAPI server with WebSocket streaming support.
Select workflow via query param: ws://host/ws?mode=w1~w4
"""

import json
import logging
import traceback

logging.basicConfig(level=logging.INFO)
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import *
from streaming.asr_azure import StreamingASR
from streaming.llm_api import StreamingLLM
from streaming.tts_azure import StreamingTTS
from pipelines.factory import init_pipelines, get_pipeline, list_pipelines

app = FastAPI(title="船舶建造智能问答系统 — 流式管线版")

asr = StreamingASR(AZURE_SPEECH_KEY, AZURE_SPEECH_REGION)
llm = StreamingLLM(DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)
tts = StreamingTTS(AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, TTS_VOICE)
init_pipelines(asr, llm, tts)


@app.get("/pipelines")
async def get_pipelines():
    return list_pipelines()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, mode: str = Query("w1")):
    await ws.accept()
    pipeline = get_pipeline(mode)
    if pipeline is None:
        await ws.send_json({"error": f"未知工作流: {mode}"})
        await ws.close()
        return

    try:
        while True:
            await pipeline.run_stream(_iter_audio_chunks(ws), ws)

    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:
        traceback.print_exc()
        try:
            await ws.send_json({"error": str(e)})
        except Exception:
            pass


async def _iter_audio_chunks(ws):
    """
    Async generator that yields (chunk_bytes, is_last).
    Audio chunks are binary WebSocket messages.
    Send {"type": "audio_end"} as text to signal end of utterance.
    """
    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            break
        if "bytes" in msg:
            yield (msg["bytes"], False)
        elif "text" in msg:
            data = json.loads(msg["text"])
            if data.get("type") in ("audio_end", "stop"):
                yield (b"", True)
                break
            yield (b"", True)
            break


app.mount("/", StaticFiles(directory=str(Path(__file__).parent.parent / "frontend"), html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
