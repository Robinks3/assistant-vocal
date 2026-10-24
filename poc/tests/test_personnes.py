"""« Ma chambre » selon la personne qui parle : mêmes cas que DictionnaireTest.kt (cas_personnes.json)."""
import json
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import assistant as A
import maison
import securite
from dictionnaire import Dictionnaire, epurer

ICI = Path(__file__).resolve().parent
# Phrases apprises dans un dossier temporaire : rien n'est jamais écrit dans config-exemple/.
DICO = Dictionnaire(maison.chemin("commandes.yaml"), Path(tempfile.mkdtemp()) / "commandes_apprises.yaml")
CAS = json.loads((ICI / "cas_personnes.json").read_text(encoding="utf-8"))["cas"]


def cibles(a):
    return securite.cibles(a.get("entity_id"))


@pytest.mark.parametrize("cas", CAS, ids=lambda c: c["note"])
def test_ma_chambre(cas):
    trouve = DICO.chercher(epurer(cas["phrase"]))
    assert trouve, cas["phrase"]
    actions, _, cle = trouve
    sortie, refus, _ = DICO.personnes.appliquer(actions, cle, cas.get("personne"))
    if cas.get("refus"):
        assert refus and not sortie
        return
    assert refus is None
    assert [cibles(a) for a in sortie] == cas["cibles"]
    if "service" in cas:
        assert sortie[0]["service"] == cas["service"]
    moment = datetime(2026, 10, 21, 21, 0, tzinfo=securite.FUSEAU)
    refus_secu = [securite.verifier(a["service"], {k: v for k, v in a.items() if k != "service"},
                                    maintenant=moment, personne=cas.get("personne")) for a in sortie]
    assert any(refus_secu) == cas["securite_refus"], refus_secu


@pytest.mark.skipif(not securite.PROTEGER_OCCUPANT, reason="règle 1 levée le 22/10/2026")
def test_sacha_ne_pilote_pas_les_lumieres_de_camille_par_le_dictionnaire_remplace():
    # Même si une action remplacée pour Camille arrivait sous le nom de Sacha, la sécurité la refuse.
    actions, _, cle = DICO.chercher("allume les lumieres de ma chambre")
    sortie, _, _ = DICO.personnes.appliquer(actions, cle, "Camille")
    assert securite.verifier(sortie[0]["service"], {"entity_id": sortie[0]["entity_id"]}, personne="Sacha")


class FausseHA:
    """Inventaire de HA simulé : la vraie méthode HomeAssistant.inventaire sur un faux client."""

    def __init__(self):
        lignes = ["light.exemple6\tSalon\tSéjour\ton",
                  "light.exemple14\tPlafond Sacha\tChambre Sacha\toff",
                  "light.chambre_camille\tChambre Camille\tChambre Camille\ton",
                  "light.exemple18\tChevet Camille\tChambre Camille\toff",
                  "Exemple44\tRéveil\tChambre Camille\ton",
                  "sensor.exemple65\tTempérature\tSalle de bain Camille\t21 °C"]
        reponse = SimpleNamespace(text="\n".join(lignes), raise_for_status=lambda: None)
        self.ha = A.HomeAssistant.__new__(A.HomeAssistant)
        self.ha.url, self.ha.vue_llm, self.ha.entites_llm, self.ha.personne = "", {}, set(), None
        self.ha.client = SimpleNamespace(post=lambda *a, **k: reponse)


@pytest.mark.skipif(not securite.PROTEGER_OCCUPANT, reason="règle 1 levée le 22/10/2026")
def test_inventaire_selon_la_personne():
    ha = FausseHA().ha
    liste, _ = ha.inventaire()
    assert "camille" not in liste.lower()
    ha.personne = "Sacha"
    liste, _ = ha.inventaire()
    assert "camille" not in liste.lower()
    ha.personne = "inconnu"
    liste, _ = ha.inventaire()
    assert "camille" not in liste.lower()
    ha.personne = "Camille"
    liste, _ = ha.inventaire()
    assert "light.chambre_camille " in liste and "light.exemple18" in liste
    assert "Exemple44" not in liste and "sensor.camille" not in liste
    assert ha.entites_llm == {"light.exemple6", "light.exemple14", "light.chambre_camille",
                              "light.exemple18"}


def test_indication_pour_le_llm():
    a = A.Assistant.__new__(A.Assistant)
    a.dico = DICO
    assert a.indication(None) == ""
    assert "Camille" in a.indication("Camille") and "light.exemple18" in a.indication("Camille")
    assert "light.exemple14" in a.indication("Sacha")
    assert "n'a pas reconnue" in a.indication("inconnu") and "n'a pas reconnue" in a.indication("Lou")
    assert "voix" not in a.indication("inconnu")
    for p in ("Camille", "Sacha", "inconnu"):
        assert ";" not in a.indication(p) and "—" not in a.indication(p)


@pytest.mark.skipif(not securite.PROTEGER_OCCUPANT, reason="règle 1 levée le 22/10/2026")
def test_pas_d_apprentissage_d_une_action_de_camille(tmp_path):
    a = A.Assistant.__new__(A.Assistant)
    a.essai = False
    appris = []
    a.dico = SimpleNamespace(apprendre=lambda *x: appris.append(x) or True)
    a.cerveau = SimpleNamespace(dernieres_actions=[{"service": "light.turn_on", "entity_id": ["light.chambre_camille"]}])
    a.apprendre("allume ma lampe", "C'est allumé.")
    assert not appris
    a.cerveau.dernieres_actions = [{"service": "light.turn_on", "entity_id": ["light.exemple6"]}]
    a.apprendre("allume le salon stp", "C'est allumé.")
    assert appris


@pytest.mark.skipif(not securite.PROTEGER_OCCUPANT, reason="règle 1 levée le 22/10/2026")
def test_passerelle_avec_la_personne():
    import acces
    corps = {"entity_id": "light.chambre_camille"}
    assert acces.verifier_requete_ha("POST", "/api/services/light/turn_on", corps)
    assert acces.verifier_requete_ha("POST", "/api/services/light/turn_on", corps, personne="Sacha")
    assert acces.verifier_requete_ha("POST", "/api/services/light/turn_on", corps, personne="Camille") is None
    assert acces.verifier_requete_ha("POST", "/api/services/automation/trigger",
                                     {"entity_id": "Exemple44"}, personne="Camille")
