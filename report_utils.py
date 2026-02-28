# ALL CODE INFLUENCED BY AI 

# report_utils.py
#
# What this file is:
# This file generates a PDF report using ReportLab.
#
# Why I built it:
# A PDF export is useful because it creates a shareable “snapshot” that someone can
# download and read outside of the Streamlit app. For a professor reviewing this,
# it also demonstrates that I can work with file outputs, formatting, and basic layout logic.
#
# How it works (high level):
# - Create the reports/ folder if it doesn't exist
# - Build a filename (with timestamp so it doesn't overwrite old files)
# - Use a ReportLab canvas and manually draw lines of text from top to bottom
# - If the page fills up, start a new page
# - Save the PDF and return the file path

import os
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


# All PDFs will be saved here so the project stays organized.
REPORTS_DIR = "reports"


def ensure_reports_dir():
    """
    Create the reports/ folder if it doesn't exist.

    I keep this in a helper function so I can reuse it in other export functions,
    and so the export code doesn't crash if the folder hasn't been created yet.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)


def export_recruiter_pdf(username, summary, avg_scores, repo_rows, output_name=None):
    """
    Create a PDF report file and return the saved file path.

    Parameters:
      username (str):
        GitHub username being analyzed.
      summary (dict):
        Output of compute_summary(repos). Contains repo_count, stars, activity, etc.
      avg_scores (dict):
        Output of average_scores(scored_rows). Contains average metrics like total_score.
      repo_rows (list[dict]):
        Per-repo rows, typically from Streamlit scoring results. Must include:
        repo, url, total_score, etc.
      output_name (str | None):
        Optional filename override. If None, we generate a timestamped filename.

    Returns:
      path (str):
        Path to the saved PDF file, inside the reports/ folder.

    Notes:
      - This is a simple “manual layout” PDF, which is fine for a first version.
      - ReportLab does not auto-wrap text by default, so I clamp long strings.
      - I also include a simple page-break check so text doesn’t run off the page.
    """
    ensure_reports_dir()

    # Timestamp is used so each export has a unique filename and old reports aren't overwritten.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not output_name:
        output_name = f"{username}_recruiter_report_{timestamp}.pdf"

    path = os.path.join(REPORTS_DIR, output_name)

    # Create a new PDF canvas at letter size.
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter  # width/height in points

    # Basic layout settings (top-left-ish origin, but ReportLab uses bottom-left coordinate system)
    x = 50                 # left margin
    y = height - 50        # start near top of the page
    line = 14              # line spacing (points)

    def write(text, bold=False):
        """
        Write a single line of text to the PDF and move the cursor downward.

        Why I wrote a helper:
        - Reduces repeated font + drawString code
        - Centralizes the page-break logic
        - Keeps the main report logic clean and readable
        """
        nonlocal y

        # If we're too close to the bottom, start a new page.
        if y < 60:
            c.showPage()
            y = height - 50

        # Switch font based on "bold" flag.
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 11)

        # ReportLab drawString doesn't wrap automatically, so I clamp long strings.
        c.drawString(x, y, str(text)[:120])
        y -= line

    # ----------------------------
    # Report Content
    # ----------------------------

    # Title section
    write("GitHub Activity Analyzer — Recruiter Report", bold=True)
    write(f"Username: {username}")
    write(f"Generated: {timestamp}")
    write("")

    # Snapshot section
    # This is meant to quickly summarize the portfolio without needing deep details.
    write("Quick Snapshot", bold=True)
    write(f"Repo Count: {summary.get('repo_count', 0)}")
    write(f"Total Stars: {summary.get('total_stars', 0)}")
    write(f"Avg Stars: {round(summary.get('avg_stars', 0), 2)}")
    write(f"Active Repos (90d): {summary.get('active_90d', 0)}")
    write("")

    # Score averages section
    # This summarizes the "scored repos" snapshot from the LLM scoring results.
    write("Combined Scores (Averages across scored repos)", bold=True)
    if avg_scores:
        write(f"Avg Total Score: {avg_scores.get('total_score')}")
        write(f"Avg LLM Skill Score: {avg_scores.get('llm_skill_score')}")
        write(f"Avg Hard Score: {avg_scores.get('hard_score')}")
        write(f"Avg Activity Score: {avg_scores.get('activity_score')}")
        write(f"Avg Popularity Score: {avg_scores.get('popularity_score')}")
        write(f"Avg Health Score: {avg_scores.get('health_score')}")
    else:
        write("No scored repos available yet.")
    write("")

    # Top repos section (table-ish format)
    write("Top Repos (by Total Score)", bold=True)

    if repo_rows:
        # Sort by total_score descending and keep the top 10.
        top = sorted(repo_rows, key=lambda r: (r.get("total_score") or 0), reverse=True)[:10]

        for r in top:
            name = r.get("repo", "")
            total = r.get("total_score", "")
            url = r.get("url", "")

            # I write repo name + score, then URL on the next line.
            write(f"{name} | total={total}")
            write(f"{url}")
            write("")  # blank line for spacing
    else:
        write("No repo rows available.")
        write("")

    # Save and close the PDF file.
    c.save()
    return path