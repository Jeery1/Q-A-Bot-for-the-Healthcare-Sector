"""
Pipeline experiment for the shipbuilding voice QA system.

Metrics:
- Latency: user audio ready -> first playable answer audio.
- ASR recall: expected domain keywords found in ASR text.
- W3 safety accuracy: safe questions pass, unsafe/out-of-domain questions are blocked.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from config import *
from streaming.llm_api import StreamingLLM

BASE_DIR = Path(__file__).parent
TESTS_DIR = BASE_DIR / "tests"
MANIFEST_PATH = BASE_DIR / "test_manifest.json"
DEFAULT_RUNS = 3
SEPARATOR = "=" * 78


def load_test_cases(manifest_path: Path = MANIFEST_PATH) -> list[dict]:
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    for tc in manifest:
        audio = TESTS_DIR / Path(tc["audio"]).name
        tc["audio_path"] = audio
        tc["audio_available"] = audio.exists() and audio.stat().st_size > 1024
    return manifest


def keyword_recall(text: str, keywords: list[str]) -> float | None:
    if not keywords:
        return None
    hits = sum(1 for kw in keywords if kw in text)
    return hits / len(keywords)


async def run_audio_case(pipeline, tc: dict, label: str, run_id: int) -> dict | None:
    audio_bytes = tc["audio_path"].read_bytes()
    start = time.perf_counter()
    result = await pipeline.run(audio_bytes)
    wall = time.perf_counter() - start

    if result.error:
        print(f"  [{label}] run {run_id}: ERROR - {result.error}")
        return None

    timings = result.timings
    first_audio = timings.first_audio if timings.first_audio is not None else timings.total
    recall = keyword_recall(result.asr_text, tc.get("expected_asr_keywords", []))
    safety_actual = result.metrics.get("safe")

    print(
        f"  [{label}] run {run_id}: "
        f"first_audio={first_audio:.2f}s  total={timings.total:.2f}s  "
        f"asr={timings.asr:.2f}s  llm_ttfb={timings.llm_ttfb:.2f}s  "
        f"recall={recall if recall is not None else 'N/A'}  wall={wall:.2f}s"
    )

    return {
        "id": tc["id"],
        "pipeline": label.lower(),
        "first_audio": first_audio,
        "total": timings.total,
        "asr": timings.asr,
        "llm": timings.llm,
        "llm_ttfb": timings.llm_ttfb,
        "recall": recall,
        "asr_text": result.asr_text,
        "answer_text": result.answer_text,
        "safe": safety_actual,
    }


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_latency(rows: list[dict]) -> list[dict]:
    summary = []
    for pipeline in ("w1", "w2", "w3"):
        subset = [r for r in rows if r["pipeline"] == pipeline]
        if not subset:
            continue
        first = [r["first_audio"] for r in subset if r["first_audio"] is not None]
        total = [r["total"] for r in subset if r["total"] is not None]
        recalls = [r["recall"] for r in subset if r["recall"] is not None]
        summary.append({
            "pipeline": pipeline,
            "first_audio_avg": average(first),
            "total_avg": average(total),
            "asr_recall_avg": average(recalls),
            "runs": len(subset),
        })
    return summary


async def run_latency_experiment(cases: list[dict], runs: int) -> list[dict]:
    from streaming.asr_azure import StreamingASR
    from streaming.tts_azure import StreamingTTS
    from pipelines.factory import init_pipelines, get_pipeline

    safe_audio_cases = [tc for tc in cases if tc.get("safe", True) and tc["audio_available"]]
    if not safe_audio_cases:
        print("没有可用于延迟实验的安全音频用例。")
        return []

    asr = StreamingASR(AZURE_SPEECH_KEY, AZURE_SPEECH_REGION)
    llm = StreamingLLM(DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)
    tts = StreamingTTS(AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, TTS_VOICE)
    init_pipelines(asr, llm, tts)

    pipelines = {
        "W1": get_pipeline("w1"),
        "W2": get_pipeline("w2"),
        "W3": get_pipeline("w3"),
    }
    rows = []

    print(f"\n{SEPARATOR}")
    print("  延迟实验：W1 基线 vs W2 全流式 vs W3 安全流式")
    print("  度量：音频就绪 -> 首段有效回答音频合成完成")
    print(f"  每个音频用例运行 {runs} 次")
    print(SEPARATOR)

    for tc in safe_audio_cases:
        print(f"\n{'-' * 62}")
        print(f"  {tc['id']}: {tc['audio_path'].name}  text={tc.get('text', '')}")
        print(f"{'-' * 62}")
        for i in range(1, runs + 1):
            for label, pipeline in pipelines.items():
                row = await run_audio_case(pipeline, tc, label, i)
                if row:
                    rows.append(row)

    summary = summarize_latency(rows)
    print(f"\n{SEPARATOR}")
    print("  延迟汇总")
    print(SEPARATOR)
    print(f"  {'管线':<8} {'首段延迟(s)':>12} {'总延迟(s)':>12} {'ASR召回':>10} {'runs':>6}")
    print(f"  {'-' * 56}")
    for item in summary:
        first = item["first_audio_avg"]
        total = item["total_avg"]
        recall = item["asr_recall_avg"]
        print(
            f"  {item['pipeline']:<8} "
            f"{first:>12.2f} {total:>12.2f} "
            f"{(recall if recall is not None else 0):>10.2f} {item['runs']:>6}"
        )
    return rows


async def run_safety_experiment(llm: StreamingLLM, cases: list[dict]) -> list[dict]:
    print(f"\n{SEPARATOR}")
    print("  W3 安全门控实验")
    print("  度量：safe 样本应放行；out_of_domain/sensitive 样本应拦截")
    print(SEPARATOR)

    rows = []
    for tc in cases:
        expected_safe = bool(tc.get("safe", True))
        text = tc.get("text", "")
        result = await llm.classify_safety(text)
        actual_safe = bool(result.get("safe", True))
        correct = actual_safe == expected_safe
        rows.append({
            "id": tc["id"],
            "text": text,
            "expected_safe": expected_safe,
            "actual_safe": actual_safe,
            "reason": result.get("reason", ""),
            "source": result.get("source", ""),
            "correct": correct,
        })
        mark = "OK" if correct else "FAIL"
        print(
            f"  {mark:<4} {tc['id']:<4} expected={expected_safe!s:<5} "
            f"actual={actual_safe!s:<5} reason={result.get('reason', ''):<13} text={text}"
        )

    correct_count = sum(1 for row in rows if row["correct"])
    total = len(rows)
    accuracy = correct_count / total if total else 0.0
    print(f"\n  安全准确率: {correct_count}/{total} = {accuracy:.2%}")
    return rows


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--safety-only", action="store_true", help="only run W3 text safety gate tests")
    args = parser.parse_args()

    cases = load_test_cases(Path(args.manifest))

    print("初始化实验配置...")
    llm = StreamingLLM(DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)

    missing_audio = [tc for tc in cases if not tc["audio_available"]]
    if missing_audio:
        print("\n以下用例缺少有效音频，将只参与文本安全门控评测：")
        for tc in missing_audio:
            print(f"  - {tc['id']}: {tc['audio']}")

    if not args.safety_only:
        await run_latency_experiment(cases, args.runs)
    await run_safety_experiment(llm, cases)


if __name__ == "__main__":
    asyncio.run(main())
