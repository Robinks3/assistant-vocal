"""Lot 0 des routines (0.28.0) : aiguillage fermé des outils du LLM, essai et personne portés par la requête,
historique et leçon par appareil, domaines interdits sur toutes les voies."""
import asyncio
import json
from types import SimpleNamespace

import pytest

import acces
import assistant as A

ENTITE = "light.essai"


class ClientEnregistreur:
    """Faux client httpx de Home Assistant : note chaque POST, répond un état allumé à chaque GET."""

    def __init__(self):
        self.posts = []

    def post(self, url, json=None):
        self.posts.append((url, json))
        return SimpleNamespace(status_code=200, text="", json=lambda: [])

    def get(self, url):
        return SimpleNamespace(status_code=200, text="", json=lambda: {"entity_id": ENTITE, "state": "on",
                                                                       "attributes": {}})


def faux_ha(monkeypatch):
    ha = A.HomeAssistant.__new__(A.HomeAssistant)
    ha.url, ha.client, ha.essai, ha.personne, ha.vue_llm = "http://ha", ClientEnregistreur(), False, None, {}
    ha.entites_llm = {ENTITE}
    ha.confirmer = lambda *a, **k: []
    monkeypatch.setattr(ha, "inventaire", lambda: (f"{ENTITE} : salon", f"{ENTITE} éteinte"), raising=False)
    return ha


class FauxQwen:
    """llama-server simulé : la première réponse appelle les outils donnés, la seconde conclut."""

    def __init__(self, appels):
        self.appels, self.corps = appels, []

    def post(self, url, json=None):
        self.corps.append(json)
        if len(self.corps) == 1:
            calls = [{"id": f"a{i}", "type": "function",
                      "function": {"name": nom, "arguments": __import__("json").dumps(args)}}
                     for i, (nom, args) in enumerate(self.appels)]
            msg = {"content": "", "tool_calls": calls}
        else:
            msg = {"content": "Voilà."}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"message": msg}]})


def cerveau_qwen(ha, appels):
    c = A.Cerveau({"llm_modele": "qwen", "llm_url": "http://llm"}, ha)
    c.client = FauxQwen(appels)
    return c


APPEL_SALON = ("appeler_service", {"domaine": "light", "service": "turn_on", "entity_id": ENTITE})


@pytest.fixture
def mode_lecture(monkeypatch):
    """Un mode sans action, comme le sera « proposer » des routines (lot 1)."""
    monkeypatch.setitem(A.MODES_OUTILS, "lecture", ("lire_etat",))


@pytest.mark.parametrize("appel", [APPEL_SALON, ("jouer_musique", {"recherche": "daft punk"})])
def test_qwen_outil_hors_liste_sans_post(monkeypatch, mode_lecture, appel):
    ha = faux_ha(monkeypatch)
    c = cerveau_qwen(ha, [appel])
    reponse, actions = c.repondre("allume le salon", mode="lecture")
    assert ha.client.posts == [] and actions == [] and c.dernieres_actions == []
    assert [nom_outil["function"]["name"] for nom_outil in c.client.corps[0]["tools"]] == ["lire_etat"]
    retour = [m for m in c.client.corps[1]["messages"] if m["role"] == "tool"]
    assert json.loads(retour[0]["content"]) == A.INDISPONIBLE


def test_qwen_nom_invente_ou_arguments_illisibles(monkeypatch):
    ha = faux_ha(monkeypatch)
    c = cerveau_qwen(ha, [("executer_script", {"script": "x"})])
    c.repondre("lance le script")
    assert ha.client.posts == []
    retour = [m for m in c.client.corps[1]["messages"] if m["role"] == "tool"]
    assert json.loads(retour[0]["content"]) == A.INDISPONIBLE
    ha2 = faux_ha(monkeypatch)
    c2 = A.Cerveau({"llm_modele": "qwen", "llm_url": "http://llm"}, ha2)
    c2.client = FauxQwen([])

    def post(url, json=None):
        c2.client.corps.append(json)
        if len(c2.client.corps) == 1:
            msg = {"content": "", "tool_calls": [{"id": "a", "type": "function",
                                                  "function": {"name": "appeler_service", "arguments": "{pas du json"}}]}
        else:
            msg = {"content": "Voilà."}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"message": msg}]})
    c2.client.post = post
    c2.repondre("allume le salon")
    assert ha2.client.posts == []


def test_qwen_outil_de_la_liste_agit(monkeypatch):
    ha = faux_ha(monkeypatch)
    c = cerveau_qwen(ha, [APPEL_SALON])
    _, actions = c.repondre("allume le salon")
    assert [p[0] for p in ha.client.posts] == ["http://ha/api/services/light/turn_on"]
    assert actions and c.dernieres_actions


class FauxClaude:
    """SDK Anthropic simulé : un appel d'outil, puis une réponse texte."""

    def __init__(self, appels):
        self.appels, self.demandes = appels, []
        self.messages = self

    def create(self, **k):
        self.demandes.append(k)
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0)
        if len(self.demandes) == 1:
            blocs = [SimpleNamespace(type="tool_use", id=f"t{i}", name=nom, input=args)
                     for i, (nom, args) in enumerate(self.appels)]
            return SimpleNamespace(stop_reason="tool_use", content=blocs, usage=usage)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Voilà.")],
                               usage=usage)


@pytest.mark.parametrize("appel", [APPEL_SALON, ("jouer_musique", {"recherche": "daft punk"}),
                                   ("executer_script", {})])
def test_claude_outil_hors_liste_sans_post(monkeypatch, mode_lecture, appel):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
    ha = faux_ha(monkeypatch)
    c = A.CerveauClaude({"claude_modele": "claude-haiku-5-5"}, ha)
    c.client = FauxClaude([appel])
    _, actions = c.repondre("allume le salon", mode="lecture")
    assert ha.client.posts == [] and actions == []
    assert [o["name"] for o in c.client.demandes[0]["tools"]] == ["lire_etat"]
    # Liste gardée en cache par mode : même objet au tour suivant, l'en-tête reste en cache chez Anthropic.
    c.client = FauxClaude([])
    c.repondre("et la cuisine", mode="lecture")
    assert c.client.demandes[0]["tools"] is c.outils["lecture"][1]


def test_domaine_interdit_sur_toutes_les_voies(monkeypatch):
    ha = faux_ha(monkeypatch)
    assert "interdit" in ha.service("lock", "unlock", "lock.porte")["erreur"]
    assistant = object.__new__(A.Assistant)
    assistant.ha = ha
    with pytest.raises(A.RefusSecurite):
        assistant.executer({"service": "lock.unlock", "entity_id": "lock.porte"})
    assert ha.client.posts == []
    assert "lock" in acces.DOMAINES_INTERDITS


def test_service_sans_confirmation(monkeypatch):
    ha = faux_ha(monkeypatch)
    ha.confirmer = lambda *a, **k: pytest.fail("confirmer=False ne doit pas attendre l'état")
    assert ha.service("light", "turn_on", ENTITE, confirmer=False) == {"ok": True}


def test_requete_ne_touche_pas_aux_objets_partages(monkeypatch):
    ha = faux_ha(monkeypatch)
    assistant = object.__new__(A.Assistant)
    assistant.ha, assistant.essai = ha, False
    assistant.indication = lambda p: f" parle : {p}." if p else ""
    with assistant.requete(essai=True, personne="sacha", appareil="tab"):
        assert assistant.essai and ha.essai and ha.personne == "sacha"
        assert A.Cerveau.cle_conversation() == ("sacha", "tab")
        assert ha.service("light", "turn_on", ENTITE) == {"ok": True} and ha.client.posts == []
    assert not assistant.essai and not ha.essai and ha.personne is None
    assert A.Cerveau.cle_conversation() == (None, None)


def test_historique_par_appareil(monkeypatch):
    ha = faux_ha(monkeypatch)
    c = cerveau_qwen(ha, [])
    assistant = object.__new__(A.Assistant)
    assistant.essai = False
    assistant.indication = lambda p: ""
    with assistant.requete(personne="sacha", appareil="tab"):
        c.repondre("allume le salon")
        assert len(c.historique) == 2
    with assistant.requete(personne="sacha", appareil="téléphone"):
        assert c.historique == []
    with assistant.requete(personne="camille", appareil="tab"):
        assert c.historique == []


def test_lecon_annulee_seulement_sur_son_appareil(monkeypatch):
    oublis = []
    monkeypatch.setattr(A, "journaliser", lambda *a: None)
    assistant = object.__new__(A.Assistant)
    assistant.essai, assistant.voix, assistant.ha = False, None, None
    assistant.indication = lambda p: ""
    assistant.dico = SimpleNamespace(oublier=lambda t: oublis.append(t) or True, chercher=lambda t: None,
                                     personnes=None)
    assistant.lecons = {"tab": ("allume la véranda", A.time.time())}
    assistant.cerveau = SimpleNamespace(repondre=lambda *a, **k: ("Je ne sais pas.", []))
    assistant.ha = SimpleNamespace(conversation=lambda t: None)
    assistant.traiter("non", appareil="téléphone")
    assert oublis == [] and "tab" in assistant.lecons
    parole = assistant.traiter("non", appareil="tab")
    assert oublis == ["allume la véranda"] and "oublie" in parole and "tab" not in assistant.lecons


def test_essai_effectif_du_serveur(monkeypatch):
    """Un téléphone en réel ne lève pas l'essai du serveur, un téléphone en essai l'impose."""
    import serveur_satellite as S
    vus = []
    moteur = object.__new__(S.Moteur)
    moteur.cerveau_actif = "local"
    ha = faux_ha(monkeypatch)
    assistant = object.__new__(A.Assistant)
    assistant.ha, assistant.essai = ha, False
    assistant.indication = lambda p: ""
    assistant.apprendre = lambda *a: None

    def repondre(texte, mode="commande"):
        r = A.REQUETE.get()
        vus.append((r.essai, r.personne, r.appareil, ha.essai))
        return "ok", []
    assistant.cerveau = SimpleNamespace(repondre=repondre)
    moteur.assistant = assistant
    monkeypatch.setattr(A, "journaliser", lambda *a: None)
    for serveur, telephone in [(True, False), (False, True), (False, False)]:
        moteur.essai = serveur
        res = moteur.llm_texte("allume le salon", telephone, "sacha", "tab")
        assert res["essai"] is (serveur or telephone)
    assert vus == [(True, "sacha", "tab", True), (True, "sacha", "tab", True), (False, "sacha", "tab", False)]
    assert not ha.essai and assistant.essai is False


def test_identite_transmise_par_repondre_llm(monkeypatch):
    import serveur_satellite as S
    recus = []

    class Moteur:
        verrou = None
        essai = False

        def llm_texte(self, *a):
            recus.append(a)
            return {"reponse": "ok", "actions": [], "cerveau": "x", "ms": 0, "erreur": "", "essai": False}

        async def diffuser(self, m):
            pass
    sat = object.__new__(S.Satellite)
    sat.moteur, sat.nom, sat.identite = Moteur(), "tablette", "appareil:a1"
    envoyes = []

    async def envoyer(**m):
        envoyes.append(m)
    sat.envoyer = envoyer
    monkeypatch.setattr(S, "lire_journal", lambda n: [])

    async def scenario():
        sat.moteur.verrou = asyncio.Lock()
        await sat.repondre_llm({"texte": "allume le salon", "essai": False, "personne": "sacha"})
    asyncio.run(scenario())
    assert recus == [("allume le salon", False, "sacha", "appareil:a1")]
    # Un jeton fixe de poc/.env partagé : le nom de l'appareil sépare les historiques.
    sat.identite = "sacha"
    assert sat.cle_appareil() == "sacha/tablette"


def test_essai_du_serveur_est_un_plancher(monkeypatch):
    ha = faux_ha(monkeypatch)
    ha.essai = True
    assistant = object.__new__(A.Assistant)
    assistant.ha, assistant.essai = ha, False
    assistant.indication = lambda p: ""
    with assistant.requete(essai=False):
        assert ha.essai
        ha.service("light", "turn_on", ENTITE)
    assert ha.client.posts == []
