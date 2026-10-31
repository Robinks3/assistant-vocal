"""Liste blanche élargie (décision D6 du 26/10/2026, S-F1) : socle statique, complément pris à HA, périmètre du LLM.

Les cas du bloc « services » de cas_securite.json sont aussi lus par SecuriteTest.kt, contre le dictionnaire exporté."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import acces
import assistant as A
import securite

CAS = json.loads((Path(__file__).parent / "cas_securite.json").read_text(encoding="utf-8"))
SERVICES = CAS["services"]


def ha_essai():
    ha = A.HomeAssistant("http://exemple.invalid", "x")
    ha.essai = True
    return ha


@pytest.mark.parametrize("cas", SERVICES, ids=lambda c: c["note"])
def test_table_statique(cas):
    assert (cas["service"] in A.SERVICES_PERMIS.get(cas["domaine"], set())) == cas["permis"]


@pytest.mark.parametrize("cas", SERVICES, ids=lambda c: c["note"])
def test_service_du_serveur(cas):
    """Même verdict par HomeAssistant.service (chemin du LLM et des routines), en essai, sans réseau."""
    res = ha_essai().service(cas["domaine"], cas["service"], f"{cas['domaine']}.exemple")
    assert ("erreur" not in res) == cas["permis"], res


def test_chaque_domaine_a_un_cas_permis_et_un_refuse():
    permis = {c["domaine"] for c in SERVICES if c["permis"]}
    refuses = {c["domaine"] for c in SERVICES if not c["permis"]}
    ajoutes = set(A.SERVICES_PERMIS) - {"light", "tele_connectee"}
    assert ajoutes <= permis, ajoutes - permis
    assert ajoutes <= refuses, ajoutes - refuses


def test_aucun_domaine_interdit_dans_la_table():
    assert not set(A.SERVICES_PERMIS) & acces.DOMAINES_INTERDITS


def test_aucun_service_d_ecriture_dans_la_table():
    for domaine, services in A.SERVICES_PERMIS.items():
        for service in services:
            assert service not in A.NOMS_ECARTES and not service.startswith("reload"), f"{domaine}.{service}"
    for exclu in A.SERVICES_ECARTES:
        domaine, service = exclu.split(".")
        assert service not in A.SERVICES_PERMIS.get(domaine, set()), exclu


# ---------------------------------------------------------------- périmètre du LLM (inchangé par D6)

def test_contexte_du_llm_inchange():
    assert A.DOMAINES_CONTEXTE == ["binary_sensor", "climate", "cover", "fan", "input_boolean", "light",
                                   "media_player", "music_assistant", "scene", "script", "sensor", "vacuum",
                                   "weather"]


def test_enum_de_l_outil_inchange():
    enum = A.OUTILS[0]["function"]["parameters"]["properties"]["domaine"]["enum"]
    assert enum == ["button", "climate", "cover", "fan", "input_boolean", "light", "media_player",
                    "music_assistant", "scene", "script", "switch", "vacuum"]


def cerveau(ha):
    return A.Cerveau({"llm_modele": "qwen", "llm_url": "http://llm"}, ha)


@pytest.mark.parametrize("domaine,service", [("humidifier", "turn_on"), ("camera", "turn_off"),
                                             ("automation", "trigger"), ("input_number", "set_value"),
                                             ("remote", "turn_on"), ("valve", "open_valve")])
def test_le_llm_n_appelle_pas_un_domaine_hors_de_son_schema(domaine, service):
    """Un modèle peut sortir de l'enum du schéma : l'aiguillage refuse les domaines que la table permet mais que
    le LLM ne voit pas."""
    ha = ha_essai()
    res = cerveau(ha).executer_outil("appeler_service", {"domaine": domaine, "service": service,
                                                           "entity_id": f"{domaine}.x"},
                                     "", {"appeler_service"}, [], [])
    assert "erreur" in res and "non disponible par la voix" in res["erreur"]


def test_le_llm_garde_ses_domaines_et_les_nouveaux_services():
    ha = ha_essai()
    for domaine, service in (("fan", "oscillate"), ("climate", "set_fan_mode"), ("cover", "toggle"),
                             ("switch", "toggle"), ("vacuum", "clean_spot")):
        res = cerveau(ha).executer_outil("appeler_service", {"domaine": domaine, "service": service,
                                                               "entity_id": f"{domaine}.x"},
                                         "", {"appeler_service"}, [], [])
        assert res == {"ok": True}, (domaine, service, res)


def test_domaine_interdit_garde_son_message():
    res = cerveau(ha_essai()).executer_outil("appeler_service", {"domaine": "lock", "service": "unlock",
                                                                   "entity_id": "lock.porte"},
                                             "", {"appeler_service"}, [], [])
    assert "interdit" in res["erreur"]


def test_entite_glissee_dans_les_donnees_est_controlee():
    """Une cible passée dans « donnees » plutôt que dans entity_id vérifie aussi la liste des appareils du LLM."""
    ha = ha_essai()
    ha.entites_llm = {"light.salon_plafond"}
    res = ha.service("light", "turn_on", None, {"entity_id": "light.inconnue"})
    assert "absente de la liste" in res["erreur"]
    assert ha.service("light", "turn_on", None, {"entity_id": "light.salon_plafond"}) == {"ok": True}


# ---------------------------------------------------------------- complément pris à HA (GET /api/services)

def service(cible=None, champs=None):
    f = {"fields": champs or {}}
    if cible is not None:
        f["target"] = cible
    return f


def cible_domaine(domaine):
    return {"entity": [{"domain": [domaine]}]}


LISTE_HA = [
    {"domain": "fan", "services": {
        "turn_on": service(cible_domaine("fan")),  # déjà dans le socle
        "set_timer_special": service(cible_domaine("fan"), {"duree": {"selector": {"number": {}}}}),
        "reload": service(),
        "copier_vers": service(cible_domaine("fan"), {"autre": {"selector": {"entity": {"domain": "light"}}}}),
        "sans_cible": service(),
        "cible_autre_domaine": service(cible_domaine("light")),
        "avec_device": service({"device": [{}]}),
    }},
    {"domain": "humidifier", "services": {"mode_nuit": service(cible_domaine("humidifier"))}},
    {"domain": "demo_integration", "services": {"agir": service({"entity": [{"integration": "demo_integration"}]})}},
    {"domain": "lock", "services": {"unlock": service(cible_domaine("lock"))}},
    {"domain": "homeassistant", "services": {"restart": service()}},
    {"domain": "update", "services": {"install": service(cible_domaine("update"))}},
    {"domain": "camera", "services": {"snapshot": service(cible_domaine("camera")),
                                      "play_stream": service(cible_domaine("camera")),
                                      "ptz": service(cible_domaine("camera"))}},
    {"domain": "mqtt", "services": {"publish": service()}},
    {"domain": "media_player", "services": {"volume_up": service(cible_domaine("media_player")),
                                            "join": service(cible_domaine("media_player")),
                                            "play_media": service(cible_domaine("media_player")),
                                            "etrange": service(cible_domaine("media_player"),
                                                               {"group_members": {"selector": {"entity": {}}}})}},
    {"domain": "valve", "services": {"set_valve_position": service(cible_domaine("valve"))}},
]


def test_complement_de_ha_filtre():
    trouves = A.services_depuis_ha(LISTE_HA)
    assert trouves["fan"] == {"set_timer_special"}
    assert trouves["humidifier"] == {"mode_nuit"}
    assert trouves["demo_integration"] == {"agir"}
    assert trouves["camera"] == {"ptz"}
    assert "valve" not in trouves  # déjà dans le socle
    for refuse in ("lock", "homeassistant", "update", "mqtt"):
        assert refuse not in trouves
    # media_player : ni join, ni play_media, ni le service qui désigne d'autres lecteurs dans ses données
    assert trouves.get("media_player", set()) <= {"volume_up"}


def test_complement_de_ha_volume_up_jamais_sous_plafond(monkeypatch):
    liste = [{"domain": "media_player", "services": {"volume_up": service(cible_domaine("media_player"))}}]
    monkeypatch.setattr(A, "SERVICES_PERMIS", {**A.SERVICES_PERMIS, "media_player": {"volume_set"}})
    monkeypatch.setattr(securite, "VOLUME_MAX", 0.5)
    assert A.services_depuis_ha(liste) == {}
    monkeypatch.setattr(securite, "VOLUME_MAX", 1.0)
    assert A.services_depuis_ha(liste) == {"media_player": {"volume_up"}}


@pytest.mark.parametrize("brut", [None, {}, "x", 5, [None], [{"domain": 5}], [{"domain": "fan", "services": []}],
                                  [{"domain": "fan", "services": {"x": 5}}], [{"domain": "fan", "services": {"x y": {}}}]])
def test_complement_de_ha_illisible(brut):
    assert A.services_depuis_ha(brut) == {}


class ClientServices:
    def __init__(self, reponse=None, erreur=None, statut=200):
        self.reponse, self.erreur, self.statut, self.urls = reponse, erreur, statut, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if self.erreur:
            raise self.erreur

        def levee():
            if self.statut >= 400:
                raise RuntimeError(f"HTTP {self.statut}")
        return SimpleNamespace(status_code=self.statut, raise_for_status=levee, json=lambda: self.reponse)


def ha_avec(client):
    ha = A.HomeAssistant("http://exemple.invalid", "x")
    ha.client = client
    return ha


def test_charger_services():
    client = ClientServices(LISTE_HA)
    ha = ha_avec(client)
    assert ha.services_permis("humidifier") == A.SERVICES_PERMIS["humidifier"]  # avant le chargement : socle seul
    ajoutes = ha.charger_services()
    assert ajoutes == sum(len(s) for s in ha.services_dynamiques.values()) > 0
    assert client.urls == ["http://exemple.invalid/api/services"]
    assert "mode_nuit" in ha.services_permis("humidifier")
    assert "set_timer_special" in ha.services_permis("fan")
    assert "oscillate" in ha.services_permis("fan")  # le socle reste


def test_service_dynamique_passe_par_la_securite():
    ha = ha_avec(ClientServices(LISTE_HA))
    ha.essai = True
    ha.charger_services()
    assert ha.service("humidifier", "mode_nuit", "humidifier.chambre") == {"ok": True}
    assert "erreur" in ha.service("humidifier", "mode_nuit", None, {"device_id": "abc"})
    assert "erreur" in ha.service("humidifier", "mode_nuit", None, {"floor_id": "rdc"})
    assert "erreur" in ha.service("humidifier", "mode_nuit", None, {"label_id": "tout"})


@pytest.mark.parametrize("client", [ClientServices(erreur=ConnectionError("injoignable")),
                                    ClientServices(erreur=TimeoutError()),
                                    ClientServices(statut=503),
                                    ClientServices(reponse="pas une liste"),
                                    ClientServices(reponse=None)])
def test_ha_injoignable_le_socle_suffit(client):
    ha = ha_avec(client)
    assert ha.charger_services() == 0
    assert ha.services_dynamiques == {}
    assert ha.services_permis("fan") == A.SERVICES_PERMIS["fan"]
    ha.essai = True
    assert ha.service("fan", "oscillate", "fan.salon") == {"ok": True}


def test_complement_remis_a_zero_si_ha_tombe_ensuite():
    ha = ha_avec(ClientServices(LISTE_HA))
    ha.charger_services()
    assert ha.services_dynamiques
    ha.client = ClientServices(erreur=ConnectionError())
    assert ha.charger_services() == 0
    assert ha.services_dynamiques == {}
