"""Enforce the two colour rules of the TUI design system.

A rule nothing executes is a suggestion. These two are the ones that silently break a
screen on somebody else's terminal, so they are a test rather than a paragraph.
"""

from __future__ import annotations

from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
STYLED_DIRS = [REPO_ROOT / "vibe" / "cli" / "textual_ui" / "screens" / "usage"]

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
BRAND_DECLARATION = re.compile(r"^\s*\$mistral_orange:\s*#FF8205;\s*$")
MUTED = re.compile(r"^\s*color:\s*\$(text-muted|text-disabled|foreground-muted)\b")


def _tcss_files() -> list[Path]:
    return sorted(path for d in STYLED_DIRS for path in d.rglob("*.tcss"))


def test_no_literal_colours() -> None:
    """Only the brand declaration may carry a hex value.

    Every other colour comes from the theme, because the palette belongs to
    textual.theme.BUILTIN_THEMES and a literal is wrong in some theme.
    """
    offenders: list[str] = []
    for path in _tcss_files():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if BRAND_DECLARATION.match(line):
                continue
            if HEX.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, "hardcoded colours found:\n" + "\n".join(offenders)


def test_muted_rules_have_an_ansi_branch() -> None:
    """A muted colour needs a dim fallback.

    The ansi themes map onto the terminal's own sixteen colours and have no muted
    colour at all, so without `&:ansi { text-style: dim; }` the hierarchy collapses to
    one weight.
    """
    offenders: list[str] = []
    for path in _tcss_files():
        lines = path.read_text().splitlines()
        for number, line in enumerate(lines):
            if not MUTED.match(line):
                continue
            window = "\n".join(lines[number : number + 8])
            if "&:ansi" not in window:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{number + 1}: {line.strip()}"
                )
    assert not offenders, (
        "muted colour without an :ansi dim fallback:\n" + "\n".join(offenders)
    )
