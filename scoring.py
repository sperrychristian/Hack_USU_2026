# ALL CODE INFLUENCED BY AI 

# scoring.py
#
# What this file is:
# This file contains the scoring logic for RepoLens. It converts repo statistics
# (stars, forks, issues, recency) into 0–100 scores and then combines them into
# an overall snapshot score.
#
# Why I wrote it this way (professor-facing explanation):
# - I separated each score into its own function (activity_score, popularity_score, etc.)
#   so each piece can be tested and tuned independently.
# - I used clamping to guarantee scores always stay in a predictable 0–100 range,
#   which keeps the UI stable and prevents weird edge cases from breaking charts.
# - I used log scaling for popularity so a repo with 10,000 stars doesn't completely
#   dominate the scoring compared to a repo with 50 stars.
#
# How to adjust weights later:
# In combined_repo_score(), I define the weights for hard score and LLM score.
# If I want to emphasize different signals, I only have to change them in one spot.

import math


def clamp(x, lo=0, hi=100):
    """
    Clamp a number into a bounded range.

    Why this matters:
    UI score displays, charts, and comparisons are easiest when every score
    is guaranteed to land inside [0, 100]. This prevents outliers or math
    mistakes from producing nonsense values like -12 or 240.
    """
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def activity_score(days_since_push):
    """
    Activity score (0–100). Newer push => higher score.

    Input:
      days_since_push (int | float | None)
        - Number of days since the repo was last pushed.
        - None means we could not compute it, so we treat it as inactive.

    Output:
      int score from 0 to 100.

    Why these thresholds:
    This is a simple heuristic that is easy to explain:
    - pushed in the last week feels “active”
    - pushed in the last month feels “maintained”
    - pushed in the last year feels “stale-ish”
    """
    if days_since_push is None:
        return 0

    d = float(days_since_push)

    if d <= 7:
        return 100
    if d <= 30:
        return 85
    if d <= 90:
        return 70
    if d <= 365:
        return 45
    return 20


def popularity_score(stars, forks):
    """
    Popularity score (0–100) using log scaling.

    Inputs:
      stars (int-like)
      forks (int-like)

    Why log scaling:
    Star/fork counts are extremely skewed. A few repos have huge counts and
    most repos have small counts. Using log1p() makes scoring more stable:
    - going from 0 -> 10 stars matters
    - going from 1000 -> 2000 stars matters less

    Output:
      float score clamped to 0–100.
    """
    s = max(0, int(stars or 0))
    f = max(0, int(forks or 0))

    # log1p(x) = log(1 + x), safe when x = 0
    raw = (math.log1p(s) * 18) + (math.log1p(f) * 14)

    return clamp(raw, 0, 100)


def repo_health_score(open_issues, archived):
    """
    Health score (0–100). Penalize archived repos and high open issue counts.

    Inputs:
      open_issues (int-like)
        - open issues can indicate maintenance burden or unfinished work
      archived (bool-like)
        - archived repos often indicate the project is no longer maintained

    Output:
      float score clamped to 0–100.

    Scoring logic:
      - start from 85 as a baseline
      - archived loses 25 points (strong penalty)
      - open issues subtract up to 25 points total (milder penalty)
    """
    issues = max(0, int(open_issues or 0))
    score = 85

    if archived:
        score -= 25

    if issues > 0:
        score -= min(25, issues * 1.5)

    return clamp(score, 0, 100)


def combined_repo_score(repo_row, llm_skill_score=None):
    """
    Combine multiple signals into a single per-repo score output.

    Inputs:
      repo_row (dict)
        Expected keys (from build_repo_rows in analytics.py):
        - days_since_push
        - stargazers_count
        - forks_count
        - open_issues_count
        - archived

      llm_skill_score (int | float | None)
        If present, this is the LLM-based assessment of code quality.
        If missing, we fall back to “hard metrics only.”

    Outputs:
      dict with:
        activity_score, popularity_score, health_score, hard_score,
        llm_skill_score, total_score

    Design choice:
    - "Hard score" = activity + popularity + health
      This is stable and doesn't require an LLM call.
    - "Total score" optionally blends hard score with the LLM score
      to capture code quality signals that raw GitHub metadata cannot.
    """
    a = activity_score(repo_row.get("days_since_push"))
    p = popularity_score(repo_row.get("stargazers_count"), repo_row.get("forks_count"))
    h = repo_health_score(repo_row.get("open_issues_count"), repo_row.get("archived"))

    # Hard score is a weighted blend of simple, explainable metadata signals.
    # I weighted Activity highest because recency often matters for assessing “current skill.”
    hard = (0.45 * a) + (0.35 * p) + (0.20 * h)

    # If no LLM score is available, the total score is just the hard score.
    if llm_skill_score is None:
        total = hard
        llm = None
    else:
        llm = clamp(float(llm_skill_score), 0, 100)

        # I weight the LLM higher because it can reflect code quality more directly
        # than stars/forks/recency alone.
        total = (0.35 * hard) + (0.65 * llm)

    return {
        "activity_score": round(a, 1),
        "popularity_score": round(p, 1),
        "health_score": round(h, 1),
        "hard_score": round(hard, 1),
        "llm_skill_score": (round(llm, 1) if llm is not None else None),
        "total_score": round(total, 1),
    }


def average_scores(score_rows):
    """
    Compute simple averages across repos.

    Input:
      score_rows: list[dict]
        Each dict should contain keys produced by combined_repo_score().

    Output:
      dict of averages (rounded to 1 decimal), where missing values stay None.

    Implementation notes:
    - I track sums + counts separately because llm_skill_score may be None
      for some repos. That means I can't just average blindly.
    - This design also prevents division-by-zero errors.
    """
    if not score_rows:
        return {}

    keys = [
        "activity_score",
        "popularity_score",
        "health_score",
        "hard_score",
        "llm_skill_score",
        "total_score",
    ]

    sums = {k: 0.0 for k in keys}
    counts = {k: 0 for k in keys}

    for r in score_rows:
        for k in keys:
            v = r.get(k)
            if v is None:
                continue
            sums[k] += float(v)
            counts[k] += 1

    avg = {}
    for k in keys:
        if counts[k] == 0:
            avg[k] = None
        else:
            avg[k] = round(sums[k] / counts[k], 1)

    return avg


def confidence_score(scores):
    """
    Compute a simple confidence score (0–100) for the overall snapshot.

    Goal:
    Confidence answers: “How much should we trust the averages we’re showing?”

    Logic:
    - If we only scored 1 repo, confidence should be low even if it has an LLM score.
    - If we scored many repos, confidence can be higher.
    - If few repos successfully got an LLM skill score, confidence is reduced.

    Inputs:
      scores: list[dict]
        Each dict should contain llm_skill_score (possibly None).

    Output:
      int from 0 to 100.

    Notes:
    This is intentionally simple and explainable rather than statistically “perfect.”
    It behaves like a “signal strength” meter for the dashboard.
    """
    if not scores:
        return 0

    valid = 0
    for r in scores:
        if r.get("llm_skill_score") is not None:
            valid += 1

    pct = valid / len(scores)

    # Base confidence grows as we score more repos.
    if len(scores) <= 1:
        base = 20
    elif len(scores) <= 3:
        base = 50
    elif len(scores) <= 5:
        base = 70
    else:
        base = 90

    # Multiply by pct so missing LLM scores reduce confidence.
    return int(base * pct)