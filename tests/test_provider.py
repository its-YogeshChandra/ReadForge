"""Checks for OpenRouter schema enforcement and bounded repair retries."""

from unittest.mock import Mock, patch

import pytest

from readforge.agents.provider import LLMProvider, LLMProviderError
from readforge.agents.state import RouterDecision


def _response(content: str) -> Mock:
    response = Mock()
    response.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    return response


def test_structured_request_retries_invalid_json() -> None:
    with (
        patch(
            "readforge.agents.provider.requests.post",
            side_effect=[
                _response("not-json"),
                _response(
                    '{"intents":["coverage"],"clarification_question":null}'
                ),
            ],
        ) as post,
        patch("readforge.agents.provider.time.sleep"),
    ):
        result = LLMProvider.invoke_json("route", {"question": "covered?"}, RouterDecision)

    assert result["intents"] == ["coverage"]
    assert post.call_count == 2
    payload = post.call_args_list[0].kwargs["json"]
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert set(payload["response_format"]["json_schema"]["schema"]["required"]) == {
        "intents",
        "clarification_question",
    }
    assert payload["provider"]["require_parameters"] is True


def test_invalid_json_exhaustion_is_an_upstream_error() -> None:
    with (
        patch(
            "readforge.agents.provider.requests.post",
            side_effect=[_response("not-json") for _ in range(2)],
        ),
        patch("readforge.agents.provider.time.sleep"),
        pytest.raises(LLMProviderError, match="after 2 attempts"),
    ):
        LLMProvider.invoke_json("route", {"question": "covered?"}, RouterDecision)
