# app.py
#
# RepoLens (Streamlit UI)
#
# Purpose:
# This file is the Streamlit front-end for my project.
# It takes GitHub API data and turns it into an interactive dashboard.
#
# Design choice:
# I keep UI code here, and I keep "business logic" (analytics, scoring, caching, DB, LLM)
# in separate modules. This makes the code easier to read, test, and maintain.

import os                     # Used for file paths and opening generated files (like PDFs)
import shutil                 # Used to delete directories (clearing caches)
import base64                 # Used to embed an SVG logo into the page as a base64 data URI
import streamlit as st        # Streamlit is the UI framework for the project
import pandas as pd           # Pandas makes it easy to display tables and build chart-ready data

# These imports are all "separated concerns":
# - github_api.py: API calls + repo sampling
# - analytics.py: computed metrics and transformations
# - scoring.py: combines scoring signals into final score
# - llm_utils.py: LLM calls for repo review and portfolio summary
# - cache_utils.py: caching layer so we don't waste free quota
# - db_utils.py: SQLite persistence for "history"
# - report_utils.py: PDF export
from github_api import fetch_repos, fetch_repo_sample
from analytics import compute_summary, top_languages, build_repo_rows
from scoring import combined_repo_score, average_scores, confidence_score
from llm_utils import analyze_repo_quality_with_llm, analyze_portfolio_summary
from cache_utils import cache_get, cache_set, make_llm_cache_key
from db_utils import (
    init_db,
    create_run,
    save_repo_score,
    get_recent_runs,
    get_run_repo_scores,
)
from report_utils import export_recruiter_pdf


# ----------------------------
# Page Config
# ----------------------------
# This sets app-level Streamlit settings.
# "wide" gives more space for tables and dashboards.
st.set_page_config(page_title="RepoLens", layout="wide")


# ----------------------------
# Logo (inline SVG)
# ----------------------------
# I use an inline SVG string because:
# - It loads instantly (no external image file needed)
# - It scales cleanly
# - It can match my app color palette
def repolens_logo_svg(accent="#0EA5E9", accent2="#22C55E"):
    return f"""
<svg width="42" height="42" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="RepoLens logo">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{accent}"/>
      <stop offset="1" stop-color="{accent2}"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="64" height="64" rx="16" fill="#FFFFFF"/>
  <circle cx="28" cy="28" r="14" fill="none" stroke="url(#g)" stroke-width="6"/>
  <circle cx="28" cy="28" r="7" fill="none" stroke="{accent}" stroke-width="3" opacity="0.85"/>
  <path d="M38.5 38.5 L51 51" stroke="url(#g)" stroke-width="6" stroke-linecap="round"/>
  <path d="M46 14 L48 18 L52 20 L48 22 L46 26 L44 22 L40 20 L44 18 Z" fill="{accent2}" opacity="0.9"/>
</svg>
""".strip()


# Streamlit needs images as URLs/paths.
# This helper converts SVG text into a "data URI" that Streamlit can render.
def svg_to_data_uri(svg: str) -> str:
    b64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
    return f"data:image/svg+xml;base64,{b64}"


# ----------------------------
# Tooltip text (single source of truth)
# ----------------------------
# These tooltips are used for hover explanations on metrics.
# Having them in one dictionary prevents inconsistent wording across the UI.
TOOLTIPS = {
    "Total": "Overall score (0–100). Weighted blend of Hard + Activity + Popularity + Health + (optional) LLM Skill.",
    "LLM Skill": "LLM reads a sample of README + code files and scores code quality & clarity (0–100).",
    "Hard": "Static signals of engineering depth, e.g., language mix, repo structure, docs, and code footprint signals.",
    "Activity": "How recently and consistently the repo has been updated (recency, pushes).",
    "Popularity": "Public interest signals like stars and forks (normalized).",
    "Health": "Maintenance signals like issues open, archived state, and basic repo hygiene.",
    "Confidence": "How reliable the snapshot is based on number of repos scored and how consistent they are.",
}


# ----------------------------
# UI helpers
# ----------------------------
# These functions help keep UI consistent and avoid duplicated UI code.
def score_color(score):
    """
    Convert a score (0–100) into a color used across the UI.
    I use green/blue/yellow/red for quick interpretation.
    """
    try:
        s = float(score)
    except Exception:
        return "#94A3B8"  # gray for invalid/unknown values

    if s >= 80:
        return "#22C55E"  # green
    if s >= 60:
        return "#0EA5E9"  # blue
    if s >= 40:
        return "#F59E0B"  # orange
    return "#EF4444"      # red


def render_badge(label, value):
    """
    Render a small pill/badge with a colored dot and a label/value.
    This is used for compact score summaries.
    """
    color = score_color(value)
    safe_val = value if value is not None else "—"  # avoid showing "None" in the UI

    return f"""
    <span style="
        display:inline-flex;
        align-items:center;
        gap:8px;
        padding:7px 12px;
        border-radius:999px;
        border:1px solid #E2E8F0;
        background:#FFFFFF;
        font-weight:800;
        color:#0F172A;
        font-size: 13px;">
        <span style="width:10px;height:10px;border-radius:999px;background:{color};"></span>
        <span style="color:#334155; font-weight:800;">{label}:</span>
        <span>{safe_val}</span>
    </span>
    """


def render_score_bar(label, value):
    """
    Render a horizontal progress bar style visualization for a score.
    Useful when I want to show score magnitude visually.
    """
    try:
        v = max(0, min(100, int(value)))  # clamp values to 0–100
    except Exception:
        v = 0

    bar_color = score_color(v)

    return f"""
    <div style="margin: 10px 0;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="font-weight:900; color:#0F172A;">{label}</div>
            <div style="font-weight:900; color:#0F172A;">{v}</div>
        </div>
        <div style="
            width:100%;
            height:12px;
            background:#F1F5F9;
            border-radius:999px;
            overflow:hidden;
            border:1px solid #E2E8F0;
        ">
            <div style="
                height:12px;
                width:{v}%;
                background:{bar_color};
                border-radius:999px;
            "></div>
        </div>
    </div>
    """


# ----------------------------
# Minimal CSS (let Streamlit theme handle most)
# ----------------------------
# Streamlit by default shows a top header bar. I hide it to keep UI clean.
# I keep CSS minimal to reduce the risk of contrast bugs.
st.markdown(
    """
<style>
/* remove Streamlit top header bar */
[data-testid="stHeader"]{ background: transparent !important; height: 0px !important; border-bottom: none !important; }
[data-testid="stToolbar"]{ visibility: hidden !important; height: 0px !important; }
[data-testid="stDecoration"]{ display: none !important; }
header{ visibility: hidden !important; height: 0px !important; }
.block-container{ padding-top: 1.2rem !important; }
</style>
""",
    unsafe_allow_html=True,
)


# ----------------------------
# Header
# ----------------------------
# I render the logo using a data URI so there are no external image assets needed.
logo_uri = svg_to_data_uri(repolens_logo_svg())

st.markdown(
    f"""
<div style="display:flex; align-items:center; gap:12px; margin-bottom:6px;">
    <img src="{logo_uri}" width="42" height="42" />
    <div>
      <h1 style="margin:0; padding:0;">RepoLens</h1>
      <div style="font-weight:800; margin-top:2px;">
        GitHub insights.
      </div>
    </div>
</div>
<div style="height:5px;width:100%;background: linear-gradient(90deg, #0EA5E9, #22C55E);
border-radius:999px;margin-bottom:18px;"></div>
""",
    unsafe_allow_html=True,
)

# Sidebar logo/title block
st.sidebar.markdown(
    f"""
<div style="display:flex; align-items:center; gap:10px; margin: 10px 0 8px 0;">
  <img src="{logo_uri}" width="34" height="34" />
  <div style="display:flex; flex-direction:column;">
    <div style="font-size:18px; font-weight:950; line-height:1;">RepoLens</div>
    <div style="font-size:12px; font-weight:800; margin-top:2px;">GitHub insights</div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)


# ----------------------------
# Constants
# ----------------------------
# This is where LLM cache files are stored.
# Caching avoids re-paying (quota/time) for the same repo analysis.
LLM_CACHE_DIR = "cache/llm"

# This is a version label I include in cache keys.
# If I change providers/models later, I can avoid mixing old cache entries with new ones.
LLM_CACHE_VERSION = "groq_v1"


# ----------------------------
# Session state
# ----------------------------
# Streamlit re-runs the script from top to bottom on every interaction.
# Session state is how I persist values across re-runs (like repos I already fetched).
if "repos" not in st.session_state:
    st.session_state["repos"] = None
if "repo_rows" not in st.session_state:
    st.session_state["repo_rows"] = None
if "username" not in st.session_state:
    st.session_state["username"] = ""
if "scores" not in st.session_state:
    st.session_state["scores"] = []
if "portfolio_summary" not in st.session_state:
    st.session_state["portfolio_summary"] = None
if "last_run_id" not in st.session_state:
    st.session_state["last_run_id"] = None


# ----------------------------
# Sidebar controls
# ----------------------------
# I put controls in the sidebar so the main page stays focused on results.
st.sidebar.header("Controls")

# Text input for username
username_input = st.sidebar.text_input(
    "GitHub Username",
    value=st.session_state["username"],
    placeholder="e.g., torvalds",
).strip()

# GitHub caching controls (separate from LLM caching)
use_cache = st.sidebar.checkbox("Use GitHub cache", value=True)
cache_minutes = st.sidebar.number_input("GitHub cache minutes", 1, 240, 30)

# LLM caching and scoring controls
st.sidebar.subheader("LLM Settings")
use_llm_cache = st.sidebar.checkbox("Use LLM cache (recommended)", value=True)
llm_cache_minutes = st.sidebar.number_input("LLM cache minutes", 1, 7 * 24 * 60, 24 * 60)
repos_to_score = st.sidebar.number_input("Repos to LLM-score", 1, 25, 8)
max_pages = st.sidebar.number_input("Max pages to fetch repos", 1, 20, 5)

# Maintenance tools (clearing caches)
st.sidebar.subheader("Maintenance")
clear_llm_cache_btn = st.sidebar.button("Clear LLM cache (cache/llm)", type="secondary")

# Main actions
fetch_btn = st.sidebar.button("Fetch Repos", type="primary")
score_btn = st.sidebar.button("Run Batch LLM Scoring", type="primary")


# ----------------------------
# Maintenance actions
# ----------------------------
# Clear LLM cache directory and reset related UI state.
if clear_llm_cache_btn:
    try:
        if os.path.exists(LLM_CACHE_DIR):
            shutil.rmtree(LLM_CACHE_DIR)            # delete entire cache folder
        os.makedirs(LLM_CACHE_DIR, exist_ok=True)   # recreate folder
        st.sidebar.success("Cleared LLM cache.")
        st.session_state["scores"] = []
        st.session_state["portfolio_summary"] = None
    except Exception as e:
        st.sidebar.error(f"Failed to clear LLM cache: {repr(e)}")


# ----------------------------
# Fetch repos
# ----------------------------
# When the user clicks "Fetch Repos", I call GitHub API (optionally cached).
if fetch_btn:
    if username_input == "":
        st.error("Enter a username.")
        st.stop()

    st.session_state["username"] = username_input

    with st.spinner("Fetching repositories..."):
        repos = fetch_repos(
            username_input,
            per_page=100,
            max_pages=int(max_pages),
            use_cache=use_cache,
            cache_minutes=int(cache_minutes),
            cache_dir="cache",
        )

    # If no repos are returned, show error and stop.
    if not repos:
        st.error("No repos returned. Check the username, or you may be rate limited.")
        st.stop()

    # Save results into session state so the user can navigate tabs without refetching.
    st.session_state["repos"] = repos

    # build_repo_rows transforms raw GitHub API dictionaries into cleaner rows for UI/SQLite.
    st.session_state["repo_rows"] = build_repo_rows(repos, username=username_input)

    # Reset scoring state since we fetched a new account.
    st.session_state["scores"] = []
    st.session_state["portfolio_summary"] = None
    st.session_state["last_run_id"] = None


# Pull state into local variables (purely for readability).
repos = st.session_state["repos"]
repo_rows = st.session_state["repo_rows"]
username = st.session_state["username"]


# Tabs organize the app into separate views.
tabs = st.tabs(
    [
        "Dashboard",
        "Repo Explorer",
        "Languages",
        "LLM Review + Scoring",
        "History (SQLite)",
    ]
)


# If repos aren't loaded yet, show a helpful message and stop early.
if repos is None:
    with tabs[0]:
        st.info("Fetch repos to begin.")
    st.stop()


# ----------------------------
# Dashboard
# ----------------------------
with tabs[0]:
    st.header("Dashboard")

    # compute_summary calculates aggregate account metrics (stars, activity, etc.)
    summary = compute_summary(repos)

    # High-level metrics displayed at the top.
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Repos", summary.get("repo_count", 0))
    c2.metric("Total Stars", summary.get("total_stars", 0))
    c3.metric("Avg Stars", round(summary.get("avg_stars", 0), 2))
    c4.metric("Active (90d)", summary.get("active_90d", 0))

    scores = st.session_state["scores"]
    st.divider()

    # If batch scoring has run, show averages and charts.
    if scores:
        avg = average_scores(scores)          # average score across scored repos
        conf = confidence_score(scores)       # confidence estimate (how reliable snapshot is)

        # Using Streamlit's metric "help" creates hover tooltips with ⓘ
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Avg Total", avg.get("total_score"), help=TOOLTIPS["Total"])
        m2.metric("Avg LLM Skill", avg.get("llm_skill_score"), help=TOOLTIPS["LLM Skill"])
        m3.metric("Avg Hard", avg.get("hard_score"), help=TOOLTIPS["Hard"])
        m4.metric("Confidence", conf, help=TOOLTIPS["Confidence"])

        # Visualization: bar chart of total_score per repo
        st.subheader("Developer Score Visualization (Total Score per Repo)")
        st.caption("Hover tooltips: Total = overall score. See ⓘ next to metric labels above.")

        chart_df = pd.DataFrame([{"repo": r["repo"], "total_score": r["total_score"]} for r in scores])
        chart_df = chart_df.sort_values("total_score", ascending=False).set_index("repo")
        st.bar_chart(chart_df)

        st.divider()
        st.subheader("Portfolio Summary")

        # This button triggers an LLM to summarize across all repo scores.
        if st.button("Generate Portfolio Summary (LLM)"):
            with st.spinner("Generating portfolio summary..."):
                ps, err = analyze_portfolio_summary(username, scores)
                if err:
                    st.error(err)
                else:
                    st.session_state["portfolio_summary"] = ps

        ps = st.session_state["portfolio_summary"]
        if ps:
            st.write(f"**Headline:** {ps.get('headline','')}")
            st.write(ps.get("recruiter_summary", ps.get("portfolio_summary", "")))

            colx, coly = st.columns(2)
            with colx:
                st.write("**Top Strengths:**")
                for s in ps.get("top_strengths", [])[:3]:
                    st.write(f"- {s}")
            with coly:
                st.write("**Top Risks / Gaps:**")
                for r in ps.get("top_risks", [])[:3]:
                    st.write(f"- {r}")

        st.divider()
        st.subheader("Export")

        # Export creates a PDF report and then provides a download button.
        if st.button("Export PDF"):
            pdf_path = export_recruiter_pdf(
                username=username,
                summary=summary,
                avg_scores=avg,
                repo_rows=scores,
            )
            st.success("PDF created.")
            st.download_button(
                "Download PDF",
                data=open(pdf_path, "rb").read(),
                file_name=os.path.basename(pdf_path),
                mime="application/pdf",
            )
    else:
        st.info("Run Batch LLM Scoring to populate scores and export.")


# ----------------------------
# Repo Explorer
# ----------------------------
with tabs[1]:
    st.header("Repo Explorer")

    # Convert rows into DataFrame so Streamlit can display it nicely.
    df = pd.DataFrame(repo_rows)
    if df.empty:
        st.warning("No repo rows.")
        st.stop()

    # Choose columns that are useful in an explorer table.
    cols = [
        "name",
        "html_url",
        "language",
        "stargazers_count",
        "forks_count",
        "open_issues_count",
        "days_since_push",
        "archived",
    ]

    # Only keep columns that actually exist, preventing KeyError crashes.
    cols = [c for c in cols if c in df.columns]
    df = df[cols].copy()

    # Use LinkColumn so URLs are clickable.
    st.dataframe(
        df.rename(
            columns={
                "name": "Repo",
                "html_url": "Link",
                "language": "Language",
                "stargazers_count": "Stars",
                "forks_count": "Forks",
                "open_issues_count": "Open Issues",
                "days_since_push": "Days Since Push",
                "archived": "Archived",
            }
        ),
        column_config={"Link": st.column_config.LinkColumn("Link")},
        use_container_width=True,
        hide_index=True,
    )


# ----------------------------
# Languages
# ----------------------------
with tabs[2]:
    st.header("Language Distribution")

    # top_languages returns a list like: [{"language": "Python", "repo_count": 3}, ...]
    langs = top_languages(repos, n=25)

    # Bar chart expects a mapping: label -> value.
    if langs:
        st.bar_chart({row["language"]: row["repo_count"] for row in langs})
    else:
        st.info("No language data available.")


# ----------------------------
# LLM Review + Scoring
# ----------------------------
with tabs[3]:
    st.header("LLM Review + Scoring")

    # Build repo names list for the selectbox dropdown.
    repo_names = sorted([r.get("name") for r in repos if r.get("name")])

    # The user chooses a repo here; Streamlit stores it in selected_repo.
    selected_repo = st.selectbox("Select a repo", repo_names)

    # Two-column layout for "Run" button and "debug" checkbox.
    colA, colB = st.columns([1, 1])
    with colA:
        run_one = st.button("Run LLM for selected repo")
    with colB:
        show_raw = st.checkbox("Show raw LLM output (debug)", value=False)

    # Single-repo LLM run
    if run_one:
        with st.spinner("Fetching repo sample and running LLM..."):
            # fetch_repo_sample returns:
            # - README text
            # - a small sample of code files
            readme_text, code_files = fetch_repo_sample(username, selected_repo)

            # The cache key is based on repo identity + content.
            # If the repo does not change, we can safely reuse cached LLM results.
            cache_key = make_llm_cache_key(
                f"{username}/{selected_repo}",
                readme_text,
                code_files,
                model_name=LLM_CACHE_VERSION,
            )

            # cache_get returns the cached JSON result if it exists and is not expired.
            cached = cache_get(LLM_CACHE_DIR, cache_key, ttl_minutes=int(llm_cache_minutes)) if use_llm_cache else None

            if cached is not None:
                result = cached
                st.success("Loaded from LLM cache.")
            else:
                # analyze_repo_quality_with_llm returns (result_dict, error_string)
                result, err = analyze_repo_quality_with_llm(
                    repo_full_name=f"{username}/{selected_repo}",
                    readme_text=readme_text,
                    code_files=code_files,
                )

                # If the provider failed, stop so we don’t show empty UI.
                if err:
                    st.error(err)
                    st.stop()

                # Save successful results into cache if enabled.
                if use_llm_cache and result is not None:
                    cache_set(LLM_CACHE_DIR, cache_key, result)
                    st.success("Saved to LLM cache.")

        # Display LLM outputs
        st.subheader("Repo Summary")
        st.write(result.get("repo_summary", ""))

        # LLM score with tooltip
        st.metric("LLM Skill", result.get("skill_score") or 0, help=TOOLTIPS["LLM Skill"])

        st.subheader("Strengths")
        strengths = result.get("strengths", []) or []
        if strengths:
            for s in strengths:
                st.write(f"- {s}")
        else:
            st.info("No strengths returned.")

        st.subheader("Weaknesses")
        weaknesses = result.get("weaknesses", []) or []
        if weaknesses:
            for w in weaknesses:
                st.write(f"- {w}")
        else:
            st.info("No weaknesses returned.")

        st.subheader("Suggested Improvements")
        improvements = result.get("suggested_improvements", []) or []
        if improvements:
            for i in improvements:
                st.write(f"- {i}")
        else:
            st.info("No improvements returned.")

        # Debug feature: show raw model output for troubleshooting.
        if show_raw:
            st.subheader("Raw Output")
            st.code(result.get("raw_output", ""), language="text")

    st.divider()
    st.subheader("Batch LLM Scoring (Most recent repos)")

    # Batch scoring runs over N repos (chosen in sidebar).
    if score_btn:
        results = []

        with st.spinner("Running LLM scoring across repos..."):
            # I score the most recent repos first because those are likely most relevant.
            for r in repos[: int(repos_to_score)]:
                repo_name = r.get("name")
                if not repo_name:
                    continue

                # Find the row data corresponding to this repo name.
                row = next((x for x in repo_rows if x.get("name") == repo_name), None)
                if row is None:
                    continue

                readme_text, code_files = fetch_repo_sample(username, repo_name)

                cache_key = make_llm_cache_key(
                    f"{username}/{repo_name}",
                    readme_text,
                    code_files,
                    model_name=LLM_CACHE_VERSION,
                )

                cached = cache_get(LLM_CACHE_DIR, cache_key, ttl_minutes=int(llm_cache_minutes)) if use_llm_cache else None

                if cached is not None:
                    llm_result = cached
                else:
                    llm_result, err = analyze_repo_quality_with_llm(
                        repo_full_name=f"{username}/{repo_name}",
                        readme_text=readme_text,
                        code_files=code_files,
                    )

                    # If the LLM fails, I store an error object instead of crashing the batch run.
                    if err:
                        llm_result = {
                            "repo_summary": "",
                            "strengths": [],
                            "weaknesses": [],
                            "suggested_improvements": [],
                            "skill_score": None,
                            "notes": f"LLM error: {err}",
                            "raw_output": "",
                        }

                    # Cache even error responses so I don’t spam the provider on repeated runs.
                    if use_llm_cache and llm_result is not None:
                        cache_set(LLM_CACHE_DIR, cache_key, llm_result)

                # Combine LLM skill score with hard/activity/popularity/health scores.
                combined = combined_repo_score(row, llm_skill_score=llm_result.get("skill_score"))

                # Store both numeric scores and LLM text output for UI.
                results.append(
                    {
                        "repo": repo_name,
                        "url": row.get("html_url", ""),
                        "language": row.get("language", ""),
                        "total_score": combined.get("total_score"),
                        "llm_skill_score": combined.get("llm_skill_score"),
                        "hard_score": combined.get("hard_score"),
                        "activity_score": combined.get("activity_score"),
                        "popularity_score": combined.get("popularity_score"),
                        "health_score": combined.get("health_score"),
                        "strengths": llm_result.get("strengths", []),
                        "weaknesses": llm_result.get("weaknesses", []),
                        "notes": llm_result.get("notes", ""),
                    }
                )

        # Save results to session state so other tabs can use them.
        st.session_state["scores"] = results
        st.session_state["portfolio_summary"] = None

        # Persist batch run to SQLite database so it shows in History tab.
        init_db()
        run_id = create_run(username, repo_count=len(repos))
        for row in results:
            save_repo_score(run_id, row)

        st.session_state["last_run_id"] = run_id
        st.success(f"Scoring complete. Saved run_id={run_id} to SQLite (github.db).")

    # If we have scores, display score tables and per-repo breakdown.
    scores = st.session_state["scores"]
    if scores:
        st.subheader("Per-Repo Scores (click link)")
        df_scores = pd.DataFrame(scores)

        st.dataframe(
            df_scores[
                [
                    "repo",
                    "url",
                    "language",
                    "total_score",
                    "llm_skill_score",
                    "hard_score",
                    "activity_score",
                    "popularity_score",
                    "health_score",
                ]
            ].rename(
                columns={
                    "repo": "Repo",
                    "url": "Link",
                    "language": "Language",
                    "total_score": "Total",
                    "llm_skill_score": "LLM Skill",
                    "hard_score": "Hard",
                    "activity_score": "Activity",
                    "popularity_score": "Popularity",
                    "health_score": "Health",
                }
            ),
            column_config={"Link": st.column_config.LinkColumn("Link")},
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Per-Repo LLM Breakdown")
        st.caption(
            "Score meanings: Hard = engineering depth signals, Activity = recency, Popularity = stars/forks, Health = hygiene."
        )

        # Expanders let the user open each repo to see detailed results.
        for r in scores:
            title = f"{r.get('repo')} | Total={r.get('total_score')} | LLM={r.get('llm_skill_score')}"
            with st.expander(title):
                # For each repo, I show metrics with tooltips so the meaning is visible on hover.
                a, b, c, d, e, f = st.columns(6)
                a.metric("Total", r.get("total_score"), help=TOOLTIPS["Total"])
                b.metric("LLM Skill", r.get("llm_skill_score"), help=TOOLTIPS["LLM Skill"])
                c.metric("Hard", r.get("hard_score"), help=TOOLTIPS["Hard"])
                d.metric("Activity", r.get("activity_score"), help=TOOLTIPS["Activity"])
                e.metric("Popularity", r.get("popularity_score"), help=TOOLTIPS["Popularity"])
                f.metric("Health", r.get("health_score"), help=TOOLTIPS["Health"])

                st.write("**Strengths**")
                strengths = r.get("strengths", []) or []
                if strengths:
                    for s in strengths:
                        st.write(f"- {s}")
                else:
                    st.write("- (none returned)")

                st.write("**Weaknesses**")
                weaknesses = r.get("weaknesses", []) or []
                if weaknesses:
                    for w in weaknesses:
                        st.write(f"- {w}")
                else:
                    st.write("- (none returned)")

                notes = r.get("notes", "")
                if notes:
                    st.caption(notes)


# ----------------------------
# History (SQLite)
# ----------------------------
with tabs[4]:
    st.header("History (SQLite)")

    # init_db ensures tables exist, even on a fresh install.
    init_db()

    # get_recent_runs loads the most recent scoring runs saved in github.db
    runs = get_recent_runs(limit=10)

    if not runs:
        st.info("No saved runs yet. Run batch scoring to create one.")
    else:
        # Convert to DataFrame for display.
        runs_df = pd.DataFrame(runs, columns=["created_at", "username", "repo_count", "run_id"])
        st.dataframe(runs_df, use_container_width=True, hide_index=True)

        # Selectbox to view historical runs by run_id.
        run_ids = runs_df["run_id"].tolist()
        chosen_run = st.selectbox("View run_id", run_ids)

        if chosen_run:
            # Load all repo score rows from that run.
            rows = get_run_repo_scores(chosen_run)

            hist_df = pd.DataFrame(
                rows,
                columns=[
                    "repo",
                    "url",
                    "language",
                    "total_score",
                    "llm_skill_score",
                    "hard_score",
                    "activity_score",
                    "popularity_score",
                    "health_score",
                    "strengths",
                    "weaknesses",
                    "notes",
                ],
            )

            st.dataframe(
                hist_df.rename(columns={"url": "Link"}),
                column_config={"Link": st.column_config.LinkColumn("Link")},
                use_container_width=True,
                hide_index=True,
            )