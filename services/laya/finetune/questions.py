"""The fine-tune's questions. `road_problem` must stay word-for-word what the news pipeline asks
(backend/app/agents/news_triage.py: QUESTION); `category` and `severity` are extra training signal."""
ROAD_PROBLEM = ("Is this story about a current or upcoming problem on streets or roads in Miami-Dade: "
                "flooding, a crash, a closure, construction, police activity or a large event?")

QUESTIONS = {
    "road_problem": {"type": "noul", "instructions": ROAD_PROBLEM},
    "category": {"type": "choice", "instructions": "Which kind of street problem is this story about?",
                 "criteria": {"flood": "water on streets", "construction": "roadwork or building works",
                              "closure": "a road or lanes closed", "incident": "a crash or police activity",
                              "event": "a large event affecting traffic", "other": "not a street problem"}},
    "severity": {"type": "score", "instructions": "How much does this affect travel on Miami-Dade streets?",
                 "criteria": ["no impact", "minor, one street", "a few streets or lanes", "a major road or area",
                              "citywide or dangerous"]},
}
CATEGORIES = list(QUESTIONS["category"]["criteria"])


def state_for(item: dict) -> str:
    """The frozen runtime format (news_triage.state_for): title, blank line, RSS summary."""
    return f"{item.get('title') or ''}\n\n{item.get('summary') or ''}"
