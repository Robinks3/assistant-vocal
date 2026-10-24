"""Vent mesuré dans la rade de Marseille (0.24.0). Réponses inventées sur le modèle des vraies réponses du
24/10/2026, aucun appel réseau (httpx.MockTransport).

Instant d'essai : le 24/10/2026 à 09:00 UTC (11:00 en heure locale). La fenêtre des mesures va donc de 06:00 UTC
(exclu) à maintenant."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import meteo_mer as MM
import vent_mesure as VM

UTC = timezone.utc
MAINTENANT = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
T0 = int(MAINTENANT.timestamp())
LIBELLE_PW = "Balises de régate indisponibles"
LIBELLE_MH = "Stations officielles indisponibles"
LIBELLE_WS3 = "Station de Vieux-Port indisponible"


# ------------------------------------------------------------ réponses inventées
def obs(ident, k, tws, twd, gust):
    """Observation Balises de la rade il y a k minutes."""
    return {"t": T0 - 60 * k, "id": ident, "tws": tws, "twd": twd, "gust": gust}


def balises_inventees():
    observations = [
        *(obs(101, k, 10.0 + k, 240, 0 if k == 0 else 15.04) for k in range(5)),   # Frioul
        obs(101, 1, 11.0, 240, 15.04),                       # doublon exact (id, t) de k = 1
        obs(101, 240, 8.0, 100, 9.0),                        # il y a 4 h : hors fenêtre
        obs(102, 0, 5.0, 0, 0), obs(102, 1, 0.0, 0, 0),   # Endoume : direction 0 avec vent, puis vent nul
        obs(103, 0, 7.44, 180, 9.0),                         # Prado
        obs(104, 0, 3.0, 193, 0), obs(104, 1, 3.5, 200, 4.0),   # Callelongue (doublon de Stations officielles)
        obs(105, 0, 9.0, 250, 0),                              # Marignane
        obs(199, 0, 20.0, 10, 30.0), obs(999999, 0, 20.0, 10, 30.0),   # ids ignorées
    ]
    return [{"result": {"data": {"json": {"weatherData": [], "observationData": observations, "webcams": []}}}}]


def produit(var, trange, mesures, lev="103,10000,0,0"):
    return {"var": var, "lev": lev, "trange": trange,
            "val": [{"val": v, "ref": ref, "rel": 1} for ref, v in mesures]}


def station_mh(nom, lat, lon, net, *prod):
    return {"stat": {"lat": lat, "lon": lon, "net": net, "details": [{"var": "B01019", "val": nom}]},
            "prod": list(prod)}


def horaires(nom, lat, lon, derniere, vitesse=1.0, trange="254,0,0"):
    """Station amateur horaire dont la dernière mesure est à `derniere` (HH:MM UTC), deux heures avant aussi."""
    heure = int(derniere[:2])
    refs = [f"2026-10-24T{heure - 2:02d}:00:00", f"2026-10-24T{heure - 1:02d}:00:00", f"2026-10-24T{heure:02d}:00:00"]
    return station_mh(nom, lat, lon, "amateurs",
                      produit("B11002", trange, [(r, vitesse + i) for i, r in enumerate(refs)]),
                      produit("B11001", trange, [(r, 200 + i) for i, r in enumerate(refs)]))


def officielles_inventees():
    refs = ["2026-10-24T08:30:00", "2026-10-24T08:40:00", "2026-10-24T08:50:00"]
    callelongue = station_mh(
        "Callelongue METEO", 43.2105, 5.3402, "reseau-officiel",
        produit("B11002", "254,0,0", list(zip(refs, [5.0, 6.0, 7.0]))),
        produit("B11001", "254,0,0", list(zip(refs, [350, 355, 0]))),
        produit("B11002", "0,0,900", [("2026-10-24T08:45:00", 99.0)]),           # moyenne : ignorée
        produit("B11041", "2,0,3600", [("2026-10-24T08:30:00", 9.0)]),            # rafale horaire
        produit("B11002", "254,0,0", [("2026-10-24T08:50:00", 50.0)], lev="103,2000,0,0"))   # pas à 10 m : ignorée
    return {"descr": {}, "data": [
        station_mh("T0065 - Careser", 46.42, 10.69, "open-trentino", produit("B11002", "254,0,0", [(refs[0], 7.1)])),
        callelongue,
        horaires("stn080", 43.3010, 5.3891, "08:00", 1.0),
        horaires("stn292", 43.3003, 5.3972, "09:00", 2.0, trange=[254, 0, 0]),   # la plus fraîche de Longchamp
        horaires("stn304", 43.2815, 5.3794, "08:00", 3.0),                       # la plus fraîche de Castellane
        horaires("stn307", 43.2838, 5.3907, "07:00", 4.0),
        horaires("stn999", 43.24, 5.25, "08:00", 1.0),                              # code inconnu, dans le cadre
        horaires("stn500", 43.40, 5.30, "08:00", 1.0),                              # hors cadre (nord)
        horaires("stn501", 43.25, 5.50, "08:00", 1.0),                              # hors cadre (est)
    ]}


def terre_inventee(vitesse=4.02, unite="m/s", avec_courbes=True, dernier="2026-10-24T08:58:00Z"):
    courbes = []
    if avec_courbes:
        x = ["2026-10-24T05:50:00Z", "2026-10-24T08:40:00Z", "2026-10-24T08:50:00Z"]   # la première est trop vieille
        courbes = [{"key": "temperature", "unit": "C", "points": [{"x": a, "y": 20.0} for a in x]},
                   {"key": "wind_speed", "unit": "m/s", "points": [{"x": a, "y": b} for a, b in zip(x, [9.0, 5.0, 6.0])]},
                   {"key": "wind_direction", "unit": "deg", "points": [{"x": a, "y": b} for a, b in zip(x, [10.0, 240.0, 250.0])]}]
    return {"changed": True, "snapshot": {
        "cards": [{"key": "wind_speed", "unit": unite, "value": vitesse},
                  {"key": "wind_direction", "unit": "deg", "value": 246.0}],
        "series": courbes, "last_timestamp": dernier, "window": "day", "rows": 3}}


def cle_de(url):
    if url.host == "balises.exemple.invalid":
        return "pw"
    if url.host == "stations.exemple.invalid":
        return "mh"
    if url.host == "station.exemple.invalid":
        return "terre"
    raise AssertionError(f"adresse imprévue {url}")


class Reseau:
    """Faux Internet : une réponse (objet JSON, httpx.Response ou fonction) par source, appels comptés."""

    def __init__(self, **remplacer):
        self.reponses = {"pw": balises_inventees(), "mh": officielles_inventees(), "terre": terre_inventee()}
        self.reponses.update(remplacer)
        self.vus, self.requetes = [], []

    def __call__(self, requete):
        cle = cle_de(requete.url)
        self.vus.append(cle)
        self.requetes.append(requete)
        r = self.reponses[cle]
        r = r(requete) if callable(r) else r
        if isinstance(r, httpx.Response):
            return r
        return httpx.Response(200, content=json.dumps(r).encode())

    def appels(self, cle=None):
        return len(self.vus) if cle is None else self.vus.count(cle)


def vent(reseau, t=None, maintenant=None):
    """VentMesure sur le faux réseau. t : horloge monotone modifiable, maintenant : liste à un instant."""
    t = t if t is not None else [0.0]
    maintenant = maintenant if maintenant is not None else [MAINTENANT]
    return VM.VentMesure(horloge=lambda: t[0], maintenant=lambda: maintenant[0],
                         transport=httpx.MockTransport(reseau))


def lire(m):
    return asyncio.run(m.donnees())


def par_id(d):
    return {s["id"]: s for s in d["stations"]}


# ------------------------------------------------------------ Balises de la rade
def test_balises_doublons_rafale_zero_et_ids_ignorees():
    d = lire(vent(Reseau(mh=httpx.Response(500), terre=httpx.Response(500))))
    s = par_id(d)
    assert set(s) == {"frioul", "endoume", "prado", "callelongue", "lfml"}   # ni 199 ni 999999
    frioul = s["frioul"]
    assert [m["t"] for m in frioul["mesures"]] == [T0 - 240, T0 - 180, T0 - 120, T0 - 60, T0]   # triées, doublon et vieille mesure retirés
    assert frioul["mesures"][-1] == {"t": T0, "vent": 10.0, "dir": 240, "rafale": None}         # gust 0 : null
    assert frioul["mesures"][0] == {"t": T0 - 240, "vent": 14.0, "dir": 240, "rafale": 15.0}
    assert s["prado"]["mesures"] == [{"t": T0, "vent": 7.4, "dir": 180, "rafale": 9.0}]
    # Vent nul avec direction 0 : pas de direction. Vent de 5 nœuds au 0 : un vrai nord.
    assert [(m["vent"], m["dir"]) for m in s["endoume"]["mesures"]] == [(0.0, None), (5.0, 0)]


def test_balises_fiches_et_positions_en_constantes():
    s = par_id(lire(vent(Reseau(mh=httpx.Response(500), terre=httpx.Response(500)))))
    champs = ["id", "nom", "genre", "type", "source", "lat", "lon", "point", "seuil_min", "mesures"]
    assert all(list(x) == champs for x in s.values())
    assert [(x["nom"], x["genre"], x["type"], x["lat"], x["lon"], x["point"]) for x in (s["frioul"], s["endoume"])] == [
        ("Frioul", "balise de régate", "mer", 43.28, 5.28, "pharo"),
        ("Endoume", "balise abritée", "abritee", 43.28, 5.34, "pharo")]
    assert (s["prado"]["lat"], s["prado"]["lon"], s["prado"]["point"]) == (43.25, 5.36, "prado")
    assert (s["lfml"]["genre"], s["lfml"]["type"], s["lfml"]["lat"], s["lfml"]["lon"]) == (
        "aéroport, hors carte", "terre", 43.44, 5.22)
    assert {x["source"] for x in s.values()} == {"balises"} and {x["seuil_min"] for x in s.values()} == {45}


@pytest.mark.parametrize("reponse", [
    [{"error": {"message": "boom"}}], {"result": {}}, [], None, "texte", [{"result": {"data": {"json": {}}}}],
    [{"result": {"data": {"json": {"observationData": {"a": 1}}}}}],
    [{"result": {"data": {"json": {"observationData": "x"}}}}],
])
def test_balises_forme_inattendue_donne_indisponible_sans_exception(reponse):
    m = vent(Reseau(pw=httpx.Response(200, content=json.dumps(reponse).encode())))
    d = lire(m)  # ne lève pas : Stations officielles et terre continuent
    assert d["erreurs"] == [LIBELLE_PW]
    assert m.balises.erreur == "réponse inattendue de Balises de la rade"
    assert {"callelongue", "stn292", "port"} <= set(par_id(d))
    assert not {"frioul", "endoume", "prado", "lfml"} & set(par_id(d))


def test_balises_elements_bizarres_ignores():
    observations = [obs(101, 0, 10.0, 240, 12.0), "x", None, {"id": [1]}, {"id": 101},
                    obs(101, 1, "10", 240, 0), obs(101, 2, float("nan"), 240, 0), obs(101, 3, -4.0, 1, 0),
                    {"t": T0 - 300, "id": 101, "tws": 8.0}, obs(True, 0, 3.0, 4, 0)]
    brut = [{"result": {"data": {"json": {"observationData": observations}}}}]
    assert VM.reduire_balises(brut, "Balises de la rade") == {
        101: {T0: (10.0, 240, 12.0), T0 - 300: (8.0, None, None)}}


# ------------------------------------------------------------ Stations officielles
def test_officielles_conversion_utc_periodes_et_rafale():
    d = lire(vent(Reseau(pw=httpx.Response(500), terre=httpx.Response(500))))
    callelongue = par_id(d)["callelongue"]
    # 5, 6 et 7 m/s en nœuds, heures UTC sans fuseau lues comme UTC. Seule la rafale horaire de 08:30 s'attache.
    assert callelongue["mesures"] == [{"t": T0 - 1800, "vent": 9.7, "dir": 350, "rafale": 17.5},
                                 {"t": T0 - 1200, "vent": 11.7, "dir": 355, "rafale": None},
                                 {"t": T0 - 600, "vent": 13.6, "dir": 0, "rafale": None}]   # un vrai nord reste 0
    assert (callelongue["nom"], callelongue["genre"], callelongue["type"], callelongue["source"], callelongue["point"], callelongue["seuil_min"]) == (
        "Callelongue", "station officielle", "mer", "officielles", "prado", 75)


def test_officielles_direction_zero_avec_vent_garde_le_nord():
    brut = {"data": [station_mh("Callelongue METEO", 43.2105, 5.3402, "reseau-officiel",
                                produit("B11002", "254,0,0", [("2026-10-24T08:50:00", 7.0), ("2026-10-24T08:40:00", 0.0)]),
                                produit("B11001", "254,0,0", [("2026-10-24T08:50:00", 0), ("2026-10-24T08:40:00", 0)]))]}
    m = VM.reduire_officielles(brut, "Stations officielles")[0]["mesures"]
    assert m[T0 - 600] == (13.6, 0, None) and m[T0 - 1200] == (0.0, None, None)


def test_officielles_cadre_geographique():
    stations = VM.reduire_officielles(officielles_inventees(), "Stations officielles")
    assert sorted(s["id"] for s in stations) == ["callelongue", "stn080", "stn292", "stn304", "stn307", "stn999"]
    sur_les_bords = {"data": [horaires("stn001", lat, lon, "08:00") for lat, lon in
                              ((43.20, 5.22), (43.32, 5.47), (43.1999, 5.3), (43.3, 5.4701))]}
    assert [s["id"] for s in VM.reduire_officielles(sur_les_bords, "Stations officielles")] == ["stn001", "stn001"]
    assert VM.dans_le_cadre(43.20, 5.47) and not VM.dans_le_cadre(43.3201, 5.4)


def test_officielles_noms_des_stations_amateurs():
    s = par_id(lire(vent(Reseau(pw=httpx.Response(500), terre=httpx.Response(500)))))
    assert (s["stn292"]["nom"], s["stn304"]["nom"], s["stn999"]["nom"]) == ("Longchamp", "Castellane", "Station amateur stn999")
    assert (s["stn292"]["genre"], s["stn292"]["type"], s["stn292"]["source"]) == ("amateur, en ville", "amateur", "officielles")
    assert s["stn292"]["mesures"][-1] == {"t": T0, "vent": 7.8, "dir": 202, "rafale": None}   # 4 m/s en nœuds, trange en liste


def test_officielles_formes_diverses():
    assert VM.reduire_officielles({"descr": {}, "data": []}, "Stations officielles") == []
    for brut in ([], {"descr": {}}, {"data": "x"}, None):
        with pytest.raises(VM.ErreurVent, match="réponse inattendue de Stations officielles"):
            VM.reduire_officielles(brut, "Stations officielles")
    bizarre = {"data": [None, {"stat": None}, {"stat": {"lat": "x", "lon": 1}}, {"stat": {"lat": 43.3, "lon": 5.4}},
                        {"stat": {"lat": 43.3, "lon": 5.4, "net": "amateurs", "details": [{"var": "B01019", "val": " "}]}},
                        {"stat": {"lat": 43.3, "lon": 5.4, "net": "autre", "details": [{"var": "B01019", "val": "Prado Nord"}]},
                         "prod": [None, {"var": "B11002", "trange": "254,0,0", "lev": "103,10000,0,0", "val": "x"},
                                  produit("B11002", "pas,une,liste", [("2026-10-24T08:50:00", 1.0)]),
                                  produit("B11002", "254,0,0", [("hier", 1.0), ("2026-10-24T08:50:00", -3.0),
                                                                ("2026-10-24T08:50:00", True), ("2026-10-24T08:30:00Z", 2.0)])]}]}
    [s] = VM.reduire_officielles(bizarre, "Stations officielles")
    assert (s["id"], s["nom"], s["type"], s["genre"]) == ("prado-nord", "Prado Nord", "terre", "station météo")
    assert s["mesures"] == {T0 - 1800: (3.9, None, None)}


# ------------------------------------------------------------ Callelongue : Stations officielles remplace, Balises de la rade revient
def test_callelongue_officielle_remplace_la_balise_balise():
    d = lire(vent(Reseau()))
    callelongue = [s for s in d["stations"] if s["id"] == "callelongue"]
    assert len(callelongue) == 1 and callelongue[0]["source"] == "officielles" and callelongue[0]["genre"] == "station officielle"
    assert d["erreurs"] == []


def test_callelongue_balise_balise_revient_quand_officielle_est_en_panne():
    d = lire(vent(Reseau(mh=httpx.Response(503))))
    callelongue = [s for s in d["stations"] if s["id"] == "callelongue"]
    assert len(callelongue) == 1 and callelongue[0]["source"] == "balises" and callelongue[0]["genre"] == "balise de régate"
    assert callelongue[0]["mesures"] == [{"t": T0 - 60, "vent": 3.5, "dir": 200, "rafale": 4.0},
                                    {"t": T0, "vent": 3.0, "dir": 193, "rafale": None}]
    assert d["erreurs"] == [LIBELLE_MH]
    assert not any(s["source"] == "officielles" for s in d["stations"])


def test_callelongue_balise_revient_aussi_avec_l_ancien_cache_de_officielles():
    t, reseau = [0.0], Reseau()
    m = vent(reseau, t)
    assert par_id(lire(m))["callelongue"]["source"] == "officielles"
    reseau.reponses["mh"] = httpx.Response(502)
    t[0] = VM.DUREE_OFFICIELLES + 1
    d = lire(m)
    assert par_id(d)["callelongue"]["source"] == "balises"
    assert len([s for s in d["stations"] if s["id"] == "callelongue"]) == 1
    assert "stn292" in par_id(d)   # l'ancien cache de Stations officielles sert toujours pour le reste
    assert d["erreurs"] == [LIBELLE_MH]


def test_callelongue_officielle_seule_si_balise_est_en_panne():
    d = lire(vent(Reseau(pw=httpx.Response(500))))
    assert par_id(d)["callelongue"]["source"] == "officielles" and d["erreurs"] == [LIBELLE_PW]
    # Stations officielles en panne aussi, mais Balises de la rade sans Callelongue dans la fenêtre : rien d'autre à montrer.
    sans_callelongue = [{"result": {"data": {"json": {"observationData": [obs(101, 0, 9.0, 1, 0)]}}}}]
    d = lire(vent(Reseau(pw=sans_callelongue, mh=httpx.Response(500))))
    assert "callelongue" not in par_id(d)


# ------------------------------------------------------------ fusion des amateurs
def test_fusion_des_amateurs_de_meme_nom_garde_la_plus_fraiche():
    s = par_id(lire(vent(Reseau())))
    assert "stn292" in s and "stn080" not in s     # Longchamp : 09:00 contre 08:00
    assert "stn304" in s and "stn307" not in s     # Castellane : 08:00 contre 07:00
    assert "stn999" in s                           # seule de son nom


def _fiche(ident, nom, lat, lon, derniere):
    return {"id": ident, "nom": nom, "genre": "amateur, en ville", "type": "amateur", "point": "pharo",
            "lat": lat, "lon": lon, "mesures": {T0 - derniere: (3.0, 100, None)}}


def test_fusion_distance_et_inconnues():
    proches = [_fiche("stn998", VM.NOM_AMATEUR_INCONNU, 43.2400, 5.2500, 600),
               _fiche("stn999", VM.NOM_AMATEUR_INCONNU, 43.2410, 5.2510, 60)]
    d = VM.assembler(None, proches, None, MAINTENANT)
    assert [s["id"] for s in d["stations"]] == ["stn999"]
    loin = [_fiche("stn001", "Longchamp", 43.30, 5.39, 60), _fiche("stn002", "Longchamp", 43.26, 5.43, 600)]   # environ 5 km
    d = VM.assembler(None, loin, None, MAINTENANT)
    assert [s["id"] for s in d["stations"]] == ["stn001", "stn002"]
    egales = [_fiche("stn020", "Longchamp", 43.30, 5.39, 60), _fiche("stn010", "Longchamp", 43.3001, 5.3901, 60)]
    assert [s["id"] for s in VM.assembler(None, egales, None, MAINTENANT)["stations"]] == ["stn010"]


def test_distance_et_point_proche():
    assert 11_000 < VM.distance_m(43.0, 5.0, 43.1, 5.0) < 11_200
    assert VM.distance_m(43.2105, 5.3402, 43.2105, 5.3402) == 0
    assert VM.point_proche(43.24, 5.37) == "prado" and VM.point_proche(43.29, 5.32) == "pharo"


# ------------------------------------------------------------ terre
def test_terre_courbes_trois_heures_et_derniere_valeur():
    s = par_id(lire(vent(Reseau())))["port"]
    assert (s["nom"], s["genre"], s["type"], s["source"], s["point"], s["seuil_min"]) == (
        "Vieux-Port", "station à terre", "terre", "station_terre", "prado", 30)
    assert (s["lat"], s["lon"]) == (43.3, 5.37)
    # La mesure de 05:50 est hors fenêtre. 5 et 6 m/s en nœuds, puis la valeur des cartes de 08:58 (4,02 m/s).
    assert s["mesures"] == [{"t": T0 - 1200, "vent": 9.7, "dir": 240, "rafale": None},
                            {"t": T0 - 600, "vent": 11.7, "dir": 250, "rafale": None},
                            {"t": T0 - 120, "vent": 7.8, "dir": 246, "rafale": None}]


def test_terre_sans_courbes_seulement_la_derniere_mesure():
    s = par_id(lire(vent(Reseau(terre=terre_inventee(avec_courbes=False)))))["port"]
    assert s["mesures"] == [{"t": T0 - 120, "vent": 7.8, "dir": 246, "rafale": None}]


def test_terre_formes_et_unites():
    assert VM.reduire_terre(terre_inventee(18, "km/h", avec_courbes=False), "terre")[T0 - 120][0] == 9.7
    for brut, motif in (({"snapshot": None}, "inattendue"), ([], "inattendue"),
                        ({"snapshot": {"cards": [{"key": "temperature", "value": 3}]}}, "sans vent"),
                        (terre_inventee(3, "furlong", avec_courbes=False), "unité de vent inconnue")):
        with pytest.raises(VM.ErreurVent, match=motif):
            VM.reduire_terre(brut, "terre")
    sans_heure = terre_inventee(avec_courbes=False, dernier="n'importe quoi")
    with pytest.raises(VM.ErreurVent, match="sans vent"):
        VM.reduire_terre(sans_heure, "terre")
    # Courbes en labels et values plutôt qu'en points.
    brut = terre_inventee(avec_courbes=False)
    brut["snapshot"]["series"] = [{"key": "wind_speed", "unit": "m/s", "labels": ["2026-10-24T08:00:00Z"], "values": [2.0]}]
    assert VM.reduire_terre(brut, "terre")[T0 - 3600] == (3.9, None, None)


# ------------------------------------------------------------ forme du message
def test_forme_de_donnees_ordre_et_serialisation():
    reseau = Reseau()
    d = lire(vent(reseau))
    assert set(d) == {"lu_a", "stations", "erreurs"}
    assert d["lu_a"] == "2026-10-24T11:00:00+02:00" and d["erreurs"] == []
    assert [s["id"] for s in d["stations"]] == ["callelongue", "frioul", "prado", "endoume", "lfml", "port", "stn304", "stn292", "stn999"]
    assert [s["type"] for s in d["stations"]] == ["mer"] * 3 + ["abritee"] + ["terre"] * 2 + ["amateur"] * 3
    assert {s["id"]: s["seuil_min"] for s in d["stations"]}["frioul"] == 45
    assert reseau.appels() == 3
    for s in d["stations"]:
        assert s["mesures"] == sorted(s["mesures"], key=lambda m: m["t"]) and s["mesures"]
        assert all(set(m) == {"t", "vent", "dir", "rafale"} and isinstance(m["t"], int) for m in s["mesures"])
        assert all(m["t"] > T0 - 10800 for m in s["mesures"])
    json.dumps(d)   # sérialisable tel quel


def test_station_sans_mesure_dans_les_trois_heures_non_listee():
    plus_tard = [MAINTENANT + timedelta(hours=2)]   # 11:00 UTC : fenêtre de 08:00 (exclu) à 11:00
    d = lire(vent(Reseau(), maintenant=plus_tard))
    s = par_id(d)
    assert set(s) == {"prado", "callelongue", "frioul", "endoume", "lfml", "port", "stn292"}   # stn304 et stn999 : dernière mesure à 08:00
    assert [m["t"] for m in s["stn292"]["mesures"]] == [T0]                          # ses mesures de 07:00 et 08:00 sont sorties
    plus_tard[0] = MAINTENANT + timedelta(hours=3, minutes=1)
    assert lire(vent(Reseau(), maintenant=plus_tard))["stations"] == []


# ------------------------------------------------------------ requêtes
def test_requetes_adresses_et_entetes():
    reseau = Reseau()
    lire(vent(reseau))
    pw = next(r for r in reseau.requetes if cle_de(r.url) == "pw")
    assert json.loads(pw.url.params["input"]) == {"0": {"json": {
        "type": "exemple",
        "observationWindow": "6hr", "latitude": 43.27, "longitude": 5.33}}}
    assert pw.url.params["batch"] == "1" and pw.url.path == "/api/trpc/observations.lire"
    assert pw.headers["user-agent"] == "assistant-vocal/1.0 (exemple, usage personnel)"
    mh = next(r for r in reseau.requetes if cle_de(r.url) == "mh")
    assert mh.url.params["q"] == ("reftime: >=2026-10-24 06:00,<=2026-10-24 09:00;"
                                  "product:B11002 or B11001 or B11041;license:CCBY_COMPLIANT")
    assert mh.url.path == "/api/observations"
    assert "python-httpx" in mh.headers["user-agent"]   # pas celui de Balises de la rade
    terre = next(r for r in reseau.requetes if cle_de(r.url) == "terre")
    assert terre.url.path.endswith("station-port/snapshot") and terre.url.params["window"] == "day"


def test_reglages_du_client(monkeypatch):
    vus = []

    class Espion(httpx.Client):
        def __init__(self, **kw):
            vus.append(kw)
            super().__init__(**kw)
    monkeypatch.setattr(httpx, "Client", Espion)
    lire(vent(Reseau()))
    assert len(vus) == 3 and all(kw["trust_env"] is False for kw in vus)
    assert {kw["timeout"].connect for kw in vus} == {4}
    assert sorted(kw["timeout"].read for kw in vus) == [8, 10, 20]
    assert sum(kw["headers"] is not None for kw in vus) == 1


# ------------------------------------------------------------ cadence
def test_cadence_par_source():
    t = [0.0]
    reseau = Reseau()
    m = vent(reseau, t)

    def lus_apres(instant):
        avant = len(reseau.vus)
        t[0] = instant
        lire(m)
        return sorted(reseau.vus[avant:])
    assert lus_apres(0) == ["mh", "pw", "terre"]
    assert lus_apres(VM.DUREE_BALISES - 1) == []
    assert lus_apres(VM.DUREE_BALISES) == ["pw", "terre"]          # Balises de la rade relu après 2 min
    assert lus_apres(VM.DUREE_OFFICIELLES - 1) == ["pw", "terre"]         # Stations officielles pas avant 10 min
    assert lus_apres(VM.DUREE_OFFICIELLES) == ["mh"]
    assert lus_apres(2 * VM.DUREE_OFFICIELLES - 1) == ["pw", "terre"]
    assert lus_apres(2 * VM.DUREE_OFFICIELLES) == ["mh"]
    assert (VM.DUREE_BALISES, VM.DUREE_TERRE, VM.DUREE_OFFICIELLES) == (120, 120, 600)


def test_attente_croissante_apres_erreur_puis_remise_a_zero():
    s = VM.Source("x", "x", lambda: "", 1, 1, 1, None)
    attentes = []
    for s.echecs in range(1, 8):
        attentes.append(s.attente())
    assert attentes == [60, 120, 240, 480, 900, 900, 900]
    t, reseau = [0.0], Reseau(pw=httpx.Response(502))
    m = vent(reseau, t)

    def essai(instant):
        avant = reseau.appels("pw")
        t[0] = instant
        lire(m)
        return reseau.appels("pw") - avant
    assert essai(0) == 1 and m.balises.echecs == 1
    assert essai(59) == 0 and essai(60) == 1 and m.balises.echecs == 2     # 1 min puis 2 min
    assert essai(60 + 119) == 0 and essai(60 + 120) == 1                       # 2 min
    assert essai(180 + 239) == 0 and essai(180 + 240) == 1 and m.balises.echecs == 4   # 4 min
    assert essai(420 + 479) == 0 and essai(420 + 480) == 1 and m.balises.echecs == 5   # 8 min
    assert essai(900 + 899) == 0 and essai(900 + 900) == 1 and m.balises.echecs == 6   # plafond de 15 min
    assert essai(1800 + 900) == 1 and m.balises.echecs == 7
    reseau.reponses["pw"] = balises_inventees()
    assert essai(2700 + 900) == 1 and m.balises.echecs == 0 and m.balises.erreur is None
    reseau.reponses["pw"] = httpx.Response(502)
    assert essai(3600 + VM.DUREE_BALISES) == 1 and m.balises.echecs == 1   # de nouveau 1 min
    assert essai(3600 + VM.DUREE_BALISES + 59) == 0


def test_une_source_en_panne_ne_bloque_pas_les_autres():
    d = lire(vent(Reseau(pw=httpx.Response(500), terre=httpx.Response(200, content=b"pas du json"))))
    assert d["erreurs"] == [LIBELLE_PW, LIBELLE_WS3]
    assert {"callelongue", "stn292"} <= set(par_id(d)) and "port" not in par_id(d)


def test_ancien_cache_servi_avec_les_vrais_horodatages():
    t, maintenant, reseau = [0.0], [MAINTENANT], Reseau()
    m = vent(reseau, t, maintenant)
    avant = par_id(lire(m))
    reseau.reponses["pw"] = httpx.Response(502)
    t[0] = 1000
    maintenant[0] = MAINTENANT + timedelta(minutes=20)
    d = lire(m)
    assert d["erreurs"] == [LIBELLE_PW]
    assert par_id(d)["frioul"]["mesures"] == avant["frioul"]["mesures"]    # mêmes t : la tablette juge la fraîcheur
    assert d["lu_a"] == "2026-10-24T11:20:00+02:00"
    # Toutes les sources meurent et le temps passe : les mesures sortent de la fenêtre de 3 h, sans erreur levée.
    reseau.reponses.update(mh=httpx.Response(502), terre=httpx.Response(502))
    t[0] = 5000
    maintenant[0] = MAINTENANT + timedelta(hours=4)
    d = lire(m)
    assert d["stations"] == [] and d["erreurs"] == [LIBELLE_PW, LIBELLE_MH, LIBELLE_WS3]


# ------------------------------------------------------------ lecture en vol et erreurs
def lent(attente, reponse):
    def f(requete):
        time.sleep(attente)
        return reponse() if callable(reponse) else reponse
    return f


def test_lecture_unique_en_vol_par_source_et_en_parallele():
    reseau = Reseau(pw=lent(0.2, balises_inventees), mh=lent(0.2, officielles_inventees), terre=lent(0.2, terre_inventee))
    m = vent(reseau)

    async def deroule():
        return await asyncio.gather(m.donnees(), m.donnees(), m.donnees())
    debut = time.monotonic()
    a, b, c = asyncio.run(deroule())
    assert reseau.appels() == 3 and a == b == c
    assert time.monotonic() - debut < 0.5   # lues ensemble, pas l'une après l'autre


def test_rafraichissement_en_vol_ne_fait_pas_attendre_celui_qui_a_un_cache():
    t, reseau = [0.0], Reseau()
    m = vent(reseau, t)
    lire(m)
    reseau.reponses["pw"] = lent(0.5, balises_inventees)
    t[0] = VM.DUREE_BALISES

    async def deroule():
        premiere = asyncio.create_task(m.donnees())   # lance la relecture de Balises de la rade et l'attend
        await asyncio.sleep(0.1)
        debut = time.monotonic()
        d = await m.donnees()                         # sert l'ancien cache sans attendre ni relire
        duree = time.monotonic() - debut
        await premiere
        return d, duree
    d, duree = asyncio.run(deroule())
    assert duree < 0.25 and "frioul" in par_id(d)
    assert reseau.appels("pw") == 2


def test_source_trop_lente_ne_bloque_pas_les_autres(monkeypatch):
    monkeypatch.setattr(VM, "MARGE", 0.05)
    m = vent(Reseau(terre=lent(0.6, terre_inventee)))
    m.station_terre.delai = 0.05

    async def deroule():
        debut = time.monotonic()
        return await m.donnees(), time.monotonic() - debut
    d, duree = asyncio.run(deroule())
    assert duree < 0.5 and d["erreurs"] == [LIBELLE_WS3] and "port" not in par_id(d)
    assert m.station_terre.erreur == "station ne répond pas (délai de 0.05 s)"


def test_demande_abandonnee_ne_declenche_pas_de_seconde_lecture(monkeypatch):
    monkeypatch.setattr(VM, "ATTENTE_MAX", 0.05)
    reseau = Reseau(pw=lent(0.3, balises_inventees), mh=lent(0.3, officielles_inventees), terre=lent(0.3, terre_inventee))
    m = vent(reseau)

    async def deroule():
        with pytest.raises(VM.ErreurVent, match="aucune source ne répond encore"):
            await m.donnees()
        await asyncio.sleep(0.6)
        return await m.donnees()
    assert "frioul" in par_id(asyncio.run(deroule()))
    assert reseau.appels() == 3


def test_rien_n_a_jamais_donne_donne_erreur():
    t = [0.0]
    reseau = Reseau(pw=httpx.Response(500), mh=httpx.Response(503, text="Erreur 1234"), terre=httpx.Response(404))
    m = vent(reseau, t)
    with pytest.raises(VM.ErreurVent) as e:
        lire(m)
    assert str(e.value) == ("mesures de vent indisponibles : Balises de la rade a répondu 500, Stations officielles a répondu 503, "
                            "station a répondu 404")
    avant = reseau.appels()
    with pytest.raises(VM.ErreurVent):
        lire(m)   # attente de 1 min : aucune lecture
    assert reseau.appels() == avant
    reseau.reponses.update(pw=balises_inventees())
    t[0] = 61
    assert "frioul" in par_id(lire(m))


@pytest.mark.parametrize("cle,taille,attendu", [
    ("pw", VM.TAILLE_BALISES, "réponse de Balises de la rade trop grande (plus de 2 Mo)"),
    ("mh", VM.TAILLE_OFFICIELLES, "réponse de Stations officielles trop grande (plus de 4 Mo)"),
    ("terre", VM.TAILLE_TERRE, "réponse de station trop grande (plus de 1 Mo)")])
def test_plafond_de_taille_par_source(cle, taille, attendu):
    m = vent(Reseau(**{cle: httpx.Response(200, content=b"x" * (taille + 1))}))
    lire(m)
    assert next(s for s in m.sources if s.nom == {"pw": "Balises de la rade", "mh": "Stations officielles", "terre": "station"}[cle]).erreur == attendu


def test_plafond_de_taille_en_flux():
    m = vent(Reseau(pw=httpx.Response(200, content=(b"x" * 500_000 for _ in range(5)))))
    lire(m)
    assert m.balises.erreur == "réponse de Balises de la rade trop grande (plus de 2 Mo)"


def test_erreurs_reseau_et_json():
    def coupe(requete):
        raise httpx.ConnectError("refusé 1.2.3.4", request=requete)

    def lente(requete):
        raise httpx.ReadTimeout("lent", request=requete)

    def casse(requete):
        raise ValueError("valeur 98 secrète")
    m = vent(Reseau(pw=coupe, mh=lente, terre=httpx.Response(200, content=b"{")))
    with pytest.raises(VM.ErreurVent):
        lire(m)
    assert m.balises.erreur == "Balises de la rade injoignable (ConnectError)"
    assert m.stations_officielles.erreur == "Stations officielles ne répond pas (délai de 20 s)"
    assert m.station_terre.erreur == "réponse illisible de station"
    m = vent(Reseau(pw=casse))
    lire(m)
    assert m.balises.erreur == "Balises de la rade : erreur inattendue (ValueError)"   # la classe seulement, pas le texte


def test_bilan_pour_le_journal():
    t, reseau = [0.0], Reseau()
    m = vent(reseau, t)
    lire(m)
    assert m.bilan() == "mesures servies (Balises de la rade, Stations officielles, station)"
    reseau.reponses["pw"] = httpx.Response(502)
    t[0] = VM.DUREE_BALISES
    lire(m)
    assert m.bilan() == "mesures servies (Stations officielles, station), en panne : Balises de la rade a répondu 502"


# ------------------------------------------------------------ serveur : capacité et message
class FauxWs:
    def __init__(self):
        self.envois = []

    async def send(self, texte):
        self.envois.append(json.loads(texte))


def moteur(vent_mesure):
    import serveur_satellite as S
    m = object.__new__(S.Moteur)  # sans charger les modèles
    m.sante, m.sante_personnes, m.meteo_mer, m.vent_mesure = None, frozenset(), None, vent_mesure
    return m


def satellite(vent_mesure):
    import serveur_satellite as S
    sat = object.__new__(S.Satellite)  # sans charger le mot de réveil
    sat.ws, sat.moteur, sat.nom = FauxWs(), moteur(vent_mesure), "essai"
    sat.identite, sat.chiffre = None, False  # connexion en clair, sans identité : servi quand même
    return sat


def test_capacite_vent_mesure(monkeypatch):
    import serveur_satellite as S

    class FauxAssistant:
        ha = None
    m = moteur(VM.VentMesure())
    m.profil, m.assistant, m.empreinte_tls, m.vision = "ha", FauxAssistant(), "", None
    assert m.capacites()["vent_mesure"] is True
    sat = object.__new__(S.Satellite)
    sat.identite, sat.chiffre = None, False
    assert m.capacites(sat)["vent_mesure"] is True   # aucune restriction d'accès
    m.vent_mesure = None
    assert m.capacites(sat)["vent_mesure"] is False
    del m.vent_mesure  # moteur construit sans l'attribut : faux, sans lever
    assert m.capacites()["vent_mesure"] is False
    monkeypatch.delenv("VENT_MESURE", raising=False)
    monkeypatch.delenv("METEO_MER", raising=False)
    assert isinstance(VM.depuis_env(), VM.VentMesure)
    monkeypatch.setenv("VENT_MESURE", "1")
    assert isinstance(VM.depuis_env(), VM.VentMesure)
    for eteint in ("0", " 0 ", "non", "false", "off"):
        monkeypatch.setenv("VENT_MESURE", eteint)
        assert VM.depuis_env() is None
    # METEO_MER=0 éteint aussi le vent (0.27.2), VENT_MESURE=0 n'éteint pas la mer.
    monkeypatch.setenv("VENT_MESURE", "1")
    for eteint in ("0", "non", "false", "off"):
        monkeypatch.setenv("METEO_MER", eteint)
        assert VM.depuis_env() is None and MM.depuis_env() is None
    monkeypatch.setenv("METEO_MER", "1")
    monkeypatch.setenv("VENT_MESURE", "0")
    assert VM.depuis_env() is None and isinstance(MM.depuis_env(), MM.MeteoMer)


def test_message_vent_mesure_servi(capsys):
    sat = satellite(vent(Reseau()))

    async def deroule():
        await sat.recevoir_texte(json.dumps({"type": "vent_mesure", "id": 7}))
        for _ in range(200):
            if sat.ws.envois:
                break
            await asyncio.sleep(0.01)
    asyncio.run(deroule())
    assert len(sat.ws.envois) == 1
    envoi = sat.ws.envois[0]
    assert set(envoi) == {"etat", "id", "donnees"} and envoi["etat"] == "vent_mesure" and envoi["id"] == 7
    assert set(envoi["donnees"]) == {"lu_a", "stations", "erreurs"}
    assert [s["id"] for s in envoi["donnees"]["stations"]][:3] == ["callelongue", "frioul", "prado"]
    assert "[essai] vent : mesures servies (Balises de la rade, Stations officielles, station)" in capsys.readouterr().out


def test_message_vent_mesure_erreurs(capsys):
    sat = satellite(vent(Reseau(pw=httpx.Response(503), mh=httpx.Response(503), terre=httpx.Response(503))))
    asyncio.run(sat.repondre_vent_mesure({"id": 1}))
    texte = "mesures de vent indisponibles : Balises de la rade a répondu 503, Stations officielles a répondu 503, station a répondu 503"
    assert sat.ws.envois == [{"etat": "vent_mesure", "id": 1, "erreur": texte}]
    assert f"[essai] vent : {texte}" in capsys.readouterr().out

    class Cassee:
        async def donnees(self):
            raise ValueError("valeur 98 illisible")
    sat = satellite(Cassee())
    asyncio.run(sat.repondre_vent_mesure({"id": 2}))
    assert sat.ws.envois == [{"etat": "vent_mesure", "id": 2, "erreur": "erreur inattendue (ValueError)"}]
    assert "98" not in capsys.readouterr().out
    sat = satellite(None)
    asyncio.run(sat.repondre_vent_mesure({"id": 3}))
    assert sat.ws.envois == [{"etat": "vent_mesure", "id": 3, "erreur": "vent mesuré éteint sur ce serveur"}]


def test_reduire_balises_horodatage_en_millisecondes_ou_futur():
    brut = [{"result": {"data": {"json": {"observationData": [
        {"t": (T0 - 60) * 1000, "id": 101, "tws": 12.0, "twd": 240, "gust": 15},
        {"t": T0 + 3600, "id": 101, "tws": 99.0, "twd": 0, "gust": 0},
    ]}}}}]
    sortie = VM.reduire_balises(brut, "Balises de la rade", maintenant=T0)
    assert list(sortie[101]) == [T0 - 60]


def test_reduire_balises_plus_aucune_mesure_lisible_est_une_erreur():
    brut = [{"result": {"data": {"json": {"observationData": [{"t": "2026-10-24T09:00", "id": 101, "speed": 12}]}}}}]
    with pytest.raises(VM.ErreurVent):
        VM.reduire_balises(brut, "Balises de la rade", maintenant=T0)


def test_callelongue_officielle_perimee_laisse_revenir_la_balise():
    pw = {104: {T0 - 60: VM.mesure(13.0, 350, None)}}
    vieux = T0 - 2 * 3600 + 120
    mh = [{"id": "callelongue", "nom": "Callelongue", "genre": "station officielle", "type": "mer", "point": "prado",
           "lat": 43.2105, "lon": 5.3402, "mesures": {vieux: VM.mesure(12.0, 340, None)}}]
    d = VM.assembler(pw, mh, None, MAINTENANT)
    callelongue = [s for s in d["stations"] if s["id"] == "callelongue"]
    assert len(callelongue) == 1 and callelongue[0]["source"] == "balises"


def test_sans_section_vent_active_le_module_est_eteint(monkeypatch):
    """Configuration sans section « vent » active, ou sans la mer : pas de vent mesuré."""
    monkeypatch.delenv("VENT_MESURE", raising=False)
    monkeypatch.setattr(VM, "ACTIF", False)
    assert VM.depuis_env() is None
    monkeypatch.setattr(VM, "ACTIF", True)
    monkeypatch.setattr(VM.MM, "ACTIF", False)
    assert VM.depuis_env() is None
