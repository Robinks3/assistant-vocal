"""Administration dans Home Assistant (0.34.0) : barrières d'entrée, liste blanche du canal, invitation, service réel."""
import asyncio
import http.client
import json
import re
from types import SimpleNamespace

import pytest
import websockets

import acces
import administration as adm
import maison


@pytest.fixture
def reglage(monkeypatch, tmp_path):
    """Le service se joint depuis 127.0.0.1 : cette adresse tient lieu de superviseur. Un seul utilisateur admis."""
    monkeypatch.setattr(acces, "SUPERVISEUR", "127.0.0.1")
    monkeypatch.setattr(maison, "ADMINISTRATION", {"utilisateurs_ha": ["abc123"]})
    return SimpleNamespace(appareils=acces.Appareils(tmp_path, {}), satellites=[], pages_admin=set())


ENTETES = {"X-Remote-User-Id": "abc123", "X-Remote-User-Display-Name": "Alice"}


def avec_service(moteur, scenario):
    async def deroule():
        serveur = await adm.demarrer(moteur, 0, "9.9.9")
        port = serveur.sockets[0].getsockname()[1]
        try:
            return await scenario(port)
        finally:
            serveur.close()
            await serveur.wait_closed()
    return asyncio.run(deroule())


def http_get(port, chemin, entetes=None):
    def requete():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", chemin, headers=entetes or {})
        r = c.getresponse()
        corps = r.read()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, corps
    return asyncio.get_running_loop().run_in_executor(None, requete)


def test_barrieres_http(reglage):
    async def scenario(port):
        sans = await http_get(port, "/")
        autre = await http_get(port, "/", {"X-Remote-User-Id": "inconnu"})
        ok = await http_get(port, "/", ENTETES)
        return sans, autre, ok
    sans, autre, ok = avec_service(reglage, scenario)
    assert sans[0] == 403 and autre[0] == 403 and ok[0] == 200
    assert b"administration.utilisateurs_ha" in autre[2] and b"inconnu" in autre[2]
    assert b"inconnu" not in sans[2] and b"utilisateurs_ha" not in sans[2]


def test_adresse_hors_superviseur_refusee(reglage, monkeypatch):
    monkeypatch.setattr(acces, "SUPERVISEUR", "172.30.32.2")

    async def scenario(port):
        return await http_get(port, "/", ENTETES)
    statut, _, corps = avec_service(reglage, scenario)
    assert statut == 403 and b"utilisateurs_ha" not in corps


def test_entetes_de_securite_et_table_fermee(reglage):
    async def scenario(port):
        return {c: await http_get(port, c, ENTETES) for c in
                ("/", "/admin.js", "/admin.css", "/../acces.py", "/poc/acces.py", "/admin/index.html",
                 "/%2e%2e/acces.py", "/inconnu")}
    rep = avec_service(reglage, scenario)
    for chemin in ("/", "/admin.js", "/admin.css"):
        assert rep[chemin][0] == 200
    for chemin in ("/../acces.py", "/poc/acces.py", "/admin/index.html", "/%2e%2e/acces.py", "/inconnu"):
        assert rep[chemin][0] == 404
    for statut, entetes, _ in rep.values():
        assert "default-src 'none'" in entetes["content-security-policy"]
        assert entetes["x-content-type-options"] == "nosniff"
        assert entetes["referrer-policy"] == "no-referrer"
        assert entetes["cache-control"] == "no-store"
    assert rep["/admin.js"][1]["content-type"].startswith("text/javascript")


def test_page_sans_script_ni_style_en_ligne_ni_ressource_externe():
    html = (adm.DOSSIER_PAGE / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "style=" not in html and "<style" not in html
    assert not re.search(r"(src|href)=\"(https?:)?//", html)
    js = (adm.DOSSIER_PAGE / "admin.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "localStorage" not in js and "eval(" not in js
    assert "location.search" not in js and "location.hash" not in js


async def ouvrir_ws(port, entetes=ENTETES, origine=None):
    return await websockets.connect(f"ws://127.0.0.1:{port}/ws", additional_headers=entetes,
                                    origin=origine if origine else f"http://127.0.0.1:{port}")


async def lire(ws, etat):
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), 5))
        if m.get("etat") == etat:
            return m


def test_websocket_origine_et_identite(reglage):
    async def scenario(port):
        resultats = {}
        for nom, entetes, origine in (("sans_origine", ENTETES, ""), ("origine_etrangere", ENTETES, "http://evil.example"),
                                      ("inconnu", {"X-Remote-User-Id": "zzz"}, None)):
            try:
                ws = await websockets.connect(f"ws://127.0.0.1:{port}/ws", additional_headers=entetes,
                                              origin=origine if origine else None)
            except websockets.InvalidStatus as e:
                resultats[nom] = e.response.status_code
                continue
            try:
                await asyncio.wait_for(ws.recv(), 5)
                resultats[nom] = "ouvert"
            except websockets.ConnectionClosed as e:
                resultats[nom] = e.rcvd.code if e.rcvd else None
        ws = await ouvrir_ws(port)
        session = await lire(ws, "session")
        await ws.close()
        return resultats, session
    resultats, session = avec_service(reglage, scenario)
    assert resultats["sans_origine"] == 4003 and resultats["origine_etrangere"] == 4003
    assert resultats["inconnu"] == 403
    assert session["version"] == "9.9.9" and session["utilisateur"] == "Alice" and session["client_web"] is False


def test_liste_blanche_du_canal(reglage):
    async def scenario(port):
        ws = await ouvrir_ws(port)
        await lire(ws, "session")
        sortie = []
        for t in ("commande", "ha_service", "reglage", "texte", "sante", "admin", "x" * 5000):
            await ws.send(json.dumps({"type": t, "id": "1"}))
            sortie.append(await lire(ws, "refuse"))
        await ws.send(json.dumps([1, 2]))
        await ws.send(json.dumps({"type": ["liste"]}))
        sortie.append(await lire(ws, "refuse"))
        await ws.close()
        return sortie
    for r in avec_service(reglage, scenario):
        assert r["message"] == "message non permis"
    assert set(adm.TYPES_PAGE) == {"appareils", "appairer", "refuser_appareil", "revoquer", "changer_role",
                                   "inviter", "annuler_invitation"}


def test_invitation_de_bout_en_bout(reglage, monkeypatch, capsys):
    monkeypatch.setattr(maison, "ADMINISTRATION", {"utilisateurs_ha": ["abc123"], "url_client": "https://client.example/"})

    async def scenario(port):
        ws = await ouvrir_ws(port)
        await lire(ws, "session")
        await ws.send(json.dumps({"type": "inviter", "role": "invite"}))
        inv = await lire(ws, "invitation")
        vue = await lire(ws, "appareils")
        await ws.close()
        return inv, vue
    inv, vue = avec_service(reglage, scenario)
    assert re.fullmatch(r"\d{6}", inv["code"]) and inv["role"] == "invite" and 0 < inv["expire"] <= 120
    assert inv["qr"].startswith("data:image/svg") and inv["client_web"] is True
    assert vue["invitation"]["role"] == "invite" and inv["code"] not in json.dumps(vue)
    assert inv["code"] not in capsys.readouterr().out
    assert reglage.appareils.invitation.verifier(inv["code"])[0] == "invite"


def test_invitation_sans_client_web_pas_de_qr(reglage):
    async def scenario(port):
        ws = await ouvrir_ws(port)
        await lire(ws, "session")
        await ws.send(json.dumps({"type": "inviter"}))
        inv = await lire(ws, "invitation")
        await ws.close()
        return inv
    inv = avec_service(reglage, scenario)
    assert inv["qr"] is None and inv["client_web"] is False and inv["role"] == "habitant"


def test_invitation_administrateur_refusee_et_annulation(reglage):
    async def scenario(port):
        ws = await ouvrir_ws(port)
        await lire(ws, "session")
        await ws.send(json.dumps({"type": "inviter", "role": "administrateur"}))
        refus = await lire(ws, "refuse")
        await ws.send(json.dumps({"type": "inviter", "role": "partage"}))
        await lire(ws, "invitation")
        await ws.send(json.dumps({"type": "annuler_invitation"}))
        await lire(ws, "appareils")
        await ws.close()
        return refus
    refus = avec_service(reglage, scenario)
    assert refus["message"] == "rôle non attribuable"
    assert reglage.appareils.invitation.vue() is None


def test_invitation_regles():
    inv = acces.Invitation()
    code = inv.ouvrir("partage", maintenant=1000)
    assert re.fullmatch(r"\d{6}", code)
    assert inv.verifier("0" * 6 if code != "0" * 6 else "1" * 6, maintenant=1001)[0] is None
    assert inv.verifier(code, maintenant=1002) == ("partage", 0)
    assert inv.verifier(code, maintenant=1003)[0] is None  # usage unique
    code = inv.ouvrir("invite", maintenant=2000)
    assert inv.verifier(code, maintenant=2000 + acces.Invitation.DUREE + 1)[0] is None  # expirée
    code = inv.ouvrir("invite", maintenant=3000)
    faux = "0" * 6 if code != "0" * 6 else "1" * 6
    assert [inv.verifier(faux, maintenant=3001)[1] for _ in range(3)] == [2, 1, 0]
    assert inv.verifier(code, maintenant=3002)[0] is None  # détruite après 3 erreurs
    with pytest.raises(ValueError):
        inv.ouvrir("administrateur")
    ancien = inv.ouvrir("habitant", maintenant=4000)
    nouveau = inv.ouvrir("habitant", maintenant=4001)
    assert ancien == nouveau or inv.verifier(ancien, maintenant=4002)[0] is None
    assert inv.verifier(nouveau, maintenant=4003)[0] == 'habitant' or ancien == nouveau


def test_role_changement_et_revocation_par_identite(reglage):
    app = reglage.appareils
    app.liste.append({"id": "ab12cd34", "nom": "Tablette", "jeton": "x", "cree": "2026-10-25T10:00:00", "dernier": ""})
    fermes = []

    class Ws:
        async def close(self, code=1000, reason=""):
            fermes.append(code)
    cible = SimpleNamespace(identite="appareil:ab12cd34", ws=Ws())
    autre = SimpleNamespace(identite="appareil:zz", ws=Ws())
    reglage.satellites.extend([cible, autre])

    async def deroule():
        r = await adm.gerer_appareils(reglage, {"type": "changer_role", "id": "ab12cd34", "role": "invite"}, "t", page=True)
        assert [a["role"] for a in r[-1]["appareils"]] == ["invite"]
        r = await adm.gerer_appareils(reglage, {"type": "changer_role", "id": "ab12cd34", "role": "administrateur"}, "t", page=True)
        assert r[0]["etat"] == "refuse"
        r = await adm.gerer_appareils(reglage, {"type": "revoquer", "id": "appareil:ab12cd34"}, "t", page=True)
        await asyncio.sleep(0)
        return r
    r = asyncio.run(deroule())
    assert r[-1]["appareils"] == [] and fermes == [4001]


def test_invitation_refusee_hors_page(reglage):
    r = asyncio.run(adm.gerer_appareils(reglage, {"type": "inviter", "role": "invite"}, "satellite", page=False))
    assert r[0]["etat"] == "refuse" and reglage.appareils.invitation.vue() is None


def test_invitation_et_amorcage_independants():
    a, i = acces.Amorcage(), acces.Invitation()
    code_i = i.ouvrir("habitant")
    code_a, _ = a.ouvrir()
    faux = "0" * 8 if code_a != "0" * 8 else "1" * 8
    for _ in range(acces.Amorcage.ESSAIS):
        a.verifier(faux)
    assert a.verifier(code_a)[0] is False
    assert i.verifier(code_i)[0] == "habitant"


def test_entrees_malformees_et_chiffres_non_ascii(reglage):
    assert acces.origine_acceptee({"Origin": "http://[x", "Host": "a"}) is False

    class Double(dict):
        def get(self, cle, defaut=None):
            raise LookupError(cle)
    assert acces.origine_acceptee(Double()) is False
    assert acces.controle_ingress("127.0.0.1", Double())[0] is None
    inv = acces.Invitation()
    inv.ouvrir("habitant")
    assert inv.verifier("\u0661" * 6)[0] is None  # chiffres arabes : refus propre, sans exception


def test_changer_role_ne_retrograde_pas_un_administrateur(reglage):
    reglage.appareils.liste.append({"id": "ad", "nom": "Chef", "jeton": "x", "role": "administrateur"})
    assert reglage.appareils.changer_role("ad", "invite") is None
    assert acces.role_de(reglage.appareils.liste[0]) == "administrateur"
