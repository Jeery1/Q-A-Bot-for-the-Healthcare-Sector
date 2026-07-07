# API 密钥清单 — 需要你手动申请

本项目所有模型均使用在线 API，以下是你需要申请的密钥：

---

## 1. DeepSeek API（LLM 流式推理）

| 项目 | 说明 |
|------|------|
| 用途 | 问答模型，支持 `stream=True` 流式返回 tokens |
| 费用 | 极低 (~1元/百万 tokens)，注册送 500 万 tokens |
| 申请地址 | https://platform.deepseek.ai/api_keys |
| 需要填写 | `DEEPSEEK_API_KEY` |

---

## 2. Azure Speech（ASR 语音识别 + TTS 语音合成）

| 项目 | 说明 |
|------|------|
| 用途 | ASR：实时语音识别（流式 partial result） |
| | TTS：文本转语音（流式音频 chunk） |
| 费用 | 免费层：ASR 5小时/月，TTS 50万字符/月 |
| 申请地址 | https://portal.azure.com → 创建 Speech 资源 |
| 需要填写 | `AZURE_SPEECH_KEY` + `AZURE_SPEECH_REGION` |
| 推荐区域 | `eastasia` 或 `chinaeast2` |

### Azure 开通步骤

1. 访问 https://portal.azure.com （学生可用 `xxx@tongji.edu.cn` 注册学生版，获 $100 免费额度）
2. 创建 → AI + 机器学习 → Speech
3. 选择 F0 免费层定价
4. 创建完成后，在「密钥和终结点」中复制 Key 和 Region

---

## 3. 环境变量配置

创建 `backend/.env` 文件（或直接设置系统环境变量）：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
AZURE_SPEECH_KEY=xxxxxxxxxxxxxxxx
AZURE_SPEECH_REGION=eastasia
```

---

## 4. 可选的替代方案

如果某个 API 申请遇到问题，以下为平替方案：

| 模块 | 首选 | 备选 |
|------|------|------|
| LLM | DeepSeek API | 阿里云 Qwen API / Moonshot API |
| ASR | Azure Speech | 阿里云 实时语音识别 / 讯飞语音听写 |
| TTS | Azure Speech | edge-tts（无密钥） / 阿里云 TTS |

> 所有 API 密钥**仅保存在本地**，不会上传或泄露。
