# file_utils.py
#
# Purpose:
# This file handles saving outputs to disk in a few formats:
#   1) TXT report (easy for a human/professor to read)
#   2) JSON summary (easy for code/tools to read later)
#   3) CSV repo rows (easy to open in Excel/Sheets)
# It also loads GitHub usernames from a text file.
#
# Why I separated this into its own file:
# - Keeps app.py / main.py focused on UI and program flow
# - Shows modular design (single-responsibility functions)
# - Makes it easier to test saving/export logic independently

import os                      # File paths + existence checks
import csv                     # Write CSV files (built-in)
import json                    # Write JSON files (built-in)
from datetime import datetime  # Timestamp for filenames

REPORTS_DIR = "reports"        # Folder to store all outputs


def ensure_reports_dir():
    """
    Create the reports folder if it doesn't exist.

    exist_ok=True means:
      - If the folder already exists, do nothing
      - If it doesn't exist, create it
    This keeps the program from crashing when exporting.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)


def _timestamp():
    """
    Return a timestamp string for filenames.

    Example: 20260228_014512
    I use timestamps so exports don't overwrite previous runs.
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_report(username, summary, top_repos, top_langs):
    """
    Save a human-readable TXT report.
    Returns the saved file path.

    Why TXT:
    - A professor can open it quickly to see results
    - It's also useful for my own debugging
    """
    ensure_reports_dir()

    ts = _timestamp()
    path = os.path.join(REPORTS_DIR, f"{username}_report_{ts}.txt")

    # "with open" closes the file automatically when the block ends
    with open(path, "w", encoding="utf-8") as f:
        # Header lines
        f.write("GitHub Activity Analyzer Report\n")
        f.write(f"Username: {username}\n")
        f.write(f"Generated: {ts}\n\n")

        # Summary section (dictionary loop)
        f.write("SUMMARY\n")
        for k, v in summary.items():
            f.write(f"- {k}: {v}\n")

        # Top repos section
        f.write("\nTOP REPOS (by stars)\n")
        for r in top_repos:
            # .get() prevents KeyError if a field is missing
            name = r.get("name", "")
            stars = r.get("stargazers_count", 0)
            url = r.get("html_url", "")
            f.write(f"- {name} | stars={stars} | {url}\n")

        # Languages section
        f.write("\nTOP LANGUAGES\n")
        for row in top_langs:
            # row is a dict like {"language": "Python", "repo_count": 3}
            f.write(f"- {row['language']}: {row['repo_count']}\n")

    return path


def save_summary_json(username, summary):
    """
    Save the summary dictionary as JSON.
    Returns the saved file path.

    Why JSON:
    - Structured format (key/value)
    - Easy to read back in later if I want to build more features
    """
    ensure_reports_dir()

    ts = _timestamp()
    path = os.path.join(REPORTS_DIR, f"{username}_summary_{ts}.json")

    # json.dump writes Python dict -> JSON text
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return path


def save_repos_csv(username, repo_rows):
    """
    Save repo rows (list of dicts) as CSV.
    Returns the saved file path.

    repo_rows is produced by analytics.build_repo_rows(repos, username)
    and looks like a list of dictionaries, where each dict is one repo.
    """
    ensure_reports_dir()

    ts = _timestamp()
    path = os.path.join(REPORTS_DIR, f"{username}_repos_{ts}.csv")

    # If repo_rows is empty, still create an empty CSV file (safe behavior)
    if not repo_rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write("")
        return path

    # CSV headers should be consistent across rows.
    # I grab the keys from the first row dict.
    fieldnames = list(repo_rows[0].keys())

    # newline="" prevents extra blank lines on Windows
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        # First line of CSV is the header row
        writer.writeheader()

        # Write each repo row (dict) as one line in the CSV
        for row in repo_rows:
            writer.writerow(row)

    return path


def load_usernames(path="usernames.txt"):
    """
    Load GitHub usernames from a text file (one per line).
    Returns a list of strings.

    Expected file format:
      torvalds
      google
      openai
    """
    # If the file doesn't exist, print an error and return empty list
    # Returning [] is safer than crashing.
    if not os.path.exists(path):
        print(f"Error: file not found: {path}")
        return []

    usernames = []

    # Read the file line by line
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            u = line.strip()  # remove whitespace/newlines
            if u != "":
                usernames.append(u)  # only keep non-empty lines

    return usernames