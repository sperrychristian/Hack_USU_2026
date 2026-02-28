import math                     # math functions like log() and sqrt()
import random                   # random.sample
import time                     # time.perf_counter() for timing comparisons
from datetime import datetime, timezone  # datetime parsing and UTC time
import numpy as np              # NumPy for arrays and mean()


def _parse_github_datetime(dt_str):
    """
    GitHub timestamps look like: '2024-01-01T12:34:56Z'
    Convert that string into a Python datetime object.
    Return None if dt_str is missing or invalid.
    """
    if not dt_str:
        return None
    try:
        # fromisoformat doesn't understand "Z", so we replace it with "+00:00"
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _days_since(dt):
    """
    Return integer days since datetime dt.
    If dt is None, return None.
    """
    if dt is None:
        return None

    # Get current time in UTC
    now = datetime.now(timezone.utc)

    # Convert dt to UTC and subtract
    delta = now - dt.astimezone(timezone.utc)

    # Convert seconds into whole days (floor division)
    return int(delta.total_seconds() // 86400)


def enrich_repos(repos):
    """
    Add derived fields to each repo dictionary.

    Derived fields:
      - pushed_dt: datetime version of pushed_at
      - days_since_push: integer days since last push
      - is_active_30 / 90 / 365: boolean activity flags

    We copy each repo dict so we do not mutate the original list.
    """
    enriched = []

    for r in repos:
        pushed_dt = _parse_github_datetime(r.get("pushed_at"))
        days = _days_since(pushed_dt)

        new_r = dict(r)  # copy
        new_r["pushed_dt"] = pushed_dt
        new_r["days_since_push"] = days

        # Activity flags (True if pushed within the window)
        new_r["is_active_30"] = (days is not None and days <= 30)
        new_r["is_active_90"] = (days is not None and days <= 90)
        new_r["is_active_365"] = (days is not None and days <= 365)

        enriched.append(new_r)

    return enriched


def compute_summary(repos):
    """
    Compute recruiter-friendly summary stats.

    Includes:
      - stars stats (total/avg/min/max)
      - activity (active in last 30/90/365 days)
      - stale repos (365+ days or missing pushed_at)
      - repo hygiene (archived, license)
      - issues overview (how many repos have open issues)
    """
    if not repos:
        # Return a complete summary dict with zeros, so UI never crashes
        return {
            "repo_count": 0,
            "total_stars": 0,
            "avg_stars": 0,
            "min_stars": 0,
            "max_stars": 0,
            "active_30d": 0,
            "active_90d": 0,
            "active_365d": 0,
            "stale_365d_plus": 0,
            "archived_count": 0,
            "licensed_count": 0,
            "repos_with_issues": 0,
            "total_open_issues": 0
        }

    repos = enrich_repos(repos)

    stars = []
    total_stars = 0

    active_30d = 0
    active_90d = 0
    active_365d = 0
    stale_365d_plus = 0

    archived_count = 0
    licensed_count = 0

    repos_with_issues = 0
    total_open_issues = 0

    for r in repos:
        # Stars
        s = int(r.get("stargazers_count", 0))
        stars.append(s)
        total_stars += s

        # Activity flags
        if r.get("is_active_30"):
            active_30d += 1
        if r.get("is_active_90"):
            active_90d += 1
        if r.get("is_active_365"):
            active_365d += 1

        # Stale logic: missing pushed date OR > 365 days ago
        d = r.get("days_since_push")
        if d is None or d > 365:
            stale_365d_plus += 1

        # Archived flag
        if bool(r.get("archived", False)):
            archived_count += 1

        # License: usually dict or None
        if r.get("license") is not None:
            licensed_count += 1

        # Issues
        issues = int(r.get("open_issues_count", 0))
        total_open_issues += issues
        if issues > 0:
            repos_with_issues += 1

    repo_count = len(repos)
    avg_stars = total_stars / repo_count if repo_count else 0
    min_stars = min(stars) if stars else 0
    max_stars = max(stars) if stars else 0

    return {
        "repo_count": repo_count,
        "total_stars": total_stars,
        "avg_stars": avg_stars,
        "min_stars": min_stars,
        "max_stars": max_stars,
        "active_30d": active_30d,
        "active_90d": active_90d,
        "active_365d": active_365d,
        "stale_365d_plus": stale_365d_plus,
        "archived_count": archived_count,
        "licensed_count": licensed_count,
        "repos_with_issues": repos_with_issues,
        "total_open_issues": total_open_issues
    }


def top_repos_by_stars(repos, n=10):
    """Sort repos by stars descending and return top n."""
    return sorted(repos, key=lambda r: int(r.get("stargazers_count", 0)), reverse=True)[:n]


def top_repos_by_forks(repos, n=10):
    """Sort repos by forks descending and return top n."""
    return sorted(repos, key=lambda r: int(r.get("forks_count", 0)), reverse=True)[:n]


def top_repos_by_recent_push(repos, n=10):
    """
    Sort repos by most recent push (smallest days_since_push).
    We enrich repos so we can access days_since_push.
    """
    enriched = enrich_repos(repos)
    # Treat None as very old by using a huge number
    return sorted(
        enriched,
        key=lambda r: r["days_since_push"] if r["days_since_push"] is not None else 10**9
    )[:n]


def top_languages(repos, n=10):
    """
    Count repos per language and return top n.
    Demonstrates dictionary aggregation.
    """
    counts = {}

    for r in repos:
        lang = r.get("language")
        if lang is None:
            continue

        # Initialize if missing
        if lang not in counts:
            counts[lang] = 0

        # Increment count (augmented assignment)
        counts[lang] += 1

    rows = [{"language": lang, "repo_count": counts[lang]} for lang in counts]
    return sorted(rows, key=lambda x: x["repo_count"], reverse=True)[:n]


def search_repos(repos, keyword):
    """Search repos by name (case-insensitive)."""
    keyword = keyword.strip().lower()
    matches = []

    for r in repos:
        name = str(r.get("name", "")).lower()
        if keyword in name:
            matches.append(r)

    return matches


def repo_score(repo):
    """
    Custom math-based scoring function.
    Demonstrates math.log and math.sqrt.
    """
    stars = int(repo.get("stargazers_count", 0))
    forks = int(repo.get("forks_count", 0))
    return math.log(stars + 1) * 2 + math.sqrt(forks + 1)


def random_spotlight(repos, k=5):
    """Pick k random repos or return all if fewer than k."""
    if len(repos) <= k:
        return repos
    return random.sample(repos, k)


def numpy_speed_test(stars_list):
    """
    Compare loop mean vs NumPy mean + timing.
    Returns means and how long each method took.
    """
    # Loop timing
    start_loop = time.perf_counter()

    total = 0
    for s in stars_list:
        total += s

    loop_mean = total / len(stars_list) if stars_list else 0
    loop_seconds = time.perf_counter() - start_loop

    # NumPy timing
    start_np = time.perf_counter()

    arr = np.array(stars_list, dtype=float)
    numpy_mean = float(arr.mean()) if stars_list else 0

    numpy_seconds = time.perf_counter() - start_np

    return {
        "loop_mean": loop_mean,
        "numpy_mean": numpy_mean,
        "loop_seconds": loop_seconds,
        "numpy_seconds": numpy_seconds
    }


def build_repo_rows(repos, username):
    """
    Convert GitHub repo dicts into simple row dicts for CSV/SQLite.
    This is a classic "transform" step (API -> clean rows).
    """
    enriched = enrich_repos(repos)
    rows = []

    for r in enriched:
        # License can be a dict or None
        license_obj = r.get("license")
        license_name = None
        if isinstance(license_obj, dict):
            license_name = license_obj.get("name")

        rows.append({
            "username": username,
            "repo_id": r.get("id"),
            "name": r.get("name"),
            "full_name": r.get("full_name"),
            "html_url": r.get("html_url"),
            "language": r.get("language"),
            "stargazers_count": int(r.get("stargazers_count", 0)),
            "forks_count": int(r.get("forks_count", 0)),
            "open_issues_count": int(r.get("open_issues_count", 0)),
            "size_kb": int(r.get("size", 0)),
            "archived": bool(r.get("archived", False)),
            "license_name": license_name,
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "pushed_at": r.get("pushed_at"),
            "days_since_push": r.get("days_since_push"),
            "is_active_30": bool(r.get("is_active_30")),
            "is_active_90": bool(r.get("is_active_90")),
            "is_active_365": bool(r.get("is_active_365"))
        })

    return rows