# Fine-tuning Laya on Miami news (#47)

Zero-shot Laya drops most real road stories at the news pipeline's 0.2 cut (#46, PR #54). This folder fine-tunes the
`multilingual` checkpoint on ~1,000 Miami news items labelled by a teacher model, so the first pass keeps road problems
and still drops the rest.

**The data never goes in this repo** (it's news text and the repo is public): everything below reads and writes
`$LAYA_DATA_DIR` (default `~/mapay-laya-data`). Only the scripts, the rubric and summary numbers are committed.

| Step | Command | Output (in `$LAYA_DATA_DIR`) |
|---|---|---|
| 1. Collect | `python collect.py` (backend venv: it reuses the pipeline's feeds) | `items.jsonl` (all), `to_label.jsonl` (balanced 1,000) |
| 2. Label | the teacher follows `label_prompt.md` → `labels_compact.txt`, then `python expand_labels.py` | `labels.jsonl` |
| 3. Build | `python build_dataset.py` (`--sample 50` prints items to spot-check) | `train.jsonl`, `test.jsonl` |
| 4. Train | `python train_cpu.py` (CPU, ~75 min on 16 cores) or `mapay_finetune.ipynb` (Kaggle T4 ×2, minutes) | `laya-mapay/` |
| 5. Evaluate | `python evaluate.py` | `eval.json` |
| 6. Serve | `LAYA_CHECKPOINT=$LAYA_DATA_DIR/laya-mapay python ../serve.py` | |

Steps 2–6 run in `services/laya/.venv` (see `../README.md`).

## What each step does

- **Collect:** Google News RSS search (last 90 days) with road-problem queries (flooding, crashes, closures,
  construction, police, traffic on Miami roads) plus general Miami news for negatives, and the five RSS feeds the
  pipeline reads. The GDELT DOC API is used when it answers (it rate-limits hard and often times out). Stories are
  deduped across outlets by URL and normalised title. `to_label.jsonl` takes every RSS item, 600 from the road queries
  and the rest general news.
- **Label:** the teacher (Claude in the Claude Code session, per the issue) writes a compact line for every item with
  any road relevance, `<id> <P(road problem)> <category[:weights]> <severity[:weights]>`. Every other item is a clear
  negative (`0.02 other 0`). `expand_labels.py` turns that into full probability distributions: a single category
  gets 0.9, a single severity level 0.7 with 0.15 on each neighbour.
- **Build:** the Laya notebook's row format (`state`, `questions`, `gold` as JSON strings), with `state` exactly what
  the pipeline sends (`"<title>\n\n<summary>"`) and `road_problem` word for word the pipeline's question
  (`questions.py`). The split is 80/20 **by story**, so the same story never lands in both halves. The training half
  down-samples *clear* negatives to 40 % road problems; borderline items and the test half keep their natural mix.
- **Train:** `train_cpu.py` is Laya's notebook training loop (RLCD: policy gradient on a proper scoring rule plus
  soft cross-entropy, same learning rates, schedule and temperature calibration on a held-out slice) in one CPU
  process.
- **Evaluate:** zero-shot vs fine-tuned on the held-out 20 %: accuracy per question, and the share of real road
  problems (teacher P ≥ 0.5) that pass the 0.2 cut, plus the share of other stories that pass it.

## Results (Sept 27, 2026)

1,000 labelled items (164 road problems); train 338 after rebalancing (913 sequences over three questions), test 186
(29 road problems), 4 epochs on CPU (74 min, final loss 0.63; calibration temperatures choice 1.21, score 1.19,
noul 1.04).

| Held-out 20 % | Zero-shot | Fine-tuned |
|---|---|---|
| road_problem accuracy | 80.1 % | **89.8 %** |
| category accuracy | 44.1 % | **68.3 %** |
| severity accuracy (within one level) | 16.1 % (95.2 %) | **75.3 %** (96.2 %) |
| road stories passing the 0.2 cut | 58.6 % (17/29) | **86.2 %** (25/29) |
| other stories passing the 0.2 cut | 20.4 % | 31.2 % |

Fine-tuned model, by cut: 0.1 keeps 29/29 road stories and 92/157 others; 0.2 keeps 25/29 and 49/157; 0.3 keeps
23/29 and 23/157. "Flooding reported on Brickell Bay Drive after king tide" went from 0.028 zero-shot to 0.659.

**Recommendation:** when `LAYA_URL` is turned on with this checkpoint, lower `RELEVANCE_MIN` in
`backend/app/agents/news_triage.py` from 0.2 to 0.1. On this test set that drops no road story and still skips ~40 % of
the others before Gemini. The test set is small (29 road stories), so re-check on fresh news before relying on it.

## Serving it

`../serve.py` attaches `LAYA_CHECKPOINT` (a folder, or a private Hugging Face repo id with `HF_TOKEN` set) as
`multilingual`, which is the name the backend asks for. Only after the evaluation shows road stories passing the cut
should `LAYA_URL` / `LAYA_API_KEY` be set for the backend (see `../README.md`).
