"""Boucle d'appel d'outils du LLM (S-D6, 0.43.1) : non régression des deux chemins.

Le serveur local parle le format OpenAI (`tool_calls`), Claude le format Anthropic (`tool_use`). Les deux suivent la
même logique : au plus six tours, exécution des outils par l'aiguillage fermé (`executer_outil`), parole fixée par
le serveur qui arrête le tour, phrase de repli à la sixième réponse sans conclusion, journal des actions. Ces tests
décrivent ce comportement par ses effets (messages envoyés au LLM, actions, appels à Home Assistant, historique),
sans rien supposer du découpage interne, pour qu'ils passent avant et après l'extraction de la logique commune."""
import copy
import json
from types import SimpleNamespace

import pytest

import assistant as A

ENTITE = "light.essai"
APPEL_SALON = ("appeler_service", {"domaine": "light", "service": "turn_on", "entity_id": ENTITE})
APPEL_ETAT = ("lire_etat", {"entity_id": ENTITE})
ABANDON = "Je n'ai pas réussi à terminer cette demande."


class ClientHA:
    """Faux client httpx de Home Assistant : note chaque POST, répond un état allumé à chaque GET."""

    def __init__(self):
        self.posts = []

    def post(self, url, json=None):
        self.posts.append((url, json))
        return SimpleNamespace(status_code=200, text="", json=lambda: [])

    def get(self, url):
        return SimpleNamespace(status_code=200, text="", raise_for_status=lambda: None,
                               json=lambda: {"entity_id": ENTITE, "state": "on", "attributes": {}})


def faux_ha(monkeypatch):
    ha = A.HomeAssistant.__new__(A.HomeAssistant)
    ha.url, ha.client, ha.essai, ha.vue_llm = "http://ha", ClientHA(), False, {}
    ha.entites_llm = {ENTITE}
    ha.confirmer = lambda *a, **k: []
    monkeypatch.setattr(ha, "inventaire", lambda: (f"{ENTITE} : salon", f"{ENTITE} éteinte"), raising=False)
    return ha


class FauxOpenAI:
    """llama-server simulé. `tours` : liste de ("outils", [(nom, args)]) ou ("texte", contenu). Le dernier tour se
    répète tant qu'on rappelle le serveur. Les messages reçus sont copiés à l'arrivée, avant que la boucle les complète."""

    def __init__(self, tours):
        self.tours, self.recus, self.corps = tours, [], []

    def post(self, url, json=None):
        rang = min(len(self.corps), len(self.tours) - 1)
        self.corps.append(copy.deepcopy(json))
        self.recus.append(copy.deepcopy(json["messages"]))
        genre, contenu = self.tours[rang]
        if genre == "outils":
            appels = [{"id": f"a{i}", "type": "function",
                       "function": {"name": nom, "arguments": args if isinstance(args, str) else __import__("json").dumps(args)}}
                      for i, (nom, args) in enumerate(contenu)]
            msg = {"content": "", "tool_calls": appels}
        else:
            msg = {"content": contenu}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"message": msg}]})


class FauxAnthropic:
    """SDK Anthropic simulé. `tours` : ("outils", [(nom, entrée)]), ("texte", contenu) ou ("refus", None)."""

    def __init__(self, tours):
        self.tours, self.recus, self.demandes = tours, [], []
        self.messages = self  # client.messages.create(...)

    def create(self, **k):
        rang = min(len(self.demandes), len(self.tours) - 1)
        self.demandes.append({c: v for c, v in k.items() if c != "messages"})
        self.recus.append(copy.deepcopy(k["messages"]))
        usage = SimpleNamespace(input_tokens=3, output_tokens=2, cache_read_input_tokens=1)
        genre, contenu = self.tours[rang]
        if genre == "refus":
            return SimpleNamespace(stop_reason="refusal", content=[], usage=usage)
        if genre == "outils":
            blocs = [SimpleNamespace(type="tool_use", id=f"t{i}", name=nom, input=entree)
                     for i, (nom, entree) in enumerate(contenu)]
            return SimpleNamespace(stop_reason="tool_use", content=blocs, usage=usage)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=contenu)],
                               usage=usage)


def monter(monkeypatch, chemin, tours):
    """Cerveau du chemin demandé (openai ou anthropic), son faux client et le faux Home Assistant."""
    ha = faux_ha(monkeypatch)
    if chemin == "openai":
        c = A.Cerveau({"llm_modele": "qwen", "llm_url": "http://llm"}, ha)
        c.client = FauxOpenAI(tours)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
        c = A.CerveauClaude({"claude_modele": "claude-haiku-5-5"}, ha)
        c.client = FauxAnthropic(tours)
    return c, ha


def appels(c):
    """Nombre d'appels faits au LLM."""
    return len(c.client.recus)


def roles(messages):
    return [m["role"] for m in messages]


def retours_outils(c, rang):
    """Résultats d'outils renvoyés au LLM à l'appel numéro `rang`, sous forme (identifiant, contenu décodé, erreur)."""
    messages = c.client.recus[rang]
    if isinstance(c, A.CerveauClaude):
        blocs = messages[-1]["content"]
        return [(b["tool_use_id"], json.loads(b["content"]), b.get("is_error", False)) for b in blocs]
    sortie = [m for m in messages if m["role"] == "tool"]
    return [(m["tool_call_id"], json.loads(m["content"]), False) for m in sortie]


def assistant_requete(ha=None):
    """Assistant minimal pour ouvrir une requête qui porte l'identité de l'appareil (historique par appareil)."""
    assistant = object.__new__(A.Assistant)
    assistant.essai = False
    assistant.indication = lambda p: ""
    assistant.ha = ha
    return assistant


CHEMINS = pytest.mark.parametrize("chemin", ["openai", "anthropic"])


@CHEMINS
def test_un_outil_puis_la_reponse_finale(monkeypatch, chemin):
    c, ha = monter(monkeypatch, chemin, [("outils", [APPEL_SALON]), ("texte", "Voilà.")])
    with assistant_requete().requete(personne="sacha", appareil="tab"):
        reponse, actions = c.repondre("allume le salon")
        assert len(c.historique) == 2  # la demande et la réponse sont gardées pour la suite de la conversation
        assert c.historique[-1] == {"role": "assistant", "content": "Voilà."}
    assert reponse == "Voilà." and appels(c) == 2
    assert actions == ["light.turn_on light.essai"]
    assert [p[0] for p in ha.client.posts] == ["http://ha/api/services/light/turn_on"]
    assert c.dernieres_actions == [{"service": "light.turn_on", "entity_id": ENTITE}]
    # Ordre des messages au second appel : la demande, l'appel d'outil du LLM, puis le résultat de l'outil.
    if chemin == "openai":
        assert roles(c.client.recus[0]) == ["system", "user"]
        assert roles(c.client.recus[1]) == ["system", "user", "assistant", "tool"]
        assistant_msg = c.client.recus[1][2]
        assert assistant_msg["content"] == "" and assistant_msg["tool_calls"][0]["id"] == "a0"
        assert c.client.recus[1][3]["tool_call_id"] == "a0"
    else:
        assert roles(c.client.recus[0]) == ["user"]
        assert roles(c.client.recus[1]) == ["user", "assistant", "user"]
        assert c.client.recus[1][1]["content"][0].id == "t0"
        assert c.client.recus[1][2]["content"][0]["type"] == "tool_result"
    assert retours_outils(c, 1) == [("a0" if chemin == "openai" else "t0", {"ok": True}, False)]


@CHEMINS
def test_plusieurs_outils_dans_un_tour_gardent_leur_ordre(monkeypatch, chemin):
    c, ha = monter(monkeypatch, chemin, [("outils", [APPEL_SALON, APPEL_ETAT]), ("texte", "Fait.")])
    reponse, actions = c.repondre("allume le salon")
    assert reponse == "Fait." and appels(c) == 2
    identifiants = [r[0] for r in retours_outils(c, 1)]
    assert identifiants == (["a0", "a1"] if chemin == "openai" else ["t0", "t1"])
    assert retours_outils(c, 1)[0][1] == {"ok": True}
    assert retours_outils(c, 1)[1][1]["etat"] == "on"
    assert actions == ["light.turn_on light.essai"]  # lire_etat ne laisse aucune ligne de journal


@CHEMINS
def test_limite_de_six_tours(monkeypatch, chemin):
    c, ha = monter(monkeypatch, chemin, [("outils", [APPEL_ETAT])])
    with assistant_requete().requete(personne="sacha", appareil="tab"):
        reponse, actions = c.repondre("où en est le salon")
        assert c.historique[-1] == {"role": "assistant", "content": ABANDON}
    assert reponse == ABANDON and actions == []
    assert appels(c) == 6
    # Dernier appel : la demande plus cinq allers-retours (assistant, puis résultats).
    attendu = 12 if chemin == "openai" else 11
    assert len(c.client.recus[5]) == attendu
    assert ha.client.posts == []


@CHEMINS
def test_refus_de_securite_sur_un_domaine_interdit(monkeypatch, chemin):
    porte = ("appeler_service", {"domaine": "lock", "service": "unlock", "entity_id": "lock.porte"})
    c, ha = monter(monkeypatch, chemin, [("outils", [porte]), ("texte", "Je ne peux pas.")])
    reponse, actions = c.repondre("ouvre la porte")
    assert reponse == "Je ne peux pas." and appels(c) == 2
    assert ha.client.posts == []
    assert c.dernieres_actions == []
    (identifiant, resultat, erreur), = retours_outils(c, 1)
    assert "erreur" in resultat
    assert erreur is (chemin == "anthropic")  # Claude reçoit is_error, le serveur local n'a pas ce champ
    assert all("lock" not in a or "refusé" in a for a in actions)


@CHEMINS
def test_volume_non_demande_refuse_avant_home_assistant(monkeypatch, chemin):
    volume = ("appeler_service", {"domaine": "light", "service": "volume_set", "entity_id": ENTITE,
                                   "donnees": {"volume_level": 1}})
    c, ha = monter(monkeypatch, chemin, [("outils", [volume]), ("texte", "Non.")])
    reponse, actions = c.repondre("allume le salon")
    assert reponse == "Non." and ha.client.posts == [] and actions == []
    (_, resultat, erreur), = retours_outils(c, 1)
    assert resultat == {"erreur": "volume non demandé dans la phrase, n'y touche pas"}
    assert erreur is (chemin == "anthropic")


@CHEMINS
def test_outil_inconnu_recoit_indisponible(monkeypatch, chemin):
    c, ha = monter(monkeypatch, chemin, [("outils", [("executer_script", {"script": "x"})]), ("texte", "Non.")])
    c.repondre("lance le script")
    (_, resultat, erreur), = retours_outils(c, 1)
    assert resultat == A.INDISPONIBLE and ha.client.posts == []
    assert erreur is (chemin == "anthropic")


@CHEMINS
def test_parole_fixee_arrete_le_tour(monkeypatch, chemin):
    c, ha = monter(monkeypatch, chemin, [("outils", [("proposer_routine", {"nom": "essai"})]),
                                         ("texte", "Ne doit pas servir.")])
    recus = []
    c.rappel_routine = lambda args, texte: recus.append((args, texte)) or {"ok": True, "parole": "Je crée la routine ?"}
    with assistant_requete().requete(personne="sacha", appareil="tab"):
        reponse, actions = c.repondre("propose une routine", mode="proposer")
        assert c.historique == []  # mode isolé : la conversation en cours n'est pas touchée
    assert reponse == "Je crée la routine ?"
    assert appels(c) == 1  # le tour s'arrête sans redemander au LLM
    assert recus == [({"nom": "essai"}, "propose une routine")]
    assert actions == []


@CHEMINS
def test_mode_isole_ne_touche_pas_a_l_historique(monkeypatch, chemin):
    c, ha = monter(monkeypatch, chemin, [("outils", [APPEL_ETAT]), ("texte", "Allumée.")])
    with assistant_requete().requete(personne="sacha", appareil="tab"):
        reponse, actions = c.repondre("elle est allumée ?", mode="question")
        assert c.historique == []
    assert reponse == "Allumée." and appels(c) == 2


@CHEMINS
def test_historique_garde_la_reponse_finale_une_fois(monkeypatch, chemin):
    c, ha = monter(monkeypatch, chemin, [("texte", "Bonjour.")])
    with assistant_requete().requete(personne="sacha", appareil="tab"):
        c.repondre("bonjour")
        assert c.historique[0] == {"role": "user", "content": "bonjour"}
        assert c.historique[1] == {"role": "assistant", "content": "Bonjour."}
        c.repondre("encore")
        assert len(c.historique) == 4
    # La conversation précédente précède la nouvelle demande au second appel.
    premier = 1 if chemin == "openai" else 0  # openai : un message système en tête
    assert c.client.recus[1][premier]["content"] == "bonjour"
    assert c.client.recus[1][premier + 1]["content"] == "Bonjour."


def test_reponse_vide_openai_garde_une_chaine_vide(monkeypatch):
    c, ha = monter(monkeypatch, "openai", [("texte", "")])
    with assistant_requete().requete(personne="sacha", appareil="tab"):
        assert c.repondre("bonjour")[0] == ""
        assert c.historique[-1] == {"role": "assistant", "content": ""}


def test_reponse_vide_claude_garde_trois_points(monkeypatch):
    c, ha = monter(monkeypatch, "anthropic", [("texte", "")])
    with assistant_requete().requete(personne="sacha", appareil="tab"):
        assert c.repondre("bonjour")[0] == ""
        assert c.historique[-1] == {"role": "assistant", "content": "..."}  # l'API refuse un message vide


def test_arguments_illisibles_openai(monkeypatch):
    c, ha = monter(monkeypatch, "openai", [("outils", [("appeler_service", "{pas du json")]), ("texte", "Voilà.")])
    c.repondre("allume le salon")
    assert retours_outils(c, 1) == [("a0", {"erreur": "arguments illisibles"}, False)]
    assert ha.client.posts == []


def test_arguments_openai_qui_ne_sont_pas_un_objet(monkeypatch):
    c, ha = monter(monkeypatch, "openai", [("outils", [("appeler_service", "[1, 2]")]), ("texte", "Voilà.")])
    c.repondre("allume le salon")
    assert retours_outils(c, 1) == [("a0", {"erreur": "arguments illisibles"}, False)]


def test_entree_claude_vide_ne_part_pas(monkeypatch):
    c, ha = monter(monkeypatch, "anthropic", [("outils", [("appeler_service", None)]), ("texte", "Voilà.")])
    c.repondre("allume le salon")
    (_, resultat, erreur), = retours_outils(c, 1)
    assert "erreur" in resultat and erreur is True and ha.client.posts == []


def test_relance_openai_apres_une_annonce_sans_outil(monkeypatch):
    c, ha = monter(monkeypatch, "openai", [("texte", "Je vais allumer le salon."), ("texte", "Voilà.")])
    reponse, actions = c.repondre("allume le salon")
    assert reponse == "Voilà." and appels(c) == 2
    avant, apres = c.client.recus
    assert roles(apres) == roles(avant) + ["assistant", "user"]
    assert apres[-2] == {"role": "assistant", "content": "Je vais allumer le salon."}
    assert apres[-1]["content"].startswith("Tu n'as appelé aucun outil, donc rien n'a été fait.")
    assert "États actuels" not in apres[-1]["content"] and f"{ENTITE} éteinte" in apres[-1]["content"]


def test_relance_openai_une_seule_fois(monkeypatch):
    c, ha = monter(monkeypatch, "openai", [("texte", "Je vais allumer le salon.")])
    reponse, actions = c.repondre("allume le salon")
    assert reponse == "Je vais allumer le salon." and appels(c) == 2  # la seconde annonce est rendue telle quelle


def test_pas_de_relance_quand_une_action_a_eu_lieu(monkeypatch):
    c, ha = monter(monkeypatch, "openai", [("outils", [APPEL_SALON]), ("texte", "J'ai allumé le salon.")])
    reponse, actions = c.repondre("allume le salon")
    assert reponse == "J'ai allumé le salon." and appels(c) == 2 and len(actions) == 1


def test_pas_de_relance_hors_du_mode_commande(monkeypatch):
    c, ha = monter(monkeypatch, "openai", [("texte", "Je vais regarder.")])
    reponse, actions = c.repondre("elle est allumée ?", mode="question")
    assert reponse == "Je vais regarder." and appels(c) == 1


def test_claude_ne_relance_pas(monkeypatch):
    c, ha = monter(monkeypatch, "anthropic", [("texte", "Je vais allumer le salon.")])
    reponse, actions = c.repondre("allume le salon")
    assert reponse == "Je vais allumer le salon." and appels(c) == 1


def test_claude_refus_du_modele(monkeypatch):
    c, ha = monter(monkeypatch, "anthropic", [("refus", None)])
    with assistant_requete().requete(personne="sacha", appareil="tab"):
        reponse, actions = c.repondre("bonjour")
        assert c.historique[-1] == {"role": "assistant", "content": "Je ne peux pas traiter cette demande."}
    assert reponse == "Je ne peux pas traiter cette demande." and actions == [] and appels(c) == 1


def test_claude_mesure_chaque_appel(monkeypatch):
    c, ha = monter(monkeypatch, "anthropic", [("outils", [APPEL_ETAT]), ("texte", "Oui.")])
    c.repondre("elle est allumée ?")
    assert len(c.mesures) == 2
    assert all(m[1:] == (3, 1, 2) for m in c.mesures)


def test_openai_demande_les_outils_du_mode_a_chaque_tour(monkeypatch):
    c, ha = monter(monkeypatch, "openai", [("outils", [APPEL_ETAT]), ("texte", "Oui.")])
    c.repondre("elle est allumée ?", mode="question")
    for corps in c.client.corps:
        assert [o["function"]["name"] for o in corps["tools"]] == ["lire_etat"]
        assert corps["model"] == "qwen" and corps["temperature"] == 0 and corps["max_tokens"] == 300


def test_claude_demande_les_outils_du_mode_a_chaque_tour(monkeypatch):
    c, ha = monter(monkeypatch, "anthropic", [("outils", [APPEL_ETAT]), ("texte", "Oui.")])
    c.repondre("elle est allumée ?", mode="question")
    for demande in c.client.demandes:
        assert [o["name"] for o in demande["tools"]] == ["lire_etat"]
        assert demande["model"] == "claude-haiku-5-5" and demande["max_tokens"] == 1024
        assert demande["thinking"] == {"type": "disabled"}


@CHEMINS
def test_annonce_de_musique_non_confirmee_remplacee(monkeypatch, chemin):
    """Le garde-fou de musique s'applique à la réponse finale des deux chemins, y compris après la limite de tours."""
    c, ha = monter(monkeypatch, chemin, [("outils", [("jouer_musique", {"recherche": "essai"})]),
                                         ("texte", "C'est parti, ça joue.")])
    ha.musique = lambda *a, **k: {"erreur": "introuvable"}
    ha.ENCEINTES_MUSIQUE = {}
    reponse, actions = c.repondre("mets de la musique")
    assert reponse == "Je n'ai pas réussi à lancer cette musique."
    assert actions and "(non joué)" in actions[0]
