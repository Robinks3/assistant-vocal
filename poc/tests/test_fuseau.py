"""Heure de la maison (S-D1, 26/10/2026) : une seule source, maison.maintenant(), dans le fuseau de maison.json.

L'app Home Assistant et certaines machines tournent en UTC : l'heure de la machine ne doit jamais décider d'une
date, d'une heure calme ou d'un horodatage de journal."""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import maison
import securite

POC = Path(__file__).resolve().parents[1]
AUCKLAND = ZoneInfo("Pacific/Auckland")

# Lancé dans un processus neuf : le fuseau se lit à l'import de maison.py.
SONDE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import maison, sante, securite
n = maison.maintenant()
print(json.dumps({"fuseau": maison.FUSEAU, "decalage": n.utcoffset().total_seconds(), "heure": n.hour,
                  "jour": sante.date_du_jour().isoformat(), "zone": str(maison.ZONE),
                  "securite": str(securite.FUSEAU)}))
"""


def sonde(tmp_path, fuseau_config, tz_machine):
    """Résultat de la sonde avec un maison.json au fuseau voulu et l'heure de la machine réglée par TZ."""
    config = json.loads((POC.parent / "config-exemple" / "maison.json").read_text(encoding="utf-8"))
    if fuseau_config is None:
        config.pop("fuseau", None)
    else:
        config["fuseau"] = fuseau_config
    dossier = tmp_path / ("cfg-" + str(fuseau_config).replace("/", "-"))
    dossier.mkdir(exist_ok=True)
    (dossier / "maison.json").write_text(json.dumps(config), encoding="utf-8")
    env = {**os.environ, "ASSISTANT_VOCAL_CONFIG": str(dossier), "TZ": tz_machine}
    sortie = subprocess.run([sys.executable, "-I", "-c", SONDE, str(POC)], env=env, capture_output=True,
                            text=True, timeout=60, check=True)
    return json.loads(sortie.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("tz_machine", ["Europe/Paris", "America/Los_Angeles", "UTC"])
def test_pacific_auckland_independant_de_la_machine(tmp_path, tz_machine):
    """Avec fuseau = Pacific/Auckland, l'heure du moteur est celle d'Auckland quelle que soit la variable TZ."""
    avant = datetime.now(AUCKLAND)
    r = sonde(tmp_path, "Pacific/Auckland", tz_machine)
    apres = datetime.now(AUCKLAND)
    assert r["fuseau"] == "Pacific/Auckland" and r["zone"] == "Pacific/Auckland" and r["securite"] == "Pacific/Auckland"
    assert r["decalage"] == avant.utcoffset().total_seconds() in (12 * 3600, 13 * 3600)
    assert r["heure"] in (avant.hour, apres.hour)
    assert r["jour"] in (avant.date().isoformat(), apres.date().isoformat())


def test_sans_fuseau_repli_sur_utc(tmp_path):
    r = sonde(tmp_path, None, "Pacific/Auckland")
    assert r["fuseau"] == "UTC" and r["decalage"] == 0


def test_fuseau_inconnu_repli_sur_utc(tmp_path):
    r = sonde(tmp_path, "Mars/Olympus", "Pacific/Auckland")
    assert r["decalage"] == 0


def test_maintenant_suit_le_fuseau(monkeypatch):
    monkeypatch.setattr(maison, "ZONE", AUCKLAND)
    assert maison.maintenant().utcoffset() in (timedelta(hours=12), timedelta(hours=13))
    import assistant
    import sante
    assert sante.date_du_jour() == datetime.now(AUCKLAND).date()
    assert assistant.date_francaise().split(", ")[1].startswith(f"{maison.maintenant().hour} h")


def test_heure_calme_a_l_heure_de_la_maison(monkeypatch):
    """Une plage qui contient l'heure d'Auckland mais pas celle d'UTC (12 ou 13 h d'écart) refuse en Auckland
    et laisse passer en UTC : securite.verifier lit maison.maintenant(), pas l'heure de la machine."""
    monkeypatch.setattr(securite, "HEURE_CALME_ACTIVE", True)
    service, donnees = "media_player.media_play", {"entity_id": "media_player.enceintes_maison"}
    monkeypatch.setattr(maison, "ZONE", AUCKLAND)
    h = maison.maintenant().hour
    monkeypatch.setattr(securite, "HEURE_CALME_DEBUT", h)
    monkeypatch.setattr(securite, "HEURE_CALME_FIN", (h + 2) % 24)
    assert securite.verifier(service, donnees) is not None
    monkeypatch.setattr(maison, "ZONE", ZoneInfo("UTC"))
    assert securite.verifier(service, donnees) is None


def test_horodatage_sans_decalage():
    """Les journaux gardent la forme naïve d'avant (l'appli Android l'affiche et la relit telle quelle)."""
    t = maison.maintenant().strftime(maison.FORMAT_HORODATAGE)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", t)


def test_aucune_heure_de_machine_dans_le_moteur():
    """Fin de S-D1 : aucun datetime.now() sans argument, ni date.today(), ni time.localtime() dans poc/ hors des
    tests. Seul maison.maintenant() lit l'horloge, avec le fuseau de la maison."""
    interdit = re.compile(r"datetime\.now\(\s*\)|\.today\(\)|\blocaltime\(|\btime\.strftime\(")
    trouves = []
    for fichier in sorted(POC.rglob("*.py")):
        rel = fichier.relative_to(POC)
        if rel.parts[0] in ("tests", ".venv", "venv", "__pycache__"):
            continue
        for n, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), 1):
            if interdit.search(ligne.split("#")[0]):
                trouves.append(f"{rel}:{n}: {ligne.strip()}")
    assert not trouves, "heure de la machine utilisée :\n" + "\n".join(trouves)
