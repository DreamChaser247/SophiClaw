"""
database.py — SophiClaw local SQLite layer
Single-user, all data stays on the student's machine.
"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

log = logging.getLogger("sophiclaw.db")


# ── Schema ─────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    UNIQUE NOT NULL,
    name        TEXT    NOT NULL,
    parent_id   INTEGER DEFAULT NULL,
    level       INTEGER DEFAULT 1,
    description TEXT,
    mastery     REAL    DEFAULT 0.0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_id) REFERENCES topics(id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id    INTEGER NOT NULL,
    difficulty  INTEGER NOT NULL CHECK (difficulty BETWEEN 1 AND 6),
    question    TEXT    NOT NULL,
    solution    TEXT,
    hints       TEXT,
    source      TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE TABLE IF NOT EXISTS attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER,
    topic_code      TEXT,
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_answer     TEXT,
    score           INTEGER CHECK (score BETWEEN 0 AND 6),
    difficulty      INTEGER CHECK (difficulty BETWEEN 1 AND 6),
    time_spent_sec  INTEGER,
    llm_json        TEXT,
    is_correct      BOOLEAN DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_code  TEXT,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_id  TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at    TIMESTAMP,
    turn_count  INTEGER DEFAULT 0,
    shadow_done BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_topic   ON attempts(topic_code);
CREATE INDEX IF NOT EXISTS idx_attempts_time    ON attempts(timestamp);
CREATE INDEX IF NOT EXISTS idx_notes_topic      ON notes(topic_code);
CREATE INDEX IF NOT EXISTS idx_notes_session    ON notes(session_id);
"""

# ── Seed data: Matura topic tree ───────────────────────────────────────────────

SEED_TOPICS = [
    ("LRZ",   "Liczby rzeczywiste",              None,    1, "Działania, potęgi, pierwiastki, logarytmy"),
    ("LRZ_WYR", "Wyrażenia algebraiczne",        "LRZ",   2, "Upraszczanie, wzory skróconego mnożenia"),
    ("LRZ_LOG", "Logarytmy",                     "LRZ",   2, "Definicja, własności, równania logarytmiczne"),
    ("FUNK",  "Funkcje",                          None,    1, "Pojęcie funkcji, dziedzina, własności"),
    ("FUNK_LIN", "Funkcja liniowa",              "FUNK",  2, "Postać ogólna, wykres, zastosowania"),
    ("FUNK_KWAD","Funkcja kwadratowa",            "FUNK",  2, "Postać ogólna/kanoniczna/iloczynowa, wierzchołek"),
    ("FUNK_WYK", "Funkcja wykładnicza",          "FUNK",  2, "Własności, równania, nierówności"),
    ("FUNK_TRYG","Funkcje trygonometryczne",      "FUNK",  2, "sin, cos, tan, cot — definicje, wykresy, jedynka trygonometryczna"),
    ("ROWNANIA", "Równania i nierówności",        None,    1, "Liniowe, kwadratowe, wymierne, z parametrem"),
    ("CIGI",  "Ciągi",                            None,    1, "Arytmetyczne, geometryczne, granice"),
    ("CIGI_AR",  "Ciąg arytmetyczny",            "CIGI",  2, "Różnica, suma, wzory"),
    ("CIGI_GEO", "Ciąg geometryczny",            "CIGI",  2, "Iloraz, suma, szereg geometryczny"),
    ("CIGI_GR",  "Granice ciągów",              "CIGI",  2, "Definicja, techniki wyznaczania granic"),
    ("GEOM",  "Geometria",                        None,    1, "Planimetria i stereometria"),
    ("GEOM_PLAN","Planimetria",                   "GEOM",  2, "Trójkąty, czworokąty, okrąg, twierdzenie Pitagorasa"),
    ("GEOM_WEKT","Wektory",                       "GEOM",  2, "Działania na wektorach, iloczyn skalarny"),
    ("GEOM_ANAL","Geometria analityczna",         "GEOM",  2, "Proste, okręgi, odległości na płaszczyźnie"),
    ("GEOM_STER","Stereometria",                  "GEOM",  2, "Graniastosłupy, ostrosłupy, bryły obrotowe"),
    ("RACHPRAW","Rachunek prawdopodobieństwa",    None,    1, "Prawdopodobieństwo, kombinatoryka"),
    ("RACHPRAW_KOMB","Kombinatoryka",             "RACHPRAW", 2, "Permutacje, kombinacje, wariacje"),
    ("RACHPRAW_STAT","Statystyka",               "RACHPRAW", 2, "Średnia, mediana, odchylenie, interpretacja danych"),
    ("POCHODNE","Pochodne (rozszerzenie)",        None,    1, "Definicja, reguły różniczkowania, zastosowania"),
    ("CALKI",  "Całki (rozszerzenie)",            None,    1, "Całka nieoznaczona i oznaczona, zastosowania"),
]


class Database:
    def __init__(self, db_path: str = "db/sophiclaw.db"):
        self.path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._apply_schema()
        self._seed_topics()
        log.info("Database ready at %s", self.path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if not self._conn:
            raise RuntimeError("Database.connect() not called")
        return self._conn

    # ── Schema & seed ──────────────────────────────────────────────────────────

    def _apply_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _seed_topics(self) -> None:
        """Insert default Matura topics if table is empty."""
        cur = self.conn.execute("SELECT COUNT(*) FROM topics")
        if cur.fetchone()[0] > 0:
            return
        for code, name, parent_code, level, desc in SEED_TOPICS:
            parent_id = None
            if parent_code:
                row = self.conn.execute(
                    "SELECT id FROM topics WHERE code=?", (parent_code,)
                ).fetchone()
                parent_id = row["id"] if row else None
            self.conn.execute(
                "INSERT OR IGNORE INTO topics (code,name,parent_id,level,description) VALUES (?,?,?,?,?)",
                (code, name, parent_id, level, desc),
            )
        self.conn.commit()
        log.info("Seeded %d topics", len(SEED_TOPICS))

    # ── Sessions ───────────────────────────────────────────────────────────────

    def create_session(self, session_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO sessions (id) VALUES (?)", (session_id,)
        )
        self.conn.commit()

    def end_session(self, session_id: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET ended_at=CURRENT_TIMESTAMP WHERE id=?",
            (session_id,),
        )
        self.conn.commit()

    def increment_turns(self, session_id: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET turn_count=turn_count+1 WHERE id=?",
            (session_id,),
        )
        self.conn.commit()

    def mark_shadow_done(self, session_id: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET shadow_done=1 WHERE id=?", (session_id,)
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()

    # ── Attempts ───────────────────────────────────────────────────────────────

    def add_attempt(
        self,
        topic_code: str,
        score: int,
        difficulty: int,
        llm_json: Optional[str] = None,
        task_id: Optional[int] = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO attempts
               (task_id, topic_code, score, difficulty, llm_json, is_correct)
               VALUES (?,?,?,?,?,?)""",
            (task_id, topic_code, score, difficulty, llm_json, 1 if score >= 4 else 0),
        )
        self._update_mastery(topic_code)
        self.conn.commit()

    def _update_mastery(self, topic_code: str) -> None:
        row = self.conn.execute(
            """SELECT AVG(CAST(score AS REAL)/6*100) as avg
               FROM attempts WHERE topic_code=?""",
            (topic_code,),
        ).fetchone()
        if row and row["avg"] is not None:
            self.conn.execute(
                "UPDATE topics SET mastery=?, last_updated=CURRENT_TIMESTAMP WHERE code=?",
                (round(row["avg"], 1), topic_code),
            )

    # ── Notes ──────────────────────────────────────────────────────────────────

    def add_note(self, content: str, session_id: str, topic_code: Optional[str] = None) -> None:
        self.conn.execute(
            "INSERT INTO notes (topic_code, content, session_id) VALUES (?,?,?)",
            (topic_code, content[:500], session_id),
        )
        self.conn.commit()

    def get_recent_notes(self, limit: int = 10) -> list:
        rows = self.conn.execute(
            "SELECT content, created_at, topic_code FROM notes ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Progress queries ───────────────────────────────────────────────────────

    def get_topic_mastery(self) -> list:
        rows = self.conn.execute(
            """SELECT t.name, t.code, t.mastery,
                      COUNT(a.id) as attempt_count,
                      AVG(a.score) as avg_score
               FROM topics t
               LEFT JOIN attempts a ON a.topic_code = t.code
               WHERE t.level = 1
               GROUP BY t.id
               ORDER BY t.mastery DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_last_attempts(self, limit: int = 10) -> list:
        rows = self.conn.execute(
            """SELECT a.timestamp, a.topic_code, t.name as topic_name,
                      a.score, a.difficulty
               FROM attempts a
               LEFT JOIN topics t ON t.code = a.topic_code
               ORDER BY a.timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_summary_stats(self) -> dict:
        stats = {}
        row = self.conn.execute(
            "SELECT COUNT(*) as total, AVG(score) as avg_score FROM attempts"
        ).fetchone()
        stats["total_attempts"] = row["total"]
        stats["avg_score"] = round(row["avg_score"] or 0, 2)

        weakest = self.conn.execute(
            """SELECT t.name, t.mastery FROM topics t
               WHERE t.mastery > 0 ORDER BY t.mastery ASC LIMIT 3"""
        ).fetchall()
        stats["weakest_topics"] = [dict(r) for r in weakest]

        strongest = self.conn.execute(
            """SELECT t.name, t.mastery FROM topics t
               WHERE t.mastery > 0 ORDER BY t.mastery DESC LIMIT 3"""
        ).fetchall()
        stats["strongest_topics"] = [dict(r) for r in strongest]

        row2 = self.conn.execute(
            "SELECT COUNT(*) as c FROM sessions"
        ).fetchone()
        stats["total_sessions"] = row2["c"]
        return stats

    # ── Settings ───────────────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
            (key, value),
        )
        self.conn.commit()
