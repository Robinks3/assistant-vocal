"""Dictionnaire de commandes et outils du LLM."""
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


def test_export_exemple_a_jour():
    """config-exemple/genere/android/dictionnaire.json, lu par les tests de l'appli, suit config-exemple/commandes.yaml.
    En cas d'échec, l'export vient d'être refait : le committer avec le dictionnaire d'exemple."""
    import subprocess
    import sys
    racine = Path(__file__).resolve().parents[2]
    export = racine / "config-exemple" / "genere" / "android" / "dictionnaire.json"
    avant = export.read_bytes() if export.exists() else b""
    r = subprocess.run([sys.executable, str(racine / "android" / "outils" / "exporter_dictionnaire.py"), "--exemple"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    assert export.read_bytes() == avant, "export d'exemple périmé, refait par ce test : le committer"


def test_prenom_mal_entendu_corrige():
    """proprietaire.variantes de config-exemple/maison.json : « sasha » et « sachat » deviennent Sacha, une seule fois."""
    from dictionnaire import epurer
    assert epurer("allume la chambre de sasha") == "allume la chambre de Sacha"
    assert epurer("allume la chambre de sachat") == "allume la chambre de Sacha"
    assert epurer("allume la chambre de Sacha") == "allume la chambre de Sacha"
