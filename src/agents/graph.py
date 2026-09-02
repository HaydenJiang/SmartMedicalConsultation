"""
LangGraph State Graph Orchestration
Orchestrates 9 agents into a complete medical consultation system.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langgraph.graph import StateGraph, START, END

from src.common.logger import setup_logger
from src.agents.state import AgentState, IntentType, create_initial_state

# Import all agents
from src.agents.intent_classifier import intent_classifier
from src.agents.symptom_detector import symptom_detector
from src.agents.department_recommender import department_recommender
from src.agents.medication_advisor import medication_advisor
from src.agents.medical_knowledge import medical_knowledge
from src.agents.pre_visit_advisor import pre_visit_advisor
from src.agents.safety_checker import safety_checker
from src.agents.answer_fusion import answer_fusion
from src.agents.general_chat import general_chat

logger = setup_logger(__name__, "agents.log")


# ============================================================
# Routing Functions
# ============================================================

def route_by_intent(state: AgentState) -> str:
    """Route to different agents based on intent"""
    intent = state.get("intent", IntentType.GENERAL)

    if intent == IntentType.APPOINTMENT:
        return "symptom_detector"
    elif intent == IntentType.MEDICATION:
        return "symptom_detector"
    elif intent == IntentType.KNOWLEDGE:
        return "medical_knowledge"
    elif intent == IntentType.EMERGENCY:
        return "safety_checker"
    else:
        return "general_chat"


def route_after_symptom(state: AgentState) -> str:
    """Route after symptom detection based on original intent"""
    intent = state.get("intent", IntentType.GENERAL)

    if intent == IntentType.APPOINTMENT:
        return "department_recommender"
    elif intent == IntentType.MEDICATION:
        # 无疾病/症状锚点时 medication_advisor 无从下手（含"含药名/相互作用/副作用"等事实问句）；
        # 交给能用 get_medication_info 等工具的 ReAct 知识 Agent，一轮答完。
        return "medical_knowledge" if not state.get("symptoms") else "medication_advisor"
    else:
        return "safety_checker"


# ============================================================
# Build State Graph
# ============================================================

def build_graph() -> StateGraph:
    """Build the LangGraph state graph"""

    # Create graph with AgentState
    graph = StateGraph(AgentState)

    # Add all agent nodes
    graph.add_node("intent_classifier", intent_classifier)
    graph.add_node("symptom_detector", symptom_detector)
    graph.add_node("department_recommender", department_recommender)
    graph.add_node("medication_advisor", medication_advisor)
    graph.add_node("medical_knowledge", medical_knowledge)
    graph.add_node("pre_visit_advisor", pre_visit_advisor)
    graph.add_node("safety_checker", safety_checker)
    graph.add_node("answer_fusion", answer_fusion)
    graph.add_node("general_chat", general_chat)

    # Define edges
    # START -> intent_classifier
    graph.add_edge(START, "intent_classifier")

    # intent_classifier -> conditional routing
    graph.add_conditional_edges(
        "intent_classifier",
        route_by_intent,
        {
            "symptom_detector": "symptom_detector",
            "medical_knowledge": "medical_knowledge",
            "safety_checker": "safety_checker",
            "general_chat": "general_chat"
        }
    )

    # symptom_detector -> conditional routing (appointment vs medication)
    graph.add_conditional_edges(
        "symptom_detector",
        route_after_symptom,
        {
            "department_recommender": "department_recommender",
            "medication_advisor": "medication_advisor",
            "medical_knowledge": "medical_knowledge",   # medication 无锚点时的二级路由
            "safety_checker": "safety_checker"
        }
    )

    # appointment flow: department_recommender -> pre_visit_advisor -> safety_checker
    graph.add_edge("department_recommender", "pre_visit_advisor")
    graph.add_edge("pre_visit_advisor", "safety_checker")

    # medication flow: medication_advisor -> safety_checker
    graph.add_edge("medication_advisor", "safety_checker")

    # knowledge flow: medical_knowledge -> safety_checker
    graph.add_edge("medical_knowledge", "safety_checker")

    # emergency flow: safety_checker (direct)

    # general flow: general_chat -> END (no safety check needed)
    graph.add_edge("general_chat", END)

    # safety_checker -> answer_fusion -> END
    graph.add_edge("safety_checker", "answer_fusion")
    graph.add_edge("answer_fusion", END)

    return graph


# ============================================================
# Compiled Graph
# ============================================================

# Build and compile the graph
graph = build_graph()
app = graph.compile()


# ============================================================
# Run Function
# ============================================================

def run(query: str, history: list | None = None) -> AgentState:
    """
    Run the medical consultation system

    Args:
        query: User's question
        history: Prior conversation turns (from session memory) for multi-turn context

    Returns:
        Final AgentState with all results
    """
    logger.info(f"[Graph] Starting consultation: {query[:50]}... (history turns: {len(history or [])})")

    # Create initial state (with conversation history for multi-turn memory)
    initial_state = create_initial_state(query, history=history)

    # Run the graph
    result = app.invoke(initial_state)

    logger.info(f"[Graph] Consultation completed")
    return result


# ============================================================
# Streaming Run (for SSE endpoint)
# ============================================================

# 节点名 → 中文标签（前端进度展示用）
NODE_LABELS_ZH = {
    "intent_classifier": "意图识别",
    "symptom_detector": "症状检测",
    "department_recommender": "科室推荐",
    "medication_advisor": "用药建议",
    "medical_knowledge": "医学知识检索",
    "pre_visit_advisor": "就医指导",
    "safety_checker": "安全检查",
    "answer_fusion": "答案生成",
    "general_chat": "通用对话",
}


def run_stream(query: str, history: list | None = None):
    """Streaming 运行 Agent 系统，供 SSE 端点消费。

    使用 LangGraph 双模式 stream：
    - "updates"：每个节点完成后给出 {node_name: delta} → yield ("progress", node_name, delta)
    - "values" ：每步之后给出完整 state 快照 → yield ("values", snapshot)，最后一个即终态

    注意：这是**同步生成器**（app.stream 为同步）。SSE 端点用
    asyncio.to_thread(lambda: next(gen, sentinel)) 逐个取值——哨兵模式保证
    StopIteration 不穿越线程边界进入 async 生成器（PEP 479 会将其转为 RuntimeError）。
    """
    logger.info(f"[Graph] Starting streaming consultation: {query[:50]}...")
    initial_state = create_initial_state(query, history=history)
    for mode, chunk in app.stream(initial_state, stream_mode=["updates", "values"]):
        if mode == "updates":
            # chunk = {node_name: state_delta}；过滤 __start__（初始状态写入，非 Agent 节点）
            for node_name, delta in chunk.items():
                if node_name == "__start__":
                    continue
                yield ("progress", node_name, delta if isinstance(delta, dict) else {})
        else:  # mode == "values"
            yield ("values", chunk)


# ============================================================
# Visualization
# ============================================================

def get_mermaid_diagram() -> str:
    """Generate Mermaid diagram of the agent flow.

    注意：这是**静态示意图**，须与 build_graph() 的边保持一致（当前已对齐
    route_by_intent / route_after_symptom，含 medication·无症状 → 医学知识 的二级路由）。
    若担心再次漂移，可改用 LangGraph 自动导出 app.get_graph().draw_mermaid()
    （节点为英文 id、无自定义配色，但永远与编译图同步）。
    """
    return """
```mermaid
graph TD
    START --> A[意图识别<br/>IntentClassifier]

    A -->|appointment| B[症状检测<br/>SymptomDetector]
    A -->|medication| B
    A -->|knowledge| E[医学知识<br/>MedicalKnowledge]
    A -->|emergency| G[安全检查<br/>SafetyChecker]
    A -->|general| I[通用对话<br/>GeneralChat]

    B -->|appointment| C[科室推荐<br/>DepartmentRecommender]
    B -->|medication 有症状| D[用药建议<br/>MedicationAdvisor]
    B -->|medication 无症状| E

    C --> F[就医指导<br/>PreVisitAdvisor]
    F --> G

    D --> G
    E --> G

    G --> H[答案融合<br/>AnswerFusion]
    H --> END

    I --> END

    style A fill:#e1f5ff
    style G fill:#ffebee
    style H fill:#e8f5e9
```
"""


# ============================================================
# Main: Test
# ============================================================

if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("LANGGRAPH AGENT SYSTEM TEST")
    print("=" * 60)

    # Print Mermaid diagram
    print("\n[Agent Flow Diagram]")
    print(get_mermaid_diagram())

    # Test query
    test_query = "我最近头痛、头晕，应该挂什么科？"
    print(f"\n[Test Query] {test_query}")
    print("-" * 60)

    # Run the system
    result = run(test_query)

    # Print results
    print("\n[Results]")
    print(f"  Intent: {result.get('intent', '')}")
    print(f"  Confidence: {result.get('intent_confidence', 0):.2f}")
    print(f"  Symptoms: {result.get('symptoms', [])}")
    print(f"  Severity: {result.get('severity', '')}")
    print(f"  Departments: {result.get('departments', [])}")
    print(f"  Disclaimers: {len(result.get('disclaimers', []))} items")
    print(f"  Messages: {len(result.get('messages', []))} steps")

    print("\n[Agent Execution Chain]")
    for msg in result.get("messages", []):
        print(f"  {msg}")

    print("\n[Final Answer]")
    print("-" * 60)
    print(result.get("final_answer", ""))
    print("-" * 60)

    # Verify required fields
    print("\n[Verification]")
    checks = [
        ("intent", result.get("intent") == "appointment"),
        ("symptoms", len(result.get("symptoms", [])) > 0),
        ("departments", len(result.get("departments", [])) > 0),
        ("final_answer", len(result.get("final_answer", "")) > 0),
        ("disclaimers", len(result.get("disclaimers", [])) > 0),
    ]

    all_passed = True
    for name, passed in checks:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} {name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("[SUCCESS] All tests passed!")
    else:
        print("[FAILED] Some tests failed")
    print("=" * 60)
