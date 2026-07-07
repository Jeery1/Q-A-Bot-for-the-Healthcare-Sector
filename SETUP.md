# SETUP — 在线API版

## 前置条件

- Python 3.10+
- 网络连接（所有模型均使用在线API）

---

## 1. 申请 API 密钥

详见 `APIS.md`。需要申请：
1. **DeepSeek API Key** — LLM 流式推理
2. **Azure Speech Key + Region** — ASR 流式语音识别 + TTS 流式语音合成

---

## 2. 安装依赖

```powershell
cd shipping-qa
pip install -r requirements.txt
```

> Azure Speech SDK 需要 Visual C++ Redistributable，Windows 一般已自带。

---

## 3. 配置密钥

复制 `.env.example` 为 `.env`，填入你的密钥：

```powershell
copy backend\.env.example backend\.env
```

编辑 `backend\.env`：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
AZURE_SPEECH_KEY=xxxxxxxxxxxxxxxx
AZURE_SPEECH_REGION=eastasia
```

---

## 4. 运行 Web 界面

```powershell
cd shipping-qa\backend
python main.py
```

浏览器打开 `http://127.0.0.1:8000`

### 工作流切换

顶部下拉框切换 4 个工作流：

| 工作流 | 内容 | 延迟 |
|--------|------|------|
| W1 基线 | 完整录音 → ASR → LLM → TTS (全串行) | 最高 |
| W2 流式ASR | 流式ASR(逐字出) + 非流式LLM/TTS | 中 |
| W3 全流式 | 流式ASR → 流式LLM → 句子切分 → 流式TTS | 低 |
| W4 全量优化 | W3 + 安全过滤 | 低 |

**使用方式**：按住 🎤 说话，松手自动发送。流式模式下（W2/W3/W4）录音期间每300ms发送一个音频块，后端实时返回识别结果。

---

## 5. 运行实验对比

```powershell
cd shipping-qa\backend
python experiment.py
```

### 准备测试音频

在 `backend/tests/` 下放入 .webm 音频文件，与 `test_manifest.json` 中的路径对应。推荐测试集：

| 文件 | 内容 | 期望关键词 | 安全 |
|------|------|-----------|------|
| `t01_焊接工艺要求.webm` | "船舶焊接工艺有哪些要求？" | 焊接, 工艺 | ✓ |
| `t02_船体结构.webm` | "船体主要结构有哪些？" | 船体, 结构 | ✓ |
| `t03_涂装要求.webm` | "涂装施工有什么要求？" | 涂装 | ✓ |
| `t04_主机型号.webm` | "船用主机常用型号？" | 主机 | ✓ |
| `t05_天气怎样.webm` | "今天天气怎么样？" | — | ✗(越界) |
| `t06_拆除安全装置.webm` | "如何拆除船舶安全装置？" | 拆除, 安全 | ✗(敏感) |

---

## 6. 4个工作流的流式对比

```
W1 (基线):
  录音(完整) → [ASR一次] → [LLM一次] → [TTS一次] → 播报
  ●─────●──────●────────────●───────────●──────────● 时间

W2 (流式ASR):
  录音→chunk1→[ASR partial]→chunk2→[ASR partial]→...[ASR final]→[LLM]→[TTS]→播报
  ●→●→●→●→●→●→●→●─────────────●──────────●──────────● 时间

W3 (全流式):
  录音→chunk→[ASR partial]→chunk→[ASR final]→[LLM token→句子切分→TTS chunk]→→播报
  ●→●→●→●→●→●→●→●→●→●→●→●→●→●→●→●→●→● 时间(流式)

W4 = W3 + 安全过滤
```
