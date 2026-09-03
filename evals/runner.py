"""
Evaluation runner —— 可量化 / 可回归 / 可进 CI。

双模式：
  默认（离线/核心）：调 src/agents/graph.py 的 run(query, history)。
  --base-url URL  ：改调 URL + /api/consult 测经 API 的 E2E（day04 的 API 零代码插上）。

每条算：intent_correct / symptom_F1 / dept_hit@k / dept_recall / clarify P/R /
emergency_recall / disclaimer_present；knowledge 用例走 RAGAS（缺则 LLM 裁判）。
统计延迟 p50/p95/p99。汇总写 evals/last_report.md 并打印。
硬规则门禁：disclaimer 覆盖率<1 或 emergency 召回<阈值 或 intent 准确率<阈值 → 退出码非 0。
"""

import sys
import re
import json
import time
import argparse
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from evals.judge import judge_answer
from evals.observe import trace_span

HERE = Path(__file__).parent
DATASET = HERE / "dataset.jsonl"
REPORT = HERE / "last_report.md"


# ---------- metric helpers ----------
def _mean(vals):
    vs = [v for v in vals if v is not None]
    return (sum(vs) / len(vs)) if vs else None

def _pct(vals, q):
    vs = sorted(v for v in vals if v is not None)
    if not vs:
        return 0.0
    k = (len(vs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vs) - 1)
    return vs[lo] + (vs[hi] - vs[lo]) * (k - lo)

def _set_f1(pred, gold):
    p, g = set(pred or []), set(gold or [])
    if not g:
        return None                      # 未标注 → 不计
    if not p:
        return 0.0
    tp = len(p & g)
    prec, rec = tp / len(p), tp / len(g)
    return (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0

def _hit_at_k(pred, acceptable, k=3):
    a = set(acceptable or [])
    if not a:
        return None
    return 1.0 if (set(pred or []) & a) else 0.0

def _recall(pred, acceptable):
    a = set(acceptable or [])
    if not a:
        return None
    p = set(pred or [])
    return len(p & a) / len(a)

def _tool_calls_from_state(state):
    out = []
    for m in state.get("messages", []):
        mt = re.search(r"tools=(\[[^\]]*\])", m)
        if mt:
            try:
                out += [t for t in json.loads(mt.group(1)) if t]
            except Exception:
                pass
    return list(dict.fromkeys(out))

def _pred_clarify(state, answer):
    if state is not None and state.get("needs_clarification") is not None:
        return bool(state.get("needs_clarification"))
    return ("❓" in answer) or ("补充" in answer) or ("描述" in answer and "症状" in answer)

def _pred_emergency(warnings, answer):
    # 精确信号 = 安全检查器是否真的加了急症 warning（离线/E2E 的 response 都带 warnings）。
    # 不用 answer 子串（通用欢迎语也会提"120/急诊"，会误报）。
    return bool(warnings)


# ---------- one case ----------
def eval_case(case, base_url=None):
    gold = case["gold"]
    query, history = case["query"], case.get("history", [])
    t0 = time.perf_counter()
    state, answer, intent, symptoms, depts, disclaimers, warnings, tool_calls = (
        None, "", "", [], [], [], [], [])

    if base_url:
        import requests
        r = requests.post(base_url.rstrip("/") + "/api/consult",
                          json={"query": query, "session_id": f"eval-{case['id']}"}, timeout=120)
        d = r.json()
        answer = d.get("answer", "")
        intent = d.get("intent", "")
        symptoms = d.get("symptoms", [])
        depts = d.get("departments", [])
        disclaimers = d.get("disclaimers", [])
        warnings = d.get("warnings", [])
    else:
        from src.agents.graph import run           # 懒加载，E2E 模式不构建图
        with trace_span(f"eval:{case['id']}", inputs={"query": query}) as span:
            state = run(query, history=history)
            tool_calls = _tool_calls_from_state(state)
            span.update(tool_calls=tool_calls)
        answer = state.get("final_answer", "")
        intent = state.get("intent", "")
        symptoms = state.get("symptoms", [])
        depts = state.get("departments", [])
        disclaimers = state.get("disclaimers", [])
        warnings = state.get("warnings", [])
        span.update(intent=intent, latency_ms=round((time.perf_counter() - t0) * 1000))

    latency_ms = (time.perf_counter() - t0) * 1000
    m = {
        "id": case["id"],
        "intent_correct": (intent == gold["intent"]),
        "symptom_f1": _set_f1(symptoms, gold.get("symptoms")),
        "dept_hit": _hit_at_k(depts, gold.get("departments_acceptable")),
        "dept_recall": _recall(depts, gold.get("departments_acceptable")),
        "must_clarify": gold.get("must_clarify", False),
        "pred_clarify": _pred_clarify(state, answer),
        "is_emergency": gold.get("is_emergency", False),
        "pred_emergency": _pred_emergency(warnings, answer),
        "must_disclaimer": gold.get("must_disclaimer", True),
        "disclaimer_present": bool(disclaimers),
        "latency_ms": latency_ms,
        "knowledge": None,
    }
    if ("knowledge" in case.get("tags", [])) or gold.get("reference_answer") or gold.get("supporting_facts"):
        rc = (state or {}).get("retrieved_contexts", []) if state is not None else []
        m["knowledge"] = judge_answer(answer, query, gold.get("reference_answer"),
                                      gold.get("supporting_facts"), rc)
    return m


# ---------- aggregate + gate ----------
def aggregate(rows, thr_intent, thr_emergency):
    intent_acc = _mean([r["intent_correct"] for r in rows])
    sym_f1 = _mean([r["symptom_f1"] for r in rows])
    dept_hit = _mean([r["dept_hit"] for r in rows])
    dept_rec = _mean([r["dept_recall"] for r in rows])

    # clarify P/R
    tp = sum(1 for r in rows if r["must_clarify"] and r["pred_clarify"])
    fp = sum(1 for r in rows if (not r["must_clarify"]) and r["pred_clarify"])
    fn = sum(1 for r in rows if r["must_clarify"] and (not r["pred_clarify"]))
    clar_p = (tp / (tp + fp)) if (tp + fp) else None
    clar_r = (tp / (tp + fn)) if (tp + fn) else None
    clar_f1 = (2 * clar_p * clar_r / (clar_p + clar_r)) if (clar_p and clar_r) else (0.0 if (tp + fp + fn) else None)

    # emergency recall
    emer_cases = [r for r in rows if r["is_emergency"]]
    emer_rec = (sum(1 for r in emer_cases if r["pred_emergency"]) / len(emer_cases)) if emer_cases else 1.0

    # disclaimer coverage (over must_disclaimer=true)
    must = [r for r in rows if r["must_disclaimer"]]
    disc_cov = (sum(1 for r in must if r["disclaimer_present"]) / len(must)) if must else 1.0

    # knowledge correctness mean (LLM 裁判)
    kcorr = _mean([r["knowledge"]["correctness"] for r in rows if r["knowledge"] and r["knowledge"].get("correctness") is not None])
    # RAGAS 四指标均值（仅在同时具备 reference + 实检索上下文的用例上计算）
    def _rk(k):
        return _mean([r["knowledge"][k] for r in rows if r["knowledge"] and isinstance(r["knowledge"].get(k), (int, float))])
    ragas = {"faithfulness": _rk("faithfulness"), "answer_relevancy": _rk("answer_relevancy"),
             "context_precision": _rk("context_precision"), "context_recall": _rk("context_recall")}
    ragas_n = sum(1 for r in rows if r["knowledge"] and isinstance(r["knowledge"].get("faithfulness"), (int, float)))

    lat = [r["latency_ms"] for r in rows]

    # composite (normalized by present weights)
    w = {"intent": 0.25, "symptom_f1": 0.15, "dept_hit": 0.10, "clarify_f1": 0.10,
         "emergency_recall": 0.15, "disclaimer_cov": 0.15, "knowledge": 0.10}
    vals = {"intent": intent_acc, "symptom_f1": sym_f1, "dept_hit": dept_hit, "clarify_f1": clar_f1,
            "emergency_recall": emer_rec, "disclaimer_cov": disc_cov, "knowledge": kcorr}
    num = sum(w[k] * vals[k] for k in w if vals[k] is not None)
    wsum = sum(w[k] for k in w if vals[k] is not None)
    composite = (num / wsum) if wsum else 0.0

    gate_ok = (disc_cov >= 1.0) and (emer_rec >= thr_emergency) and ((intent_acc or 0) >= thr_intent)

    return {
        "intent_accuracy": intent_acc, "symptom_f1": sym_f1,
        "dept_hit@3": dept_hit, "dept_recall": dept_rec,
        "clarify_P": clar_p, "clarify_R": clar_r, "clarify_F1": clar_f1,
        "emergency_recall": emer_rec, "disclaimer_coverage": disc_cov,
        "knowledge_correctness": kcorr, "ragas": ragas, "ragas_n": ragas_n,
        "latency_p50": _pct(lat, 0.5), "latency_p95": _pct(lat, 0.95), "latency_p99": _pct(lat, 0.99),
        "composite": composite, "gate_ok": gate_ok,
        "thr_intent": thr_intent, "thr_emergency": thr_emergency,
    }


def _f(v, pct=False):
    if v is None:
        return "  -  "
    return f"{v*100:5.1f}%" if pct else f"{v:.3f}"


def write_report(rows, agg, mode, path):
    L = [f"# 评估报告  ({mode})", "",
         f"- 用例数：{len(rows)}　综合分：**{agg['composite']:.3f}**　门禁：{'✅ PASS' if agg['gate_ok'] else '❌ FAIL'}　RAGAS 覆盖用例：{agg['ragas_n']}",
         f"- 门禁阈值：intent≥{agg['thr_intent']}　emergency_recall≥{agg['thr_emergency']}　disclaimer_coverage=1.0", "",
         "| 维度 | 值 |", "|------|------|",
         f"| intent_accuracy | {_f(agg['intent_accuracy'], True)} |",
         f"| symptom_F1 | {_f(agg['symptom_f1'], True)} |",
         f"| dept_hit@3 | {_f(agg['dept_hit@3'], True)} |",
         f"| dept_recall | {_f(agg['dept_recall'], True)} |",
         f"| clarify P / R / F1 | {_f(agg['clarify_P'], True)} / {_f(agg['clarify_R'], True)} / {_f(agg['clarify_F1'], True)} |",
         f"| emergency_recall | {_f(agg['emergency_recall'], True)} |",
         f"| disclaimer_coverage | {_f(agg['disclaimer_coverage'], True)} |",
         f"| RAGAS faithfulness | {_f(agg['ragas']['faithfulness'])} |",
         f"| RAGAS answer_relevancy | {_f(agg['ragas']['answer_relevancy'])} |",
         f"| RAGAS context_precision | {_f(agg['ragas']['context_precision'])} |",
         f"| RAGAS context_recall | {_f(agg['ragas']['context_recall'])} |",
         f"| LLM裁判 correctness | {_f(agg['knowledge_correctness'])} |",
         f"| latency p50 / p95 / p99 | {agg['latency_p50']:.0f} / {agg['latency_p95']:.0f} / {agg['latency_p99']:.0f} ms |",
         "", "## 逐条", "", "| id | intent✓ | sympF1 | deptHit | clarify? | emer? | disc✓ | ms |",
         "|----|--------|--------|---------|----------|-------|-------|----|"]
    for r in rows:
        L.append(f"| {r['id']} | {'✅' if r['intent_correct'] else '❌'} | {_f(r['symptom_f1'])} | "
                 f"{_f(r['dept_hit'])} | {'C' if r['pred_clarify'] else '-'}{'/' if r['must_clarify'] else ''} | "
                 f"{'E' if r['pred_emergency'] else '-'}{'/' if r['is_emergency'] else ''} | "
                 f"{'✅' if r['disclaimer_present'] else '❌'} | {r['latency_ms']:.0f} |")
    Path(path).write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=None, help="设置则走 E2E（POST {base_url}/api/consult）")
    ap.add_argument("--subset", default=None, help="只跑含该 tag 的用例（如 smoke）")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 条用例（快速回归，如 --limit 10）")
    ap.add_argument("--dataset", default=str(DATASET))
    ap.add_argument("--thr-intent", type=float, default=0.9)
    ap.add_argument("--thr-emergency", type=float, default=1.0)
    args = ap.parse_args()

    cases = [json.loads(l) for l in Path(args.dataset).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.subset:
        cases = [c for c in cases if args.subset in c.get("tags", [])]
    if args.limit:
        cases = cases[:args.limit]
    mode = f"E2E @ {args.base_url}" if args.base_url else "offline/core"
    print(f"[EVAL] mode={mode}  cases={len(cases)}" + (f"  subset={args.subset}" if args.subset else "")
          + (f"  limit={args.limit}" if args.limit else ""))

    rows = []
    for c in cases:
        r = eval_case(c, base_url=args.base_url)
        rows.append(r)
        print(f"  - {c['id']:4} intent={'✅' if r['intent_correct'] else '❌'} "
              f"clarify={r['pred_clarify']}/{r['must_clarify']} emer={r['pred_emergency']}/{r['is_emergency']} "
              f"disc={'✅' if r['disclaimer_present'] else '❌'} {r['latency_ms']:.0f}ms")

    agg = aggregate(rows, args.thr_intent, args.thr_emergency)
    write_report(rows, agg, mode, REPORT)
    print("\n" + "=" * 60)
    print(f"composite = {agg['composite']:.3f}")
    print(f"intent_acc={_f(agg['intent_accuracy'], True)}  emergency_recall={_f(agg['emergency_recall'], True)}  "
          f"disclaimer_cov={_f(agg['disclaimer_coverage'], True)}")
    print(f"latency p50/p95/p99 = {agg['latency_p50']:.0f}/{agg['latency_p95']:.0f}/{agg['latency_p99']:.0f} ms")
    print(f"GATE: {'✅ PASS' if agg['gate_ok'] else '❌ FAIL'}  → report: {REPORT}")
    print("=" * 60)
    sys.exit(0 if agg["gate_ok"] else 1)


if __name__ == "__main__":
    main()
