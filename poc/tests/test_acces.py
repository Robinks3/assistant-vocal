"""Accès des téléphones : jetons, appairage, passerelle Home Assistant, arbitre du mot de réveil."""
import asyncio
import json

import acces


def test_jetons_fixes_et_empreinte_seule(tmp_path):
    app = acces.Appareils(tmp_path, {"a" * 20: "sacha", "c" * 20: "camille"})
    assert app.identifier("a" * 20) == "sacha"
    assert app.identifier("b" * 20) is None
    assert app.identifier("court") is None
    assert app.identifier("") is None
    assert app.identite("a" * 20) == ("sacha", "sacha")
    assert app.identite("c" * 20) == ("camille", "camille")
    assert app.identite("b" * 20) == (None, None)


def test_identite_d_un_appareil_appaire(tmp_path):
    """Un téléphone appairé a pour clé son id, jamais son nom, qu'il choisit lui-même."""
    async def deroule():
        app = acces.Appareils(tmp_path, {})
        futur = asyncio.get_running_loop().create_future()
        ident, _, _ = app.demande("sacha", "192.168.0.10", futur)
        app.accepter(ident)
        jeton = await futur
        assert app.identite(jeton) == ("sacha", f"appareil:{ident}")
    asyncio.run(deroule())


def test_appairage_puis_revocation(tmp_path):
    async def deroule():
        app = acces.Appareils(tmp_path, {})
        futur = asyncio.get_running_loop().create_future()
        ident, code, nom = app.demande("tablette <script>", "192.0.2.1", futur)
        assert len(code) == 4 and code.isdigit()
        assert nom == "tablette script"
        assert app.vue(avec_code=True)["attente"][0]["code"] == code
        assert app.accepter(ident) == nom
        jeton = await futur
        assert app.identifier(jeton) == nom
        stocke = (tmp_path / "appareils.json").read_text(encoding="utf-8")
        assert jeton not in stocke and acces.empreinte(jeton) in stocke
        assert app.accepter(ident) is None  # une demande ne s'accepte qu'une fois
        assert app.revoquer(json.loads(stocke)[0]["id"])
        assert app.identifier(jeton) is None
    asyncio.run(deroule())


class Requete:
    def __init__(self, entetes):
        self.headers = entetes


def test_jeton_en_entete_et_ancienne_forme():
    assert acces.jeton_de_la_requete(Requete({"Authorization": "Bearer xyz"}), "/", False) == "xyz"
    assert acces.jeton_de_la_requete(Requete({}), "/?jeton=abc", True) == "abc"
    assert acces.jeton_de_la_requete(Requete({}), "/?jeton=abc", False) == ""


def test_passerelle_ha():
    v = acces.verifier_requete_ha
    assert v("GET", "/api/states", None) is None
    assert v("GET", "/api/states/light.exemple6", None) is None
    assert v("POST", "/api/template", {"template": "{{ 1 }}"}) is None
    assert v("POST", "/api/services/light/turn_on", {"entity_id": "light.exemple6"}) is None
    import securite
    if securite.PROTEGER_OCCUPANT:  # règle 1, levée le 22/10/2026
        assert v("POST", "/api/services/light/turn_on", {"entity_id": "light.chambre_camille"})
    assert v("POST", "/api/services/lock/unlock", {"entity_id": "lock.porte"})
    assert v("POST", "/api/services/homeassistant/restart", {})
    assert v("GET", "/api/config", None)
    assert v("DELETE", "/api/states/light.x", None)
    assert v("POST", "/api/services/../config", {})
    assert v("GET", "/api/media_player_proxy/media_player.exemple22?token=abc&cache=12", None) is None
    assert v("GET", "/api/media_player_proxy/../config", None)


def test_passerelle_retour_a_la_ligne_et_majuscules():
    v = acces.verifier_requete_ha
    corps = {"entity_id": "light.exemple6"}
    assert v("POST", "/api/services/light/turn_on\n", corps) == "chemin non permis"
    assert v("POST", "/api/services/light/turn_on\r\n", corps) == "chemin non permis"
    assert v("POST", "/api/services/LIGHT/turn_on", corps) == "chemin non permis"
    assert v("POST", "/api/services/light/TURN_ON", corps) == "chemin non permis"
    assert v("POST", "/API/services/light/turn_on", corps) == "chemin non permis"
    assert v("GET", "/api/states\n", None)
    assert v("GET", "/api/states/light.exemple6\n", None)
    assert v("GET", "/api/states/Exemple6", None)
    assert v("GET", "/api/media_player_proxy/media_player.exemple22\n", None)
    assert v("POST", "/api/services/weather/get_forecasts?return_response\n",
             {"entity_id": "weather.forecast_maison", "type": "hourly"})
    assert v("POST", "/api/services/WEATHER/get_forecasts?return_response",
             {"entity_id": "weather.forecast_maison", "type": "hourly"})


PREVISIONS = "/api/services/weather/get_forecasts?return_response"


def test_passerelle_previsions_acceptees():
    v = acces.verifier_requete_ha
    for genre in ("hourly", "daily", "twice_daily"):
        assert v("POST", PREVISIONS, {"entity_id": "weather.forecast_maison", "type": genre}) is None
    assert v("GET", "/api/states/sun.sun", None) is None


def test_passerelle_previsions_refusees():
    v = acces.verifier_requete_ha
    bon = {"entity_id": "weather.forecast_maison", "type": "hourly"}
    assert v("POST", PREVISIONS, {"entity_id": ["weather.forecast_maison"], "type": "hourly"})  # liste
    assert v("POST", PREVISIONS, {"entity_id": "weather.a, weather.b", "type": "hourly"})
    assert v("POST", PREVISIONS, {"entity_id": "calendar.x", "type": "hourly"})
    assert v("POST", PREVISIONS, {"entity_id": "weather.forecast_maison\n", "type": "hourly"})
    assert v("POST", PREVISIONS, {**bon, "area_id": "salon"})  # clé en plus
    assert v("POST", PREVISIONS, {"entity_id": "weather.forecast_maison"})  # type manquant
    assert v("POST", PREVISIONS, {"entity_id": "weather.forecast_maison", "type": "weekly"})
    assert v("POST", PREVISIONS, {"entity_id": "weather.forecast_maison", "type": ["hourly"]})
    assert v("POST", PREVISIONS, {})
    assert v("POST", PREVISIONS, None)
    assert v("POST", PREVISIONS, "entity_id=weather.forecast_maison")
    # Autre chaîne de requête, autre méthode, autre service à réponse
    assert v("POST", "/api/services/weather/get_forecasts?return_response=1", bon)
    assert v("POST", "/api/services/weather/get_forecasts?return_response&x=1", bon)
    assert v("POST", "/api/services/weather/get_forecasts?jeton=abc", bon)
    assert v("GET", PREVISIONS, bon)
    assert v("GET", PREVISIONS, None)
    assert v("POST", "/api/services/calendar/get_events?return_response",
             {"entity_id": "calendar.maison", "type": "hourly"})
    assert v("POST", "/api/services/todo/get_items?return_response", {"entity_id": "todo.courses"})


def test_certificat(tmp_path):
    cert, cle, empreinte = acces.certificat(tmp_path)
    assert cert.exists() and cle.exists() and len(empreinte) == 44
    assert acces.certificat(tmp_path)[2] == empreinte  # créé une seule fois


class FauxSat:
    def __init__(self, nom):
        self.nom, self.etat = nom, "repos"


class FauxMoteur:
    def __init__(self, sats):
        self.satellites = set(sats)


def test_arbitre_meilleur_score():
    import serveur_satellite as S

    async def deroule():
        a, b, c = FauxSat("a"), FauxSat("b"), FauxSat("c")
        arbitre = S.Arbitre(FauxMoteur([a, b, c]))
        res = await asyncio.gather(arbitre.demander(a, 0.6), arbitre.demander(b, 0.9), arbitre.demander(c, 0.7))
        assert res == [False, True, False]
        assert await arbitre.demander(a, 0.99) is False  # écho du même appel
    asyncio.run(deroule())


def test_arbitre_seul():
    import serveur_satellite as S

    async def deroule():
        a = FauxSat("a")
        assert await S.Arbitre(FauxMoteur([a])).demander(a, 0.5) is True
    asyncio.run(deroule())
