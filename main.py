# ALL CODE INFLUENCED BY AI 

# main.py
#
# What this file is:
# This is my command-line (terminal) version of RepoLens / GitHub Activity Analyzer.
# Instead of a Streamlit UI, it uses a simple menu and prints results to the console.
#
# Why I built this:
# - It proves I understand the full data pipeline without relying on a web framework.
# - It gives a fast way to test features (API calls, analytics, exports, database writes).
# - A professor reviewing this can see I understand program flow, functions, loops, and imports.
#
# Big picture flow (Option 1):
#   GitHub API -> analytics -> exports (TXT/JSON/CSV) -> SQLite (save run + repo rows)
#
# Notes on style:
# - I use small functions so each feature is isolated and testable.
# - I keep printing logic separate from analysis logic.
# - I use input validation (empty usernames, empty results) to avoid crashes.

from github_api import fetch_repos
from analytics import (
    compute_summary,
    top_repos_by_stars,
    top_repos_by_forks,
    top_repos_by_recent_push,
    top_languages,
    search_repos,
    repo_score,
    random_spotlight,
    numpy_speed_test,
    build_repo_rows,
)
from file_utils import (
    save_report,
    save_summary_json,
    save_repos_csv,
    load_usernames,
)

# IMPORTANT:
# In my current Streamlit version, db_utils functions are:
#   init_db, create_run, save_repo_score, get_recent_runs, get_run_repo_scores
#
# This CLI file uses save_run and upsert_repos, which are from an older DB approach.
# If your db_utils.py still has save_run/upsert_repos, this will work.
# If not, I included a production-safe fallback below so this file works either way.
#
# Goal:
# Keep this CLI version compatible with BOTH database implementations.
from db_utils import init_db

# Try to import the old functions. If they don't exist, we fall back to the new ones.
try:
    from db_utils import save_run, upsert_repos
    _DB_MODE = "old"  # save_run + upsert_repos exist
except Exception:
    # New DB mode (matches the Streamlit app's DB functions)
    from db_utils import create_run, save_repo_score
    _DB_MODE = "new"


def print_menu():
    """
    Print the menu options.

    I keep this separate so the main loop stays clean and readable.
    """
    print("\nGitHub Activity Analyzer")
    print("----------------------------")
    print("1. Analyze a GitHub username (export + DB)")
    print("2. Analyze usernames from file (summary only)")
    print("3. Search repositories by keyword")
    print("4. Random spotlight + score")
    print("5. NumPy speed test")
    print("q. Quit")


def print_summary(summary):
    """
    Print the summary dict in a readable format.

    I define the order of keys so output is predictable and easy to compare across runs.
    """
    print("\nSUMMARY")
    print("----------------------------")

    keys = [
        "repo_count",
        "total_stars",
        "avg_stars",
        "min_stars",
        "max_stars",
        "active_30d",
        "active_90d",
        "active_365d",
        "stale_365d_plus",
        "archived_count",
        "licensed_count",
        "repos_with_issues",
        "total_open_issues",
    ]

    for k in keys:
        v = summary.get(k)
        # avg_stars is a float so I format it to 2 decimals for readability.
        if k == "avg_stars" and v is not None:
            v = round(v, 2)
        print(f"{k:16} : {v}")


def print_top_repos(title, repos, n=5, sort_field="stargazers_count"):
    """
    Print the top repositories with key fields.

    Parameters:
      title: label shown in the console
      repos: list of repo dicts from GitHub
      n: how many to print
      sort_field: which numeric field the list is ranked by (stars or forks)
    """
    print(f"\n{title}")
    print("----------------------------")

    # enumerate gives me a clean 1..n numbering for display.
    for i, r in enumerate(repos[:n], start=1):
        print(
            f"{i}. {r.get('name')} | {sort_field}={r.get(sort_field, 0)} | "
            f"lang={r.get('language')} | {r.get('html_url')}"
        )


def _save_to_db(username, repos, repo_rows):
    """
    Save a run + repos into SQLite.

    Why I made a helper:
    This is the only place in the file that cares about which db_utils functions exist.

    Supports:
      - Old mode: save_run(username, repo_count) + upsert_repos(repo_rows)
      - New mode: create_run(username, repo_count) + save_repo_score(run_id, row)
    """
    init_db()

    if _DB_MODE == "old":
        # Old schema approach: store repos as rows in a repos table (upsert).
        save_run(username, repo_count=len(repos))
        upsert_repos(repo_rows)
        return None

    # New schema approach: store a run row + a repo_scores row per repo.
    run_id = create_run(username, repo_count=len(repos))

    # In the Streamlit version, save_repo_score expects scoring fields too.
    # Here, the CLI is mostly analytics-focused, so I store the repo metadata and keep scores blank.
    for rr in repo_rows:
        save_repo_score(
            run_id,
            {
                "repo": rr.get("name", ""),
                "url": rr.get("html_url", ""),
                "language": rr.get("language", ""),
                "total_score": None,
                "llm_skill_score": None,
                "hard_score": None,
                "activity_score": None,
                "popularity_score": None,
                "health_score": None,
                "strengths": [],
                "weaknesses": [],
                "notes": "Saved from CLI mode (no LLM scoring performed).",
            },
        )

    return run_id


def analyze_one():
    """
    Full pipeline for one user:
      API -> analytics -> exports -> SQLite.

    This is the most complete option, since it demonstrates:
      - calling an external API
      - computing metrics
      - saving multiple file formats
      - writing to SQLite
    """
    username = input("Enter GitHub username: ").strip()

    # Basic input validation (prevents pointless API call).
    if username == "":
        print("Error: username cannot be empty.")
        return

    # Fetch repos from GitHub.
    repos = fetch_repos(username)
    if not repos:
        print("No repos returned (invalid username, private, or rate-limited).")
        return

    # Analytics computations (pure functions, no side effects).
    summary = compute_summary(repos)
    top_stars = top_repos_by_stars(repos, n=10)
    top_forks = top_repos_by_forks(repos, n=10)
    top_recent = top_repos_by_recent_push(repos, n=10)
    langs = top_languages(repos, n=10)

    # Convert repos to normalized rows for export/DB.
    repo_rows = build_repo_rows(repos, username=username)

    # Save exports (TXT/JSON/CSV).
    txt_path = save_report(username, summary, top_stars, langs)
    json_path = save_summary_json(username, summary)
    csv_path = save_repos_csv(username, repo_rows)

    # Save to DB (supports old OR new schema).
    run_id = _save_to_db(username, repos, repo_rows)

    # Show where exports were saved so the user knows what happened.
    print("\nEXPORTS")
    print("----------------------------")
    print("Report TXT :", txt_path)
    print("Summary JSON:", json_path)
    print("Repos CSV  :", csv_path)
    print("SQLite DB  :", "github.db")
    if run_id is not None:
        print("Run ID     :", run_id)

    # Print key results.
    print_summary(summary)
    print_top_repos("TOP REPOS (stars)", top_stars, n=5, sort_field="stargazers_count")
    print_top_repos("TOP REPOS (forks)", top_forks, n=5, sort_field="forks_count")

    print("\nMOST RECENTLY PUSHED")
    print("----------------------------")
    for i, r in enumerate(top_recent[:5], start=1):
        print(
            f"{i}. {r.get('name')} | days_since_push={r.get('days_since_push')} | {r.get('html_url')}"
        )


def analyze_file():
    """
    Analyze usernames listed in usernames.txt (summary-only mode).

    This option is intentionally lighter:
    - no file exports
    - no DB writes
    - just prints summary for each username
    """
    usernames = load_usernames()
    if not usernames:
        print("No usernames found. Create usernames.txt with one username per line.")
        return

    for u in usernames:
        print(f"\nAnalyzing {u}...")
        repos = fetch_repos(u)
        if not repos:
            print("  (No repos returned)")
            continue
        summary = compute_summary(repos)
        print_summary(summary)


def search_option():
    """
    Search a user's repos by keyword.

    Demonstrates:
    - reading multiple inputs
    - filtering with a helper function
    - limiting output size to keep console readable
    """
    username = input("Enter GitHub username: ").strip()
    keyword = input("Enter keyword: ").strip()

    if username == "" or keyword == "":
        print("Username and keyword are required.")
        return

    repos = fetch_repos(username)
    if not repos:
        print("No repos returned.")
        return

    matches = search_repos(repos, keyword)

    print(f"\nFound {len(matches)} repos matching '{keyword}':")
    print("----------------------------")
    for r in matches[:20]:
        print("-", r.get("name"), "|", r.get("html_url", ""))

    if len(matches) > 20:
        print("(Showing first 20 matches)")


def spotlight_option():
    """
    Random repos + math-based score.

    Demonstrates:
    - sampling (random_spotlight)
    - a custom scoring function using math.log and sqrt (repo_score)
    """
    username = input("Enter GitHub username: ").strip()
    if username == "":
        print("Username is required.")
        return

    repos = fetch_repos(username)
    if not repos:
        print("No repos returned.")
        return

    picks = random_spotlight(repos, k=5)

    print("\nRANDOM SPOTLIGHT (custom score)")
    print("----------------------------")
    for r in picks:
        print(r.get("name"), "| score=", round(repo_score(r), 3), "|", r.get("html_url"))


def numpy_option():
    """
    Compare loop mean vs NumPy mean + timing.

    Demonstrates:
    - building a numeric list from repo data
    - measuring runtime using time.perf_counter inside numpy_speed_test
    """
    username = input("Enter GitHub username: ").strip()
    if username == "":
        print("Username is required.")
        return

    repos = fetch_repos(username)
    if not repos:
        print("No repos returned.")
        return

    stars = [int(r.get("stargazers_count", 0)) for r in repos]
    results = numpy_speed_test(stars)

    print("\nNUMPY SPEED TEST")
    print("----------------------------")
    print(f"Loop mean : {round(results['loop_mean'], 4)}")
    print(f"NumPy mean: {round(results['numpy_mean'], 4)}")
    print(f"Loop time : {results['loop_seconds']:.8f} seconds")
    print(f"NumPy time: {results['numpy_seconds']:.8f} seconds")


def main():
    """
    Sentinel-controlled main menu loop.

    Sentinel pattern explanation:
    - I keep looping until the user enters "q"
    - This is a clean way to avoid repeating code or needing recursion
    """
    choice = ""
    while choice != "q":
        print_menu()
        choice = input("Choice: ").strip().lower()

        if choice == "1":
            analyze_one()
        elif choice == "2":
            analyze_file()
        elif choice == "3":
            search_option()
        elif choice == "4":
            spotlight_option()
        elif choice == "5":
            numpy_option()
        elif choice == "q":
            print("Goodbye!")
        else:
            print("Invalid option. Try again.")


# Standard Python entry point.
# This ensures the menu runs only when I execute this file directly:
#   python main.py
# and not when it's imported by another file.
if __name__ == "__main__":
    main()