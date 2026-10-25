"""Réglages fins de la télé et des lampes (0.30.0) : services permis, URL en https, device_id et clés de light.turn_on."""
import pytest

import acces
import assistant as A

TELE = "media_player.exemple70"
V = acces.verifier_requete_ha

# (domaine, service, corps) de chaque service ouvert au lot 1
NOUVEAUX = [
    ("domaine_tele", "launch_app", {"entity_id": TELE, "url": "https://www.netflix.com/title/80100172"}),
    ("domaine_tele", "send_text_input", {"entity_id": TELE, "text": "docteur"}),
    ("domaine_tele", "set_picture_setting", {"entity_id": TELE, "setting": "brightness", "value": 40}),
    ("remote", "send_command", {"entity_id": "remote.salon", "command": "KEY_HOME"}),
    ("select", "select_option", {"entity_id": "select.salon_mode", "option": "Cinéma"}),
]


def _ha():
    ha = A.HomeAssistant("http://exemple.invalid", "x")
    ha.essai = True
    return ha


@pytest.mark.parametrize("domaine,service,corps", NOUVEAUX)
def test_service_accepte_par_le_serveur(domaine, service, corps):
    assert service in A.SERVICES_PERMIS[domaine]
    donnees = {k: v for k, v in corps.items() if k != "entity_id"}
    assert _ha().service(domaine, service, corps["entity_id"], donnees) == {"ok": True}


@pytest.mark.parametrize("domaine,service,corps", NOUVEAUX)
def test_service_accepte_par_la_passerelle(domaine, service, corps):
    assert V("POST", f"/api/services/{domaine}/{service}", corps) is None


@pytest.mark.parametrize("domaine,service,corps", NOUVEAUX)
def test_device_id_toujours_refuse(domaine, service, corps):
    avec = {**corps, "device_id": "abcdef0123456789"}
    assert V("POST", f"/api/services/{domaine}/{service}", avec)
    donnees = {k: v for k, v in avec.items() if k != "entity_id"}
    assert "erreur" in _ha().service(domaine, service, corps["entity_id"], donnees)


def test_service_voisin_non_ouvert():
    for domaine, service in (("domaine_tele", "reboot"), ("remote", "turn_off"), ("select", "select_first"),
                             ("remote", "learn_command")):
        assert service not in A.SERVICES_PERMIS[domaine]
        assert "erreur" in _ha().service(domaine, service, "x.y")


def test_domaines_interdits_toujours_refuses():
    for domaine in ("lock", "alarm_control_panel", "homeassistant", "shell_command"):
        assert V("POST", f"/api/services/{domaine}/x", {"entity_id": "x.y"})


def test_nouveaux_domaines_hors_contexte_du_llm():
    for domaine in ("domaine_tele", "remote", "select"):
        assert domaine not in A.DOMAINES_CONTEXTE


@pytest.mark.parametrize("url", ["http://exemple.org/a", "javascript:alert(1)", "data:text/html,x", "HTTP://x.fr",
                                 "ftp://x.fr", "//x.fr", "https://", "https://x.fr/a b", "https://x.fr/\n", "",
                                 None, 5, ["https://x.fr"]])
def test_launch_app_url_non_https_refusee(url):
    corps = {"entity_id": TELE, "url": url}
    assert V("POST", "/api/services/domaine_tele/launch_app", corps)
    donnees = {"url": url}
    resultat = _ha().service("domaine_tele", "launch_app", TELE, donnees)
    assert "erreur" in resultat and "https://" in resultat["erreur"]


def test_launch_app_autre_champ_avec_schema_refuse():
    corps = {"entity_id": TELE, "url": "https://x.fr/a", "app": "javascript:alert(1)"}
    assert V("POST", "/api/services/domaine_tele/launch_app", corps)
    assert V("POST", "/api/services/domaine_tele/launch_app", {"entity_id": TELE, "app": "Netflix"}) is None


def test_launch_app_https_passe():
    assert V("POST", "/api/services/domaine_tele/launch_app", {"entity_id": TELE, "url": "https://x.fr/a?b=1"}) is None


def test_controle_https_limite_a_launch_app():
    assert V("POST", "/api/services/domaine_tele/send_text_input",
             {"entity_id": TELE, "text": "http://exemple.org"}) is None


def test_light_turn_on_flash_et_effect_passent():
    corps = {"entity_id": "light.exemple6", "flash": "short", "effect": "colorloop"}
    assert V("POST", "/api/services/light/turn_on", corps) is None
    donnees = {"flash": "short", "effect": "colorloop"}
    assert _ha().service("light", "turn_on", "light.exemple6", donnees) == {"ok": True}


def test_llm_ne_voit_pas_les_domaines_de_reglage():
    enum = A.OUTILS[0]["function"]["parameters"]["properties"]["domaine"]["enum"]
    for domaine in ("domaine_tele", "remote", "select"):
        assert domaine not in enum
    assert "light" in enum


def test_launch_app_valeur_imbriquee_ou_invisible_refusee():
    base = {"entity_id": TELE, "url": "https://x.fr/a"}
    assert V("POST", "/api/services/domaine_tele/launch_app", {**base, "app": {"u": "javascript:1"}})
    assert V("POST", "/api/services/domaine_tele/launch_app", {**base, "app": ["x"]})
    assert V("POST", "/api/services/domaine_tele/launch_app", {**base, "app": "\u200bNetflix"})
    assert V("POST", "/api/services/domaine_tele/launch_app", {**base, "app": "//x.fr"})
    assert V("POST", "/api/services/domaine_tele/launch_app", None)
