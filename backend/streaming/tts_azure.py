"""
TTS using Azure Speech Services (synchronous API).
"""

import asyncio
import logging
from xml.sax.saxutils import escape as xml_escape
from azure.cognitiveservices import speech as speechsdk

logger = logging.getLogger(__name__)


class StreamingTTS:
    """Azure TTS with streaming audio output."""

    def __init__(self, key: str, region: str, voice: str = "zh-CN-XiaoxiaoNeural"):
        self._config = speechsdk.SpeechConfig(subscription=key, region=region)
        self._voice = voice

    async def synthesize_stream(self, text: str):
        """Synthesize text to speech, yield audio chunks (bytes)."""
        audio_bytes = await self.synthesize_once(text)
        if audio_bytes:
            yield audio_bytes

    async def synthesize_once(self, text: str) -> bytes:
        """Non-streaming: return full audio bytes."""
        ssml = self._build_ssml(text)

        def _synth():
            pull_stream = speechsdk.audio.PullAudioOutputStream()
            audio_config = speechsdk.audio.AudioOutputConfig(stream=pull_stream)
            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=self._config, audio_config=audio_config
            )
            result = synthesizer.speak_ssml(ssml)
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                data = result.audio_data or pull_stream.read(pull_stream.size())
                return data
            detail = getattr(result, 'error_details', None)
            if detail is None and result.reason == speechsdk.ResultReason.Canceled:
                cancel = getattr(result, 'cancellation_details', None)
                if cancel:
                    detail = getattr(cancel, 'error_details', str(cancel))
            logger.error(
                f"TTS synthesis failed: reason={result.reason} "
                f"details={detail}"
            )
            return b""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _synth)

    def _build_ssml(self, text: str) -> str:
        safe_text = xml_escape(text)
        return (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xml:lang="zh-CN">'
            f'<voice name="{self._voice}">'
            f'{safe_text}'
            f'</voice></speak>'
        )
