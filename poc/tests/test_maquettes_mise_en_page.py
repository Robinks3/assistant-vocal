"""Les maquettes du client web ne doivent présenter aucune superposition ni défaut de mise en page.

Lance `poc/outils/verifier_mise_en_page.py` sur docs/maquettes/client-web/*.html (Chrome sans fenêtre, 360,
390 et 430 de large, thèmes clair et sombre). Le test est ignoré quand Chrome est absent.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
OUTIL = RACINE / "poc" / "outils" / "verifier_mise_en_page.py"
PAGES = RACINE / "docs" / "maquettes" / "client-web"

sys.path.insert(0, str(OUTIL.parent))
import verifier_mise_en_page as outil  # noqa: E402


def test_les_maquettes_existent():
    assert len(list(PAGES.glob("*.html"))) == 19


def test_maquettes_sans_defaut_de_mise_en_page():
    if outil.trouver_chrome() is None:
        pytest.skip("Chrome est absent : contrôle de mise en page impossible")
    res = subprocess.run(
        [sys.executable, "-X", "utf8", str(OUTIL), str(PAGES)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert res.returncode == 0, f"défauts de mise en page (code {res.returncode}) :\n{res.stdout}\n{res.stderr}"
