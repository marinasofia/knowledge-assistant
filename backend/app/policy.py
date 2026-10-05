"""Policy metadata and rule-based conflict detection. No model decides precedence."""

import re
from datetime import date
from uuid import uuid4

from fastapi import HTTPException

from .db import run

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
FIGURE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
FIELDS = {"owner", "effective"}


def parse_front_matter(content):
    """Split an optional `---` header of `key: value` lines from the document body."""
    match = FRONT_MATTER.match(content)
    if not match:
        return {}, content
    meta = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not sep or key not in FIELDS or not value:
            raise HTTPException(422, "invalid_front_matter")
        meta[key] = value[:200]
    if "effective" in meta:
        try:
            meta["effective"] = date.fromisoformat(meta["effective"])
        except ValueError:
            raise HTTPException(422, "invalid_effective_date") from None
    return meta, content[match.end() :]


def figures(text):
    return {f.replace(",", "") for f in FIGURE.findall(text)}


def section_key(section):
    return " ".join(section.lower().split())


def find_conflicts(conn, evidence):
    """Group passages from different documents under the same section title whose figures
    differ. A declared precedence resolves a group; otherwise it is a conflict."""
    groups = {}
    for item in evidence:
        groups.setdefault(section_key(item["section"]), []).append(item)
    found = []
    for section, items in groups.items():
        documents = {i["document_id"] for i in items}
        if len(documents) < 2 or len({frozenset(figures(i["content"])) for i in items}) < 2:
            continue
        rule = run(
            conn,
            """SELECT p.prevailing_document_id,p.yielding_document_id,p.note,d.title AS prevailing
          FROM document_precedence p JOIN documents d
          ON d.workspace_id=p.workspace_id AND d.id=p.prevailing_document_id
          WHERE p.section=:s AND p.prevailing_document_id = ANY(:docs)
          AND p.yielding_document_id = ANY(:docs)""",
            s=section,
            docs=list(documents),
        ).first()
        found.append(
            {
                "section": items[0]["section"],
                "source_ids": [i["source_id"] for i in items],
                "prevailing_document_id": rule.prevailing_document_id if rule else None,
                "prevailing_title": rule.prevailing if rule else None,
                "note": rule.note if rule else None,
            }
        )
    return found


def declare(conn, who, prevailing, yielding, section, note):
    for document_id in (prevailing, yielding):
        if not run(
            conn, "SELECT 1 FROM documents WHERE id=:d AND NOT deleted", d=document_id
        ).first():
            raise HTTPException(404, "document_not_found")
    if prevailing == yielding:
        raise HTTPException(422, "precedence_needs_two_documents")
    if run(
        conn,
        """SELECT 1 FROM document_precedence WHERE section=:s
      AND prevailing_document_id=:y AND yielding_document_id=:p""",
        s=section_key(section),
        p=prevailing,
        y=yielding,
    ).first():
        raise HTTPException(409, "contradicts_existing_precedence")
    key = str(uuid4())
    inserted = run(
        conn,
        """INSERT INTO document_precedence(id,workspace_id,prevailing_document_id,
      yielding_document_id,section,note,created_by) VALUES(:i,:w,:p,:y,:s,:n,:u)
      ON CONFLICT(workspace_id,yielding_document_id,section) DO NOTHING RETURNING id""",
        i=key,
        w=who.workspace,
        p=prevailing,
        y=yielding,
        s=section_key(section),
        n=note,
        u=who.user_id,
    ).first()
    if not inserted:
        raise HTTPException(409, "precedence_already_declared")
    return key
