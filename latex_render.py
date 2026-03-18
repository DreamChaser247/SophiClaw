"""
latex_render.py — SophiClaw LaTeX renderer

Parses [LaTeX]...[/LaTeX] tags from LLM output.
- Complex formulas (fractions, binomials, sums…) → PNG via matplotlib mathtext
- Simple formulas (x², n=11…) → unicode inline text
Works fully offline, no external API needed.
"""

import io
import re
import logging
from typing import Optional

log = logging.getLogger("sophiclaw.latex")

_TAG_RE = re.compile(r'\[LaTeX\](.*?)\[/LaTeX\]', re.DOTALL | re.IGNORECASE)

# Presence of any of these → render as image
_COMPLEX = (
    r'\frac', r'\binom', r'\sum', r'\int', r'\prod',
    r'\sqrt', r'\lim', r'\partial', r'\begin', r'\end',
    r'\vec', r'\overline', r'\underline',
    r'\overbrace', r'\underbrace',
    r'_{', r'^{',
)

# ── Unicode conversion for simple formulas ─────────────────────────

_SUP = str.maketrans('0123456789ni+-abcde', '⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱ⁺⁻ᵃᵇᶜᵈᵉ')
_SUB = str.maketrans('0123456789nikjmabcde', '₀₁₂₃₄₅₆₇₈₉ₙᵢₖⱼₘₐᵦ꜀ᵈₑ')

_SIMPLE_SUBS = [
    (r'\cdot',   '·'),   (r'\times',  '×'),   (r'\div',    '÷'),
    (r'\neq',    '≠'),   (r'\leq',    '≤'),   (r'\geq',    '≥'),
    (r'\approx', '≈'),   (r'\infty',  '∞'),   (r'\pm',     '±'),
    (r'\in',     '∈'),   (r'\notin',  '∉'),   (r'\subset', '⊂'),
    (r'\cup',    '∪'),   (r'\cap',    '∩'),   (r'\emptyset','∅'),
    (r'\forall', '∀'),   (r'\exists', '∃'),
    (r'\wedge',  '∧'),   (r'\vee',    '∨'),   (r'\neg',    '¬'),
    (r'\alpha',  'α'),   (r'\beta',   'β'),   (r'\gamma',  'γ'),
    (r'\delta',  'δ'),   (r'\epsilon','ε'),   (r'\zeta',   'ζ'),
    (r'\eta',    'η'),   (r'\theta',  'θ'),   (r'\iota',   'ι'),
    (r'\kappa',  'κ'),   (r'\lambda', 'λ'),   (r'\mu',     'μ'),
    (r'\nu',     'ν'),   (r'\xi',     'ξ'),   (r'\pi',     'π'),
    (r'\rho',    'ρ'),   (r'\sigma',  'σ'),   (r'\tau',    'τ'),
    (r'\phi',    'φ'),   (r'\chi',    'χ'),   (r'\psi',    'ψ'),
    (r'\omega',  'ω'),
    (r'\Delta',  'Δ'),   (r'\Sigma',  'Σ'),   (r'\Pi',     'Π'),
    (r'\Omega',  'Ω'),   (r'\Gamma',  'Γ'),   (r'\Lambda', 'Λ'),
    (r'\quad',   ' '),   (r'\,',      ''),    (r'\ ',      ' '),
    (r'\left',   ''),    (r'\right',  ''),
    (r'\{',      '{'),   (r'\}',      '}'),   (r'\|',      '|'),
]


def _to_unicode(formula: str) -> str:
    text = formula.strip().strip('$').strip()
    for latex, uni in _SIMPLE_SUBS:
        text = text.replace(latex, uni)
    # ^{...} and _{...}
    text = re.sub(r'\^\{([^}]+)\}', lambda m: m.group(1).translate(_SUP), text)
    text = re.sub(r'_\{([^}]+)\}',  lambda m: m.group(1).translate(_SUB), text)
    # ^x and _x (single char)
    text = re.sub(r'\^([0-9niA-Za-z])', lambda m: m.group(1).translate(_SUP), text)
    text = re.sub(r'_([0-9niA-Za-z])',  lambda m: m.group(1).translate(_SUB), text)
    return text


# ── Matplotlib renderer ────────────────────────────────────────────

def render_latex(formula: str) -> Optional[bytes]:
    """
    Render LaTeX formula to PNG bytes using matplotlib mathtext.
    Returns None on failure — caller falls back to plain text.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib as mpl

        mpl.rcParams.update({
            'mathtext.fontset': 'cm',       # Computer Modern — classic math look
            'text.color':       '#1a1a1a',
            'figure.facecolor': 'white',
            'axes.facecolor':   'white',
        })

        fig, ax = plt.subplots(figsize=(1, 1))
        ax.set_axis_off()

        display = f'${formula.strip()}$'
        t = ax.text(0.5, 0.5, display, fontsize=18,
                    ha='center', va='center', transform=ax.transAxes)

        # Measure actual rendered size and resize figure to fit tightly
        renderer = fig.canvas.get_renderer()
        bbox = t.get_window_extent(renderer=renderer)
        pad = 16  # px padding on each side
        fig.set_size_inches(
            max((bbox.width  + pad * 2) / fig.dpi, 0.5),
            max((bbox.height + pad * 2) / fig.dpi, 0.25),
        )

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150,
                    bbox_inches='tight', pad_inches=pad / 150)
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except ImportError:
        log.warning("matplotlib not installed — LaTeX image rendering unavailable")
        return None
    except Exception as e:
        log.warning("render_latex failed for '%.80s': %s", formula, e)
        return None


# ── Public API ─────────────────────────────────────────────────────

def has_latex(text: str) -> bool:
    """Return True if text contains any [LaTeX] tags."""
    return bool(_TAG_RE.search(text))


def split_message(text: str) -> list[dict]:
    """
    Split LLM response into alternating text/latex parts.

    Returns list of dicts:
      {"type": "text",  "content": "some text"}
      {"type": "latex", "content": "\\frac{1}{2}"}   ← render as PNG
      {"type": "text",  "content": "`x²`"}            ← simple, stays as text
    """
    parts = []
    last_end = 0

    for match in _TAG_RE.finditer(text):
        before = text[last_end:match.start()]
        if before:
            parts.append({"type": "text", "content": before})

        formula = match.group(1).strip()

        if any(ind in formula for ind in _COMPLEX):
            parts.append({"type": "latex", "content": formula})
        else:
            # Simple formula — convert to unicode, wrap in backticks for Discord
            parts.append({"type": "text", "content": f"`{_to_unicode(formula)}`"})

        last_end = match.end()

    tail = text[last_end:]
    if tail:
        parts.append({"type": "text", "content": tail})

    return parts
