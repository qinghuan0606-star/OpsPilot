"""Self-RAG retrieval grading prompt (ops)."""

GRADE_SYSTEM = """你评估运维知识检索结果是否足以回答问题。只输出 JSON。
relevant：是否至少有一条证据与问题相关
sufficient：是否足以给出不编造的运维结论（只靠文档即可判断时才算足够）
missing_aspect：若不足，还缺什么（例如"缺少具体报错行"或"缺少版本对应关系"）
"""

GRADE_USER = """问题：{query}

证据：
{evidence}

输出 JSON：
{{"relevant":true,"sufficient":true,"missing_aspect":"","rationale":"..."}}
"""
