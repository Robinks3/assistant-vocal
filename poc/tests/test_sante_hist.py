"""Historique de santé (0.20.0). Toutes les valeurs ci-dessous sont inventées."""
import asyncio
import json
from datetime import date as Date, timedelta

import httpx
import pytest

import sante as SA
import sante_hist as SH

AUJOURDHUI = Date(2031, 3, 15)  # un samedi
HOTE = "sante.exemple.ts.net"
URL = f"https://{HOTE}/dashboard/HealthStats/dashboard/data-auto.js"


def jour(**champs):
    """Jour au format du tableau de bord (days[date] de data-auto.js)."""
    base = {"steps": 8000, "dist": None, "kcal": 2100, "active": None, "floors": None, "sleepH": 7.0,
            "sleepScore": None, "deepPct": None, "remPct": None, "sleepStages": None, "hr": 64.25, "hrMin": 51,
            "hrMax": 150, "stress": None, "spo2Min": 93, "weight": None, "speedAvg": None, "speedMax": None,
            "fatigue": None, "recovery": None, "acwr": None, "sessions": []}
    base.update(champs)
    return base


def pesee():
    """Jour où seule une pesée existe : tout est null."""
    return jour(steps=None, kcal=None, sleepH=None, hr=None, hrMin=None, hrMax=None, spo2Min=None, weight=70)


def seance(ident, debut, fin, type_="course", minutes=60, km=0, **detail):
    d = {"id": ident, "typeBrut": type_, "typeCode": 52, "titre": "Séance inventée", "debut": debut, "fin": fin,
         "decalage": "+01:00", "fcMin": 90, "fcMax": 175, "fcMoy": 140.5, "fcN": 3000,
         "fcCourbe": [[i / 2, 120 + i % 50] for i in range(120)],
         "zones": {"z1": 5, "z2": 10, "z3": 20, "z4": 15, "z5": 6.5}, "trimp": 80, "vitMoy": 9.9, "vitMax": 30.1,
         "origine": "com.exemple", "saisie": 1}
    d.update(detail)
    return {"t": "course / course", "min": minutes, "km": km, "cal": 600, "hr": 140.5, "start": debut[11:16], "detail": d}


def sans_fc(s):
    s["detail"].update(fcMin=None, fcMax=None, fcMoy=None, fcN=0, fcCourbe=None, zones=None, trimp=None)
    s["hr"] = 0
    return s


def fichier(days, first=None, genere="2031-03-15T07:00:00.000Z"):
    payload = {"generatedAt": genere, "source": "Health Connect, export automatique", "cle": "auto",
               "range": {"first": first or min(days), "last": max(days), "days": len(days)}, "days": days}
    return ("window.HEALTHSTATS_AUTO = " + json.dumps(payload) + ";\n").encode()


def donnees(days, first=None, **kw):
    return SH.reduire_fichier(fichier(days, first, **kw), "2031-03-15T09:00:00", 0.0)


def iso(x):
    return x.isoformat()


def plage(debut, fin):
    return SH.jours_entre(debut, fin)


# ------------------------------------------------------------ lecture du fichier et réduction
def test_reduction_d_un_jour_et_de_sa_nuit():
    nuit = {"start": "2031-03-13T22:30:00.000Z", "dureeMin": 410,
            "seq": [[0, 20, 4], [20, 30, 1], [50, 90, 5], [140, 200, 4], [340, 60, 6], [400, 10, 7]]}
    d = donnees({"2031-03-14": jour(sleepH=7.9, sleepStages=nuit, dist=3.456), "2031-03-13": jour(sleepH=6.5)})
    j = d.jours[Date(2031, 3, 14)]
    assert (j.sommeil, j.au_lit, j.profond) == (370, 410, 90)  # éveils (codes 1 et 7) retirés, siestes non comptées
    assert j.distance_m == 3456 and j.pas == 8000 and j.fc_moyenne == 64.3
    sans_stades = d.jours[Date(2031, 3, 13)]
    assert (sans_stades.sommeil, sans_stades.au_lit, sans_stades.profond) == (390, 390, None)  # repli sur sleepH
    assert d.premier == Date(2031, 3, 13) and d.genere == "2031-03-15T07:00:00.000Z"


def test_fichier_vide_tronque_ou_etranger():
    with pytest.raises(SA.ErreurSante, match="historique vide"):
        SH.reduire_fichier(b"window.HEALTHSTATS_AUTO = null;\n")
    complet = fichier({"2031-03-14": jour()})
    with pytest.raises(SA.ErreurSante, match="tronqué"):
        SH.reduire_fichier(complet[: len(complet) // 2])
    with pytest.raises(SA.ErreurSante, match="forme inattendue"):
        SH.reduire_fichier(b"<html>portail</html>")
    with pytest.raises(SA.ErreurSante, match="sans jours"):
        SH.reduire_fichier(b'window.HEALTHSTATS_AUTO = {"days": {"pas une date": {}}};')


def test_entrees_quelconques_tolerees():
    d = donnees({"2031-03-14": jour(steps="8000", hr=float("nan"), sleepStages={"seq": [[0, 10], "x", [0, 5, 99]]},
                                    sessions=[3, None, {"t": "Inconnu", "min": True}])})
    j = d.jours[Date(2031, 3, 14)]
    assert j.pas is None and j.fc_moyenne is None and j.nuit is None and j.sommeil == 420
    assert len(j.seances) == 1  # la séance illisible devient « autre », les non-objets sont ignorés
    s = d.seances[j.seances[0]]
    assert s.sport == "autre" and s.minutes is None and s.debut is None and not s.avec_fc


# ------------------------------------------------------------ période et comparaison
def jeu_periode():
    days = {iso(x): jour(steps=6000) for x in plage(Date(2031, 3, 2), Date(2031, 3, 8))}
    days["2031-03-05"] = pesee()
    for x in plage(Date(2031, 3, 9), Date(2031, 3, 14)):
        days[iso(x)] = jour(steps=9000, dist=3.0)
    del days["2031-03-11"]                     # jour sans donnée
    days["2031-03-10"]["dist"] = None          # renseigné sans distance : 0 dans la moyenne
    days["2031-03-10"]["sessions"] = [seance("ski-1", "2031-03-10T09:00:00Z", "2031-03-10T11:00:00Z", "ski",
                                             minutes=120, trimp=200)]
    days["2031-03-13"]["sessions"] = [seance("course-1", "2031-03-13T18:00:00Z", "2031-03-13T19:00:00Z")]
    days["2031-03-15"] = jour(steps=99999, hrMin=30, spo2Min=85, sessions=[
        seance("course-1", "2031-03-15T07:00:00Z", "2031-03-15T07:30:00Z", "course", minutes=30, km=5.0, trimp=40)])
    return donnees(days)


def test_periode_de_7_jours_et_comparaison():
    p = SH.periode(jeu_periode(), 7, AUJOURDHUI)
    assert (p["du"], p["au"], p["granularite"]) == ("2031-03-09", "2031-03-15", "jour")
    s = p["serie"]
    assert s["dates"] == [iso(x) for x in plage(Date(2031, 3, 9), AUJOURDHUI)]
    assert s["en_cours"] == [False] * 6 + [True]
    assert s["pas"] == [9000, 9000, None, 9000, 9000, 9000, 99999]
    assert s["seance"] == [False, True, None, False, True, False, True]
    assert s["sommeil_minutes"][2] is None and s["fc_min"][2] is None  # jour manquant : null, jamais 0
    assert s["sommeil_estime"] == [True, True, None, True, True, True, True]  # sleepH sans stades
    assert p["courbes"] == {"granularite": "jour", **s}
    b = p["bilan"]
    assert (b["du"], b["au"], b["jours"], b["couverture"]) == ("2031-03-09", "2031-03-15", 6, 5)
    assert (b["jours_disponibles"], b["partielle"], b["jours_sommeil_estime"]) == (7, False, 5)
    assert b["pas"] == 9000 and b["fc_repos"] == 51 and b["sommeil_minutes"] == 420
    assert b["distance_m"] == 2400  # (4 x 3000 + 0) / 5
    assert b["spo2_min"] == 85      # un minimum, pas une moyenne : aujourd'hui compte
    sp = b["sport"]
    assert sp["minutes"] == 210 and sp["seances"] == 3 and sp["sans_fc"] == 0
    assert sp["trimp"] == 120  # ski exclu de la charge
    assert (sp["minutes_par_semaine"], sp["seances_par_semaine"], sp["trimp_par_semaine"]) == (210, 3, 120)
    assert sp["par_sport"]["ski"] == {"nom": "Ski", "minutes": 120, "seances": 1, "trimp": None, "sans_fc": 0}
    assert sp["par_sport"]["course"]["trimp"] == 80
    assert sp["par_sport"]["course"] == {"nom": "Course à pied", "minutes": 30, "seances": 1, "trimp": 40,
                                         "sans_fc": 0}
    a = p["avant"]
    assert (a["du"], a["au"], a["jours"], a["couverture"], a["pas"]) == ("2031-03-02", "2031-03-08", 7, 6, 6000)
    assert (a["jours_disponibles"], a["partielle"], a["sport"]["trimp"]) == (7, False, None)
    assert p["hors_charge"] == ["ski", "snowboard"]
    groupes = p["sport"]["groupes"]
    assert p["sport"]["granularite"] == "jour" and len(groupes) == 7 and p["sport"]["par_mois"] is None
    assert groupes[-1]["en_cours"] and groupes[-1]["seances"] == 1
    assert groupes[1]["trimp"] is None and groupes[1]["minutes"] == 120  # ski seul : pas de charge
    assert groupes[0]["trimp"] is None and groupes[0]["seances"] == 0
    assert "minutes_par_semaine" not in groupes[0]
    json.dumps(p)


def test_jour_en_cours_exclu_des_moyennes():
    days = {iso(x): jour(steps=5000, sleepH=6) for x in plage(Date(2031, 3, 1), Date(2031, 3, 14))}
    days["2031-03-15"] = jour(steps=50000, sleepH=12, hr=120, hrMin=90)
    b = SH.periode(donnees(days), 7, AUJOURDHUI)["bilan"]
    assert (b["pas"], b["sommeil_minutes"], b["fc_repos"], b["fc_moyenne"]) == (5000, 360, 51, 64.3)


def test_avant_absent_si_trop_peu_de_jours():
    days = {iso(x): jour() for x in plage(Date(2031, 3, 9), AUJOURDHUI)}
    days.update({"2031-03-02": jour(), "2031-03-04": jour(), "2031-03-06": jour()})  # 3 jours sur 7
    assert SH.periode(donnees(days), 7, AUJOURDHUI)["avant"] is None  # sous le plancher de 4
    days["2031-03-08"] = jour()  # 4 jours sur 7 : assez
    assert SH.periode(donnees(days), 7, AUJOURDHUI)["avant"]["couverture"] == 4


def test_avant_partielle_ou_trop_courte():
    days = {iso(x): jour() for x in plage(Date(2031, 3, 3), AUJOURDHUI)}  # commence un jour trop tard
    a = SH.periode(donnees(days), 7, AUJOURDHUI)["avant"]
    assert (a["du"], a["au"], a["partielle"], a["jours_disponibles"], a["couverture"]) == (
        "2031-03-03", "2031-03-08", True, 6, 6)
    days = {iso(x): jour() for x in plage(Date(2031, 3, 7), AUJOURDHUI)}  # 2 jours avant : trop court
    assert SH.periode(donnees(days), 7, AUJOURDHUI)["avant"] is None
    days = {iso(x): jour() for x in plage(Date(2031, 3, 9), AUJOURDHUI)}  # rien avant
    assert SH.periode(donnees(days), 7, AUJOURDHUI)["avant"] is None


def jeu_un_an_et_demi(debut):
    """Une séance de 60 min chaque lundi et chaque jeudi, du premier jour au 22/10/2026."""
    days = {}
    for x in plage(debut, Date(2026, 10, 22)):
        sessions = ([seance(f"s-{iso(x)}", f"{iso(x)}T18:00:00Z", f"{iso(x)}T19:00:00Z", trimp=70)]
                    if x.weekday() in (0, 3) else [])
        days[iso(x)] = jour(steps=7000, sessions=sessions)
    return donnees(days)


def test_vue_365_jours_avec_avant_partielle():
    aujourdhui = Date(2026, 10, 22)
    d = jeu_un_an_et_demi(Date(2025, 3, 12))
    p = SH.periode(d, 365, aujourdhui)
    b, a = p["bilan"], p["avant"]
    assert (b["du"], b["jours_disponibles"], b["partielle"]) == ("2025-10-23", 365, False)
    # Période précédente du 23/10/2024 au 22/10/2025, données à partir du 12/03/2025 : environ 7 mois.
    assert (a["du"], a["au"], a["partielle"], a["jours_disponibles"], a["couverture"]) == (
        "2025-03-12", "2025-10-22", True, 225, 225)
    # Les totaux ne se comparent pas sur 225 et 365 jours, les valeurs par semaine si.
    assert a["sport"]["minutes"] < b["sport"]["minutes"]
    for bloc in (a, b):
        assert abs(bloc["sport"]["minutes_par_semaine"] - 120) <= 3
        assert abs(bloc["sport"]["seances_par_semaine"] - 2) <= 0.1
        assert abs(bloc["sport"]["trimp_par_semaine"] - 140) <= 4
    # Avant un an de données, la période en cours n'a pas ses 365 jours.
    b = SH.periode(d, 365, Date(2025, 12, 31))["bilan"]
    assert (b["du"], b["jours_disponibles"], b["partielle"]) == ("2025-03-12", 295, True)


def test_vue_365_jours_avant_trop_courte():
    d = jeu_un_an_et_demi(Date(2025, 10, 1))  # 22 jours avant la période : sous le plancher de 28
    assert SH.periode(d, 365, Date(2026, 10, 22))["avant"] is None


def test_semaines_du_lundi_pour_90_et_365_jours():
    days = {iso(x): jour(steps=1000 * (x.weekday() + 1)) for x in plage(Date(2030, 1, 1), AUJOURDHUI)}
    days["2031-03-15"]["steps"] = 99999
    p = SH.periode(donnees(days), 90, AUJOURDHUI)
    c = p["courbes"]
    assert p["granularite"] == "semaine" and c["granularite"] == "semaine"
    assert all(Date.fromisoformat(x).weekday() == 0 for x in c["dates"])
    assert c["dates"][0] == p["du"] == "2030-12-16" and len(c["dates"]) == 13
    assert c["dates"][-1] == "2031-03-10" and c["en_cours"][-1] and not any(c["en_cours"][:-1])
    assert c["pas"][1] == 4000                    # semaine complète : moyenne de 1000 à 7000
    assert c["pas"][-1] == 3000 and c["jours_renseignes"][-1] == 5  # lundi à vendredi, samedi en cours exclu
    assert c["jours_seance"][-1] == 0
    assert len(p["serie"]["dates"]) == 90
    assert all(Date.fromisoformat(g["debut"]).weekday() == 0 for g in p["sport"]["groupes"])
    an = SH.periode(donnees(days), 365, AUJOURDHUI)
    assert an["du"] == "2030-03-16" and an["courbes"]["dates"][0] == "2030-03-11"  # premier lundi à cheval
    assert an["courbes"]["pas"][0] == 6500 and an["sport"]["groupes"][0]["jours"] == 2  # samedi et dimanche
    mois = an["sport"]["par_mois"]
    assert mois[0]["debut"] == "2030-03-01" and mois[0]["jours"] == 16 and mois[-1]["debut"] == "2031-03-01"
    assert sum(m["jours"] for m in mois) == 365 and mois[-1]["en_cours"] and mois[-1]["jours"] == 15


def test_changement_d_heure_du_25_octobre_2026():
    aujourdhui = Date(2026, 10, 27)
    days = {iso(x): jour() for x in plage(Date(2026, 10, 1), aujourdhui)}
    days["2026-10-25"]["sessions"] = [
        seance("avant-bascule", "2026-10-25T00:30:00Z", "2026-10-25T00:40:00Z", minutes=10, decalage=None),
        seance("apres-bascule", "2026-10-25T01:30:00Z", "2026-10-25T01:50:00Z", minutes=20, decalage=None),
        seance("decalage-porte", "2026-10-25T16:00:00Z", "2026-10-25T17:00:00Z", decalage="+01:00")]
    days["2026-10-25"]["sleepStages"] = {"start": "2026-10-24T21:30:00Z", "dureeMin": 540, "seq": [[0, 540, 4]]}
    d = donnees(days)
    p = SH.periode(d, 7, aujourdhui)
    assert p["serie"]["dates"] == ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25",
                                   "2026-10-26", "2026-10-27"]
    heures = {s["seance_id"]: s["debut_local"] for s in SH.liste_seances(d, 7, "tous", aujourdhui)["seances"]}
    # Repli Europe/Paris : 02:30 à l'heure d'été, puis 02:30 encore à l'heure d'hiver.
    assert heures == {"avant-bascule": "2026-10-25T02:30", "apres-bascule": "2026-10-25T02:30",
                      "decalage-porte": "2026-10-25T17:00"}
    semaine = next(g for g in SH.periode(d, 30, aujourdhui)["sport"]["groupes"] if g["debut"] == "2026-10-19")
    assert semaine["jours"] == 7 and semaine["seances"] == 3 and not semaine["en_cours"]
    assert SH.vue_jour(d, Date(2026, 10, 25), aujourdhui)["nuit"]["debut_local"] == "2026-10-24T23:30"


def test_debut_des_donnees_un_mercredi():
    debut, aujourdhui = Date(2025, 3, 12), Date(2025, 3, 30)  # mercredi 12/03, dimanche 30/03
    days = {}
    for x in plage(debut, aujourdhui):
        pas = 30000 if x < Date(2025, 3, 17) else (12000 if x < Date(2025, 3, 24) else 20000)
        days[iso(x)] = jour(steps=pas)
    d = donnees(days)
    assert d.premier == debut
    r = SH.records(d, aujourdhui, 10000, 420)["records"]
    # Première semaine (incomplète) et semaine en cours (complète, aujourd'hui dimanche) écartées.
    assert r["meilleure_semaine_pas"] == {"valeur": 84000, "unite": "pas", "lundi": "2025-03-17", "battu_le": None}
    assert SH.records(d, Date(2025, 3, 29), 10000, 420)["records"]["meilleure_semaine_pas"]["battu_le"] == "2025-03-23"
    p = SH.periode(d, 7, Date(2025, 3, 18))
    assert p["avant"] is None  # du 05/03 au 11/03 : commence avant le premier jour
    c = SH.periode(d, 90, aujourdhui)["courbes"]
    i = c["dates"].index("2025-03-10")
    assert c["pas"][i] == 30000 and c["jours_renseignes"][i] == 5 and c["pas"][i - 1] is None
    # Données qui commencent un lundi : la première semaine, même complète, reste écartée.
    lundi = {iso(x): jour(steps=50000 if x < Date(2025, 3, 17) else 11000) for x in plage(Date(2025, 3, 10), aujourdhui)}
    assert SH.records(donnees(lundi), aujourdhui, 10000, 420)["records"]["meilleure_semaine_pas"]["lundi"] == "2025-03-17"


# ------------------------------------------------------------ séances
def test_seance_sans_fc():
    days = {"2031-03-14": jour(sessions=[sans_fc(seance("s1", "2031-03-14T18:00:00Z", "2031-03-14T19:00:00Z"))])}
    d = donnees(days)
    s = d.seances["s1"]
    assert not s.avec_fc and s.trimp is None and s.zones is None
    ligne = SH.liste_seances(d, 7, "tous", AUJOURDHUI)["seances"][0]
    assert ligne["avec_fc"] is False and ligne["fc_moyenne"] is None and ligne["trimp"] is None
    total = SH.periode(d, 7, AUJOURDHUI)["bilan"]["sport"]
    assert total["sans_fc"] == 1 and total["trimp"] is None and total["minutes"] == 60
    assert total["trimp_par_semaine"] is None and total["par_sport"]["course"]["sans_fc"] == 1
    detail = SH.detail_seance(d, s, 193, None)
    assert detail["zones_minutes"] is None and detail["fc_courbe"] is None and detail["zones_bornes"] is not None
    assert SH.records(d, AUJOURDHUI, 10000, 420)["records"]["fc_la_plus_haute"] is None


def test_seances_emboitees_ecartees():
    days = {"2031-03-14": jour(sessions=[
        seance("courte", "2031-03-14T18:30:00Z", "2031-03-14T19:00:00Z", minutes=30),
        seance("longue", "2031-03-14T18:00:00Z", "2031-03-14T19:30:00Z", minutes=90),
        seance("doublon", "2031-03-14T18:00:00Z", "2031-03-14T19:30:00Z", minutes=90),
        seance("chevauche", "2031-03-14T19:15:00Z", "2031-03-14T20:00:00Z", minutes=45)])}
    d = donnees(days)
    assert d.jours[Date(2031, 3, 14)].seances == ("longue", "chevauche")
    l = SH.liste_seances(d, 7, "tous", AUJOURDHUI)
    assert [s["seance_id"] for s in l["seances"]] == ["chevauche", "longue"]
    assert l["total"] == {"seances": 2, "minutes": 135, "distance_m": 0, "trimp": 160, "sans_fc": 0}


def test_liste_des_seances_par_sport():
    days = {"2031-03-13": jour(sessions=[
                seance("c1", "2031-03-13T07:00:00Z", "2031-03-13T07:25:00Z", "course", minutes=25, km=5.0),
                seance("h1", "2031-03-13T18:00:00Z", "2031-03-13T19:00:00Z")]),
            "2031-03-14": jour(sessions=[seance("t1", "2031-03-14T07:00:00Z", "2031-03-14T07:20:00Z", "course_tapis",
                                                minutes=20, km=4.0)])}
    d = donnees(days)
    l = SH.liste_seances(d, 30, "course", AUJOURDHUI)
    assert [s["seance_id"] for s in l["seances"]] == ["t1", "c1"]
    assert l["par_sport"] == {"course": {"nom": "Course à pied", "seances": 2, "minutes": 45, "distance_m": 9000,
                                         "trimp": 160, "sans_fc": 0}}
    c1 = l["seances"][1]
    assert c1 == {"seance_id": "c1", "date": "2031-03-13", "debut_local": "2031-03-13T08:00", "minutes": 25,
                  "sport": "course", "nom": "Course à pied", "distance_m": 5000, "allure_s_par_km": 300,
                  "fc_moyenne": 140.5, "fc_max": 175, "trimp": 80, "avec_fc": True}
    course = SH.liste_seances(d, 30, "course", AUJOURDHUI)["seances"]
    assert [s["seance_id"] for s in course] == ["h1"] and course[0]["allure_s_par_km"] is None


def test_detail_d_une_seance_et_bornes_des_zones():
    d = donnees({"2031-03-14": jour(sessions=[seance("h1", "2031-03-14T18:00:00Z", "2031-03-14T19:00:00Z")])})
    detail = SH.detail_seance(d, d.seances["h1"], 193, None)
    assert detail["zones_minutes"] == {"z1": 5, "z2": 10, "z3": 20, "z4": 15, "z5": 6.5}
    assert len(detail["fc_courbe"]) == 120 and detail["fin_local"] == "2031-03-14T20:00"
    assert detail["zones_bornes"] == {
        "z1": {"nom": "récupération", "min_bpm": 0, "max_bpm": 115}, "z2": {"nom": "endurance", "min_bpm": 116, "max_bpm": 135},
        "z3": {"nom": "tempo", "min_bpm": 136, "max_bpm": 154}, "z4": {"nom": "seuil", "min_bpm": 155, "max_bpm": 173},
        "z5": {"nom": "anaérobie", "min_bpm": 174, "max_bpm": None}}  # 60 % de 193 = 115,8, etc.
    assert detail["dans_la_charge"] is True and detail["type"] == "course" and detail["analyse"] is None
    sans = SH.detail_seance(d, d.seances["h1"], None, None)
    assert sans["zones_bornes"] is None and sans["fc_max_reference"] is None


def test_fc_max_lue_dans_l_environnement(monkeypatch):
    monkeypatch.delenv("SANTE_FC_MAX", raising=False)
    assert SH.fc_max_env() is None
    for brut, attendu in (("186", 186), (" 177 ", 177), ("abc", None), ("80", None), ("", None)):
        monkeypatch.setenv("SANTE_FC_MAX", brut)
        assert SH.fc_max_env() == attendu


# ------------------------------------------------------------ records
def stades(minutes):
    """Nuit avec stades : minutes de sommeil léger puis 10 min d'éveil."""
    return {"start": "2031-03-01T22:00:00Z", "dureeMin": minutes + 10, "seq": [[0, minutes, 4], [minutes, 10, 1]]}


def jeu_records():
    days = {}
    pas = [9000, 9500, 7000, 8500, 8600, 8700, 12000, 3000]
    for i, x in enumerate(plage(Date(2031, 3, 1), Date(2031, 3, 8))):
        days[iso(x)] = jour(steps=pas[i], sleepH=9.5, sleepStages=stades(390 + 15 * i), hrMin=50 - i % 3)
    days["2031-03-02"]["sessions"] = [
        seance("pic", "2031-03-02T18:00:00Z", "2031-03-02T19:00:00Z", fcMax=230,           # artefact
               fcCourbe=[[0, 120], [30, 170], [59, 150]]),
        seance("ski", "2031-03-02T09:00:00Z", "2031-03-02T14:00:00Z", "ski", minutes=300, trimp=500)]
    days["2031-03-03"]["sessions"] = [
        seance("vrai", "2031-03-03T18:00:00Z", "2031-03-03T19:30:00Z", minutes=90, fcMax=190, trimp=150,
               fcCourbe=[[0, 120], [45, 185]], zones={"z5": 12.5})]
    days["2031-03-04"]["sessions"] = [
        seance("c10", "2031-03-04T07:00:00Z", "2031-03-04T07:55:00Z", "course", minutes=55, km=10.0)]
    days["2031-03-12"] = jour(steps=4000, sleepH=9, sessions=[
        seance("c5", "2031-03-12T07:00:00Z", "2031-03-12T07:25:00Z", "course", minutes=25, km=5.0),
        seance("c4", "2031-03-12T17:00:00Z", "2031-03-12T17:18:00Z", "course", minutes=18, km=4.0)])
    days["2031-03-14"] = jour(steps=2000, hrMin=44, sleepStages={
        "start": "2031-03-13T22:00:00Z", "dureeMin": 500, "seq": [[0, 200, 4], [200, 150, 5], [350, 150, 6]]})
    return donnees(days)


def test_records():
    d = jeu_records()
    sortie = SH.records(d, AUJOURDHUI, 10000, 420)
    assert sortie["depuis"] == "2031-03-01" and sortie["seuils"] == {"pas": 10000, "nuit_minutes": 420}
    r = sortie["records"]
    assert r["serie_pas"] == {"valeur": 1, "unite": "jours", "du": "2031-03-07", "au": "2031-03-07", "battu_le": None}
    assert r["journee_la_plus_active"] == {"valeur": 12000, "unite": "pas", "date": "2031-03-07", "battu_le": None}
    assert r["meilleure_semaine_pas"] is None  # aucune semaine complète hors première et en cours
    assert r["seance_la_plus_longue"]["seance_id"] == "ski"            # la durée compte le ski
    # Semaine du 24/02 : 60 min de course, le ski du même dimanche (300 min) exclu. Semaine du 03/03 : 90 + 55.
    assert r["semaine_la_plus_sportive"] == {"valeur": 145, "unite": "min", "lundi": "2031-03-03",
                                             "battu_le": "2031-03-09"}
    assert r["seance_la_plus_chargee"] == {"valeur": 150, "unite": "trimp", "date": "2031-03-03", "seance_id": "vrai",
                                           "sport": "course", "battu_le": None}
    assert r["zone5_la_plus_longue"]["valeur"] == 12.5
    assert r["course_la_plus_longue"]["valeur"] == 10 and r["course_la_plus_longue"]["seance_id"] == "c10"
    assert r["meilleure_allure_5km"] == {"valeur": 300, "unite": "s/km", "date": "2031-03-12", "seance_id": "c5",
                                         "sport": "course", "distance_m": 5000,
                                         "battu_le": "2031-03-12"}  # 4 km trop court
    # 230 bpm dépasse de plus de 15 bpm le sommet de sa courbe (170) : pic de capteur écarté.
    assert r["fc_la_plus_haute"] == {"valeur": 190, "unite": "bpm", "date": "2031-03-03", "seance_id": "vrai",
                                     "sport": "course", "battu_le": None}
    assert r["fc_la_plus_basse"] == {"valeur": 44, "unite": "bpm", "date": "2031-03-14", "battu_le": "2031-03-14"}
    # Le 12/03 n'a que sleepH (9 h au lit, estimé) : écarté, la plus longue nuit mesurée est celle du 14.
    assert r["nuit_la_plus_longue"] == {"valeur": 500, "unite": "min", "date": "2031-03-14", "battu_le": "2031-03-14"}
    assert r["sommeil_profond_le_plus_long"] == {"valeur": 150, "unite": "min", "date": "2031-03-14",
                                                 "battu_le": "2031-03-14"}
    assert r["serie_nuits"] == {"valeur": 6, "unite": "nuits", "du": "2031-03-03", "au": "2031-03-08", "battu_le": None}
    assert set(r) == {"serie_pas", "journee_la_plus_active", "meilleure_semaine_pas", "seance_la_plus_longue",
                      "course_la_plus_longue", "semaine_la_plus_sportive", "seance_la_plus_chargee",
                      "zone5_la_plus_longue", "meilleure_allure_5km", "nuit_la_plus_longue", "serie_nuits",
                      "sommeil_profond_le_plus_long", "fc_la_plus_basse", "fc_la_plus_haute"}


def test_records_seuils_lus_dans_l_environnement(monkeypatch, jour_fixe):
    h, vu = historique(httpx.Response(200, content=b""))
    h._donnees, h._t = jeu_records(), h._horloge()
    monkeypatch.setenv("SANTE_SEUIL_PAS", "8000")
    monkeypatch.setenv("SANTE_SEUIL_NUIT_MIN", "480")
    sortie = asyncio.run(h.repondre({"type": "sante_records", "id": 1}))
    assert sortie["seuils"] == {"pas": 8000, "nuit_minutes": 480}
    assert sortie["records"]["serie_pas"]["valeur"] == 4  # 8500, 8600, 8700, 12000
    assert sortie["records"]["serie_nuits"]["du"] == "2031-03-07"  # 390 + 15 x i : 480 min dès le 7
    monkeypatch.setenv("SANTE_SEUIL_PAS", "pas un nombre")
    monkeypatch.delenv("SANTE_SEUIL_NUIT_MIN")
    sortie = asyncio.run(h.repondre({"type": "sante_records", "id": 2}))
    assert sortie["seuils"] == {"pas": 6000, "nuit_minutes": 420}
    assert vu == []


# ------------------------------------------------------------ vue Jour
def test_vue_jour():
    d = jeu_records()
    v = SH.vue_jour(d, Date(2031, 3, 14), AUJOURDHUI)
    assert v["nuit"] == {"debut_local": "2031-03-13T23:00", "au_lit_minutes": 500, "sommeil_minutes": 500,
                         "profond_minutes": 150, "stades": {"leger": 200, "profond": 150, "paradoxal": 150},
                         "seq": [[0, 200, 4], [200, 150, 5], [350, 150, 6]]}
    assert v["codes_stades"]["5"] == "profond" and v["seances"] == [] and v["seance"] is False
    v = SH.vue_jour(d, Date(2031, 3, 12), AUJOURDHUI)
    assert [s["seance_id"] for s in v["seances"]] == ["c5", "c4"] and "fc_courbe" not in v["seances"][0]
    vide = SH.vue_jour(d, Date(2031, 3, 10), AUJOURDHUI)
    assert vide["renseigne"] is False and vide["pas"] is None and vide["seance"] is None and vide["nuit"] is None


# ------------------------------------------------------------ lecture réseau et caches
def historique(reponse, horloge=None, maintenant=None, adresses=("100.64.0.10",),
               source=lambda ip, port: "100.64.0.10", jeton="jeton-invente-de-test"):
    vu = []

    def appel(requete):
        vu.append(requete)
        return reponse(requete) if callable(reponse) else reponse
    kw = {k: v for k, v in (("horloge", horloge), ("maintenant", maintenant)) if v}
    h = SH.Historique("http://sante.exemple.ts.net:8096", jeton, url_donnees=URL,
                      transport=httpx.MockTransport(appel), resoudre=lambda hote: list(adresses), source=source, **kw)
    return h, vu


@pytest.fixture
def jour_fixe(monkeypatch):
    monkeypatch.setattr(SA, "date_du_jour", lambda: AUJOURDHUI)


def contenu():
    return fichier({"2031-03-14": jour(sessions=[seance("h1", "2031-03-14T18:00:00Z", "2031-03-14T19:00:00Z")]),
                    "2031-03-15": jour(steps=777)})


def test_lecture_par_l_adresse_verifiee(monkeypatch, jour_fixe):
    vus = []

    class Espion(httpx.Client):
        def __init__(self, **kw):
            vus.append(kw)
            super().__init__(**kw)
    monkeypatch.setattr(httpx, "Client", Espion)
    h, vu = historique(httpx.Response(200, content=contenu(), headers={"ETag": '"v1"'}))
    d = asyncio.run(h.donnees())
    assert d.jours[AUJOURDHUI].pas == 777 and h._etag == '"v1"'
    r = vu[0]
    assert r.url.scheme == "https" and r.url.host == "100.64.0.10" and r.url.port is None
    assert r.url.path == "/dashboard/HealthStats/dashboard/data-auto.js"
    assert r.headers["Host"] == HOTE and r.extensions["sni_hostname"] == HOTE  # nom en SNI : certificat vérifié
    assert "if-none-match" not in r.headers and "authorization" not in r.headers
    assert r.headers["accept-encoding"] == "identity"  # plafond de 16 Mo sur les octets reçus
    assert vus[0]["trust_env"] is False and "verify" not in vus[0]
    assert vus[0]["timeout"].read == 20 and vus[0]["timeout"].connect == 4


@pytest.mark.parametrize("adresses,source,attendu", [
    (("8.8.4.4",), lambda ip, port: "100.64.0.10", "ne mène pas dans Tailscale, lecture annulée"),
    (("100.64.0.10",), lambda ip, port: "192.168.0.20", "ne passe pas par Tailscale, lecture annulée"),
])
def test_hors_tailscale_aucune_lecture(adresses, source, attendu):
    h, vu = historique(httpx.Response(200, content=contenu()), adresses=adresses, source=source)
    with pytest.raises(SA.ErreurSante, match=attendu):
        asyncio.run(h.donnees())
    assert vu == []


def test_304_prolonge_le_cache(jour_fixe):
    t = [0.0]

    def reponse(requete):
        if requete.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=contenu(), headers={"ETag": '"v1"'})
    h, vu = historique(reponse, horloge=lambda: t[0])

    async def deroule():
        d1 = await h.donnees()
        t[0] = SH.DUREE_CACHE + 1
        d2 = await h.donnees()            # requête conditionnelle, 304
        t[0] += SH.DUREE_CACHE - 10
        d3 = await h.donnees()            # le 304 a prolongé le cache de 10 min
        t[0] += 20
        d4 = await h.donnees()
        return d1, d2, d3, d4
    d1, d2, d3, d4 = asyncio.run(deroule())
    assert d1 is d2 is d3 is d4
    assert len(vu) == 3 and "if-none-match" not in vu[0].headers
    assert vu[1].headers["if-none-match"] == '"v1"' and vu[2].headers["if-none-match"] == '"v1"'


def test_fichier_tronque_garde_l_ancien_cache(jour_fixe):
    t = [0.0]
    etat = {"corps": contenu()}
    h, vu = historique(lambda r: httpx.Response(200, content=etat["corps"]), horloge=lambda: t[0])

    async def deroule():
        d1 = await h.donnees()
        etat["corps"] = etat["corps"][:200]
        t[0] = SH.DUREE_CACHE + 1
        d2 = await h.donnees()            # tronqué : l'ancien cache est servi
        t[0] += 10
        d3 = await h.donnees()            # panne gardée 30 s, pas de nouvelle lecture
        etat["corps"] = b"window.HEALTHSTATS_AUTO = null;\n"
        t[0] += SH.DUREE_ERREUR
        d4 = await h.donnees()            # vide : toujours l'ancien cache
        etat["corps"] = fichier({"2031-03-15": jour(steps=4321)})
        t[0] += SH.DUREE_ERREUR + 1
        d5 = await h.donnees()
        return d1, d2, d3, d4, d5
    d1, d2, d3, d4, d5 = asyncio.run(deroule())
    assert d1 is d2 is d3 is d4 and len(vu) == 4
    assert d5 is not d1 and d5.jours[AUJOURDHUI].pas == 4321


def test_panne_sans_cache_gardee_30_s(jour_fixe):
    t = [0.0]
    h, vu = historique(httpx.Response(500, text="erreur 98 bpm"), horloge=lambda: t[0])

    async def deroule():
        for _ in range(2):
            with pytest.raises(SA.ErreurSante, match="le tableau de bord a répondu 500"):
                await h.donnees()
    asyncio.run(deroule())
    assert len(vu) == 1


def test_perime_apres_24_h(jour_fixe):
    maintenant = [SA.datetime(2031, 3, 15, 8, 0, tzinfo=SH.timezone.utc).timestamp()]
    h, _ = historique(httpx.Response(200, content=contenu()), maintenant=lambda: maintenant[0])
    d = asyncio.run(h.donnees())
    assert h.perime(d) is False
    maintenant[0] += 24 * 3600
    assert h.perime(d) is True  # generatedAt du 15/03 à 7 h


def test_plafond_de_taille(monkeypatch, jour_fixe):
    monkeypatch.setattr(SH, "TAILLE_MAX", 1000)
    h, _ = historique(httpx.Response(200, content=(b"x" * 400 for _ in range(5))))
    with pytest.raises(SA.ErreurSante, match="plus de 16 Mo"):
        asyncio.run(h.donnees())


def test_une_seule_lecture_en_vol(jour_fixe):
    import time

    def lent(requete):
        time.sleep(0.3)
        return httpx.Response(200, content=contenu())
    h, vu = historique(lent)

    async def deroule():
        return await asyncio.gather(*(h.donnees() for _ in range(4)))
    resultats = asyncio.run(deroule())
    assert len(vu) == 1 and all(r is resultats[0] for r in resultats)


# ------------------------------------------------------------ analyses écrites
def jeu_commentaires(commentaires):
    """Transport : data-auto.js, et une analyse par date (ou 404)."""
    days = {"2031-03-13": jour(sessions=[seance("seule", "2031-03-13T18:00:00Z", "2031-03-13T19:00:00Z")]),
            "2031-03-14": jour(sessions=[seance("matin", "2031-03-14T07:00:00Z", "2031-03-14T08:00:00Z"),
                                         seance("soir", "2031-03-14T18:00:00Z", "2031-03-14T19:00:00Z")])}

    def reponse(requete):
        if requete.url.path == "/api/commentaire":
            date = requete.url.params["date"]
            if date not in commentaires:
                return httpx.Response(404, json={"erreur": "aucun commentaire"})
            return httpx.Response(200, json={"date": date, "modele": "modele-invente", "genere": "2031-03-14T20:00:00Z",
                                             **commentaires[date]})
        return httpx.Response(200, content=fichier(days))
    return reponse


def detail(h, ident):
    return asyncio.run(h.repondre({"type": "sante_seance", "id": 1, "seance_id": ident}))


def test_commentaire_associe_ou_ignore(jour_fixe):
    h, vu = historique(jeu_commentaires({
        "2031-03-14": {"texte": "Analyse inventée du soir.", "seance_id": "soir"},
        "2031-03-13": {"texte": "x" * 7000, "seance_id": None}}))
    assert detail(h, "matin")["analyse"] is None            # l'analyse désigne une autre séance du jour
    assert detail(h, "soir")["analyse"] == {"texte": "Analyse inventée du soir.", "modele": "modele-invente",
                                            "genere": "2031-03-14T20:00:00Z"}
    assert len(detail(h, "seule")["analyse"]["texte"]) == SH.COMM_TEXTE_MAX  # seule séance du jour, plafonnée
    appels = [r for r in vu if r.url.path == "/api/commentaire"]
    assert len(appels) == 2                                   # une lecture par date, puis le cache
    r = appels[0]
    assert r.url.host == "100.64.0.10" and r.headers["Host"] == "sante.exemple.ts.net:8096"
    assert r.headers["Authorization"] == "Bearer jeton-invente-de-test"
    assert all("seule" not in str(x.url) and "matin" not in str(x.url) for x in vu)  # id jamais dans une URL


def test_commentaire_d_une_autre_seance_connue_ignore(jour_fixe):
    h, _ = historique(jeu_commentaires({"2031-03-13": {"texte": "Analyse inventée.", "seance_id": "soir"}}))
    assert detail(h, "seule")["analyse"] is None
    h, _ = historique(jeu_commentaires({"2031-03-13": {"texte": "Analyse inventée.", "seance_id": "inconnue-1"}}))
    assert detail(h, "seule")["analyse"]["texte"] == "Analyse inventée."
    h, _ = historique(jeu_commentaires({"2031-03-14": {"texte": "Analyse inventée.", "seance_id": None}}))
    assert detail(h, "matin")["analyse"] is None              # deux séances ce jour-là


def test_commentaire_absent_garde_60_s_et_purge_au_changement_de_jour(monkeypatch):
    t, jour_courant = [0.0], [AUJOURDHUI]
    monkeypatch.setattr(SA, "date_du_jour", lambda: jour_courant[0])
    h, vu = historique(jeu_commentaires({}), horloge=lambda: t[0])

    def lectures():
        return len([r for r in vu if r.url.path == "/api/commentaire"])
    assert detail(h, "seule")["analyse"] is None and lectures() == 1
    t[0] += 30
    detail(h, "seule")
    assert lectures() == 1
    t[0] += SH.COMM_ABSENT
    detail(h, "seule")
    assert lectures() == 2
    jour_courant[0] = AUJOURDHUI + timedelta(days=1)
    detail(h, "seule")
    assert lectures() == 3 and len(h._comm) == 1


def test_commentaire_sans_jeton_aucun_appel(jour_fixe):
    h, vu = historique(jeu_commentaires({"2031-03-13": {"texte": "x", "seance_id": None}}), jeton="")
    assert detail(h, "seule")["analyse"] is None
    assert all(r.url.path != "/api/commentaire" for r in vu)


def test_cache_des_commentaires_plafonne():
    h, _ = historique(httpx.Response(404))
    for i in range(SH.COMM_MAX + 5):
        h._ranger_commentaire(f"cle-{i}", None, 60)
    assert len(h._comm) == SH.COMM_MAX and "cle-0" not in h._comm and f"cle-{SH.COMM_MAX + 4}" in h._comm


# ------------------------------------------------------------ demandes et validation
@pytest.mark.parametrize("msg,attendu", [
    ({"type": "sante_periode", "jours": 14}, "période non prise en charge"),
    ({"type": "sante_periode", "jours": True}, "période non prise en charge"),
    ({"type": "sante_seances", "jours": 30, "sport": "course!"}, "sport inconnu"),
    ({"type": "sante_seance", "seance_id": 12}, "séance inconnue"),
    ({"type": "sante_jour", "date": "2031-02-30"}, "date invalide"),
    ({"type": "sante_jour", "date": "15/03/2031"}, "date invalide"),
])
def test_demande_invalide_sans_lecture(msg, attendu):
    h, vu = historique(httpx.Response(200, content=contenu()))
    with pytest.raises(SA.ErreurSante, match=attendu):
        asyncio.run(h.repondre(msg))
    assert vu == []


@pytest.mark.parametrize("msg,attendu", [
    ({"type": "sante_seance", "seance_id": "absente"}, "séance inconnue"),
    ({"type": "sante_jour", "date": "2031-03-16"}, "date hors de l'historique"),
    ({"type": "sante_jour", "date": "2020-01-01"}, "date hors de l'historique"),
    ({"type": "sante_seances", "sport": "curling"}, "sport inconnu"),
])
def test_demande_hors_index(msg, attendu, jour_fixe):
    h, _ = historique(httpx.Response(200, content=contenu()))
    with pytest.raises(SA.ErreurSante, match=attendu):
        asyncio.run(h.repondre(msg))


def test_reponses_avec_meta(jour_fixe):
    h, _ = historique(httpx.Response(200, content=contenu()))
    for msg in ({"type": "sante_periode", "jours": 30}, {"type": "sante_seances"}, {"type": "sante_records"},
                {"type": "sante_jour", "date": "2031-03-14"}, {"type": "sante_seance", "seance_id": "h1"}):
        sortie = asyncio.run(h.repondre(msg))
        assert {"aujourdhui", "premier_jour", "genere_le", "lu_a", "perime"} <= set(sortie)
        assert sortie["aujourdhui"] == "2031-03-15" and sortie["perime"] is False
        json.dumps(sortie)


# ------------------------------------------------------------ messages du serveur
class FauxWs:
    def __init__(self):
        self.envois = []

    async def send(self, texte):
        self.envois.append(json.loads(texte))


def satellite(hist, identite="sacha", chiffre=True, permises=("sacha",), relais=None):
    import serveur_satellite as S
    m = object.__new__(S.Moteur)  # sans charger les modèles
    m.sante, m.sante_hist, m.sante_personnes = relais, hist, frozenset(permises)
    sat = object.__new__(S.Satellite)  # sans charger le mot de réveil
    sat.ws, sat.moteur, sat.nom = FauxWs(), m, "essai"
    sat.identite, sat.chiffre = identite, chiffre
    return sat


def test_messages_servis_sans_valeur_au_journal(capsys, jour_fixe):
    h, _ = historique(httpx.Response(200, content=contenu()))
    sat = satellite(h)
    messages = [{"type": "sante_periode", "id": 1, "jours": 7}, {"type": "sante_seances", "id": 2, "jours": 30},
                {"type": "sante_seance", "id": 3, "seance_id": "h1"}, {"type": "sante_records", "id": 4},
                {"type": "sante_jour", "id": 5, "date": "2031-03-14"}]

    async def deroule():
        for msg in messages:
            await sat.repondre_sante_hist(msg)
    asyncio.run(deroule())
    assert [(e["etat"], e["id"], "donnees" in e) for e in sat.ws.envois] == [
        ("sante_periode", 1, True), ("sante_seances", 2, True), ("sante_seance", 3, True),
        ("sante_records", 4, True), ("sante_jour", 5, True)]
    journal = capsys.readouterr().out
    for ligne in ("santé : période servie", "santé : séances servies", "santé : séance servie",
                  "santé : records servis", "santé : jour servi"):
        assert ligne in journal
    for valeur in ("777", "8000", "2031", "h1", "140"):
        assert valeur not in journal


@pytest.mark.parametrize("identite,chiffre,attendu", [
    ("camille", True, "santé non permise pour cet appareil"),
    ("appareil:ab12cd34", True, "santé non permise pour cet appareil"),
    (None, True, "santé non permise pour cet appareil"),
    ("sacha", False, "santé réservée à la liaison chiffrée (wss)"),
])
def test_acces_refuse_sans_appel_reseau(identite, chiffre, attendu, capsys):
    h, vu = historique(httpx.Response(200, content=contenu()))
    sat = satellite(h, identite=identite, chiffre=chiffre)

    async def deroule():
        await sat.recevoir_texte(json.dumps({"type": "sante_periode", "id": 9, "jours": 7}))
        for _ in range(5):
            await asyncio.sleep(0)
        await sat.repondre_sante_hist({"type": "sante_seance", "id": 10, "seance_id": "h1"})
    asyncio.run(deroule())
    assert vu == [] and h._donnees is None
    assert sat.ws.envois == [{"etat": "sante_periode", "id": 9, "erreur": attendu},
                             {"etat": "sante_seance", "id": 10, "erreur": attendu}]


def test_historique_non_configure():
    sat = satellite(None)
    asyncio.run(sat.repondre_sante_hist({"type": "sante_records", "id": 1}))
    assert sat.ws.envois == [{"etat": "sante_records", "id": 1, "erreur": "santé non configurée sur ce serveur"}]


def test_erreur_de_lecture_relayee(capsys):
    h, _ = historique(httpx.Response(503, text="valeur 98"))
    sat = satellite(h)
    asyncio.run(sat.repondre_sante_hist({"type": "sante_records", "id": 2}))
    assert sat.ws.envois == [{"etat": "sante_records", "id": 2, "erreur": "le tableau de bord a répondu 503"}]
    assert "98" not in capsys.readouterr().out


def test_capacite_par_connexion():
    import serveur_satellite as S

    class FauxAssistant:
        ha = None
    h, _ = historique(httpx.Response(200, content=contenu()))
    sat = satellite(h)
    m = sat.moteur
    m.profil, m.assistant, m.empreinte_tls, m.vision = "ha", FauxAssistant(), "", None
    assert m.capacites()["sante_historique"] is False
    assert m.capacites(sat)["sante_historique"] is True
    sat.chiffre = False
    assert m.capacites(sat)["sante_historique"] is False
    sat.chiffre, sat.identite = True, "camille"
    assert m.capacites(sat)["sante_historique"] is False
    m.sante_hist = None
    sat.identite = "sacha"
    assert m.capacites(sat)["sante_historique"] is False
    assert S.SH.TYPES == {"sante_periode", "sante_seances", "sante_seance", "sante_records", "sante_jour"}


class FauxRelais:
    async def resume(self):
        return {"jours": []}


def test_prechauffage_apres_un_sante_reussi(jour_fixe):
    h, vu = historique(httpx.Response(200, content=contenu()))
    sat = satellite(h, relais=FauxRelais())

    async def deroule():
        await sat.repondre_sante({"id": 1})
        await asyncio.sleep(0.3)  # la lecture tourne en tâche de fond
        assert h._donnees is not None and len(vu) == 1
        await sat.repondre_sante({"id": 2})  # cache plein : pas de nouvelle lecture
        await asyncio.sleep(0.05)
    asyncio.run(deroule())
    assert len(vu) == 1
    refuse = satellite(historique(httpx.Response(200, content=contenu()))[0], relais=FauxRelais(), identite="camille")
    asyncio.run(refuse.repondre_sante({"id": 3}))
    assert refuse.moteur.sante_hist._en_vol is None and refuse.moteur.sante_hist._donnees is None


def test_configuration(monkeypatch):
    for v in ("SANTE_JETON", "SANTE_URL"):
        monkeypatch.delenv(v, raising=False)
    assert SH.depuis_env("pc") is None
    monkeypatch.setenv("SANTE_JETON", "jeton-invente-de-test")
    h = SH.depuis_env("pc")
    assert h.url == SH.URL_DONNEES and h.url.startswith("https://") and ".ts.net/" in h.url
    assert h.url_sante == SA.URL_DEFAUT and h.profil == "pc"
    assert SH.depuis_env("ha").profil == "ha"  # 0.53.0 : possible en profil ha avec un jeton
    assert SH.depuis_env("autre") is None
    monkeypatch.delenv("SANTE_JETON")
    assert SH.depuis_env("ha") is None  # sans jeton, pas d'historique en profil ha


# ------------------------------------------------------------ corrections de revue (0.20.1)
def test_sommeil_estime_sans_stades():
    d = donnees({"2031-03-13": jour(sleepH=10.0),                  # 600 min au lit, sans stades
                 "2031-03-14": jour(sleepStages=stades(450)),
                 "2031-03-15": jour(sleepH=None)})
    s = SH.periode(d, 7, AUJOURDHUI)["serie"]
    assert s["sommeil_estime"][-3:] == [True, False, None] and s["sommeil_minutes"][-3:] == [600, 450, None]
    assert SH.vue_jour(d, Date(2031, 3, 13), AUJOURDHUI)["sommeil_estime"] is True
    assert SH.vue_jour(d, Date(2031, 3, 14), AUJOURDHUI)["sommeil_estime"] is False
    assert SH.periode(d, 7, AUJOURDHUI)["bilan"]["jours_sommeil_estime"] == 1
    c = SH.courbes_semaine(d, SH.dates_periode(AUJOURDHUI, 7), AUJOURDHUI)
    assert c["dates"] == ["2031-03-03", "2031-03-10"] and c["jours_sommeil_estime"] == [None, 1]
    r = SH.records(d, AUJOURDHUI, 10000, 420)["records"]
    assert r["nuit_la_plus_longue"]["date"] == "2031-03-14"  # les 600 min estimées ne comptent pas
    assert r["serie_nuits"] == {"valeur": 1, "unite": "nuits", "du": "2031-03-14", "au": "2031-03-14",
                                "battu_le": "2031-03-14"}
    r = SH.records(donnees({"2031-03-14": jour(sleepH=11.0)}), AUJOURDHUI, 10000, 420)["records"]
    assert r["nuit_la_plus_longue"] is None and r["serie_nuits"] is None and r["sommeil_profond_le_plus_long"] is None


def test_stades_qui_se_recouvrent():
    nuit = {"start": "2031-03-13T22:00:00Z", "dureeMin": 300, "seq": [[0, 200, 4], [100, 200, 5]]}
    j = donnees({"2031-03-14": jour(sleepStages=nuit)}).jours[Date(2031, 3, 14)]
    assert (j.sommeil, j.au_lit, j.profond, j.sommeil_estime) == (300, 300, 200, False)  # 400 min de stades


def test_premier_jour_sans_les_pesees():
    d = donnees({"2031-03-01": pesee(), "2031-03-05": jour()})  # range.first vaut le 01/03
    assert d.premier == Date(2031, 3, 5) and Date(2031, 3, 1) in d.jours


def test_libelles_accentues_et_seances_de_forme_inattendue():
    def a(heure, minutes=20):
        return f"2031-03-14T{heure:02d}:00:00Z", f"2031-03-14T{heure:02d}:{minutes:02d}:00Z"
    days = {"2031-03-14": jour(sessions=[
        seance("p1", *a(6), "plongee"), seance("e1", *a(7), "etirements"),
        seance("g1", *a(8), "gymnastique_suedoise"), seance("f1", *a(9), "football_americain"),
        seance("r1", *a(10), "respiration_guidee"), seance("x1", *a(11), "type_99"),
        {"t": ["liste"], "min": 30, "detail": {"id": "bizarre", "zones": "z1", "fcCourbe": {"a": 1}}},
        {"t": {"x": 1}, "detail": ["pas", "un", "objet"]}])}
    d = donnees(days)
    noms = {s.id: s.nom for s in d.seances.values()}
    assert {k: noms[k] for k in ("p1", "e1", "g1", "f1", "r1", "x1", "bizarre")} == {
        "p1": "Plongée", "e1": "Étirements", "g1": "Gymnastique suédoise", "f1": "Football américain",
        "r1": "Respiration guidée", "x1": "Type 99", "bizarre": "Autre"}
    assert len(d.jours[Date(2031, 3, 14)].seances) == 8


def test_une_seance_ou_un_jour_illisible_ne_rejette_pas_le_fichier(monkeypatch):
    original_seance, original_jour = SH.seance_compacte, SH.jour_compact

    def seance_piegee(date, s, rang):
        if rang == 0:
            raise TypeError("forme imprévue")
        return original_seance(date, s, rang)

    def jour_piege(j, seances):
        if j.get("steps") == 1234:
            raise TypeError("forme imprévue")
        return original_jour(j, seances)
    monkeypatch.setattr(SH, "seance_compacte", seance_piegee)
    monkeypatch.setattr(SH, "jour_compact", jour_piege)
    d = donnees({"2031-03-13": jour(steps=1234),
                 "2031-03-14": jour(sessions=[seance("a", "2031-03-14T08:00:00Z", "2031-03-14T09:00:00Z"),
                                              seance("b", "2031-03-14T18:00:00Z", "2031-03-14T19:00:00Z")])})
    assert list(d.jours) == [Date(2031, 3, 14)] and d.jours[Date(2031, 3, 14)].seances == ("b",)


def test_pic_de_fc_controle_sur_la_courbe_recue():
    brute = [[i / 2, 150] for i in range(240)]
    brute[1] = [0.5, 190]  # point que la réduction à 120 points écarte
    d = donnees({"2031-03-14": jour(sessions=[seance("h1", "2031-03-14T18:00:00Z", "2031-03-14T20:00:00Z",
                                                     minutes=120, fcMax=200, fcCourbe=brute)])})
    s = d.seances["h1"]
    assert len(s.courbe) == 120 and max(p[1] for p in s.courbe) == 150 and s.fc_sommet == 190
    assert SH.records(d, AUJOURDHUI, 10000, 420)["records"]["fc_la_plus_haute"]["valeur"] == 200


def transport_analyse(analyse):
    """data-auto.js avec une séance le 13/03, et analyse(requete) pour /api/commentaire."""
    corps = fichier({"2031-03-13": jour(sessions=[seance("seule", "2031-03-13T18:00:00Z", "2031-03-13T19:00:00Z")])})

    def reponse(requete):
        return analyse(requete) if requete.url.path == "/api/commentaire" else httpx.Response(200, content=corps)
    return reponse


def test_analyse_indisponible_au_journal_sans_date_ni_texte(capsys, jour_fixe):
    h, _ = historique(transport_analyse(lambda r: httpx.Response(500, text="Analyse inventée du 13")))
    assert detail(h, "seule")["analyse"] is None
    journal = capsys.readouterr().out
    assert "santé : analyse indisponible (HTTP 500)" in journal
    assert "2031" not in journal and "inventée" not in journal

    def refus(requete):
        raise httpx.ConnectError("refusée", request=requete)
    h, _ = historique(transport_analyse(refus))
    assert detail(h, "seule")["analyse"] is None
    assert "santé : analyse indisponible (ConnectError)" in capsys.readouterr().out
    h, _ = historique(transport_analyse(lambda r: httpx.Response(200, json={})), adresses=("8.8.4.4",))
    h._donnees, h._t = donnees({"2031-03-13": jour(sessions=[
        seance("seule", "2031-03-13T18:00:00Z", "2031-03-13T19:00:00Z")])}), h._horloge()
    assert detail(h, "seule")["analyse"] is None
    assert "santé : analyse indisponible (hors Tailscale)" in capsys.readouterr().out


def test_analyse_delai_total(monkeypatch):
    import time
    monkeypatch.setattr(SH, "COMM_DELAI", 0.05)

    def lent():
        yield b'{"texte": '
        time.sleep(0.1)
        yield b'"x"}'
    h, vu = historique(lambda r: httpx.Response(200, content=lent()))
    with pytest.raises(SH.AnalyseIndisponible) as e:
        h.lire_commentaire(Date(2031, 3, 13))
    assert e.value.raison == "délai dépassé"
    assert vu[0].headers["accept-encoding"] == "identity"


class FauxWsFlux:
    def __init__(self, messages):
        self.messages, self.envois = list(messages), []

    async def send(self, texte):
        self.envois.append(texte)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)


class FauxReveilHa:
    ferme = False

    async def fermer(self):
        self.ferme = True


class FauxMoteurConnexion:
    def __init__(self):
        self.satellites = set()

    def etat_cerveau(self):
        return {"etat": "cerveau"}

    def etat_mode(self):
        return {"etat": "mode"}

    def etat_stt(self):
        return {"etat": "stt"}

    def capacites(self, sat=None):
        return {"etat": "capacites"}


def connexion(messages):
    import serveur_satellite as S
    m = FauxMoteurConnexion()
    sat = object.__new__(S.Satellite)  # sans charger le mot de réveil
    sat.ws, sat.moteur, sat.nom, sat.reveil_ha = FauxWsFlux(messages), m, "essai", FauxReveilHa()
    sat.identite, sat.chiffre, sat.etat = "sacha", True, "repos"
    m.satellites.add(sat)
    return S, sat, m


def test_messages_mal_formes_ignores_et_satellite_retire(capsys):
    S, sat, m = connexion(['{"type": []}', '[]', '"x"', '3', '{"type": {}}', '{"type": ["sante_periode"]}',
                           "[" * 100_000, "pas du json"])
    asyncio.run(S.suivre_satellite(sat, sat.ws, m, "essai"))
    assert sat not in m.satellites and sat.reveil_ha.ferme
    assert len(sat.ws.envois) == 5  # les messages d'accueil, rien pour les messages mal formés
    journal = capsys.readouterr().out
    assert "erreur inattendue" not in journal and "[essai] satellite déconnecté" in journal


def test_erreur_inattendue_retire_le_satellite(capsys):
    S, sat, m = connexion(['{"type": "lecture_finie"}'])

    async def boum(texte):
        raise ValueError("valeur 98 bpm")
    sat.recevoir_texte = boum
    asyncio.run(S.suivre_satellite(sat, sat.ws, m, "essai"))
    assert sat not in m.satellites and sat.reveil_ha.ferme
    journal = capsys.readouterr().out
    assert "connexion coupée sur une erreur inattendue (ValueError)" in journal and "98" not in journal


# ------------------------------------------------------------ ajouts pour l'appli 0.22 (0.20.2)
def historique_plein(d):
    """Historique dont le cache est déjà rempli : aucune lecture réseau."""
    h, vu = historique(httpx.Response(500))
    h._donnees, h._t = d, h._horloge()
    return h, vu


def test_periode_calee_sur_une_date_passee(jour_fixe):
    days = {iso(x): jour(steps=1000 * x.day) for x in plage(Date(2031, 2, 1), AUJOURDHUI)}
    h, vu = historique_plein(donnees(days))
    p = asyncio.run(h.repondre({"type": "sante_periode", "id": 1, "jours": 7, "au": "2031-03-08"}))
    assert (p["du"], p["au"], p["aujourdhui"]) == ("2031-03-02", "2031-03-08", "2031-03-15")
    assert p["serie"]["dates"][-1] == "2031-03-08" and not any(p["serie"]["en_cours"])
    assert not any(g["en_cours"] for g in p["sport"]["groupes"])
    b, a = p["bilan"], p["avant"]
    assert (b["jours"], b["jours_disponibles"], b["couverture"], b["pas"]) == (7, 7, 7, 5000)  # 2 à 8 mars
    assert (a["du"], a["au"], a["couverture"]) == ("2031-02-23", "2031-03-01", 7)  # la semaine qui précède
    du_jour = asyncio.run(h.repondre({"type": "sante_periode", "id": 2, "jours": 7, "au": "2031-03-15"}))
    assert du_jour["serie"]["en_cours"][-1] is True and du_jour["bilan"]["jours"] == 6
    sans_au = asyncio.run(h.repondre({"type": "sante_periode", "id": 3, "jours": 7, "au": None}))
    assert sans_au["au"] == "2031-03-15"
    for au in ("2031-03-16", "2031-01-31"):  # après aujourd'hui, avant le premier jour
        with pytest.raises(SA.ErreurSante, match="date hors de l'historique"):
            asyncio.run(h.repondre({"type": "sante_periode", "id": 4, "jours": 7, "au": au}))
    assert vu == []


@pytest.mark.parametrize("genre", ["sante_periode", "sante_seances"])
@pytest.mark.parametrize("au", ["2031-02-30", "08/03/2031", 20310308, ["2031-03-08"]])
def test_au_invalide_sans_lecture(genre, au):
    h, vu = historique(httpx.Response(200, content=contenu()))
    with pytest.raises(SA.ErreurSante, match="date invalide"):
        asyncio.run(h.repondre({"type": genre, "id": 1, "au": au}))
    assert vu == []


def test_seances_d_une_fenetre_passee_avec_charge(jour_fixe):
    days = {}
    for x in plage(Date(2031, 2, 1), AUJOURDHUI):
        sessions = [seance(f"h-{iso(x)}-{i}", f"{iso(x)}T{8 + 2 * i:02d}:00:00Z", f"{iso(x)}T{9 + 2 * i:02d}:00:00Z",
                           trimp=10) for i in range(5)]  # 5 séances par jour : 225 en tout
        days[iso(x)] = jour(sessions=sessions)
    days["2031-03-03"]["sessions"] += [
        seance("ski-1", "2031-03-03T19:00:00Z", "2031-03-03T22:00:00Z", "ski", minutes=180, trimp=300),
        sans_fc(seance("c-1", "2031-03-03T23:00:00Z", "2031-03-03T23:30:00Z", "course", minutes=30, km=5.0))]
    h, _ = historique_plein(donnees(days))
    recent = asyncio.run(h.repondre({"type": "sante_seances", "id": 1, "jours": 30}))
    assert recent["tronque"] is True and len(recent["seances"]) == 100
    l = asyncio.run(h.repondre({"type": "sante_seances", "id": 2, "jours": 7, "au": "2031-03-05"}))
    assert (l["du"], l["au"], l["tronque"]) == ("2031-02-27", "2031-03-05", False)
    assert len(l["seances"]) == 37 and l["seances"][0]["date"] == "2031-03-05"
    assert l["par_sport"]["course"] == {"nom": "course", "seances": 35, "minutes": 2100,
                                               "distance_m": 0, "trimp": 350, "sans_fc": 0}
    assert l["par_sport"]["ski"]["trimp"] is None                  # hors charge
    assert l["par_sport"]["course"]["trimp"] is None and l["par_sport"]["course"]["sans_fc"] == 1
    assert l["total"] == {"seances": 37, "minutes": 2310, "distance_m": 5000, "trimp": 350, "sans_fc": 1}
    vide = asyncio.run(h.repondre({"type": "sante_seances", "id": 3, "jours": 7, "au": "2031-03-05",
                                   "sport": "velo"}))
    assert vide["total"] == {"seances": 0, "minutes": 0, "distance_m": 0, "trimp": None, "sans_fc": 0}
    with pytest.raises(SA.ErreurSante, match="date hors de l'historique"):
        asyncio.run(h.repondre({"type": "sante_seances", "id": 4, "au": "2031-03-16"}))


def test_zone_1_part_de_zero_comme_agregats():
    bornes = SH.bornes_zones(193)
    assert bornes["z1"]["min_bpm"] == 0 and bornes["z1"]["max_bpm"] == bornes["z2"]["min_bpm"] - 1
    assert bornes["z5"]["max_bpm"] is None
    for bas, haut in zip(SH.CLES_ZONES, SH.CLES_ZONES[1:]):
        assert bornes[bas]["max_bpm"] + 1 == bornes[haut]["min_bpm"]  # zones contiguës, sans trou
