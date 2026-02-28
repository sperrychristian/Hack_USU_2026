# GitHub Activity Analyzer (CLI + Streamlit)

## Problem / Goal
This project analyzes a GitHub user’s public repositories using the GitHub API. It computes summary statistics, finds top repositories by stars, identifies top languages, supports keyword search, generates a text report, and includes both a CLI menu and a Streamlit frontend.

## Features
- Fetch GitHub repository data using the GitHub REST API
- CLI menu with sentinel loop (`q` to quit)
- Summary analytics (repo count, total stars, avg/min/max stars)
- Sort repos by stars and show top results
- Count top programming languages
- Keyword search in repo names
- Random “spotlight” repo selection + custom math-based score
- NumPy comparison (loop mean vs NumPy mean + timing)
- Save report to a timestamped text file
- Streamlit UI for interactive viewing + report saving

## Tech Used
- Python
- requests (API calls)
- Streamlit (frontend)
- NumPy (arrays + mean)
- Built-in modules: os, math, random, time, datetime

## Project Structure
- `main.py` → CLI menu + program flow (routes user choices)
- `app.py` → Streamlit frontend (calls the same logic)
- `github_api.py` → GitHub API calls + error handling
- `analytics.py` → analytics, sorting/searching, NumPy test
- `file_utils.py` → saving reports + loading usernames
- `usernames.txt` → optional input file for batch analysis
- `reports/` → output folder for saved reports

## Course Concepts Demonstrated
- Variables, arithmetic, strings, f-strings
- input(), print(), triple-quoted strings (docstrings)
- if / elif / else logic
- while loop + sentinel value
- for loops, range usage (via enumerate), break/continue patterns
- lists (append, slicing), dictionaries
- sorting + searching
- functions with arguments + default parameters
- file I/O (read/write), os module (directories, paths)
- random module + math module usage
- NumPy array usage + performance comparison timing

## How to Run

### 1) Install dependencies
```bash
pip install requests numpy streamlit
