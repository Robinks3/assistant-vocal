"""Serveur HTTP du client web (lot S-W1a) : Host et Origin, cookie de session, en-têtes, coquille PWA, journal."""
import asyncio
import http.client
import json
import re

import pytest
import websockets

import acces
import serveur_web as W

NOM_SERVE = "assistant.exemple.ts.net"
CAUSES_REFUS = []


@pytest.fixture
def journal(monkeypatch):
    CAUSES_REFUS.clear()
    lignes = []
    monkeypatch.setattr(W, "journaliser", lignes.append)
    return lignes


class Horloge:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def horloge():
    return Horloge()


@pytest.fixture
def sessions(horloge):
    return W.Sessions(duree_s=1000, plafond_s=5000, horloge=horloge)


def avec_serveur(sessions, scenario, hote=NOM_SERVE):
    async def deroule():
        service = W.ServiceWeb(0, "9.9.9", "27/10/2026", sessions, hote=hote, nom="Iris")
        serveur = await W.demarrer("127.0.0.1", 0, "9.9.9", service=service)
        port = serveur.sockets[0].getsockname()[1]
        try:
            return await scenario(port)
        finally:
            serveur.close()
            await serveur.wait_closed()
    return asyncio.run(deroule())


def get(port, chemin, entetes=None):
    def requete():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", chemin, headers=entetes or {})
        r = c.getresponse()
        corps = r.read()
        c.close()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, corps
    return asyncio.get_running_loop().run_in_executor(None, requete)


def cookie(jeton):
    return {"Cookie": f"{W.NOM_COOKIE}={jeton}"}


def verifier_entetes_securite(entetes):
    assert "frame-ancestors 'none'" in entetes["content-security-policy"]
    assert "default-src 'self'" in entetes["content-security-policy"]
    assert "script-src 'self'" in entetes["content-security-policy"]
    assert "'unsafe-inline'" not in entetes["content-security-policy"]
    assert entetes["x-content-type-options"] == "nosniff"
    assert entetes["referrer-policy"] == "no-referrer"
    assert entetes["strict-transport-security"].startswith("max-age=")
    politique = entetes["permissions-policy"]
    assert "microphone=(self)" in politique  # S-W3 : le micro, à la page seule (écran Demander)
    for ferme in ("camera", "geolocation", "accelerometer", "gyroscope", "magnetometer", "payment", "usb"):
        assert f"{ferme}=()" in politique
    assert entetes["cross-origin-opener-policy"] == "same-origin"
    assert entetes["cross-origin-resource-policy"] == "same-origin"
    assert "cache-control" in entetes


# Accueil public et en-têtes

def test_accueil_public_sans_cookie_et_entetes_de_securite(sessions):
    async def scenario(port):
        return await get(port, "/")
    statut, entetes, corps = avec_serveur(sessions, scenario)
    assert statut == 200
    assert entetes["content-type"].startswith("text/html")
    verifier_entetes_securite(entetes)
    page = corps.decode("utf-8")
    assert "Iris" in page and "Serveur 9.9.9" in page and "Client web " in page and "27/10/2026" in page
    assert "{{" not in page


def test_refus_aussi_portent_les_entetes_de_securite(sessions):
    async def scenario(port):
        return (await get(port, "/", {"Host": "pirate.example"}),
                await get(port, "/api/etat"),
                await get(port, "/", {"Origin": "https://pirate.example"}))
    for statut, entetes, corps in avec_serveur(sessions, scenario):
        assert statut in (401, 403)
        verifier_entetes_securite(entetes)
        assert len(corps) < 60  # aucun détail sur la cause


# Host et Origin

@pytest.mark.parametrize("hote", ["pirate.example", "pirate.example:80", "localhost", "127.0.0.1", "[::2]:8767",
                                  "assistant.exemple.ts.net.pirate.example", "127.0.0.1:1", ""])
def test_mauvais_host_refuse(sessions, journal, hote):
    async def scenario(port):
        return await get(port, "/", {"Host": hote})
    statut, _, corps = avec_serveur(sessions, scenario)
    assert statut == 403 and b"hote" not in corps.lower() and hote.encode() not in corps or hote == ""
    assert any("hôte refusé" in ligne for ligne in journal)


def test_host_de_serve_et_de_la_boucle_locale_acceptes(sessions):
    async def scenario(port):
        return (await get(port, "/", {"Host": NOM_SERVE}),
                await get(port, "/", {"Host": f"localhost:{port}"}),
                await get(port, "/", {"Host": NOM_SERVE.upper()}))
    assert [r[0] for r in avec_serveur(sessions, scenario)] == [200, 200, 200]


def test_sans_nom_serve_configure_seule_la_boucle_locale_passe(sessions):
    async def scenario(port):
        return await get(port, "/", {"Host": NOM_SERVE})
    assert avec_serveur(sessions, scenario, hote="")[0] == 403


@pytest.mark.parametrize("origine", ["https://pirate.example", "null", "http://assistant.exemple.ts.net",
                                     "https://assistant.exemple.ts.net:8443", "https://assistant.exemple.ts.net.evil.fr",
                                     "http://127.0.0.1:1", "chrome-extension://abc"])
def test_mauvaise_origin_refusee(sessions, journal, origine):
    async def scenario(port):
        return await get(port, "/", {"Host": NOM_SERVE, "Origin": origine})
    assert avec_serveur(sessions, scenario)[0] == 403
    assert any("origine refusée" in ligne for ligne in journal)


def test_origin_correcte_acceptee(sessions):
    async def scenario(port):
        return (await get(port, "/", {"Host": NOM_SERVE, "Origin": f"https://{NOM_SERVE}"}),
                await get(port, "/", {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}"}))
    assert [r[0] for r in avec_serveur(sessions, scenario)] == [200, 200]


def test_websocket_sans_origin_ou_sans_cookie_refuse(sessions, journal):
    async def scenario(port):
        resultats = []
        for entetes in ({}, {"Origin": f"http://127.0.0.1:{port}"}, {"Origin": "https://pirate.example"}):
            with pytest.raises(websockets.InvalidStatus) as e:
                await websockets.connect(f"ws://127.0.0.1:{port}/ws", additional_headers=entetes, open_timeout=5)
            resultats.append(e.value.response.status_code)
        return resultats
    assert avec_serveur(sessions, scenario) == [403, 401, 403]


# Cookie de session

def test_cookie_absent_forge_expire_et_rejoue(sessions, horloge, journal):
    jeton = sessions.creer("proprietaire")

    async def scenario(port):
        sans = await get(port, "/api/etat")
        forge = await get(port, "/api/etat", cookie("A" * 43))
        illisible = await get(port, "/api/etat", {"Cookie": f"{W.NOM_COOKIE}=a b;c"})
        mauvais_nom = await get(port, "/api/etat", {"Cookie": f"session={jeton}"})
        valide = await get(port, "/api/etat", cookie(jeton))
        sessions.revoquer(jeton)
        rejoue = await get(port, "/api/etat", cookie(jeton))
        neuf = sessions.creer("proprietaire")
        horloge.t += 1001
        expire = await get(port, "/api/etat", cookie(neuf))
        return sans, forge, illisible, mauvais_nom, valide, rejoue, expire
    sans, forge, illisible, mauvais_nom, valide, rejoue, expire = avec_serveur(sessions, scenario)
    for refus in (sans, forge, illisible, mauvais_nom, rejoue, expire):
        assert refus[0] == 401
        assert b"etat" not in refus[2] and b"serveur" not in refus[2].lower()
    assert valide[0] == 200 and json.loads(valide[2]) == {"session": True, "serveur": "9.9.9"}
    causes = " | ".join(journal)
    for cause in ("cookie absent", "cookie inconnu", "cookie illisible", "cookie révoqué", "cookie expiré"):
        assert cause in causes


def test_chemin_inconnu_sans_cookie_est_401_et_avec_cookie_404(sessions):
    jeton = sessions.creer("proprietaire")

    async def scenario(port):
        chemins = ("/inconnu", "/../poc/acces.py", "/%2e%2e/acces.py", "/poc/acces.py", "/web/index.html",
                   "/serveur_web.py", "/polices/../../maison.py", "/api/autre")
        return ({c: await get(port, c) for c in chemins}, {c: await get(port, c, cookie(jeton)) for c in chemins})
    sans, avec = avec_serveur(sessions, scenario)
    assert {r[0] for r in sans.values()} == {401}
    assert {r[0] for r in avec.values()} == {404}


def test_session_glissante_avec_plafond(sessions, horloge):
    jeton = sessions.creer("proprietaire")
    for _ in range(4):
        horloge.t += 900
        assert sessions.verifier(jeton)[0] is not None  # chaque usage prolonge de 1000 s
    horloge.t += 1001
    assert sessions.verifier(jeton) == (None, "cookie expiré")  # sans usage pendant plus de 1000 s


def test_plafond_absolu_de_session(sessions, horloge):
    jeton = sessions.creer("proprietaire")
    for _ in range(5):
        horloge.t += 900
        sessions.verifier(jeton)
    horloge.t += 900
    assert sessions.verifier(jeton) == (None, "cookie expiré")  # 5400 s depuis l'ouverture, plafond de 5000 s


def test_revocation_par_identite_et_purge(sessions, horloge):
    a, b, c = sessions.creer("proprietaire"), sessions.creer("proprietaire"), sessions.creer("sacha")
    assert sessions.revoquer(identite="proprietaire") == 2
    assert sessions.verifier(a) == (None, "cookie révoqué") and sessions.verifier(b)[1] == "cookie révoqué"
    assert sessions.verifier(c)[0]["identite"] == "sacha"
    horloge.t += 100000
    assert sessions.purger() == 3
    assert sessions.verifier(c) == (None, "cookie inconnu")


def test_seule_l_empreinte_est_gardee(sessions):
    jeton = sessions.creer("proprietaire")
    assert len(jeton) >= 43  # 256 bits en base 64 url
    assert jeton not in repr(sessions._sessions) and acces.empreinte(jeton) in sessions._sessions
    assert sessions.creer("proprietaire") != jeton


def test_attributs_du_cookie():
    valeur = W.en_tete_cookie("abc", 3600)
    assert valeur.startswith("__Host-session=abc;")
    for attribut in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/", "Max-Age=3600"):
        assert attribut in valeur
    assert "Domain" not in valeur
    assert "Max-Age=0" in W.en_tete_cookie_efface()


def test_page_d_appairage_publique_avec_les_entetes_de_securite(sessions):
    async def scenario(port):
        return await get(port, "/appairage"), await get(port, "/appairage.js"), await get(port, "/client.js")
    page, script, client = avec_serveur(sessions, scenario)
    assert page[0] == 200 and page[1]["content-type"].startswith("text/html")
    assert b"Iris" in page[2] and b"{{" not in page[2]
    assert script[0] == 200 and client[0] == 200
    for reponse in (page, script, client):
        verifier_entetes_securite(reponse[1])


def test_journal_sans_cookie_ni_jeton(sessions, journal):
    jeton = sessions.creer("proprietaire")
    secret = "Zz9" * 14

    async def scenario(port):
        await get(port, "/api/etat", cookie(secret))
        await get(port, "/api/etat", {"Cookie": f"{W.NOM_COOKIE}={jeton}x; autre=1", "Authorization": "Bearer " + secret})
        await get(port, "/chemin-secret-" + secret, {"Host": "pirate.example"})
        await get(port, "/api/etat", {"Origin": "https://pirate.example", "X-Test": secret})
    avec_serveur(sessions, scenario)
    texte = "\n".join(journal)
    assert journal and secret not in texte and jeton not in texte and "Bearer" not in texte
    assert "chemin-secret" not in texte and "pirate.example" not in texte and "Cookie" not in texte
    assert all(re.fullmatch(r"serveur web : refus depuis 127\.0\.0\.1 \([^)]+\)", ligne) for ligne in journal)


# Coquille PWA

def test_manifeste_et_icones(sessions):
    async def scenario(port):
        manifeste = await get(port, "/manifest.webmanifest")
        icones = {c: await get(port, c) for c in ("/icones/icone-192.png", "/icones/icone-512.png",
                                                  "/icones/icone-masquable-512.png", "/icones/apple-touch-icon.png")}
        return manifeste, icones
    manifeste, icones = avec_serveur(sessions, scenario)
    assert manifeste[0] == 200 and manifeste[1]["content-type"].startswith("application/manifest+json")
    m = json.loads(manifeste[2])
    assert m["name"] == "Iris" and m["start_url"] == "/" and m["display"] == "standalone"
    assert {i["sizes"] for i in m["icons"]} == {"192x192", "512x512"}
    assert any(i["purpose"] == "maskable" for i in m["icons"])
    for i in m["icons"]:
        assert i["src"].startswith("/icones/") and i["type"] == "image/png"
    for chemin, (statut, entetes, corps) in icones.items():
        assert statut == 200 and entetes["content-type"] == "image/png", chemin
        assert corps.startswith(b"\x89PNG\r\n\x1a\n")
        verifier_entetes_securite(entetes)
    for i in m["icons"]:
        taille = int(i["sizes"].split("x")[0])
        png = icones[i["src"]][2]
        assert int.from_bytes(png[16:20], "big") == taille and int.from_bytes(png[20:24], "big") == taille


def test_fichiers_statiques_servis_avec_le_bon_type(sessions):
    async def scenario(port):
        return {c: await get(port, c) for c in W.FICHIERS}
    for chemin, (statut, entetes, corps) in avec_serveur(sessions, scenario).items():
        assert statut == 200 and corps, chemin
        assert entetes["content-type"] == W.FICHIERS[chemin][1]
    assert W.FICHIERS["/app.js"][1].startswith("text/javascript")


PAGES = ("index.html", "appairage.html", "associer.html", "reglages.html")
SCRIPTS = ("app.js", "client.js", "appairage.js", "associer.js", "reglages.js")


def test_page_sans_script_ni_style_en_ligne_ni_ressource_externe():
    for nom in PAGES:
        html = (W.DOSSIER / nom).read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "<style" not in html, nom
        assert not re.search(r"\sstyle=", html) and not re.search(r"\son[a-z]+=", html, re.I), nom
        assert not re.search(r"(src|href|action)=\"(https?:)?//", html), nom
        assert not re.search(r"tabindex=\"[1-9]", html), nom
    css = (W.DOSSIER / "app.css").read_text(encoding="utf-8")
    assert "@import" not in css and not re.search(r"url\(\s*[\"']?(https?:)?//", css)
    for nom in SCRIPTS:
        js = (W.DOSSIER / nom).read_text(encoding="utf-8")
        for interdit in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "localStorage",
                         "sessionStorage", "location.search", "location.hash", "setAttribute('style'",
                         'setAttribute("style"', "new Function"):
            if nom == "appairage.js" and interdit == "location.hash":
                continue  # le QR porte le code dans le fragment (jamais envoyé au serveur), effacé dès la lecture
            if nom == "client.js" and interdit == "localStorage":
                continue  # seul le réglage « mode développeur » (oui/non) y est gardé, voir test_mode_developpeur.py
            assert interdit not in js, (nom, interdit)


def test_aucun_texte_typographique_d_ia_dans_la_coquille():
    for nom in PAGES + SCRIPTS + ("app.css",):
        texte = (W.DOSSIER / nom).read_text(encoding="utf-8")
        interdits = {chr(c) for c in (0x2014, 0x2013, 0x2026, 0xA0, 0x202F, 0x200B, 0xFEFF)}
        assert not interdits & set(texte), nom


def test_hote_serve_lu_dans_la_configuration():
    assert W.hote_serve() == NOM_SERVE
    assert W.duree_session_s() == 30 * 86400
