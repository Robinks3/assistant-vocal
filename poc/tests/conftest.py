import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Les tests tournent sur la configuration fictive de la maison (config-exemple/), jamais sur la vraie.
# ASSISTANT_VOCAL_CONFIG (ou MAISON_DOSSIER) déjà réglée, par exemple vers config/, est respectée : sert à rejouer
# d'anciens cas écrits avec les vrais noms (les cas d'aujourd'hui, écrits pour config-exemple/, y échouent).
if not (os.environ.get("ASSISTANT_VOCAL_CONFIG") or os.environ.get("MAISON_DOSSIER")):
    os.environ["ASSISTANT_VOCAL_CONFIG"] = str(Path(__file__).resolve().parents[2] / "config-exemple")

import pytest


@pytest.fixture(autouse=True)
def journal_musique_temporaire(tmp_path, monkeypatch):
    """Les essais de musique écrivent leur ligne de journal ailleurs que dans poc/journal."""
    import assistant
    monkeypatch.setattr(assistant, "MUSIQUE", tmp_path / "musique.jsonl")
    return tmp_path / "musique.jsonl"
