"""Météo marine de la rade de Marseille (0.21.0). Réponses inventées, aucun appel réseau (httpx.MockTransport).

Jour d'essai : le 24/10/2026, veille du passage à l'heure d'hiver (25/10 à 3 h, 01:00 UTC), pour que
les trois jours de prévisions traversent le changement d'heure."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import meteo_mer as MM

UTC = timezone.utc
MAINTENANT = datetime(2026, 10, 24, 8, 30, tzinfo=UTC)       # 10:30 en heure locale
DEBUT_LOCAL = datetime(2026, 10, 24, 0, 0)                    # minuit en heure locale, premier libellé Open-Meteo
DEBUT_VAGUES_REGIONAL = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)   # run 00 UTC, heures en UTC
N = 72


# ------------------------------------------------------------ réponses inventées
def libelles(n=N):
    """Libellés Open-Meteo : depuis minuit local, avec UN décalage pour toute la réponse (+2 h ici)."""
    return [(DEBUT_LOCAL + timedelta(hours=k)).strftime("%Y-%m-%dT%H:%M") for k in range(n)]


def open_meteo(champs, quotidien=None, decalage=7200):
    reponse = []
    for i in range(3):
        p = {"latitude": 43.3, "longitude": 5.3, "utc_offset_seconds": decalage, "timezone": "Europe/Paris",
             "hourly": {"time": libelles(), **champs(i)}}
        if quotidien and i == 0:
            p["daily"] = quotidien
        reponse.append(p)
    return reponse


def icon_invente():
    return open_meteo(lambda i: {
        "wind_speed_10m": [k + i / 10 for k in range(N)], "wind_gusts_10m": [k + 5.04 for k in range(N)],
        "wind_direction_10m": [219.6] * N, "temperature_2m": [19.94] * N, "precipitation": [0.0] * N,
        "cape": [40.4] * N, "lightning_potential": [0.0] * N, "weather_code": [3] * N},
        quotidien={"time": ["2026-10-24", "2026-10-25", "2026-10-26"],
                   "sunrise": ["2026-10-24T07:24", "2026-10-25T07:25", "2026-10-26T07:26"],
                   "sunset": ["2026-10-24T18:10", "2026-10-25T18:08", "2026-10-26T18:07"]})


def harmonie_inventee():
    # AROME ne couvre qu'environ 60 h : null au-delà.
    return open_meteo(lambda i: {
        "wind_speed_10m": [100 + k + i / 10 if k < 60 else None for k in range(N)],
        "wind_direction_10m": [250.6 if k < 60 else None for k in range(N)],
        "wind_gusts_10m": [9.0] * N, "visibility": [50000.0 if k < 60 else None for k in range(N)]})


def mfwam_invente():
    return open_meteo(lambda i: {
        "wave_height": [1.5 + i / 10] * N, "wave_period": [50 + k for k in range(N)],
        "wave_direction": [262.0] * N,
        "sea_surface_temperature": [20 + k / 10 for k in range(N)] if i == 2 else [30.0] * N})


def vagues_regional_inventee(hs):
    """period vaut le rang de l'heure UTC depuis le 24/10 00:00 UTC, pour suivre l'appariement."""
    return {"result": "ok", "timeseries": [
        {"dateTime": (DEBUT_VAGUES_REGIONAL + timedelta(hours=j)).strftime("%Y%m%dZ%H%M"), "hs": hs,
         "period": float(j), "dir": 231.4, "fp": 0.2, "principal": "slight.png", "result": "ok"} for j in range(N)]}


def station_inventee(vitesse=0.89, unite="m/s"):
    return {"changed": True, "snapshot": {
        "cards": [{"key": "temperature", "unit": "C", "value": 19.3},
                  {"key": "wind_speed", "unit": unite, "value": vitesse},
                  {"key": "wind_direction", "unit": "deg", "value": 35.0}],
        "last_timestamp": "2026-10-24T08:20:07Z", "station_name": "inventée"}}


def cle_de(url):
    if url.host == "api.open-meteo.com":
        return "principal" if url.params["models"] == "meteofrance_arpege_europe" else "second"
    if url.host == "marine-api.open-meteo.com":
        return "mfwam"
    if url.host == "api.vagues.exemple.invalid":
        return url.path.rsplit("/", 1)[-1]
    if url.host == "station.exemple.invalid":
        return "station"
    raise AssertionError(f"adresse imprévue {url}")


class Reseau:
    """Faux Internet : une réponse (objet JSON, httpx.Response ou fonction) par source, appels comptés."""

    def __init__(self, **remplacer):
        self.reponses = {"principal": icon_invente(), "second": harmonie_inventee(), "mfwam": mfwam_invente(),
                         "mr01": vagues_regional_inventee(0.34), "mr02": vagues_regional_inventee(0.21),
                         "station": station_inventee()}
        self.reponses.update(remplacer)
        self.vus = []

    def __call__(self, requete):
        cle = cle_de(requete.url)
        self.vus.append(cle)
        r = self.reponses[cle]
        r = r(requete) if callable(r) else r
        if isinstance(r, httpx.Response):
            return r
        return httpx.Response(200, content=json.dumps(r).encode())  # NaN permis, comme json.loads

    def appels(self, cle=None):
        return len(self.vus) if cle is None else self.vus.count(cle)


def mer(reseau, t=None, maintenant=MAINTENANT):
    t = t if t is not None else [0.0]
    return MM.MeteoMer(horloge=lambda: t[0], maintenant=lambda: maintenant, transport=httpx.MockTransport(reseau))


def lire(m):
    return asyncio.run(m.donnees())


def heures(d, ident):
    return next(p for p in d["points"] if p["id"] == ident)["heures"]


# ------------------------------------------------------------ assemblage
def test_url_et_points_constants():
    assert [p[0] for p in MM.POINTS] == ["prado", "pharo", "rade"]
    for url in (MM.URL_PRINCIPAL, MM.URL_SECOND, MM.URL_MFWAM):
        assert "latitude=43.25,43.28,43.27&longitude=5.36,5.33,5.31" in url
        assert "cell_selection=sea" in url and "timezone=Europe%2FParis" in url
    assert "models=meteofrance_arpege_europe" in MM.URL_PRINCIPAL and "daily=sunrise,sunset" in MM.URL_PRINCIPAL
    assert "models=meteofrance_arome_france_hd" in MM.URL_SECOND and "daily" not in MM.URL_SECOND


def test_assemblage_des_trois_points():
    reseau = Reseau()
    d = lire(mer(reseau))
    assert set(d) == {"lu_a", "titre", "points", "eau", "soleil", "station", "erreurs"}
    assert [(p["id"], p["nom"], p["vagues_source"]) for p in d["points"]] == [
        ("prado", "Prado", "regional"), ("pharo", "Pharo", "regional"),
        ("rade", "Milieu de rade", "mfwam")]
    assert d["lu_a"] == "2026-10-24T10:30:00+02:00"
    assert d["erreurs"] == []
    assert reseau.appels() == 6 and set(reseau.vus) == {"principal", "second", "mfwam", "mr01", "mr02", "station"}
    for p in d["points"]:
        assert len(p["heures"]) == N
    # Heure 12:00 en heure locale le 24/10 (10:00 UTC, rang 12 d'Open-Meteo, rang 10 de source régionale).
    h = next(h for h in heures(d, "pharo") if h["t"] == "2026-10-24T12:00")
    assert h == {"t": "2026-10-24T12:00", "vent": 12.1, "rafales": 17.0, "dir": 220, "vent2": 112.1, "dir2": 251,
                 "air": 19.9, "pluie": 0.0, "cape": 40, "foudre": 0.0, "code": 3, "visi": 50000,
                 "vagues": 0.2, "periode": 10.0, "dir_vagues": 231}
    rade = next(h for h in heures(d, "rade") if h["t"] == "2026-10-24T12:00")
    assert (rade["vent"], rade["vagues"], rade["periode"], rade["dir_vagues"]) == (12.2, 1.7, 62.0, 262)
    assert d["eau"] == 21.0  # MFWAM du point rade à 08:00 UTC (rang 10), pas celle des autres points
    assert d["station"] == {"nom": "Vieux-Port", "vent": 1.7, "dir": 35, "le": "2026-10-24T10:20:07+02:00"}
    json.dumps(d)  # sérialisable tel quel


def test_heures_open_meteo_ramenees_a_l_heure_locale():
    """Open-Meteo écrit toute sa réponse avec le décalage du moment de l'appel (+2) : après 01:00 UTC le
    25/10, ses libellés ont une heure d'avance sur l'heure locale. Ils sont corrigés, lever du soleil compris."""
    d = lire(mer(Reseau()))
    t = [h["t"] for h in heures(d, "rade")]
    assert t[0] == "2026-10-24T00:00" and t[-1] == "2026-10-26T22:00"
    du_25 = [x for x in t if x.startswith("2026-10-25")]
    assert len(du_25) == 25  # journée de 25 heures
    assert du_25[:5] == ["2026-10-25T00:00", "2026-10-25T01:00", "2026-10-25T02:00", "2026-10-25T02:00",
                         "2026-10-25T03:00"]
    assert d["soleil"] == [{"jour": "2026-10-24", "lever": "07:24", "coucher": "18:10"},
                           {"jour": "2026-10-25", "lever": "06:25", "coucher": "17:08"},
                           {"jour": "2026-10-26", "lever": "06:26", "coucher": "17:07"}]


def test_vagues_regional_utc_vers_rome_et_heure_d_hiver():
    locale = lambda texte: MM.heure_locale(MM.instant_regional(texte)).isoformat()
    assert locale("20261023Z0800") == "2026-10-23T10:00:00+02:00"
    assert locale("20261025Z0000") == "2026-10-25T02:00:00+02:00"
    assert locale("20261025Z0100") == "2026-10-25T02:00:00+01:00"  # 3 h d'été redevient 2 h d'hiver
    assert locale("20261025Z0200") == "2026-10-25T03:00:00+01:00"
    assert MM.instant_regional("2026-10-25 01:00") is None and MM.instant_regional("20261332Z0000") is None
    # Appariement sur l'instant : les deux « 02:00 » du 25/10 portent 00:00 UTC (rang 24) puis 01:00 UTC.
    d = lire(mer(Reseau()))
    deux = [h for h in heures(d, "prado") if h["t"] == "2026-10-25T02:00"]
    trois = [h for h in heures(d, "prado") if h["t"] == "2026-10-25T03:00"]
    assert [h["periode"] for h in deux] == [24.0, 25.0] and [h["periode"] for h in trois] == [26.0]
    assert [h["vent"] for h in deux + trois] == [26.0, 27.0, 28.0]  # ICON au même instant


def test_regle_europeenne_sans_tzdata(monkeypatch):
    instants = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=k) for k in range(366 * 24)]
    attendus = [MM.heure_locale(i).isoformat() for i in instants]
    monkeypatch.setattr(MM, "LOCAL", None)
    assert [MM.heure_locale(i).isoformat() for i in instants] == attendus


def test_repli_mfwam_heure_par_heure():
    d = lire(mer(Reseau()))
    b = heures(d, "prado")
    # Le run source régionale commence à 00:00 UTC, soit 02:00 en heure locale : minuit et 1 h viennent de MFWAM.
    assert [(h["t"], h["vagues"], h["periode"], h["dir_vagues"]) for h in b[:3]] == [
        ("2026-10-24T00:00", 1.5, 50.0, 262), ("2026-10-24T01:00", 1.5, 51.0, 262), ("2026-10-24T02:00", 0.3, 0.0, 231)]
    # Une heure source régionale sans hauteur lisible ne compte pas : MFWAM à cette heure-là.
    mr01 = vagues_regional_inventee(0.34)
    mr01["timeseries"][5]["hs"] = None
    d = lire(mer(Reseau(mr01=mr01)))
    assert heures(d, "prado")[7]["vagues"] == 1.5 and heures(d, "prado")[8]["vagues"] == 0.3
    # source régionale en panne : tout le point en MFWAM, et vagues_source le dit.
    d = lire(mer(Reseau(mr02=httpx.Response(502))))
    c = heures(d, "pharo")
    assert next(p for p in d["points"] if p["id"] == "pharo")["vagues_source"] == "mfwam"
    assert {h["vagues"] for h in c} == {1.6} and c[12]["periode"] == 62.0
    assert next(p for p in d["points"] if p["id"] == "prado")["vagues_source"] == "regional"
    assert d["erreurs"] == ["Vagues du Pharo indisponibles"]


def test_valeurs_absentes_en_null():
    principal = icon_invente()
    h = principal[0]["hourly"]
    h["wind_speed_10m"][3], h["wind_gusts_10m"][3], h["wind_direction_10m"][3] = None, "x", True
    h["cape"][3], h["temperature_2m"] = float("nan"), h["temperature_2m"][:2]  # liste trop courte
    del h["weather_code"]
    h["precipitation"][3], h["wind_direction_10m"][4] = 0, 359.7
    d = lire(mer(Reseau(principal=principal)))
    b = heures(d, "prado")
    assert (b[3]["vent"], b[3]["rafales"], b[3]["dir"], b[3]["cape"]) == (None, None, None, None)
    assert b[3]["pluie"] == 0.0 and b[4]["dir"] == 0  # un vrai 0 reste 0, 359,7 degrés devient 0
    assert b[1]["air"] == 19.9 and b[2]["air"] is None
    assert {x["code"] for x in b} == {None}
    # AROME au-delà de 60 h : null, jamais 0.
    assert (b[-1]["vent2"], b[-1]["dir2"], b[-1]["visi"]) == (None, None, None)
    assert b[59]["vent2"] == 159.0


def test_sources_jamais_lues_en_null():
    reseau = Reseau(second=httpx.Response(500), mfwam=httpx.Response(503), mr01=httpx.Response(500),
                    station=httpx.Response(200, content=b"pas du json"))
    d = lire(mer(reseau))
    b = heures(d, "prado")
    assert {(h["vent2"], h["dir2"], h["visi"]) for h in b} == {(None, None, None)}
    assert {(h["vagues"], h["periode"], h["dir_vagues"]) for h in b} == {(None, None, None)}
    assert d["eau"] is None and d["station"] is None
    assert d["erreurs"] == ["AROME indisponible", "Vagues MFWAM indisponibles",
                            "Vagues du Prado indisponibles",
                            "Station de Vieux-Port indisponible"]
    assert b[12]["vent"] == 12.0


def test_aujourdhui_depuis_minuit():
    d = lire(mer(Reseau(), maintenant=datetime(2026, 10, 25, 10, 0, tzinfo=UTC)))
    t = [h["t"] for h in heures(d, "rade")]
    assert t[0] == "2026-10-25T00:00" and len(t) == N - 24
    assert [s["jour"] for s in d["soleil"]] == ["2026-10-25", "2026-10-26"]


# ------------------------------------------------------------ cache, pannes et lecture en vol
def test_source_en_panne_garde_l_ancien_cache():
    t = [0.0]
    reseau = Reseau()
    m = mer(reseau, t)
    assert lire(m)["erreurs"] == []
    reseau.reponses["second"] = httpx.Response(502)
    t[0] = MM.DUREE_OPEN_METEO + 1
    d = lire(m)
    assert reseau.appels("second") == 2
    assert d["erreurs"] == ["AROME indisponible"]
    assert heures(d, "prado")[12]["vent2"] == 112.0  # ancien cache servi
    assert "en panne : AROME a répondu 502" in m.bilan()
    t[0] += MM.DUREE_PANNE - 1  # panne gardée : pas de nouvel essai
    assert lire(m)["erreurs"] == ["AROME indisponible"] and reseau.appels("second") == 2
    reseau.reponses["second"] = harmonie_inventee()
    t[0] += 2
    assert lire(m)["erreurs"] == [] and reseau.appels("second") == 3
    assert m.bilan() == ("prévisions servies (ARPEGE, AROME, MFWAM, Vagues du Prado, "
                         "Vagues du Pharo, station)")


def test_cache_perime_selon_la_source():
    t = [0.0]
    reseau = Reseau()
    m = mer(reseau, t)

    def lus_apres(instant):
        avant = len(reseau.vus)
        t[0] = instant
        lire(m)
        return sorted(reseau.vus[avant:])
    assert lus_apres(0) == ["mfwam", "mr01", "mr02", "principal", "second", "station"]
    assert lus_apres(MM.DUREE_STATION - 1) == []
    assert lus_apres(MM.DUREE_STATION) == ["station"]
    assert lus_apres(MM.DUREE_OPEN_METEO) == ["mfwam", "principal", "second", "station"]
    assert lus_apres(MM.DUREE_REGIONAL - 1) == ["mfwam", "principal", "second", "station"]
    assert lus_apres(MM.DUREE_REGIONAL) == ["mr01", "mr02"]


def test_lecture_unique_en_vol():
    def lent(cle):
        def reponse(requete):
            time.sleep(0.2)
            return {"principal": icon_invente, "second": harmonie_inventee, "mfwam": mfwam_invente,
                    "station": station_inventee}.get(cle, lambda: vagues_regional_inventee(0.3))()
        return reponse
    reseau = Reseau(**{c: lent(c) for c in ("principal", "second", "mfwam", "mr01", "mr02", "station")})
    m = mer(reseau)

    async def deroule():
        return await asyncio.gather(m.donnees(), m.donnees(), m.donnees())
    debut = time.monotonic()
    a, b, c = asyncio.run(deroule())
    assert reseau.appels() == 6 and a == b == c
    assert time.monotonic() - debut < 1.0  # sources lues en parallèle, pas l'une après l'autre


def test_source_trop_lente_ne_bloque_pas_les_autres(monkeypatch):
    monkeypatch.setattr(MM, "MARGE", 0.05)

    def bloquee(requete):
        time.sleep(0.6)
        return station_inventee()
    m = mer(Reseau(station=bloquee))
    m.station.delai = 0.05

    async def deroule():  # mesuré ici : asyncio.run attend ensuite la fin du thread abandonné
        debut = time.monotonic()
        return await m.donnees(), time.monotonic() - debut
    d, duree = asyncio.run(deroule())
    assert duree < 0.5
    assert d["station"] is None and d["erreurs"] == ["Station de Vieux-Port indisponible"]
    assert m.station.erreur == "station ne répond pas (délai de 0.05 s)"
    assert len(heures(d, "prado")) == N


def test_demande_abandonnee_sans_seconde_lecture(monkeypatch):
    monkeypatch.setattr(MM, "ATTENTE_MAX", 0.05)
    reseau = Reseau()
    lentes = dict(reseau.reponses)

    def lent(cle):
        def reponse(requete):
            time.sleep(0.3)
            return lentes[cle]
        return reponse
    reseau.reponses = {c: lent(c) for c in lentes}
    m = mer(reseau)

    async def deroule():
        with pytest.raises(MM.ErreurMer, match="prévisions indisponibles : ARPEGE ne répond pas encore"):
            await m.donnees()
        await asyncio.sleep(0.6)
        return await m.donnees()
    assert len(heures(asyncio.run(deroule()), "rade")) == N
    assert reseau.appels() == 6


def test_icon_jamais_lu_donne_erreur():
    t = [0.0]
    reseau = Reseau(principal=httpx.Response(503, text="Erreur 1234"))
    m = mer(reseau, t)
    with pytest.raises(MM.ErreurMer) as e:
        lire(m)
    assert str(e.value) == "prévisions indisponibles : ARPEGE a répondu 503"
    avant = reseau.appels()
    with pytest.raises(MM.ErreurMer):
        lire(m)  # panne gardée 60 s : aucune lecture, pas même des autres sources
    assert reseau.appels() == avant
    reseau.reponses["principal"] = icon_invente()
    t[0] = MM.DUREE_PANNE + 1
    d = lire(m)
    assert d["erreurs"] == [] and len(heures(d, "prado")) == N


@pytest.mark.parametrize("reponse,attendu", [
    (httpx.Response(500, text="x"), "ARPEGE a répondu 500"),
    (httpx.Response(200, text="pas du json"), "réponse illisible de ARPEGE"),
    (httpx.Response(200, json={"error": True}), "réponse inattendue de ARPEGE"),
    (httpx.Response(200, json=[{"hourly": {"time": []}, "utc_offset_seconds": 7200}] * 3),
     "réponse de ARPEGE sans prévision"),
    (httpx.Response(200, content=b"x" * (MM.TAILLE_MAX + 1)), "réponse de ARPEGE trop grande (plus de 2 Mo)"),
    (httpx.Response(200, content=(b"x" * 500_000 for _ in range(5))), "réponse de ARPEGE trop grande (plus de 2 Mo)"),
])
def test_erreurs_lisibles(reponse, attendu):
    with pytest.raises(MM.ErreurMer) as e:
        lire(mer(Reseau(principal=reponse)))
    assert str(e.value) == f"prévisions indisponibles : {attendu}"


def test_erreur_reseau():
    def coupe(requete):
        raise httpx.ConnectError("refusé 1.2.3.4", request=requete)

    def lent(requete):
        raise httpx.ReadTimeout("lent", request=requete)
    m = mer(Reseau(second=coupe, station=lent))
    lire(m)
    assert m.second.erreur == "AROME injoignable (ConnectError)"
    assert m.station.erreur == "station ne répond pas (délai de 8 s)"


def test_reglages_du_client(monkeypatch):
    vus = []

    class Espion(httpx.Client):
        def __init__(self, **kw):
            vus.append(kw)
            super().__init__(**kw)
    monkeypatch.setattr(httpx, "Client", Espion)
    lire(mer(Reseau()))
    assert len(vus) == 6 and all(kw["trust_env"] is False for kw in vus)
    assert {kw["timeout"].connect for kw in vus} == {4}
    assert sorted(kw["timeout"].read for kw in vus) == [8, 15, 15, 15, 20, 20]


# ------------------------------------------------------------ station
def test_station_m_s_en_noeuds():
    d = MM.reduire_station(station_inventee(0.89), "station")
    assert d == {"nom": "Vieux-Port", "vent": 1.7, "dir": 35, "le": "2026-10-24T10:20:07+02:00"}
    assert MM.reduire_station(station_inventee(4.47), "station")["vent"] == 8.7
    assert MM.reduire_station(station_inventee(18, "km/h"), "station")["vent"] == 9.7
    assert MM.reduire_station(station_inventee(3, "furlong"), "station")["vent"] is None  # unité inconnue
    sans_heure = station_inventee()
    del sans_heure["snapshot"]["last_timestamp"]
    assert MM.reduire_station(sans_heure, "station")["le"] is None
    sans_vent = {"snapshot": {"cards": [{"key": "temperature", "unit": "C", "value": 19.3}]}}
    with pytest.raises(MM.ErreurMer, match="sans vent"):
        MM.reduire_station(sans_vent, "station")
    with pytest.raises(MM.ErreurMer, match="inattendue"):
        MM.reduire_station({"snapshot": None}, "station")


# ------------------------------------------------------------ serveur : capacité et message
class FauxWs:
    def __init__(self):
        self.envois = []

    async def send(self, texte):
        self.envois.append(json.loads(texte))


def moteur(meteo_mer):
    import serveur_satellite as S
    m = object.__new__(S.Moteur)  # sans charger les modèles
    m.sante, m.sante_personnes, m.meteo_mer = None, frozenset(), meteo_mer
    return m


def satellite(meteo_mer):
    import serveur_satellite as S
    sat = object.__new__(S.Satellite)  # sans charger le mot de réveil
    sat.ws, sat.moteur, sat.nom = FauxWs(), moteur(meteo_mer), "essai"
    sat.identite, sat.chiffre = None, False  # connexion en clair, sans identité : servi quand même
    return sat


def test_capacite_meteo_mer(monkeypatch):
    import serveur_satellite as S

    class FauxAssistant:
        ha = None
    m = moteur(MM.MeteoMer())
    m.profil, m.assistant, m.empreinte_tls, m.vision = "ha", FauxAssistant(), "", None
    assert m.capacites()["meteo_mer"] is True
    sat = object.__new__(S.Satellite)
    sat.identite, sat.chiffre = None, False
    assert m.capacites(sat)["meteo_mer"] is True
    m.meteo_mer = None
    assert m.capacites(sat)["meteo_mer"] is False
    del m.meteo_mer  # moteur construit sans l'attribut : faux, sans lever
    assert m.capacites()["meteo_mer"] is False
    monkeypatch.delenv("METEO_MER", raising=False)
    assert isinstance(MM.depuis_env(), MM.MeteoMer)
    monkeypatch.setenv("METEO_MER", "1")
    assert isinstance(MM.depuis_env(), MM.MeteoMer)
    for eteint in ("0", " 0 ", "non", "false", "off"):
        monkeypatch.setenv("METEO_MER", eteint)
        assert MM.depuis_env() is None


def test_message_meteo_mer_servi(capsys):
    sat = satellite(mer(Reseau()))

    async def deroule():
        await sat.recevoir_texte(json.dumps({"type": "meteo_mer", "id": 7}))
        for _ in range(200):
            if sat.ws.envois:
                break
            await asyncio.sleep(0.01)
    asyncio.run(deroule())
    assert len(sat.ws.envois) == 1
    envoi = sat.ws.envois[0]
    assert set(envoi) == {"etat", "id", "donnees"} and envoi["etat"] == "meteo_mer" and envoi["id"] == 7
    assert [p["id"] for p in envoi["donnees"]["points"]] == ["prado", "pharo", "rade"]
    assert envoi["donnees"]["station"]["nom"] == "Vieux-Port"
    assert ("[essai] mer : prévisions servies (ARPEGE, AROME, MFWAM, Vagues du Prado, "
            "Vagues du Pharo, station)") in capsys.readouterr().out


def test_message_meteo_mer_erreurs(capsys):
    sat = satellite(mer(Reseau(principal=httpx.Response(503))))
    asyncio.run(sat.repondre_meteo_mer({"id": 1}))
    assert sat.ws.envois == [{"etat": "meteo_mer", "id": 1,
                              "erreur": "prévisions indisponibles : ARPEGE a répondu 503"}]
    assert "[essai] mer : prévisions indisponibles : ARPEGE a répondu 503" in capsys.readouterr().out

    class Cassee:
        async def donnees(self):
            raise ValueError("valeur 98 illisible")
    sat = satellite(Cassee())
    asyncio.run(sat.repondre_meteo_mer({"id": 2}))
    assert sat.ws.envois == [{"etat": "meteo_mer", "id": 2, "erreur": "erreur inattendue (ValueError)"}]
    assert "98" not in capsys.readouterr().out
    sat = satellite(None)
    asyncio.run(sat.repondre_meteo_mer({"id": 3}))
    assert sat.ws.envois == [{"etat": "meteo_mer", "id": 3, "erreur": "météo marine éteinte sur ce serveur"}]


def test_sans_section_mer_active_le_module_est_eteint(monkeypatch):
    """Configuration sans section « mer » active : ni module ni capacité, quelle que soit METEO_MER."""
    monkeypatch.setattr(MM, "ACTIF", False)
    for valeur in ("1", "oui"):
        monkeypatch.setenv("METEO_MER", valeur)
        assert MM.depuis_env() is None
    monkeypatch.delenv("METEO_MER", raising=False)
    assert MM.depuis_env() is None
