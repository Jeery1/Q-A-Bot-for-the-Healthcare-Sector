"""
Streaming ASR using Azure Speech Services.
"""

import asyncio
import logging
import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)


class StreamingASR:
    """Azure Speech-to-Text with streaming (partial + final results)."""

    def __init__(self, key: str, region: str):
        self._config = speechsdk.SpeechConfig(subscription=key, region=region)
        self._config.speech_recognition_language = "zh-CN"
        self._config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_EnableAudioLogging, "False"
        )

    async def transcribe_stream(self, audio_chunk_iter):
        """
        Feed audio chunks from an async iterator, yield (type, text) where type is
        "partial" or "final".  Uses a sentinel on the result queue to avoid
        the race between call_soon_threadsafe callbacks and Event.set().
        """
        _SENTINEL = object()

        logger.info("[ASR] transcribe_stream start")
        push_stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=self._config, audio_config=audio_config
        )

        loop = asyncio.get_event_loop()
        result_queue = asyncio.Queue()

        def _on_partial(evt):
            if evt.result.reason == speechsdk.ResultReason.RecognizingSpeech and evt.result.text:
                logger.info(f"[ASR] partial: {evt.result.text!r}")
                loop.call_soon_threadsafe(result_queue.put_nowait, ("partial", evt.result.text))

        def _on_final(evt):
            logger.info(f"[ASR] final: {evt.result.text!r} reason={evt.result.reason}")
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
                loop.call_soon_threadsafe(result_queue.put_nowait, ("final", evt.result.text))
            loop.call_soon_threadsafe(result_queue.put_nowait, _SENTINEL)

        def _on_cancel(evt):
            logger.warning(f"[ASR] cancelled: reason={evt.result.reason} "
                           f"code={evt.result.cancellation_details.error_code} "
                           f"details={evt.result.cancellation_details.error_details}")
            loop.call_soon_threadsafe(result_queue.put_nowait, _SENTINEL)

        recognizer.recognizing.connect(_on_partial)
        recognizer.recognized.connect(_on_final)
        recognizer.canceled.connect(_on_cancel)

        logger.info("[ASR] start_continuous_recognition")
        recognizer.start_continuous_recognition()

        chunk_count = 0
        total_bytes = 0

        async def _feed():
            nonlocal chunk_count, total_bytes
            logger.info("[ASR] _feed start")
            async for chunk in audio_chunk_iter:
                chunk_count += 1
                total_bytes += len(chunk)
                if chunk_count <= 3 or chunk_count % 10 == 0:
                    logger.debug(f"[ASR] feed chunk#{chunk_count} size={len(chunk)} total={total_bytes}")
                push_stream.write(chunk)
            logger.info(f"[ASR] _feed done: {chunk_count} chunks, {total_bytes} bytes")
            push_stream.close()

        feed_task = asyncio.create_task(_feed())

        # All results (partial/final) + sentinel come through this queue
        logger.info("[ASR] waiting for results...")
        result_count = 0
        while True:
            item = await result_queue.get()
            if item is _SENTINEL:
                logger.info(f"[ASR] sentinel received, total results={result_count}")
                break
            result_count += 1
            yield item

        logger.info("[ASR] stop_continuous_recognition")
        recognizer.stop_continuous_recognition()
        await feed_task
        logger.info("[ASR] transcribe_stream end")

    async def transcribe_once(self, audio_bytes: bytes) -> str:
        push_stream = speechsdk.audio.PushAudioInputStream()
        push_stream.write(audio_bytes)
        push_stream.close()
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=self._config, audio_config=audio_config
        )
        fut = asyncio.get_event_loop().create_future()

        def _on_result(evt):
            if not fut.done():
                if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                    fut.set_result(evt.result.text)
                else:
                    fut.set_result("")

        def _on_cancel(evt):
            if not fut.done():
                fut.set_result("")

        recognizer.recognized.connect(_on_result)
        recognizer.canceled.connect(_on_cancel)
        recognizer.recognize_once()
        return await fut
