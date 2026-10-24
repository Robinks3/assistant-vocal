"""Relais des données de santé (0.19.0). Toutes les valeurs ci-dessous sont inventées."""
import asyncio
import json
import time

import httpx
import pytest

import sante as SA

AUJOURDHUI = "2031-03-15"


def jour(date, **champs):
    base = {"date": date, "pas": 1000, "distance_activites_m": 2500, "kcal_totales": 2000, "kcal_actives": 0,
            "sommeil_minutes": 400, "stades_minutes": {"leger": 200, "profond": 100, "paradoxal": 80, "eveille": 20},
            "spo2_min": 90, "spo2_moyenne": 95.5, "fc_repos": None, "fc_min": 50, "fc_max": 150,
            "fc_moyenne": 70.3, "poids_kg": None, "vo2max": None, "vitesse_moyenne_kmh": None,
            "vitesse_max_kmh": None, "seances": []}
    base.update(champs)
    return base


def vide(date, **champs):
    """Jour tel que sante-api le crée pour une mesure hors du résumé (une pesée) : tout à 0 ou null."""
    base = jour(date, pas=0, distance_activites_m=0, kcal_totales=0, kcal_actives=0, sommeil_minutes=0,
                stades_minutes={}, spo2_min=None, spo2_moyenne=None, fc_min=None, fc_max=None,
                fc_moyenne=None, poids_kg=70)
    base.update(champs)
    return base


def seance(debut, **champs):
    base = {"id": "x", "type": "course", "type_code": 1, "debut": debut, "fin": debut, "decalage": "+01:00",
            "minutes": 61.23456, "titre": "Entraînement inventé", "origine": "com.exemple", "methode_saisie": 1,
            "fc_min": 80, "fc_max": 180, "fc_moyenne": 130.25, "fc_echantillons": 4000,
            "fc_courbe": [[i / 2, 100 + i % 50] for i in range(240)],
            "zones_minutes": {"z1": 5.25, "z2": 10, "z3": 20, "z4": 15, "z5": 1}, "trimp": 90,
            "vitesse_moyenne_kmh": 12.5, "vitesse_max_kmh": 25, "distance_m": 3100, "kcal": 500}
    base.update(champs)
    return base


def resume_invente():
    return {"debut": "2031-03-07T10:00:00.000Z", "fin": "2031-03-15T10:00:00.000Z", "jours": [
        jour("2031-03-07", seances=[seance("2031-03-07T18:00:00Z")]),  # 8e jour : hors série
        jour("2031-03-09", pas=4321, distance_activites_m=0, kcal_actives=150),
        vide("2031-03-11"),
        jour("2031-03-12", seances=[seance("2031-03-12T09:00:00Z", titre="matin"),
                                    seance("2031-03-12T19:00:00Z", titre="soir")]),
        jour("2031-03-14", sommeil_minutes=380, stades_minutes={"leger": 190, "profond": 70},
             seances=[seance("2031-03-14T20:00:00Z", titre="veille")]),
        jour("2031-03-15", pas=777, distance_activites_m=1234, sommeil_minutes=432, fc_repos=48,
             stades_minutes={"leger": 210, "profond": 90.4, "paradoxal": 100, "eveille": 32}),
    ]}


# ------------------------------------------------------------ réduction
def test_reduction_valeurs_du_jour():
    d = SA.reduire(resume_invente(), AUJOURDHUI)
    assert set(d) == {"date", "aujourdhui", "nuit", "jours", "seances"}
    assert d["date"] == AUJOURDHUI
    assert [j["date"] for j in d["jours"]] == [f"2031-03-{n:02d}" for n in range(9, 16)]
    assert d["aujourdhui"] == {
        "date": AUJOURDHUI, "renseigne": True, "pas": 777, "distance_m": 1234, "kcal_totales": 2000,
        "kcal_actives": None, "fc_repos": 48, "fc_min": 50, "fc_max": 150, "fc_moyenne": 70.3,
        "spo2_moyenne": 95.5, "spo2_min": 90}
    assert d["jours"][-1]["sommeil_minutes"] == 432
    json.dumps(d)  # sérialisable tel quel


def test_serie_valeurs_et_jours_vides():
    d = SA.reduire(resume_invente(), AUJOURDHUI)
    j09, j10, j11 = d["jours"][0], d["jours"][1], d["jours"][2]
    assert j09 == {"date": "2031-03-09", "renseigne": True, "pas": 4321, "distance_m": 0, "kcal_totales": 2000,
                   "kcal_actives": 150, "fc_repos": None, "fc_min": 50, "fc_max": 150, "fc_moyenne": 70.3,
                   "spo2_moyenne": 95.5, "spo2_min": 90, "sommeil_minutes": 400,
                   "stades": {"leger": 200, "profond": 100, "paradoxal": 80, "eveille": 20}}
    nul = {"pas": None, "distance_m": None, "kcal_totales": None, "kcal_actives": None, "fc_repos": None,
           "fc_min": None, "fc_max": None, "fc_moyenne": None, "spo2_moyenne": None, "spo2_min": None,
           "sommeil_minutes": None, "stades": {}}
    assert j10 == {"date": "2031-03-10", "renseigne": False, **nul}  # absent du résumé
    assert j11 == {"date": "2031-03-11", "renseigne": False, **nul}  # seulement une pesée, tout à 0
    assert SA.jours_renseignes(d) == 4


def test_renseigne_par_famille_de_mesure():
    activite = SA.jour_reduit("2031-03-15", vide("2031-03-15", pas=12))
    assert activite["renseigne"] and activite["pas"] == 12 and activite["distance_m"] == 0
    seance_seule = SA.jour_reduit("2031-03-15", vide("2031-03-15", seances=[seance("2031-03-15T08:00:00Z")]))
    assert seance_seule["renseigne"] and seance_seule["pas"] is None
    sommeil = SA.jour_reduit("2031-03-15", vide("2031-03-15", sommeil_minutes=300))
    assert sommeil["renseigne"] and sommeil["sommeil_minutes"] == 300 and sommeil["pas"] is None
    coeur = SA.jour_reduit("2031-03-15", vide("2031-03-15", fc_repos=55))
    assert coeur["renseigne"] and coeur["fc_repos"] == 55 and coeur["kcal_totales"] is None


def test_nuit_de_ce_matin_ou_d_hier():
    d = SA.reduire(resume_invente(), AUJOURDHUI)
    # Nuit rattachée au jour du réveil par sante-api : la nuit dernière est celle d'aujourd'hui.
    assert d["nuit"] == {"date": AUJOURDHUI, "cette_nuit": True, "minutes": 432,
                         "stades": {"leger": 210, "profond": 90, "paradoxal": 100, "eveille": 32}}
    brut = resume_invente()
    brut["jours"][-1]["sommeil_minutes"] = 0  # avant la synchro du matin
    assert SA.reduire(brut, AUJOURDHUI)["nuit"] == {
        "date": "2031-03-14", "cette_nuit": False, "minutes": 380, "stades": {"leger": 190, "profond": 70}}
    brut["jours"][-2]["sommeil_minutes"] = 0
    assert SA.reduire(brut, AUJOURDHUI)["nuit"] == {"date": None, "cette_nuit": False, "minutes": None,
                                                     "stades": {}}


def test_seances_ordre_et_courbe():
    d = SA.reduire(resume_invente(), AUJOURDHUI)
    assert [s["titre"] for s in d["seances"]] == ["veille", "soir", "matin"]  # 8e jour exclu
    derniere = d["seances"][0]
    assert len(derniere["fc_courbe"]) == 60
    assert derniere["fc_courbe"][0] == [0, 100] and derniere["fc_courbe"][-1] == [119.5, 139]
    assert all(s["fc_courbe"] is None for s in d["seances"][1:])
    assert {k: v for k, v in derniere.items() if k != "fc_courbe"} == {
        "date": "2031-03-14", "debut": "2031-03-14T20:00:00Z", "fin": "2031-03-14T20:00:00Z", "type": "course",
        "titre": "veille", "type_code": 1, "minutes": 61.2, "kcal": 500, "distance_m": 3100, "fc_moyenne": 130.2,
        "fc_max": 180, "fc_min": 80, "trimp": 90, "vitesse_moyenne_kmh": 12.5, "vitesse_max_kmh": 25,
        "zones_minutes": {"z1": 5.2, "z2": 10, "z3": 20, "z4": 15, "z5": 1}}


def test_courbe_de_forme_inattendue():
    assert SA.courbe([[0, 100], {"t": 1, "bpm": 110}]) is None
    assert SA.courbe([[0, 100], [1, "110"]]) is None
    assert SA.courbe([[0, 100, 3]]) is None
    assert SA.courbe({"0": 100}) is None
    assert SA.courbe([]) is None
    assert SA.courbe([[0, 100.4], [1, 101.6]]) == [[0, 100], [1, 102]]
    r = SA.reduire({"jours": [jour(AUJOURDHUI, seances=[seance("2031-03-15T08:00:00Z", fc_courbe="xyz")])]},
                   AUJOURDHUI)
    assert r["seances"][0]["fc_courbe"] is None


def test_stades_et_zones_defensifs():
    assert SA.minutes_par_cle([{"stade": "leger", "minutes": 10}, {"nom": "leger", "minutes": 5}, 3]) == {"leger": 15}
    assert SA.minutes_par_cle({"leger": "10", "profond": True, "Bad Key": 3, "paradoxal": -2, "eveille": 4}) == {"eveille": 4}
    assert SA.minutes_par_cle("leger") == {} and SA.minutes_par_cle(None) == {}
    r = SA.reduire({"jours": [jour(AUJOURDHUI, stades_minutes=[1, 2],
                                   seances=[seance("2031-03-15T08:00:00Z", zones_minutes="z1")])]}, AUJOURDHUI)
    assert r["nuit"]["stades"] == {} and r["seances"][0]["zones_minutes"] is None


def test_entrees_quelconques():
    for brut in (None, {}, {"jours": "x"}, {"jours": [1, None, {"date": 5}, {"date": "pas une date"}]}, []):
        d = SA.reduire(brut, AUJOURDHUI)
        assert len(d["jours"]) == 7 and SA.jours_renseignes(d) == 0
        assert d["nuit"]["minutes"] is None and d["seances"] == []
    d = SA.reduire({"jours": [jour(AUJOURDHUI, pas=True, fc_min=float("nan"), fc_max="150",
                                   distance_activites_m=-5, sommeil_minutes=0, seances="x")]}, AUJOURDHUI)
    a = d["aujourdhui"]
    assert a["pas"] is None and a["fc_min"] is None and a["fc_max"] is None and a["distance_m"] is None
    assert a["renseigne"] is True and a["kcal_totales"] == 2000


# ------------------------------------------------------------ configuration et droits
def test_configuration(monkeypatch):
    for v in ("SANTE_JETON", "SANTE_URL", "SANTE_PERSONNES"):
        monkeypatch.delenv(v, raising=False)
    assert SA.depuis_env("pc") is None
    assert SA.personnes_permises() == {"sacha"}
    monkeypatch.setenv("SANTE_JETON", "jeton-invente-de-test")
    assert SA.depuis_env("ha") is None  # sante-api injoignable depuis Home Assistant
    r = SA.depuis_env("pc")
    assert r is not None and r.url == SA.URL_DEFAUT and ".ts.net" in SA.URL_DEFAUT
    monkeypatch.setenv("SANTE_URL", "http://exemple.test:1234/")
    assert SA.depuis_env("pc").url == "http://exemple.test:1234"
    monkeypatch.setenv("SANTE_PERSONNES", " Sacha , appareil:ab12cd34,")
    assert SA.personnes_permises() == {"sacha", "appareil:ab12cd34"}
    monkeypatch.setenv("SANTE_PERSONNES", "")
    assert SA.personnes_permises() == frozenset()


def test_refus():
    r, permises = object(), frozenset({"sacha"})
    assert SA.refus(None, True, "sacha", permises) == "santé non configurée sur ce serveur"
    assert SA.refus(r, False, "sacha", permises) == "santé réservée à la liaison chiffrée (wss)"
    assert SA.refus(r, True, "camille", permises) == "santé non permise pour cet appareil"
    assert SA.refus(r, True, "appareil:ab12cd34", permises) == "santé non permise pour cet appareil"
    assert SA.refus(r, True, None, permises) == "santé non permise pour cet appareil"
    assert SA.refus(r, True, "sacha", permises) is None


def test_adresse_tailscale():
    assert str(SA.adresse_tailscale("x", lambda h: ["192.0.2.1"])) == "192.0.2.1"
    assert str(SA.adresse_tailscale("x", lambda h: ["fd7a:115c:a1e0::5", "192.0.2.1"])) == "192.0.2.1"
    for adresses in (["192.0.2.1"], ["192.0.2.1", "192.0.2.1"], ["192.0.2.1"], []):
        with pytest.raises(SA.ErreurSante, match="jeton gardé"):
            SA.adresse_tailscale("x", lambda h, a=adresses: a)

    def introuvable(h):
        raise OSError("pas de DNS")
    with pytest.raises(SA.ErreurSante, match="introuvable"):
        SA.adresse_tailscale("x", introuvable)


# ------------------------------------------------------------ appels à sante-api
def relais_simule(reponse, horloge=None, adresses=("192.0.2.1",), source=lambda ip, port: "192.0.2.1"):
    vu = []

    def appel(requete):
        vu.append(requete)
        return reponse(requete) if callable(reponse) else reponse
    kw = {"horloge": horloge} if horloge else {}
    relais = SA.Relais("http://sante.test:8096", "jeton-invente-de-test", transport=httpx.MockTransport(appel),
                       resoudre=lambda h: list(adresses), source=source, **kw)
    return relais, vu


@pytest.fixture
def jour_fixe(monkeypatch):
    monkeypatch.setattr(SA, "date_du_jour", lambda: SA.Date.fromisoformat(AUJOURDHUI))


def test_appel_et_cache(jour_fixe):
    t = [0.0]
    relais, vu = relais_simule(httpx.Response(200, json=resume_invente()), horloge=lambda: t[0])

    async def deroule():
        d1 = await relais.resume()
        d2 = await relais.resume()
        t[0] = SA.DUREE_CACHE + 1
        d3 = await relais.resume()
        return d1, d2, d3
    d1, d2, d3 = asyncio.run(deroule())
    assert len(vu) == 2 and d1 is d2 and d3 is not d1
    requete = vu[0]
    assert requete.headers["Authorization"] == "Bearer jeton-invente-de-test"
    assert requete.headers["Host"] == "sante.test:8096"
    assert requete.url.host == "192.0.2.1"  # l'adresse vérifiée, pas le nom résolu une 2e fois
    assert requete.url.path == "/api/resume" and requete.url.params["jours"] == "8"
    assert d1["nuit"]["minutes"] == 432 and "lu_a" in d1


def test_reglages_du_client(jour_fixe, monkeypatch):
    vus = []

    class Espion(httpx.Client):
        def __init__(self, **kw):
            vus.append(kw)
            super().__init__(**kw)
    monkeypatch.setattr(httpx, "Client", Espion)
    relais, _ = relais_simule(httpx.Response(200, json=resume_invente()))
    asyncio.run(relais.resume())
    kw = vus[0]
    assert kw["trust_env"] is False
    assert kw["timeout"].connect == 4 and kw["timeout"].read == 10


def test_hors_tailscale_aucun_appel():
    relais, vu = relais_simule(httpx.Response(200, json=resume_invente()), adresses=("192.0.2.1",))
    with pytest.raises(SA.ErreurSante, match="ne mène pas dans Tailscale"):
        asyncio.run(relais.resume())
    assert vu == []


def test_une_seule_demande_en_vol(jour_fixe):
    def lent(requete):
        time.sleep(0.3)
        return httpx.Response(200, json=resume_invente())
    relais, vu = relais_simule(lent)

    async def deroule():
        return await asyncio.gather(*(relais.resume() for _ in range(4)))
    resultats = asyncio.run(deroule())
    assert len(vu) == 1 and all(r is resultats[0] for r in resultats)


def test_demande_abandonnee_sans_second_appel(jour_fixe, monkeypatch):
    monkeypatch.setattr(SA, "ATTENTE_MAX", 0.05)

    def lent(requete):
        time.sleep(0.4)
        return httpx.Response(200, json=resume_invente())
    relais, vu = relais_simule(lent)

    async def deroule():
        for _ in range(2):  # la tablette abandonne deux fois pendant que l'appel continue
            with pytest.raises(SA.ErreurSante, match="délai"):
                await relais.resume()
        await asyncio.sleep(0.6)
        return await relais.resume()
    assert asyncio.run(deroule())["aujourdhui"]["pas"] == 777
    assert len(vu) == 1


def test_panne_gardee_30_s(jour_fixe):
    t = [0.0]
    etat = {"code": 500}

    def reponse(requete):
        return httpx.Response(etat["code"], json=resume_invente())
    relais, vu = relais_simule(reponse, horloge=lambda: t[0])

    async def deroule():
        for _ in range(2):
            with pytest.raises(SA.ErreurSante, match="sante-api a répondu 500"):
                await relais.resume()
        assert len(vu) == 1  # la panne est resservie sans nouvel appel
        t[0] = SA.DUREE_ERREUR + 1
        etat["code"] = 200
        return await relais.resume()
    assert asyncio.run(deroule())["aujourdhui"]["pas"] == 777
    assert len(vu) == 2


@pytest.mark.parametrize("reponse,attendu", [
    (httpx.Response(401, text="non"), "jeton refusé par sante-api (401)"),
    (httpx.Response(500, text="Erreur 1234 pas"), "sante-api a répondu 500"),
    (httpx.Response(200, text="pas du json 98 bpm"), "réponse illisible de sante-api"),
    (httpx.Response(200, json={"jours": "x"}), "réponse de sante-api sans liste de jours"),
    (httpx.Response(200, content=b"x" * (SA.TAILLE_MAX + 1)), "réponse de sante-api trop grande (plus de 2 Mo)"),
    (httpx.Response(200, content=(b"x" * 500_000 for _ in range(5))), "réponse de sante-api trop grande (plus de 2 Mo)"),
])
def test_erreurs_sans_donnee(reponse, attendu):
    relais, _ = relais_simule(reponse)
    with pytest.raises(SA.ErreurSante) as e:
        asyncio.run(relais.resume())
    assert str(e.value) == attendu


def test_erreur_reseau(jour_fixe):
    def reponse(requete):
        raise httpx.ReadTimeout("lent", request=requete)
    relais, _ = relais_simule(reponse)
    with pytest.raises(SA.ErreurSante, match="délai de 10 s"):
        asyncio.run(relais.resume())


# ------------------------------------------------------------ message {"type": "sante"} du serveur
class FauxWs:
    def __init__(self):
        self.envois = []

    async def send(self, texte):
        self.envois.append(json.loads(texte))


class FauxRelais:
    def __init__(self, donnees=None, erreur=None):
        self.donnees, self.erreur, self.appels = donnees, erreur, 0

    async def resume(self):
        self.appels += 1
        if self.erreur:
            raise self.erreur
        return self.donnees


def moteur(relais, permises=("sacha",)):
    import serveur_satellite as S
    m = object.__new__(S.Moteur)  # sans charger les modèles
    m.sante, m.sante_personnes = relais, frozenset(permises)
    return m


def satellite(relais, identite="sacha", chiffre=True, permises=("sacha",)):
    import serveur_satellite as S
    sat = object.__new__(S.Satellite)  # sans charger le mot de réveil
    sat.ws, sat.moteur, sat.nom = FauxWs(), moteur(relais, permises), "essai"
    sat.identite, sat.chiffre = identite, chiffre
    return sat


def test_message_sante_servi_sans_valeur_au_journal(capsys):
    donnees = SA.reduire(resume_invente(), AUJOURDHUI)
    sat = satellite(FauxRelais(donnees))

    async def deroule():
        await sat.recevoir_texte(json.dumps({"type": "sante", "id": 7}))
        for _ in range(5):
            await asyncio.sleep(0)
    asyncio.run(deroule())
    assert sat.ws.envois == [{"etat": "sante", "id": 7, "donnees": json.loads(json.dumps(donnees))}]
    journal = capsys.readouterr().out
    assert "santé : résumé servi (4 jours)" in journal
    for valeur in ("777", "432", "4321", "48", "1234"):
        assert valeur not in journal


@pytest.mark.parametrize("identite,chiffre,attendu", [
    ("camille", True, "santé non permise pour cet appareil"),            # jeton fixe de Camille
    ("appareil:ab12cd34", True, "santé non permise pour cet appareil"),  # téléphone appairé
    (None, True, "santé non permise pour cet appareil"),
    ("sacha", False, "santé réservée à la liaison chiffrée (wss)"),      # port en clair 8765
])
def test_message_sante_refuse_sans_appel(identite, chiffre, attendu, capsys):
    relais = FauxRelais(SA.reduire(resume_invente(), AUJOURDHUI))
    sat = satellite(relais, identite=identite, chiffre=chiffre)
    asyncio.run(sat.repondre_sante({"id": 4}))
    assert relais.appels == 0
    assert sat.ws.envois == [{"etat": "sante", "id": 4, "erreur": attendu}]
    assert "777" not in capsys.readouterr().out


def test_message_sante_appareil_appaire_permis():
    relais = FauxRelais(SA.reduire(resume_invente(), AUJOURDHUI))
    sat = satellite(relais, identite="appareil:ab12cd34", permises=("sacha", "appareil:ab12cd34"))
    asyncio.run(sat.repondre_sante({"id": 5}))
    assert relais.appels == 1 and sat.ws.envois[0]["donnees"]["aujourdhui"]["pas"] == 777


def test_message_sante_erreurs(capsys):
    sat = satellite(None)
    asyncio.run(sat.repondre_sante({"id": 1}))
    assert sat.ws.envois[-1] == {"etat": "sante", "id": 1, "erreur": "santé non configurée sur ce serveur"}
    sat = satellite(FauxRelais(erreur=SA.ErreurSante("sante-api a répondu 500")))
    asyncio.run(sat.repondre_sante({"id": 2}))
    assert sat.ws.envois[-1] == {"etat": "sante", "id": 2, "erreur": "sante-api a répondu 500"}
    sat = satellite(FauxRelais(erreur=ValueError("valeur 98 illisible")))
    asyncio.run(sat.repondre_sante({"id": 3}))
    assert sat.ws.envois[-1] == {"etat": "sante", "id": 3, "erreur": "erreur inattendue (ValueError)"}
    assert "98" not in capsys.readouterr().out


def test_capacites_par_connexion():
    import serveur_satellite as S

    class FauxAssistant:
        ha = None
    m = moteur(FauxRelais({}))
    m.profil, m.assistant, m.empreinte_tls, m.vision = "ha", FauxAssistant(), "", None
    assert m.capacites()["previsions"] is False  # Home Assistant non configuré
    m.assistant.ha = object()
    assert m.capacites()["previsions"] is True
    assert m.capacites()["sante"] is False
    sat = object.__new__(S.Satellite)
    sat.identite, sat.chiffre = "sacha", True
    assert m.capacites(sat)["sante"] is True
    sat.chiffre = False
    assert m.capacites(sat)["sante"] is False
    sat.identite, sat.chiffre = "camille", True
    assert m.capacites(sat)["sante"] is False
    m.sante = None
    sat.identite = "sacha"
    assert m.capacites(sat)["sante"] is False


def test_route_hors_tailscale_aucun_appel():
    # Tailscale coupé : le DNS rend encore l'adresse en 100.x, mais la route part de l'interface du réseau local.
    relais, vu = relais_simule(httpx.Response(200, json=resume_invente()), source=lambda ip, port: "192.168.0.20")
    with pytest.raises(SA.ErreurSante, match="ne passe pas par Tailscale"):
        relais.lire()
    assert vu == []


def test_sans_route_aucun_appel():
    def sans_route(ip, port):
        raise OSError("réseau injoignable")
    relais, vu = relais_simule(httpx.Response(200, json=resume_invente()), source=sans_route)
    with pytest.raises(SA.ErreurSante, match="pas de route"):
        relais.lire()
    assert vu == []
