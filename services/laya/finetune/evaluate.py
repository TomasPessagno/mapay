"""Zero-shot vs fine-tuned Laya on the held-out 20 % (#47).

    python services/laya/finetune/evaluate.py [FINE_TUNED_DIR]

Prints accuracy per question (road_problem: P(yes) >= 0.5 vs the teacher; category: top choice;
severity: top level and within one level) and the number that matters for the news pipeline: the
share of real road problems that pass its 0.2 cut (backend/app/agents/news_triage.RELEVANCE_MIN),
and the share of other stories it lets through.
"""
import json
import os
import sys
from pathlib import Path

import laya
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR  # noqa: E402

CUT = 0.2


def evaluate(agent, rows) -> dict:
    counts = {"road": 0, "road_ok": 0, "cat_ok": 0, "sev_ok": 0, "sev_near": 0, "pos": 0, "pos_pass": 0,
              "neg": 0, "neg_pass": 0}
    for row in rows:
        state, questions, gold = json.loads(row["state"]), json.loads(row["questions"]), json.loads(row["gold"])
        answers = agent.predict(state, questions)["answers"]
        p = float(answers["road_problem"]["noul"])
        is_road = gold["road_problem"]["probabilities"]["true"] >= 0.5
        counts["road"] += 1
        counts["road_ok"] += (p >= 0.5) == is_road
        counts["cat_ok"] += answers["category"]["choice"] == gold["category"]["label"]
        level, gold_level = int(answers["severity"]["score"]), int(gold["severity"]["label"])
        counts["sev_ok"] += level == gold_level
        counts["sev_near"] += abs(level - gold_level) <= 1
        key = "pos" if is_road else "neg"
        counts[key] += 1
        counts[f"{key}_pass"] += p >= CUT
    n = max(1, counts["road"])
    return {"n": counts["road"], "road_problem_acc": counts["road_ok"] / n, "category_acc": counts["cat_ok"] / n,
            "severity_acc": counts["sev_ok"] / n, "severity_within_1": counts["sev_near"] / n,
            "road_pass_at_0.2": counts["pos_pass"] / max(1, counts["pos"]),
            "other_pass_at_0.2": counts["neg_pass"] / max(1, counts["neg"]), "road_stories": counts["pos"]}


def main() -> None:
    # PyTorch's default thread count oversubscribes this CPU badly (minutes instead of 0.3 s per story).
    torch.set_num_threads(int(os.environ.get("THREADS", 8)))
    rows = [json.loads(line) for line in (DATA_DIR / "test.jsonl").read_text().splitlines() if line.strip()]
    results = {"zero_shot": evaluate(laya.load("convaiinnovations/laya", subfolder="multilingual"), rows)}
    if len(sys.argv) > 1 or (DATA_DIR / "laya-mapay").exists():
        results["fine_tuned"] = evaluate(laya.load(sys.argv[1] if len(sys.argv) > 1 else str(DATA_DIR / "laya-mapay")),
                                         rows)
    for name, r in results.items():
        print(f"{name:10}  n={r['n']}  road_problem {r['road_problem_acc']:.1%}  category {r['category_acc']:.1%}  "
              f"severity {r['severity_acc']:.1%} (±1: {r['severity_within_1']:.1%})  "
              f"road stories passing 0.2: {r['road_pass_at_0.2']:.1%} of {r['road_stories']}  "
              f"other stories passing: {r['other_pass_at_0.2']:.1%}")
    (DATA_DIR / "eval.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
