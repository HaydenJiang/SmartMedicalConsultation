"""
抽取效果对比评测：自部署微调模型(vLLM) vs 云端大模型 API

- 数据集：data/finetune/ft_extract.json 全部样本（instruction/input/gold output）
- 公平性：两个模型用**完全相同**的提示词（样本自带 instruction 作 system、input 作 user），
  相同的裸调用 + JSON 解析方式；唯一差异是模型本身（vLLM 侧 max_tokens=2048 为失控保险丝）。
- 指标：
  * JSON 有效率：输出能解析且含 SimpleLLMOutput 必备字段
  * 实体名集合 P/R/F1：五个列表字段 + 疾病名，逐样本算再取宏平均
  * 延迟：mean / P95（含网络）
  * token：prompt/completion 总量（供成本核算）

Usage:
    python evals/extract_finetune_vs_cloud.py
    python evals/extract_finetune_vs_cloud.py --limit 50     # 快速冒烟
"""

import sys
import json
import time
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from tqdm import tqdm
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from config.settings import settings

FT_FILE = PROJECT_ROOT / "data" / "finetune" / "ft_extract.json"
OUT_FILE = PROJECT_ROOT / "evals" / "results" / "extract_ft_vs_cloud.json"

FIELDS = ("symptoms", "medications", "departments", "examinations", "body_parts")
REQUIRED_KEYS = ("disease",) + FIELDS


# ============================================================
# 解析与打分
# ============================================================

def parse_json(raw: str):
    """裸调用输出解析：剥 ```json 围栏，截取首个 { 到末个 }，校验必备字段。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not all(k in data for k in REQUIRED_KEYS):
        return None
    return data


def name_set(d: dict) -> set:
    names = {n for f in FIELDS for n in (d.get(f) or []) if isinstance(n, str) and n.strip()}
    disease_name = ((d.get("disease") or {}).get("name") or "").strip()
    if disease_name:
        names.add(disease_name)
    return names


def prf(pred: set, gold: set):
    if not pred and not gold:
        return 1.0, 1.0, 1.0
    inter = len(pred & gold)
    p = inter / len(pred) if pred else 0.0
    r = inter / len(gold) if gold else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


# ============================================================
# 单模型评测
# ============================================================

def call_one(llm, instruction: str, text: str) -> dict:
    t0 = time.time()
    try:
        resp = llm.invoke([SystemMessage(content=instruction), HumanMessage(content=text)])
        content = resp.content
        usage = resp.response_metadata.get("token_usage") or {}
        ok = True
    except Exception as e:
        content, usage, ok = "", {}, False
    dt = time.time() - t0
    return {
        "content": content,
        "latency": dt,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "call_ok": ok,
    }


def eval_model(tag: str, llm, samples: list, workers: int) -> dict:
    results = [None] * len(samples)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(call_one, llm, s["instruction"], s["input"]): i
            for i, s in enumerate(samples)
        }
        for fut in tqdm(as_completed(futs), total=len(futs), desc=tag, unit="sample"):
            results[futs[fut]] = fut.result()

    # 打分
    ps, rs, f1s, valid, latencies = [], [], [], 0, []
    prompt_tok = comp_tok = 0
    for res, s in zip(results, samples):
        latencies.append(res["latency"])
        prompt_tok += res["prompt_tokens"]
        comp_tok += res["completion_tokens"]
        pred = parse_json(res["content"]) if res["call_ok"] else None
        if pred is not None:
            valid += 1
            p, r, f1 = prf(name_set(pred), name_set(json.loads(s["output"])))
            ps.append(p); rs.append(r); f1s.append(f1)
        else:
            ps.append(0.0); rs.append(0.0); f1s.append(0.0)

    latencies.sort()
    return {
        "n": len(samples),
        "valid_rate": valid / len(samples),
        "precision": sum(ps) / len(ps),
        "recall": sum(rs) / len(rs),
        "f1": sum(f1s) / len(f1s),
        "latency_mean": sum(latencies) / len(latencies),
        "latency_p95": latencies[int(len(latencies) * 0.95) - 1],
        "prompt_tokens": prompt_tok,
        "completion_tokens": comp_tok,
    }


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="抽取对比评测：微调 vLLM vs 云端 API")
    parser.add_argument("--limit", type=int, default=0, help="只用前 N 条样本（0=全部）")
    args = parser.parse_args()

    samples = json.loads(FT_FILE.read_text(encoding="utf-8"))
    if args.limit:
        samples = samples[:args.limit]
    print(f"样本数: {len(samples)}  (来源: {FT_FILE.name})")

    # 微调模型（vLLM）：与生产抽取同参数（temp=0，max_tokens 保险丝）
    vllm_llm = ChatOpenAI(
        model=settings.extraction_model_name,
        openai_api_key=settings.extraction_model_api_key,
        openai_api_base=settings.extraction_model_base_url,
        temperature=0,
        max_tokens=2048,
        max_retries=0,
        request_timeout=120,
    )
    # 云端大模型：同提示词、同裸调用（公平对比，不用 json_mode）
    cloud_llm = ChatOpenAI(
        model=settings.model_name,
        openai_api_key=settings.model_api_key,
        openai_api_base=settings.model_base_url,
        temperature=0,
        max_retries=1,
        request_timeout=120,
    )

    print(f"\n[1/2] 评测微调模型 {settings.extraction_model_name} @ {settings.extraction_model_base_url}")
    m_ft = eval_model("finetune(vLLM)", vllm_llm, samples, workers=8)
    print(f"\n[2/2] 评测云端模型 {settings.model_name} @ {settings.model_base_url}")
    m_cloud = eval_model("cloud(API)", cloud_llm, samples, workers=8)

    report = {
        "dataset": str(FT_FILE),
        "n_samples": len(samples),
        "finetune_vllm": m_ft,
        "cloud_api": m_cloud,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台摘要
    print("\n" + "=" * 66)
    print(f"{'指标':<22}{'微调 vLLM':>18}{'云端 API':>18}")
    print("-" * 66)
    rows = [
        ("JSON 有效率", f"{m_ft['valid_rate']:.1%}", f"{m_cloud['valid_rate']:.1%}"),
        ("精确率 P", f"{m_ft['precision']:.3f}", f"{m_cloud['precision']:.3f}"),
        ("召回率 R", f"{m_ft['recall']:.3f}", f"{m_cloud['recall']:.3f}"),
        ("F1(宏平均)", f"{m_ft['f1']:.3f}", f"{m_cloud['f1']:.3f}"),
        ("延迟均值(s)", f"{m_ft['latency_mean']:.2f}", f"{m_cloud['latency_mean']:.2f}"),
        ("延迟 P95(s)", f"{m_ft['latency_p95']:.2f}", f"{m_cloud['latency_p95']:.2f}"),
        ("prompt tokens", f"{m_ft['prompt_tokens']}", f"{m_cloud['prompt_tokens']}"),
        ("completion tokens", f"{m_ft['completion_tokens']}", f"{m_cloud['completion_tokens']}"),
    ]
    for name, a, b in rows:
        print(f"{name:<22}{a:>18}{b:>18}")
    print("=" * 66)
    print(f"结果已保存: {OUT_FILE}")


if __name__ == "__main__":
    main()
