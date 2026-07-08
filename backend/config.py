import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / "backend" / ".env")

# DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Azure Speech
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "eastasia")
TTS_VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")

# RAG
RAG_ENABLED = os.getenv("RAG_ENABLED", "true").lower() == "true"
RAG_PERSIST_DIR = os.getenv("RAG_PERSIST_DIR", str(BASE_DIR / "data" / "healthcare_rag"))
RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "models/text2vec-base-chinese")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))

# Server
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
