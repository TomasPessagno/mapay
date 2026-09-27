"""Expand the teacher's compact labels into labels.jsonl (#47).

The teacher writes one line per item that has any road relevance:

    <id> <P(road problem)> <category or cat:w,cat:w> <severity or level:w,level:w>

and every item not listed is a clear negative: 0.02, other, 0. A single category gets 0.9 (the
remaining 0.1 spread over the other five); a single severity level gets 0.7 with 0.15 on each
neighbour. The output is the probability format label_prompt.md describes.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR  # noqa: E402
from questions import CATEGORIES  # noqa: E402

NEGATIVE = "0.02 other 0"


def parse_weights(text: str) -> dict[str, float]:
    return {k: float(v) for k, v in (part.split(":") for part in text.split(","))} if ":" in text else {text: None}


def category(text: str) -> dict[str, float]:
    weights = parse_weights(text)
    if list(weights.values()) == [None]:
        main = next(iter(weights))
        return {k: 0.9 if k == main else 0.1 / (len(CATEGORIES) - 1) for k in CATEGORIES}
    total = sum(weights.values())
    return {k: weights.get(k, 0.0) / total for k in CATEGORIES}


def severity(text: str) -> list[float]:
    weights = parse_weights(text)
    probs = [0.0] * 5
    if list(weights.values()) == [None]:
        level = int(next(iter(weights)))
        for offset, share in ((0, 0.7), (-1, 0.15), (1, 0.15)):
            probs[min(4, max(0, level + offset))] += share
    else:
        for level, w in weights.items():
            probs[int(level)] += w
    total = sum(probs)
    return [p / total for p in probs]


def main() -> None:
    compact = {}
    for line in (DATA_DIR / "labels_compact.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            item_id, rest = line.split(maxsplit=1)
            compact[item_id] = rest
    items = [json.loads(line) for line in (DATA_DIR / "to_label.jsonl").read_text().splitlines() if line.strip()]
    out = []
    for item in items:
        p, cat, sev = compact.get(item["id"], NEGATIVE).split()
        out.append({"id": item["id"], "road_problem": float(p), "category": category(cat), "severity": severity(sev)})
    (DATA_DIR / "labels.jsonl").write_text("".join(json.dumps(label) + "\n" for label in out))
    unknown = set(compact) - {i["id"] for i in items}
    positives = sum(label["road_problem"] >= 0.5 for label in out)
    print(f"{len(out)} labels ({len(compact)} written by the teacher, {len(out) - len(compact) + len(unknown)} "
          f"default negatives); {positives} road problems ({positives / len(out):.0%}); unknown ids: {sorted(unknown)}")


if __name__ == "__main__":
    main()
