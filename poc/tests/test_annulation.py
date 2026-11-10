"""Annulation d'une commande par un appui sur l'écran (0.60.0).

L'appli envoie {"type": "annuler"} (avec « ecouter » pour un appui sur l'heure). Le serveur lève l'événement des
commandes en cours de cet appareil : le client HTTP de Home Assistant refuse alors tout POST qui agit sur la maison,
la boucle des outils s'arrête, rien n'est appris, ni réponse ni audio ne partent, et le journal note « annulé »."""
import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest

import acces
import assistant as A
from test_boucle_outils import APPEL_SALON, assistant_requete, monter

CHEMINS = pytest.mark.parametrize("chemin", ["openai", "anthropic"])


def annulee():
    evenement = threading.Event()
    evenement.set()
    return evenement


# ------------------------------------------------------------------------------------------------ point de passage
def test_hors_requete_jamais_annulee():
    assert A.demande_annulee() is False


def test_requete_reprend_l_evenement_du_contexte():
    evenement = threading.Event()
    jeton = A.ANNULATION.set(evenement)
    try:
        with assistant_requete().requete(appareil="tab"):
            assert A.demande_annulee() is False
            evenement.set()
            assert A.demande_annulee() is True
    finally:
        A.ANNULATION.reset(jeton)


def test_client_ha_porte_le_crochet():
    ha = A.HomeAssistant("http://ha", "jeton-de-test")
    assert A.bloquer_si_annulee in ha.client.event_hooks["request"]


def client_note():
    vus = []

    def repondre(requete):
        vus.append((requete.method, requete.url.path))
        return httpx.Response(200, json={})
    return httpx.Client(transport=httpx.MockTransport(repondre), event_hooks={"request": [A.bloquer_si_annulee]}), vus


def test_crochet_refuse_les_actions_d_une_commande_annulee():
    client, vus = client_note()
    with assistant_requete().requete(appareil="tab", annulation=annulee()):
        for chemin in ("/api/services/light/turn_on", "/api/conversation/process"):
            with pytest.raises(A.DemandeAnnulee):
                client.post(f"http://ha{chemin}", json={})
        client.get("http://ha/api/states/light.essai")  # lire reste permis
        client.post("http://ha/api/template", json={"template": "x"})
    assert vus == [("GET", "/api/states/light.essai"), ("POST", "/api/template")]


def test_crochet_laisse_passer_une_commande_non_annulee():
    client, vus = client_note()
    with assistant_requete().requete(appareil="tab"):
        client.post("http://ha/api/services/light/turn_on", json={})
    assert vus == [("POST", "/api/services/light/turn_on")]


# ------------------------------------------------------------------------------------------------ boucle des outils
@CHEMINS
def test_annulee_avant_le_llm_aucun_appel(monkeypatch, chemin):
    c, ha = monter(monkeypatch, chemin, [("outils", [APPEL_SALON]), ("texte", "Voilà.")])
    with assistant_requete().requete(appareil="tab", annulation=annulee()):
        with pytest.raises(A.DemandeAnnulee):
            c.repondre("allume le salon")
    assert len(c.client.recus) == 0 and ha.client.posts == []
    assert c.historique == []  # la commande annulée ne reste pas dans la conversation


@CHEMINS
def test_annulee_pendant_l_appel_les_outils_ne_partent_pas(monkeypatch, chemin):
    c, ha = monter(monkeypatch, chemin, [("outils", [APPEL_SALON]), ("texte", "Voilà.")])
    evenement = threading.Event()
    faux = c.client
    if chemin == "openai":
        post = faux.post
        faux.post = lambda *a, **k: (evenement.set(), post(*a, **k))[1]
    else:
        creer = faux.create
        faux.create = lambda **k: (evenement.set(), creer(**k))[1]
    with assistant_requete().requete(appareil="tab", annulation=evenement):
        with pytest.raises(A.DemandeAnnulee) as e:
            c.repondre("allume le salon")
    assert len(c.client.recus) == 1 and ha.client.posts == [] and e.value.actions == []


@CHEMINS
def test_annulee_apres_une_action_plus_de_second_tour(monkeypatch, chemin):
    c, ha = monter(monkeypatch, chemin, [("outils", [APPEL_SALON]), ("texte", "Voilà.")])
    evenement = threading.Event()
    confirmer = ha.confirmer
    ha.confirmer = lambda *a, **k: (evenement.set(), confirmer(*a, **k))[1]  # l'appui arrive après l'ordre
    with assistant_requete().requete(appareil="tab", annulation=evenement):
        with pytest.raises(A.DemandeAnnulee) as e:
            c.repondre("allume le salon")
    assert len(c.client.recus) == 1 and len(ha.client.posts) == 1
    assert e.value.actions == ["light.turn_on light.essai"]  # pour « Annulé, déjà fait : ... »


# ------------------------------------------------------------------------------------------------ journal
@pytest.mark.parametrize("voie, issue", [("llm (x) annulée", "annulé"), ("dictionnaire (a) annulée [essai]", "annulé"),
                                         ("transcription annulée", "annulé"), ("llm (x)", "ok")])
def test_issue_d_une_commande_annulee(voie, issue):
    assert A.issue_de(voie) == issue


def test_actions_faites_ecarte_refus_et_annulations():
    actions = ["light.turn_on light.a", "light.turn_on light.b (annulé)", "lock.unlock lock.p (refusé : sécurité)",
               "music_assistant.play_media x (non joué)", "light.turn_off light.c (non confirmé)"]
    assert A.actions_faites(actions) == ["light.turn_on light.a", "light.turn_off light.c (non confirmé)"]


def test_rien_n_est_appris_d_une_commande_annulee():
    assistant = assistant_requete()
    assistant.cerveau = SimpleNamespace(dernieres_actions=[{"service": "light.turn_on", "entity_id": "light.essai"}])
    assistant.dico = SimpleNamespace(apprendre=lambda *a: pytest.fail("une commande annulée ne s'apprend pas"))
    with assistant.requete(appareil="tab", annulation=annulee()):
        assistant.apprendre("allume la lampe du bureau", "C'est allumé.")


# ------------------------------------------------------------------------------------------------ message annuler
def test_annuler_permis_a_tous_les_roles():
    for role in ("administrateur", "habitant", "partage", "invite"):
        assert acces.type_permis(role, "annuler")


def satellite(etat="reflexion"):
    import serveur_satellite as S
    sat = object.__new__(S.Satellite)
    sat.nom, sat.identite, sat.etat, sat.reveil = "Tab", "appareil:a1", etat, None
    sat.moteur = SimpleNamespace(appareils=None, verrou=asyncio.Lock(), noms=lambda e: e,
                                 diffuser_historique=lambda *a: asyncio.sleep(0), diffuser=lambda *a: asyncio.sleep(0))
    envoyes, ecoutes = [], []

    async def envoyer(**m):
        envoyes.append(m)

    async def commencer_ecoute(origine):
        ecoutes.append(origine)
        sat.etat = "ecoute"
    sat.envoyer, sat.commencer_ecoute = envoyer, commencer_ecoute
    return S, sat, envoyes, ecoutes


def test_annuler_pendant_la_reflexion_revient_au_repos():
    S, sat, envoyes, ecoutes = satellite()
    evenement = threading.Event()
    sat.en_cours().add(evenement)
    asyncio.run(sat.recevoir_texte('{"type": "annuler"}'))
    assert evenement.is_set() and sat.etat == "repos" and ecoutes == []
    assert envoyes == [{"etat": "repos", "raison": "annule"}]


def test_annuler_avec_ecouter_relance_l_ecoute():
    S, sat, envoyes, ecoutes = satellite()
    asyncio.run(sat.recevoir_texte('{"type": "annuler", "ecouter": true}'))
    assert ecoutes == ["bouton Parler"] and sat.etat == "ecoute"


def test_annuler_ne_touche_que_les_commandes_de_cet_appareil():
    S, sat, _, _ = satellite()
    S2, autre, _, _ = satellite()
    a_moi, a_l_autre = threading.Event(), threading.Event()
    sat.en_cours().add(a_moi)
    autre.en_cours().add(a_l_autre)
    asyncio.run(sat.recevoir_texte('{"type": "annuler"}'))
    assert a_moi.is_set() and not a_l_autre.is_set() and autre.etat == "reflexion"


def test_llm_annule_aucune_reponse_tardive(monkeypatch):
    S, sat, envoyes, _ = satellite("repos")
    monkeypatch.setattr(S, "lire_journal", lambda n: [])
    vus = []

    def llm_texte(texte, essai, personne=None, appareil=None):
        evenement = A.ANNULATION.get()  # l'événement de la session a suivi la commande dans son fil
        vus.append(evenement)
        evenement.set()  # l'appui arrive pendant la réflexion
        return {"reponse": "", "actions": ["light.turn_on light.essai"], "annulee": True,
                "faites": ["light.turn_on light.essai"]}
    sat.moteur.llm_texte = llm_texte
    asyncio.run(sat.repondre_llm({"type": "llm", "texte": "allume la lampe"}))
    assert isinstance(vus[0], threading.Event) and sat.en_cours() == set()
    assert [m["etat"] for m in envoyes] == ["annule"]
    assert envoyes[0]["faites"] == ["allumer light.essai"]


def test_llm_annule_sans_action_rien_n_est_envoye(monkeypatch):
    S, sat, envoyes, _ = satellite("repos")
    monkeypatch.setattr(S, "lire_journal", lambda n: [])
    sat.moteur.llm_texte = lambda *a: {"reponse": "", "actions": [], "annulee": True, "faites": []}
    asyncio.run(sat.repondre_llm({"type": "llm", "texte": "allume la lampe"}))
    assert envoyes == []


def test_llm_non_annule_repond_comme_avant(monkeypatch):
    S, sat, envoyes, _ = satellite("repos")
    monkeypatch.setattr(S, "lire_journal", lambda n: [])
    sat.moteur.llm_texte = lambda *a: {"reponse": "ok", "actions": [], "cerveau": "x", "ms": 0, "erreur": "",
                                       "essai": False}
    asyncio.run(sat.repondre_llm({"type": "llm", "texte": "allume la lampe"}))
    assert [m["etat"] for m in envoyes] == ["llm"] and A.ANNULATION.get() is None


def test_phrase_annulee_ne_parle_pas_et_garde_l_etat(monkeypatch):
    """Mode serveur : la phrase est traitée dans une tâche, l'annulation arrive pendant le traitement."""
    import numpy as np
    S, sat, envoyes, ecoutes = satellite("ecoute")
    sat.capture, sat.qui_parle = [np.zeros(160, dtype=np.int16)], None
    sat.annoncer_demande = lambda: None
    sat.reinitialiser_reveil = lambda: None
    monkeypatch.setattr(S, "lire_journal", lambda n: [{"actions": "light.turn_on light.essai | light.turn_off light.b (annulé)"}])

    async def scenario():
        demarre = threading.Event()
        libere = threading.Event()

        def traiter(signal, personne, appareil):
            demarre.set()
            libere.wait(5)
            assert A.demande_annulee() is False  # hors requête ici, mais l'événement du contexte est levé
            assert A.ANNULATION.get().is_set()
            return "allume la lampe", "", "llm (x) annulée", None
        sat.moteur.traiter = traiter
        sat.lancer_phrase()
        assert sat.etat == "reflexion"
        while not demarre.is_set():
            await asyncio.sleep(0.01)
        await sat.recevoir_texte('{"type": "annuler", "ecouter": true}')
        libere.set()
        await sat.tache_phrase
    asyncio.run(scenario())
    etats = [m.get("etat") for m in envoyes]
    assert etats == ["reflexion", "repos", "annule"]  # ni « reponse » ni audio, pas de second « repos »
    assert envoyes[2]["faites"] == ["allumer light.essai"]
    assert ecoutes == ["bouton Parler"] and sat.etat == "ecoute"  # la nouvelle écoute n'est pas écrasée
