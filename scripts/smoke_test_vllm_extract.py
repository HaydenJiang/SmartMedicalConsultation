# ===== Vibe Coding 生成：调用自部署微调模型做抽取（手工冒烟测试）=====
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

# 必须与训练数据的 instruction（§4.2 INSTRUCTION，即 DiseaseExtractor 提示词原文）保持一致，
# 否则微调模型的格式遵循会退化。项目正式接回（§5.3）时由 DiseaseExtractor 发原版提示词，无需手工处理。
EXTRACT_INSTRUCTION = """你是一个专业的医疗信息抽取助手。请从以下文本中提取疾病及其相关信息。

要求：
1. 疾病名称使用标准医学术语
2. 症状列表要完整，包含所有提到的症状
3. 科室名称使用标准科室名称（如"心血管内科"而非"心内科"）
4. 药物名称使用通用名（如"氨氯地平"而非商品名）
5. 如果没有相关信息，对应字段返回空列表
6. 严格按照 JSON 格式输出

请以 JSON 格式输出，包含以下字段：
{
    "disease": {
        "name": "疾病名称",
        "description": "疾病描述",
        "icd_code": "ICD编码（如知道）或 null"
    },
    "symptoms": ["症状1", "症状2"],
    "medications": ["药物1", "药物2"],
    "departments": ["科室1"],
    "examinations": ["检查1", "检查2"],
    "treatments": ["治疗方案1"],
    "body_parts": ["身体部位1"]
}"""

llm = ChatOpenAI(
    api_key="EMPTY",
    base_url="http://223.109.239.11:16070/v1",   # 指向 vLLM 服务
    model="qwen2.5-merged",
    temperature=0,                               # 抽取任务要稳，温度设 0
)

text = "糖尿病常见症状为多饮、多尿，常用药物二甲双胍，就诊科室内分泌科。"
resp = llm.invoke([
    SystemMessage(content=EXTRACT_INSTRUCTION),
    HumanMessage(content=text),
])
print(resp.content)   # 期望: SimpleLLMOutput schema 的 JSON（disease + 五个列表字段）
