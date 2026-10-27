"""Barre du bas du client web : rendue par le serveur dans chaque page, l'onglet courant allumé, l'orbe du milieu qui
mène à /ecouter (la page Demander, micro ouvert dès l'arrivée). Seul le nom de l'assistant vient de la configuration :
il est échappé."""
import re
from pathlib import Path

import serveur_web as W
from test_serveur_web_appairage import (  # noqa: F401  (fixtures réutilisées)
    appairer_direct, entetes, horloge, journal, service, statut_de)

WEB = Path(__file__).resolve().parent.parent / "web"
PAGES = {"index.html": "accueil", "journal.html": "journal", "demander.html": "demander", "maison.html": "maison",
         "meteo.html": "meteo", "reglages.html": "aucun", "vie-privee.html": "aucun", "associer.html": "aucun"}


def test_chaque_page_connectee_porte_la_barre_et_une_marge_pour_elle():
    for nom, actif in PAGES.items():
        texte = (WEB / nom).read_text(encoding="utf-8")
        marques = W._MODELE_ONGLETS.findall(texte)
        assert [m[1] for m in marques] == [actif], nom
        assert "contenu--onglets" in texte, nom
    # L'accueil sert aussi l'appareil pas encore appairé : la barre y reste cachée jusqu'à la réponse de /api/etat.
    assert "{{onglets-cache:accueil}}" in (WEB / "index.html").read_text(encoding="utf-8")
    for nom in ("appairage.html",):
        assert "{{onglets" not in (WEB / nom).read_text(encoding="utf-8")


def test_l_onglet_courant_est_seul_allume_et_l_orbe_est_au_milieu():
    for actif in ("accueil", "journal", "maison", "meteo"):
        barre = W.barre_onglets(actif, "Iris")
        assert barre.count('aria-current="page"') == 1
        courant = re.search(r'<a [^>]*aria-current="page"[^>]*>', barre).group(0)
        assert f'href="{dict((c, l) for c, l, _ in W.ONGLETS)[actif]}"' in courant
    liens = re.findall(r'<a [^>]*>', W.barre_onglets("aucun", "Iris"))
    assert len(liens) == 5 and "onglet--orbe" in liens[2] and 'href="/ecouter"' in liens[2]
    assert 'aria-current' not in W.barre_onglets("aucun", "Iris")


def test_sur_demander_l_orbe_reste_sur_la_page():
    barre = W.barre_onglets("demander", "Iris")
    orbe = re.search(r'<a id="onglet-micro"[^>]*>', barre).group(0)
    assert 'href="/demander"' in orbe and 'aria-current="page"' in orbe


def test_le_nom_de_l_assistant_est_echappe_et_la_barre_cachee_sur_demande():
    barre = W.barre_onglets("accueil", 'A"<b>', cache=True)
    assert "<b>" not in barre and "&quot;" in barre and "&lt;b&gt;" in barre
    assert re.match(r'<nav id="onglets" class="onglets" aria-label="[^"]+" hidden>', barre)
    assert " hidden" not in W.barre_onglets("accueil", "Iris")[:120]
    # Ni style en ligne ni gestionnaire d'événement : la CSP de la page les refuserait.
    assert "style=" not in barre and not re.search(r"\son\w+=", barre)


def test_ecouter_est_protegee_et_sert_la_page_demander(service):
    assert W.PAGES_PROTEGEES["/ecouter"][0] == W.PAGES_PROTEGEES["/demander"][0] == "demander.html"
    sans = service.traiter("127.0.0.1", "/ecouter", entetes())
    assert statut_de(sans) in (302, 303, 401, 403)
    _, _, jeton = appairer_direct(service, "habitant")
    rep = service.traiter("127.0.0.1", "/ecouter", entetes(jeton))
    corps = rep[2].decode("utf-8")
    assert statut_de(rep) == 200 and 'id="formulaire-demande"' in corps
    assert "{{" not in corps and 'id="onglet-micro"' in corps


def test_les_pages_rendues_ne_gardent_aucune_marque(service):
    _, _, jeton = appairer_direct(service, "habitant")
    for chemin in ("/", "/journal", "/demander", "/maison", "/meteo", "/reglages", "/vie-privee"):
        rep = service.traiter("127.0.0.1", chemin, entetes(jeton))
        corps = rep[2].decode("utf-8")
        assert statut_de(rep) == 200, chemin
        assert "{{" not in corps and '<nav id="onglets"' in corps, chemin
