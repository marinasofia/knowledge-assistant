"""Optional local semantic encoding. Never loads remote executable model code."""

import json
from functools import lru_cache

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
IDENTIFIER = MODEL + "@" + REVISION


@lru_cache(maxsize=1)
def model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL, revision=REVISION, trust_remote_code=False, device="cpu")


def encode(texts):
    vectors = model().encode(texts, normalize_embeddings=True, batch_size=16)
    if vectors.shape[1] != 384:
        raise ValueError("embedding_dimension_mismatch")
    return [json.dumps(v.tolist()) for v in vectors]


def fuse_ranks(*rankings, limit=5):
    scores, records, first_seen = {}, {}, {}
    for ranking in rankings:
        for position, item in enumerate(ranking, 1):
            key = item["source_id"]
            records[key] = item
            first_seen.setdefault(key, len(first_seen))
            scores[key] = scores.get(key, 0) + 1 / (60 + position)
    # Ties keep first-seen order; source IDs are random UUIDs and would reorder between seeds.
    ordered = sorted(scores, key=lambda k: (-scores[k], first_seen[k]))
    return [records[key] for key in ordered[:limit]]
