"""README is the Free tier's front door: every site CTA for the Pi lands on it.

The 2026-10 site-copy audit found it promised an "open-source platform" with a
"real-time React dashboard" (the dashboard's source isn't here and it polls
over REST), mentioned the active species category twice with the
education-and-research notice only ~470 lines later, and gave contributors
conventions for dashboard code they can't see. These pin what it must say.
"""

import re
from pathlib import Path

from app.species.profiles import BUILTIN_PROFILES

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

# The Terms of Service §7 clause (EDUCATIONAL_USE on sporeprint.ai), quoted
# verbatim wherever the README mentions the active category.
EDUCATIONAL_USE = (
    "Some cultivation profiles in SporePrint cover species that are controlled or restricted "
    "in many jurisdictions. That information is provided for education and research purposes "
    "only. Any use of SporePrint with those species is for education and research purposes "
    "only, and only where it is lawful. It is not encouragement to cultivate, possess, or use "
    "any controlled organism. You are solely responsible for knowing and complying with the "
    "laws where you live."
)

# "active category", "active species", "25 active", "**Active** (25)" and the
# wizard's include_active switch; not "active session", "Active Cooler" etc.
_ACTIVE_CATEGORY = re.compile(
    r"\bactive (?:category|species)\b|\b\d+ active\b|\*\*Active\*\*|include_active", re.I
)


def _text() -> str:
    return README.read_text(encoding="utf-8")


def _sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) for every ## / ### section, body up to the next heading."""
    parts = re.split(r"^(#{2,3} .+)$", text, flags=re.M)
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("> ", " "))


def _between(start: str, end: str) -> str:
    """The README text from the heading line `start` up to the next heading matching `end`."""
    m = re.search(rf"^{start}$(.*?)^{end}", _text(), re.M | re.S)
    assert m, f"README has no section {start!r}"
    return m.group(1)


def test_every_section_that_mentions_the_active_category_quotes_the_notice():
    mentions = [(h, b) for h, b in _sections(_text()) if _ACTIVE_CATEGORY.search(b)]
    assert mentions, "README no longer mentions the active category: drop this check"
    missing = [h for h, b in mentions if EDUCATIONAL_USE not in _flat(b)]
    assert not missing, f"README sections mention the active category without the notice: {missing}"


def test_the_intro_mentions_the_category_only_with_the_notice():
    # Everything above the first Quick Start step is what a visitor from the
    # site reads first.
    intro = _text().split("## Quick Start", 1)[0]
    if _ACTIVE_CATEGORY.search(intro):
        assert EDUCATIONAL_USE in _flat(intro)


def test_readme_names_no_active_species():
    active = [p for p in BUILTIN_PROFILES if p.category == "active"]
    assert active
    names = {n for p in active for n in (p.common_name, p.scientific_name, p.strain) if n}
    names |= {p.scientific_name.split()[0] for p in active}
    text = _text()
    named = sorted(n for n in names if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text))
    assert not named, f"README names {len(named)} active species, strains or genera"


def test_readme_states_what_is_open_source():
    text = _text()
    flat = _flat(text)
    for overclaim in ("Open-source automated mushroom cultivation platform", "real-time React dashboard",
                      "fully open source", "fully open-source", "the whole stack"):
        assert overclaim.lower() not in flat.lower(), overclaim
    scope = _flat(_between("## Open Source", "## "))
    assert "AGPL-3.0" in scope and "pre-built bundle" in scope and "proprietary" in scope


def test_readme_gives_install_update_and_dashboard_address():
    text = _text()
    assert "curl -fsSL https://raw.githubusercontent.com/59psi/SporePrint/main/install.sh | bash" in text
    assert "cd ~/SporePrint && git pull && ./install.sh" in text
    assert "http://<pi-ip>:3001" in text
    assert "--recurse-submodules" not in text  # the repo has no submodules


def test_readme_pairing_says_a_public_https_address_is_needed():
    cloud = _flat(_between("## Cloud Connector", "## Security"))
    assert "Setup → § III Cloud link" in cloud and "Devices → Pair new device" in cloud
    assert "public HTTPS address" in cloud and "SPOREPRINT_ALLOWED_HOSTS" in cloud
    assert "mobile app is being rebuilt" not in cloud


def test_contributing_carries_no_dashboard_code_conventions():
    conventions = _between("### Code Conventions", "## ")
    assert "**Frontend**" not in conventions and "parent monorepo" not in conventions
    contributing = _flat(_between("## Contributing", "### "))
    assert "can't change the dashboard" in contributing


def test_readme_says_where_to_get_help():
    help_ = _flat(_between("## Getting Help", "## "))
    assert "https://github.com/59psi/SporePrint/issues" in help_
    assert "support@sporeprint.ai" in help_ and "Security" in help_
