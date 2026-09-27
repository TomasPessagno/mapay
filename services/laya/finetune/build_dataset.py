"""Join items + teacher labels into the Laya notebook's format and split 80/20 by story (#47).

    python services/laya/finetune/build_dataset.py              # writes train.jsonl / test.jsonl
    python services/laya/finetune/build_dataset.py --sample 50  # print 50 labelled items to spot-check

Rows are {id, workflow, state, questions, gold}; state, questions and gold are JSON strings, and
gold[q]["probabilities"] is {"true": p, "false": 1-p} for noul, per option for choice and {"0".."4"}
for the 5-level score, as Laya's fine-tuning notebook reads them.
"""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR, title_key  # noqa: E402
from questions import CATEGORIES, QUESTIONS, state_for  # noqa: E402


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def normalise(values: list[float]) -> list[float]:
    values = [max(0.0, float(v)) for v in values]
    total = sum(values)
    return [v / total for v in values] if total > 0 else [1 / len(values)] * len(values)


def gold_for(label: dict) -> dict:
    p = min(1.0, max(0.0, float(label["road_problem"])))
    category = normalise([label["category"].get(k, 0.0) for k in CATEGORIES])
    severity = normalise(label["severity"][:5] + [0.0] * (5 - len(label["severity"][:5])))
    return {
        "road_problem": {"label": "true" if p >= 0.5 else "false", "probabilities": {"true": p, "false": 1 - p}},
        "category": {"label": CATEGORIES[category.index(max(category))],
                     "probabilities": dict(zip(CATEGORIES, category, strict=True))},
        "severity": {"label": str(severity.index(max(severity))),
                     "probabilities": {str(i): v for i, v in enumerate(severity)}},
    }


def in_test(item: dict, share: float) -> bool:
    """Deterministic by story (normalised title), so a story never lands in both halves."""
    digest = hashlib.sha1(title_key(item["title"]).encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF < share


def rebalance(rows: list[dict], share: float) -> list[dict]:
    def p(row):
        return json.loads(row["gold"])["road_problem"]["probabilities"]["true"]
    positives = [r for r in rows if p(r) >= 0.5]
    clear = [r for r in rows if p(r) <= 0.05]
    borderline = [r for r in rows if 0.05 < p(r) < 0.5]
    keep = max(0, round(len(positives) / share) - len(positives) - len(borderline)) if share else len(clear)
    kept = random.Random(47).sample(clear, min(len(clear), keep))
    return sorted(positives + borderline + kept, key=lambda r: r["id"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-share", type=float, default=0.2)
    parser.add_argument("--sample", type=int, default=0, help="print N labelled items for a spot check")
    parser.add_argument("--train-positive-share", type=float, default=0.4,
                        help="down-sample clear negatives (P <= 0.05) in the training half to reach this share of "
                             "road problems; borderline cases and the test half are never dropped")
    args = parser.parse_args()
    items = {i["id"]: i for i in load(DATA_DIR / "items.jsonl")}
    labels = [lab for lab in load(DATA_DIR / "labels.jsonl") if lab["id"] in items]
    if args.sample:
        for label in random.Random(7).sample(labels, min(args.sample, len(labels))):
            item = items[label["id"]]
            print(f"{label['road_problem']:.2f}  {max(label['category'], key=label['category'].get):12}  {item['title']}")
        return
    splits = {"train": [], "test": []}
    for label in labels:
        item = items[label["id"]]
        row = {"id": item["id"], "workflow": "mapay_news", "state": json.dumps(state_for(item)),
               "questions": json.dumps(QUESTIONS), "gold": json.dumps(gold_for(label))}
        splits["test" if in_test(item, args.test_share) else "train"].append(row)
    splits["train"] = rebalance(splits["train"], args.train_positive_share)
    for name, rows in splits.items():
        (DATA_DIR / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        positives = sum(json.loads(r["gold"])["road_problem"]["probabilities"]["true"] >= 0.5 for r in rows)
        print(f"{name}: {len(rows)} rows, {positives} road problems ({positives / max(1, len(rows)):.0%})")


if __name__ == "__main__":
    main()
