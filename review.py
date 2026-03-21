"""
review.py — SophiClaw longitudinal progress review & shadow notes

Collects the last 50-100 session notes + per-topic stats,
sends them to the LLM, and writes a concise summary to
progress_summary.md.

Also handles shadow notes (post-session analysis) and auto-review triggering.

Called by:
  - /summarise command  (generates + returns text for Discord)
  - auto-trigger in sophiclaw.py every REVIEW_EVERY_N_SESSIONS sessions (silent)
  - _run_shadow after each session completion
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import prompts

log = logging.getLogger("sophiclaw.review")

SUMMARY_PATH = Path("progress_summary.md")


def _build_review_input(db) -> str:
    """Collect notes and stats from DB into a single text block for the LLM."""
    notes  = db.get_recent_notes(100)
    topics = db.get_topic_mastery()
    stats  = db.get_summary_stats()

    lines = []

    lines.append("=== STATYSTYKI OGÓLNE ===")
    lines.append(f"Łącznie prób: {stats['total_attempts']}")
    lines.append(f"Średnia ocena: {stats['avg_score']:.1f}/6")
    lines.append(f"Liczba sesji: {stats['total_sessions']}")
    lines.append("")

    active = [t for t in topics if t.get("attempt_count")]
    if active:
        lines.append("=== OPANOWANIE TEMATÓW ===")
        for t in active:
            lines.append(
                f"  {t['name']}: {t['mastery']:.0f}% "
                f"({t['attempt_count']} prób, śr. {t['avg_score']:.1f}/6)"
            )
        lines.append("")

    if notes:
        lines.append(f"=== NOTATKI Z SESJI (ostatnie {len(notes)}) ===")
        for n in notes:
            date  = n["created_at"][:10]
            topic = f" [{n['topic_code']}]" if n.get("topic_code") else ""
            lines.append(f"  [{date}{topic}] {n['content']}")
    else:
        lines.append("=== NOTATKI Z SESJI ===")
        lines.append("  (brak notatek — uczeń nie ukończył jeszcze żadnej sesji)")

    return "\n".join(lines)


async def run_review(db, llm_adapter) -> str:
    """
    Generate a longitudinal progress summary.

    Writes progress_summary.md and returns the summary text.
    Returns an error string starting with ❌ on failure.
    """
    input_text = _build_review_input(db)

    messages = [
        {"role": "system", "content": prompts.REVIEW_PROMPT},
        {"role": "user",   "content": input_text},
    ]

    log.info("Running longitudinal review (LLM call)...")
    summary = await llm_adapter.send_shadow(messages)

    if summary.startswith("❌"):
        log.error("Review LLM call failed: %s", summary)
        return summary

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    file_content = f"# Podsumowanie postępów\n_Wygenerowano: {timestamp}_\n\n{summary}\n"
    SUMMARY_PATH.write_text(file_content, encoding="utf-8")
    log.info("Progress summary written to %s", SUMMARY_PATH)

    return summary


def read_current_summary() -> str | None:
    """
    Read progress_summary.md and return its content, or None if it doesn't exist.
    Strips the markdown heading line so Discord output is clean.
    """
    if not SUMMARY_PATH.exists():
        return None
    text = SUMMARY_PATH.read_text(encoding="utf-8").strip()
    # Remove the first two header lines (# title + _timestamp_) for Discord display
    lines = text.splitlines()
    # Find first non-empty line after the header block (skip lines starting with # or _)
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("#") or line.startswith("_"):
            start = i + 1
        else:
            break
    body = "\n".join(lines[start:]).strip()
    # Recover the timestamp line for the footer
    timestamp_line = next((l for l in lines if l.startswith("_")), None)
    return body, timestamp_line


# ── Shadow notes & auto-review ───────────────────────────────────────────

async def _run_shadow(db, llm_adapter, state: dict, review_every_n: int = 5) -> None:
    """
    Run shadow analysis after session completion.
    - Scores each attempt (JSON format)
    - Generates descriptive notes
    - Triggers auto-review if needed
    
    Args:
        db: Database instance
        llm_adapter: LLM adapter instance
        state: Session state dictionary
        review_every_n: Trigger auto-review every N sessions (0 to disable)
    """
    sid     = state["session_id"]
    history = state.get("history", [])
    if not history:
        return

    transcript = "\n".join(
        f"{m['role'].upper()}: " +
        (m["content"] if isinstance(m["content"], str) else "[multimodal]")
        for m in history
    )

    # Shadow 1 — JSON scoring
    s1_msgs = [
        {"role": "system", "content": "Odpowiadaj TYLKO w formacie JSON, bez żadnego innego tekstu."},
        {"role": "user",   "content": f"{prompts.SHADOW_SCORING_PROMPT}\n\nSESJA:\n{transcript}"},
    ]
    json_text = await llm_adapter.send_shadow(s1_msgs)
    try:
        clean = json_text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        for item in json.loads(clean):
            db.add_attempt(
                session_id  = sid,
                topic_code  = item.get("topic", "UNKNOWN"),
                difficulty  = max(1, min(6, int(item.get("difficulty", 3)))),
                score       = max(0, min(6, int(item.get("score", 3)))),
                llm_json    = json.dumps(item, ensure_ascii=False),
            )
    except Exception as e:
        log.warning("Shadow 1 parse error: %s", e)

    # Shadow 2 — descriptive note
    s2_msgs = [
        {"role": "system", "content": "Jesteś analitykiem postępów ucznia."},
        {"role": "user",   "content": f"{prompts.SHADOW_NOTES_PROMPT}\n\nSESJA:\n{transcript}"},
    ]
    note = await llm_adapter.send_shadow(s2_msgs)
    if note and not note.startswith("❌"):
        db.add_note(sid, note.strip())

    db.mark_shadow_done(sid)
    db.end_session(sid)
    log.info("Shadow done for session %s", sid)

    # Auto-review every N completed sessions (silent — just writes the file)
    await _maybe_auto_review(db, llm_adapter, review_every_n)


async def _end_session(db, llm_adapter, state: dict, review_every_n: int = 5) -> None:
    """Alias used by timeout checker — same as _run_shadow."""
    await _run_shadow(db, llm_adapter, state, review_every_n)


async def _maybe_auto_review(db, llm_adapter, review_every_n: int = 5) -> None:
    """Run a silent longitudinal review every REVIEW_EVERY_N sessions."""
    if review_every_n <= 0:
        return
    total = db.get_summary_stats().get("total_sessions", 0)
    if total > 0 and total % review_every_n == 0:
        log.info("Auto-review triggered at %d sessions", total)
        await run_review(db, llm_adapter)   # writes file, no Discord message
