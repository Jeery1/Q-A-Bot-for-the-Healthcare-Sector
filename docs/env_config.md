# 模块版本与环境配置

## 运行环境

本项目为在线 API 版语音问答系统。推荐在 Windows 环境运行。

| 项目 | 配置 |
|---|---|
| Python | 3.10 或更高 |
| 后端框架 | FastAPI |
| 服务启动 | uvicorn |
| ASR | Azure Speech SDK |
| LLM | DeepSeek API |
| TTS | Azure Speech SDK |
| 前端 | 浏览器 WebSocket + AudioContext |
| 实验脚本 | `backend/experiment.py` |

## Python 依赖

依赖文件为 `requirements.txt`。

```text
fastapi
uvicorn[standard]
azure-cognitiveservices-speech
httpx
python-dotenv
```

安装命令如下。

```powershell
pip install -r requirements.txt
```

## API 配置

复制环境变量模板。

```powershell
copy backend\.env.example backend\.env
```

填写 `backend/.env`。

```env
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
AZURE_SPEECH_KEY=your-azure-speech-key
AZURE_SPEECH_REGION=eastasia
TTS_VOICE=zh-CN-XiaoxiaoNeural
```

| 变量 | 用途 |
|---|---|
| `DEEPSEEK_API_KEY` | LLM 回答与安全分类 |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | LLM 模型名称 |
| `AZURE_SPEECH_KEY` | Azure Speech 密钥 |
| `AZURE_SPEECH_REGION` | Azure Speech 区域 |
| `TTS_VOICE` | 中文 TTS 音色 |

## 系统启动

进入后端目录。

```powershell
cd backend
python main.py
```

浏览器访问：

```text
http://127.0.0.1:8000
```

## 管线模式

| 模式 | 流程 |
|---|---|
| W1 基线 | 完整 ASR -> 完整 LLM -> 完整 TTS |
| W2 全流式 | 流式 ASR -> 流式 LLM -> 句级 TTS |
| W3 安全 | W2 + 安全门控 |

## 实验运行

完整实验：

```powershell
python backend\experiment.py
```

安全门控实验：

```powershell
python backend\experiment.py --safety-only
```

实验脚本读取以下文件。

```text
backend/test_manifest.json
backend/tests/*.wav
```

测试集包含 6 条样本。样本覆盖造船问答、越界问题和危险问题。

```text
backend/tests/t01_焊接工艺要求.wav
backend/tests/t02_船体结构.wav
backend/tests/t03_涂装要求.wav
backend/tests/t04_主机型号.wav
backend/tests/t05_天气怎样.wav
backend/tests/t06_拆除安全装置.wav
```

## 注意事项

- `.env` 包含密钥。不要提交。
- Azure Speech 用于 ASR 和 TTS。
- DeepSeek 用于主回答和安全分类。
- 浏览器需要麦克风权限。
