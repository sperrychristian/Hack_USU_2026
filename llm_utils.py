# ALL CODE INFLUENCED BY AI 

# llm_utils.py
#
# Purpose:
# This file is my "LLM analysis" layer.
# It takes a small sample of a GitHub repository (README + a few code files),
# sends it to an LLM (Groq), and returns structured, recruiter-friendly insights.
#
# Why I put this in its own file:
# - app.py stays focused on Streamlit UI
# - analytics/scoring stay deterministic (math-based)
# - this file handles non-deterministic / external API behavior (LLM calls)
#
# Key design choices I made:
# 1) I REQUIRE an API key from environment variables (never hard-code keys)
# 2) I clean repo samples to reduce token usage and avoid minified files
# 3) I force the model to return JSON only, then I parse and validate it
# 4) I retry a few times because LLM APIs can fail or return messy outputs
# 5) I clamp scores to 0–100 so the UI and database don't break

import os
import json
import time
import re
from groq import Groq


# I store secrets like API keys as environment variables, not in code.
# In Codespaces, I add these in the Secrets panel.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Allow model to be overridden for testing, but default to a fast/cheap one.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")


def _require_key():
    """
    Guardrail:
    If the key is missing, return a friendly error message (not an exception).
    This keeps Streamlit from crashing and makes debugging obvious.
    """
    if not GROQ_API_KEY:
        return "Missing GROQ_API_KEY. Add it to Codespaces secrets and rebuild/restart."
    return None


def _looks_minified(text):
    """
    Heuristic to skip minified/bundled JS:
    If any line is extremely long (ex: 500+ chars), it's likely minified.
    Minified files waste tokens and don't provide useful quality signals.
    """
    if not text:
        return False
    lines = text.splitlines()
    if not lines:
        return False
    return max(len(line) for line in lines) > 500


def _clean_repo_sample(readme_text, code_files):
    """
    Reduce the size of what I send to the LLM (saves money + avoids context limits).

    Plan:
    - Keep up to 2000 chars of README
    - Keep up to 4 code/text files
    - Skip minified files
    - Cap each file at 2000 chars
    """
    readme = (readme_text or "")[:2000]

    keep = []
    for f in (code_files or []):
        path = (f.get("path") or "").lower()
        content = f.get("content") or ""

        # Skip minified output because it isn't readable and wastes tokens.
        if _looks_minified(content):
            continue

        # Only keep relevant file types (my goal: show structure + code quality quickly)
        if path.endswith((".py", ".js", ".ts", ".md", ".txt", ".json", ".yml", ".yaml")) or path in (
            "requirements.txt",
            "package.json",
        ):
            keep.append({"path": f.get("path", ""), "content": content[:2000]})

        # Stop early so I don't blow up prompt size.
        if len(keep) >= 4:
            break

    return readme, keep


def _extract_json(text):
    """
    Parse JSON from the model output.

    Why this exists:
    LLMs sometimes add markdown fences like ```json ... ```
    or extra commentary, even when instructed not to.
    I do a best-effort extraction:
      1) remove markdown fences
      2) try json.loads directly
      3) if that fails, regex-search for the first {...} block and parse that
    """
    if not text:
        raise ValueError("Empty response")

    cleaned = text.strip()

    # Remove common markdown wrappers.
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    # First attempt: parse directly.
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Second attempt: find a JSON object inside the text.
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model output.")

    candidate = m.group(0)
    return json.loads(candidate)


def _clamp_score(x):
    """
    Convert any model-provided score into a safe integer in [0, 100].
    If parsing fails, return None (caller decides how to handle).
    """
    try:
        n = int(x)
    except Exception:
        return None
    if n < 0:
        n = 0
    if n > 100:
        n = 100
    return n


def analyze_repo_quality_with_llm(repo_full_name, readme_text, code_files):
    """
    Evaluate a SINGLE repo using the LLM.

    Returns: (result_dict, error_string)

    result_dict keys:
      repo_summary: short summary of what the repo does
      strengths: 3 bullets
      weaknesses: 3 bullets
      suggested_improvements: 3 bullets
      skill_score: integer 0-100
      notes: short cautionary note about evidence limits
      raw_output: the model output (debugging)

    Error handling:
    - Missing key returns (None, message)
    - LLM failures retry up to 3 times with exponential backoff
    - If still failing, return (None, detailed message)
    """
    err = _require_key()
    if err:
        return None, err

    # I intentionally send only a small sample to control token usage.
    readme, files = _clean_repo_sample(readme_text, code_files)

    # Important: this prompt is strict about JSON so the UI can rely on it.
    prompt = f"""
You are a senior software engineer evaluating a GitHub repo for recruiter-facing insight.
Only use the README + file samples below. Do not invent details.

Return ONLY valid JSON (no markdown, no extra text).
The JSON MUST have exactly these keys:
- repo_summary (string, <= 220 chars)
- strengths (array of 3 strings)
- weaknesses (array of 3 strings)
- suggested_improvements (array of 3 strings)
- skill_score (integer 0-100)
- notes (string, <= 220 chars)

Repo: {repo_full_name}

README:
{readme}

FILES (sample):
{files}
""".strip()

    # Create the Groq client once for this call.
    client = Groq(api_key=GROQ_API_KEY)

    last_error = None
    last_raw = ""

    # Retry loop: LLM APIs can fail or return malformed data occasionally.
    for attempt in range(1, 4):
        try:
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    # System message sets behavior constraints very strongly.
                    {"role": "system", "content": "You return only valid JSON. No markdown. No commentary."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,  # low randomness so output is consistent
                max_tokens=900,   # enough room for the JSON payload
            )

            raw = (resp.choices[0].message.content or "").strip()
            last_raw = raw

            # Parse JSON and validate shapes.
            data = _extract_json(raw)

            repo_summary = str(data.get("repo_summary", ""))[:220]
            strengths = data.get("strengths", []) or []
            weaknesses = data.get("weaknesses", []) or []
            improvements = data.get("suggested_improvements", []) or []
            notes = str(data.get("notes", ""))[:220]
            score = _clamp_score(data.get("skill_score"))

            # Make sure they are lists; otherwise treat as empty.
            if not isinstance(strengths, list):
                strengths = []
            if not isinstance(weaknesses, list):
                weaknesses = []
            if not isinstance(improvements, list):
                improvements = []

            # Force exactly 3 items each (predictable UI and PDF export).
            strengths = [str(x) for x in strengths][:3]
            weaknesses = [str(x) for x in weaknesses][:3]
            improvements = [str(x) for x in improvements][:3]

            # If the model didn't provide enough bullets, I fill with safe defaults.
            while len(strengths) < 3:
                strengths.append("Not enough evidence in sample to make a confident strength.")
            while len(weaknesses) < 3:
                weaknesses.append("Not enough evidence in sample to make a confident weakness.")
            while len(improvements) < 3:
                improvements.append("Add a README with setup, usage, and project goals.")

            return {
                "repo_summary": repo_summary,
                "strengths": strengths,
                "weaknesses": weaknesses,
                "suggested_improvements": improvements,
                "skill_score": score,
                "notes": notes,
                "raw_output": raw,
            }, None

        except Exception as e:
            # Save error so I can return useful information after all retries.
            last_error = repr(e)

            # Exponential backoff: 1s, 2s, 4s (helps with rate limits / transient failures).
            time.sleep(2 ** (attempt - 1))

    preview = (last_raw[:300] + "...") if last_raw else ""
    return None, f"Groq JSON parse failed after retries. Last error: {last_error}. Preview: {preview}"


def analyze_portfolio_summary(username, scored_repos):
    """
    Evaluate the ENTIRE portfolio (multiple repos) and generate a short summary.

    Input:
      scored_repos: list of dicts from app scoring:
        repo, language, total_score, strengths, weaknesses

    Returns:
      (summary_dict, error_string)

    Output keys:
      - recruiter_summary: 3-5 sentences (<= 600 chars)
      - headline: short title (<= 90 chars)
      - top_strengths: 3 bullets
      - top_risks: 3 bullets
      - raw_output: raw model output for debugging
    """
    err = _require_key()
    if err:
        return None, err

    # Keep prompt small and stable to reduce token usage.
    compact = []
    for r in scored_repos[:12]:
        compact.append({
            "repo": r.get("repo"),
            "language": r.get("language"),
            "total_score": r.get("total_score"),
            "strengths": (r.get("strengths") or [])[:2],
            "weaknesses": (r.get("weaknesses") or [])[:2],
        })

    prompt = f"""
You are writing a recruiter-facing portfolio summary based on GitHub repo evaluation results.

Return ONLY valid JSON with exactly these keys:
- recruiter_summary (string, 3-5 sentences, <= 600 chars)
- headline (string, <= 90 chars)
- top_strengths (array of 3 strings)
- top_risks (array of 3 strings)

GitHub username: {username}

Scored repo signals:
{compact}
""".strip()

    client = Groq(api_key=GROQ_API_KEY)

    last_error = None
    last_raw = ""

    for attempt in range(1, 4):
        try:
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "Return only JSON. Do not include markdown."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=600,
            )

            raw = (resp.choices[0].message.content or "").strip()
            last_raw = raw

            data = _extract_json(raw)

            summary = str(data.get("recruiter_summary", ""))[:600]
            headline = str(data.get("headline", ""))[:90]
            top_strengths = data.get("top_strengths", []) or []
            top_risks = data.get("top_risks", []) or []

            # Validate shapes and sanitize.
            if not isinstance(top_strengths, list):
                top_strengths = []
            if not isinstance(top_risks, list):
                top_risks = []

            top_strengths = [str(x) for x in top_strengths][:3]
            top_risks = [str(x) for x in top_risks][:3]

            # Fill defaults so UI always has 3 bullets.
            while len(top_strengths) < 3:
                top_strengths.append("Not enough evidence to identify a clear strength.")
            while len(top_risks) < 3:
                top_risks.append("Not enough evidence to identify a clear risk.")

            return {
                "headline": headline,
                "recruiter_summary": summary,
                "top_strengths": top_strengths,
                "top_risks": top_risks,
                "raw_output": raw,
            }, None

        except Exception as e:
            last_error = repr(e)
            time.sleep(2 ** (attempt - 1))

    preview = (last_raw[:300] + "...") if last_raw else ""
    return None, f"Portfolio summary failed after retries. Last error: {last_error}. Preview: {preview}"
    