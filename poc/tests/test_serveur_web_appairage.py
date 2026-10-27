"""Appairage du client web (lot S-W1b) vu depuis le serveur HTTP et WebSocket : requêtes forgées refusées, ticket,
cookie, rôles, révocation, et un parcours complet de bout en bout avec une vraie clé P-256."""
import asyncio
import http.client
import json
import re

import pytest
import websockets
from websockets.datastructures import Headers

import appairage_web as AW
import serveur_web as W
import webauthn as WA
from aide_webauthn import Authentificateur

NOM_SERVE = "assistant.exemple.ts.net"
ORIGINE = f"https://{NOM_SERVE}"


class Horloge:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def horloge():
    return Horloge()


@pytest.fixture
def journal(monkeypatch):
    lignes = []
    monkeypatch.setattr(W, "journaliser", lignes.append)
    return lignes


@pytest.fixture
def service(tmp_path, horloge, journal):
    sessions = W.Sessions(duree_s=1000, plafond_s=5000, horloge=horloge, fichier=tmp_path / "sessions_web.json")
    s = W.ServiceWeb(8767, "9.9.9", "27/10/2026", sessions, hote=NOM_SERVE, nom="Iris")
    s.brancher_appairage(tmp_path / "appareils_web.json", invite_jours=7, horloge=horloge)
    return s


def entetes(jeton=None, websocket=False, **plus):
    h = {"Host": NOM_SERVE}
    if jeton:
        h["Cookie"] = f"{W.NOM_COOKIE}={jeton}"
    if websocket:
        h["Upgrade"] = "websocket"
        h["Origin"] = ORIGINE
    h.update({k.replace("_", "-"): v for k, v in plus.items()})
    return Headers(h)


def appairer_direct(service, role="habitant", nom="Appareil de test", acteur="ha", conn=1):
    """Associe un appareil sans réseau. Renvoie (appareil, authentificateur, jeton de session)."""
    ap = service.appairage
    o = ap.ouvrir(nom, role, acteur)
    rep = ap.tenter_code(conn, o["code"])
    tel = Authentificateur(NOM_SERVE)
    assert ap.creation(conn, tel.creer(WA.deb64u(rep["options"]["challenge"], 100), ORIGINE))["etat"] == "attente"
    appareil = ap.finaliser()
    return appareil, tel, service.sessions.creer(AW.identite_de(appareil["id"]))


def statut_de(rep):
    return int(rep[0])


# Pages, scripts et rôles

def test_page_d_appairage_publique_et_pages_protegees_renvoyees_vers_elle(service, journal):
    pub = service.traiter("127.0.0.1", "/appairage", entetes())
    assert statut_de(pub) == 200 and b"Associer" in pub[2] or b"appairage" in pub[2].lower()
    for chemin in ("/associer", "/reglages"):
        rep = service.traiter("127.0.0.1", chemin, entetes())
        assert statut_de(rep) == 303 and rep[1]["Location"] == "/appairage"
    for chemin in ("/associer.js", "/reglages.js", "/api/etat", "/oublier", "/n-importe-quoi"):
        assert statut_de(service.traiter("127.0.0.1", chemin, entetes())) == 401, chemin


def test_roles_pages_proprietaire_et_habitant(service):
    proprio, _, jeton_p = appairer_direct(service, "administrateur", "Propriétaire")
    habitant, _, jeton_h = appairer_direct(service, "habitant", "Habitant", conn=2)
    assert statut_de(service.traiter("127.0.0.1", "/associer", entetes(jeton_p))) == 200
    assert statut_de(service.traiter("127.0.0.1", "/associer.js", entetes(jeton_p))) == 200
    assert statut_de(service.traiter("127.0.0.1", "/reglages", entetes(jeton_h))) == 200
    assert statut_de(service.traiter("127.0.0.1", "/reglages.js", entetes(jeton_h))) == 200
    rep = service.traiter("127.0.0.1", "/associer", entetes(jeton_h))
    assert statut_de(rep) == 303 and rep[1]["Location"] == "/reglages"
    assert statut_de(service.traiter("127.0.0.1", "/associer.js", entetes(jeton_h))) == 403
    assert proprio["role"] == "administrateur" and habitant["role"] == "habitant"


def test_pages_remplies_sans_modele_residuel(service):
    _, _, jeton = appairer_direct(service, "administrateur")
    page = service.traiter("127.0.0.1", "/reglages", entetes(jeton))[2].decode("utf-8")
    assert "{{" not in page and "9.9.9" in page and "27/10/2026" in page


# Ouverture des WebSocket : Host, Origin, cookie

def test_websocket_appairage_refuse_mauvais_host_origine_et_origine_absente(service, journal):
    ok = service.traiter("127.0.0.1", "/ws/appairage", entetes(websocket=True))
    assert ok is None
    mauvais_host = service.traiter("127.0.0.1", "/ws/appairage", entetes(websocket=True, Host="pirate.example"))
    mauvaise_origine = service.traiter("127.0.0.1", "/ws/appairage", entetes(websocket=True, Origin="https://pirate.example"))
    sans_origine = Headers({"Host": NOM_SERVE, "Upgrade": "websocket"})
    sans = service.traiter("127.0.0.1", "/ws/appairage", sans_origine)
    nulle = service.traiter("127.0.0.1", "/ws/appairage", entetes(websocket=True, Origin="null"))
    assert [statut_de(r) for r in (mauvais_host, mauvaise_origine, sans, nulle)] == [403, 403, 403, 403]
    assert any("origine absente" in ligne for ligne in journal) and any("hôte refusé" in ligne for ligne in journal)


def test_websocket_client_exige_un_cookie_valide(service):
    _, _, jeton = appairer_direct(service, "administrateur")
    assert service.traiter("127.0.0.1", "/ws", entetes(jeton, websocket=True)) is None
    for h in (entetes(websocket=True), entetes("Z" * 43, websocket=True), entetes("court", websocket=True)):
        assert statut_de(service.traiter("127.0.0.1", "/ws", h)) == 401
    assert statut_de(service.traiter("127.0.0.1", "/ws", entetes(jeton, websocket=True, Origin="https://pirate.example"))) == 403
    # Un chemin WebSocket inconnu n'apprend rien : refus identique sans cookie, 404 avec cookie.
    assert statut_de(service.traiter("127.0.0.1", "/ws/autre", entetes(websocket=True))) == 401
    assert statut_de(service.traiter("127.0.0.1", "/ws/autre", entetes(jeton, websocket=True))) == 404


def test_trop_de_navigateurs_en_train_de_saisir_un_code(service, journal):
    for i in range(W.MAX_APPAIRAGES_WS):
        service.connexions[i] = W.Connexion(i, None, "appairage")
    rep = service.traiter("127.0.0.1", "/ws/appairage", entetes(websocket=True))
    assert statut_de(rep) == 503
    assert any("trop de connexions" in ligne for ligne in journal)


# Ticket de fin d'appairage

def ticket_pour(service, role="administrateur", nom="Premier"):
    """Mène un appairage au bout et renvoie le ticket envoyé au nouveau navigateur."""
    recu = []
    ancien = service.evenement

    def espion(cible, message, conn=None):
        if cible == "ouverture" and "ticket" in message:
            recu.append(message["ticket"])
        ancien(cible, message, conn)
    service.appairage.sur_evenement = espion
    ap = service.appairage
    o = ap.ouvrir(nom, role, "ha")
    rep = ap.tenter_code(5, o["code"])
    tel = Authentificateur(NOM_SERVE)
    ap.creation(5, tel.creer(WA.deb64u(rep["options"]["challenge"], 100), ORIGINE))
    ap.finaliser()
    return recu[0]


def test_ticket_contre_cookie_une_seule_fois(service, journal):
    ticket = ticket_pour(service)
    rep = service.traiter("127.0.0.1", "/appairage/fin", entetes(X_Ticket=ticket))
    assert statut_de(rep) == 200
    cookie = rep[1]["Set-Cookie"]
    for attribut in ("__Host-session=", "Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
        assert attribut in cookie
    assert "Domain" not in cookie
    assert json.loads(rep[2]) == {"ok": True, "role": "administrateur", "nom": "Premier"}
    jeton = re.match(r"__Host-session=([^;]+);", cookie).group(1)
    assert statut_de(service.traiter("127.0.0.1", "/api/etat", entetes(jeton))) == 200
    rejoue = service.traiter("127.0.0.1", "/appairage/fin", entetes(X_Ticket=ticket))
    assert statut_de(rejoue) == 401 and "Set-Cookie" not in rejoue[1]
    assert any("ticket refusé" in ligne for ligne in journal)
    assert ticket not in "\n".join(journal) and jeton not in "\n".join(journal)


def test_ticket_expire_inconnu_ou_absent_refuse(service, horloge):
    ticket = ticket_pour(service)
    horloge.t += AW.VALIDITE_TICKET_S + 1
    for h in (entetes(X_Ticket=ticket), entetes(X_Ticket="A" * 43), entetes(X_Ticket=""), entetes(),
              entetes(X_Ticket="x" * 500)):
        rep = service.traiter("127.0.0.1", "/appairage/fin", h)
        assert statut_de(rep) == 401 and "Set-Cookie" not in rep[1]


def test_ticket_refuse_depuis_un_autre_site(service):
    ticket = ticket_pour(service)
    rep = service.traiter("127.0.0.1", "/appairage/fin", entetes(X_Ticket=ticket, Origin="https://pirate.example"))
    assert statut_de(rep) == 403
    rep = service.traiter("127.0.0.1", "/appairage/fin", entetes(X_Ticket=ticket, Host="pirate.example"))
    assert statut_de(rep) == 403
    assert statut_de(service.traiter("127.0.0.1", "/appairage/fin", entetes(X_Ticket=ticket))) == 200


# Cookie, révocation, oubli

def test_cookie_d_un_appareil_retire_est_refuse(service, journal):
    _, _, jeton_p = appairer_direct(service, "administrateur")
    habitant, _, jeton_h = appairer_direct(service, "habitant", conn=2)
    assert statut_de(service.traiter("127.0.0.1", "/api/etat", entetes(jeton_h))) == 200
    service.appairage.revoquer(habitant["id"])
    assert statut_de(service.traiter("127.0.0.1", "/api/etat", entetes(jeton_h))) == 401
    assert statut_de(service.traiter("127.0.0.1", "/api/etat", entetes(jeton_p))) == 200
    assert service.sessions.verifier(jeton_h)[1] == "cookie révoqué"


def test_oublier_exige_la_confirmation_et_efface_tout(service):
    appareil, _, jeton = appairer_direct(service, "administrateur")
    sans = service.traiter("127.0.0.1", "/oublier", entetes(jeton))
    assert statut_de(sans) == 400 and "Set-Cookie" not in sans[1]
    mauvaise = service.traiter("127.0.0.1", "/oublier", entetes(jeton, X_Confirme="non"))
    assert statut_de(mauvaise) == 400
    rep = service.traiter("127.0.0.1", "/oublier", entetes(jeton, X_Confirme="oui"))
    assert statut_de(rep) == 200 and json.loads(rep[2]) == {"ok": True, "dernier": True}
    assert "Max-Age=0" in rep[1]["Set-Cookie"] and "cookies" in rep[1]["Clear-Site-Data"]
    assert statut_de(service.traiter("127.0.0.1", "/api/etat", entetes(jeton))) == 401
    assert service.appairage.appareils.get(appareil["id"]) is None


def test_sessions_et_appareils_survivent_a_un_redemarrage(service, tmp_path, horloge):
    appareil, _, jeton = appairer_direct(service, "administrateur")
    sessions = W.Sessions(duree_s=1000, plafond_s=5000, horloge=horloge, fichier=tmp_path / "sessions_web.json")
    neuf = W.ServiceWeb(8767, "9.9.9", "27/10/2026", sessions, hote=NOM_SERVE, nom="Iris")
    neuf.brancher_appairage(tmp_path / "appareils_web.json", horloge=horloge)
    assert statut_de(neuf.traiter("127.0.0.1", "/api/etat", entetes(jeton))) == 200
    assert neuf.appairage.appareils.get(appareil["id"]) is not None
    brut = (tmp_path / "sessions_web.json").read_text(encoding="utf-8")
    assert jeton not in brut, "seule l'empreinte du jeton est écrite"


def test_une_session_expiree_est_refusee(service, horloge):
    _, _, jeton = appairer_direct(service, "administrateur")
    horloge.t += 1001
    assert statut_de(service.traiter("127.0.0.1", "/api/etat", entetes(jeton))) == 401


# Parcours de bout en bout avec de vrais WebSocket

def origine_locale(port):
    return f"http://127.0.0.1:{port}"


async def lancer(service):
    serveur = await W.demarrer("127.0.0.1", 0, "9.9.9", service=service)
    return serveur, serveur.sockets[0].getsockname()[1]


async def arreter(serveur):
    serveur.close()
    await serveur.wait_closed()


def get(port, chemin, en_tetes=None):
    def requete():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", chemin, headers=en_tetes or {})
        r = c.getresponse()
        corps = r.read()
        c.close()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, corps
    return asyncio.get_running_loop().run_in_executor(None, requete)


async def ouvrir_ws(port, chemin, jeton=None, origine="defaut"):
    en_tetes = {"Cookie": f"{W.NOM_COOKIE}={jeton}"} if jeton else None
    origine = origine_locale(port) if origine == "defaut" else origine
    return await websockets.connect(f"ws://127.0.0.1:{port}{chemin}", origin=origine, additional_headers=en_tetes,
                                    open_timeout=5)


async def envoyer(ws, message):
    await ws.send(json.dumps(message))


async def recevoir(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 5))


async def attendre(ws, genre, evenements=None):
    """Premier message du type demandé. Les événements croisés sont rangés dans la liste donnée."""
    while True:
        m = await recevoir(ws)
        if m.get("type") == genre or m.get("etat") == genre:
            return m
        if evenements is not None:
            evenements.append(m)


async def fermeture(ws):
    """Code de fermeture reçu du serveur."""
    try:
        while True:
            await asyncio.wait_for(ws.recv(), 5)
    except websockets.ConnectionClosed as e:
        return e.rcvd.code if e.rcvd else None


async def nouveau_navigateur(port, code, tel):
    """Le nouveau navigateur : code, création de la clé, attente de la confirmation. Renvoie sa connexion."""
    ws = await ouvrir_ws(port, "/ws/appairage")
    await envoyer(ws, {"type": "code", "code": code})
    rep = await recevoir(ws)
    assert rep["etat"] == "creation" and rep["options"]["rp"]["id"] == NOM_SERVE
    challenge = WA.deb64u(rep["options"]["challenge"], 100)
    await envoyer(ws, {"type": "creation", **tel.creer(challenge, ORIGINE)})
    assert (await recevoir(ws))["etat"] == "attente"
    return ws


async def signer(ws, action, tel, cible=None, **defauts):
    """Défi puis preuve du propriétaire. Renvoie la réponse du serveur à la preuve."""
    demande = {"type": "defi", "action": action}
    if cible:
        demande["cible"] = cible
    await envoyer(ws, demande)
    d = await attendre(ws, "defi")
    challenge = WA.deb64u(d["options"]["challenge"], 100)
    reponse = tel.signer(challenge, ORIGINE, **defauts)
    await envoyer(ws, {"type": "preuve", "reponse": reponse})
    return await recevoir_reponse(ws)


async def recevoir_reponse(ws):
    while True:
        m = await recevoir(ws)
        if m.get("type") != "evenement":
            return m


def jeton_du_cookie(statut_entetes):
    return re.match(r"__Host-session=([^;]+);", statut_entetes["set-cookie"]).group(1)


def test_parcours_complet_premier_proprietaire_puis_habitant_puis_revocation(service, journal):
    recus_ha = []
    service.sur_ha = recus_ha.append

    async def scenario():
        serveur, port = await lancer(service)
        try:
            # Premier propriétaire : code ouvert par Home Assistant, confirmation par Home Assistant.
            o = service.appairage.ouvrir("Téléphone de Camille", "administrateur", "ha")
            tel1 = Authentificateur(NOM_SERVE)
            nav1 = await nouveau_navigateur(port, o["code"], tel1)
            service.appairage.finaliser()
            fait = await recevoir(nav1)
            assert fait["etat"] == "fait" and await fermeture(nav1) == 1000
            statut, tetes, _ = await get(port, "/appairage/fin", {"X-Ticket": fait["ticket"]})
            assert statut == 200
            jeton1 = jeton_du_cookie(tetes)

            # Le propriétaire se connecte avec son cookie.
            proprio = await ouvrir_ws(port, "/ws", jeton1)
            await envoyer(proprio, {"type": "moi"})
            moi = await recevoir(proprio)
            assert moi["type"] == "moi" and moi["proprietaire"] is True and moi["dernier_proprietaire"] is True
            assert moi["serveur"]["version"] == "9.9.9" and moi["appareil"]["nom"] == "Téléphone de Camille"

            # Il ouvre l'association d'un habitant.
            await envoyer(proprio, {"type": "ouvrir", "nom": "Tablette du salon", "role": "habitant"})
            ouv = await attendre(proprio, "ouverture")
            assert len(ouv["code"]) == 6 and ouv["role"] == "habitant" and ouv["qr"] and ouv["qr"].startswith("data:")
            tel2 = Authentificateur(NOM_SERVE)
            evenements = []
            nav2 = await nouveau_navigateur(port, ouv["code"], tel2)
            confirme = await signer(proprio, "confirmer", tel1)
            assert confirme["type"] == "confirme" and confirme["appareil"]["role"] == "habitant"
            fait2 = await recevoir(nav2)
            assert fait2["etat"] == "fait"
            statut, tetes, _ = await get(port, "/appairage/fin", {"X-Ticket": fait2["ticket"]})
            assert statut == 200
            jeton2 = jeton_du_cookie(tetes)
            assert jeton2 != jeton1

            # L'habitant ne peut que se décrire.
            hab = await ouvrir_ws(port, "/ws", jeton2)
            await envoyer(hab, {"type": "moi"})
            moi2 = await recevoir(hab)
            assert moi2["proprietaire"] is False and moi2["appareil"]["role"] == "habitant"
            for interdit in ({"type": "appareils"}, {"type": "ouvrir", "nom": "x", "role": "invite"},
                              {"type": "defi", "action": "confirmer"}, {"type": "annuler"}):
                await envoyer(hab, interdit)
                assert await recevoir(hab) == {"type": "erreur", "cause": "droit"}

            # Le propriétaire voit les deux appareils, dont un connecté.
            await envoyer(proprio, {"type": "appareils"})
            liste = await attendre(proprio, "appareils", evenements)
            par_nom = {a["nom"]: a for a in liste["appareils"]}
            assert set(par_nom) == {"Téléphone de Camille", "Tablette du salon"}
            assert par_nom["Téléphone de Camille"]["courant"] is True and par_nom["Tablette du salon"]["en_ligne"] is True
            assert all("credential" not in a and "cle" not in a for a in liste["appareils"])

            # Révocation de l'habitant : la connexion est coupée et le cookie ne sert plus.
            cible = par_nom["Tablette du salon"]["id"]
            revoque = await signer(proprio, "revoquer", tel1, cible=cible)
            assert revoque == {"type": "revoque", "cible": cible}
            assert await fermeture(hab) == W.FERMETURE_REVOQUE
            statut, _, _ = await get(port, "/api/etat", {"Cookie": f"{W.NOM_COOKIE}={jeton2}"})
            assert statut == 401
            with pytest.raises(websockets.InvalidStatus) as e:
                await ouvrir_ws(port, "/ws", jeton2)
            assert e.value.response.status_code == 401

            await proprio.close()
            return port
        finally:
            await arreter(serveur)

    asyncio.run(scenario())
    texte = "\n".join(journal)
    assert "Zz" not in texte
    assert any(m.get("evenement") == "appairage_fait" for m in recus_ha)
    assert all(not re.search(r"\b\d{6}\b", ligne) for ligne in journal), "le code ne va jamais au journal"


def test_deuxieme_navigateur_pendant_la_fenetre_detruit_l_appairage(service):
    async def scenario():
        serveur, port = await lancer(service)
        try:
            o = service.appairage.ouvrir("Téléphone", "administrateur", "ha")
            premier = await ouvrir_ws(port, "/ws/appairage")
            await envoyer(premier, {"type": "code", "code": o["code"]})
            assert (await recevoir(premier))["etat"] == "creation"
            intrus = await ouvrir_ws(port, "/ws/appairage")
            await envoyer(intrus, {"type": "code", "code": "000000"})
            assert (await recevoir(intrus))["etat"] == "interrompu"
            assert (await recevoir(premier))["etat"] == "interrompu"
            assert await fermeture(premier) == 1000 and await fermeture(intrus) == 1000
            assert service.appairage.etat_ouverture() == {"ouverte": False}
        finally:
            await arreter(serveur)
    asyncio.run(scenario())


def test_trois_mauvais_codes_detruisent_l_ouverture(service):
    async def scenario():
        serveur, port = await lancer(service)
        try:
            o = service.appairage.ouvrir("Téléphone", "administrateur", "ha")
            faux = "000000" if o["code"] != "000000" else "111111"
            ws = await ouvrir_ws(port, "/ws/appairage")
            restants = []
            for _ in range(3):
                await envoyer(ws, {"type": "code", "code": faux})
                restants.append(await recevoir(ws))
            assert [r["etat"] for r in restants] == ["code_refuse", "code_refuse", "interrompu"]
            assert await fermeture(ws) == 1000
            ws2 = await ouvrir_ws(port, "/ws/appairage")
            await envoyer(ws2, {"type": "code", "code": o["code"]})
            assert (await recevoir(ws2))["etat"] == "code_refuse", "le bon code ne marche plus après la destruction"
            await ws2.close()
        finally:
            await arreter(serveur)
    asyncio.run(scenario())


def test_limite_de_codes_refuses_sans_ouverture(service):
    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws/appairage")
            etats = []
            for _ in range(AW.LIMITE_ECHECS[0] + 1):
                await envoyer(ws, {"type": "code", "code": "123456"})
                etats.append((await recevoir(ws))["etat"])
            assert etats[:AW.LIMITE_ECHECS[0]] == ["code_refuse"] * AW.LIMITE_ECHECS[0]
            assert etats[-1] == "limite" and await fermeture(ws) == 1000
        finally:
            await arreter(serveur)
    asyncio.run(scenario())


def test_messages_illisibles_ou_inconnus_ferment_la_connexion(service):
    _, _, jeton = appairer_direct(service, "administrateur")

    async def scenario():
        serveur, port = await lancer(service)
        try:
            for brut in ("pas du json", "[1, 2]", b"\x00\x01", json.dumps({"type": "code", "code": 1}) + "x"):
                ws = await ouvrir_ws(port, "/ws/appairage")
                await ws.send(brut)
                assert await fermeture(ws) in (1000, 1008)
            ws = await ouvrir_ws(port, "/ws/appairage")
            await envoyer(ws, {"type": "inconnu"})
            assert await fermeture(ws) == 1000
            for brut in ("pas du json", b"\x00\x01"):
                ws = await ouvrir_ws(port, "/ws", jeton)
                await ws.send(brut)
                assert await fermeture(ws) == 1008
            ws = await ouvrir_ws(port, "/ws", jeton)
            await envoyer(ws, {"type": "n_importe_quoi"})
            assert await recevoir(ws) == {"type": "erreur", "cause": "action"}
            await ws.close()
        finally:
            await arreter(serveur)
    asyncio.run(scenario())


def test_trop_de_messages_ferment_la_connexion_du_proprietaire(service):
    _, _, jeton = appairer_direct(service, "administrateur")

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", jeton)
            for _ in range(W.LIMITE_MESSAGES[0] + 1):
                await envoyer(ws, {"type": "moi"})
            assert await fermeture(ws) == 1008
        finally:
            await arreter(serveur)
    asyncio.run(scenario())


def test_websocket_refuse_depuis_un_autre_site_ou_sans_cookie(service):
    _, _, jeton = appairer_direct(service, "administrateur")

    async def scenario():
        serveur, port = await lancer(service)
        try:
            for chemin, tok, origine in (("/ws/appairage", None, "https://pirate.example"),
                                         ("/ws/appairage", None, None),
                                         ("/ws", jeton, "https://pirate.example"),
                                         ("/ws", jeton, None),
                                         ("/ws", None, "defaut"),
                                         ("/ws", "A" * 43, "defaut")):
                with pytest.raises(websockets.InvalidStatus) as e:
                    await ouvrir_ws(port, chemin, tok, origine)
                assert e.value.response.status_code in (401, 403), (chemin, tok, origine)
        finally:
            await arreter(serveur)
    asyncio.run(scenario())


def test_signature_forgee_ou_rejouee_refusee_par_le_serveur(service):
    proprio, tel, jeton = appairer_direct(service, "administrateur")
    habitant, _, _ = appairer_direct(service, "habitant", "Cible", conn=2)
    temoin, _, _ = appairer_direct(service, "invite", "Témoin", conn=3)

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", jeton)
            # UV absent : refusé, et la cible reste en place.
            rep = await signer(ws, "revoquer", tel, cible=habitant["id"], drapeaux=WA.DRAPEAU_UP)
            assert rep == {"type": "erreur", "cause": "preuve"}
            # Mauvais rpId : refusé.
            rep = await signer(ws, "revoquer", tel, cible=habitant["id"], rp_id="pirate.example")
            assert rep == {"type": "erreur", "cause": "preuve"}
            # Compteur qui recule : refusé, une fois qu'une vraie signature a fait avancer le compteur.
            rep = await signer(ws, "revoquer", tel, cible=temoin["id"])
            assert rep["type"] == "revoque"
            rep = await signer(ws, "revoquer", tel, cible=habitant["id"], compteur=1)
            assert rep == {"type": "erreur", "cause": "preuve"}
            # Preuve sans défi en cours : refusée.
            await envoyer(ws, {"type": "preuve", "reponse": tel.signer(b"\x00" * 32, ORIGINE)})
            assert await recevoir(ws) == {"type": "erreur", "cause": "defi"}
            assert service.appairage.appareils.get(habitant["id"]) is not None
            # Clé inconnue : un autre authentificateur ne peut pas signer pour le propriétaire.
            autre = Authentificateur(NOM_SERVE)
            rep = await signer(ws, "revoquer", autre, cible=habitant["id"])
            assert rep == {"type": "erreur", "cause": "preuve"}
            # Défi légitime : accepté une fois, puis rejoué sans effet.
            await envoyer(ws, {"type": "defi", "action": "revoquer", "cible": habitant["id"]})
            d = await attendre(ws, "defi")
            reponse = tel.signer(WA.deb64u(d["options"]["challenge"], 100), ORIGINE)
            await envoyer(ws, {"type": "preuve", "reponse": reponse})
            assert (await recevoir_reponse(ws))["type"] == "revoque"
            await envoyer(ws, {"type": "preuve", "reponse": reponse})
            assert await recevoir(ws) == {"type": "erreur", "cause": "defi"}
            # On ne se révoque pas soi-même par ce chemin.
            await envoyer(ws, {"type": "defi", "action": "revoquer", "cible": proprio["id"]})
            assert await recevoir_reponse(ws) == {"type": "erreur", "cause": "cible"}
            await ws.close()
        finally:
            await arreter(serveur)
    asyncio.run(scenario())


def test_defi_expire_refuse(service, horloge):
    _, tel, jeton = appairer_direct(service, "administrateur")
    habitant, _, _ = appairer_direct(service, "habitant", "Cible", conn=2)

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", jeton)
            await envoyer(ws, {"type": "defi", "action": "revoquer", "cible": habitant["id"]})
            d = await attendre(ws, "defi")
            horloge.t += AW.VALIDITE_DEFI_S + 1
            await envoyer(ws, {"type": "preuve", "reponse": tel.signer(WA.deb64u(d["options"]["challenge"], 100), ORIGINE)})
            assert await recevoir(ws) == {"type": "erreur", "cause": "defi"}
            assert service.appairage.appareils.get(habitant["id"]) is not None
            await ws.close()
        finally:
            await arreter(serveur)
    asyncio.run(scenario())


def test_oubli_d_un_navigateur_coupe_sa_connexion(service):
    proprio, _, jeton_p = appairer_direct(service, "administrateur")
    habitant, _, jeton_h = appairer_direct(service, "habitant", "Oublieux", conn=2)

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", jeton_h)
            await envoyer(ws, {"type": "moi"})
            await recevoir(ws)
            statut, tetes, _ = await get(port, "/oublier", {"Cookie": f"{W.NOM_COOKIE}={jeton_h}", "X-Confirme": "oui"})
            assert statut == 200 and "max-age=0" in tetes["set-cookie"].lower()
            assert await fermeture(ws) == W.FERMETURE_REVOQUE
            assert service.appairage.appareils.get(habitant["id"]) is None
            assert service.appairage.appareils.get(proprio["id"]) is not None
        finally:
            await arreter(serveur)
    asyncio.run(scenario())
