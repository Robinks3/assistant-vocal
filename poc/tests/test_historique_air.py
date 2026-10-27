"""Historique de l'air d'une pièce (S-L8) : bornes de temps, choix des capteurs, conversion de la réponse de Home
Assistant, réduction des points par moyenne, trous, puis le message du serveur et sa liste blanche."""
import asyncio
import json
import time

import pytest

import acces
import historique_air as AH

T0 = 1790000000          # début des cas, en secondes Unix
HEURE = 3600


def iso(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


# ------------------------------------------------------------------ durée et bornes
@pytest.mark.parametrize("brut,attendu", [
    (None, 24), (24, 24), (6, 6), (168, 168), (169, 168), (100000, 168), (0, 1), (-5, 1), (0.4, 1), (5.6, 6),
    ("24", 24), ("beaucoup", 24), (True, 24), (float("nan"), 24), ([6], 24), ({"h": 6}, 24)])
def test_heures_bornees(brut, attendu):
    assert AH.heures(brut) == attendu


def test_bornes_finissent_a_maintenant_et_plafonnent_a_sept_jours():
    assert AH.bornes(T0, 6) == (T0 - 6 * HEURE, T0)
    debut, fin = AH.bornes(T0, 24)
    assert fin - debut == 24 * HEURE
    debut, fin = AH.bornes(T0, 100000)
    assert fin - debut == 7 * 24 * HEURE
    debut, fin = AH.bornes(T0, None)
    assert fin - debut == 24 * HEURE


def test_requete_historique():
    chemin, params = AH.requete(T0 - 6 * HEURE, T0, ["sensor.a", "sensor.b"])
    assert chemin.startswith("/api/history/period/")
    assert "+" not in chemin and chemin.endswith("%2B00%3A00") is False  # le décalage est encodé, pas de + brut
    assert params["filter_entity_id"] == "sensor.a,sensor.b"
    assert params["end_time"] == iso(T0)
    assert "minimal_response" in params and "no_attributes" in params


# ------------------------------------------------------------------ choix des capteurs
def capteur(ident, classe, zone="", zone_appareil="", appareil=""):
    return {"id": ident, "nom": ident, "classe": classe, "etat": "1", "unite": "", "zone": zone,
            "zone_appareil": zone_appareil, "appareil": appareil, "modifie": T0}


CORRESP = {"salon": ["coin_repas", "salon"], "couloir": ["couloir"], "chambre": ["chambre_camille"]}


def test_entites_de_piece_par_zone_et_grandeur():
    releve = {"capteurs": [
        capteur("sensor.co2_salon", "carbon_dioxide", zone="salon"),
        capteur("sensor.pm_salon", "pm25", zone="coin_repas"),
        capteur("sensor.t_salon", "temperature", zone="salon"),
        capteur("sensor.h_salon", "humidity", zone_appareil="salon"),
        capteur("sensor.co2_couloir", "carbon_dioxide", zone="couloir"),
        capteur("sensor.lux_salon", "illuminance", zone="salon"),
        capteur("sensor.aqi_salon", "aqi", zone="salon"),
        capteur("sensor.ailleurs", "temperature", zone="cave")]}
    assert AH.entites_de_piece(releve, CORRESP, "salon", []) == {
        "co2": ["sensor.co2_salon"], "pm25": ["sensor.pm_salon"], "temperature": ["sensor.t_salon"],
        "humidite": ["sensor.h_salon"]}
    assert AH.entites_de_piece(releve, CORRESP, "couloir", []) == {"co2": ["sensor.co2_couloir"]}


def test_thermometre_dedie_prioritaire_comme_sur_la_carte():
    releve = {"capteurs": [
        capteur("sensor.t_combine", "temperature", zone="salon", appareil="air"),
        capteur("sensor.co2_combine", "carbon_dioxide", zone="salon", appareil="air"),
        capteur("sensor.t_dedie", "temperature", zone="salon", appareil="therm"),
        capteur("sensor.h_dedie", "humidity", zone="salon", appareil="therm")]}
    sortie = AH.entites_de_piece(releve, CORRESP, "salon", [])
    assert sortie["temperature"] == ["sensor.t_dedie"]
    assert sortie["humidite"] == ["sensor.h_dedie"]
    assert sortie["co2"] == ["sensor.co2_combine"]


def test_piece_inconnue_protegee_ou_sans_capteur():
    releve = {"capteurs": [capteur("sensor.t_chambre", "temperature", zone="chambre_camille")]}
    for piece in ("inconnue", None, 3, ["salon"], {"salon": 1}, ""):
        with pytest.raises(AH.ErreurAir, match="inconnue"):
            AH.entites_de_piece(releve, CORRESP, piece, [])
    with pytest.raises(AH.ErreurAir, match="protégée"):
        AH.entites_de_piece(releve, CORRESP, "chambre", ["chambre_camille"])
    with pytest.raises(AH.ErreurAir, match="protégée"):
        AH.entites_de_piece(releve, CORRESP, "chambre", ["Chambre"])   # l'identifiant de la pièce lui-même
    with pytest.raises(AH.ErreurAir, match="aucun capteur"):
        AH.entites_de_piece(releve, CORRESP, "couloir", [])


def test_une_entite_au_nom_inattendu_n_est_jamais_demandee():
    releve = {"capteurs": [
        capteur("sensor.ok", "temperature", zone="salon"),
        capteur("sensor.a,light.salon", "temperature", zone="salon"),
        capteur("light.salon", "temperature", zone="salon"),
        capteur("sensor.Majuscule", "temperature", zone="salon"),
        capteur("sensor.x/../y", "temperature", zone="salon"),
        capteur(None, "temperature", zone="salon")]}
    assert AH.entites_de_piece(releve, CORRESP, "salon", [])["temperature"] == ["sensor.ok"]


def test_nombre_d_entites_par_grandeur_borne():
    releve = {"capteurs": [capteur(f"sensor.co2_{i}", "carbon_dioxide", zone="salon") for i in range(30)]}
    assert len(AH.entites_de_piece(releve, CORRESP, "salon", [])["co2"]) == AH.MAX_ENTITES_PAR_GRANDEUR


# ------------------------------------------------------------------ conversion de la réponse de Home Assistant
def test_lire_historique_reponse_minimale():
    reponse = [
        [{"entity_id": "sensor.a", "state": "400", "last_changed": iso(T0)},
         {"state": "unavailable", "last_changed": iso(T0 + 600)},
         {"state": "450.5", "last_changed": iso(T0 + 1200)},
         {"state": "unknown", "last_changed": iso(T0 + 1800)},
         {"state": "nan", "last_changed": iso(T0 + 2400)},
         {"state": "texte", "last_changed": iso(T0 + 3000)}],
        [{"entity_id": "sensor.pirate", "state": "1", "last_changed": iso(T0)}],
        [{"entity_id": "sensor.b", "state": "7", "last_updated": iso(T0 + 5).replace("+00:00", "Z")}],
        "n'importe quoi", [], [None, 4], [{"state": "1"}]]
    h = AH.lire_historique(reponse, {"sensor.a", "sensor.b"})
    assert set(h) == {"sensor.a", "sensor.b"}
    assert h["sensor.a"] == [(T0, 400.0), (T0 + 600, None), (T0 + 1200, 450.5), (T0 + 1800, None),
                             (T0 + 2400, None), (T0 + 3000, None)]
    assert h["sensor.b"] == [(T0 + 5, 7.0)]


def test_lire_historique_trie_et_ignore_les_horodatages_illisibles():
    reponse = [[{"entity_id": "sensor.a", "state": "2", "last_changed": iso(T0 + 100)},
                {"state": "1", "last_changed": iso(T0)},
                {"state": "9", "last_changed": "hier"},
                {"state": "9"}, {"state": "9", "last_changed": 12}]]
    assert AH.lire_historique(reponse, {"sensor.a"})["sensor.a"] == [(T0, 1.0), (T0 + 100, 2.0)]
    assert AH.lire_historique({"erreur": 1}, {"sensor.a"}) == {}
    assert AH.lire_historique(None, {"sensor.a"}) == {}


# ------------------------------------------------------------------ réduction par moyenne
def test_moyenne_ponderee_par_le_temps():
    # 4 intervalles d'une heure. 400 jusqu'à T0+1800, puis 800 : le premier intervalle vaut 600.
    pts = [(T0, 400.0), (T0 + 1800, 800.0)]
    m = AH.moyennes_par_intervalle(pts, T0, T0 + 4 * HEURE, 4, tenue=10 * HEURE)
    assert m == [600.0, 800.0, 800.0, 800.0]


def test_un_etat_n_est_pas_tenu_au_dela_de_la_perennite():
    # 500 tenu 2 h : trou ensuite, pas de valeur inventée.
    m = AH.moyennes_par_intervalle([(T0, 500.0)], T0, T0 + 5 * HEURE, 5, tenue=2 * HEURE)
    assert m == [500.0, 500.0, None, None, None]


def test_indisponible_fait_un_trou_et_jamais_un_zero():
    pts = [(T0, 500.0), (T0 + HEURE, None), (T0 + 2 * HEURE, 700.0)]
    m = AH.moyennes_par_intervalle(pts, T0, T0 + 3 * HEURE, 3, tenue=5 * HEURE)
    assert m == [500.0, None, 700.0]
    assert 0 not in m


def test_etat_anterieur_au_debut_est_tenu():
    # Home Assistant donne l'état du début ; un état plus ancien reste pris sur la partie visible.
    m = AH.moyennes_par_intervalle([(T0 - HEURE, 300.0)], T0, T0 + 2 * HEURE, 2, tenue=10 * HEURE)
    assert m == [300.0, 300.0]


def test_etat_apres_la_fin_ou_sans_duree_est_ignore():
    pts = [(T0 + 10 * HEURE, 9.0), (T0 + HEURE, 4.0), (T0 + HEURE, 5.0)]
    pts.sort()
    m = AH.moyennes_par_intervalle(pts, T0, T0 + 2 * HEURE, 2, tenue=10 * HEURE)
    assert m[0] is None and m[1] == 5.0   # deux états au même instant : le premier ne dure pas


def test_serie_moyenne_des_capteurs_et_omet_les_intervalles_vides():
    historique = {"sensor.a": [(T0, 400.0)], "sensor.b": [(T0, 600.0), (T0 + HEURE, None)]}
    s = AH.serie(historique, ["sensor.a", "sensor.b", "sensor.absent"], T0, T0 + 3 * HEURE, 3, tenue=10 * HEURE)
    assert s == [[T0 + 1800, 500.0], [T0 + 1800 + HEURE, 400.0], [T0 + 1800 + 2 * HEURE, 400.0]]
    s = AH.serie({"sensor.a": [(T0, 400.0), (T0 + HEURE, None)]}, ["sensor.a"], T0, T0 + 2 * HEURE, 2, tenue=10 * HEURE)
    assert s == [[T0 + 1800, 400.0]]


def test_serie_arrondie_a_une_decimale_et_bornee_en_nombre_de_points():
    long = [(T0 + i * 60, 20.0 + (i % 7) / 3) for i in range(7 * 24 * 60)]
    s = AH.serie({"sensor.a": long}, ["sensor.a"], T0, T0 + 7 * 24 * HEURE, tenue=600)
    assert 0 < len(s) <= AH.POINTS_MAX
    assert all(round(v, 1) == v for _, v in s)
    assert all(T0 < t < T0 + 7 * 24 * HEURE for t, _ in s)
    assert [t for t, _ in s] == sorted(t for t, _ in s)


def test_mettre_en_forme_une_cle_par_grandeur_mesuree():
    entites = {"co2": ["sensor.a"], "temperature": ["sensor.t"]}
    hist = {"sensor.a": [(T0, 450.0)]}
    d = AH.mettre_en_forme("salon", 6, T0, T0 + 6 * HEURE, entites, hist, nb=6)
    assert set(d) == {"piece", "heures", "debut", "fin", "pas", "series"}
    assert d["piece"] == "salon" and d["heures"] == 6 and d["debut"] == T0 and d["fin"] == T0 + 6 * HEURE
    assert d["pas"] == HEURE
    assert set(d["series"]) == {"co2", "temperature"}
    assert d["series"]["temperature"] == []                     # capteur sans historique : liste vide
    assert d["series"]["co2"][0] == [T0 + 1800, 450.0]
    json.dumps(d)


# ------------------------------------------------------------------ serveur
class FausseReponse:
    def __init__(self, code, contenu):
        self.status_code = code
        self.text = contenu if isinstance(contenu, str) else json.dumps(contenu)
        self._contenu = contenu

    def json(self):
        if isinstance(self._contenu, str):
            return json.loads(self._contenu)
        return self._contenu


class FauxWs:
    def __init__(self):
        self.envois = []

    async def send(self, texte):
        self.envois.append(json.loads(texte))


class FauxClient:
    def __init__(self, releve, historique, panne=None):
        self.releve, self.historique, self.panne = releve, historique, panne
        self.posts, self.gets = [], []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return self.releve

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, params))
        if self.panne:
            raise self.panne
        return self.historique


class FauxHa:
    def __init__(self, client):
        self.url, self.client = "http://ha.test:8123", client


class FauxAssistant:
    def __init__(self, ha):
        self.ha = ha


def _releve():
    m = int(time.time())
    return {"maintenant": m, "capteurs": [
        capteur("sensor.salon_co2", "carbon_dioxide", zone="salon"),
        capteur("sensor.salon_pm", "pm25", zone="salon"),
        capteur("sensor.salon_t", "temperature", zone="salon", appareil="air"),
        capteur("sensor.camille_t", "temperature", zone="chambre_camille"),
        capteur("sensor.autre_co2", "carbon_dioxide", zone="cuisine_autre")]}


def _satellite(ha):
    import serveur_satellite as S
    sat = object.__new__(S.Satellite)
    m = object.__new__(S.Moteur)
    m.sante, m.sante_personnes, m.meteo_mer, m.vent_mesure = None, frozenset(), None, None
    m.assistant = FauxAssistant(ha)
    sat.ws, sat.moteur, sat.nom = FauxWs(), m, "essai"
    sat.identite, sat.chiffre = None, False
    return sat


@pytest.fixture
def corresp(monkeypatch):
    import mesures
    monkeypatch.setattr(mesures, "correspondance", lambda config: {
        "salon": ["salon"], "chambre": ["chambre_camille"], "vide": ["rien"]})


def _historique():
    t = int(time.time()) - 3 * HEURE
    return [[{"entity_id": "sensor.salon_co2", "state": "500", "last_changed": iso(t)},
             {"state": "900", "last_changed": iso(t + HEURE)}],
            [{"entity_id": "sensor.salon_pm", "state": "unavailable", "last_changed": iso(t)}],
            [{"entity_id": "light.pirate", "state": "on", "last_changed": iso(t)}]]


def test_message_air_historique_servi(corresp, capsys):
    client = FauxClient(FausseReponse(200, _releve()), FausseReponse(200, _historique()))
    sat = _satellite(FauxHa(client))
    asyncio.run(sat.repondre_air_historique({"id": 7, "piece": "salon", "heures": 6}))
    assert len(sat.ws.envois) == 1
    e = sat.ws.envois[0]
    assert set(e) == {"etat", "id", "donnees"} and e["etat"] == "air_historique" and e["id"] == 7
    d = e["donnees"]
    assert d["piece"] == "salon" and d["heures"] == 6 and d["fin"] - d["debut"] == 6 * HEURE
    assert set(d["series"]) == {"co2", "pm25", "temperature", "humidite"} - {"humidite"}
    assert d["series"]["co2"] and d["series"]["pm25"] == [] and d["series"]["temperature"] == []
    valeurs = [v for _, v in d["series"]["co2"]]
    # 500 puis 900 : l'intervalle qui contient le changement est une moyenne pondérée entre les deux.
    assert min(valeurs) == 500.0 and max(valeurs) == 900.0 and all(500.0 <= v <= 900.0 for v in valeurs)
    # Une seule requête d'historique, limitée aux capteurs de la pièce (jamais l'entité d'une autre pièce ni le pirate).
    assert len(client.gets) == 1
    url, params = client.gets[0]
    assert url.startswith("http://ha.test:8123/api/history/period/")
    assert sorted(params["filter_entity_id"].split(",")) == ["sensor.salon_co2", "sensor.salon_pm", "sensor.salon_t"]
    assert "[essai] air_historique : salon sur 6 h" in capsys.readouterr().out


def test_le_client_ne_choisit_ni_entite_ni_duree_hors_bornes(corresp):
    client = FauxClient(FausseReponse(200, _releve()), FausseReponse(200, _historique()))
    sat = _satellite(FauxHa(client))
    asyncio.run(sat.repondre_air_historique({
        "id": 1, "piece": "salon", "heures": 99999, "entites": ["sensor.autre_co2"], "filter_entity_id": "light.x",
        "entity_id": "sensor.autre_co2"}))
    d = sat.ws.envois[0]["donnees"]
    assert d["heures"] == 168 and d["fin"] - d["debut"] == 168 * HEURE
    _, params = client.gets[0]
    assert "autre_co2" not in params["filter_entity_id"] and "light" not in params["filter_entity_id"]


@pytest.mark.parametrize("piece,erreur", [("inconnue", "pièce inconnue"), (None, "pièce inconnue"),
                                           ("vide", "aucun capteur de mesure dans cette pièce")])
def test_message_air_historique_pieces_refusees(corresp, piece, erreur):
    client = FauxClient(FausseReponse(200, _releve()), FausseReponse(200, _historique()))
    sat = _satellite(FauxHa(client))
    asyncio.run(sat.repondre_air_historique({"id": 2, "piece": piece}))
    assert sat.ws.envois == [{"etat": "air_historique", "id": 2, "erreur": erreur}]
    assert client.gets == []


def test_piece_protegee_refusee_sans_appel_d_historique(corresp, monkeypatch):
    import securite
    monkeypatch.setattr(securite, "PROTEGER_OCCUPANT", True)
    client = FauxClient(FausseReponse(200, _releve()), FausseReponse(200, _historique()))
    sat = _satellite(FauxHa(client))
    asyncio.run(sat.repondre_air_historique({"id": 3, "piece": "chambre", "heures": 24}))
    assert sat.ws.envois == [{"etat": "air_historique", "id": 3, "erreur": "pièce protégée"}]
    assert client.gets == []
    # Le gabarit écarte aussi la zone protégée dès Home Assistant.
    assert "chambre_camille" in client.posts[0][1]["template"]


def test_message_air_historique_erreurs_reseau(corresp, capsys):
    sat = _satellite(None)
    asyncio.run(sat.repondre_air_historique({"id": 1, "piece": "salon"}))
    assert sat.ws.envois == [{"etat": "air_historique", "id": 1, "erreur": "Home Assistant non configuré sur ce serveur"}]
    sat = _satellite(FauxHa(FauxClient(FausseReponse(500, "boum"), None)))
    asyncio.run(sat.repondre_air_historique({"id": 2, "piece": "salon"}))
    assert sat.ws.envois == [{"etat": "air_historique", "id": 2, "erreur": "relevé des capteurs indisponible"}]
    sat = _satellite(FauxHa(FauxClient(FausseReponse(200, _releve()), FausseReponse(503, "indisponible"))))
    asyncio.run(sat.repondre_air_historique({"id": 3, "piece": "salon"}))
    assert sat.ws.envois == [{"etat": "air_historique", "id": 3, "erreur": "historique indisponible"}]
    sat = _satellite(FauxHa(FauxClient(FausseReponse(200, _releve()), None, panne=ValueError("jeton secret 12345"))))
    asyncio.run(sat.repondre_air_historique({"id": 4, "piece": "salon"}))
    assert sat.ws.envois == [{"etat": "air_historique", "id": 4, "erreur": "erreur inattendue (ValueError)"}]
    assert "12345" not in capsys.readouterr().out
    sat = _satellite(FauxHa(FauxClient(FausseReponse(200, _releve()), FausseReponse(200, "pas du json"))))
    asyncio.run(sat.repondre_air_historique({"id": 5, "piece": "salon"}))
    assert sat.ws.envois[0]["erreur"] == "erreur inattendue (JSONDecodeError)"


def test_message_air_historique_sans_correspondance(monkeypatch):
    import mesures
    monkeypatch.setattr(mesures, "correspondance", lambda config: {})
    sat = _satellite(FauxHa(FauxClient(FausseReponse(200, _releve()), FausseReponse(200, []))))
    asyncio.run(sat.repondre_air_historique({"id": 5, "piece": "salon"}))
    assert sat.ws.envois[0]["etat"] == "air_historique" and "erreur" in sat.ws.envois[0]


def test_message_air_historique_dispatche_par_recevoir_texte(corresp):
    sat = _satellite(FauxHa(FauxClient(FausseReponse(200, _releve()), FausseReponse(200, _historique()))))

    async def deroule():
        await sat.recevoir_texte(json.dumps({"type": "air_historique", "id": 9, "piece": "salon", "heures": 24}))
        for _ in range(200):
            if sat.ws.envois:
                break
            await asyncio.sleep(0.01)
    asyncio.run(deroule())
    assert sat.ws.envois and sat.ws.envois[0]["etat"] == "air_historique" and "donnees" in sat.ws.envois[0]


def test_capacite_air_historique(corresp):
    import serveur_satellite as S
    m = object.__new__(S.Moteur)
    m.sante, m.sante_personnes, m.meteo_mer, m.vent_mesure = None, frozenset(), None, None
    m.profil, m.empreinte_tls, m.vision = "ha", "", None
    m.assistant = FauxAssistant(FauxHa(None))
    assert m.capacites()["air_historique"] is True
    m.assistant = FauxAssistant(None)
    assert m.capacites()["air_historique"] is False


def test_air_historique_reserve_au_foyer():
    for role in ("administrateur", "habitant", "partage"):
        assert acces.type_permis(role, "air_historique"), role
    assert not acces.type_permis("invite", "air_historique")
