"""0.29.1 : lire_etat limité à l'inventaire, passerelle HA sans service en mode essai."""
from types import SimpleNamespace

import assistant as A
import serveur_satellite as S
from test_aiguillage import ENTITE, faux_ha


def test_lire_etat_refuse_hors_inventaire(monkeypatch):
    ha = faux_ha(monkeypatch)
    lus = []
    ha.etat = lambda e: lus.append(e) or {"etat": "on"}
    c = A.Cerveau({"llm_modele": "qwen", "llm_url": "http://llm"}, ha)
    noms = {"lire_etat"}
    res = c.executer_outil("lire_etat", {"entity_id": "lock.porte"}, "", noms, [], [])
    assert res["erreur"].startswith("refusé") and lus == []
    assert c.executer_outil("lire_etat", {"entity_id": ENTITE}, "", noms, [], []) == {"etat": "on"}
    assert lus == [ENTITE]


class ClientHA:
    def __init__(self):
        self.appels = []

    def request(self, methode, url, json=None, timeout=None):
        self.appels.append((methode, url))
        return SimpleNamespace(status_code=200, text="ok", headers={}, content=b"")


def moteur_ha(essai):
    ha = SimpleNamespace(url="http://ha", client=ClientHA())
    return SimpleNamespace(essai=essai, assistant=SimpleNamespace(ha=ha)), ha.client


def test_passerelle_essai_ne_transmet_pas_les_services():
    moteur, client = moteur_ha(True)
    corps = {"entity_id": "light.exemple6"}
    r = S.passerelle_ha(moteur, {"id": 1, "methode": "POST", "chemin": "/api/services/light/turn_on", "corps": corps})
    assert (r["code"], r["corps"]) == (200, "[]") and client.appels == []
    S.passerelle_ha(moteur, {"id": 2, "methode": "GET", "chemin": "/api/states"})
    S.passerelle_ha(moteur, {"id": 3, "methode": "POST", "chemin": "/api/template", "corps": {"template": "{{ 1 }}"}})
    assert [a[0] for a in client.appels] == ["GET", "POST"]
    refus = S.passerelle_ha(moteur, {"id": 4, "methode": "POST", "chemin": "/api/services/lock/unlock",
                                     "corps": {"entity_id": "lock.porte"}})
    assert refus["code"] == 403 and len(client.appels) == 2


def test_passerelle_reel_transmet_les_services():
    moteur, client = moteur_ha(False)
    S.passerelle_ha(moteur, {"id": 1, "methode": "POST", "chemin": "/api/services/light/turn_on",
                             "corps": {"entity_id": "light.exemple6"}})
    assert len(client.appels) == 1
