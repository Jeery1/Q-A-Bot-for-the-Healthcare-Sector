# 队员B 工作清单

> 项目：船舶建造安全低延迟语音问答系统  
> 更新日期：2026-06-12

---

## ✅ 已完成

| 编号 | 任务 | 交付物 | 状态 |
|------|------|--------|------|
| B1 | 申请 DeepSeek API Key | `sk-3b8c5...` | ✅ |
| B2 | 申请 Azure Speech Key + Region | `southeastasia` | ✅ |
| B3 | 配置 `.env` + `.gitignore` 保密 | `backend/.env`、`.gitignore` | ✅ |
| B4 | 领域对话数据收集（200 条） | `data/shipbuilding_dialogues.json` | ✅ |

### B4 数据集详情

- **条目数**：200 条
- **分类数**：10 大类（船舶类型与设计、船体建造工艺、焊接工艺、涂装与防腐、轮机工程、电气与自动化、安全规范、质量检验、材料与标准、舾装工程）
- **难度分级**：basic / intermediate / advanced
- **来源标注**：textbook / standard / practice / regulation
- **JSON Schema**：`id`、`category`、`subcategory`、`question`、`answer`、`keywords`、`difficulty`、`source_type`

---

## ⬜ 待定（视情况）

| 编号 | 任务 | 前置条件 | 说明 |
|------|------|----------|------|
| B5 | 模型微调 | ① B4 数据充足 ② 系统确认跑通 ③ 组长确认需要 | 基于 GPT2-Dialogbot 或 ChatGLM 在 B4 数据上微调，替换 DeepSeek API。若系统运行正常且 DeepSeek API 响应质量可接受，可能不需要执行 |

### B5 触发条件

满足以下**任意一条**即启动 B5：

1. 组长明确要求做微调（满足 A1 考核加分）
2. DeepSeek API 在造船领域的回答质量不满足答辩要求
3. 其他队员工作已收尾，有时间做深一步优化

---

## 📦 已交付文件清单

```
security_group_assignment/
├── .gitignore                          ← B3 新增
├── backend/
│   └── .env                            ← B3 新增（含 API Key，已 gitignore）
├── data/
│   └── shipbuilding_dialogues.json     ← B4 新增（200 条造船领域问答）
```

---

## ⚠️ 当前阻塞项（非队员B职责）

| 问题 | 负责人 | 影响 |
|------|--------|------|
| ASR 识别失败（`transcribe_once` 回调未触发） | 队员A | 系统无法正常问答，B5 无法验证 |
| 测试音频未录制 | 队员C | 实验无法运行 |

---

## 📋 后续建议

1. **等待队员A修复 ASR** → 验证系统完整问答流程
2. **确认 B4 数据是否满足组长预期** → 如需补充特定领域可快速追加
3. **组长下达 B5 启动指令** → 开始微调工作
4. **协助答辩准备** → 提供 B4 数据统计和分类说明给队员D用于 PPT

---

## 💡 备注

- B4 数据为 CSV/JSON 双格式可用，若组长需要其他格式可快速转换
- 数据集已在 `_schema` 字段中标注了 answer 长度分级和分类体系，可直接用于 PPT 中的"领域数据"展示
- 如需扩充数据集，运行 `python data/expand_data.py` 或 `python data/final_batch.py`
