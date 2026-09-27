# Labelling rubric for the Laya fine-tune (#47)

The teacher (Claude, in the Claude Code session) labels each news item with **probabilities, not hard labels**, for
the three questions in `questions.py`. Work in batches of ~50; write one JSON object per line to
`$LAYA_DATA_DIR/labels.jsonl`:

```json
{"id": "n00042", "road_problem": 0.92, "category": {"flood": 0.85, "construction": 0, "closure": 0.1, "incident": 0, "event": 0, "other": 0.05}, "severity": [0, 0.1, 0.6, 0.3, 0]}
```

## road_problem (yes/no)

> Is this story about a current or upcoming problem on streets or roads in Miami-Dade: flooding, a crash, a closure,
> construction, police activity or a large event?

- **Yes (≥ 0.85):** a specific, current or upcoming thing a Miami-Dade driver or walker would hit: street flooding, a
  crash, a road or lane closure, roadwork, police activity blocking or near roads, a big event with traffic impact,
  a bridge opening problem, traffic signal outages.
- **Probably (0.5–0.8):** likely road impact but not stated (a large fire, a shooting on a named street, a storm
  forecast for tonight with flooding expected).
- **Probably not (0.1–0.4):** Miami but only indirect (a court case about an old crash, a transit budget vote, a
  business opening, traffic statistics or opinion pieces).
- **No (≤ 0.05):** sports results, entertainment, politics, real estate, national news, or anything outside
  Miami-Dade (Broward, Palm Beach and the Keys are outside).
- The title is often all there is (GDELT items have no summary): judge from it, don't invent details.

## category (one of six)

`flood`, `construction`, `closure`, `incident` (crash, police activity), `event`, `other` (not a street problem).
Spread probability when a story fits two (a crash that closed a road: incident 0.6, closure 0.4). Non-road stories put
≥ 0.9 on `other`.

## severity (0–4)

0 no impact · 1 minor, one street · 2 a few streets or lanes · 3 a major road or area (I-95, 836, 826, the Turnpike,
US-1, a causeway, a whole neighbourhood) · 4 citywide or dangerous (hurricane, major flooding, a highway fully closed
for hours). Non-road stories are ~[0.95, 0.05, 0, 0, 0].

## Checks

- Probabilities in each question sum to 1 (`road_problem` is P(yes)).
- Spot-check 50 items by hand before training (`build_dataset.py --sample 50` prints them).
