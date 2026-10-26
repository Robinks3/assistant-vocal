"""S-F4 (0.40.0) : contexte de requête et point de contrôle unique des appels de service.

Une requête porte son essai, sa personne, son appareil, son rôle et son canal dans un contexte (REQUETE), jamais
sur les objets partagés. La personne et le rôle viennent de la session (jeton, appareils.json), pas du message.
Tout appel de service passe par acces.controler_service, quelle que soit la voie (LLM, dictionnaire, appli)."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

import acces
import assistant as A
import maison
import securite

ENTITE = "light.salon_plafond"
PROPRIETAIRE = maison.CLE_PROPRIETAIRE


class Client:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None):
        self.posts.append((url, json))
        return SimpleNamespace(status_code=200, text="", json=lambda: [])


def faux_ha():
    ha = A.HomeAssistant.__new__(A.HomeAssistant)
    ha.url, ha.client, ha.essai, ha.vue_llm = "http://ha", Client(), False, {}
    ha.entites_llm = {ENTITE}
    ha.confirmer = lambda *a, **k: []
    ha.manquantes = []
    return ha


def faux_assistant(ha=None):
    a = object.__new__(A.Assistant)
    a.ha, a.essai = ha, False
    a.indication = lambda p: f" parle : {p}." if p else ""
    return a


def appareils_avec(tmp_path, *entrees):
    app = acces.Appareils(tmp_path, {})
    app.liste = [dict({"nom": "Tab", "empreinte": "x", "cree": "2026-10-26 10:00:00", "dernier": ""}, **e)
                 for e in entrees]
    return app


# ---------------------------------------------------------------------------------------------------------------
# Le contexte de requête : rôle et canal
# ---------------------------------------------------------------------------------------------------------------

def test_requete_par_defaut_sans_role_ni_canal():
    r = A.Requete()
    assert (r.essai, r.personne, r.appareil, r.indication, r.role, r.canal) == (False, None, None, "", "", "")


def test_requete_garde_role_et_canal():
    r = A.Requete(True, "camille", "appareil:i1", "ind", "invite", "voix")
    assert (r.role, r.canal, r.personne, r.appareil, r.essai) == ("invite", "voix", "camille", "appareil:i1", True)


def test_role_pris_de_l_appareil_appaire(monkeypatch, tmp_path):
    app = appareils_avec(tmp_path, {"id": "i1", "role": "invite"}, {"id": "h1", "role": "habitant"})
    monkeypatch.setattr(A, "ROLE_DE", lambda identite: acces.role_effectif(identite, app))
    a = faux_assistant()
    with a.requete(appareil="appareil:i1", canal="appli"):
        r = A.requete_en_cours()
        assert (r.role, r.canal) == ("invite", "appli")
    with a.requete(appareil="appareil:h1", canal="voix"):
        r = A.requete_en_cours()
        assert (r.role, r.canal) == ("habitant", "voix")
    with a.requete():  # micro du PC, pas d'appareil
        assert A.requete_en_cours().role == "local"
    assert A.requete_en_cours() is None


def test_role_donne_par_l_appelant_l_emporte(monkeypatch):
    monkeypatch.setattr(A, "ROLE_DE", lambda identite: "habitant")
    a = faux_assistant()
    with a.requete(appareil="appareil:x", role="invite", canal="texte"):
        assert A.requete_en_cours().role == "invite"
        assert A.requete_en_cours().canal == "texte"


# ---------------------------------------------------------------------------------------------------------------
# Deux requêtes simultanées ne se croisent pas
# ---------------------------------------------------------------------------------------------------------------

def test_deux_requetes_simultanees_dans_deux_threads(monkeypatch):
    monkeypatch.setattr(A, "ROLE_DE", lambda identite: "invite" if identite.endswith("a") else "habitant")
    ha = faux_ha()
    a = faux_assistant(ha)
    barriere = threading.Barrier(2, timeout=10)
    vu = {}

    def requete(nom, essai, personne, appareil, canal):
        with a.requete(essai=essai, personne=personne, appareil=appareil, canal=canal):
            barriere.wait()  # les deux requêtes sont ouvertes en même temps
            r = A.requete_en_cours()
            vu[nom] = (a.essai, ha.essai, ha.personne, r.personne, r.appareil, r.role, r.canal, r.indication)
            barriere.wait()
            # Encore le même après que l'autre a fini d'écrire son contexte.
            assert (ha.personne, r.canal) == (personne, canal)

    fils = [threading.Thread(target=requete, args=("a", True, "camille", "appareil:a", "voix")),
            threading.Thread(target=requete, args=("b", False, "sacha", "appareil:b", "texte"))]
    for f in fils:
        f.start()
    for f in fils:
        f.join(15)
    assert vu["a"] == (True, True, "camille", "camille", "appareil:a", "invite", "voix", " parle : camille.")
    assert vu["b"] == (False, False, "sacha", "sacha", "appareil:b", "habitant", "texte", " parle : sacha.")
    assert A.requete_en_cours() is None and ha.personne is None and not ha.essai


def test_deux_requetes_simultanees_dans_une_boucle(monkeypatch):
    """asyncio.to_thread copie le contexte : chaque tâche voit le sien, même entrelacées."""
    ha = faux_ha()
    a = faux_assistant(ha)

    async def une(personne, canal, attente):
        def travail():
            with a.requete(personne=personne, appareil="tab-" + personne, canal=canal):
                return (ha.personne, A.requete_en_cours().canal, A.Cerveau.cle_conversation())
        await asyncio.sleep(attente)
        return await asyncio.to_thread(travail)

    async def scenario():
        return await asyncio.gather(une("camille", "voix", 0.02), une("sacha", "appli", 0.0))
    camille, sacha = asyncio.run(scenario())
    assert camille == ("camille", "voix", ("camille", "tab-camille"))
    assert sacha == ("sacha", "appli", ("sacha", "tab-sacha"))
    assert A.requete_en_cours() is None


def test_la_personne_n_est_plus_un_champ_de_l_objet_partage():
    ha = faux_ha()
    with pytest.raises(AttributeError):
        ha.personne = "sacha"  # lecture seule depuis 0.40.0
    assert ha.personne is None
    assert "personne" not in vars(ha)


def test_essai_du_serveur_est_le_defaut_d_une_requete_sans_essai_explicite():
    ha = faux_ha()
    a = faux_assistant(ha)
    a.essai = ha.essai = True  # réglage du serveur, fait sous le verrou du moteur (Moteur.changer_mode)
    with a.requete():
        assert a.essai and ha.essai
    with a.requete(essai=False):  # l'essai de la requête ne s'écrit nulle part, le plancher du serveur reste
        assert not a.essai
        assert ha.essai  # côté HA, le plancher du serveur s'ajoute toujours (OU), il ne se lève pas
    assert a.essai and ha.essai  # le réglage du serveur n'a pas bougé
    a.essai = ha.essai = False
    with a.requete(essai=True):
        assert a.essai and ha.essai
    assert not a.essai and not ha.essai


# ---------------------------------------------------------------------------------------------------------------
# La personne vient de la session, jamais du message
# ---------------------------------------------------------------------------------------------------------------

@pytest.fixture
def parc(tmp_path):
    return appareils_avec(tmp_path,
                          {"id": "h1", "role": "habitant", "personne": "camille"},
                          {"id": "i1", "role": "invite", "personne": "camille"},
                          {"id": "i2", "role": "invite"})


def satellite(identite, parc, canal_appels):
    import serveur_satellite as S
    verrou = asyncio.Lock()

    def llm_texte(texte, essai, personne=None, appareil=None, canal="appli"):
        canal_appels.append(("llm", personne, appareil, canal))
        return {"reponse": "ok", "actions": [], "cerveau": "x", "ms": 0, "erreur": "", "essai": essai}

    envoyes = []
    moteur = SimpleNamespace(appareils=parc, verrou=verrou, llm_texte=llm_texte,
                             diffuser_historique=lambda *a: asyncio.sleep(0))
    sat = object.__new__(S.Satellite)
    sat.moteur, sat.nom, sat.identite = moteur, "Tab", identite

    async def envoyer(**m):
        envoyes.append(m)
    sat.envoyer = envoyer
    return S, sat, envoyes


def test_personne_forgee_dans_le_message_ignoree_pour_un_invite(monkeypatch, parc):
    appels = []
    S, sat, _ = satellite("appareil:i2", parc, appels)
    monkeypatch.setattr(S, "lire_journal", lambda n: [])
    for forgee in ("camille", "sacha", PROPRIETAIRE, "propriétaire"):
        assert sat.personne_du_message({"type": "llm", "personne": forgee}) is None
    asyncio.run(sat.repondre_llm({"texte": "allume ma chambre", "personne": "camille", "essai": True}))
    assert appels == [("llm", None, sat.cle_appareil(), "appli")]


def test_invite_garde_sa_personne_d_appareil_pas_celle_du_message(monkeypatch, parc):
    appels = []
    S, sat, _ = satellite("appareil:i1", parc, appels)
    monkeypatch.setattr(S, "lire_journal", lambda n: [])
    asyncio.run(sat.repondre_llm({"texte": "allume ma chambre", "personne": PROPRIETAIRE, "essai": True}))
    assert appels[0][1] == "camille"  # le champ de son entrée, jamais le propriétaire annoncé par le message


def test_personne_forgee_ignoree_pour_parler_et_reveil(parc):
    appels = []
    S, sat, _ = satellite("appareil:i2", parc, appels)
    assert sat.personne_du_message({"type": "parler", "personne": "camille"}) is None
    assert sat.personne_du_message({"type": "reveil", "personne": PROPRIETAIRE}) is None


def test_passerelle_ha_ignore_la_personne_forgee(monkeypatch, parc):
    """Un invite ne peut pas se faire passer pour une personne dont les droits « ma chambre » valent."""
    import serveur_satellite as S
    vus = []
    monkeypatch.setattr(acces, "verifier_requete_ha", lambda m, c, corps, personne=None: vus.append(personne))
    ha = SimpleNamespace(url="http://ha", client=SimpleNamespace(request=lambda *a, **k: SimpleNamespace(
        status_code=200, text="[]", headers={}, content=b"")))
    moteur = SimpleNamespace(assistant=SimpleNamespace(ha=ha), appareils=parc, essai=False)
    S.passerelle_ha(moteur, {"id": 1, "methode": "POST", "chemin": "/api/services/light/turn_on",
                             "corps": {"entity_id": ENTITE}, "personne": "camille"}, "appareil:i2")
    assert vus == [None]


def test_canal_et_personne_passent_du_message_au_contexte(monkeypatch):
    """Moteur.llm_texte ouvre le contexte avec le canal « appli » et rien d'autre que ce qu'on lui donne."""
    import serveur_satellite as S
    vus = []

    class Cerveau:
        def repondre(self, texte):
            r = A.requete_en_cours()
            vus.append((r.personne, r.appareil, r.canal, r.role))
            return "ok", []

    a = faux_assistant()
    a.cerveau, a.apprendre = Cerveau(), lambda *x: None
    monkeypatch.setattr(A, "ROLE_DE", lambda identite: "invite")
    monkeypatch.setattr(A, "journaliser", lambda *x, **k: None)
    moteur = object.__new__(S.Moteur)
    moteur.assistant, moteur.essai, moteur.cerveau_actif = a, False, "claude"
    moteur.llm_texte("bonjour", True, None, "appareil:i2")
    assert vus == [(None, "appareil:i2", "appli", "invite")]


# ---------------------------------------------------------------------------------------------------------------
# Le point de contrôle unique
# ---------------------------------------------------------------------------------------------------------------

def test_controle_ordre_et_genres():
    permis = {"turn_on", "turn_off"}
    r = acces.controler_service("lock", "unlock", {}, services_permis=permis)
    assert r and r.genre == "domaine"  # le domaine passe avant la liste blanche
    r = acces.controler_service("light", "explose", {"entity_id": ENTITE}, services_permis=permis)
    assert r and r.genre == "service"
    r = acces.controler_service("light", "turn_on", {"entity_id": 3}, services_permis=permis)
    assert r and r.genre == "donnees"
    r = acces.controler_service("light", "turn_on", {"entity_id": ENTITE, 4: 5}, services_permis=permis)
    assert r and r.genre == "donnees"
    r = acces.controler_service("light", "turn_on", ["pas", "un", "objet"])
    assert r and r.genre == "donnees"
    r = acces.controler_service("light", "turn_on", {"entity_id": ENTITE, "device_id": "abc"}, services_permis=permis)
    assert r and r.genre == "securite"
    assert acces.controler_service("light", "turn_on", {"entity_id": ENTITE}, services_permis=permis) is None
    assert acces.controler_service("light", "turn_on", {"entity_id": [ENTITE, ENTITE]}) is None
    assert acces.controler_service("media_player", "join", {"entity_id": ENTITE}) is None  # sans liste blanche


@pytest.mark.parametrize("domaine,service", [("lock", "unlock"), ("alarm_control_panel", "alarm_disarm")])
def test_serrures_et_alarmes_refusees_par_la_securite_en_dur_elle_meme(domaine, service):
    """Même si une voie oublie la liste des domaines interdits, securite.verifier refuse."""
    assert securite.verifier(f"{domaine}.{service}", {"entity_id": f"{domaine}.x"})
    assert securite.verifier("homeassistant.turn_off", {"entity_id": [ENTITE, f"{domaine}.x"]})
    assert securite.verifier("light.turn_off", {"entity_id": ENTITE}) is None


def test_la_securite_ne_se_desserre_pas_par_le_point_de_controle():
    for corps in ({"floor_id": "rdc"}, {"label_id": "x"}, {"device_id": "d"}):
        r = acces.controler_service("light", "turn_on", dict(corps), services_permis={"turn_on"})
        assert r and r.genre == "securite", corps


def test_voie_llm_passe_par_le_controle():
    ha = faux_ha()
    for domaine, service, fragment in [("lock", "unlock", "domaine lock interdit"),
                                       ("light", "explose", "inexistant ou interdit"),
                                       ("light", "turn_on", "données")]:
        corps = {"entity_id": 7} if fragment == "données" else None
        res = ha.service(domaine, service, None, corps)
        assert fragment in res["erreur"], res
    assert "Services permis pour light" in ha.service("light", "explose", ENTITE)["erreur"]
    assert ha.client.posts == []  # rien n'est parti vers HA
    assert ha.service("light", "turn_on", ENTITE) == {"ok": True}
    assert len(ha.client.posts) == 1


def test_voie_dictionnaire_passe_par_le_controle():
    ha = faux_ha()
    a = faux_assistant(ha)
    a.dico = SimpleNamespace()
    for action in ({"service": "lock.unlock", "entity_id": "lock.porte"},
                   {"service": "light.turn_on", "entity_id": 12},
                   {"service": "light.turn_on", "entity_id": ENTITE, "floor_id": "rdc"},
                   {"service": "alarm_control_panel.alarm_disarm", "entity_id": "alarm_control_panel.x"}):
        with pytest.raises(A.RefusSecurite):
            a.executer(action)
    assert ha.client.posts == []


def test_voie_dictionnaire_garde_son_message_de_domaine():
    a = faux_assistant(faux_ha())
    with pytest.raises(A.RefusSecurite, match="le domaine shell_command est interdit"):
        a.executer({"service": "shell_command.x"})


def test_voie_appli_passe_par_le_controle():
    assert acces.verifier_requete_ha("POST", "/api/services/lock/unlock", {}) == "domaine lock interdit par la passerelle"
    assert acces.verifier_requete_ha("POST", "/api/services/light/turn_on", {"entity_id": 5})
    assert acces.verifier_requete_ha("POST", "/api/services/light/turn_on", ["x"])
    assert acces.verifier_requete_ha("POST", "/api/services/light/turn_on", {"entity_id": ENTITE, "label_id": "x"})
    assert acces.verifier_requete_ha("POST", "/api/services/light/turn_on", {"entity_id": ENTITE}) is None
    assert acces.verifier_requete_ha("POST", "/api/services/light/turn_on", None) is None
    assert acces.verifier_requete_ha("POST", "/api/services/media_player/join", {"entity_id": ENTITE}) is None
