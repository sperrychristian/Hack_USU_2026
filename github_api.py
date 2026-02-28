# github_api.py
#
# Purpose:
# This file is the "data ingestion" layer of my project.
# It is responsible for pulling raw data from the GitHub REST API, then returning
# clean Python data structures (dicts/lists) for the rest of the app to use.
#
# Why I separated this into its own file:
# - app.py should focus on the Streamlit UI, not API details
# - analytics.py should focus on calculations, not network calls
# - this separation shows modular design + makes debugging easier
#
# Main features in this file:
# 1) Token support (higher GitHub rate limits)
# 2) A simple JSON file cache (so I don't spam the API while testing)
# 3) fetch_repos(): paginated fetch of user repos
# 4) fetch_repo_sample(): fetch README + a small code sample to send to the LLM

import os
import base64
import time
import json
import hashlib
from datetime import datetime  # (not required by core logic, but useful for debugging / future logs)
import requests

# ----------------------------
# Config
# ----------------------------

# Read the GitHub token from the environment.
# In Codespaces, I store this in Secrets (so it isn't hard-coded in my repo).
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Base headers sent with every GitHub request.
# Accept tells GitHub I want the modern JSON format.
BASE_HEADERS = {"Accept": "application/vnd.github+json"}

# If I have a token, attach it as a Bearer token.
# This increases API rate limits and avoids 403 errors as often.
if GITHUB_TOKEN:
    BASE_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# Default cache directory for API responses.
CACHE_DIR_DEFAULT = "cache"


# ----------------------------
# Simple file cache helpers
# ----------------------------
def _ensure_dir(path):
    """
    Make sure a folder exists before writing cache files into it.
    exist_ok=True prevents crashing if it already exists.
    """
    os.makedirs(path, exist_ok=True)


def _cache_key(prefix, url, params):
    """
    Build a stable cache key from:
      - request type ("GET")
      - URL
      - params (sorted so ordering does not change the hash)
    Then hash it so filenames are short and safe.
    """
    raw = prefix + "|" + url + "|" + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(cache_dir, key):
    """
    Convert a cache key into an on-disk path like:
      cache/<sha256>.json
    """
    return os.path.join(cache_dir, f"{key}.json")


def _cache_get(cache_dir, key, cache_minutes):
    """
    Try to load cached JSON from disk.
    Returns:
      - Python object if found and not expired
      - None if missing or expired or unreadable
    """
    path = _cache_path(cache_dir, key)

    # If the file doesn't exist, it's a cache miss.
    if not os.path.exists(path):
        return None

    # Check the age of the cache file using the file modification time.
    age_seconds = time.time() - os.path.getmtime(path)

    # If it is older than our TTL, ignore it (treat as miss).
    if age_seconds > cache_minutes * 60:
        return None

    # If it's fresh enough, try reading JSON.
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # If parsing fails, treat it as a miss.
        return None


def _cache_set(cache_dir, key, obj):
    """
    Save a Python object to disk as JSON.
    I keep this best-effort (no crashing if write fails).
    """
    _ensure_dir(cache_dir)
    path = _cache_path(cache_dir, key)

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
    except Exception:
        # Cache failures should not break the app.
        pass


def _get(url, params=None, timeout=20, use_cache=False, cache_minutes=30, cache_dir=CACHE_DIR_DEFAULT):
    """
    Wrapper around requests.get() with optional caching.

    Returns:
      (json_data, error_string)

    - json_data is a Python dict/list if successful
    - error_string is a human-readable message if something failed
    """
    # 1) Cache check (if enabled)
    if use_cache:
        key = _cache_key("GET", url, params)
        hit = _cache_get(cache_dir, key, cache_minutes)
        if hit is not None:
            return hit, None

    # 2) Make the HTTP request
    try:
        resp = requests.get(url, headers=BASE_HEADERS, params=params, timeout=timeout)
    except requests.RequestException as e:
        # This catches timeouts, DNS issues, no internet, etc.
        return None, f"Network error calling GitHub API: {e}"

    # 3) Handle common HTTP error codes
    if resp.status_code == 404:
        return None, "Not found (404)."
    if resp.status_code == 401:
        return None, "Unauthorized (401). Check your GITHUB_TOKEN."
    if resp.status_code == 403:
        # 403 commonly means rate limiting. GitHub often includes a message in JSON.
        msg = ""
        try:
            msg = resp.json().get("message", "")
        except Exception:
            msg = ""
        return None, f"Forbidden / rate limited (403). {msg}"
    if resp.status_code != 200:
        # Anything else non-200 is a generic API error.
        return None, f"GitHub API error: status {resp.status_code}"

    # 4) Parse JSON response body into Python structures
    try:
        data = resp.json()
    except ValueError:
        return None, "GitHub response was not valid JSON."

    # 5) Save to cache (if enabled)
    if use_cache:
        _cache_set(cache_dir, key, data)

    return data, None


# ----------------------------
# Core API functions
# ----------------------------
def fetch_repos(username, per_page=100, max_pages=10, use_cache=True, cache_minutes=30, cache_dir="cache"):
    """
    Fetch public repos for a GitHub username.

    Returns:
      - list of repo dictionaries (like GitHub API returns)
      - empty list [] if any error occurs (so caller does not crash)

    Why pagination:
      GitHub returns repos in pages. per_page is max 100.
      I loop pages until:
        - I hit max_pages, OR
        - I get an empty page, OR
        - I get fewer than per_page repos (meaning last page)
    """
    username = (username or "").strip()
    if username == "":
        print("Error: username cannot be empty.")
        return []

    all_repos = []  # this will grow as I fetch each page
    page = 1        # start at page 1

    while page <= max_pages:
        url = f"https://api.github.com/users/{username}/repos"

        params = {
            "per_page": per_page,
            "page": page,
            "sort": "pushed",        # I want most recently pushed repos first
            "direction": "desc",
        }

        data, err = _get(
            url,
            params=params,
            use_cache=use_cache,
            cache_minutes=cache_minutes,
            cache_dir=cache_dir
        )

        # If any error happens, return [] so the UI can show a message.
        if err:
            print(f"Error fetching repos: {err}")
            return []

        # GitHub should return a list here (one dict per repo).
        if not isinstance(data, list):
            print("Error: unexpected response format for repos.")
            return []

        # Empty list means no more pages.
        if len(data) == 0:
            break

        # Add this page's repos into our full list.
        all_repos.extend(data)

        # If GitHub returned less than per_page, we've reached the last page.
        if len(data) < per_page:
            break

        # Otherwise move to the next page.
        page += 1

    return all_repos


def fetch_repo_sample(owner, repo, use_cache=True, cache_minutes=30, cache_dir="cache"):
    """
    Fetch a small sample of a repository to send to the LLM.

    Returns:
      (readme_text, code_files)

    where code_files is a list like:
      [{"path": "README.md", "content": "..."},
       {"path": "src/main.py", "content": "..."}, ...]

    Strategy:
    - Fetch repo metadata to get the default branch
    - Fetch README using the /readme endpoint (best-effort)
    - Fetch a recursive git tree from the default branch commit
    - Choose a small set of "good" text/code files (avoid huge and binary)
    - Download content for those files via the contents API
    """
    owner = (owner or "").strip()
    repo = (repo or "").strip()
    if owner == "" or repo == "":
        return "", []

    # 1) Repo metadata (needed to find default_branch reliably)
    repo_url = f"https://api.github.com/repos/{owner}/{repo}"
    repo_data, err = _get(
        repo_url,
        use_cache=use_cache,
        cache_minutes=cache_minutes,
        cache_dir=cache_dir
    )

    # If the repo doesn't exist / is private / API fails, return empty sample.
    if err or not isinstance(repo_data, dict):
        return "", []

    default_branch = repo_data.get("default_branch", "main")

    # 2) README text (best effort)
    readme_text = ""
    readme_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    readme_data, readme_err = _get(
        readme_url,
        use_cache=use_cache,
        cache_minutes=cache_minutes,
        cache_dir=cache_dir
    )

    # README endpoint returns base64 content inside a dict.
    if not readme_err and isinstance(readme_data, dict):
        content_b64 = readme_data.get("content", "")
        if content_b64:
            try:
                readme_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
            except Exception:
                readme_text = ""

    # 3) Get tree SHA for default branch
    branch_url = f"https://api.github.com/repos/{owner}/{repo}/branches/{default_branch}"
    branch_data, err = _get(
        branch_url,
        use_cache=use_cache,
        cache_minutes=cache_minutes,
        cache_dir=cache_dir
    )
    if err or not isinstance(branch_data, dict):
        return readme_text, []

    commit = branch_data.get("commit", {}) or {}
    commit_sha = commit.get("sha")
    if not commit_sha:
        return readme_text, []

    # 4) Fetch commit details to find the tree SHA
    commit_url = f"https://api.github.com/repos/{owner}/{repo}/git/commits/{commit_sha}"
    commit_data, err = _get(
        commit_url,
        use_cache=use_cache,
        cache_minutes=cache_minutes,
        cache_dir=cache_dir
    )
    if err or not isinstance(commit_data, dict):
        return readme_text, []

    tree = (commit_data.get("tree") or {})
    tree_sha = tree.get("sha")
    if not tree_sha:
        return readme_text, []

    # 5) Fetch git tree recursively (this gives a list of file paths)
    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}"
    tree_data, err = _get(
        tree_url,
        params={"recursive": "1"},
        use_cache=use_cache,
        cache_minutes=cache_minutes,
        cache_dir=cache_dir
    )
    if err or not isinstance(tree_data, dict):
        return readme_text, []

    entries = tree_data.get("tree", []) or []
    if not entries:
        return readme_text, []

    # 6) Decide which file types are worth sampling (text/code)
    good_ext = (
        ".py", ".md", ".txt", ".json", ".yml", ".yaml",
        ".toml", ".ini", ".cfg",
        ".js", ".ts", ".html", ".css"
    )

    prioritized = []  # files I really want if they exist
    others = []       # other files that are still useful

    for e in entries:
        # Only "blob" entries are files. (Trees are folders.)
        if e.get("type") != "blob":
            continue

        path = e.get("path", "")
        size = e.get("size", 0) or 0

        # Skip very large files to avoid huge prompts.
        if size > 200_000:  # 200KB
            continue

        lower = path.lower()

        # Only include good extensions or key config files.
        if lower.endswith(good_ext) or lower in ("requirements.txt", "package.json"):
            # Favor README and main entrypoint files.
            if "readme" in lower or lower.endswith(("main.py", "app.py", "index.js")):
                prioritized.append(path)
            else:
                others.append(path)

    # Limit how many files I download (keeps prompt size manageable).
    chosen_paths = (prioritized + others)[:8]

    # 7) Download content for chosen files using the contents API
    code_files = []
    for path in chosen_paths:
        content_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        file_data, err = _get(
            content_url,
            use_cache=use_cache,
            cache_minutes=cache_minutes,
            cache_dir=cache_dir
        )
        if err or not isinstance(file_data, dict):
            continue

        # contents API returns base64 file content
        content_b64 = file_data.get("content", "")
        if not content_b64:
            continue

        try:
            raw = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except Exception:
            continue

        code_files.append({"path": path, "content": raw})

    return readme_text, code_files