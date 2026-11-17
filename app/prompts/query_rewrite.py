"""Query rewrite prompt (ops retrieval)."""

REWRITE_SYSTEM = """你改写运维检索查询。只输出 JSON。
生成 1-3 条更适合检索的短查询，保留关键约束：操作系统与版本、服务名、包名、报错关键词、故障阶段。
"""

REWRITE_USER = """原始问题：{query}
仍缺少的信息：{missing_aspect}

输出 JSON：
{{"queries":["..."]}}
"""
