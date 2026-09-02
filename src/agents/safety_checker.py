"""
Safety Checker Agent (MOST IMPORTANT!)
Ensures all medical advice includes mandatory disclaimers and emergency warnings
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.logger import setup_logger
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


# Mandatory disclaimer (DO NOT MODIFY)
MANDATORY_DISCLAIMER = """🔴 重要声明：本建议仅供参考，不能替代专业医疗诊断。请及时就医，遵医嘱用药！"""

# Emergency warning template
EMERGENCY_WARNING = """🚨 紧急警告：您描述的症状可能是急症表现，请立即拨打 120 或前往最近的医院急诊科！"""

# 急症关键词（**高精度**确定性兜底：临床红旗词 + 少量无歧义的重症口语）。
# 口语化表述的高召回由意图识别(LLM)兜住（见 __call__ 中 intent=="emergency"）；
# 本列表是"即便意图识别失灵也必须拦下"的最后一道确定性防线，故宁精勿滥、不放宽泛词。
EMERGENCY_KEYWORDS = [
    # 心 / 呼吸
    "胸痛", "胸闷", "呼吸困难", "喘不过气", "喘不上气", "窒息", "憋气",
    # 意识 / 神经
    "意识模糊", "昏迷", "晕厥", "不省人事", "抽搐", "口吐白沫", "晕倒在地",
    "突然失明", "眼前一黑", "肢体麻木", "半身不遂", "偏瘫",
    # 出血
    "大出血", "吐血", "咳血", "便血", "呕血",
    # 剧痛 / 高热 / 过敏
    "剧烈腹痛", "痛得打滚", "疼得打滚", "高烧不退", "持续高烧", "退不下来", "严重过敏",
]


class SafetyCheckerAgent:
    """
    Safety Checker Agent

    This is the MOST IMPORTANT agent in the system.
    It ensures all medical advice includes mandatory disclaimers.
    The disclaimer is added programmatically, NOT by LLM.
    """

    def __call__(self, state: AgentState) -> dict:
        """Process state and return update"""
        query = state.get("query", "")
        intent = state.get("intent", "")
        symptoms = state.get("symptoms", [])
        is_emergency = state.get("is_emergency", False)
        severity = state.get("severity", "")
        medications = state.get("medications", [])

        logger.info(f"[SafetyChecker] Checking safety...")

        disclaimers = []
        warnings = []

        # 1. MANDATORY: Always add disclaimer (DO NOT SKIP!)
        disclaimers.append(MANDATORY_DISCLAIMER)

        # 2. Check for emergency keywords
        detected_emergency = False
        for keyword in EMERGENCY_KEYWORDS:
            if keyword in query or keyword in str(symptoms):
                detected_emergency = True
                break

        # 主信号 = 意图识别(LLM)判定为急症：能覆盖口语化表述（"眼睛看不见""烧到40度退不下来""痛得打滚"），
        # 这是关键词精确匹配兜不住的高召回来源。急症宁可误报、不可漏报（医疗安全优先）。
        if detected_emergency or is_emergency or severity == "emergency" or intent == "emergency":
            warnings.append(EMERGENCY_WARNING)
            logger.warning(f"[SafetyChecker] EMERGENCY detected! (keyword={detected_emergency}, intent={intent})")

        # 3. Medication safety warnings（用药意图一律提醒，即便未给具体药物）
        if medications or intent == "medication":
            disclaimers.append("⚠️ 用药提醒：请在医生或药师指导下用药，不要自行调整剂量或停药。")

            # Check for special populations
            special_keywords = ["孕妇", "怀孕", "哺乳", "儿童", "小孩", "老人", "老年"]
            for kw in special_keywords:
                if kw in query:
                    disclaimers.append(f"⚠️ 特殊人群提醒：{kw}用药需特别谨慎，请务必咨询医生。")
                    break

        # 4. High severity warning
        if severity == "high":
            warnings.append("⚠️ 您的症状较为严重，建议尽快就医，不要拖延。")

        logger.info(f"[SafetyChecker] Added {len(disclaimers)} disclaimers, {len(warnings)} warnings")

        return {
            "disclaimers": disclaimers,
            "warnings": warnings,
            "is_emergency": is_emergency or detected_emergency or intent == "emergency",
            "messages": [f"[SafetyChecker] Added {len(disclaimers)} disclaimers, {len(warnings)} warnings"]
        }


safety_checker = SafetyCheckerAgent()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("SAFETY CHECKER AGENT TEST")
    print("=" * 60)

    # Test 1: Normal query
    print("\n[Test 1] Normal query")
    state = {"query": "我最近头痛", "symptoms": ["头痛"], "severity": "medium", "medications": []}
    result = safety_checker(state)
    print(f"  Disclaimers: {len(result['disclaimers'])}")
    print(f"  Warnings: {len(result['warnings'])}")

    # Test 2: Emergency query
    print("\n[Test 2] Emergency query")
    state = {"query": "我突然胸痛、呼吸困难", "symptoms": ["胸痛", "呼吸困难"], "severity": "emergency", "medications": []}
    result = safety_checker(state)
    print(f"  Disclaimers: {len(result['disclaimers'])}")
    print(f"  Warnings: {len(result['warnings'])}")
    print(f"  Is Emergency: {result['is_emergency']}")

    print("\n" + "=" * 60)
