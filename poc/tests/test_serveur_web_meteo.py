"""Écran Météo et mer sur le serveur du client web (S-W5) : pages, message « meteo » par WebSocket, filtrage par rôle,
en-têtes, aucun script ni style en ligne."""
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import meteo_web as MW
import serveur_satellite as SS
import serveur_web as W
from test_meteo_web import MAINTENANT, donnees_mer, donnees_vent, fournisseur, locale
from test_serveur_web_appairage import (  # noqa: F401  (fixtures réutilisées)
    appairer_direct, arreter, entetes, envoyer, horloge, journal, lancer, ouvrir_ws, recevoir, recevoir_reponse,
    service, statut_de)

RACINE = Path(__file__).resolve().parent.parent


def meteo_factice(mer="defaut", vent="defaut"):
    mer = donnees_mer() if mer == "defaut" else mer
    vent = donnees_vent() if vent == "defaut" else vent
    return MW.Meteo(None if mer is None else fournisseur(mer), None if vent is None else fournisseur(vent),
                    maintenant=lambda: MAINTENANT, locale=locale)


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
    return await recevoir_reponse(ws)


# ------------------------------------------------------------------ pages et script

def test_le_message_meteo_est_dans_la_liste_blanche_et_la_version_du_client_est_0_8_0():
    assert MW.GENRES == ("meteo",) and "meteo" in W.MESSAGES_TOUT_ROLE
    assert W.VERSION_CLIENT == "0.9.1"


def test_la_page_et_le_script_exigent_une_session(service):
    rep = service.traiter("127.0.0.1", "/meteo", entetes())
    assert statut_de(rep) == 303 and rep[1]["Location"] == "/appairage"
    assert statut_de(service.traiter("127.0.0.1", "/meteo.js", entetes())) == 401


def test_la_page_est_servie_a_chaque_role_avec_les_en_tetes_de_securite(service):
    for conn, role in enumerate(("administrateur", "habitant", "invite"), start=1):
        _, _, jeton = appairer_direct(service, role, f"Appareil {role}", conn=conn)
        page = service.traiter("127.0.0.1", "/meteo", entetes(jeton))
        assert statut_de(page) == 200, role
        html = page[2].decode("utf-8")
        assert "{{" not in html and W.VERSION_CLIENT in html and "9.9.9" in html and "Météo et mer" in html, role
        csp = page[1]["Content-Security-Policy"]
        assert "script-src 'self'" in csp and "unsafe-inline" not in csp and "require-trusted-types-for 'script'" in csp
        assert page[1]["Cache-Control"] in ("no-store", "no-cache") and page[1]["X-Content-Type-Options"] == "nosniff"
        script = service.traiter("127.0.0.1", "/meteo.js", entetes(jeton))
        assert statut_de(script) == 200 and b"/ws" in script[2], role
        assert "javascript" in script[1]["Content-Type"]


def test_la_page_meteo_est_dans_les_tables_protegees_et_liee_depuis_l_accueil():
    assert W.PAGES_PROTEGEES["/meteo"][0] == "meteo.html" and W.SCRIPTS_PROTEGES["/meteo.js"][0] == "meteo.js"
    accueil = (RACINE / "web" / "index.html").read_text(encoding="utf-8")
    assert "{{onglets-cache:accueil}}" in accueil and 'href="/meteo"' in W.barre_onglets("accueil", "Iris")


# ------------------------------------------------------------------ message par WebSocket

def test_meteo_par_websocket_est_servi_a_l_habitant_et_refuse_a_l_invite(service):
    service.meteo = meteo_factice()
    _, _, jeton_h = appairer_direct(service, "habitant", "Habitant", conn=1)
    _, _, jeton_i = appairer_direct(service, "invite", "Invité", conn=2)

    async def corps(ws):
        return [await echange(ws, {"type": "meteo"}), await echange(ws, {"type": "meteo", "point": "pharo"})]
    defaut, pharo = scenario_ws(service, jeton_h, corps)
    assert defaut["type"] == "meteo" and defaut["point"]["id"] == "prado" and defaut["heures"]
    assert pharo["point"]["id"] == "pharo" and pharo["heures"] == []

    async def invite(ws):
        return await echange(ws, {"type": "meteo"})
    rep = scenario_ws(service, jeton_i, invite)
    assert rep == {"type": "erreur", "cause": "droit", "genre": "meteo"}


def test_le_role_vient_de_la_session_jamais_du_message(service):
    service.meteo = meteo_factice()
    _, _, jeton_i = appairer_direct(service, "invite", "Invité", conn=1)

    async def corps(ws):
        return [await echange(ws, {"type": "meteo", "role": "administrateur"}),
                await echange(ws, {"type": "meteo", "point": "prado", "role": "administrateur"})]
    for rep in scenario_ws(service, jeton_i, corps):
        assert rep["type"] == "erreur" and rep["genre"] == "meteo"
        assert rep["cause"] in ("droit", "format") and "heures" not in rep and "points" not in rep


def test_un_message_hors_schema_ou_un_point_inconnu_donne_une_erreur_courte(service):
    service.meteo = meteo_factice()
    _, _, jeton = appairer_direct(service, "habitant")

    async def corps(ws):
        return [await echange(ws, {"type": "meteo", "lat": 43.2}), await echange(ws, {"type": "meteo", "point": 4}),
                await echange(ws, {"type": "meteo", "point": "nulle-part"})]
    hors_schema, mauvais_type, inconnu = scenario_ws(service, jeton, corps)
    assert hors_schema == {"type": "erreur", "cause": "format", "genre": "meteo"}
    assert mauvais_type == {"type": "erreur", "cause": "format", "genre": "meteo"}
    assert inconnu == {"type": "erreur", "cause": "entite", "genre": "meteo", "entite": "nulle-part"}


def test_sans_fournisseur_l_ecran_dit_indisponible(service):
    service.meteo = None
    _, _, jeton = appairer_direct(service, "habitant")

    async def corps(ws):
        return await echange(ws, {"type": "meteo"})
    assert scenario_ws(service, jeton, corps) == {"type": "erreur", "cause": "indisponible", "genre": "meteo"}


def test_deux_sources_en_panne_disent_indisponible_sans_le_texte_de_l_exception(service):
    service.meteo = meteo_factice(mer=RuntimeError("jeton sk-secret"), vent=OSError("chemin C:/prive"))
    _, _, jeton = appairer_direct(service, "habitant")

    async def corps(ws):
        return await echange(ws, {"type": "meteo"})
    rep = scenario_ws(service, jeton, corps)
    assert rep == {"type": "erreur", "cause": "indisponible", "genre": "meteo"}


def test_une_exception_inattendue_ne_laisse_partir_que_indisponible(service, capsys):
    class Casse:
        async def vue(self, role, msg):
            raise ValueError("secret interne http://interne.invalid")
    service.meteo = Casse()
    _, _, jeton = appairer_direct(service, "habitant")

    async def corps(ws):
        return await echange(ws, {"type": "meteo"})
    rep = scenario_ws(service, jeton, corps)
    assert rep == {"type": "erreur", "cause": "indisponible", "genre": "meteo"}
    sortie = capsys.readouterr().out
    assert "ValueError" in sortie and "secret interne" not in sortie


def test_la_reponse_ne_porte_aucune_coordonnee_ni_champ_interne(service):
    service.meteo = meteo_factice()
    _, _, jeton = appairer_direct(service, "habitant")

    async def corps(ws):
        return await echange(ws, {"type": "meteo", "point": "prado"})
    brut = json.dumps(scenario_ws(service, jeton, corps))
    for interdit in ("43.25", "5.36", '"lat"', '"lon"', "seuil_min", "http"):
        assert interdit not in brut, interdit


def test_une_source_en_panne_partielle_reste_servie_avec_son_avertissement(service):
    service.meteo = meteo_factice(vent=RuntimeError("x"))
    _, _, jeton = appairer_direct(service, "administrateur")

    async def corps(ws):
        return await echange(ws, {"type": "meteo"})
    rep = scenario_ws(service, jeton, corps)
    assert rep["type"] == "meteo" and rep["sources_en_panne"] == ["Balises de vent indisponibles"]


# ------------------------------------------------------------------ branchement sur le serveur

def test_meteo_pour_web_branche_les_lectures_en_cache_et_traite_une_source_eteinte_comme_telle():
    class Source:
        def __init__(self, donnees):
            self._d = donnees

        async def donnees(self):
            return self._d
    moteur = SimpleNamespace(meteo_mer=Source(donnees_mer()), vent_mesure=Source(donnees_vent()))
    m = SS.meteo_pour_web(moteur)
    rep = asyncio.run(m.vue("habitant", {"type": "meteo"}))
    assert rep["type"] == "meteo" and rep["point"]["id"] == "prado" and rep["balises"]
    eteint = SS.meteo_pour_web(SimpleNamespace(meteo_mer=Source(donnees_mer()), vent_mesure=None))
    assert asyncio.run(eteint.vue("habitant", {"type": "meteo"}))["sources_en_panne"] == []
    rien = SS.meteo_pour_web(SimpleNamespace(meteo_mer=None, vent_mesure=None))
    with pytest.raises(MW.RefusMeteo) as e:
        asyncio.run(rien.vue("habitant", {"type": "meteo"}))
    assert e.value.cause == "indisponible"


def test_le_serveur_pose_service_web_meteo_sans_nouvelle_source_reseau():
    source = (RACINE / "serveur_satellite.py").read_text(encoding="utf-8")
    assert "service_web.meteo = meteo_pour_web(moteur)" in source
    debut = source.index("def meteo_pour_web")
    fonction = source[debut:source.index("\nclass ", debut)]
    assert "moteur.meteo_mer.donnees()" in fonction and "moteur.vent_mesure.donnees()" in fonction
    assert not re.search(r"https?://|urlopen|requests|httpx|aiohttp", fonction)


# ------------------------------------------------------------------ page et script

def test_la_page_meteo_n_a_ni_script_ni_style_en_ligne():
    html = (RACINE / "web" / "meteo.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "style=" not in html and "<style" not in html
    assert not re.search(r"\son[a-z]+=", html), "aucun gestionnaire d'événement en ligne"
    assert not re.search(r"https?://", html)
    assert 'src="/client.js"' in html and 'src="/meteo.js"' in html
    assert 'class="version dev-seulement"' in html, "les versions se masquent avec le mode développeur"


def test_le_script_meteo_ne_fabrique_aucun_html_et_ne_touche_ni_au_stockage_ni_au_reseau():
    js = (RACINE / "web" / "meteo.js").read_text(encoding="utf-8")
    for interdit in ("innerHTML", "insertAdjacentHTML", "document.write", "eval(", 'setAttribute("style"', ".cssText",
                     "localStorage", "sessionStorage", "fetch(", "XMLHttpRequest", "new Function"):
        assert interdit not in js, interdit
    assert not re.search(r"https?://", js)
    assert '"meteo"' in js


def test_le_defilement_horizontal_des_heures_est_voulu_et_declare():
    js = (RACINE / "web" / "meteo.js").read_text(encoding="utf-8")
    assert "data-defilement-horizontal-voulu" in js


def test_les_causes_d_erreur_du_serveur_ont_un_texte_dans_l_ecran():
    js = (RACINE / "web" / "meteo.js").read_text(encoding="utf-8")
    for cause in sorted(MW.CAUSES):
        assert re.search(rf"\b{cause}\b\s*:", js), cause


def test_les_symboles_du_ciel_du_serveur_sont_tous_dessines_par_le_client():
    js = (RACINE / "web" / "meteo.js").read_text(encoding="utf-8")
    for symbole in sorted(MW.SYMBOLES):
        assert f'{symbole}' in js, symbole

