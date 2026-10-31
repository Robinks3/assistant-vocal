"""S-F5 (0.41.0) : une seule liste blanche des actions de la télé et des lampes.

Le module liste_blanche porte la table des services (voie LLM) et les réglages de la maison (section « reglages »
de maison.json : attributs refusés, applis, interrupteurs). La voie LLM (HomeAssistant.service) et la passerelle de
l'appli (acces.verifier_requete_ha) y passent toutes les deux par acces.controler_service."""
import pytest

import acces
import assistant as A
import liste_blanche

TELE = "media_player.tele_salon"
LAMPE = "light.salon_plafond"
PRISE_LISTEE = "switch.chambre_camille_prise"
PRISE_HORS_LISTE = "switch.prise"

REGLAGES_TEST = {
    "applis": ["Netflix", "YouTube"],
    "interrupteurs": [PRISE_LISTEE],
    "attributs_refuses": {"light.turn_on": ["flash"]},
}


@pytest.fixture
def reglages(monkeypatch):
    monkeypatch.setattr(liste_blanche, "REGLAGES", REGLAGES_TEST)


def _ha():
    ha = A.HomeAssistant("http://exemple.invalid", "x")
    ha.essai = True
    return ha


def voie_llm(domaine, service, corps):
    """True quand la voie LLM accepte l'appel (essai : rien n'est envoyé à HA)."""
    donnees = {k: v for k, v in corps.items() if k != "entity_id"}
    retour = _ha().service(domaine, service, corps.get("entity_id"), donnees)
    return "erreur" not in retour


def voie_passerelle(domaine, service, corps):
    return acces.verifier_requete_ha("POST", f"/api/services/{domaine}/{service}", corps) is None


def voie_directe(domaine, service, corps):
    permis = liste_blanche.SERVICES_PERMIS.get(domaine)
    return acces.controler_service(domaine, service, corps, services_permis=permis) is None


# (domaine, service, corps, accepté)
CAS = [
    ("tele_connectee", "launch_app", {"entity_id": TELE, "app": "Netflix"}, True),
    ("tele_connectee", "launch_app", {"entity_id": TELE, "app": "Appli inconnue"}, False),
    ("tele_connectee", "launch_app", {"entity_id": TELE, "app": ["Netflix"]}, False),
    ("tele_connectee", "launch_app", {"entity_id": TELE, "url": "https://www.netflix.com/title/80100172"}, True),
    ("tele_connectee", "launch_app", {"entity_id": TELE, "url": "http://www.netflix.com/title/80100172"}, False),
    ("tele_connectee", "reboot", {"entity_id": TELE}, False),
    ("tele_connectee", "send_text_input", {"entity_id": TELE, "text": "docteur"}, True),
    ("tele_connectee", "send_text_input", {"entity_id": TELE, "text": "x", "device_id": "abcdef0123"}, False),
    ("remote", "send_command", {"entity_id": "remote.salon", "command": "KEY_HOME"}, True),
    ("remote", "learn_command", {"entity_id": "remote.salon", "command": "KEY_HOME"}, False),
    ("select", "select_option", {"entity_id": "select.salon_mode", "option": "Cinéma"}, True),
    ("select", "reload", {"entity_id": "select.salon_mode"}, False),
    ("switch", "turn_on", {"entity_id": PRISE_LISTEE}, True),
    ("switch", "turn_off", {"entity_id": [PRISE_LISTEE]}, True),
    ("switch", "turn_on", {"entity_id": PRISE_HORS_LISTE}, False),
    ("switch", "turn_on", {"entity_id": [PRISE_LISTEE, PRISE_HORS_LISTE]}, False),
    ("switch", "turn_on", {}, False),
    ("light", "turn_on", {"entity_id": LAMPE, "brightness_pct": 40}, True),
    ("light", "turn_on", {"entity_id": LAMPE, "flash": "short"}, False),
    ("light", "turn_on", {"entity_id": LAMPE, "device_id": "abcdef0123"}, False),
    ("lock", "unlock", {"entity_id": "lock.porte"}, False),
    ("alarm_control_panel", "alarm_disarm", {"entity_id": "alarm_control_panel.maison"}, False),
]


@pytest.mark.parametrize("domaine,service,corps,attendu", CAS)
def test_les_deux_filtres_repondent_pareil(reglages, domaine, service, corps, attendu):
    llm = voie_llm(domaine, service, corps)
    passerelle = voie_passerelle(domaine, service, corps)
    directe = voie_directe(domaine, service, corps)
    assert (llm, passerelle, directe) == (attendu, attendu, attendu)


@pytest.mark.parametrize("domaine,service,corps,attendu",
                         [c for c in CAS if not c[3] and c[0] in ("tele_connectee", "switch", "light")])
def test_meme_motif_de_refus_sur_les_deux_voies(reglages, domaine, service, corps, attendu):
    """Le texte du refus de la voie LLM contient celui de la passerelle : une seule source."""
    refus = acces.controler_service(domaine, service, corps,
                                    services_permis=liste_blanche.SERVICES_PERMIS.get(domaine))
    assert refus
    passerelle = acces.verifier_requete_ha("POST", f"/api/services/{domaine}/{service}", corps)
    assert passerelle == refus
    donnees = {k: v for k, v in corps.items() if k != "entity_id"}
    retour = _ha().service(domaine, service, corps.get("entity_id"), donnees)
    if refus.genre in ("donnees", "securite"):
        assert str(refus) in retour["erreur"]
    else:
        assert "erreur" in retour


# ---------------------------------------------------------------------------------------------------------------
# Une seule copie
# ---------------------------------------------------------------------------------------------------------------

def test_une_seule_table_pour_le_llm_et_la_passerelle():
    assert A.SERVICES_PERMIS is liste_blanche.SERVICES_PERMIS
    assert A.DOMAINES_HORS_LLM is liste_blanche.DOMAINES_HORS_LLM


def test_la_passerelle_applique_la_table_aux_domaines_de_l_appli():
    for domaine in liste_blanche.DOMAINES_HORS_LLM:
        hors_table = "reboot" if domaine == "tele_connectee" else "learn_command" if domaine == "remote" else "reload"
        assert hors_table not in liste_blanche.SERVICES_PERMIS[domaine]
        assert acces.verifier_requete_ha("POST", f"/api/services/{domaine}/{hors_table}",
                                         {"entity_id": TELE})


def test_l_exemple_ouvre_les_applis_de_la_section_reglages():
    for app in liste_blanche.REGLAGES.get("applis") or []:
        assert liste_blanche.refus_reglage("tele_connectee", "launch_app", {"entity_id": TELE, "app": app}) is None
    assert liste_blanche.refus_reglage("tele_connectee", "launch_app", {"entity_id": TELE, "app": "Appli inconnue"})


def test_regle_absente_regle_inactive():
    """Sans clé dans les réglages, rien n'est restreint de plus que la table et securite.py."""
    vide = {}
    assert liste_blanche.refus_reglage("switch", "turn_on", {"entity_id": PRISE_HORS_LISTE}, vide) is None
    assert liste_blanche.refus_reglage("tele_connectee", "launch_app", {"entity_id": TELE, "app": "x"}, vide) is None
    assert liste_blanche.refus_reglage("light", "turn_on", {"entity_id": LAMPE, "flash": "long"}, vide) is None


def test_reglage_mal_forme_ne_leve_pas_et_ne_restreint_pas():
    for mal_forme in ({"applis": "Netflix"}, {"interrupteurs": 3}, {"attributs_refuses": ["flash"]},
                      {"attributs_refuses": {"light.turn_on": "flash"}}):
        assert liste_blanche.refus_reglage("light", "turn_on", {"entity_id": LAMPE, "flash": "x"}, mal_forme) is None


def test_device_id_et_domaines_interdits_hors_de_portee_des_reglages(monkeypatch):
    """Aucun réglage de la maison ne rouvre ce que securite.py et DOMAINES_INTERDITS ferment."""
    monkeypatch.setattr(liste_blanche, "REGLAGES", {"interrupteurs": [PRISE_LISTEE], "applis": ["Netflix"]})
    assert acces.controler_service("light", "turn_on", {"entity_id": LAMPE, "device_id": "abcdef0123"})
    for domaine in ("lock", "alarm_control_panel"):
        assert acces.controler_service(domaine, "x", {"entity_id": f"{domaine}.x"})
