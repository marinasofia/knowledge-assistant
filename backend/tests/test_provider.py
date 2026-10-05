"""Provider path tests with hand-written stub responses. No network or API key is used."""

from types import SimpleNamespace

import anthropic
import pytest
from fastapi import HTTPException

from app.answers import generate
from app.config import settings

EVIDENCE = [
    {"source_id": "s1", "content": "The equipment allowance is $500 per year.", "coverage": 1.0}
]


def stub_provider(monkeypatch, text, stop_reason="end_turn"):
    response = SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
    )

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
            self.messages = SimpleNamespace(create=lambda **_: response)

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    monkeypatch.setattr(settings, "generation_mode", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "stub-key")


def test_valid_provider_answer(monkeypatch):
    stub_provider(
        monkeypatch,
        '{"status": "answer", "text": "It is $500 per year.", "gaps": [],'
        ' "citations": [{"source_id": "s1", "quote": "allowance is $500 per year"}],'
        ' "claims": [{"text": "The allowance is $500 per year.", "citations": [0]}]}',
    )
    answer = generate("What is the equipment allowance?", EVIDENCE)
    assert answer.status == "answer" and answer.citations[0].source_id == "s1"
    assert answer.claims[0].citations == [0]


@pytest.mark.parametrize(
    "text,stop_reason",
    [
        # Quote not present in the evidence.
        (
            '{"status": "answer", "text": "It is $900.", "gaps": [],'
            ' "citations": [{"source_id": "s1", "quote": "allowance is $900"}]}',
            "end_turn",
        ),
        # Source ID that was never retrieved.
        (
            '{"status": "answer", "text": "Yes.", "gaps": [],'
            ' "citations": [{"source_id": "invented", "quote": "allowance"}]}',
            "end_turn",
        ),
        # Answer without any citation.
        ('{"status": "answer", "text": "Yes.", "gaps": [], "citations": []}', "end_turn"),
        # Not JSON.
        ("The allowance is $500.", "end_turn"),
        # Extra field the schema forbids.
        (
            '{"status": "abstain", "text": "No.", "gaps": ["x"], "citations": [],'
            ' "tool": "delete"}',
            "end_turn",
        ),
        # Truncated output.
        ('{"status": "answer", "text": "It is', "max_tokens"),
        # Answer without claims.
        (
            '{"status": "answer", "text": "It is $500.", "gaps": [],'
            ' "citations": [{"source_id": "s1", "quote": "$500"}]}',
            "end_turn",
        ),
        # Claim pointing at a citation that does not exist.
        (
            '{"status": "answer", "text": "It is $500.", "gaps": [],'
            ' "citations": [{"source_id": "s1", "quote": "$500"}],'
            ' "claims": [{"text": "It is $500.", "citations": [3]}]}',
            "end_turn",
        ),
        # Citation that supports no claim.
        (
            '{"status": "answer", "text": "It is $500.", "gaps": [],'
            ' "citations": [{"source_id": "s1", "quote": "$500"}, {"source_id": "s1",'
            ' "quote": "per year"}], "claims": [{"text": "It is $500.", "citations": [0]}]}',
            "end_turn",
        ),
        # Claim with no citation at all.
        (
            '{"status": "answer", "text": "It is $500.", "gaps": [],'
            ' "citations": [{"source_id": "s1", "quote": "$500"}],'
            ' "claims": [{"text": "It is $500.", "citations": []}]}',
            "end_turn",
        ),
    ],
)
def test_invalid_provider_output_rejected(monkeypatch, text, stop_reason):
    stub_provider(monkeypatch, text, stop_reason)
    with pytest.raises(ValueError):
        generate("What is the equipment allowance?", EVIDENCE)


def test_unreviewed_model_refused(monkeypatch):
    stub_provider(monkeypatch, "{}")
    monkeypatch.setattr(settings, "model", "some-unreviewed-model")
    with pytest.raises(HTTPException) as exc:
        generate("What is the equipment allowance?", EVIDENCE)
    assert exc.value.status_code == 503


def test_uncovered_question_never_reaches_the_model(monkeypatch):
    stub_provider(monkeypatch, "{}")

    class Refuse:
        def __init__(self, **_):
            raise AssertionError("model called for an uncovered question")

    monkeypatch.setattr(anthropic, "Anthropic", Refuse)
    weak = [{"source_id": "s1", "content": "Laptops are encrypted.", "coverage": 0.2}]
    assert generate("Is there dental insurance?", weak).status == "abstain"


def test_relevance_gate_is_replaceable(monkeypatch):
    """A new gate, such as a Jev adapter, plugs in without touching the decision rules."""
    from app import generators

    class RejectAll:
        name = "reject-all"

        def covers(self, question, evidence):
            return False

    monkeypatch.setitem(generators.GATES, "reject-all", RejectAll())
    monkeypatch.setattr(settings, "relevance_gate", "reject-all")
    assert generate("What is the equipment allowance?", EVIDENCE).status == "abstain"


def test_unknown_gate_rejected_at_startup():
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(relevance_gate="unreviewed")
