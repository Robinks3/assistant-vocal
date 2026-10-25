"""Dictionnaire de commandes et outils du LLM."""
import json
import tempfile
from pathlib import Path

import assistant as A
from dictionnaire import Dictionnaire

import maison

# Phrases apprises dans un dossier temporaire : rien n'est jamais écrit dans config-exemple/.
DICO = Dictionnaire(maison.chemin("commandes.yaml"), Path(tempfile.mkdtemp()) / "commandes_apprises.yaml")


def test_phrases_connues():
    for phrase in ("allume le salon", "éteins toutes les lumières", "est-ce que tu peux éteindre la télé"):
        from dictionnaire import epurer
        assert DICO.chercher(epurer(phrase)), phrase


def test_mot_remplace_refuse():
    # « éteins » ne doit jamais devenir « allume » par ressemblance
    trouve = DICO.chercher("allume la télé")
    if trouve:
        assert all("turn_off" not in a["service"] for a in trouve[0])


def test_aucune_action_du_dictionnaire_ne_vise_camille():
    import securite
    vues = 0
    for forme, (entree, _emplacements) in DICO.formes.items():
        actions = entree.get("action") or entree.get("actions") or []
        for a in (actions if isinstance(actions, list) else [actions]):
            if isinstance(a, dict) and "service" in a and not any("{" in str(v) for v in a.values()):
                vues += 1
                donnees = {k: v for k, v in a.items() if k != "service"}
                assert not any(securite.protege(e) for e in securite.cibles(donnees.get("entity_id"))), forme
                assert not str(donnees.get("entity_id", "")).lower() == "all", forme
    assert vues > 100


def test_outils_enum():
    outils = A.outils_avec_entites({"light.b", "light.a"})
    schema = outils[0]["function"]["parameters"]["properties"]["entity_id"]
    assert schema["anyOf"][0]["enum"] == ["light.a", "light.b"]
    assert A.outils_avec_entites(set()) is A.OUTILS
    assert "enum" not in str(A.OUTILS[0]["function"]["parameters"]["properties"]["entity_id"])


def test_entite_hors_liste_refusee():
    ha = A.HomeAssistant("http://exemple.invalid", "x")
    ha.essai = True
    ha.entites_llm = {"light.exemple6"}
    assert "erreur" in ha.service("light", "turn_on", "light.inconnue")
    assert ha.service("light", "turn_on", "light.exemple6") == {"ok": True}


def test_outil_musique():
    noms = [o["function"]["name"] for o in A.OUTILS]
    assert noms == ["appeler_service", "jouer_musique", "lire_etat"]
    outils = A.outils_avec_entites({"light.a"})
    assert outils[2]["function"]["parameters"]["properties"]["entity_id"]["enum"] == ["light.a"]
    ha = A.HomeAssistant("http://exemple.invalid", "x")
    ha.essai = True
    ha.chercher_musique = lambda r, t, a="", fin=None: ({"nom": "Titre Fictif de Artiste Fictif", "uri": "spotify://track/x",
                                               "titre": "Titre Fictif", "type": t} if "titre" in r else None)
    assert ha.musique("Titre Fictif", "track", "toutes", "Artiste Fictif") == {"ok": True, "lance": "Titre Fictif de Artiste Fictif"}
    assert "erreur" in ha.musique("inconnu", "track")
    assert "erreur" in ha.musique("", "track")


def _exporter(*args, env=None):
    import subprocess
    import sys
    racine = Path(__file__).resolve().parents[2]
    r = subprocess.run([sys.executable, str(racine / "android" / "outils" / "exporter_dictionnaire.py"), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert r.returncode == 0, r.stderr


def test_export_exemple_a_jour(tmp_path):
    """config-exemple/genere/android/dictionnaire.json, lu par les tests de l'appli, suit config-exemple/commandes.yaml.
    L'export est refait dans un dossier temporaire, le fichier suivi par git n'est jamais réécrit par le test."""
    export = Path(__file__).resolve().parents[2] / "config-exemple" / "genere" / "android" / "dictionnaire.json"
    neuf = tmp_path / "dictionnaire.json"
    _exporter("--exemple", "--sortie", str(neuf))
    assert export.exists() and export.read_bytes() == neuf.read_bytes(), \
        "export d'exemple périmé : python android/outils/exporter_dictionnaire.py --exemple, puis le committer"


def test_phrases_apprises_hors_export_de_configuration(tmp_path):
    """0.32.2 : les phrases apprises partent dans dictionnaire_appris.json du dossier de données, jamais dans
    genere/android/dictionnaire.json du dossier de configuration, que le dépôt de configuration peut versionner."""
    import os
    import shutil
    racine = Path(__file__).resolve().parents[2]
    config, donnees = tmp_path / "config", tmp_path / "donnees"
    shutil.copytree(racine / "config-exemple", config, ignore=shutil.ignore_patterns("genere"))
    donnees.mkdir()
    (donnees / "commandes_apprises.yaml").write_text(
        "apprises:\n- phrase: Phrase apprise de test\n  action: {service: light.turn_on, entity_id: light.essai}\n",
        encoding="utf-8")
    env = {**os.environ, "ASSISTANT_VOCAL_CONFIG": str(config), "JARVIS_DONNEES": str(donnees)}
    _exporter(env=env)
    dico = json.loads((config / "genere" / "android" / "dictionnaire.json").read_text(encoding="utf-8"))
    appris = json.loads((donnees / "genere" / "android" / "dictionnaire_appris.json").read_text(encoding="utf-8"))
    assert "phrase apprise de test" not in {f[0] for f in dico["formes"]}
    assert not any(m.get("appris") for m in dico["modeles"])
    assert [f[0] for f in appris["formes"]] == ["phrase apprise de test"]
    assert appris["modeles"][0]["appris"] and appris["modeles"][0]["source"] == "commandes_apprises.yaml"
    # Sans phrase apprise, l'export à part est réécrit vide plutôt que laissé périmé.
    (donnees / "commandes_apprises.yaml").unlink()
    _exporter(env=env)
    assert json.loads((donnees / "genere" / "android" / "dictionnaire_appris.json").read_text(encoding="utf-8"))["formes"] == []


def test_prenom_mal_entendu_corrige():
    """proprietaire.variantes de config-exemple/maison.json : « sasha » et « sachat » deviennent Sacha, une seule fois."""
    from dictionnaire import epurer
    assert epurer("allume la chambre de sasha") == "allume la chambre de Sacha"
    assert epurer("allume la chambre de sachat") == "allume la chambre de Sacha"
    assert epurer("allume la chambre de Sacha") == "allume la chambre de Sacha"
