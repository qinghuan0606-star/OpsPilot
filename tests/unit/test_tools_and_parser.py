import pytest

from app.core.enums import ToolRisk
from app.core.exceptions import ToolPermissionError
from app.providers.json_parser import extract_json_object, parse_model
from app.schemas.agent import IntentResult
from app.tools.base import Tool
from app.tools.permissions import assert_permitted


class _Dummy(Tool):
    name = "restart_service"
    description = "x"
    risk = ToolRisk.DESTRUCTIVE
    input_model = IntentResult  # unused


def test_destructive_requires_confirmation() -> None:
    with pytest.raises(ToolPermissionError):
        assert_permitted(_Dummy(), confirmed=False)
    assert_permitted(_Dummy(), confirmed=True)


def test_json_parser_strips_fence() -> None:
    text = """当然可以：
```json
{"label":"package_rpm","confidence":0.9,"rationale":"x","prompt_version":"intent_ops_v1"}
```
"""
    parsed = parse_model(text, IntentResult)
    assert parsed.label.value == "package_rpm"


def test_json_parser_rejects_garbage() -> None:
    with pytest.raises(Exception):
        extract_json_object("sorry I cannot")


def test_unknown_intent_label_is_rejected() -> None:
    """An e-commerce label coming back from the model must fail, not be coerced."""
    from app.core.exceptions import LLMOutputError

    with pytest.raises(LLMOutputError):
        parse_model(
            '{"label":"refund","confidence":0.9,"rationale":"x","prompt_version":"v"}',
            IntentResult,
        )
