# db_utils.py
#
# Purpose:
# This file handles saving and loading results to a local SQLite database (github.db).
# I use SQLite because it is built into Python, runs locally, and works well for small apps.
#
# Why I built it this way (professor-review context):
# - Streamlit re-runs the script on every interaction, so I keep DB logic in functions.
# - I want the app to be "production safe" for grading, meaning:
#     * It creates tables if missing
#     * It can upgrade older database schemas without crashing (migrations)
#     * It avoids breaking if a student runs older versions of the DB file
#
# Files created:
# - github.db: the SQLite database file in the project root

import sqlite3                  # Built-in DB library in Python (no install needed)
from datetime import datetime   # Used for timestamps (created_at)

DB_PATH = "github.db"           # SQLite file name (created automatically)


# ----------------------------
# Connection helpers
# ----------------------------
def get_conn():
    """
    Open a connection to the SQLite database file.

    Why check_same_thread=False:
    Streamlit can re-run code and manage state in a way that sometimes
    triggers SQLite "thread" warnings. This option avoids that issue.
    """
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def _table_exists(conn, table_name):
    """
    Return True if a table exists in the SQLite database.
    I use sqlite_master which is SQLite's internal schema table.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cur.fetchone() is not None


def _get_table_columns(conn, table_name):
    """
    Return a set of column names for a table.

    PRAGMA table_info returns rows like:
      (cid, name, type, notnull, dflt_value, pk)

    I only keep the "name" field because I want to check if columns exist.
    """
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    rows = cur.fetchall()
    return set([r[1] for r in rows])


# ----------------------------
# Schema versioning
# ----------------------------
def _ensure_schema_version_table(conn):
    """
    Create a schema_version table to track migrations.

    Design:
    - This table stores exactly one row (id = 1)
    - version is an integer number

    This makes it easier to "upgrade" the DB without breaking old copies.
    """
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schema_version (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        version INTEGER NOT NULL
    )
    """)

    # Ensure exactly one row exists
    cur.execute("SELECT version FROM schema_version WHERE id = 1")
    row = cur.fetchone()

    # If missing, insert version 1
    if row is None:
        cur.execute("INSERT INTO schema_version (id, version) VALUES (1, 1)")

    conn.commit()


def _get_schema_version(conn):
    """
    Read the current schema version from schema_version table.
    """
    _ensure_schema_version_table(conn)
    cur = conn.cursor()
    cur.execute("SELECT version FROM schema_version WHERE id = 1")
    return int(cur.fetchone()[0])


def _set_schema_version(conn, version):
    """
    Update the schema version after running migrations successfully.
    """
    cur = conn.cursor()
    cur.execute("UPDATE schema_version SET version = ? WHERE id = 1", (int(version),))
    conn.commit()


# ----------------------------
# Base schema creation
# ----------------------------
def _create_base_tables(conn):
    """
    Create base tables if they don't exist.

    Tables:
    - runs: one row per batch run (username + repo_count + timestamp)
    - repo_scores: one row per repo scored, linked to runs via run_id
    """
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        username TEXT NOT NULL,
        repo_count INTEGER NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS repo_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        repo_name TEXT NOT NULL,
        repo_url TEXT,
        language TEXT,
        total_score REAL,
        llm_skill_score REAL,
        hard_score REAL,
        activity_score REAL,
        popularity_score REAL,
        health_score REAL,
        strengths TEXT,
        weaknesses TEXT,
        notes TEXT,
        FOREIGN KEY(run_id) REFERENCES runs(id)
    )
    """)

    conn.commit()


# ----------------------------
# Migrations
# ----------------------------
def _migration_add_created_at_to_runs(conn):
    """
    Migration #1: Add created_at to runs if missing.

    Why this exists:
    Earlier versions of my DB may have created runs without created_at.
    SQLite supports ALTER TABLE ADD COLUMN, so I can add it safely.

    Safety:
    - If table doesn't exist, return
    - If column already exists, return
    - Otherwise, add column and backfill old rows with "now"
    """
    if not _table_exists(conn, "runs"):
        return

    cols = _get_table_columns(conn, "runs")
    if "created_at" in cols:
        return

    cur = conn.cursor()

    # Add the column
    cur.execute("ALTER TABLE runs ADD COLUMN created_at TEXT")

    # Backfill existing rows so old rows are not NULL
    now = datetime.now().isoformat(timespec="seconds")
    cur.execute("UPDATE runs SET created_at = ? WHERE created_at IS NULL", (now,))

    conn.commit()


def _migration_ensure_repo_scores_columns(conn):
    """
    Migration #2: Ensure repo_scores has all expected columns.

    Why:
    The repo_scores schema might evolve as I add fields to the scoring output.
    SQLite can only ADD columns easily, so I check for missing columns and add them.

    Note:
    This migration is idempotent (safe to run multiple times).
    """
    if not _table_exists(conn, "repo_scores"):
        return

    # Expected columns and types for repo_scores
    expected = {
        "repo_url": "TEXT",
        "language": "TEXT",
        "total_score": "REAL",
        "llm_skill_score": "REAL",
        "hard_score": "REAL",
        "activity_score": "REAL",
        "popularity_score": "REAL",
        "health_score": "REAL",
        "strengths": "TEXT",
        "weaknesses": "TEXT",
        "notes": "TEXT",
    }

    cols = _get_table_columns(conn, "repo_scores")
    cur = conn.cursor()

    # Add any missing columns
    for col, col_type in expected.items():
        if col not in cols:
            cur.execute(f"ALTER TABLE repo_scores ADD COLUMN {col} {col_type}")

    conn.commit()


def init_db():
    """
    Production-safe database initialization.

    What this does every time:
    1) Opens DB connection
    2) Ensures schema_version table exists
    3) Ensures base tables exist
    4) Runs migrations that repair older schemas
    5) Updates schema version number

    Important design:
    - This function is safe to call repeatedly.
    - I intentionally call init_db() inside each public function so the app does not
      break if the DB file is deleted or created fresh mid-run.
    """
    conn = get_conn()

    # Step 1: schema versioning exists
    _ensure_schema_version_table(conn)

    # Step 2: base tables exist
    _create_base_tables(conn)

    # Step 3: migrations (safe to re-run)
    _migration_add_created_at_to_runs(conn)
    _migration_ensure_repo_scores_columns(conn)

    # Step 4: bump schema version (current version = 2)
    current_version = _get_schema_version(conn)
    if current_version < 2:
        _set_schema_version(conn, 2)

    conn.close()


# ----------------------------
# Public DB functions used by app.py
# ----------------------------
def create_run(username, repo_count):
    """
    Create a new 'run' record.

    Inputs:
      - username: GitHub username analyzed
      - repo_count: number of repos fetched from API

    Returns:
      - run_id (int): primary key for this run, used to link repo_scores rows
    """
    init_db()

    conn = get_conn()
    cur = conn.cursor()

    # ISO timestamp is human-readable and sorts correctly in many contexts
    created_at = datetime.now().isoformat(timespec="seconds")

    cur.execute(
        "INSERT INTO runs (created_at, username, repo_count) VALUES (?, ?, ?)",
        (created_at, str(username), int(repo_count))
    )

    run_id = cur.lastrowid  # last inserted primary key value
    conn.commit()
    conn.close()
    return run_id


def save_repo_score(run_id, row):
    """
    Save one repo score row to repo_scores.

    The 'row' dict is produced by app.py batch scoring.
    Expected keys:
      repo, url, language,
      total_score, llm_skill_score, hard_score,
      activity_score, popularity_score, health_score,
      strengths (list), weaknesses (list), notes (string)

    Storage choice:
    - strengths/weaknesses are lists in Python, but SQLite does not store lists.
      I store them as newline-separated TEXT so it's readable when viewed later.
    """
    init_db()

    conn = get_conn()
    cur = conn.cursor()

    # Convert lists to a readable string format
    strengths_text = "\n".join(row.get("strengths", []) or [])
    weaknesses_text = "\n".join(row.get("weaknesses", []) or [])

    cur.execute("""
    INSERT INTO repo_scores (
        run_id, repo_name, repo_url, language,
        total_score, llm_skill_score, hard_score,
        activity_score, popularity_score, health_score,
        strengths, weaknesses, notes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        int(run_id),
        str(row.get("repo", "")),
        str(row.get("url", "")),
        str(row.get("language", "")),
        row.get("total_score"),
        row.get("llm_skill_score"),
        row.get("hard_score"),
        row.get("activity_score"),
        row.get("popularity_score"),
        row.get("health_score"),
        strengths_text,
        weaknesses_text,
        str(row.get("notes", "")),
    ))

    conn.commit()
    conn.close()


def get_recent_runs(limit=10):
    """
    Return the most recent run records.

    Output rows include:
      created_at, username, repo_count, run_id

    Safety:
    - COALESCE(created_at, '') keeps the query from failing if created_at is NULL
      in an older DB before migration.
    """
    init_db()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT COALESCE(created_at, '') AS created_at, username, repo_count, id
    FROM runs
    ORDER BY id DESC
    LIMIT ?
    """, (int(limit),))

    rows = cur.fetchall()
    conn.close()
    return rows


def get_run_repo_scores(run_id):
    """
    Return all repo_scores rows for a given run_id.

    Output columns match what app.py expects when displaying history.
    """
    init_db()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT repo_name, repo_url, language,
           total_score, llm_skill_score, hard_score,
           activity_score, popularity_score, health_score,
           strengths, weaknesses, notes
    FROM repo_scores
    WHERE run_id = ?
    ORDER BY total_score DESC
    """, (int(run_id),))

    rows = cur.fetchall()
    conn.close()
    return rows