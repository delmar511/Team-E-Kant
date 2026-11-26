# Takeaways: project status check and project-specific agents

Session: 2026-11-25 to 2026-11-26. A record of what was asked, what was answered, where it went wrong, and what to do differently next time.

---

## 1. What happened, in order

| #   | You asked                                                                                    | I answered                                                                                                                                                                                                                                                                                                                                             | Was it right?                                                                                                                                          |
| --- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Gave me the roadmap PDF (status as of 11-24) and the roles PDF. "Has everything been built?" | "No, the project is still at an early stage." I listed steps 1, 2 and 4 as drafted, step 5 (`schemas.py`, `config.py`) as not started, and steps 3 and 7–20 as not started.                                                                                                                                                                            | **Wrong.** I only read the PDFs, not the repo. Git history already showed merged PRs for ingest, BM25/vector retrieval, the answer agent and dev runs. |
| 2   | "Check again, `schemas.py` and `config.py` should be there."                                 | Read both files. Both are fully implemented. I said "the roadmap is out of date."                                                                                                                                                                                                                                                                      | Partly right. I corrected step 5 but still called steps 1–4 the blockers without checking anything else, so most of the first mistake stayed.          |
| 3   | (switched model to Opus) "Does the agents file mention model switching for different tasks?" | Found `agents/`. Each agent pins a model in its frontmatter (`opus` for senior-dev and debugger, `sonnet` for the other four). There's no general rule for when to switch. I also found that the agents describe a different project (iPhone Photo Manager) and sit where Claude Code doesn't load them. I admitted the first status answer was wrong. | Right, and it found two problems you hadn't asked about.                                                                                               |
| 4   | "Build agents with the same roles, but fitted to this project."                              | Read all six originals plus `problem.md`, `design.md`, both interface docs, `search_adapter.py`, `requirements.txt` and the repo file list. Wrote six agents in `.claude/agents/` with the same models.                                                                                                                                                | Done. Based on the real repo, not the plan PDF.                                                                                                        |
| 5   | "Summarize this and put the findings in takeaway.md."                                        | This file.                                                                                                                                                                                                                                                                                                                                             |                                                                                                                                                        |

---

## 2. Insights

### 2.1 Planning documents go stale; the repo is the source of truth

- The roadmap said step 5 was "not started" one day before. The code was already written, tested and merged, and much more besides.
- The roles PDF describes a layout (`retrieval/pipeline.py`, `ingest/loader.py`, `eval/dev.json`) that the team didn't use. The real files are `src/retrieve.py`, `src/search_adapter.py`, `src/ingest/chunk.py`, `eval/eval-dev.json`.
- **Lesson:** to answer "is it built?", check `git log` and the file list first, then use the plan to see what's missing. A status snapshot is a claim about one moment, not a fact about now.

### 2.2 How the question was answered mattered more than which model answered

- The first two answers came from a smaller, faster model and the last two from Opus. But the main error, trusting the PDF without looking, was a process mistake that any model can make.
- The evidence was already in the context: the git status at the start of the session listed the merged PRs. It was ignored.
- **Lesson:** for status or audit questions, ask for verification explicitly ("check the repo, not just the doc"). When an answer is surprising, push back as you did in turn 2. Your push corrected one file; asking "what else did you assume?" would have caught the rest.

### 2.3 A correction for one item can hide the same mistake elsewhere

- After you corrected step 5, I fixed step 5 only and repeated the same untested assumptions for every other step.
- **Lesson:** when one claim turns out wrong, ask whether the method behind it was wrong. If it was, recheck everything that method produced.

### 2.4 Reusing agent definitions: copying a file isn't adapting it

- The agents in `agents/` came from another project. Every file talked about iPhones, TypeScript, Zod and TanStack Query, and they sat in a folder Claude Code never reads (`.claude/agents/` is the project location).
- So the `model:` settings you asked about had no effect.
- **Lesson:** an agent is only as useful as its project knowledge. Keep the structure (roles, workflow, output format, the "ask a human" rule) and rewrite the content (files, invariants, commands, known errors).

### 2.5 What "the safety rule" is depends on the project

- The iPhone app's core invariant was "never delete a photo without a verified copy."
- This project has no user data to destroy. What can be destroyed is **the credibility of the measured numbers**. So the new agents' invariants protect the evaluation:
  - tune on dev only, never on test
  - errors never count as a correct "no evidence" answer
  - `results/runs/` is append-only and failed runs are kept
  - configs A, B and C differ only in retrieval
  - never add BM25 and vector scores together; reranking must recompute relevance
  - no answer-key data goes to the rewriter, prompt or evidence gate
  - chunk IDs stay stable (rechunking breaks Hit@5)
- **Lesson:** before writing rules for agents, ask "what is the worst thing that could go wrong without anyone noticing?" Build the rules around that.

### 2.6 Model choice in the agents follows the task

- Opus: tasks that write or change code and need deep reasoning (senior-dev, debugger).
- Sonnet: read-only or narrow tasks (review, planning, standards lookup, schema edits).
- The rule is a rough guide, not a law: use the stronger model where a mistake is expensive and hard to spot.

### 2.7 Things found in the repo along the way (still open)

These came out while reading the code for the agents. They're recorded in the `debugger` and `schema-generator` agents as well.

- `config.py` uses `tomllib` (Python 3.11+), but `requirements.txt` says 3.10.
- `base.toml` uses `index_dir = "index"`, but the index is in `data/index`. `config.py` looks for `manifest.json`; `build_index.py` writes `meta.json`.
- The eval file evidence format (`page, section, quote, chunk_id, chunk_ids_all`) doesn't match `schemas.EvalItem` (`doc_id, location, excerpt, chunk_id, required`).
- `GenerationConfig` has `temperature`, which Claude Opus 5.5 rejects, and no `effort` field, so effort isn't part of the version string.
- `FusionConfig` has no field for RRF weights.
- `tests/test_config.py` matches English error text, but the messages are now in Korean.
- Config C (reranker) isn't implemented yet; `search_adapter.py` raises `ConfigError` for it.
- `docs/design.md` still has several `[기입]` blanks.
- `docs/problem.md` still has placeholder dates and manual version (`YYYY-MM-DD`, `YYMMDD`).

---

## 3. What was produced

| File                                   | Role                                                                                   | Model  |
| -------------------------------------- | -------------------------------------------------------------------------------------- | ------ |
| `.claude/agents/coding-rules.md`       | Single source of standards and evaluation invariants for this repo                     | sonnet |
| `.claude/agents/senior-dev.md`         | Builds bottom-up, then verifies with pytest, a dev Hit@5 run and a free test run       | opus   |
| `.claude/agents/code-reviewer.md`      | Read-only review, evaluation rules checked first                                       | sonnet |
| `.claude/agents/debugger.md`           | Known failures in this repo, plus sorting failed runs into problem.md §11.4 categories | opus   |
| `.claude/agents/pipeline-architect.md` | Plans a new part (reranker, gate, cache/rewrite, metrics, Streamlit) before code       | sonnet |
| `.claude/agents/schema-generator.md`   | Maintains `schemas.py`, `config.py`, `configs/*.toml`, eval format                     | sonnet |

All six ask a human first before: editing `eval-test.json` or `problem.md` §11, deleting or rewriting results, rechunking, or a paid Claude run. They also ask whenever they're 20% sure or less.

The original `agents/` folder is untouched and untracked. Nothing has been committed.

---

## 4. Checklist for next time

1. **Status questions:** "Check git log and the files, then compare with the plan." Don't accept an answer built only from a document.
2. **When you correct me:** also ask "what else did you assume the same way?"
3. **Reusing agents, prompts or configs from another project:** check the folder location, then rewrite the project facts, not just the names.
4. **Writing agent rules:** start from the worst silent failure for this project.
5. **Choosing a model:** use the stronger model where a mistake is costly or hard to see; a smaller one is fine for lookups and read-only checks.

---

---

# Part 2: audit against the requirements, then filling the gaps

Session: 2026-11-25 to 2026-11-26.

## 1. What happened, in order

| #   | You asked                                                                                       | I answered or did                                                                                                                                                                                                                                                                                                                                                                             | Was it right?                                                                                                                                                                  |
| --- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Pasted the full project requirements. "What is present, what's missing, what errors are there?" | Read git history, configs, eval files, code and the saved dev run before answering. Listed what works (retrieval A/B, agent, cache/rewrite code, run logging), what's missing (reranker, test-set answers, README, report, metrics, UI, cache test) and what's wrong (placeholder versions, unpinned embedding model, no-answer items with evidence, missing packages).                       | Mostly right, and this time it was checked against the repo (Part 1's lesson applied). One wrong cause: I called "the model refuses too often" the biggest problem. See row 2. |
| 2   | "Do what you can while I bring the test answers."                                               | Set up a venv. That exposed a pip failure on Windows and 5 failing tests. Then: wrote `metrics.py` and the 15-run cache test, fixed the cache key, `requirements.txt`, `.env.example` and `chunk.py`, filled the document list, wrote the README, moved the dev no-answer evidence. Reproduced the BM25 baseline (4/8) and confirmed rebuilt chunks are byte-identical to the committed file. | Right. It also **corrected my own diagnosis from row 1**: looking at the saved answers showed the refusals came from missing evidence chunks, not the evidence check.          |
| 3   | "1. go ahead (reranker) 2. use KURE-v1."                                                        | Built config C (cross-encoder `bge-reranker-v2-m3`, 20 in, 5 to the prompt, before/after ranks logged). Pinned KURE-v1 and the real chunking values. Started the vector build and model download in the background. Noticed files changing under me: DOC-INTRO, the filled test set, teammate's PR #7.                                                                                        | Code and tests done. **Config C was never measured**: the background jobs died with the session, and the chunk file changed while the vectors were building.                   |
| 4   | "Give me a branch name, title and summary."                                                     | Gave them in Korean (repo style), suggested two commits: your data (DOC-INTRO, test set) first, my code second.                                                                                                                                                                                                                                                                               | Right.                                                                                                                                                                         |
| 5   | "Can't merge because of `run_experiment.py`."                                                   | Merged `main` locally. Took the teammate's version and re-applied my one small change. Updated the cache runner to their new log format. 56 tests passed and both runners worked in a dry run. Left the merge staged for you to commit.                                                                                                                                                       | Right.                                                                                                                                                                         |
| 6   | Daily brief, then "in Korean".                                                                  | Wrote both.                                                                                                                                                                                                                                                                                                                                                                                   | Right.                                                                                                                                                                         |
| 7   | This summary.                                                                                   | This section.                                                                                                                                                                                                                                                                                                                                                                                 |                                                                                                                                                                                |

## 2. Insights

### 2.1 Look at the raw output before blaming a component

- The dev run showed many "no evidence" answers. I first blamed the evidence check (the answer step being too cautious).
- Reading the saved answers showed something else: the model answered what it had and named what was missing. **Every "refusal" was missing at least one expected evidence chunk from its top 5.**
- In config A, none of the 8 dev questions had _all_ their evidence in the top 5, yet Hit@5 was 8/8.
- **Lesson:** Hit@5 counts a question as found if _one_ evidence chunk is in the top 5. For questions that need several chunks, it overstates retrieval quality. Report "all evidence in top 5" next to it. Loosening the refusal rule would have made things worse: confident wrong answers, the error `problem.md` ranks as most dangerous.

### 2.2 Running the code finds bugs that reading doesn't

Reading the repo in row 1 missed all of these. Setting up an environment and running things found them in minutes:

- `pip install -r requirements.txt` fails on Windows (Korean comments read as cp1252). Fixed with a `# -*- coding: utf-8 -*-` line.
- Every script that prints Korean crashes on a Windows console. Fix: `PYTHONUTF8=1` (now in the README).
- 5 tests failed only because someone translated the error messages and the tests still expected English.
- `requirements.txt` said Python 3.10 but the code needs 3.11.
- **Lesson:** "can another teammate reproduce it?" is a requirement (평가표 11). The only way to know is to run it on a clean machine. Try it early, not on the last day.

### 2.3 A version must track content, not a label

- The cache key used `index_version`, but `index_version` was a hash of the _config_ only. Rebuilding the chunks without editing a config left it unchanged, so **old answers could be reused after the documents changed**. That is exactly what the cache test exists to catch.
- Fix: include a hash of `data/chunks.jsonl`, with line endings normalized so Windows and macOS checkouts agree.
- Run records said `embedding_model: "TBD"`, and two reports used two different models. Nobody could tell which model produced which number.
- **Lesson:** any number you'll report must be traceable to exact inputs. Placeholders (`TBD`, `YYMMDD`) in a run record make that run unattributable. Pin values before the runs that count.

### 2.4 Working while others change the same files

- During the session, `design.md`, `eval-dev.json`, `chunks.jsonl` and the test set changed on disk, and a teammate merged PR #7.
- What helped: working on a branch; checking `git status` before committing; reading a file again before editing it; not overwriting edits I didn't make (I added to `design.md` and left your idx-v2 line alone).
- What went wrong: I started a 1,646-chunk vector build while the chunk file was being changed. The result would have been an index that silently didn't match the chunks.
- **Merge conflicts:** take the version that changed more (theirs) and re-apply your smallest change on top. Don't hand-merge two big rewrites.
- **Lesson:** before a slow build, freeze its input (note the file hash or row count). Check afterwards that the output matches.

### 2.5 Background jobs don't survive the session

- The vector build and model download were left running in the background. The session ended and both were marked stopped, with no record of finishing.
- **Lesson:** for long jobs, write a log file and check it next time. Never report a result from a job you didn't see finish.

### 2.6 Ask before taking over someone else's part

- The reranker was assigned to 서종찬, so I asked before building it. You said go ahead.
- **Lesson:** "do what you can" doesn't cover other people's assignments. A one-line question avoids two people building the same thing.

### 2.7 Small mistakes of mine worth knowing about

- Twice, shell escaping turned `\r\n` or `\\` inside Python code into real line breaks and broke the file. Writing the script to a file first avoided it. A test run caught it each time.
- I wrote "pages 1–10 aren't indexed" when the data said 1–13. Caught when I re-read the output.
- **Lesson:** run the tests or re-read the output after every edit. Cheap checks catch cheap mistakes.

### 2.8 Part 1's open items (section 2.7 there), now

| Item                                      | Status                                                                                                |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `tomllib` vs Python 3.10                  | Fixed (requirements says 3.11+)                                                                       |
| `index_dir = "index"`                     | Fixed (`data/index`)                                                                                  |
| Tests expecting English errors            | Fixed                                                                                                 |
| Config C not implemented                  | Implemented; **not yet measured by me** (`results/ragas/` has a team dev A-B-C run I haven't checked) |
| `design.md` blanks                        | Reranker and model rows filled; others remain                                                         |
| `problem.md` placeholders                 | Not touched                                                                                           |
| Eval evidence format ≠ `schemas.EvalItem` | Still mismatched. The scripts read `page / section / quote / chunk_id`, so use that for the test set  |
| RRF weights not configurable              | Still open (B uses equal weights, though the dev sweep found BM25 at equal weight made results worse) |

## 3. What was produced

| File                                                                   | What it does                                                                                                                       |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `src/rerank.py`, `configs/C.toml`, C branch in `src/search_adapter.py` | Config C: cross-encoder reranking, before/after ranks logged, `rerank_ms` timed separately                                         |
| `experiments/metrics.py`                                               | Score sheet for hand scoring (errors pre-scored 0) and the A/B/C table with every STEP 6 metric                                    |
| `experiments/run_cache_experiment.py`                                  | The 15 cache runs, each checked against its expected outcome                                                                       |
| `README.md`, `docs/document_index.md`, part of `docs/design.md`        | Reproduction steps, the 36-document list (later corpus changes not reflected), reranker design                                     |
| Fixes                                                                  | cache key, Windows install and encoding, `.env.example`, config tests, real embedding model in run records, dev no-answer evidence |
| Tests                                                                  | `tests/test_metrics.py`, `tests/test_rerank.py`; 56 passing after the merge                                                        |

## 4. Still open at the end of this session

- `main` has moved on to PR #17, and the corpus is now 1,815 chunks. A KURE-v1 index for 1,815 chunks exists in `data/index/` (built after my session), and both models are downloaded.
- Config C's dev Hit@5 and full-evidence recall still need to be measured on that index, before the test set is frozen.
- `docs/document_index.md` lists the 36 original documents; it needs updating for the current corpus.

## 5. Checklist for next time

1. **Before blaming a component, read 3–5 raw outputs.** The cause is often one step earlier.
2. **Report "all evidence found" next to Hit@5** whenever questions need several evidence chunks.
3. **Run setup on a clean environment early.** That's how reproducibility bugs show up.
4. **Version by content hash, not by hand-typed labels.** No `TBD` in any run that counts.
5. **Before a long build, note its input; after it, check the output matches.** Check that background jobs actually finished.
6. **On a merge conflict, keep the bigger rewrite and re-apply your small change.**
7. **Ask before working on a teammate's assigned part.**

---

# Takeaways: pages 1–13 not indexed, and what `vectors.npy` is

Session: 2026-11-25 to 2026-11-26 (branch `feat/metrics-and-gaps`).

## 1. What happened, in order

| #   | You asked                                                   | I answered                                                                                                                                                                                                                                                               | Was it right?                                                                                                                                                  |
| --- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "What do you mean pages 1–13 of the manual aren't indexed?" | Traced the claim to `docs/document_index.md`. The corpus starts at p.14, so the cover, TOC and 유의사항/공통사항 had no chunks. DEV-009's p.3 evidence quote ("허가 여부는 심사에 의해 결정될 수 있습니다") therefore had `chunk_id: null` and could never be retrieved. | Right, but my message was cut off before the proposed fix.                                                                                                     |
| 2   | "Go ahead."                                                 | Added `DOC-INTRO` (pp.3–8, 12–13) with a new converter `src/ingest/intro_to_md.py`. Left out the cover/TOC (1–2) and a blank form (9–11). Re-chunked (1,646 → 1,653, all old chunk IDs unchanged), rebuilt BM25 as `idx-v2`, linked DEV-009, updated the docs.           | Done and checked. Two limits: the fee table on p.5 was transcribed from text extraction, not checked against the page image; the vector index was not rebuilt. |
| 3   | "Why can't I rebuild `vectors.npy`, do I not have access?"  | Not an access problem. I had said "couldn't" when I meant "didn't". The file is git-ignored and was never built on this machine. The model and libraries are installed; `EMBEDDING_MODEL` must be set or the script writes a file search ignores.                        | Right, after correcting my own wording.                                                                                                                        |
| 4   | "What is `vectors.npy`?"                                    | One embedding row per chunk (1,653 × 1,024), matched to chunks only by row order. Used for meaning-based search, fused with BM25.                                                                                                                                        | Right.                                                                                                                                                         |
| 5   | "Is there a vector store here?"                             | No. A NumPy dot product over the whole array (`retrieve.py:91`). FAISS/Chroma are commented out in `requirements.txt`; not needed at this size.                                                                                                                          | Right.                                                                                                                                                         |

## 2. Insights

- **A missing chunk makes an eval item silently unwinnable.** DEV-009 could never score a hit, and nothing failed loudly. Check that every eval evidence quote resolves to a `chunk_id` before trusting Hit@5.
- **A converter written for one layout breaks on another.** The table converter cut numbered sentences in half on non-table pages, and the chunker then dropped the short halves. Read the converted Markdown before indexing it.
- **Text extraction can scramble tables.** The `-layout` mode paired the wrong fee with the wrong task. `-raw` gave the right pairs; cross-checking three extraction modes caught it. For numbers people will rely on, check against the page itself.
- **Hash-based chunk IDs made adding a document safe.** IDs depend only on each document's own content, so a new document left all 1,646 existing IDs untouched. Comparing old and new `chunks.jsonl` proved it in one step.
- **Page markers before headings shift page numbers.** The chunker records the page at emit time, so a section can be cited one page late. Avoided in `DOC-INTRO`; 129 such spots remain in the old corpus (한계 L9).
- **Indexes matched by row order must be rebuilt together.** `vectors.npy` has no chunk IDs inside it; after any re-chunk, BM25 and vectors must both be rebuilt or they drift apart.
- **Say "didn't" when you mean "didn't".** "Couldn't rebuild vectors" sounded like a permission problem and cost a question. It was a choice not to start a long job.
- **Unrelated edits appeared during the session.** Config files and tests changed without my touching them; 4 test failures came from that, not from this change. Check `git diff` before blaming your own work.

## 3. Still open from this session

- Compare the p.5 fee table in `intro_to_md.FEES` with the PDF page.
- Rebuild `vectors.npy`: `EMBEDDING_MODEL=nlpai-lab/KURE-v1 .venv/Scripts/python.exe src/build_vectors.py`.
- Decide whether to fix 한계 L9 (page attribution) in the old corpus.
- The section above records a later corpus of 1,815 chunks; check whether `DOC-INTRO` survived into it.

---

# Takeaways: requirements audit, chunk page bug, test evidence, chunking strategy

Session: 2026-11-26 (branch `feat/rerank-metrics-cache`).

## 1. What happened, in order

| #   | You asked                                                                                                        | I answered or did                                                                                                                                                                                                                                    | Was it right?                                                                                                |
| --- | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 1   | Pasted the requirements. "Is everything done?"                                                                   | No. Code for days 1–3 exists; the 60 main runs, 15 cache runs, scoring, `report.md`, UI, `contributions.md`, re-run by a teammate and the tag are missing. Blockers: test evidence had no `chunk_id`s; TEST-010 had a type the loader doesn't allow. | Right, and checked against the repo.                                                                         |
| 2   | "Fix #2 first." Then "can I change the type?", "5 per category?"                                                 | TEST-010 `false_premise` → `direct` (spec split 10/7/3), logged in the change log. Advised against 5/5/5/5: it breaks the spec's fixed split and denominators.                                                                                       | Right. You agreed to keep the spec split.                                                                    |
| 3   | "Is the missing chunk_id because of the chunks?"                                                                 | First: no, it's a process gap (test evidence was written as `{source, page}` with no quote, and the linking step was left to "the owner").                                                                                                           | **Half wrong.** Drafting evidence later showed the chunks were also at fault (row 5).                        |
| 4   | Chose option 3: Claude drafts, a teammate verifies.                                                              | Listed the chunks on each cited page against `expected_facts`.                                                                                                                                                                                       |                                                                                                              |
| 5   | (found while drafting)                                                                                           | **Page bug:** `chunk.py` stamped each chunk with the page where its section _ended_. 726/1,653 chunks (44%) were wrong, some by 10 pages. Fixed it, added tests, rebuilt BM25 as `idx-v3`. IDs, text and dev retrieval were unchanged.               | Right. It corrected my answer in row 3.                                                                      |
| 6   | "Go ahead."                                                                                                      | Drafted 33 evidence items for TEST-001–017. Every quote checked as a substring of its chunk; the team's linker agreed 33/33. Marked "drafted by Claude, needs human verification".                                                                   | Done. One fact (TEST-004, the 15-day deadline) lives only in a body-less heading (L8), so no chunk holds it. |
| 7   | "How do we fix PDF glyph artifacts?" → "write a prompt"                                                          | 290 chunks contain private-use glyphs (`` = `·`, bullets, form junk). Wrote a prompt for a mapping fix.                                                                                                                                             | Right, with a correction: I had said they hurt BM25; testing showed the tokenizer drops them.                |
| 8   | "Overview of the chunking", "compare with fixed-size, recursive, semantic", "why this one?", "is there overlap?" | Heading-based chunking, a 1,200-character cap, no overlap, heading path used as context. It suits a list-heavy manual with one rule per heading, but it was **never measured** against the alternatives.                                             | Right.                                                                                                       |
| 9   | "Would overlap help?" → chose option 2 → "write a prompt"                                                        | Overlap helps only where long sections are split (128 sections; 9 test evidence items sit in them). Recommended parent-section expansion at answer time instead. Wrote the prompt.                                                                   | Right.                                                                                                       |

## 2. Insights

- **Doing the work reveals what inspection misses.** "Is it the chunks?" looked like a no from the git history. Picking chunks one by one showed TEST-004's evidence filed 10 pages away, and that exposed the page bug. Don't settle a diagnosis by reading alone if you can test it on a real case.
- **A team's known limitation can understate the problem.** L9 said "129 spots, off by one page". Measuring found 604 chunks, off by up to 10. Measure the scope before deciding to postpone a fix.
- **Check whether a fix will change IDs before you make it.** The page fix was cheap because `page` isn't part of the chunk ID hash, so the answer keys and vectors survived. The glyph fix would change 189 IDs, and overlap about 290. That cost decides _when_ a fix is safe: before the eval set is frozen.
- **Verify AI-drafted answer keys mechanically, then by a person.** The substring check and the independent linker check caught a hidden glyph in one quote. Neither replaces a human checking the meaning, so the draft is labelled and `verified_by` stays empty.
- **Test a claim of harm before repeating it.** "Glyphs hurt BM25" sounded plausible; one tokenizer call disproved it. The real harm was in the text shown to the LLM and in citations.
- **Spec constraints come before personal preference.** 5/5/5/5 looks balanced but breaks the required 10/7/3 split and its denominators.
- **Chunking strategy should follow the document.** Heading-based chunking matches a manual with one rule per heading and protects lists and tables. Its weak spot is the split pieces. Fix that where the failure is (give the model the whole section), not with blanket overlap. A design choice needs either a measurement or an honest "reasoned, not measured" in the report.
- **Reusable prompts need guardrails written in.** Each prompt said: no test-set runs, don't commit, leave teammates' uncommitted files alone, prove IDs and text are unchanged, and ask before paid API runs.

## 3. Still open from this session

- A teammate verifies the 33 drafted evidence items (`verified_by` / `reviewed_by`) before the eval set is frozen.
- TEST-004 15-day fact (L8): treat it as a retrieval limitation, or fix L8 (changes some IDs).
- Glyph cleanup and section expansion: prompts written, not yet run. `tests/test_chunk.py` was changed on disk by someone else during this session (fold/drop, `section_key`); check whether that work has started and whether it changed chunk IDs.
- `design.md` §2 is still a template describing statute-article chunking. `batch_convert.py` imports a `convert` module that doesn't exist, and works in `/tmp`.
- The `schemas.EvalItem` format still doesn't match either eval file.
- Nothing from this session is committed.

## 4. Checklist for next time

1. **Test a diagnosis on one concrete case** before answering "is it X?".
2. **Measure the scope of a known limitation** before accepting "fix later".
3. **Before any data fix, ask: do IDs change? does the answer key change?** Do it before the freeze or not at all.
4. **Label AI-drafted answer keys** and keep them unverified until a person checks them.
5. **Check constraints in the spec** before changing the eval design.
6. **Write a design choice up as a decision, or measure it.** Don't present it as an improvement without numbers.

# Takeaways: running the RAG, switching to OpenAI, and finding a chunking bug

Session: 2026-11-25 to 2026-11-26.

## 1. What happened, in order

| #   | You asked                                                                                          | I answered                                                                                                                                                                                                                                                      | Was it right?                                                                                                                                                                                   |
| --- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "I want to run the RAG."                                                                           | Found no `.env` or API key. Tried retrieval alone: it stopped with "벡터 색인이 없다" (vector index not found).                                                                                                                                                 | Right to stop. The vectors existed but under a per-model filename. They were built before `EMBEDDING_MODEL` was set, so the default `vectors.npy` was never written. Fixed by copying the file. |
| 2   | Made `.env`, "use openai not anthropic", then several "try again".                                 | Generation was Claude-only. Each retry failed with 401. Causes: a key starting `key_` (not an OpenAI key), an old invalid `OPENAI_API_KEY` in Windows overriding `.env`, then the shortened dashboard version `sk-...fVoA` (10 characters). The 4th key worked. | Right. Checking the key's length and first characters without printing it found each cause quickly.                                                                                             |
| 3   | (key worked)                                                                                       | Added an OpenAI generator (`gpt-6-luna`, the only chat model on the account) and `--llm openai`. Dev run: 20/20 calls succeeded. But the model said "no evidence" on 3 questions it should have answered.                                                       | Worked. The over-declining was the real finding.                                                                                                                                                |
| 4   | "Look into it."                                                                                    | Not an OpenAI problem: Claude had declined the same questions. Three causes: DEV-002, a PDF-conversion bug lost the D-4 → D-2 cross-reference sentence; DEV-004/003, casual wording that retrieval misses; DEV-008, an over-strict model.                       | Right. Comparing with earlier Claude runs ruled out the model first.                                                                                                                            |
| 5   | "How will you rechunk?" / "I have the PDF."                                                        | Fix the Markdown by hand for that page, rechunk, re-link the eval evidence, rebuild the indexes. The PDF lets us check the fix and scan for other cases.                                                                                                        | Right.                                                                                                                                                                                          |
| 6   | "Write a Korean prompt for a coworker, cheap models for easy work, best model for important work." | Wrote a hand-off doc: Opus for judgment, Sonnet for implementation, Haiku for mechanical runs, three approval stops.                                                                                                                                            | First version depended on my uncommitted OpenAI code and an API key.                                                                                                                            |
| 7   | "Use Anthropic" → "We all use Claude Code, why a key?" → "Why test the RAG at all?"                | Explained that a Claude Code login doesn't give the Python app an API key. Then agreed: a chunking fix should be measured by retrieval (Hit@5, all evidence in top 5), which runs free. Removed every API key and answer run from the doc.                      | **Your push was right.** I had added answer-level testing out of habit, not because the task needed it.                                                                                         |
| 8   | Questions about the embedding model, a `.md` copy, this summary.                                   | `nlpai-lab/KURE-v1`, local, no key needed. Saved `코퍼스_청킹_수정_작업지시서.md`.                                                                                                                                                                              | Done.                                                                                                                                                                                           |

## 2. Insights

- **A metric can say "found" when the answer is impossible.** Hit@5 counted DEV-002 as a hit because 1 of 3 gold passages was retrieved. The passage the answer depends on wasn't in the index at all. For multi-passage questions, look at "all evidence in top 5".
- **"No evidence" can be correct behaviour.** The model declined because the prompt says not to use another visa's rules, and the bridge sentence was missing. Check what the model was given before blaming it.
- **Compare against an earlier run before blaming the new component.** Earlier Claude runs declined the same questions, which ruled out the model switch in one step.
- **Data bugs hide upstream.** The chunker worked as designed. The fault was in PDF conversion (limitation L5), two steps earlier.
- **Keys: check the shape, never the value.** `sk-ant-` is Anthropic, `sk-proj-` is OpenAI, a 10-character `sk-...abcd` is the dashboard's shortened display. Old Windows environment variables silently beat `.env`.
- **Match the test to the task.** A chunking fix is proven by retrieval metrics, which are free and run locally. Answer quality is a separate evaluation. Your question "why test the RAG?" cut the cost and removed the key requirement.
- **A hand-off must work on someone else's machine.** The first draft relied on my uncommitted code, local files and a key. Check what the reader will actually have.
- **Claude Code login ≠ API key.** Claude Code is the assistant. The RAG app calls the API itself and needs its own key.

## 3. Still open from this session

- The OpenAI generator (`src/answer/generator.py`, `experiments/run_experiment.py`) and its run results are uncommitted.
- `eval/eval-test.json` and `eval/README.md` had changes I didn't make. Check them before committing.
- Not yet tried: query rewrite for DEV-004/003, and loosening prompt rule 6 for DEV-008 (dev set only).

# Takeaways: RAGAS evaluation — debugging a 0.000 faithfulness score

Session: 2026-11-26.

## 1. What happened, in order

| #   | You asked                                                | I answered                                                                                                                                                                                                                                                                                                | Was it right?                                                                                                                                                        |
| --- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "Is the RAGAS built here now?"                           | Yes: `experiments/ragas_eval.py` exists and a baseline result file is saved. Showed the results table.                                                                                                                                                                                                    | Right.                                                                                                                                                               |
| 2   | "Investigate" (faithfulness = 0.000 across all configs). | Traced it to the response content. Every `answer` field was the same stub: `"문서에 따르면 해당 내용이 있습니다. [DOC-X]"`. No real claims → judge finds nothing to support → faithfulness 0. Root cause: the baseline was run with `--llm dummy` (the default), which is a no-cost stub for development. | Right. The faithfulness metric was not broken; the input was.                                                                                                        |
| 3   | "Sure" (run with a real LLM).                            | Checked `.env`: `ANTHROPIC_API_KEY` missing, `OPENAI_API_KEY` set. Tried the OpenAI key → 401 (invalid). Could not proceed.                                                                                                                                                                               | Right to stop.                                                                                                                                                       |
| 4   | "Use OpenAI."                                            | Added OpenAI judge support to `ragas_eval.py` (`--provider openai`, `--model` defaults to `OPENAI_MODEL`). Re-ran the experiment → succeeded (real answers). Re-ran RAGAS → 401 again.                                                                                                                    | Experiment succeeded because `OpenAILLM` reads `.env` via `dotenv_values`; the judge used `OpenAI()` with no key override and hit the stale Windows env var instead. |
| 5   | (auto, fixing the 401)                                   | Copied the same `dotenv_values` pattern into the judge. Next run → 400: `max_tokens` not supported. `gpt-6-luna` is a reasoning model that requires `max_completion_tokens`. Fixed.                                                                                                                       | Right.                                                                                                                                                               |
| 6   | (auto, re-ran)                                           | RAGAS completed. Real results: context_recall 0.565, faithfulness 0.899, context_precision 0.763 overall. Config A leads on recall; B leads on faithfulness and precision.                                                                                                                                | Done.                                                                                                                                                                |

## 2. Insights

- **A metric that scores 0.000 uniformly is almost certainly reading the wrong input, not measuring a real failure.** When every config and every question scores exactly 0, the judge saw nothing to work with. Check what was actually passed in before debugging the metric formula.
- **The default LLM matters more than it looks.** `--llm dummy` is a sensible default for fast iteration (no cost, no key). But running RAGAS on dummy output is meaningless. When producing results you plan to report, explicitly pass `--llm claude` or `--llm openai`.
- **Two parts of the same codebase can handle the same key differently.** `OpenAILLM` (generator) used `dotenv_values` to read `.env` directly, bypassing a stale Windows env var. The RAGAS judge used `OpenAI()` with no key override and was silently wrong. The fix was to match the working pattern exactly. When a key fails in one place and works in another, compare the two construction paths.
- **Reasoning models have a different API surface.** `gpt-6-luna` rejects `max_tokens` and requires `max_completion_tokens`. This is a known OpenAI split between chat and reasoning models; always check the model family before sending parameters.
- **Faithfulness measures the answer, not the retrieval.** context_recall and context_precision depend only on what was retrieved, so they scored correctly even with the stub. Faithfulness was the only metric that needed a real answer. When one metric is an outlier, check which part of the pipeline it depends on.

## 3. What was produced

| Change                                              | File                                                   |
| --------------------------------------------------- | ------------------------------------------------------ |
| `--provider openai/anthropic` flag + OpenAI judge   | `experiments/ragas_eval.py`                            |
| `dotenv_values` key override (matches `OpenAILLM`)  | `experiments/ragas_eval.py`                            |
| `max_completion_tokens` for reasoning models        | `experiments/ragas_eval.py`                            |
| First real RAGAS result (gpt-6-luna judge, dev set) | `results/ragas/2026-11-26_172732_dev_A-B-C.ragas.json` |

## 4. Checklist for next time

1. **Before blaming a metric, read 2–3 raw `answer` fields.** A uniform score usually means the input is wrong, not the judge.
2. **When running any evaluation that costs money, check `--llm` explicitly.** Don't rely on the default.
3. **When a key fails in one place and works in another, compare the two construction paths.** Look for one using `dotenv_values` and the other using `os.getenv` / the default constructor.
4. **Check whether the model is a reasoning model before sending parameters.** Reasoning models reject `max_tokens`; use `max_completion_tokens` instead.

---

# Takeaways: reviewing uncommitted work and removing date placeholders

Session: 2026-11-26.

## 1. What happened, in order

| #   | You asked                                                                                       | I answered                                                                                                                                                                                                                                                                                                                                                                                                  | Was it right?                                                                                 |
| --- | ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 1   | "What's the issue with this" (no file selected).                                                | Reviewed all uncommitted changes. Tests passed (58/58), and only `page` changed in `chunks.jsonl` (604 of 1,653 chunks, IDs and text unchanged). Flagged: test-set evidence (33 `chunk_id`s) drafted by Claude and not yet checked by a person; 6 dev evidence pages now differ from chunk pages; `check_index_manifest` is never called; OpenAI shares `LLM_EFFORT`; unrelated changes are mixed together. | Useful, but I had to guess what "this" meant. Naming the file saves a round trip.             |
| 2   | "problem.md is still a draft with date placeholders; criteria must be fixed before final runs." | Found the edition in the corpus (`version: 2026-11-16`), but no collection date anywhere. No core runs yet, so fixing now was still allowed. Asked you which date to use.                                                                                                                                                                                                                                   | You stopped the question. The date wasn't needed at all.                                      |
| 3   | "Remove the need of the date." / "Remove that too."                                             | Replaced the date placeholders with a pointer to the `version` field in `docs/corpus/`. Removed the draft status line and the collection-date and fixed-date rows in `eval/README.md`.                                                                                                                                                                                                                      | Right. The git commit, tag and SHA-256 already lock the criteria; a typed date added nothing. |

## 2. Insights

- **Don't ask for data the repo already holds.** The edition was in every corpus file. Pointing to it beats copying it into another placeholder that can drift.
- **A placeholder isn't automatically a requirement.** I treated "fill the date" as the task; the better move was asking whether the field was needed. A commit is the real proof that criteria were fixed before the final run.
- **"Fixed before final runs" is checkable.** No core run files existed and `problem.md` hadn't changed since its first commit, so the rule still held.
- **A clean diff check is cheap insurance.** Comparing old and new `chunks.jsonl` field by field showed the change was exactly what was intended.
- **AI-drafted answer keys need a human check before the final runs.** The test-set `chunk_id`s were picked by Claude. The README says so, but nothing enforces it.

## 3. Still open from this session

- A teammate must check the 33 test-set `chunk_id`s against the PDF and record `verified_by`.
- `problem.md` still points to `eval/dev.json`, `eval/test.json` and `docs/documents.csv`; the real files are `eval-dev.json` and `eval-test.json`, and `documents.csv` doesn't exist.
- The stale-index check (`check_index_manifest`) is still dead code.
- The working tree mixes the page fix, the test-set evidence, the OpenAI provider and run records. Split them into separate commits.

---

# Takeaways: running the core eval and diagnosing retrieval failures

Session: 2026-11-26 (branch `feat/section-expand-threadsafe-corpus-e2-f5`).

## 1. What happened, in order

| #   | You asked                                                                 | I answered or did                                                                                                                                                                                                                                                                                         | Was it right?                                                      |
| --- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| 1   | Run the core eval with configs A B C, 60 records, using Claude LLM.       | ANTHROPIC_API_KEY was missing. Switched to `--llm openai`.                                                                                                                                                                                                                                                | Right to stop and ask, not guess.                                  |
| 2   | "Why is Hit@5 so low?" (first run was ~37%)                               | Traced it to a stale index — chunk IDs in the index no longer matched the current `chunks.jsonl` after rechunking. `KeyError` on lookup was silently counted as a miss.                                                                                                                                   | Right. Rebuilt the index and scores improved.                      |
| 3   | "Why do eval runs take so long?"                                          | Sequential inner loop — one question at a time, each waiting on an LLM API call.                                                                                                                                                                                                                          | Right.                                                             |
| 4   | (Parallelized the eval runner)                                            | Replaced the sequential loop with `ThreadPoolExecutor`. Added thread safety: `threading.local()` for `last_rerank_ms` in `ManualRetriever`, double-checked locking for `CrossEncoderScorer`, `threading.Lock()` in `JsonlWriter`. Config C capped at 3 workers (CPU-bound cross-encoder); others at 10.   | Done. Run time dropped from ~360s to ~210s.                        |
| 5   | "Break down why answers were wrong."                                      | Categorised misses as WRONG_SECTION (sibling chunk retrieved) and TOPIC_CONFUSION (TEST-003, E-class boilerplate floods results).                                                                                                                                                                         | Right.                                                             |
| 6   | "Why do I keep getting a retrieval failure on TEST-003?"                  | Diagnosed boilerplate flooding: 6 E-class chunks all contain the same cross-reference footnote mentioning D-10 and D-2. Their vectors collectively occupy all 5 top-k slots, pushing the actual D-10 gold chunks out. BM25 makes it no better because the same tokens appear verbatim in the boilerplate. | Right. This was a structural corpus problem, not a config problem. |
| 7   | "If I fix just the D-10 boilerplate, isn't that just gaming the numbers?" | Yes. The same failure pattern will appear on any section that is cross-referenced repeatedly. The right fix must work generally.                                                                                                                                                                          | Right. User pushed back on a targeted fix correctly.               |
| 8   | "Is there a query rewrite function?"                                      | Yes — `src/optimize/rewrite.py`, two modes: dictionary substitution (free) and LLM rewrite (Claude only). Noted it wouldn't fix TEST-003 because the query already uses the correct formal terms.                                                                                                         | Right.                                                             |
| 9   | "Without BM25, why are vector-only results still low?"                    | The 6 near-identical E-class vectors collectively beat the unique D-10 vectors even in pure embedding space. 6 votes at ~97% similarity vs 4 votes at ~94%.                                                                                                                                               | Right.                                                             |
| 10  | "Summarise all the problems."                                             | Produced the full diagnostic: 6 root causes across 10 failing test items, covering boilerplate flooding, chunk boundary splits, BM25 DOC-WIDE noise, false-premise cross-doc retrieval, colloquial-to-formal mismatch, and eval gold annotation gaps.                                                     | Done.                                                              |

## 2. Insights

- **A stale index causes silent wrong answers, not loud errors.** When chunk IDs in the index no longer exist in `chunks.jsonl`, the lookup `KeyError` was swallowed and counted as a miss. Nothing failed loudly. Always check that the index was built from the same `chunks.jsonl` by comparing chunk counts.

- **Fixing a symptom in one test case is not the same as fixing the underlying problem.** Stripping the D-10 boilerplate from E-class chunks would have improved TEST-003 specifically, but the same failure would reappear whenever any other section is heavily cross-referenced. The user was right to reject it. Think "what general class of input causes this?" before proposing a fix.

- **Repeated identical text in multiple chunks is a vector search poison.** 6 near-identical chunks embed to nearly the same vector. At query time, 6 of them compete for top-k slots and win by sheer repetition, crowding out unique relevant chunks. BM25 does not help because the token overlap is also identical. The fix is at the corpus level (deduplicate or strip the repeated text at ingest) or at the retrieval level (MMR diversification, or penalise near-duplicate candidates).

- **Config B (BM25 + vector hybrid) can score worse than Config A (vector only).** Adding BM25 introduced `DOC-WIDE` summary chunks into results (broad coverage, low specificity). These occupied top-k slots that in Config A would have been taken by more specific chunks. Hybrid is not always better.

- **Thread safety needs to be explicit when you parallelise.** Making `run_agent` concurrent exposed three latent races: `last_rerank_ms` written directly on `self` (thread-shared), `CrossEncoderScorer._model` lazy-loaded without a lock (double-load on first call), and `JsonlWriter._f.write()` called from multiple threads without a lock (interleaved bytes). All three had to be fixed before parallelisation was safe.

- **CPU-bound parallelism needs fewer workers than I/O-bound parallelism.** Config C's cross-encoder is CPU-intensive. Running it with 10 workers caused CPU contention and pushed median latency from ~21s to ~67s. Dropping to 3 workers fixed it. Know whether your bottleneck is I/O waiting or CPU computing before picking the worker count.

- **Eval gold annotations may be too narrow.** For TEST-011, TEST-016, TEST-017, the system retrieved sibling chunks (adjacent in the section) and produced a **correct answer**, but was still marked Hit@5=0 because the specific gold `chunk_id` wasn't retrieved. The annotation only marks one chunk per evidence item. `chunk_ids_all` exists but isn't used in the Hit@5 check. Consider widening the gold set before treating these as true failures.

- **Colloquial Korean does not embed near its formal equivalent.** TEST-012 asks "본국에 1년 넘게 다녀오면 뭘 해야 돼?" (casual), which should map to 재입국허가 (re-entry permit). The dictionary rewriter only covers a few terms. Without LLM-based query rewrite, the casual embedding misses the formal section.

## 3. Final Hit@5 results (after index rebuild)

| Config                 | Hit@5      | Notes                                                     |
| ---------------------- | ---------- | --------------------------------------------------------- |
| A (vector only)        | 40% (8/20) | Sibling chunk misses + TEST-003 boilerplate               |
| B (hybrid BM25+vector) | 30% (6/20) | DOC-WIDE noise made it worse than A                       |
| C (hybrid + reranker)  | 40% (8/20) | Reranker helps where candidates exist; can't fix TEST-003 |

## 4. Still open

- TEST-003 boilerplate flooding needs a generalised fix (MMR, candidate deduplication, or corpus-level cleanup).
- TEST-012 colloquial mismatch needs LLM-based query rewrite activated.
- Eval gold `chunk_ids_all` should be used in the Hit@5 check for questions where sibling chunks contain the same answer.
- Config B underperforming A is unexpected; investigate BM25 weight tuning or DOC-WIDE chunk filtering.

## 5. Checklist for next time

1. **After any rechunk, verify index chunk count matches `chunks.jsonl` row count** before running eval.
2. **Before proposing a targeted fix, ask: does this fix the class of problem, or just this test case?**
3. **When parallelising, audit every shared mutable state** for thread safety before the first concurrent run.
4. **Know your bottleneck (I/O vs CPU) before choosing worker count.** Test with a small batch first.
5. **Check `chunk_ids_all` in the eval**, not just the primary `chunk_id`, before concluding retrieval failed.

---

# Takeaways: index versioning, test run on idx-v5, and freeze readiness

Session: 2026-11-26.

## 1. What happened, in order

| #   | You asked                                         | I answered                                                                                                                                                                                                                                                                                                                          | Was it right?                         |
| --- | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| 1   | "idx-v4 어떤 매핑 사용중?"                        | Explained that chunk_id is a SHA-1 hash of `(doc_id, location, occurrence, text[:200])`. "위치 기반 매핑" (idx-v4) was not a new algorithm — it was a manual remap of eval answer keys using `doc_id + location` after the PUA glyph cleanup changed 208 body chunk IDs. The automated tool for this is `src/ingest/chunk_diff.py`. | Right.                                |
| 2   | "위치 기반 매핑 v4 말고 또 뭐 있어?"              | Listed the four matching strategies in `chunk_diff.py` (by order): exact ID match → full text match → head-200 match → line-overlap ≥ 0.4. ID change reasons: `path`, `head200`, `seq_shift`, `doc_split`.                                                                                                                          | Right.                                |
| 3   | "v5 있어?"                                        | Confirmed: idx-v5 is the current main index (1,815 chunks, 39 docs, KURE-v1). `data/index/meta.json` had a stale `idx-v1` tag because whoever rebuilt BM25 last passed `--version idx-v1`.                                                                                                                                          | Right.                                |
| 4   | "v5로 바꿔서 test run 다시해"                     | Rebuilt BM25 with `--version idx-v5`. Dev check passed (A: 8/8, B: 7/8, C: 6/8). Full test run on `eval-test-quoted.json`: A 15/17, B 13/17, C 15/17. Matches the previous idx-v5 record.                                                                                                                                           | Right.                                |
| 5   | "freeze it and I want to test on other questions" | Checked freeze pre-conditions: chunk_ids all filled in test-quoted ✅, but `verified_by` / `reviewed_by` are empty for all 30 questions in both dev and test files. Asked how to proceed.                                                                                                                                           | Right to surface this before tagging. |
| 6   | "summarize and add to takeaway.md"                | This section.                                                                                                                                                                                                                                                                                                                       |                                       |

## 2. Insights

- **The version tag in `meta.json` is cosmetic; `config.py` computes a real version from a hash of the config and `chunks.jsonl`.** The tag matters only for humans reading logs. Stale tags cause confusion but not bugs — the hash mismatch check in `check_index_manifest` would catch a real drift, if it were called.
- **`check_index_manifest` looks for `manifest.json`, but `build_index.py` writes `meta.json`.** The integrity check is never triggered. Either rename the file or update the checker before the final runs.
- **A "freeze" that skips `verified_by` / `reviewed_by` is a draft tag, not a true freeze.** The README's own procedure requires both fields before tagging. Freezing with empty fields means the eval set's answers were never independently checked, which undermines the credibility of the Hit@5 numbers.
- **idx-v4 → idx-v5 reduced the chunk count from 1,879 to 1,815.** Check the conversion notes for what was dropped; a chunk that disappears is an eval answer key that silently becomes unwinnable.
- **Running the same experiment twice on the same index produces the same numbers.** A/C both gave 15/17 again. Stability is a good sign, but only if the eval set itself is correct — which is what `verified_by` is for.

## 3. Still open from this session

- Decide how to handle the freeze: fill `verified_by` / `reviewed_by` properly, or tag as `eval-v0.1-draft` and treat the numbers as preliminary.
- `check_index_manifest` / `manifest.json` naming mismatch is still unresolved dead code.
- TEST-010 `type` warning (loader doesn't recognise the value in the file) fires on every run. A one-line fix.
- "Other questions" the user wants to test: create a separate eval file (e.g. `eval-extra.json`) so the frozen test set stays untouched.

---

# Takeaways: running eval end-to-end and reading the results

Session: 2026-11-26 (branch `feat/section-expand-threadsafe-corpus-e2-f5`).

## 1. What happened, in order

| #   | You asked                                         | I answered or did                                                                                                 | Was it right?                                                |
| --- | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| 1   | "run eval"                                        | Ran dev eval (10문항, dummy LLM) on configs A/B/C. A: 8/8, B: 7/8, C: 6/8 Hit@5.                                  | Right.                                                       |
| 2   | "run test eval"                                   | Ran core eval (20문항, gpt-6-luna) on A/B/C. A/C: 8/16, B: 6/16. Two loader warnings shown.                       | Right.                                                       |
| 3   | "테스트 과정과 결과를 GitHub에 올릴 수 있게 써줘" | Wrote a Korean GitHub write-up: procedure, results table, per-question miss breakdown, known issues, next steps.  | Done.                                                        |
| 4   | "md file로 줘"                                    | Saved to `results/runs/2026-11-26_test-report.md`.                                                                | Done.                                                        |
| 5   | "re run the test"                                 | Re-ran core eval. A/B unchanged; C `answered` went 14 → 15.                                                       | Right. Small shift = LLM non-determinism, not a code change. |
| 6   | "its 20 questions why does it only show 16"       | Explained: 3 `no_answer` questions have no gold chunk, TEST-013 has `chunk_id: null`. 20 − 3 − 1 = 16 measurable. | Right.                                                       |

## 2. Insights

- **The Hit@5 denominator is not always n.** `no_answer` items and items with `chunk_id: null` are silently excluded, making the score look better. Always print the denominator: `8/16 (20문항 중 측정 가능 16)`.
- **LLM non-determinism is real but small.** One re-run shifted Config C's `answered` by 1 out of 20. Never treat a single run as final for items near a threshold.
- **Two eval data quality issues survived into the final run.** TEST-010's `type` field (`"false_premise"`) was listed as fixed in the README change log but never updated in the JSON — these must move together in the same commit. TEST-013's `chunk_id` was left null, costing one measurable slot every run.
- **Config B consistently underperforms A and C.** B was 6/16 in both runs; A and C were 8/16. The RRF fusion is not helping retrieval for this question set.
- **Config C's slowness is structural.** The reranker loads ~390 weights per run and processes questions sequentially, giving a ~21 s median. If C is chosen for production, the model should stay resident.

## 3. Checklist for next time

1. **Change the JSON and the README change log in the same commit.** A log entry that says "done" when the file isn't updated is misleading.
2. **Add a pre-flight check before the run loop:** any measurable item with `chunk_id: null` should fail loudly, not silently drop from the denominator.
3. **Report the denominator alongside Hit@5** in every summary table.
4. **Run twice before reporting.** One extra run is cheap and shows whether a borderline number is stable.

---

# Takeaways: checking for outdated files, fixing housekeeping issues, and understanding evaluation options

Session: 2026-11-26 (branch `feat/section-expand-threadsafe-corpus-e2-f5`).

## 1. What happened, in order

| #   | You asked                                                                                  | I answered or did                                                                                                                                                                                                                                                        | Was it right?                                                                                                                                                                                                                       |
| --- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "Is there a reranker?"                                                                     | Yes — `src/rerank.py`, `configs/C.toml`, `tests/test_rerank.py`.                                                                                                                                                                                                         | Right.                                                                                                                                                                                                                              |
| 2   | "Check for outdated or conflicting files."                                                 | Ran `git status` and `git diff HEAD` across all modified files. Found: `tests/test_chunk.py` appeared to have a merge conflict, two corpus files untracked, results files untracked, and a large in-flight feature (section expansion + thread safety) across ~50 files. | Mostly right. The apparent conflict in `test_chunk.py` was not real — the diff showed the old HEAD content being deleted as part of a valid rewrite. I should have read the working-copy file before concluding a conflict existed. |
| 3   | "What needs fixing?"                                                                       | Five items: untracked corpus files (DOC-E2, DOC-F5), results files not in `.gitignore`, possible encoding issue in `chunks.jsonl`, `expand_sections=true` in `base.toml` inherited by C.toml, and `last_rerank_ms` thread-local property.                                | After deeper investigation: encoding was already correct everywhere, the `expand_sections` inheritance was intentional, and `last_rerank_ms` was correct. Only two real fixes were needed.                                          |
| 4   | "Solve these."                                                                             | Added `results/runs/` to `.gitignore`. Added DOC-E2 and DOC-F5 to git. Rechunked all corpus files; both new docs confirmed in output (1,815 chunks, stable count).                                                                                                       | Done.                                                                                                                                                                                                                               |
| 5   | "Give me a commit title and GitHub description."                                           | Gave both — title covering section expansion, thread safety, corpus completion; description broken into four sections.                                                                                                                                                   | Done.                                                                                                                                                                                                                               |
| 6   | "Branch name."                                                                             | `feat/section-expand-threadsafe-corpus-e2-f5`                                                                                                                                                                                                                            | Done.                                                                                                                                                                                                                               |
| 7   | "Do a RAGAS test."                                                                         | RAGAS not installed, no RAGAS files in the project. Explained the two options.                                                                                                                                                                                           | Right to surface this before attempting to run.                                                                                                                                                                                     |
| 8   | "Tell me how the options impact the project and time."                                     | Option 1 (existing runner): free or ~$0.30, ~5 min, no new code. Option 2 (RAGAS adapter): 2–3 hrs dev work, adds dependency, noisy on Korean.                                                                                                                           | Right.                                                                                                                                                                                                                              |
| 9   | "Would option 3 be more accurate?" / "What's option 3?"                                    | There was no option 3. Clarified.                                                                                                                                                                                                                                        | Right to say so rather than invent one.                                                                                                                                                                                             |
| 10  | "What would give me the most accurate test?"                                               | Option 1 is more accurate: ground truth is hand-crafted in Korean, RAGAS judges in English and is noisier.                                                                                                                                                               | Right.                                                                                                                                                                                                                              |
| 11  | "Does option 1 measure faithfulness, answer_relevancy, context_recall, context_precision?" | No. Mapped what it does measure to RAGAS equivalents. Only context_precision has no equivalent. Offered to add it.                                                                                                                                                       | Right.                                                                                                                                                                                                                              |

## 2. Insights

- **Read the actual file before concluding a conflict exists.** `git diff` showed `<<<<<<< HEAD` being removed, which looked like an unresolved conflict. Reading the working copy showed a clean file. The diff was showing the old content being deleted, not a live marker.

- **Over-reporting issues is as costly as under-reporting.** The initial list had five problems; two were real. The other three took investigation to rule out. When a check is fast (read the file, grep for utf-8), do it before adding an item to the fix list.

- **Know what your eval actually measures before choosing it.** Option 1 misses context_precision. RAGAS covers it but loses accuracy on Korean. The right question is "which metric gap matters most for this project?" — not "which framework is more famous?"

- **The existing eval runner is already the most accurate tool for this project.** It uses hand-crafted Korean ground truth, runs free on retrieval, and is already integrated. RAGAS would add a weaker LLM judge in a language it wasn't optimised for. Use the tool built for the domain.

- **A blank question ("option 3") should be named, not answered.** When there is no third option, say so. Inventing one to avoid the awkward pause would have wasted time and confused the direction.

## 3. Checklist for next time

1. **Before calling something a conflict, read the working-copy file.** `git diff` shows what changed, not what the file contains now.
2. **Before adding an item to a fix list, do a one-step check** (read the file, grep for the pattern). Rule out the false positives first.
3. **When comparing evaluation options, start from "what does this project's ground truth look like?"** A bespoke Korean eval set beats a generic English-tuned framework on Korean content.
4. **If a metric is missing and it matters, add it to the existing runner** rather than switching frameworks.

---

# Takeaways: understanding the eval file structure and the `quote` field

Session: 2026-11-26.

## What happened, in order

| #   | You asked                                                         | I answered                                                                                                                                                                                                                                                                                                                                                                        | Was it right? |
| --- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| 1   | "There is a quote on the dev but not on the test questions, why?" | Read both eval files. Dev evidence entries have a `quote` field (verbatim text from the PDF); test entries only have `source`, `page`, `chunk_id`, `chunk_ids_all`. Explained this is intentional — `quote` is omitted from the test set to prevent leakage.                                                                                                                      | Right.        |
| 2   | "What does the quote do?"                                         | Traced it to `src/link_evidence.py`. The `quote` field is the anchor text the script uses to find which chunk an evidence entry belongs to. It is split on `/` (since quotes often concatenate multiple lines), then searched as a substring in chunk text. More reliable than matching by `section` (Korean formatting inconsistencies) or `page` (a page can have many chunks). | Right.        |
| 3   | "What is leakage?"                                                | Explained: if the test eval file contained the answer text (`quote`), someone tuning the system could inadvertently optimise toward matching those exact phrases. The system would score well on the test not because it's genuinely good, but because the answer was visible in the eval file. Omitting `quote` keeps the test a true blind evaluation.                          | Right.        |

## Insights

- **The `quote` field is a linking tool, not just annotation.** It has a functional role: `link_evidence.py` uses it to assign `chunk_id`s. Without it, the fallback is page-number matching, which is less precise (one page can contain many chunks).
- **Dev and test eval files are intentionally asymmetric.** Dev has more metadata (section, quote) to aid development and debugging. Test is kept minimal to protect evaluation integrity.
- **Leakage is subtle.** It doesn't require deliberate cheating. Having the answer text in the same file as the questions is enough to bias tuning decisions, even unintentionally.
- **Two modes in `link_evidence.py` match the two file shapes:** `--mode quote` (default, for dev) uses the quote text; `--mode page` (for test) assigns a chunk only when exactly one chunk sits on the cited page.
