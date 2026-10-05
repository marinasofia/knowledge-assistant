import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .config import settings
from .db import run, transaction
from .policy import parse_front_matter

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 500_000


def new_id():
    return str(uuid4())


def validate_file(filename, data):
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".md"}:
        raise HTTPException(415, "text_or_markdown_required_pdf_not_enabled")
    if len(data) > MAX_BYTES or not data:
        raise HTTPException(413, "file_size_limit")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeError:
        raise HTTPException(415, "utf8_text_required") from None
    if "\x00" in content or any(ord(c) < 32 and c not in "\n\r\t" for c in content):
        raise HTTPException(415, "binary_content_rejected")
    if len(content) > MAX_CHARS:
        raise HTTPException(413, "extracted_text_limit")
    if not content.strip():
        raise HTTPException(422, "empty_document")
    return content


MAX_PASSAGE = 1200
EXTRACTION_VERSION = "markdown-paragraphs-v2"
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Passage:
    section: str
    section_path: str
    text: str

    @property
    def key(self):
        # Same section path and same words give the same key in every version.
        normalized = " ".join(self.text.split())
        return hashlib.sha256((self.section_path + "\n" + normalized).encode()).hexdigest()[:32]


def split_passages(content):
    """Split Markdown into paragraph passages that never break inside a sentence."""
    headings = []
    paragraphs = []
    buffer = []

    def flush():
        text = "\n".join(buffer).strip()
        buffer.clear()
        if text:
            path = " > ".join(title for _, title in headings) or "Overview"
            leaf = headings[-1][1] if headings else "Overview"
            paragraphs.extend(Passage(leaf, path, piece) for piece in pack(text))

    for line in content.splitlines():
        match = HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            headings[:] = [h for h in headings if h[0] < level]
            headings.append((level, match.group(2).strip()[:200]))
        elif not line.strip():
            flush()
        else:
            buffer.append(line)
    flush()
    return paragraphs


def pack(text):
    """Greedily pack whole sentences into pieces of at most MAX_PASSAGE characters."""
    if len(text) <= MAX_PASSAGE:
        return [text]
    pieces, current = [], ""
    for sentence in SENTENCE_END.split(text):
        while len(sentence) > MAX_PASSAGE:
            # A single sentence longer than the limit: cut at the last space that fits.
            cut = sentence.rfind(" ", 0, MAX_PASSAGE)
            cut = cut if cut > 0 else MAX_PASSAGE
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > MAX_PASSAGE:
            pieces.append(current)
            current = sentence
        else:
            current = (current + " " + sentence).strip()
    if current:
        pieces.append(current)
    return pieces


def object_path(key):
    # Keys are generated UUIDs, never paths or user filenames.
    from uuid import UUID

    if str(UUID(key)) != key:
        raise ValueError("Invalid object key")
    root = Path(settings.storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root / key


def enqueue(conn, workspace, title, filename, data, document_id=None):
    parse_front_matter(validate_file(filename, data))
    run(conn, "SELECT pg_advisory_xact_lock(hashtext(:w))", w=workspace)
    count = run(conn, "SELECT count(*) FROM documents WHERE NOT deleted").scalar()
    if document_id is None and count >= 100:
        raise HTTPException(409, "document_limit")
    version_id, key = new_id(), new_id()
    if document_id:
        doc = run(
            conn, "SELECT id FROM documents WHERE id=:id AND NOT deleted FOR UPDATE", id=document_id
        ).first()
        if not doc:
            raise HTTPException(404, "document_not_found")
        number = run(
            conn, "SELECT max(number)+1 FROM document_versions WHERE document_id=:d", d=document_id
        ).scalar()
    else:
        document_id, number = new_id(), 1
        run(
            conn,
            "INSERT INTO documents(id,workspace_id,title) VALUES(:d,:w,:t)",
            d=document_id,
            w=workspace,
            t=title[:200],
        )
    path = object_path(key)
    with path.open("xb") as handle:
        path.chmod(0o600)
        handle.write(data)
    run(
        conn,
        """INSERT INTO document_versions
      (id,workspace_id,document_id,number,status,content_hash,storage_key)
      VALUES(:v,:w,:d,:n,'queued',:h,:k)""",
        v=version_id,
        w=workspace,
        d=document_id,
        n=number,
        h=hashlib.sha256(data).hexdigest(),
        k=key,
    )
    run(conn, "UPDATE documents SET latest_version=:v WHERE id=:d", v=version_id, d=document_id)
    run(
        conn,
        "INSERT INTO ingestion_jobs(id,workspace_id,version_id) VALUES(:i,:w,:v)",
        i=new_id(),
        w=workspace,
        v=version_id,
    )
    return {"id": document_id, "version_id": version_id, "status": "queued"}


def process_one(workspace):
    lease = new_id()
    with transaction(workspace) as conn:
        job = (
            run(
                conn,
                """SELECT * FROM ingestion_jobs WHERE attempts<3 AND available_at<=now()
          AND (status='queued' OR (status='processing' AND lease_until<now()))
          ORDER BY available_at FOR UPDATE SKIP LOCKED LIMIT 1""",
            )
            .mappings()
            .first()
        )
        if not job:
            # Exhausted crashed leases become explicit failures.
            run(
                conn,
                """UPDATE document_versions SET status='failed',error='retry_limit' WHERE id IN
              (SELECT version_id FROM ingestion_jobs WHERE status='processing' AND attempts>=3
               AND lease_until<now())""",
            )
            run(
                conn,
                """UPDATE ingestion_jobs SET status='failed' WHERE status='processing'
              AND attempts>=3 AND lease_until<now()""",
            )
            return False
        run(
            conn,
            """UPDATE ingestion_jobs SET status='processing',attempts=attempts+1,
          lease_token=:l,lease_until=now()+interval '60 seconds' WHERE id=:i""",
            l=lease,
            i=job["id"],
        )
        version = (
            run(conn, "SELECT * FROM document_versions WHERE id=:v", v=job["version_id"])
            .mappings()
            .one()
        )
        run(conn, "UPDATE document_versions SET status='processing' WHERE id=:v", v=version["id"])
    try:
        content = object_path(version["storage_key"]).read_text(encoding="utf-8-sig")
        meta, body = parse_front_matter(content)
        chunks = split_passages(body)
        vectors = None
        if settings.semantic_search:
            from .embeddings import encode

            vectors = encode([p.text for p in chunks])
        with transaction(workspace) as conn:
            current = (
                run(conn, "SELECT * FROM ingestion_jobs WHERE id=:i FOR UPDATE", i=job["id"])
                .mappings()
                .one()
            )
            doc = (
                run(
                    conn, "SELECT * FROM documents WHERE id=:d FOR UPDATE", d=version["document_id"]
                )
                .mappings()
                .one()
            )
            if current["lease_token"] != lease:
                return True
            status = "superseded"
            if not doc["deleted"] and doc["latest_version"] == version["id"]:
                run(conn, "DELETE FROM chunks WHERE version_id=:v", v=version["id"])
                for ordinal, passage in enumerate(chunks):
                    run(
                        conn,
                        """INSERT INTO chunks(id,workspace_id,version_id,section,section_path,
                      content_key,ordinal,content) VALUES(:i,:w,:v,:s,:sp,:k,:o,:c)""",
                        i=new_id(),
                        w=workspace,
                        v=version["id"],
                        s=passage.section,
                        sp=passage.section_path,
                        k=passage.key,
                        o=ordinal,
                        c=passage.text,
                    )
                if vectors is not None:
                    from .embeddings import IDENTIFIER

                    for ordinal, vector in enumerate(vectors):
                        run(
                            conn,
                            "UPDATE chunks SET embedding=CAST(:e AS vector) WHERE version_id=:v AND ordinal=:o",
                            e=vector,
                            v=version["id"],
                            o=ordinal,
                        )
                    run(
                        conn,
                        "UPDATE document_versions SET embedding_model=:m WHERE id=:v",
                        m=IDENTIFIER,
                        v=version["id"],
                    )
                due = run(
                    conn,
                    "SELECT CAST(:e AS date) IS NULL OR :e <= current_date",
                    e=meta.get("effective"),
                ).scalar()
                # A future effective date keeps the current version answering until that day.
                status = "ready" if due else "scheduled"
                if due:
                    activate(conn, workspace, version["id"], version["document_id"])
            run(
                conn,
                "UPDATE ingestion_jobs SET status='ready',lease_until=NULL WHERE id=:i",
                i=job["id"],
            )
            run(
                conn,
                """UPDATE document_versions SET status=:s,error=NULL,extraction_version=:x,
              owner=:o,effective_from=:e WHERE id=:v""",
                v=version["id"],
                s=status,
                x=EXTRACTION_VERSION,
                o=meta.get("owner"),
                e=meta.get("effective"),
            )
    except (OSError, UnicodeError, ValueError, HTTPException):
        with transaction(workspace) as conn:
            run(
                conn,
                """UPDATE ingestion_jobs SET status=CASE WHEN attempts>=3 THEN 'failed'
              ELSE 'queued' END, available_at=now()+interval '10 seconds',lease_until=NULL
              WHERE id=:i AND lease_token=:l""",
                i=job["id"],
                l=lease,
            )
            run(
                conn,
                # Failed only once retries are exhausted; until then the version is queued again.
                """UPDATE document_versions v SET error='extraction_failed',
              status=CASE WHEN j.status='failed' THEN 'failed' ELSE 'queued' END
              FROM ingestion_jobs j WHERE v.id=:v AND j.id=:i AND j.lease_token=:l""",
                v=version["id"],
                i=job["id"],
                l=lease,
            )
    return True


def activate(conn, workspace, version_id, document_id):
    run(conn, "UPDATE documents SET active_version=:v WHERE id=:d", v=version_id, d=document_id)
    # Imported here because reviews imports new_id from this module.
    from .reviews import outdate_for_document

    outdate_for_document(conn, workspace, document_id)


def activate_due(workspace):
    """Activate scheduled versions whose effective date has arrived."""
    with transaction(workspace) as conn:
        due = run(
            conn,
            """SELECT v.id,v.document_id,(d.latest_version=v.id AND NOT d.deleted) AS current
          FROM document_versions v JOIN documents d
          ON d.workspace_id=v.workspace_id AND d.id=v.document_id
          WHERE v.status='scheduled' AND v.effective_from<=current_date
          ORDER BY v.effective_from FOR UPDATE OF v,d""",
        ).all()
        for version in due:
            if version.current:
                activate(conn, workspace, version.id, version.document_id)
            run(
                conn,
                "UPDATE document_versions SET status=:s WHERE id=:v",
                s="ready" if version.current else "superseded",
                v=version.id,
            )
    return len(due)


def cleanup(workspace):
    with transaction(workspace) as conn:
        versions = run(
            conn,
            """SELECT v.* FROM document_versions v JOIN documents d
          ON d.workspace_id=v.workspace_id AND d.id=v.document_id
          WHERE d.deleted AND v.cleaned_at IS NULL""",
        ).mappings()
        for version in versions:
            object_path(version["storage_key"]).unlink(missing_ok=True)
            run(conn, "DELETE FROM chunks WHERE version_id=:v", v=version["id"])
            # Marked so each deleted version is cleaned once, not on every worker tick.
            run(
                conn,
                "UPDATE document_versions SET cleaned_at=now() WHERE id=:v",
                v=version["id"],
            )


def diff_versions(conn, document_id, old_number, new_number):
    """Compare two versions section by section using passage content keys."""

    def passages(number):
        return run(
            conn,
            """SELECT c.section_path,c.content_key,c.content FROM chunks c
          JOIN document_versions v ON v.workspace_id=c.workspace_id AND v.id=c.version_id
          WHERE v.document_id=:d AND v.number=:n ORDER BY c.ordinal""",
            d=document_id,
            n=number,
        ).all()

    old, new = passages(old_number), passages(new_number)
    if not old or not new:
        raise HTTPException(404, "version_not_found")
    sections = list(dict.fromkeys([p.section_path for p in new] + [p.section_path for p in old]))
    changes = []
    for path in sections:
        before = [p for p in old if p.section_path == path]
        after = [p for p in new if p.section_path == path]
        before_keys, after_keys = {p.content_key for p in before}, {p.content_key for p in after}
        if not before:
            status = "added"
        elif not after:
            status = "removed"
        elif before_keys == after_keys:
            status = "unchanged"
        else:
            status = "changed"
        changes.append(
            {
                "section_path": path,
                "status": status,
                "removed": [p.content for p in before if p.content_key not in after_keys],
                "added": [p.content for p in after if p.content_key not in before_keys],
            }
        )
    return {"document_id": document_id, "from": old_number, "to": new_number, "sections": changes}
