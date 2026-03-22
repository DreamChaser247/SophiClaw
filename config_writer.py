"""
config_writer.py — safe, targeted rewrites of config.py variables

One generic function handles all types: str, int, bool, list.
Only the targeted assignment is touched — everything else stays intact.
Existing alignment/padding is preserved for each key.
"""

import re
import logging
import importlib
from pathlib import Path

log = logging.getLogger("sophiclaw.config_writer")

CONFIG_PATH = Path("config.py")


# ── core read / write ──────────────────────────────────────────────

def get_value(key: str):
    """Read any variable from config.py. Returns None if not found."""
    try:
        import config  # type: ignore
        importlib.reload(config)
        return getattr(config, key, None)
    except Exception as e:
        log.warning("Could not read %s from config: %s", key, e)
        return None


def set_value(key: str, value) -> None:
    """
    Overwrite the assignment `KEY = ...` in config.py.

    Handles all Python literal types:
      str   ->  KEY = "value"
      int   ->  KEY = 42
      bool  ->  KEY = True
      list  ->  KEY = ["a"]          (single item: one line)
                KEY = [              (multiple items: multi-line)
                    "a",
                    "b",
                ]

    Existing whitespace between KEY and = is preserved.
    Appends the assignment if the key isn't present in the file.
    """
    content = CONFIG_PATH.read_text(encoding="utf-8")

    # Find the existing padding (spaces between key and =) so we preserve alignment.
    # e.g. "VISION_ENABLED           = True" -> padding is "           "
    pad_match = re.search(rf'^{re.escape(key)}(\s*)=', content, re.MULTILINE)
    padding = pad_match.group(1) if pad_match else " " * max(1, 25 - len(key))

    new_line = _format_assignment(key, padding, value)

    # Replace multi-line list first (KEY<pad>= [\n...\n])
    ml_pattern = rf'^{re.escape(key)}\s*=\s*\[.*?\]'
    content, n = re.subn(ml_pattern, new_line, content,
                         flags=re.MULTILINE | re.DOTALL)
    if not n:
        # Single-line assignment
        sl_pattern = rf'^{re.escape(key)}\s*=\s*[^\n]+'
        content, n = re.subn(sl_pattern, new_line, content, flags=re.MULTILINE)
    if not n:
        # Key not present — append with default padding
        content = content.rstrip("\n") + f"\n{new_line}\n"

    CONFIG_PATH.write_text(content, encoding="utf-8")
    log.info("config.py: %s = %r", key, value)


def _format_assignment(key: str, padding: str, value) -> str:
    """Return the full assignment line(s) for a key/value pair."""
    prefix = f"{key}{padding}="
    if isinstance(value, list):
        if len(value) == 1:
            return f'{prefix} "{value[0]}"'
        items = ",\n    ".join(f'"{v}"' for v in value)
        return f"{prefix} [\n    {items},\n]"
    if isinstance(value, bool):
        # bool must come before int — bool is a subclass of int in Python
        return f"{prefix} {value}"
    if isinstance(value, int):
        return f"{prefix} {value}"
    # str (default)
    return f'{prefix} "{value}"'


# ── typed convenience wrappers ─────────────────────────────────────

def get_model_list() -> list[str]:
    val = get_value("MODEL")
    if val is None:
        return []
    return [val] if isinstance(val, str) else list(val)


def add_model(model: str) -> list[str]:
    current = get_model_list()
    if model not in current:
        current.append(model)
        set_value("MODEL", current)
    return current


def remove_models(to_remove: list[str]) -> list[str]:
    current = get_model_list()
    updated = [m for m in current if m not in to_remove]
    if not updated:
        raise ValueError("Nie można usunąć wszystkich modeli — musi pozostać przynajmniej jeden")
    set_value("MODEL", updated)
    return updated
