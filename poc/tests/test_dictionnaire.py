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
    ha.entites_llm = {"light.salon_plafond"}
    assert "erreur" in ha.service("light", "turn_on", "light.inconnue")
    assert ha.service("light", "turn_on", "light.salon_plafond") == {"ok": True}


def test_outil_musique():
    noms = [o["function"]["name"] for o in A.OUTILS]
    assert noms == ["appeler_service", "jouer_musique", "lire_etat"]
    outils = A.outils_avec_entites({"light.a"})
    assert outils[2]["function"]["parameters"]["properties"]["entity_id"]["enum"] == ["light.a"]
    ha = A.HomeAssistant("http://exemple.invalid", "x")
    ha.essai = True
    ha.chercher_musique = lambda r, t, a="", fin=None: ({"nom": "La Route du Sel de Lou Fictif", "uri": "spotify://track/x",
                                               "titre": "La Route du Sel", "type": t} if "route" in r.lower() else None)
    assert ha.musique("La Route du Sel", "track", "toutes", "Lou Fictif") == {"ok": True, "lance": "La Route du Sel de Lou Fictif"}
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


def _exporter_config_modifiee(tmp_path, modifier):
    """Exporte une copie de config-exemple/ dont commandes.yaml est modifié par `modifier(dict)`, rend le JSON exporté."""
    import os
    import shutil
    import yaml
    racine = Path(__file__).resolve().parents[2]
    config = tmp_path / "config"
    shutil.copytree(racine / "config-exemple", config, ignore=shutil.ignore_patterns("genere"))
    donnees = yaml.safe_load((config / "commandes.yaml").read_text(encoding="utf-8"))
    modifier(donnees)
    (config / "commandes.yaml").write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    sortie = tmp_path / "dictionnaire.json"
    env = {**os.environ, "ASSISTANT_VOCAL_CONFIG": str(config), "JARVIS_DONNEES": str(tmp_path / "donnees")}
    _exporter("--sortie", str(sortie), env=env)
    return json.loads(sortie.read_text(encoding="utf-8"))


def test_export_porte_les_notes_du_llm():
    """S-D7 (constat C6) : llm.notes de commandes.yaml part dans l'export lu par CerveauAppareil.kt, tel quel,
    en plus de llm.renommer et llm.masquer."""
    import yaml
    export = Path(__file__).resolve().parents[2] / "config-exemple" / "genere" / "android" / "dictionnaire.json"
    llm = json.loads(export.read_text(encoding="utf-8"))["llm"]
    attendu = yaml.safe_load(maison.chemin("commandes.yaml").read_text(encoding="utf-8"))["llm"]
    assert attendu["notes"], "la configuration d'exemple doit porter une note pour que ce test ait un sens"
    assert llm["notes"] == attendu["notes"]
    assert llm["renommer"] == attendu["renommer"] and llm["masquer"] == attendu["masquer"]


def test_export_notes_modifiees_et_absentes(tmp_path):
    """Une note changée dans commandes.yaml change l'export. Sans la clé llm.notes, ou sans section llm, l'export
    reste valide et ne porte aucune note (comportement d'avant S-D7)."""
    def autre_note(d):
        d["llm"]["notes"] = {"light.essai": "variante de test"}
    assert _exporter_config_modifiee(tmp_path / "a", autre_note)["llm"]["notes"] == {"light.essai": "variante de test"}

    def sans_notes(d):
        d["llm"].pop("notes")
    llm = _exporter_config_modifiee(tmp_path / "b", sans_notes)["llm"]
    assert "notes" not in llm and llm["renommer"] and llm["masquer"]

    def sans_llm(d):
        d.pop("llm")
    assert _exporter_config_modifiee(tmp_path / "c", sans_llm)["llm"] == {}


def test_phrases_apprises_hors_export_de_configuration(tmp_path):
    """0.32.2 : les phrases apprises partent dans dictionnaire_appris.json du dossier de données, jamais dans
    genere/android/dictionnaire.json du dossier de configuration, que le dépôt de configuration peut versionner."""
    import os
    import shutil
    racine = Path(__file__).resolve().parents[2]
    config, donnees = tmp_path / "config", tmp_path / "donnees"
    shutil.copytree(racine / "config-exemple", config, ignore=shutil.ignore_patterns("genere"))
    donnees.mkdir()
    # Une phrase déjà couverte par commandes.yaml ne part pas dans l'export à part.
    deja = json.loads((racine / "config-exemple" / "genere" / "android" / "dictionnaire.json")
                      .read_text(encoding="utf-8"))["formes"][0][0]
    (donnees / "commandes_apprises.yaml").write_text(
        "apprises:\n- phrase: Phrase apprise de test\n  action: {service: light.turn_on, entity_id: light.essai}\n"
        f"- phrase: {deja}\n  action: {{service: light.turn_on, entity_id: light.essai}}\n",
        encoding="utf-8")
    env = {**os.environ, "ASSISTANT_VOCAL_CONFIG": str(config), "JARVIS_DONNEES": str(donnees)}
    _exporter(env=env)
    dico = json.loads((config / "genere" / "android" / "dictionnaire.json").read_text(encoding="utf-8"))
    appris = json.loads((donnees / "genere" / "android" / "dictionnaire_appris.json").read_text(encoding="utf-8"))
    assert "phrase apprise de test" not in {f[0] for f in dico["formes"]}
    assert not any(m.get("appris") for m in dico["modeles"])
    assert [f[0] for f in appris["formes"]] == ["phrase apprise de test"]
    assert appris["modeles"][0]["appris"] and appris["modeles"][0]["source"] == "commandes_apprises.yaml"
    # Même jeton dans les deux fichiers : l'appli ignore des phrases apprises d'un autre export.
    assert dico["export"] and appris["export"] == dico["export"]
    # Sans phrase apprise, l'export à part est réécrit vide plutôt que laissé périmé.
    (donnees / "commandes_apprises.yaml").unlink()
    _exporter(env=env)
    assert json.loads((donnees / "genere" / "android" / "dictionnaire_appris.json").read_text(encoding="utf-8"))["formes"] == []


def test_export_donnees_relatives_depuis_la_racine(tmp_path):
    """--donnees relatif part de la racine du dépôt, comme -PdonneesDossier dans build.gradle.kts, quel que soit
    le dossier d'où l'export est lancé. Un argument inconnu est refusé plutôt qu'ignoré."""
    import os
    import shutil
    import subprocess
    import sys
    racine = Path(__file__).resolve().parents[2]
    config = tmp_path / "config"
    shutil.copytree(racine / "config-exemple", config, ignore=shutil.ignore_patterns("genere"))
    relatif = os.path.relpath(tmp_path / "donnees", racine)
    env = {**os.environ, "ASSISTANT_VOCAL_CONFIG": str(config)}
    env.pop("JARVIS_DONNEES", None)
    script = str(racine / "android" / "outils" / "exporter_dictionnaire.py")
    r = subprocess.run([sys.executable, script, "--donnees", relatif], cwd=tmp_path, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "donnees" / "genere" / "android" / "dictionnaire_appris.json").exists()
    r = subprocess.run([sys.executable, script, "--exemple", "--sortei", str(tmp_path / "x.json")], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode != 0 and not (tmp_path / "x.json").exists()


def test_prenom_mal_entendu_corrige():
    """proprietaire.variantes de config-exemple/maison.json : « sasha » et « sachat » deviennent Sacha, une seule fois."""
    from dictionnaire import epurer
    assert epurer("allume la chambre de sasha") == "allume la chambre de Sacha"
    assert epurer("allume la chambre de sachat") == "allume la chambre de Sacha"
    assert epurer("allume la chambre de Sacha") == "allume la chambre de Sacha"
