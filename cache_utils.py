# cache_utils.py
#
# Purpose:
# This file implements a very simple "file-based cache" for JSON objects.
# I use it to store API/LLM results so I do not repeat expensive calls.
#
# Why this matters:
# - Streamlit reruns the script often (every click), so caching prevents re-doing work.
# - LLM calls can be slow / rate-limited, so caching helps me stay within free quota.
# - Storing as JSON files keeps it beginner-friendly and easy to inspect in the filesystem.

import os       # Used for file paths and creating folders
import json     # Used to save/load cached objects as JSON
import time     # Used to calculate cache age (TTL)
import hashlib  # Used to create stable hashed cache keys


def ensure_dir(path):
    """
    Ensure a directory exists.
    exist_ok=True prevents errors if the folder already exists.
    """
    os.makedirs(path, exist_ok=True)


def _hash_key(s):
    """
    Convert an input string into a fixed-length SHA256 hex string.
    I do this so cache file names are safe (no slashes, spaces, etc.)
    and consistent length regardless of input size.
    """
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def cache_get(cache_dir, key, ttl_minutes):
    """
    Read from cache if possible.

    Inputs:
      - cache_dir: folder where cache files live (ex: "cache/llm")
      - key: file name key (usually a hash)
      - ttl_minutes: "time to live" in minutes, how long cache is valid

    Returns:
      - Cached JSON object (Python dict/list) if present and not expired
      - None if:
          * file doesn't exist
          * file is expired
          * file can't be read / JSON is invalid

    Design choice:
    I return None on failure instead of raising exceptions so the app
    doesn't crash just because cache is missing/broken.
    """
    ensure_dir(cache_dir)

    # Cache file path is like: cache/llm/<key>.json
    path = os.path.join(cache_dir, f"{key}.json")

    # If there's no file, there's no cached value.
    if not os.path.exists(path):
        return None

    # File modification time = "last time this cache was written"
    # Age is current time minus that modified time.
    age_seconds = time.time() - os.path.getmtime(path)

    # TTL check: if the file is too old, treat it as missing.
    if age_seconds > (ttl_minutes * 60):
        return None

    # Try to open and parse the JSON.
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # If the cache file is corrupted or unreadable, just ignore it.
        return None


def cache_set(cache_dir, key, obj):
    """
    Write a Python object to cache as JSON.

    Inputs:
      - cache_dir: folder for cached files
      - key: cache key (filename)
      - obj: any JSON-serializable Python object (dict/list/etc.)

    Behavior:
      - If writing fails, I silently ignore it. That way caching can fail
        without breaking the entire program.
    """
    ensure_dir(cache_dir)

    path = os.path.join(cache_dir, f"{key}.json")

    try:
        with open(path, "w", encoding="utf-8") as f:
            # indent=2 makes the JSON human-readable if I open the file later
            json.dump(obj, f, indent=2)
    except Exception:
        # If disk permissions or serialization fails, don't crash the app.
        pass


def make_llm_cache_key(repo_full_name, readme_text, code_files, model_name="default"):
    """
    Build a cache key for LLM outputs.

    The key should change when the LLM input changes.
    That means the key changes if:
      - repo name changes
      - model changes (ex: "groq_v1" vs "gemini")
      - README changes
      - sampled code files change

    Why I truncate:
    README and code can be huge, but cache keys should be small and stable.
    I only use the first 1500 characters of README and each file content.
    This is a tradeoff, but it's good enough for caching and avoids giant keys.

    Returns:
      - A SHA256 hashed string suitable for a filename.
    """
    # Keep hashing stable and small by truncating.
    readme_part = (readme_text or "")[:1500]

    # Build a simplified representation of the repo file sample.
    files_part = []
    for f in (code_files or []):
        files_part.append({
            "path": f.get("path", ""),
            "content": (f.get("content", "")[:1500])
        })

    # Serialize the key input as JSON with sort_keys=True
    # so the string is deterministic (same inputs -> same JSON string).
    raw = json.dumps({
        "repo": repo_full_name,
        "model": model_name,
        "readme": readme_part,
        "files": files_part
    }, sort_keys=True)

    # Hash the JSON string to get a consistent filename-safe key.
    return _hash_key(raw)