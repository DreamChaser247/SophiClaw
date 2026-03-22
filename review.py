"""
review.py — SophiClaw longitudinal progress review & shadow notes

Public API:
  run_review(db, llm_adapter) -> str
  read_current_summary() -> tuple[str, str] | None
  run_shadow(db, llm_adapter, state, review_every_n)
  end_session(db, llm_adapter, state, review_every_n)
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import prompts

log = logging.getLogger("sophiclaw.review")

SUMMARY_PATH = Path("progress_summary.md")


def _build_review_input(db) -> str:
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


async def run_review(db, llm_adapter, user_id: int = None) -> str:
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
    summary = await llm_adapter.send_shadow(messages, user_id=user_id, db=db)

    if summary.startswith("❌"):
        log.error("Review LLM call failed: %s", summary)
        return summary

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    file_content = f"# Podsumowanie postępów\n_Wygenerowano: {timestamp}_\n\n{summary}\n"
    SUMMARY_PATH.write_text(file_content, encoding="utf-8")
    log.info("Progress summary written to %s", SUMMARY_PATH)

    return summary


def read_current_summary() -> tuple[str, str | None] | None:
    """
    Read progress_summary.md.
    Returns (body, timestamp_line) or None if the file doesn't exist.
    """
    if not SUMMARY_PATH.exists():
        return None
    text = SUMMARY_PATH.read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    # Skip header lines (# title and _timestamp_)
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("#") or line.startswith("_"):
            start = i + 1
        else:
            break
    body = "\n".join(lines[start:]).strip()
    timestamp_line = next((l for l in lines if l.startswith("_")), None)
    return body, timestamp_line


async def _maybe_auto_review(db, llm_adapter, review_every_n: int) -> None:
    if review_every_n <= 0:
        return
    total = db.get_summary_stats().get("total_sessions", 0)
    if total > 0 and total % review_every_n == 0:
        log.info("Auto-review triggered at %d sessions", total)
        await run_review(db, llm_adapter)


async def run_shadow(db, llm_adapter, state: dict, review_every_n: int = 5, user_id: int = None) -> None:
    """
    Run shadow analysis after a session ends:
      1. JSON scoring of attempts
      2. Descriptive note about understanding
      3. Auto-review if N sessions reached
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
    json_text = await llm_adapter.send_shadow(s1_msgs, user_id=user_id, db=db)
    try:
        clean = json_text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        for item in json.loads(clean):
            db.add_attempt(
                session_id = sid,
                topic_code = item.get("topic", "UNKNOWN"),
                difficulty = max(1, min(6, int(item.get("difficulty", 3)))),
                score      = max(0, min(6, int(item.get("score", 3)))),
                llm_json   = json.dumps(item, ensure_ascii=False),
            )
    except Exception as e:
        log.warning("Shadow 1 parse error: %s", e)

    # Shadow 2 — descriptive note
    s2_msgs = [
        {"role": "system", "content": "Jesteś analitykiem postępów ucznia."},
        {"role": "user",   "content": f"{prompts.SHADOW_NOTES_PROMPT}\n\nSESJA:\n{transcript}"},
    ]
    note = await llm_adapter.send_shadow(s2_msgs, user_id=user_id, db=db)
    if note and not note.startswith("❌"):
        db.add_note(sid, note.strip())

    db.mark_shadow_done(sid)
    db.end_session(sid)
    log.info("Shadow done for session %s", sid)

    await _maybe_auto_review(db, llm_adapter, review_every_n)


async def end_session(db, llm_adapter, state: dict, review_every_n: int = 5, user_id: int = None) -> None:
    """End a session — currently identical to run_shadow, kept separate for clarity."""
    await run_shadow(db, llm_adapter, state, review_every_n, user_id)