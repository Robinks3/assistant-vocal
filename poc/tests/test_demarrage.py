"""Démarrage du serveur à vide et contrôle des scripts shell (0.36.3).

Deux garanties de bout en bout, sur le dépôt seul :
- le serveur des satellites se lance sans poc/.env, sans micro, sans réseau et sans Home Assistant, écoute
  quelques secondes puis s'arrête de lui-même (le démarrage ne dépend donc d'aucune machine particulière) ;
- les scripts shell suivis par git passent shellcheck, quand l'outil est installé."""
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
HARNAIS = Path(__file__).resolve().parent / "demarrage_a_vide.py"
DUREE_ECOUTE = 4.0
DELAI_MAX = 90  # imports compris (onnxruntime, numpy), le test ne dépasse jamais ce délai

# Variables de l'environnement passées au sous-processus : le strict nécessaire pour lancer Python.
# Ni clé, ni jeton, ni réglage de l'utilisateur : le serveur démarre comme sur un poste vierge.
VARIABLES_SYSTEME = ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "TMPDIR", "LOCALAPPDATA", "APPDATA",
                     "USERPROFILE", "HOME", "COMSPEC", "PATHEXT")


def _port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _environnement(donnees):
    env = {k: os.environ[k] for k in VARIABLES_SYSTEME if k in os.environ}
    env.update({
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "ASSISTANT_VOCAL_CONFIG": str(RACINE / "config-exemple"),
        "JARVIS_DONNEES": str(donnees),
        "JARVIS_PROFIL": "ha",  # aucun modèle local à charger, comme l'appli Home Assistant
        "METEO_MER": "0",
        # Valeur fictive de test : sans jeton de 16 caractères au moins, le serveur refuse de démarrer.
        "SATELLITE_JETON": "jeton-de-test-pour-le-demarrage-a-vide",
    })
    return env


def test_le_serveur_demarre_a_vide_et_s_arrete_seul(tmp_path):
    donnees = tmp_path / "donnees"
    donnees.mkdir()
    try:
        fini = subprocess.run(
            [sys.executable, str(HARNAIS), str(_port_libre()), str(DUREE_ECOUTE)],
            cwd=tmp_path, env=_environnement(donnees), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=DELAI_MAX)
    except subprocess.TimeoutExpired as e:
        pytest.fail(f"le serveur n'a pas fini en {DELAI_MAX} s (il devait s'arrêter seul après {DUREE_ECOUTE} s) :\n"
                    f"{(e.stdout or b'')[-1500:]!r}")
    sortie = fini.stdout + fini.stderr
    if fini.returncode == 4:
        pytest.skip("module tiers absent de cet environnement Python, démarrage non vérifiable : "
                    + sortie.strip().splitlines()[-1])
    assert fini.returncode == 0, f"code {fini.returncode} :\n{sortie[-3000:]}"
    assert "DEMARRAGE_OK" in fini.stdout, sortie[-3000:]
    assert "Serveur satellite v" in fini.stdout, sortie[-3000:]
    assert "TENTATIVES_RESEAU" not in sortie
    # Le certificat du port chiffré est créé dans le dossier de données de test, jamais dans poc/.
    assert any(donnees.iterdir()), "aucun fichier de données créé (certificat du port chiffré attendu)"


def _scripts_shell():
    exclus = {".git", ".venv", "node_modules", "build", "worktrees", "config", "genere"}
    trouves = []
    for chemin in RACINE.rglob("*.sh"):
        if exclus & set(chemin.relative_to(RACINE).parts):
            continue
        trouves.append(chemin)
    trouves += [p for p in (RACINE / ".githooks").glob("*") if p.is_file() and p.suffix == ""]
    return sorted(set(trouves))


def test_les_scripts_shell_passent_shellcheck():
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck n'est pas installé (https://www.shellcheck.net), scripts shell non contrôlés")
    scripts = _scripts_shell()
    assert scripts, "aucun script shell trouvé : la recherche est cassée"
    # Erreurs seulement : les avertissements de style ne bloquent pas la suite de tests.
    fini = subprocess.run([shellcheck, "--shell=bash", "--severity=error", *map(str, scripts)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert fini.returncode == 0, fini.stdout + fini.stderr


def test_les_scripts_shell_sont_trouves():
    """La liste des scripts contrôlés contient au moins les trois scripts d'outillage connus."""
    noms = {p.name for p in _scripts_shell()}
    assert {"deployer.sh", "garde-fou.sh", "pousser_canary.sh"} <= noms


def _modules_copies_par_deployer():
    """Modules de poc/ que ha-app/deployer.sh copie dans l'appli Home Assistant (ligne cp vers $ETAPE/app/)."""
    texte = (RACINE / "ha-app" / "deployer.sh").read_text(encoding="utf-8")
    ligne = next(l for l in texte.splitlines() if l.startswith("cp ") and l.rstrip().endswith('"$ETAPE/app/"'))
    return set(re.findall(r'"\$POC/(\w+)\.py"', ligne))


def test_deployer_copie_tous_les_modules_importes():
    """Tout module de poc/ importé par un module copié est copié lui aussi (panne du 26/10 : liste_blanche.py
    oublié, l'appli HA 0.41.0 s'arrêtait au démarrage sur ModuleNotFoundError)."""
    poc = RACINE / "poc"
    copies = _modules_copies_par_deployer()
    assert {"serveur_satellite", "assistant", "acces"} <= copies, "ligne cp de deployer.sh introuvable"
    manquants = {}
    for module in sorted(copies):
        source = (poc / f"{module}.py").read_text(encoding="utf-8")
        for importe in re.findall(r"(?m)^\s*(?:import|from)\s+(\w+)", source):
            if (poc / f"{importe}.py").exists() and importe not in copies:
                manquants.setdefault(importe, []).append(module)
    assert not manquants, f"modules importés mais absents de deployer.sh : {manquants}"
