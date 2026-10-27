"""Écran Routines sur le serveur du client web (S-W6) : pages, six messages par WebSocket, droits par rôle tirés de la
session, schéma strict, signal « routines_maj », rien sur le port 8765, aucun script ni style en ligne."""
import asyncio
import json
import re
from pathlib import Path

import pytest

import appairage_web as AW
import assistant as A
import maison
import routines as R
import routines_web as RW
import serveur_satellite as SS
import serveur_web as W
from test_routines import faux_assistant, faux_serveur, jouer
from test_serveur_web_appairage import (  # noqa: F401  (fixtures réutilisées)
    appairer_direct, arreter, entetes, envoyer, horloge, journal, lancer, ouvrir_ws, recevoir, recevoir_reponse,
    service, statut_de)

RACINE = Path(__file__).resolve().parent.parent
EXEMPLE = RACINE.parent / "config-exemple" / "routines-exemple.json"
ARRIVEE, SOIREE, FILM = "r-20261012-1842-a1", "r-20261014-2105-b2", "r-20261020-2030-c3"


def charger_exemple(*en_plus):
    """Les trois routines fictives de config-exemple/, plus celles données, dans le fichier temporaire du test."""
    donnees = json.loads(EXEMPLE.read_text(encoding="utf-8"))
    donnees["routines"].extend(en_plus)
    R.FICHIER.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
    R.reinitialiser()


def routine_de(auteur, ident="r-20261026-0900-d4", nom="Réveil"):
    return {"id": ident, "nom": nom, "auteur": auteur, "pour": "auteur", "actif": True, "a_revoir": None,
            "declencheurs": [{"genre": "phrase", "phrases": ["bonjour la maison"], "variantes": []}],
            "etapes": [{"etape": "annonce", "texte": "Bonne journée."}], "creee_le": "2026-10-26T09:00:00",
            "derniere_execution": None, "executions": 0}


@pytest.fixture
def moteur(monkeypatch, service):
    """Le moteur réel des routines (Moteur.messages_routines et Moteur.diffuser) sur un assistant factice en essai."""
    monkeypatch.setattr(A, "journaliser", lambda *a, **k: None)
    monkeypatch.setattr(SS, "lire_journal", lambda n=1: [{"horodatage": "x"}])
    historiques = []

    class Moteur:
        profil, essai, appareils, satellites, pages_admin = "tablette", True, None, set(), set()
        messages_routines = SS.Moteur.messages_routines
        diffuser = SS.Moteur.diffuser

        def __init__(self):
            self.assistant, self.verrou, self.service_web = faux_assistant(), asyncio.Lock(), service
            self.historiques = historiques

        @staticmethod
        def noms(entity_id):
            return None

        async def diffuser_historique(self, ligne):
            historiques.append(ligne)

    m = Moteur()
    service.routines = SS.routines_pour_web(m)
    return m


def scenario_ws(service, jeton, corps):
    async def lance():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", jeton)
            try:
                return await corps(ws)
            finally:
                await ws.close()
        finally:
            await arreter(serveur)
    return asyncio.run(lance())


async def echange(ws, msg):
    await envoyer(ws, msg)
    while True:
        m = await recevoir_reponse(ws)
        if m.get("type") != "routines_maj":
            return m


def liste(service, jeton):
    async def corps(ws):
        return await echange(ws, {"type": "routines"})
    return scenario_ws(service, jeton, corps)


def par_id(rep):
    return {r["id"]: r for r in rep["routines"]}


# ------------------------------------------------------------------ pages et script

def test_les_six_messages_sont_dans_la_liste_blanche_et_la_version_du_client_est_0_10_0():
    assert RW.GENRES == {"routines", "routine_lancer", "routine_activer", "routine_supprimer", "routine_texte",
                         "routines_export"}
    assert RW.GENRES <= W.MESSAGES_TOUT_ROLE
    assert W.VERSION_CLIENT == "0.10.0"


def test_la_page_et_le_script_exigent_une_session(service):
    rep = service.traiter("127.0.0.1", "/routines", entetes())
    assert statut_de(rep) == 303 and rep[1]["Location"] == "/appairage"
    assert statut_de(service.traiter("127.0.0.1", "/routines.js", entetes())) == 401


def test_la_page_est_servie_a_chaque_role_avec_les_en_tetes_de_securite(service):
    for conn, role in enumerate(("administrateur", "habitant", "invite"), start=1):
        _, _, jeton = appairer_direct(service, role, f"Appareil {role}", conn=conn)
        page = service.traiter("127.0.0.1", "/routines", entetes(jeton))
        assert statut_de(page) == 200, role
        html = page[2].decode("utf-8")
        assert "{{" not in html and W.VERSION_CLIENT in html and "9.9.9" in html and "Routines" in html, role
        assert "Iris" in html, "le nom de l'assistant vient de la configuration"
        csp = page[1]["Content-Security-Policy"]
        assert "script-src 'self'" in csp and "unsafe-inline" not in csp and "require-trusted-types-for 'script'" in csp
        assert page[1]["Cache-Control"] in ("no-store", "no-cache") and page[1]["X-Content-Type-Options"] == "nosniff"
        script = service.traiter("127.0.0.1", "/routines.js", entetes(jeton))
        assert statut_de(script) == 200 and b"/ws" in script[2], role
        assert "javascript" in script[1]["Content-Type"]


def test_la_page_routines_est_dans_les_tables_protegees_et_liee_depuis_l_accueil():
    assert W.PAGES_PROTEGEES["/routines"][0] == "routines.html"
    assert W.SCRIPTS_PROTEGES["/routines.js"][0] == "routines.js"
    accueil = (RACINE / "web" / "index.html").read_text(encoding="utf-8")
    assert 'href="/routines"' in accueil
    page = (RACINE / "web" / "routines.html").read_text(encoding="utf-8")
    assert "{{onglets:accueil}}" in page, "la barre du bas allume l'onglet Accueil"


# ------------------------------------------------------------------ droits par rôle

def test_l_invite_ne_voit_et_ne_lance_que_les_routines_pour_tous_et_ne_coupe_ni_ne_supprime(service, moteur):
    charger_exemple()
    _, _, jeton = appairer_direct(service, "invite", "Invité")

    async def corps(ws):
        return [await echange(ws, {"type": "routines"}),
                await echange(ws, {"type": "routine_lancer", "id": ARRIVEE}),
                await echange(ws, {"type": "routine_lancer", "id": SOIREE}),
                await echange(ws, {"type": "routine_activer", "id": ARRIVEE, "actif": False}),
                await echange(ws, {"type": "routine_supprimer", "id": ARRIVEE}),
                await echange(ws, {"type": "routines_export"})]
    vue, lancee, reservee, couper, supprimer, export = scenario_ws(service, jeton, corps)
    assert [r["id"] for r in vue["routines"]] == [ARRIVEE]
    assert vue["routines"][0]["droits"] == {"lancer": True, "couper": False, "supprimer": False}
    assert vue["droits"] == {"exporter": False, "tout_gerer": False}
    assert lancee["type"] == "routine_lancee" and lancee["id"] == ARRIVEE and lancee["ok"] is True
    assert reservee == {"type": "routine_lancee", "id": SOIREE, "ok": False, "parole": "Je ne trouve pas cette routine.",
                        "echecs": []}, "une routine invisible vaut une routine inconnue"
    for rep, genre in ((couper, "routine_activer"), (supprimer, "routine_supprimer"), (export, "routines_export")):
        assert rep == {"type": "erreur", "cause": "droit", "genre": genre}
    assert [r["id"] for r in R.registre().routines] == [ARRIVEE, SOIREE, FILM]
    assert R.registre().par_id(ARRIVEE)["actif"] is True


def test_l_habitant_ne_gere_que_ses_routines(service, moteur):
    appareil, _, jeton = appairer_direct(service, "habitant", "Habitant")
    a_lui = routine_de(AW.identite_de(appareil["id"]))
    charger_exemple(a_lui)

    async def corps(ws):
        return [await echange(ws, {"type": "routines"}),
                await echange(ws, {"type": "routine_activer", "id": ARRIVEE, "actif": False}),
                await echange(ws, {"type": "routine_supprimer", "id": SOIREE}),
                await echange(ws, {"type": "routine_activer", "id": a_lui["id"], "actif": False}),
                await echange(ws, {"type": "routines_export"})]
    vue, autre, invisible, sienne, export = scenario_ws(service, jeton, corps)
    routines = par_id(vue)
    assert set(routines) == {ARRIVEE, a_lui["id"]}, "les routines « auteur » des autres ne se voient pas"
    assert routines[ARRIVEE]["droits"] == {"lancer": True, "couper": False, "supprimer": False}
    assert routines[a_lui["id"]]["droits"] == {"lancer": True, "couper": True, "supprimer": True}
    assert routines[a_lui["id"]]["auteur_nom"] == "toi"
    assert autre == {"type": "erreur", "cause": "droit", "genre": "routine_activer"}
    assert invisible == {"type": "erreur", "cause": "inconnue", "genre": "routine_supprimer"}
    assert sienne == {"type": "routine_ok", "genre": "routine_activer", "id": a_lui["id"]}
    assert export == {"type": "erreur", "cause": "droit", "genre": "routines_export"}
    assert R.registre().par_id(ARRIVEE)["actif"] is True and R.registre().par_id(a_lui["id"])["actif"] is False
    assert R.registre().par_id(SOIREE) is not None


def test_l_administrateur_voit_tout_coupe_supprime_et_exporte(service, moteur):
    charger_exemple()
    _, _, jeton = appairer_direct(service, "administrateur", "Propriétaire")

    async def corps(ws):
        return [await echange(ws, {"type": "routines"}),
                await echange(ws, {"type": "routine_activer", "id": FILM, "actif": True}),
                await echange(ws, {"type": "routine_supprimer", "id": SOIREE}),
                await echange(ws, {"type": "routines_export"}),
                await echange(ws, {"type": "routines"})]
    vue, reactivee, supprimee, export, apres = scenario_ws(service, jeton, corps)
    routines = par_id(vue)
    assert set(routines) == {ARRIVEE, SOIREE, FILM}
    for r in routines.values():
        assert r["droits"]["couper"] is True and r["droits"]["supprimer"] is True, r["id"]
    assert vue["droits"] == {"exporter": True, "tout_gerer": True}
    assert reactivee == {"type": "routine_ok", "genre": "routine_activer", "id": FILM}
    assert supprimee == {"type": "routine_ok", "genre": "routine_supprimer", "id": SOIREE}
    assert export["type"] == "routines_export" and export["contenu"]
    assert set(par_id(apres)) == {ARRIVEE, FILM} and par_id(apres)[FILM]["actif"] is True
    assert R.registre().par_id(SOIREE) is None


def test_la_personne_et_le_role_viennent_de_la_session_jamais_du_message(service, moteur):
    charger_exemple()
    _, _, jeton = appairer_direct(service, "invite", "Invité")

    async def corps(ws):
        return [await echange(ws, {"type": "routines", "role": "administrateur"}),
                await echange(ws, {"type": "routine_supprimer", "id": ARRIVEE, "personne": maison.CLE_PROPRIETAIRE}),
                await echange(ws, {"type": "routine_lancer", "id": FILM, "essai": True})]
    for rep in scenario_ws(service, jeton, corps):
        assert rep["type"] == "erreur" and rep["cause"] == "format", rep
    assert RW.personne_de("invite", "web:x") == "" and RW.personne_de("habitant", "appareil:tab1") == ""
    assert RW.personne_de("habitant", "web:abc") == "web:abc"
    assert RW.personne_de("administrateur", "web:abc") == maison.CLE_PROPRIETAIRE


def test_un_message_malforme_est_refuse_avant_le_moteur(service, moteur):
    charger_exemple()
    appels = []
    service.routines = lambda *a: appels.append(a)
    _, _, jeton = appairer_direct(service, "administrateur", "Propriétaire")
    mauvais = [{"type": "routines", "en_trop": 1},
               {"type": "routine_lancer"},
               {"type": "routine_lancer", "id": "../../etc"},
               {"type": "routine_lancer", "id": 4},
               {"type": "routine_activer", "id": FILM, "actif": "oui"},
               {"type": "routine_activer", "id": FILM},
               {"type": "routine_texte", "texte": ""},
               {"type": "routine_texte", "texte": "x" * (RW.TEXTE_MAX + 1)},
               {"type": "routine_supprimer", "id": "A" * 81}]

    async def corps(ws):
        return [await echange(ws, m) for m in mauvais]
    for m, rep in zip(mauvais, scenario_ws(service, jeton, corps)):
        assert rep == {"type": "erreur", "cause": "format", "genre": m["type"]}, m
    assert appels == []


def test_sans_moteur_l_ecran_dit_indisponible_et_une_exception_ne_laisse_rien_fuir(service, capsys):
    _, _, jeton = appairer_direct(service, "habitant", "Habitant")
    service.routines = None
    assert liste(service, jeton) == {"type": "erreur", "cause": "indisponible", "genre": "routines"}

    async def casse(*a):
        raise ValueError("secret interne C:/prive")
    service.routines = casse
    assert liste(service, jeton) == {"type": "erreur", "cause": "indisponible", "genre": "routines"}
    sortie = capsys.readouterr().out
    assert "ValueError" in sortie and "secret interne" not in sortie


# ------------------------------------------------------------------ contenu de la projection

def test_l_identifiant_technique_et_l_auteur_ne_partent_que_vers_le_proprietaire(service, moteur):
    charger_exemple()
    _, _, jeton_a = appairer_direct(service, "administrateur", "Propriétaire", conn=1)
    _, _, jeton_i = appairer_direct(service, "invite", "Invité", conn=2)
    admin = par_id(liste(service, jeton_a))
    invite = par_id(liste(service, jeton_i))
    etapes_admin = admin[ARRIVEE]["etapes_mots"]
    assert len(etapes_admin) == 3 and all(e["texte"] for e in etapes_admin)
    assert etapes_admin[0]["technique"] == "light.turn_on sur light.couloir_plafond"
    assert etapes_admin[2]["technique"] is None, "une annonce n'a pas d'identifiant technique"
    assert all(e["technique"] is None for e in invite[ARRIVEE]["etapes_mots"])
    assert "light." not in json.dumps(invite), "aucun identifiant d'entité vers un invité"
    assert admin[SOIREE]["auteur_nom"] == "Camille" and admin[ARRIVEE]["auteur_nom"] == "toi"
    assert invite[ARRIVEE]["auteur_nom"] == "le propriétaire" and invite[ARRIVEE]["lanceurs"] == "tout le monde"
    assert "auteur" not in invite[ARRIVEE], "l'auteur brut ne part jamais"
    assert admin[SOIREE]["derniere_execution"]["ok"] is False and admin[SOIREE]["derniere_execution"]["echecs"]
    assert admin[FILM]["derniere_execution"] is None and admin[FILM]["executions"] == 0


def test_un_lancement_ecrit_l_historique_et_un_changement_signale_routines_maj_aux_navigateurs(service, moteur):
    charger_exemple()
    _, _, jeton = appairer_direct(service, "administrateur", "Propriétaire")

    async def corps(ws):
        lancee = await echange(ws, {"type": "routine_lancer", "id": ARRIVEE})
        await envoyer(ws, {"type": "routine_activer", "id": ARRIVEE, "actif": False})
        recus = [await recevoir_reponse(ws), await recevoir_reponse(ws)]
        return lancee, recus
    lancee, recus = scenario_ws(service, jeton, corps)
    assert lancee["type"] == "routine_lancee" and lancee["ok"] is True and lancee["parole"]
    assert moteur.historiques, "le lancement écrit l'historique comme une commande dite"
    signal = next(m for m in recus if m.get("type") == "routines_maj")
    assert set(signal) == {"type", "version"} and isinstance(signal["version"], int)
    assert any(m.get("type") == "routine_ok" for m in recus)


def test_routine_texte_passe_par_le_meme_moteur_que_la_voix(service, moteur):
    charger_exemple()
    _, _, jeton = appairer_direct(service, "administrateur", "Propriétaire")

    async def corps(ws):
        return await echange(ws, {"type": "routine_texte", "texte": "quand je te dis dodo profond éteins le salon"})
    rep = scenario_ws(service, jeton, corps)
    assert rep["type"] == "routine_texte" and rep["parole"] and rep["confirmation_attendue"] == 30


# ------------------------------------------------------------------ rien sur le port 8765

def test_rien_des_routines_sur_le_port_8765(monkeypatch):
    monkeypatch.setattr(A, "journaliser", lambda *a, **k: None)
    _, sat, envoyes, _, _ = faux_serveur(monkeypatch, faux_assistant(), chiffre=False)
    for genre in sorted(RW.GENRES):
        jouer(sat, type=genre, id="x")
    assert [e["message"] for e in envoyes] == ["réservé au port chiffré"] * len(RW.GENRES)
    source = (RACINE / "serveur_satellite.py").read_text(encoding="utf-8")
    debut = source.index("class Satellite")
    fin = re.compile(r"\n(?:class|def|async def) ").search(source, debut + 1)
    satellite = source[debut:fin.start() if fin else len(source)]
    assert "réservé au port chiffré" in satellite
    assert "routines_web" not in satellite and "routines_pour_web" not in satellite
    assert "service_web.routines = routines_pour_web(moteur)" in source


# ------------------------------------------------------------------ page et script

def test_la_page_routines_n_a_ni_script_ni_style_en_ligne():
    html = (RACINE / "web" / "routines.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "style=" not in html and "<style" not in html
    assert not re.search(r"\son[a-z]+=", html), "aucun gestionnaire d'événement en ligne"
    assert not re.search(r"https?://", html)
    assert 'src="/client.js"' in html and 'src="/routines.js"' in html
    assert 'class="version dev-seulement"' in html, "les versions se masquent avec le mode développeur"
    assert 'role="alertdialog"' in html and 'id="garder-routine"' in html
    assert "Créer" not in html, "pas de bouton de création : une routine se crée à la voix"
    assert "Iris" not in html, "le nom de l'assistant vient de la configuration"


def test_le_script_routines_ne_fabrique_aucun_html_et_ne_touche_ni_au_stockage_ni_au_reseau():
    js = (RACINE / "web" / "routines.js").read_text(encoding="utf-8")
    for interdit in ("innerHTML", "insertAdjacentHTML", "document.write", "eval(", 'setAttribute("style"', ".cssText",
                     "localStorage", "sessionStorage", "fetch(", "XMLHttpRequest", "new Function"):
        assert interdit not in js, interdit
    assert not re.search(r"https?://", js)
    for genre in ("routines", "routine_lancer", "routine_activer", "routine_supprimer", "routines_maj"):
        assert f'"{genre}"' in js, genre
    assert "dev-seulement" in js, "l'identifiant technique d'une étape se masque hors mode développeur"


def test_les_causes_d_erreur_du_serveur_ont_un_texte_dans_l_ecran():
    js = (RACINE / "web" / "routines.js").read_text(encoding="utf-8")
    for cause in sorted(RW.CAUSES):
        assert re.search(rf"\b{cause}\b\s*:", js), cause
