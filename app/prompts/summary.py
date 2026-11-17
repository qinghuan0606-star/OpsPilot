"""Conversation summarisation prompt (ops)."""

SUMMARY_SYSTEM = """把运维支持对话压成简短摘要，保留：目标主机、操作系统与版本、涉及的服务/软件包、
已取得的工具证据（状态、版本、报错）、已确认或待确认的操作、仍未解决的问题。只输出 JSON。"""

SUMMARY_USER = """历史：
{history}

输出 JSON：
{{"summary":"..."}}
"""
