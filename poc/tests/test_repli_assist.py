"""S-D9 (décision D8) : le repli vers Assist de Home Assistant est coupé par défaut, ouvert par
securite.assist_repli seulement, et jamais pour une phrase que la sécurité refuse. Assist est simulé, aucun réseau."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import assistant as A
import maison
import securite

CAS = json.loads((Path(__file__).parent / "cas_securite.json").read_text(encoding="utf-8"))
REFUSES = [c for c in CAS["actions"] if c["refus"]]

# Phrases que le LLM n'a pas su traiter et qu'Assist peut tenter quand le repli est ouvert.
ANODINES = ["allume la lumière du salon", "éteins la lampe du bureau", "quelle heure est-il", "ferme le volet du salon"]

# Phrases dangereuses ou ambiguës : jamais confiées à Assist, quel que soit le réglage.
DANGEREUSES = [
    "ouvre la serrure", "verrouille la porte d'entrée", "déverrouille", "désactive l'alarme", "arme l'alarme",
    "allume le four", "mets la plaque à fond", "mets le chauffage à 30 degrés", "règle le thermostat",
    "éteins tout", "éteins toutes les lumières", "allume la maison", "éteins l'étage", "allume l'étiquette salon",
    "coupe le frigo", "lance le script bonne nuit", "active la scène cinéma", "déclenche l'automatisation",
]

# Une phrase par famille de cas refusés de cas_securite.json : le repli ne les rattrape pas.
PHRASES_PAR_FAMILLE = {
    "device_id": ["allume l'appareil abc123", "éteins le device abc123"],
    "floor_id": ["éteins tout l'étage", "ferme les volets du rez-de-chaussée en entier"],
    "label_id": ["éteins tout ce qui a l'étiquette tout éteindre", "coupe l'étiquette des lampes"],
    "lock": ["ouvre la serrure de la porte d'entrée", "déverrouille la porte"],
    "alarm_control_panel": ["désarme l'alarme de la maison", "active l'alarme"],
    "volume_up": ["monte le son", "mets le volume plus fort"],
}


def famille(cas):
    donnees = cas["donnees"]
    for cle in ("device_id", "floor_id", "label_id"):
        if cle in donnees:
            return cle
    domaines = {cas["service"].split(".")[0]} | {e.split(".")[0].lower() for e in securite.cibles(donnees.get("entity_id"))}
    for d in ("lock", "alarm_control_panel"):
        if d in {x.lower() for x in domaines}:
            return d
    if cas["service"] == "media_player.volume_up":
        return "volume_up"
    pytest.fail(f"cas refusé sans phrase de repli associée : {cas['note']}")


class FauxClient:
    """Simule le client HTTP de Home Assistant : compte les appels à Assist, sans réseau."""

    def __init__(self):
        self.appels = []

    def post(self, url, json=None, **_):
        self.appels.append((url, json))
        reponse = {"response": {"response_type": "action_done", "speech": {"plain": {"speech": "C'est fait."}},
                                "data": {"success": [{"type": "entity", "id": "light.salon_plafond"}]}}}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: reponse)


def ha_simule():
    ha = object.__new__(A.HomeAssistant)
    ha.url, ha.client, ha.dernieres_cibles = "http://ha.test", FauxClient(), []
    return ha


def assistant_simule(monkeypatch, ha, llm_en_panne=True):
    """Assistant dont le dictionnaire ne connaît rien et dont le LLM échoue (ou répond), avec l'Assist simulé."""
    monkeypatch.setattr(A, "journaliser", lambda *a, **k: None)
    monkeypatch.setattr(A, "ajouter_jsonl", lambda *a, **k: None)
    a = object.__new__(A.Assistant)
    a.essai, a.voix, a.lecons, a.ha = False, None, {}, ha
    a.dico = SimpleNamespace(chercher=lambda t: None, personnes=None)
    a.routines_avant = lambda t: None
    a.indication = lambda p: ""
    a.apprendre = lambda *x: None

    def repondre(texte, mode="commande"):
        if llm_en_panne:
            raise RuntimeError("LLM hors service")
        return "Je ne sais pas.", []
    a.cerveau = SimpleNamespace(repondre=repondre)
    return a


def regler(monkeypatch, repli):
    monkeypatch.setattr(securite, "ASSIST_REPLI", repli)


def dire(a, phrase):
    return a._traiter(phrase, 0.0, None)


# --- Le réglage ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("valeur", [None, False, 0, 1, "true", "false", "oui", [], {}])
def test_seul_le_booleen_vrai_ouvre(valeur):
    assert securite.repli_configure(valeur) is False


def test_booleen_vrai_ouvre():
    assert securite.repli_configure(True) is True


def test_configuration_d_exemple_est_coupee():
    assert maison.SECURITE.get("assist_repli") is False
    assert securite.ASSIST_REPLI is False


# --- Réglage absent ou faux : jamais de repli ------------------------------------------------------------------

@pytest.mark.parametrize("phrase", ANODINES)
@pytest.mark.parametrize("repli", [False, None])
def test_repli_coupe_jamais_assist(monkeypatch, phrase, repli):
    """Réglage faux ou absent (lu comme faux) : Assist n'est jamais appelé, même pour une phrase anodine."""
    regler(monkeypatch, securite.repli_configure(repli))
    ha = ha_simule()
    a = assistant_simule(monkeypatch, ha)
    parole = dire(a, phrase)
    assert ha.client.appels == []
    assert "ne répond pas" in parole
    assert securite.SECURITE_ACTIVE is True


def test_conversation_coupee_donne_le_motif(monkeypatch):
    regler(monkeypatch, False)
    ha = ha_simule()
    compris, parole, code = ha.conversation("allume la lumière du salon")
    assert (compris, parole) == (False, "")
    assert code.startswith("Assist sauté (sécurité") and "securite.assist_repli" in code
    assert ha.client.appels == []


# --- Réglage vrai ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", ANODINES)
def test_repli_ouvert_phrase_anodine_tentee(monkeypatch, phrase, capsys):
    regler(monkeypatch, True)
    ha = ha_simule()
    a = assistant_simule(monkeypatch, ha)
    parole = dire(a, phrase)
    assert len(ha.client.appels) == 1
    url, corps = ha.client.appels[0]
    assert url.endswith("/api/conversation/process") and corps["text"] == phrase
    assert parole == "C'est fait."
    assert "[repli Assist] repli tenté" in capsys.readouterr().out
    assert securite.SECURITE_ACTIVE is True


def test_repli_ouvert_jamais_avant_le_llm(monkeypatch):
    """Le LLM répond : Assist n'est pas sollicité, c'est un repli et non une première voie."""
    regler(monkeypatch, True)
    ha = ha_simule()
    a = assistant_simule(monkeypatch, ha, llm_en_panne=False)
    assert dire(a, "allume la lumière du salon") == "Je ne sais pas."
    assert ha.client.appels == []


def test_repli_ouvert_jamais_en_mode_essai(monkeypatch):
    """HA exécute lui-même ses intentions : en essai, aucun appel."""
    regler(monkeypatch, True)
    ha = ha_simule()
    a = assistant_simule(monkeypatch, ha)
    a.essai = True
    dire(a, "allume la lumière du salon")
    assert ha.client.appels == []


@pytest.mark.parametrize("phrase", DANGEREUSES)
def test_repli_ouvert_phrase_dangereuse_jamais_assist(monkeypatch, phrase):
    regler(monkeypatch, True)
    ha = ha_simule()
    a = assistant_simule(monkeypatch, ha)
    dire(a, phrase)
    assert ha.client.appels == [], phrase
    assert securite.SECURITE_ACTIVE is True


def test_repli_ouvert_phrase_de_l_occupant_jamais_assist(monkeypatch):
    """Un mot de l'occupant protégé ferme le repli même quand la règle 1 est levée."""
    regler(monkeypatch, True)
    mot = securite.MOTS_PROTEGES[0]
    ha = ha_simule()
    a = assistant_simule(monkeypatch, ha)
    dire(a, f"allume la chambre de {mot}")
    assert ha.client.appels == []
    ok, motif = securite.repli_assist(f"allume la lumière de {mot}", "inconnu")
    assert not ok and "sécurité" in motif


@pytest.mark.parametrize("cas", REFUSES, ids=lambda c: c["note"])
def test_repli_ouvert_cas_refuses_de_cas_securite(monkeypatch, cas):
    """Chaque famille de cas refusés de cas_securite.json a ses phrases, et aucune n'atteint Assist."""
    regler(monkeypatch, True)
    if famille(cas) == "volume_up":
        monkeypatch.setattr(securite, "VOLUME_MAX", 0.5)
    for phrase in PHRASES_PAR_FAMILLE[famille(cas)]:
        ha = ha_simule()
        a = assistant_simule(monkeypatch, ha)
        dire(a, phrase)
        assert ha.client.appels == [], phrase
        ok, motif = securite.repli_assist(phrase)
        assert not ok and motif.startswith("repli refusé par la sécurité"), phrase
    assert securite.SECURITE_ACTIVE is True


def test_volume_libre_sans_plafond(monkeypatch):
    """Sans plafond, le volume n'est pas un motif de refus."""
    regler(monkeypatch, True)
    monkeypatch.setattr(securite, "VOLUME_MAX", 1)
    ok, _ = securite.repli_assist("baisse le volume de la télé")
    assert ok


# --- Le réglage ne lève rien -----------------------------------------------------------------------------------

def test_le_reglage_ne_touche_pas_a_la_securite(monkeypatch):
    regler(monkeypatch, True)
    assert securite.SECURITE_ACTIVE is True
    refus = securite.verifier("lock.unlock", {"entity_id": "lock.porte_entree"})
    assert refus and "serrures" in refus
    assert securite.verifier("light.turn_off", {"device_id": "abc123"})


def test_securite_levee_garde_l_ancien_comportement(monkeypatch):
    """SECURITE_ACTIVE faux (levée totale par le propriétaire) : Assist comme avant S-D9, sans filtre."""
    monkeypatch.setattr(securite, "SECURITE_ACTIVE", False)
    ok, motif = securite.repli_assist("allume le four")
    assert ok and "sécurité levée" in motif
