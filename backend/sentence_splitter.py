"""
Sentence boundary detection for streaming LLM output.
Splits text into complete sentences suitable for TTS.
"""

import re
import logging

logger = logging.getLogger(__name__)

_SENTENCE_CHARS = re.compile(r'[。！？]$')
_SENTENCE_SPLIT = re.compile(r'(?<=[。！？])')

_FORCE_SPLITTERS = ['\n\n', '\n', '；', '，', '、', '：', '）', ')', ' ', ',']


class SentenceSplitter:
    def __init__(self, max_len: int = 100):
        self.buffer = ""
        self.max_len = max_len

    def feed(self, text: str) -> list[str]:
        """Feed new text, return any complete sentences detected."""
        self.buffer += text
        segments = _SENTENCE_SPLIT.split(self.buffer)

        complete = []
        i = 0
        while i < len(segments):
            seg = segments[i]
            if not seg or not seg.strip():
                i += 1
                continue
            stripped = seg.strip()
            if _SENTENCE_CHARS.search(stripped) and len(stripped) > 2:
                logger.info(f"[Splitter] detected: {stripped!r}")
                complete.append(stripped)
                i += 1
            elif len(stripped) >= self.max_len:
                part, remaining = self._force_split(stripped)
                logger.info(f"[Splitter] force-split ({len(stripped)} chars): {part!r}")
                complete.append(part.strip())
                self.buffer = remaining + "".join(segments[i + 1:])
                break
            else:
                self.buffer = "".join(segments[i:])
                break
        else:
            self.buffer = ""

        return complete

    def _force_split(self, text: str) -> tuple:
        """Split long text at the most natural break point within max_len."""
        chunk = text[:self.max_len]
        for delim in _FORCE_SPLITTERS:
            idx = chunk.rfind(delim)
            if idx > self.max_len // 2:
                idx += len(delim)
                return text[:idx], text[idx:]
        return text[:self.max_len], text[self.max_len:]

    def flush(self) -> list[str]:
        """Return any remaining text in buffer and reset."""
        remainder = self.buffer.strip()
        self.buffer = ""
        if remainder and len(remainder) > 1:
            return [remainder]
        return []

    def has_remainder(self) -> bool:
        return len(self.buffer.strip()) > 0
