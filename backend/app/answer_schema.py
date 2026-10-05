"""The answer contract every generator must satisfy, and its validation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    quote: str = Field(min_length=1, max_length=1200)


class Claim(BaseModel):
    """One sentence of an answer and the citations (by index) that support it."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)
    citations: list[int] = Field(min_length=1, max_length=8)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["answer", "abstain", "conflict"]
    text: str = Field(max_length=8000)
    citations: list[Reference] = Field(max_length=8)
    gaps: list[str] = Field(max_length=8)
    claims: list[Claim] = Field(default_factory=list, max_length=12)


def validate_answer(answer, evidence):
    """Structural grounding checks. They prove every quote is real and every claim points at a
    quote; they do not prove the quote entails the claim."""
    sources = {item["source_id"]: item for item in evidence}
    for citation in answer.citations:
        if (
            citation.source_id not in sources
            or citation.quote not in sources[citation.source_id]["content"]
        ):
            raise ValueError("invalid_citation")
    if answer.status in {"answer", "conflict"} and not answer.citations:
        raise ValueError("unsupported_answer")
    if answer.status == "conflict" and len(answer.citations) < 2:
        raise ValueError("unsupported_conflict")
    if answer.status == "abstain" and not answer.gaps:
        raise ValueError("missing_abstention_reason")
    used = set()
    for claim in answer.claims:
        if any(i < 0 or i >= len(answer.citations) for i in claim.citations):
            raise ValueError("claim_cites_missing_citation")
        used.update(claim.citations)
    if answer.claims and used != set(range(len(answer.citations))):
        raise ValueError("citation_supports_no_claim")
    return answer
