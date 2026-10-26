"""carte/3d/generer_3d.py : tourne de bout en bout sur config-exemple/ et donne deux fois la même sortie.

Le test travaille sur une copie en dossier temporaire : rien n'est écrit dans config-exemple/."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
EXEMPLE = RACINE / "config-exemple"
SCRIPT = RACINE / "carte" / "3d" / "generer_3d.py"


@pytest.fixture()
def copie(tmp_path):
    """Copie légère de la configuration d'exemple (maison.json et carte/, sans le dictionnaire généré)."""
    dest = tmp_path / "config"
    dest.mkdir()
    shutil.copy2(EXEMPLE / "maison.json", dest / "maison.json")
    shutil.copytree(EXEMPLE / "carte", dest / "carte", ignore=shutil.ignore_patterns("modele.glb"))
    return dest


def lancer(config):
    env = dict(os.environ, ASSISTANT_VOCAL_CONFIG=str(config))
    return subprocess.run([sys.executable, "-I", str(SCRIPT)], cwd=config, env=env, capture_output=True,
                          text=True, timeout=120)


def sorties(config):
    return (config / "carte" / "modele.glb", config / "genere" / "android" / "maison3d" / "vue3d.html")


def test_c11_tourne_de_bout_en_bout_sur_l_exemple(copie):
    r = lancer(copie)
    assert r.returncode == 0, r.stderr
    glb, page = sorties(copie)
    assert glb.read_bytes()[:4] == b"glTF" and glb.stat().st_size > 1000
    html = page.read_text(encoding="utf-8")
    meubles = json.loads((copie / "carte" / "meubles.json").read_text(encoding="utf-8"))
    assert meubles["version"] in html and "{{" not in html and "/*SCENE*/" not in html and "/*THREE*/" not in html
    assert "modele.glb" in r.stdout and "nœuds" in r.stdout


def test_c11_deux_executions_donnent_la_meme_sortie(copie):
    premiere = []
    for _ in range(2):
        r = lancer(copie)
        assert r.returncode == 0, r.stderr
        glb, page = sorties(copie)
        premiere.append((glb.read_bytes(), page.read_bytes()))
        shutil.rmtree(copie / "genere")
        glb.unlink()
    assert premiere[0] == premiere[1]


def test_c11_le_script_n_ecrit_que_dans_la_configuration_pointee(copie):
    avant = {p.relative_to(EXEMPLE) for p in EXEMPLE.rglob("*") if p.is_file()}
    assert lancer(copie).returncode == 0
    apres = {p.relative_to(EXEMPLE) for p in EXEMPLE.rglob("*") if p.is_file()}
    assert avant == apres


def test_c11_plan_absent_donne_un_message_clair(tmp_path):
    vide = tmp_path / "vide"
    vide.mkdir()
    shutil.copy2(EXEMPLE / "maison.json", vide / "maison.json")
    r = lancer(vide)
    assert r.returncode != 0 and "pieces.json" in r.stderr and "config-exemple/carte/" in r.stderr
