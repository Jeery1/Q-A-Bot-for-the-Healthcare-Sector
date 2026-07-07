# 船舶建造智能语音问答系统

船舶建造领域的**低延迟流式语音交互系统**，用户说出问题后逐字显示回答并流式播放语音，首段音频延迟从 44s 降至 18s（加速 2.4×）。

## 架构

```
前端 (Vue 3) ←── WebSocket ──→ FastAPI 管线调度
                                     │
                    ┌────────────────┼────────────────┐
                    ↓                ↓                ↓
                 W1 基线         W2 全流式        W3 安全流式
              (顺序执行)       (流式并行)     (W2 + LLM 门控)
                    │                │                │
                    └────────────────┼────────────────┘
                                     ↓
              Azure ASR ──→ DeepSeek API ──→ Azure TTS
```

## 管线对比

| | W1 基线 | W2 全流式 | W3 安全流式 |
|---|---|---|---|
| ASR | 累积后一次识别 | 流式（实时 partial） | 同 W2 |
| LLM | 一次性生成全文 | 逐 token 流式 | 同 W2 |
| TTS | 全文一次合成 | 句级并行合成（3 worker） | 同 W2 |
| 安全门控 | — | — | LLM 分类 + 短路拒绝 |
| 文字显示 | TTS 完成后 | 逐 token 实时 | 逐 token 实时 |

## 快速开始

**环境要求**

- Python 3.10+
- Azure Speech Services 订阅
- DeepSeek API Key

**配置**

```bash
git clone <repo-url>
cd security_group_assignment
pip install -r requirements.txt
cp backend/.env.example backend/.env
# 编辑 backend/.env 填入 AZURE_SPEECH_KEY 和 DEEPSEEK_API_KEY
```

**启动**

```bash
cd backend
python main.py
# 浏览器打开 http://127.0.0.1:8000
```


## 项目结构

```
├── frontend/
│   └── index.html          # Vue 3 单页（CDN 引入，零构建）
├── backend/
│   ├── main.py             # FastAPI + WebSocket 入口
│   ├── experiment.py       # W1 vs W2 延迟对比实验
│   ├── config.py           # 环境变量 & API 配置
│   ├── safety.py           # 安全关键词表（备用）
│   ├── sentence_splitter.py # 流式分句器（。！？+ 超长强制切分）
│   ├── domain_knowledge.py  # RAG 领域语料检索
│   ├── streaming/
│   │   ├── asr_azure.py    # Azure 流式语音识别
│   │   ├── llm_api.py      # DeepSeek 流式 + 安全分类
│   │   └── tts_azure.py    # Azure TTS（SSML）
│   ├── pipelines/
│   │   ├── base.py         # PipelineResult / TimingMetrics
│   │   ├── factory.py      # 管线注册
│   │   ├── w1_baseline.py  # W1 顺序执行
│   │   ├── w2_full_stream.py # W2 全流式 + 并行 TTS
│   │   └── w3_secure_stream.py # W3 安全流式
│   └── tests/              # 测试用 WAV 录音
└── data/
    └── shipbuilding_dialogues.json  # 领域语料（200 条造船问答）
```


## 技术要点

**并行 TTS 合成** — 3 个异步合成器从共享队列抢句子，`asyncio.Queue` + 序号有序重组 `_output_sender`，合成阶段从串行 `sum(句)` 变为并行 `max(句)`。

**LLM 安全门控** — `classify_safety()` 用同 API 轻量分类（max_tokens=64, temperature=0），区分敏感输入 / 无关话题并短路拒绝，约 0.5s 延迟。

**领域知识注入（RAG）** — `build_domain_context()` 关键词检索 `shipbuilding_dialogues.json`，匹配 topic + terms + turns，注入 system prompt 提升术语一致性。

**流式分句** — `SentenceSplitter` 检测 `。！？` 边界 + 超 100 字符时沿换行/标点强制切分，兼顾正确句法和极端长文本。

**Markdown 过滤** — `_strip_markdown()` 在 TTS 合成前去掉 `#`、`**bold**`、`~~strikethrough~~`、`` `code` `` 等符号。
