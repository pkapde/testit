from contextlib import contextmanager
from types import SimpleNamespace

from app.infrastructure import azure_openai, observability


class FakeSpan:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, name, value):
        self.attributes[name] = value


def test_record_llm_response_exports_only_model_and_token_metadata(monkeypatch):
    monkeypatch.setattr(
        observability,
        "settings",
        SimpleNamespace(azure_openai_deployment="deployment-fallback"),
    )
    span = FakeSpan()
    response = SimpleNamespace(
        model="gpt-5",
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150),
    )

    observability.record_llm_response(span, response)

    assert span.attributes == {
        "llm.model_name": "gpt-5",
        "llm.token_count.prompt": 120,
        "llm.token_count.completion": 30,
        "llm.token_count.total": 150,
    }


def test_complete_records_response_metadata_without_changing_model_call(monkeypatch):
    span = FakeSpan()
    captured = {}

    @contextmanager
    def fake_llm_operation(operation):
        captured["operation"] = operation
        yield span

    def fake_record_llm_response(received_span, response):
        captured["span"] = received_span
        captured["response"] = response

    response = SimpleNamespace(choices=[])

    def create(**kwargs):
        captured["request"] = kwargs
        return response

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=create
            )
        )
    )
    # Avoid importing from an external dependency in the test by patching the
    # dependency boundary used by the helper itself.
    monkeypatch.setattr(observability, "llm_operation", fake_llm_operation)
    monkeypatch.setattr(observability, "record_llm_response", fake_record_llm_response)

    result = azure_openai._complete(client, "field_extraction", model="gpt-5")

    assert result is response
    assert captured["operation"] == "field_extraction"
    assert captured["request"] == {"model": "gpt-5"}
    assert captured["span"] is span
    assert captured["response"] is response
