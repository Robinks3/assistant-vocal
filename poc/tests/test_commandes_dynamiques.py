"""S-L4 (serveur 0.44.0) : lampes et télévision à la voix.

Trois choses, avec les mêmes cas que la tablette (CommandesDynamiquesTest.kt, DictionnaireTest.kt) :
  - cas_dynamique.json : la résolution des actions dynamiques d'après l'état des appareils ;
  - cas_commandes_lampes_tele.json : les phrases de commandes.yaml, avec leurs pièges (rose, orange, monte, chaud) ;
  - le branchement dans Assistant : états lus, sécurité en dur appliquée à ce que la résolution produit.
"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import acces
import assistant as A
import commandes_dynamiques as CD
import maison
import securite
from dictionnaire import Dictionnaire, epurer

ICI = Path(__file__).resolve().parent
DICO = Dictionnaire(maison.chemin("commandes.yaml"), Path(tempfile.mkdtemp()) / "commandes_apprises.yaml")
CAS_DYNAMIQUE = json.loads((ICI / "cas_dynamique.json").read_text(encoding="utf-8"))["cas"]
CAS_PHRASES = json.loads((ICI / "cas_commandes_lampes_tele.json").read_text(encoding="utf-8"))["cas"]
TELE = "media_player.tele_salon"


def texte(valeur):
    """Valeur comparée en texte, comme la tablette : 2200 = "2200", true = "true", listes et objets à plat."""
    if isinstance(valeur, bool):
        return "true" if valeur else "false"
    if isinstance(valeur, dict):
        return "{" + ",".join(f"{k}={texte(valeur[k])}" for k in sorted(valeur)) + "}"
    if isinstance(valeur, (list, tuple)):
        return "[" + ",".join(texte(v) for v in valeur) + "]"
    return str(valeur)


# ---------------------------------------------------------------------------------------------------------------
# Résolution des actions dynamiques
# ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cas", CAS_DYNAMIQUE, ids=lambda c: c["note"])
def test_resolution_dynamique(cas):
    actions, vide = CD.resoudre_toutes([cas["action"]], cas["etats"])
    assert [texte(a) for a in actions] == [texte(a) for a in cas["actions"]]
    assert vide == cas["vide"]


def test_une_action_ordinaire_passe_telle_quelle():
    ordinaire = {"service": "light.turn_on", "entity_id": "light.a"}
    assert CD.resoudre_toutes([ordinaire], {}) == ([ordinaire], None)


def test_entites_lues_sans_doublon_et_dans_l_ordre():
    liste = [{"dynamique": "kelvin_pas", "entity_id": ["light.b", "light.a"], "pas": 500},
             {"dynamique": "selon_etat", "entite": "light.a"},
             {"dynamique": "selon_etat", "entite": TELE},
             {"service": "light.turn_on", "entity_id": "light.z"}]
    assert CD.entites_lues(liste) == ["light.b", "light.a", TELE]


def test_une_action_dynamique_inconnue_ne_fait_rien():
    actions, vide = CD.resoudre_toutes([{"dynamique": "inventee"}], {})
    assert actions == [] and vide == CD.REPONSE_VIDE_DEFAUT


def test_on_non_cite_dans_un_yaml_vaut_l_etat_on():
    # YAML 1.1 lit `on` comme un booléen : la liste des états permis doit quand même reconnaître l'état "on".
    action = {"dynamique": "selon_etat", "entite": TELE, "etats": [True, "playing"],
              "alors": {"service": "media_player.volume_up", "entity_id": TELE},
              "sinon": {"service": "light.turn_on", "entity_id": "light.a"}}
    actions, _ = CD.resoudre_toutes([action], {TELE: {"state": "on"}})
    assert [a["service"] for a in actions] == ["media_player.volume_up"]


def test_les_etats_du_dictionnaire_sont_des_textes():
    # Garde-fou de la même cause : aucune liste `etats` de commandes.yaml ne contient un booléen.
    for forme_actions in (DICO.chercher(epurer(p))[0] for p in ("monte", "baisse", "reprends")):
        for a in forme_actions:
            assert all(isinstance(e, str) for e in a["etats"]), a


def test_la_resolution_ne_modifie_pas_l_action_du_dictionnaire():
    # Le dictionnaire garde la même action d'un appel à l'autre : la résolution rend des copies.
    alors = {"service": "media_player.volume_up", "entity_id": TELE}
    action = {"dynamique": "selon_etat", "entite": TELE, "etats": ["on"], "alors": alors}
    actions, _ = CD.resoudre_toutes([action], {TELE: {"state": "on"}})
    actions[0]["entity_id"] = "autre"
    assert alors["entity_id"] == TELE


# ---------------------------------------------------------------------------------------------------------------
# Phrases de commandes.yaml
# ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cas", CAS_PHRASES, ids=lambda c: c["note"])
def test_phrase(cas):
    trouve = DICO.chercher(epurer(cas["phrase"]))
    if cas.get("absent"):
        assert trouve is None, f"{cas['phrase']!r} ne doit rien déclencher, trouvé : {trouve}"
        return
    assert trouve, cas["phrase"]
    actions, _, _ = trouve
    attendues = cas["actions"]
    assert len(actions) == len(attendues), actions
    for obtenue, voulue in zip(actions, attendues):
        for cle, valeur in voulue.items():
            assert texte(obtenue.get(cle)) == texte(valeur), f"{cle} de {obtenue}"


def test_les_couleurs_et_les_blancs_nommes_sont_ceux_de_la_tablette():
    # Mêmes valeurs que ReglageLampe.kt (TEINTES et BLANCS) : ce que le volet affiche est ce que la voix envoie.
    teintes = {"rouge": 0, "orange": 30, "jaune": 55, "vert": 120, "cyan": 180, "bleu": 220, "violet": 275, "rose": 330}
    for nom, degres in teintes.items():
        actions = DICO.chercher(epurer(f"mets le salon en {nom}"))[0]
        assert texte(actions[0]["hs_color"]) == texte([str(degres), 100]), nom
    blancs = {"bougie": 2200, "chaud": 2700, "blanc neutre": 4000, "blanc froid": 6000}
    for nom, kelvin in blancs.items():
        actions = DICO.chercher(epurer(f"mets le salon en {nom}"))[0]
        assert texte(actions[0]["color_temp_kelvin"]) == str(kelvin), nom


def test_chaque_action_ordinaire_passe_la_securite_de_la_configuration_d_exemple():
    # Sauf le volume sous plafond, qui est refusé exprès (voir plus bas), tout ce que les nouvelles phrases demandent
    # traverse le contrôle habituel.
    for cas in CAS_PHRASES:
        if cas.get("absent"):
            continue
        actions, _, _ = DICO.chercher(epurer(cas["phrase"]))
        for a in actions:
            if CD.est_dynamique(a):
                continue
            service = a["service"]
            if service == "media_player.volume_up" and securite.plafond_actif():
                continue
            dom, _, srv = service.partition(".")
            refus = acces.controler_service(dom, srv, {k: v for k, v in a.items() if k != "service"})
            assert refus is None, f"{cas['phrase']} : {service} refusé ({refus})"


# ---------------------------------------------------------------------------------------------------------------
# Branchement dans Assistant
# ---------------------------------------------------------------------------------------------------------------

class FaussePasserelle:
    """Home Assistant simulé : des états à lire, des services enregistrés."""

    def __init__(self, etats):
        self.etats, self.lus, self.appels = etats, [], []

    def etat_brut(self, entity_id):
        self.lus.append(entity_id)
        return self.etats.get(entity_id)


def assistant_de_test(monkeypatch, etats, essai=False):
    monkeypatch.setattr(A, "journaliser", lambda *a, **k: None)
    a = object.__new__(A.Assistant)
    a.essai, a.voix, a.lecons = essai, None, {}
    a.dico = DICO
    a.ha = FaussePasserelle(etats)
    a.indication = lambda p: ""
    a.routines_avant = lambda t: None
    a.cerveau = SimpleNamespace(repondre=lambda *x, **k: pytest.fail("le LLM ne doit pas être appelé"))
    a.executees = []
    a.executer = lambda action, personne=None: a.executees.append(action)
    return a


def dire(assistant, phrase):
    return assistant._traiter(epurer(phrase), 0.0, None)


def test_monte_avec_la_tele_allumee_monte_le_volume(monkeypatch):
    a = assistant_de_test(monkeypatch, {TELE: {"state": "playing", "attributes": {}}})
    dire(a, "monte")
    assert a.ha.lus == [TELE]
    assert [x["service"] for x in a.executees] == ["media_player.volume_up"] * 3


def test_monte_avec_la_tele_eteinte_monte_la_lumiere(monkeypatch):
    a = assistant_de_test(monkeypatch, {TELE: {"state": "off", "attributes": {}}})
    dire(a, "monte")
    assert [(x["service"], x["entity_id"], x["brightness_step_pct"]) for x in a.executees] == \
        [("light.turn_on", "light.salon_plafond", 20)]


def test_baisse_avec_la_tele_injoignable_baisse_la_lumiere(monkeypatch):
    a = assistant_de_test(monkeypatch, {})
    dire(a, "baisse")
    assert [(x["service"], x["brightness_step_pct"]) for x in a.executees] == [("light.turn_on", -20)]


def test_pause_vise_la_tele_si_elle_lit_sinon_la_musique(monkeypatch):
    a = assistant_de_test(monkeypatch, {TELE: {"state": "playing", "attributes": {}}})
    dire(a, "pause")
    assert [x["service"] for x in a.executees] == ["media_player.media_pause"]
    a = assistant_de_test(monkeypatch, {TELE: {"state": "off", "attributes": {}}})
    dire(a, "pause")
    assert [(x["service"], x["entity_id"]) for x in a.executees] == [("script.turn_on", "script.couper_musique")]


def test_reprends_sans_rien_en_pause_le_dit_et_ne_lance_rien(monkeypatch):
    a = assistant_de_test(monkeypatch, {TELE: {"state": "playing", "attributes": {}}})
    parole = dire(a, "reprends")
    assert a.executees == [] and parole == "Il n'y a rien à reprendre."


def test_plus_chaud_deplace_chaque_lampe_allumee_en_blanc(monkeypatch):
    etats = {"light.salon_plafond": {"state": "on", "attributes": {"color_temp_kelvin": 4000, "min_color_temp_kelvin": 2000,
                                                                  "max_color_temp_kelvin": 6500}},
             "light.salon_lampe_tele": {"state": "off", "attributes": {"color_temp_kelvin": 4000}}}
    a = assistant_de_test(monkeypatch, etats)
    dire(a, "plus chaud")
    assert a.executees == [{"service": "light.turn_on", "entity_id": "light.salon_plafond", "color_temp_kelvin": 3500}]


def test_plus_chaud_avec_tout_eteint_le_dit(monkeypatch):
    a = assistant_de_test(monkeypatch, {})
    parole = dire(a, "plus chaud")
    assert a.executees == [] and "Aucune lampe allumée" in parole


def test_en_mode_essai_aucun_etat_n_est_lu(monkeypatch):
    a = assistant_de_test(monkeypatch, {TELE: {"state": "on", "attributes": {}}}, essai=True)
    dire(a, "monte")
    assert a.ha.lus == [] and a.executees == []


def test_la_securite_voit_les_actions_resolues(monkeypatch):
    # Plafond de volume actif : un « monte » sur la télé allumée est refusé comme volume_up, pas laissé passer parce
    # qu'il était écrit dynamique.
    monkeypatch.setattr(securite, "VOLUME_MAX", 0.5)
    assert acces.controler_service("media_player", "volume_up", {"entity_id": TELE}) is not None
    a = assistant_de_test(monkeypatch, {TELE: {"state": "on", "attributes": {}}})
    parole = dire(a, "monte")
    assert a.executees == [] and parole
