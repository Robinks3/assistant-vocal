"""IA locale d'un PC en fournisseur optionnel du profil ha (0.53.0), avec repli sur Claude : adresse, sonde courte,
repli sans double action, journal sans adresse, choix du cerveau dans les capacités."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

import assistant as A
import llm_local as LL

URL = "http://ia.exemple.test:1234/v1"


def reponse_modeles(modele="modele-de-test"):
    return httpx.Response(200, json={"data": [{"id": modele}]})


# ------------------------------------------------------------ adresse
@pytest.mark.parametrize("brut, attendu", [
    ("", ""), ("   ", ""), (None, ""),
    ("http://ia.exemple.test:1234", URL),
    ("http://ia.exemple.test:1234/", URL),
    ("http://ia.exemple.test:1234/v1", URL),
    ("https://ia.exemple.test/v1/", "https://ia.exemple.test/v1"),
    ("ftp://ia.exemple.test/v1", ""),
    ("ia.exemple.test:1234", ""),
    ("http://", ""),
    ("http://utilisateur:secret@ia.exemple.test/v1", ""),
    ("http://ia.exemple.test/v1?cle=abc", ""),
    ("http://ia.exemple.test/v1#x", ""),
    ("http://ia.exemple.test:99999/v1", ""),
])
def test_url_valide(brut, attendu):
    assert LL.url_valide(brut) == attendu


def test_url_depuis_env(capsys):
    assert LL.url_depuis_env("pc", {"LLM_LOCAL_URL": URL}) == ""  # le PC n'utilise pas ce module
    assert LL.url_depuis_env("ha", {}) == ""
    assert LL.url_depuis_env("ha", {"LLM_LOCAL_URL": ""}) == ""
    assert capsys.readouterr().out == ""  # option vide : silence
    assert LL.url_depuis_env("ha", {"LLM_LOCAL_URL": URL}) == URL
    assert LL.url_depuis_env("ha", {"LLM_LOCAL_URL": "http://u:mdp-secret@ia.exemple.test/v1"}) == ""
    sortie = capsys.readouterr().out
    assert "llm_local_url ignorée" in sortie and "mdp-secret" not in sortie and "ia.exemple" not in sortie


# ------------------------------------------------------------ sonde
def sonde(reponse, horloge=None):
    vu = []

    def appel(requete):
        vu.append(requete)
        if isinstance(reponse, Exception):
            raise reponse
        return reponse(requete) if callable(reponse) else reponse
    kw = {"horloge": horloge} if horloge else {}
    return LL.Sonde(URL, transport=httpx.MockTransport(appel), **kw), vu


def test_sonde_joignable_et_modele():
    s, vu = sonde(reponse_modeles())
    assert s.verifier() is True and s.modele == "modele-de-test"
    assert vu[0].method == "GET" and str(vu[0].url) == URL + "/models"


@pytest.mark.parametrize("reponse", [
    httpx.Response(500), httpx.Response(404, json={}), httpx.Response(200, content=b"pas du json"),
    httpx.Response(200, json=["liste"]), httpx.ConnectError("refusée"), httpx.ConnectTimeout("lent"),
    httpx.ReadTimeout("lent"),
])
def test_sonde_injoignable(reponse):
    s, _ = sonde(reponse)
    assert s.verifier() is False


def test_sonde_delai_court_et_sans_environnement(monkeypatch):
    vus = []

    class Espion(httpx.Client):
        def __init__(self, **kw):
            vus.append(kw)
            super().__init__(**kw)
    monkeypatch.setattr(httpx, "Client", Espion)
    s, _ = sonde(reponse_modeles())
    s.verifier()
    assert vus[0]["trust_env"] is False and vus[0]["timeout"].connect == LL.DELAI_SONDE <= 2.0
    assert vus[0]["timeout"].read == LL.DELAI_SONDE


def test_sonde_cache_et_panne():
    t = [0.0]
    s, vu = sonde(reponse_modeles(), horloge=lambda: t[0])
    assert s.verifier() and s.verifier() and len(vu) == 1  # « oui » cru GARDE_JOIGNABLE secondes
    t[0] = LL.GARDE_JOIGNABLE + 1
    assert s.verifier() and len(vu) == 2
    s.signaler_panne()  # une demande vient d'échouer : on n'insiste pas tout de suite
    assert s.verifier() is False and len(vu) == 2
    t[0] += LL.GARDE_PANNE + 1
    assert s.verifier() is True and len(vu) == 3
    assert LL.GARDE_JOIGNABLE <= 60 and LL.GARDE_PANNE <= 60  # « quelques dizaines de secondes »


def test_sonde_injoignable_cache_court():
    t = [0.0]
    s, vu = sonde(httpx.ConnectError("refusée"), horloge=lambda: t[0])
    assert s.verifier() is False and s.verifier() is False and len(vu) == 1  # PC éteint : un seul essai
    t[0] = LL.GARDE_PANNE + 1
    assert s.verifier() is False and len(vu) == 2
    assert s.verifier(force=True) is False and len(vu) == 3


# ------------------------------------------------------------ repli sur Claude (cerveaux simulés)
class FauxCerveau:
    def __init__(self, nom, reponse=("ok", []), erreur=None, outils=0):
        self.nom, self.reponse, self.erreur, self.outils_appeles_apres = nom, reponse, erreur, outils
        self.historiques, self.cfg = {}, {}
        self.rappel_routine = self.rappel_liste = None
        self.dernieres_actions = []
        self.appels = 0
        self.outils_appeles = 0
        self.sans_cle = False

    def repondre(self, texte, mode="commande"):
        self.appels += 1
        self.outils_appeles = self.outils_appeles_apres
        if self.erreur:
            raise self.erreur
        return self.reponse


def faux_sonde(joignable=True, modele=""):
    s = LL.Sonde(URL, transport=httpx.MockTransport(
        lambda r: reponse_modeles(modele or "m") if joignable else httpx.Response(503)))
    return s


def cerveau(local, secours, sonde_=None):
    return LL.CerveauAvecRepli(local, secours, sonde_ or faux_sonde())


def test_pc_joignable_reponse_locale():
    local, secours = FauxCerveau("local", ("locale", [])), FauxCerveau("claude", ("claude", []))
    c = cerveau(local, secours)
    assert c.repondre("allume le salon") == ("locale", [])
    assert local.appels == 1 and secours.appels == 0 and c.dernier_nom == LL.CerveauAvecRepli.NOM_LOCAL


def test_pc_eteint_claude_repond_sans_essayer_le_local(capsys):
    local, secours = FauxCerveau("local"), FauxCerveau("claude", ("claude", []))
    c = cerveau(local, secours, faux_sonde(joignable=False))
    assert c.repondre("allume le salon") == ("claude", [])
    assert c.repondre("éteins le salon") == ("claude", [])
    assert local.appels == 0 and secours.appels == 2 and c.dernier_nom == LL.CerveauAvecRepli.NOM_SECOURS
    sortie = capsys.readouterr().out
    assert sortie.count("repli sur Claude") == 1  # signalé une fois, pas à chaque phrase
    assert "exemple.test" not in sortie and "1234" not in sortie


@pytest.mark.parametrize("erreur", [httpx.ConnectError("coupée"), httpx.ReadTimeout("lent"),
                                    httpx.HTTPStatusError("503", request=httpx.Request("POST", URL),
                                                          response=httpx.Response(503)),
                                    KeyError("choices"), ValueError("json")])
def test_local_tombe_en_route_repli_sur_claude(erreur, capsys):
    local, secours = FauxCerveau("local", erreur=erreur), FauxCerveau("claude", ("claude", []))
    sonde_ = faux_sonde()
    c = cerveau(local, secours, sonde_)
    assert c.repondre("allume le salon") == ("claude", [])
    assert local.appels == 1 and secours.appels == 1
    assert sonde_._joignable is False  # la sonde ne croit plus le dernier « oui »
    sortie = capsys.readouterr().out
    assert "repli sur Claude" in sortie and erreur.__class__.__name__ in sortie
    assert "exemple.test" not in sortie and "1234" not in sortie
    assert c.repondre("encore") == ("claude", []) and local.appels == 1  # pas de nouvel essai avant la garde


def test_local_de_nouveau_joignable(capsys):
    t = [0.0]
    local, secours = FauxCerveau("local", erreur=httpx.ConnectError("x")), FauxCerveau("claude", ("claude", []))
    s = LL.Sonde(URL, transport=httpx.MockTransport(lambda r: reponse_modeles()), horloge=lambda: t[0])
    c = cerveau(local, secours, s)
    c.repondre("a")
    local.erreur, local.reponse = None, ("locale", [])
    t[0] = LL.GARDE_PANNE + 1
    assert c.repondre("b") == ("locale", [])
    assert "de nouveau joignable" in capsys.readouterr().out


def test_pas_de_double_action_apres_un_outil():
    """Un outil déjà exécuté avant la panne : l'erreur remonte, Claude ne refait pas l'action."""
    local = FauxCerveau("local", erreur=httpx.ReadTimeout("lent"), outils=1)
    secours = FauxCerveau("claude", ("claude", []))
    c = cerveau(local, secours)
    with pytest.raises(httpx.ReadTimeout):
        c.repondre("allume le salon")
    assert secours.appels == 0


def test_pas_de_repli_sans_cle_claude():
    local = FauxCerveau("local", erreur=httpx.ReadTimeout("lent"))
    secours = FauxCerveau("claude")
    secours.sans_cle = True
    with pytest.raises(httpx.ReadTimeout):
        cerveau(local, secours).repondre("allume le salon")
    assert secours.appels == 0


def test_modele_annonce_par_le_serveur_est_utilise():
    local = FauxCerveau("local")
    c = cerveau(local, FauxCerveau("claude"), faux_sonde(modele="qwen-de-test"))
    c.repondre("a")
    assert local.cfg["llm_modele"] == "qwen-de-test"


def test_historiques_et_rappels_partages():
    local, secours = FauxCerveau("local"), FauxCerveau("claude")
    c = cerveau(local, secours)
    assert c.historiques is local.historiques and secours.historiques is local.historiques
    c.rappel_routine, c.rappel_liste = (lambda a, t: 1), (lambda: "x")
    assert local.rappel_routine is secours.rappel_routine is c.rappel_routine
    assert local.rappel_liste is secours.rappel_liste is c.rappel_liste


# ------------------------------------------------------------ cerveau local réel contre un serveur simulé
def serveur_llm(handler):
    vu = []

    def appel(requete):
        vu.append(requete)
        return handler(requete)
    return httpx.MockTransport(appel), vu


def test_cerveau_local_surveille_reponse_simple():
    def handler(requete):
        assert requete.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "Bonjour."}}]})
    transport, vu = serveur_llm(handler)
    c = LL.CerveauLocalSurveille({"llm_modele": "m", "llm_url": "http://autre"}, None, URL, transport=transport)
    reponse, actions = c.repondre("dis bonjour")
    assert reponse == "Bonjour." and actions == [] and c.outils_appeles == 0
    assert str(vu[0].url).startswith(URL)  # l'adresse de l'option, pas llm_url du PC


def test_cerveau_local_surveille_delais_courts_et_sans_environnement():
    c = LL.CerveauLocalSurveille({"llm_modele": "m", "llm_url": ""}, None, URL)
    assert c.client.timeout.read == LL.DELAI_REPONSE and c.client.timeout.connect == LL.DELAI_CONNEXION
    assert LL.DELAI_REPONSE < 60 and LL.DELAI_CONNEXION <= 2.0
    assert c.client.trust_env is False


def test_cerveau_local_surveille_compte_les_outils():
    c = LL.CerveauLocalSurveille({"llm_modele": "m"}, None, URL)
    c.outils_appeles = 0
    res = c.executer_outil("outil_inventé", {}, "texte", set(), [], [])
    assert c.outils_appeles == 1 and res  # refusé par l'aiguillage fermé, mais compté
    transport, _ = serveur_llm(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}))
    c2 = LL.CerveauLocalSurveille({"llm_modele": "m"}, None, URL, transport=transport)
    c2.outils_appeles = 5
    c2.repondre("x")
    assert c2.outils_appeles == 0  # remis à zéro à chaque demande


def test_repli_de_bout_en_bout_serveur_lent():
    """Serveur simulé qui répond à la sonde puis dépasse le délai : la demande est refaite sur Claude."""
    def handler(requete):
        if requete.url.path.endswith("/models"):
            return reponse_modeles()
        raise httpx.ReadTimeout("trop lent")
    transport, _ = serveur_llm(handler)
    local = LL.CerveauLocalSurveille({"llm_modele": "m"}, None, URL, transport=transport)
    s = LL.Sonde(URL, transport=transport)
    secours = FauxCerveau("claude", ("claude", []))
    c = LL.CerveauAvecRepli(local, secours, s)
    assert c.repondre("dis bonjour") == ("claude", []) and secours.appels == 1


def test_repli_de_bout_en_bout_serveur_injoignable():
    transport, _ = serveur_llm(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refusée")))
    local = LL.CerveauLocalSurveille({"llm_modele": "m"}, None, URL, transport=transport)
    secours = FauxCerveau("claude", ("claude", []))
    c = LL.CerveauAvecRepli(local, secours, LL.Sonde(URL, transport=transport))
    assert c.repondre("dis bonjour") == ("claude", []) and secours.appels == 1


# ------------------------------------------------------------ moteur : capacités et choix du cerveau
def moteur(profil, llm_local_url=""):
    import serveur_satellite as S
    m = object.__new__(S.Moteur)
    m.profil, m.llm_local_url = profil, llm_local_url
    m.cerveau_actif, m.cerveau_pret, m.cerveau_message = "claude", True, ""
    m.cfg = {"claude_modele": "claude-haiku-5-5", "llm_modele": "m", "llm_url": "http://127.0.0.1:8080/v1"}
    m.assistant = SimpleNamespace(ha=None, cerveau=None, creer_routine=lambda a, t: "routine",
                                  liste_routines_llm=lambda: " liste")
    m.vision, m.empreinte_tls = None, ""
    m.sante = m.sante_hist = None
    m.sante_personnes = frozenset()
    m.diffuses = []

    async def diffuser(message):
        m.diffuses.append(message)
    m.diffuser = diffuser
    m.etat_cerveau = lambda: {"etat": "cerveau", "actif": m.cerveau_actif, "message": m.cerveau_message}
    return m


def test_capacites_cerveau():
    assert moteur("ha").capacites()["cerveau"] == ["claude"]  # option vide : comme avant
    assert moteur("ha", URL).capacites()["cerveau"] == ["claude", "local"]
    assert moteur("pc").capacites()["cerveau"] == ["claude", "local"]  # le PC ne change pas


def test_bascule_ha_vers_local_pc_allume(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
    monkeypatch.setattr(LL.Sonde, "_sonder", lambda self: True)
    m = moteur("ha", URL)

    async def scenario():
        m.verrou = asyncio.Lock()
        await m.changer_cerveau("local")
    asyncio.run(scenario())
    assert m.cerveau_actif == "local" and m.cerveau_pret
    assert isinstance(m.assistant.cerveau, LL.CerveauAvecRepli)
    assert URL not in m.cerveau_message and "exemple" not in m.cerveau_message
    # Correctif préexistant : le nouveau cerveau reçoit les rappels de routine posés par l'assistant.
    assert m.assistant.cerveau.rappel_routine is m.assistant.creer_routine
    assert m.assistant.cerveau.rappel_liste is m.assistant.liste_routines_llm


def test_bascule_ha_vers_local_pc_eteint_reste_sur_claude(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
    monkeypatch.setattr(LL.Sonde, "_sonder", lambda self: False)
    m = moteur("ha", URL)

    async def scenario():
        m.verrou = asyncio.Lock()
        await m.changer_cerveau("local")
    asyncio.run(scenario())
    assert m.cerveau_actif == "claude" and m.cerveau_pret
    assert isinstance(m.assistant.cerveau, A.CerveauClaude)
    assert "injoignable" in m.cerveau_message and "exemple" not in m.cerveau_message
    assert "exemple" not in capsys.readouterr().out
    assert m.assistant.cerveau.rappel_routine is m.assistant.creer_routine


def test_bascule_ha_local_inconnu_sans_option_refusee(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
    m = moteur("ha")

    async def scenario():
        m.verrou = asyncio.Lock()
        await m.changer_cerveau("local")
    asyncio.run(scenario())
    assert m.cerveau_actif == "claude" and m.assistant.cerveau is None  # rien n'a bougé


def test_retour_sur_claude_en_ha_sans_arreter_de_serveur(monkeypatch):
    import serveur_satellite as S
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")

    def interdit():
        raise AssertionError("le profil ha n'arrête aucun llama-server")
    monkeypatch.setattr(S, "arreter_llm_local", interdit)
    monkeypatch.setattr(S, "demarrer_llm_local", interdit)
    m = moteur("ha", URL)
    m.cerveau_actif = "local"

    async def scenario():
        m.verrou = asyncio.Lock()
        await m.changer_cerveau("claude")
    asyncio.run(scenario())
    assert m.cerveau_actif == "claude" and isinstance(m.assistant.cerveau, A.CerveauClaude)
    assert m.cerveau_message == "Claude en ligne"
