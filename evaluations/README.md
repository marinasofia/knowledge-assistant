# Evaluation protocol

The versioned corpus has 60 draft cases: 25 answerable, 10 multi-document, 10 unanswerable, 5 conflicting, and 10 injection cases. Development has 40 cases and held-out has 20. Labels were authored during implementation and have not been reviewed by a human. They are not a production acceptance dataset.

`cases.json` contains expected source document and section pairs and acceptable outcome categories. Source IDs are generated at ingestion and therefore resolved by provenance during evaluation. The same fictional six-document corpus must be seeded before evaluation. Do not include test uploads in the retrieval corpus.

Run after optional semantic setup and reindexing:

```sh
cd backend
uv run --extra semantic python -m app.evaluate --split development
uv run --extra semantic python -m app.evaluate --split held-out
```

Reports compare keyword retrieval with hybrid retrieval at five passages. Numerators count retrieved expected passages; denominators count labeled expected passages. This is passage recall on draft labels, not claim support or answer correctness. Do not tune on the held-out report. Reports also record the local evidence mode outcome (answer or abstain) for every case against its expected outcome. Evidence mode abstains when the best passage contains fewer than 40% of the question's search terms. This is a lexical check, not semantic abstention, and evidence mode never detects conflicts, so it cannot satisfy the live answer-quality gates. The evaluator refuses to run in provider mode so that it never makes paid calls.

Provisional release targets remain 85% recall@5, 90% sampled claim support, and 90% correct abstention after human review. Human reviewers must check every substantive claim against its cited passage, mark unsupported claims and misleading omissions, and independently flag unresolved policy conflicts. Two reviewers should adjudicate disagreements before claiming human-reviewed results. No human review or independent security review is claimed here.

The injection cases are prompts to the application, not instructions for operators. Hard authorization and citation invariants are tested independently in pytest. A model judge, if added later, cannot replace those tests or the human review rubric.

## Metrics

Per labeled case, over the top five passages, keyed by (document title, section):

* Recall@5: share of expected passages retrieved.
* MRR: reciprocal rank of the first expected passage.
* nDCG@5: binary relevance nDCG (Järvelin and Kekäläinen, 2002), which rewards expected passages ranked higher.

Keyword and hybrid are compared with a paired randomization test on per-question nDCG@5 (10,000 sign flips, fixed seed), following Smucker, Allan and Carterette (CIKM 2007). Each report also carries an abstention curve: for thresholds 0.00 to 1.00 on top passage coverage, the share of cases answered, the share of answers that should have been abstentions (risk), and the share of answerable cases wrongly refused. This is the selective prediction framing (El-Yaniv and Wiener, 2010).

Ranking ties are broken by document title and passage order, and rank fusion keeps first-seen order on ties, so a fresh database gives byte-identical reports. This was verified by dropping the evaluation database, reseeding, and comparing both reports.

## Observed run (Sep 28 2026, structured passages, deterministic ranking)

| Split | Mode | Recall@5 | MRR | nDCG@5 |
|---|---|---|---|---|
| Development (28 labeled) | Keyword | 0.964 | 0.920 | 0.908 |
| Development | Hybrid | 0.964 | 0.946 | 0.930 |
| Held-out (12 labeled) | Keyword | 0.917 | 0.958 | 0.898 |
| Held-out | Hybrid | 1.000 | 1.000 | 0.976 |

Hybrid is ahead on both splits, but the paired randomization test gives p = 0.19 (development) and p = 0.25 (held-out). With 28 and 12 labeled questions the difference is not distinguishable from noise. Earlier runs that reported keyword ahead by one passage were within the tie-break noise described above.

Evidence mode outcomes with keyword retrieval:

| Category | Development | Held-out |
|---|---|---|
| Answerable, answered | 17/17 | 8/8 |
| Multi-document, answered | 5/7 | 3/3 |
| Unanswerable, abstained | 6/6 | 4/4 |
| Injection, abstained | 6/6 | 3/4 |
| Conflicting, flagged | 3/4 | 0/1 |

On the development curve, risk reaches zero at a coverage threshold of 0.35 and stays zero above it, while wrongly refused answerable cases rise from 7 percent at 0.35 and 0.40 to 18 percent at 0.45 and 36 percent at 0.55. The 0.4 threshold sits at that knee. Conflicts are flagged when two documents give different figures under the same section title and the best matching passage is one of them; this rule was chosen on the development split over counting any disagreement in the evidence, which flagged 2 of 17 answerable questions. The held-out conflicting case ("How much can field employees claim for meals?") is missed under keyword retrieval because only the field handbook's meal passage is retrieved, so there is no second document to compare; hybrid retrieval returns both meal passages and flags it. The development miss ("Does the field handbook agree with the travel policy?") matches the handbook's introduction, not a shared section. Held-out numbers were visible while these rules were chosen, so they are not a strictly blind check.

Tried and rejected (Sep 28 2026): adding passages from other documents under the best passage's section title before conflict detection. It flagged the held-out conflict, but on the development split it made one answerable question ("When does the team work together?") a false conflict, because keyword retrieval ranks the field handbook's meal passage first for it. Development results decide, so it was not adopted.

Limits: labels are draft and written by the author, the corpus is six short documents, the conflict rule misses disagreements that use different section titles or no figures, and lexical coverage cannot read intent (the remaining injection miss shares most of its words with the hotel policy). No human semantic support, correct abstention, or conflict-resolution score has been measured.
