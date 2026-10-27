"""Page d'administration de Home Assistant et client web (S-W1b) : amorçage de la première clé, secours, limites."""
import asyncio
import json
import re
from types import SimpleNamespace

import pytest

import administration as adm
import appairage_web as AW
import serveur_web as W
import webauthn as WA
from aide_webauthn import Authentificateur

NOM_SERVE = "assistant.exemple.ts.net"
ORIGINE = f"https://{NOM_SERVE}"


@pytest.fixture
def moteur(tmp_path, monkeypatch):
    lignes = []
    monkeypatch.setattr(W, "journaliser", lignes.append)
    service = W.ServiceWeb(8767, "9.9.9", "27/10/2026", W.Sessions(duree_s=1000, plafond_s=5000), hote=NOM_SERVE,
                           nom="Iris")
    service.brancher_appairage(tmp_path / "appareils_web.json", invite_jours=7)
    vus = []
    service.sur_ha = vus.append
    m = SimpleNamespace(service_web=service, pages_admin=set(), evenements_ha=vus, journal=lignes)
    return m


def gerer(moteur, **msg):
    return asyncio.run(adm.gerer_web(moteur, msg, "Alice"))


def associer_navigateur(moteur, code, conn=1):
    """Le nouveau navigateur saisit le code et crée sa clé. Renvoie l'authentificateur."""
    ap = moteur.service_web.appairage
    rep = ap.tenter_code(conn, code)
    assert rep["etat"] == "creation"
    tel = Authentificateur(NOM_SERVE)
    assert ap.creation(conn, tel.creer(WA.deb64u(rep["options"]["challenge"], 100), ORIGINE))["etat"] == "attente"
    return tel


def test_les_types_web_ne_sont_pas_des_types_de_satellite():
    assert adm.TYPES_WEB.isdisjoint(adm.TYPES_PAGE)


def test_sans_client_web_la_page_le_dit_et_refuse(moteur):
    moteur.service_web = None
    assert adm.vue_web(moteur) == {"etat": "web", "disponible": False}
    r = gerer(moteur, type="web_ouvrir", nom="x", role="administrateur")
    assert r[0]["etat"] == "refuse" and r[-1]["disponible"] is False
    sans_attribut = SimpleNamespace(pages_admin=set())
    assert adm.vue_web(sans_attribut)["disponible"] is False


def test_amorcage_du_premier_proprietaire_par_la_page(moteur):
    vue = adm.vue_web(moteur)
    assert vue["disponible"] and vue["proprietaire"] is False and vue["appareils"] == []
    assert vue["ouverture"] == {"ouverte": False}
    r = gerer(moteur, type="web_ouvrir", nom="Téléphone de Camille", role="administrateur")
    ouv = r[0]
    assert ouv["etat"] == "web_ouverture" and re.fullmatch(r"\d{6}", ouv["code"]) and ouv["duree"] > 0
    assert ouv["qr"].startswith("data:image/svg") and ouv["role"] == "administrateur"
    # La vue renvoyée à toutes les pages ne contient jamais le code, mais une durée restante.
    assert ouv["code"] not in json.dumps(r[-1])
    assert r[-1]["ouverture"]["ouverte"] is True and 0 < r[-1]["ouverture"]["restant"] <= ouv["duree"]
    # Sans navigateur en attente, la confirmation est refusée proprement.
    refus = gerer(moteur, type="web_confirmer")
    assert refus[0]["etat"] == "refuse" and "confirmation" in refus[0]["message"]
    associer_navigateur(moteur, ouv["code"])
    assert any(e.get("evenement") == "appairage_attente" for e in moteur.evenements_ha)
    assert adm.vue_web(moteur)["ouverture"]["etat"] == "attente"
    fait = gerer(moteur, type="web_confirmer")
    assert fait[0] == {"etat": "web_confirme", "nom": "Téléphone de Camille", "role": "administrateur"}
    vue = fait[-1]
    assert vue["proprietaire"] is True and [a["nom"] for a in vue["appareils"]] == ["Téléphone de Camille"]
    assert vue["ouverture"] == {"ouverte": False}
    assert all("credential" not in a and "cle" not in a for a in vue["appareils"])
    assert any(e.get("evenement") == "appairage_fait" for e in moteur.evenements_ha)
    assert all(not re.search(r"\b\d{6}\b", ligne) for ligne in moteur.journal)


def test_la_page_ne_cree_plus_de_proprietaire_quand_il_en_existe_un(moteur):
    o = gerer(moteur, type="web_ouvrir", nom="Premier", role="administrateur")[0]
    associer_navigateur(moteur, o["code"])
    gerer(moteur, type="web_confirmer")
    refus = gerer(moteur, type="web_ouvrir", nom="Second", role="administrateur")
    assert refus[0]["etat"] == "refuse" and "propriétaire" in refus[0]["message"]
    # Un habitant reste possible depuis la page (secours quand le propriétaire n'a plus son téléphone).
    ok = gerer(moteur, type="web_ouvrir", nom="Tablette", role="habitant")
    assert ok[0]["etat"] == "web_ouverture" and ok[0]["role"] == "habitant"


def test_role_et_nom_invalides_refuses(moteur):
    assert gerer(moteur, type="web_ouvrir", nom="x", role="root")[0]["message"].startswith("rôle")
    assert gerer(moteur, type="web_ouvrir", nom="x", role=None)[0]["etat"] == "refuse"
    assert gerer(moteur, type="web_ouvrir", nom=["liste"], role="habitant")[0]["etat"] == "refuse"
    assert gerer(moteur, type="web_ouvrir", nom="a" * 500, role="habitant")[0]["etat"] in ("refuse", "web_ouverture")


def test_annulation_depuis_la_page(moteur):
    gerer(moteur, type="web_ouvrir", nom="Téléphone", role="administrateur")
    r = gerer(moteur, type="web_annuler")
    assert r[-1]["ouverture"] == {"ouverte": False}
    assert gerer(moteur, type="web_annuler")[-1]["ouverture"] == {"ouverte": False}  # sans effet, sans erreur


def test_limite_d_ouvertures(moteur):
    reponses = [gerer(moteur, type="web_ouvrir", nom="t", role="habitant")[0] for _ in range(AW.LIMITE_OUVERTURES[0] + 2)]
    assert reponses[0]["etat"] == "web_ouverture"
    assert reponses[-1]["etat"] == "refuse" and "ouvertures" in reponses[-1]["message"]


def test_revocation_de_secours_depuis_la_page(moteur):
    o = gerer(moteur, type="web_ouvrir", nom="Téléphone", role="administrateur")[0]
    associer_navigateur(moteur, o["code"])
    appareil = gerer(moteur, type="web_confirmer")[-1]["appareils"][0]
    jeton = moteur.service_web.sessions.creer(AW.identite_de(appareil["id"]))
    assert moteur.service_web.sessions.verifier(jeton)[0] is not None
    r = gerer(moteur, type="web_revoquer", id=appareil["id"])
    assert r[-1]["appareils"] == [] and r[-1]["proprietaire"] is False
    assert moteur.service_web.sessions.verifier(jeton)[0] is None, "la session de l'appareil retiré ne sert plus"
    inconnu = gerer(moteur, type="web_revoquer", id="inconnu")
    assert inconnu[0]["etat"] == "refuse" and inconnu[0]["message"] == "appareil inconnu"
    # Après la révocation du dernier propriétaire, la page peut en amorcer un nouveau.
    assert gerer(moteur, type="web_ouvrir", nom="Nouveau", role="administrateur")[0]["etat"] == "web_ouverture"


def test_les_pages_ouvertes_sont_prevenues(moteur):
    recus = []

    class Page:
        async def envoyer(self, **m):
            recus.append(m)
    moteur.pages_admin.add(Page())
    asyncio.run(adm.notifier_web(moteur, {"evenement": "appairage_fait", "nom": "x", "role": "habitant"}))
    assert [m["etat"] for m in recus] == ["web_evenement", "web"]
    assert recus[0]["evenement"] == "appairage_fait"


def test_une_page_cassee_ne_bloque_pas_les_autres(moteur):
    recus = []

    class Cassee:
        async def envoyer(self, **m):
            raise RuntimeError("fermée")

    class Bonne:
        async def envoyer(self, **m):
            recus.append(m)
    moteur.pages_admin.update({Cassee(), Bonne()})
    asyncio.run(adm.notifier_web(moteur))
    assert [m["etat"] for m in recus] == ["web"]


def test_canal_de_la_page_de_bout_en_bout(moteur, tmp_path, monkeypatch):
    """Par le vrai WebSocket de la page : vue initiale, ouverture, confirmation, et message web refusé hors liste."""
    import websockets
    import acces
    import maison
    monkeypatch.setattr(acces, "SUPERVISEUR", "127.0.0.1")
    monkeypatch.setattr(maison, "ADMINISTRATION", {"utilisateurs_ha": ["abc123"]})
    moteur.appareils = acces.Appareils(tmp_path, {})
    moteur.satellites = []

    async def lire(ws, etat):
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if m.get("etat") == etat:
                return m

    async def scenario():
        serveur = await adm.demarrer(moteur, 0, "9.9.9")
        port = serveur.sockets[0].getsockname()[1]
        try:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}/ws", origin=f"http://127.0.0.1:{port}",
                                          additional_headers={"X-Remote-User-Id": "abc123",
                                                              "X-Remote-User-Display-Name": "Alice"})
            vue0 = await lire(ws, "web")
            await ws.send(json.dumps({"type": "web_ouvrir", "nom": "Téléphone", "role": "administrateur"}))
            ouv = await lire(ws, "web_ouverture")
            associer_navigateur(moteur, ouv["code"])
            await ws.send(json.dumps({"type": "web_confirmer"}))
            conf = await lire(ws, "web_confirme")
            vue1 = await lire(ws, "web")
            await ws.send(json.dumps({"type": "web_supprimer_tout"}))
            refus = await lire(ws, "refuse")
            await ws.close()
            return vue0, ouv, conf, vue1, refus
        finally:
            serveur.close()
            await serveur.wait_closed()
    vue0, ouv, conf, vue1, refus = asyncio.run(scenario())
    assert vue0["disponible"] and vue0["proprietaire"] is False
    assert conf["role"] == "administrateur" and vue1["proprietaire"] is True
    assert refus["message"] == "message non permis"
