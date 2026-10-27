"""Mesures par pièce (S-L6) : seuils aux bornes, cas particuliers, gabarit de découverte et correspondance.

Les cas de cas_mesures.json sont communs avec l'appli Android (MesuresTest.kt). Leurs attendus sont écrits à la main.
"""
import asyncio
import copy
import json
from pathlib import Path

import pytest

import maison
import mesures

ICI = Path(__file__).resolve().parent
CAS = json.loads((ICI / "cas_mesures.json").read_text(encoding="utf-8"))["cas"]


def _mot(bloc):
    return bloc.get("mot") if bloc else None


def _vue(r):
    """Projection d'une pièce sur les clés comparées par les cas communs (None = absent)."""
    return {
        "statut": r["statut"], "texte": r["texte"], "couleur": r["couleur"], "alerte": r["alerte"],
        "air_mot": _mot(r["air"]), "temperature_mot": _mot(r["temperature"]),
        "co2_mot": _mot(r["co2"]), "pm25_mot": _mot(r["pm25"]),
        "co2_suivant": r["co2"].get("suivant") if r["co2"] else None,
        "pm25_suivant": r["pm25"].get("suivant") if r["pm25"] else None,
    }


@pytest.mark.parametrize("cas", CAS, ids=[c["nom"] for c in CAS])
def test_cas_communs(cas):
    releve = {"maintenant": cas["maintenant"], "capteurs": copy.deepcopy(cas["capteurs"])}
    sortie = mesures.mesures_par_piece(releve, cas["correspondance"], cas["protegees"], cas["fuseau"], cas["noms"])
    assert set(sortie) == set(cas["correspondance"])
    for piece, attendu in cas["attendu"].items():
        vue = _vue(sortie[piece])
        for cle, valeur in attendu.items():
            assert vue[cle] == valeur, f"{cas['nom']} / {piece} / {cle}"


def test_les_cas_couvrent_chaque_borne():
    noms = " ".join(c["nom"] for c in CAS)
    for v in ("799.9", "800", "1000", "1000.1", "1500", "1500.1", "8.9", "35.4", "35.5", "55.4", "55.5", "18.9", "24.1"):
        assert v in noms, v


@pytest.mark.parametrize("valeur,mot", [
    (0, "bon"), (799.9, "bon"), (800, "correct"), (1000, "correct"), (1000.1, "médiocre"), (1500, "médiocre"),
    (1500.1, "mauvais"), (5000, "mauvais")])
def test_mot_co2(valeur, mot):
    assert mesures.mot_co2(valeur) == mot


@pytest.mark.parametrize("valeur,mot", [
    (0, "bon"), (8.9, "bon"), (9, "correct"), (35.4, "correct"), (35.5, "médiocre"), (55.4, "médiocre"),
    (55.5, "mauvais")])
def test_mot_pm25(valeur, mot):
    assert mesures.mot_pm25(valeur) == mot


@pytest.mark.parametrize("valeur,mot", [(-5, "frais"), (18.9, "frais"), (19, "agréable"), (24, "agréable"),
                                        (24.1, "chaud"), (35, "chaud")])
def test_mot_temperature(valeur, mot):
    assert mesures.mot_temperature(valeur) == mot


def test_couleurs_et_mots_imposes():
    assert mesures.MOTS_AIR == ("bon", "correct", "médiocre", "mauvais")
    assert mesures.COULEURS_AIR == ("#D4E6C8", "#EDD48A", "#EE9A45", "#D6503A")
    assert mesures.SEUILS_CO2 == (800.0, 1000.0, 1500.0)
    assert mesures.SEUILS_PM25 == (9.0, 35.4, 55.4)


def test_air_pire_prend_le_pire_et_ignore_les_absents():
    assert mesures.air_pire([]) is None
    assert mesures.air_pire([None]) is None
    a = mesures.air_pire([0, None, 2, 1])
    assert (a["mot"], a["couleur"], a["aerer"]) == ("médiocre", "#EE9A45", True)
    assert mesures.air_pire([1])["aerer"] is False


def test_arrondi_demi_vers_le_haut():
    assert [mesures.arrondi(x) for x in (21.4, 21.5, 21.6, 18.5, -0.4)] == [21, 22, 22, 19, 0]


def test_heure_locale():
    assert mesures.heure_locale(1790000000, "Europe/Paris") == "16 h 13"
    assert mesures.heure_locale(1790000000, "UTC") == "14 h 13"
    assert mesures.heure_locale(1790000000, "Zone/Inconnue") == "14 h 13"


# ------------------------------------------------------------------ gabarit de découverte
def test_gabarit_contient_les_classes_utiles():
    g = mesures.gabarit([])
    for classe in ("temperature", "humidity", "carbon_dioxide", "pm25", "pm10", "aqi",
                   "volatile_organic_compounds"):
        assert f'"{classe}"' in g
    assert "states.sensor" in g
    assert "tojson" in g


def test_gabarit_lit_la_zone_de_l_entite_puis_celle_de_l_appareil():
    g = mesures.gabarit([])
    assert "area_id(s.entity_id)" in g
    assert "device_id(s.entity_id)" in g
    assert "area_id(d)" in g
    assert "'zone': ze" in g and "'zone_appareil': za" in g


def test_gabarit_n_ecrit_aucune_entite():
    g = mesures.gabarit([])
    assert "sensor." not in g.replace("states.sensor", "")


def test_gabarit_ecarte_les_zones_protegees():
    g = mesures.gabarit(["Chambre_P", "salle_p"])
    assert '["chambre_p", "salle_p"]' in g
    assert "not in protegees" in g
    # Même liste en désordre ou avec doublons : même gabarit.
    assert mesures.gabarit(["salle_p", "chambre_p", "CHAMBRE_P"]) == g


def test_gabarit_sans_zone_protegee_a_une_liste_vide():
    assert "set protegees = []" in mesures.gabarit([])


def test_gabarit_garde_les_capteurs_sans_zone_pour_que_le_moteur_les_ignore():
    # Un capteur sans aire n'est jamais écarté par Home Assistant : le moteur l'ignore faute de pièce.
    g = mesures.gabarit(["x"])
    assert "(ze or za) not in protegees" in g


def test_lire_releve():
    assert mesures.lire_releve("pas du json") is None
    assert mesures.lire_releve("[]") is None
    assert mesures.lire_releve('{"capteurs": 3}') is None
    r = mesures.lire_releve('{"maintenant": 5, "capteurs": []}')
    assert r == {"maintenant": 5, "capteurs": []}
    assert mesures.lire_releve({"maintenant": 5, "capteurs": []})["maintenant"] == 5


# ------------------------------------------------------------------ jeu d'états fictif de bout en bout
def _jeu():
    m = 1790000000
    def cap(id, classe, etat, zone="", zone_appareil="", appareil="", ago=30):
        return {"id": id, "nom": id, "classe": classe, "etat": etat, "unite": "", "zone": zone,
                "zone_appareil": zone_appareil, "appareil": appareil, "modifie": m - ago}
    return {"maintenant": m, "capteurs": [
        cap("sensor.salon_co2", "carbon_dioxide", "1200", zone="salon"),
        cap("sensor.salon_t", "temperature", "21.2", zone="salon"),
        cap("sensor.sans_aire", "temperature", "30", zone=""),
        cap("sensor.chambre_t", "temperature", "19.5", zone_appareil="chambre_1", appareil="d1"),
        cap("sensor.chambre_h", "humidity", "55", zone_appareil="chambre_1", appareil="d1"),
        cap("sensor.couloir_t", "temperature", "unavailable", zone="couloir", ago=5000),
        cap("sensor.protegee_t", "temperature", "22", zone="chambre_camille"),
    ]}


def test_jeu_etats_fictif():
    corresp = {"sejour_cuisine": ["salon"], "couloir": ["couloir"], "chambre_sacha": ["chambre_1"],
               "chambre_camille": ["chambre_camille"], "autre": ["nulle_part"]}
    out = mesures.mesures_par_piece(_jeu(), corresp, ["chambre_camille"], "Europe/Paris",
                                    {"sejour_cuisine": "Salon"})
    assert out["sejour_cuisine"]["texte"] == "21°, air médiocre"
    assert out["sejour_cuisine"]["alerte"] == "Aère la pièce Salon, CO2 1200 ppm"
    assert out["chambre_sacha"]["texte"] == "20°, pas de capteur d'air"          # 19,5 arrondi, aire d'appareil
    assert out["chambre_sacha"]["humidite"]["valeur"] == 55
    assert out["couloir"]["texte"] == "mesure absente depuis 14 h 50, pas de capteur d'air"
    assert out["chambre_camille"]["texte"] == "pièce protégée"
    assert out["chambre_camille"]["temperature"] is None
    assert out["autre"]["texte"] == "pas de capteur"
    # Le capteur sans aire (30 degrés) n'apparaît dans aucune pièce.
    assert all(30.0 != (p["temperature"] or {}).get("valeur") for p in out.values())


# ------------------------------------------------------------------ correspondance et configuration
def test_correspondance_normalise():
    c = mesures.correspondance({"correspondance_pieces": {
        "_lisez_moi": "x", "a": "Zone_A", "b": [" Z1 ", "", "z2"], "c": [], "d": 5}})
    assert c == {"a": ["zone_a"], "b": ["z1", "z2"]}


def test_correspondance_absente():
    assert mesures.correspondance({}) == {}
    assert mesures.correspondance({"correspondance_pieces": "oui"}) == {}
    assert mesures.correspondance(None) == {}


def test_config_exemple_relie_des_pieces_connues():
    c = mesures.correspondance(maison.CONFIG)
    assert c, "config-exemple/maison.json doit porter correspondance_pieces"
    pieces = json.loads((Path(maison.chemin("carte/pieces.json"))).read_text(encoding="utf-8"))["pieces"]
    ids = {p["id"] for p in pieces}
    assert set(c) <= ids


def test_config_exemple_pieces_protegees_sans_valeur():
    # La chambre protégée de l'exemple ne montre rien, même avec un capteur dans sa zone.
    c = mesures.correspondance(maison.CONFIG)
    protegees = maison.liste("zones_protegees")
    releve = {"maintenant": 1790000000, "capteurs": [
        {"id": "s", "nom": "s", "classe": "carbon_dioxide", "etat": "2000", "unite": "", "zone": "chambre_camille",
         "zone_appareil": "", "appareil": "", "modifie": 1790000000 - 10}]}
    out = mesures.mesures_par_piece(releve, c, protegees, "Europe/Paris")
    assert out["chambre_camille"]["statut"] == "protegee"
    assert out["chambre_camille"]["co2"] is None
    assert out["chambre_camille"]["alerte"] == ""


# ------------------------------------------------------------------ serveur : capacité et message
class FauxWs:
    def __init__(self):
        self.envois = []

    async def send(self, texte):
        self.envois.append(json.loads(texte))


class FausseReponse:
    def __init__(self, code, texte):
        self.status_code, self.text = code, texte


class FauxClient:
    def __init__(self, reponse=None, panne=None):
        self.reponse, self.panne, self.appels = reponse, panne, []

    def post(self, url, json=None, timeout=None):
        self.appels.append((url, json))
        if self.panne:
            raise self.panne
        return self.reponse


class FauxHa:
    def __init__(self, client):
        self.url, self.client = "http://ha.test:8123", client


class FauxAssistant:
    def __init__(self, ha):
        self.ha = ha


def _moteur(ha):
    import serveur_satellite as S
    m = object.__new__(S.Moteur)  # sans charger les modèles
    m.sante, m.sante_personnes, m.meteo_mer, m.vent_mesure = None, frozenset(), None, None
    m.assistant = FauxAssistant(ha)
    return m


def _satellite(ha):
    import serveur_satellite as S
    sat = object.__new__(S.Satellite)  # sans charger le mot de réveil
    sat.ws, sat.moteur, sat.nom = FauxWs(), _moteur(ha), "essai"
    sat.identite, sat.chiffre = None, False
    return sat


def _releve_json():
    r = _jeu()
    r["capteurs"] = [c for c in r["capteurs"] if c["zone"] != "chambre_camille"]
    return json.dumps(r)


def test_capacite_mesures():
    m = _moteur(FauxHa(FauxClient()))
    m.profil, m.empreinte_tls, m.vision = "ha", "", None
    assert m.capacites()["mesures"] is True
    m.assistant = FauxAssistant(None)
    assert m.capacites()["mesures"] is False


def test_message_mesures_servi(capsys):
    client = FauxClient(FausseReponse(200, _releve_json()))
    sat = _satellite(FauxHa(client))
    asyncio.run(sat.repondre_mesures({"id": 4}))
    assert len(sat.ws.envois) == 1
    envoi = sat.ws.envois[0]
    assert set(envoi) == {"etat", "id", "donnees"} and envoi["etat"] == "mesures" and envoi["id"] == 4
    pieces = envoi["donnees"]["pieces"]
    assert pieces["sejour_cuisine"]["texte"].startswith("21°, air ")
    # Règle 1 levée (27/10/2026) : la chambre n'est plus cachée, elle n'a simplement pas de capteur ici.
    assert pieces["chambre_camille"]["statut"] == "aucun"
    url, corps = client.appels[0]
    assert url == "http://ha.test:8123/api/template"
    assert "chambre_camille" not in corps["template"]
    assert "[essai] mesures : " in capsys.readouterr().out


def test_message_mesures_regle_active_cache_la_zone(monkeypatch):
    import securite
    monkeypatch.setattr(securite, "PROTEGER_OCCUPANT", True)
    client = FauxClient(FausseReponse(200, _releve_json()))
    sat = _satellite(FauxHa(client))
    asyncio.run(sat.repondre_mesures({"id": 4}))
    pieces = sat.ws.envois[0]["donnees"]["pieces"]
    assert pieces["chambre_camille"]["statut"] == "protegee"
    assert pieces["chambre_camille"]["temperature"] is None
    _, corps = client.appels[0]
    # Les zones protégées de l'exemple sont écartées dès Home Assistant.
    assert "chambre_camille" in corps["template"] and "not in protegees" in corps["template"]


def test_message_mesures_erreurs(capsys):
    sat = _satellite(None)
    asyncio.run(sat.repondre_mesures({"id": 1}))
    assert sat.ws.envois == [{"etat": "mesures", "id": 1, "erreur": "Home Assistant non configuré sur ce serveur"}]
    sat = _satellite(FauxHa(FauxClient(FausseReponse(500, "boum"))))
    asyncio.run(sat.repondre_mesures({"id": 2}))
    assert sat.ws.envois == [{"etat": "mesures", "id": 2, "erreur": "relevé des capteurs indisponible"}]
    sat = _satellite(FauxHa(FauxClient(FausseReponse(200, "ceci n'est pas du json"))))
    asyncio.run(sat.repondre_mesures({"id": 3}))
    assert sat.ws.envois[0]["erreur"] == "relevé des capteurs indisponible"
    sat = _satellite(FauxHa(FauxClient(panne=ValueError("jeton secret 12345"))))
    asyncio.run(sat.repondre_mesures({"id": 4}))
    assert sat.ws.envois == [{"etat": "mesures", "id": 4, "erreur": "erreur inattendue (ValueError)"}]
    assert "12345" not in capsys.readouterr().out


def test_message_mesures_sans_correspondance(monkeypatch):
    monkeypatch.setattr(mesures, "correspondance", lambda config: {})
    sat = _satellite(FauxHa(FauxClient(FausseReponse(200, _releve_json()))))
    asyncio.run(sat.repondre_mesures({"id": 5}))
    assert sat.ws.envois[0]["etat"] == "mesures" and "erreur" in sat.ws.envois[0]


def test_message_mesures_dispatche_par_recevoir_texte():
    sat = _satellite(FauxHa(FauxClient(FausseReponse(200, _releve_json()))))

    async def deroule():
        await sat.recevoir_texte(json.dumps({"type": "mesures", "id": 9}))
        for _ in range(200):
            if sat.ws.envois:
                break
            await asyncio.sleep(0.01)
    asyncio.run(deroule())
    assert sat.ws.envois and sat.ws.envois[0]["etat"] == "mesures"


def test_mesures_reservees_au_foyer():
    import acces
    for role in ("administrateur", "habitant", "partage"):
        assert acces.type_permis(role, "mesures"), role
    assert not acces.type_permis("invite", "mesures")
