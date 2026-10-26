"""Les prénoms viennent de la configuration (maison.json), jamais du code Python (dette C14, partie prénoms).

Trois garanties :
- le nom de l'occupant protégé que le code affiche est celui de la clé securite.nom_occupant, et il change avec elle
  (vérifié dans un interpréteur séparé, sur une configuration fictive écrite pour l'occasion) ;
- le propriétaire et ses clés de personne sont lus dans proprietaire et securite.permis_personne ;
- aucun prénom de la configuration n'est écrit dans une chaîne de code de poc/ (les commentaires et les
  docstrings sont des explications, pas du code).
"""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import maison
import securite

POC = Path(__file__).resolve().parents[1]
RACINE = POC.parent
EXEMPLE = RACINE / "config-exemple"


def prenoms_de(configuration):
    """Prénoms et clés de personne d'une configuration : propriétaire, occupant protégé, personnes autorisées."""
    securite_conf = configuration.get("securite") or {}
    proprietaire = configuration.get("proprietaire") or {}
    noms = {securite_conf.get("nom_occupant"), proprietaire.get("nom"), proprietaire.get("cle")}
    noms.update(proprietaire.get("variantes") or [])
    noms.update((securite_conf.get("permis_personne") or {}).keys())
    return sorted({str(n).strip() for n in noms if n and len(str(n).strip()) >= 3}, key=str.lower)


def nom_occupant_dans_un_autre_interpreteur(dossier):
    """NOM_OCCUPANT et NOM_PROPRIETAIRE tels que le code les calcule au chargement, sur ce dossier de configuration."""
    environnement = dict(os.environ, ASSISTANT_VOCAL_CONFIG=str(dossier))
    environnement.pop("MAISON_DOSSIER", None)
    code = ("import json, maison, securite; "
            "print(json.dumps([securite.NOM_OCCUPANT, maison.NOM_PROPRIETAIRE, maison.CLE_PROPRIETAIRE]))")
    sortie = subprocess.run([sys.executable, "-c", code], cwd=POC, env=environnement, capture_output=True,
                            text=True, check=True, timeout=60).stdout
    return json.loads(sortie.strip().splitlines()[-1])


def test_le_nom_de_l_occupant_vient_de_la_configuration_chargee():
    assert securite.NOM_OCCUPANT == (maison.SECURITE.get("nom_occupant") or "l'occupant")
    assert maison.NOM_PROPRIETAIRE == (maison.PROPRIETAIRE.get("nom") or "Moi")
    assert maison.CLE_PROPRIETAIRE == (maison.PROPRIETAIRE.get("cle") or maison.NOM_PROPRIETAIRE).lower()


def test_les_tests_tournent_sur_l_exemple_fictif():
    """Sans cela, les noms vérifiés ici seraient ceux d'un vrai logement."""
    exemple = json.loads((EXEMPLE / "maison.json").read_text(encoding="utf-8"))
    if os.environ.get("ASSISTANT_VOCAL_CONFIG", "") != str(EXEMPLE):
        pytest.skip("configuration réglée à la main : le nom attendu n'est plus celui de l'exemple")
    assert securite.NOM_OCCUPANT == exemple["securite"]["nom_occupant"]
    assert maison.NOM_PROPRIETAIRE == exemple["proprietaire"]["nom"]
    assert maison.CLE_PROPRIETAIRE == exemple["proprietaire"]["cle"].lower()


def test_le_nom_change_avec_la_configuration(tmp_path):
    """Une configuration d'un autre foyer donne d'autres noms, sans toucher au code."""
    exemple = json.loads((EXEMPLE / "maison.json").read_text(encoding="utf-8"))
    assert nom_occupant_dans_un_autre_interpreteur(EXEMPLE)[0] == exemple["securite"]["nom_occupant"]
    autre = {"securite": {"nom_occupant": "Noa"}, "proprietaire": {"nom": "Lou", "cle": "lou"}}
    (tmp_path / "maison.json").write_text(json.dumps(autre), encoding="utf-8")
    assert nom_occupant_dans_un_autre_interpreteur(tmp_path) == ["Noa", "Lou", "lou"]
    (tmp_path / "maison.json").write_text("{}", encoding="utf-8")
    assert nom_occupant_dans_un_autre_interpreteur(tmp_path)[0] == "l'occupant"


def test_le_refus_nomme_l_occupant_de_la_configuration(monkeypatch):
    monkeypatch.setattr(securite, "PROTEGER_OCCUPANT", True)
    monkeypatch.setattr(securite, "NOM_OCCUPANT", "Camille")
    monkeypatch.setattr(securite, "MOTS_PROTEGES", ("camille",))
    refus = securite.verifier("light.turn_on", {"entity_id": "light.chambre_camille_plafonds"})
    assert refus and "Camille" in refus
    refus = securite.phrase_protegee("allume la chambre de camille")
    assert refus and "Camille" in refus


def fichiers_de_code():
    """Fichiers Python du moteur, sans les tests (qui ont le droit d'écrire les noms fictifs de l'exemple)."""
    return sorted(p for p in POC.rglob("*.py")
                  if "tests" not in p.relative_to(POC).parts and "genere" not in p.relative_to(POC).parts
                  and ".venv" not in p.relative_to(POC).parts)


def chaines_de_code(chemin):
    """(ligne, texte) de chaque chaîne du fichier qui n'est pas une docstring ni un texte flottant."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    explications = {id(n.value) for n in ast.walk(arbre) if isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
    return [(n.lineno, n.value) for n in ast.walk(arbre)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in explications]


def prenoms_en_dur(prenoms):
    """Chemin -> lignes où une chaîne de code contient l'un de ces prénoms en mot entier. Valeurs jamais renvoyées."""
    if not prenoms:
        return {}
    motif = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(p) for p in prenoms) + r")(?!\w)", re.IGNORECASE)
    trouves = {}
    for chemin in fichiers_de_code():
        lignes = sorted({ligne for ligne, texte in chaines_de_code(chemin) if motif.search(texte)})
        if lignes:
            trouves[str(chemin.relative_to(RACINE)).replace("\\", "/")] = lignes
    return trouves


def configurations_a_surveiller():
    """L'exemple public, plus la configuration réelle quand elle est là (alors ses prénoms sont cherchés aussi)."""
    configurations = [json.loads((EXEMPLE / "maison.json").read_text(encoding="utf-8"))]
    reelle = RACINE / "config" / "maison.json"
    if reelle.is_file():
        configurations.append(json.loads(reelle.read_text(encoding="utf-8")))
    return configurations


def test_aucun_prenom_en_dur_dans_le_code_python():
    prenoms = sorted({p for c in configurations_a_surveiller() for p in prenoms_de(c)})
    assert len(prenoms) >= 2, "l'exemple fournit au moins le propriétaire et l'occupant"
    trouves = prenoms_en_dur(prenoms)
    assert not trouves, f"Prénoms de la configuration écrits dans du code (valeurs non affichées) : {trouves}"


def test_le_detecteur_de_prenoms_voit_une_chaine_et_ignore_les_explications(tmp_path, monkeypatch):
    prenom = "".join(("Zo", "raïde"))
    source = (f'"""Docstring qui parle de {prenom}."""\n'
              f'# commentaire sur {prenom}\n'
              f'def f():\n    """Explication sur {prenom}."""\n    return "bonjour {prenom.lower()}"\n')
    fichier = tmp_path / "essai.py"
    fichier.write_text(source, encoding="utf-8")
    assert [ligne for ligne, _ in chaines_de_code(fichier)] == [5]
    monkeypatch.setattr(sys.modules[__name__], "fichiers_de_code", lambda: [fichier])
    monkeypatch.setattr(sys.modules[__name__], "RACINE", tmp_path)
    assert prenoms_en_dur([prenom]) == {"essai.py": [5]}
    assert prenoms_en_dur(["autre-prenom"]) == {}


def test_prenoms_de_lit_les_cles_de_personne():
    configuration = {"securite": {"nom_occupant": "Noa", "permis_personne": {"lou": {}}},
                     "proprietaire": {"nom": "Eli", "cle": "eli", "variantes": ["elie"]}}
    assert set(prenoms_de(configuration)) == {"Eli", "eli", "elie", "lou", "Noa"}
