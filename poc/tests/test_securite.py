"""Sécurité en dur : mêmes cas que SecuriteTest.kt côté Android (cas_securite.json)."""
import json
from datetime import datetime
from pathlib import Path

import pytest

import securite

CAS = json.loads((Path(__file__).parent / "cas_securite.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("cas", CAS["actions"], ids=lambda c: c["note"])
def test_action(cas):
    moment = datetime(2026, 10, 21, cas["heure"], 30, tzinfo=securite.FUSEAU)
    refus = securite.verifier(cas["service"], cas["donnees"], maintenant=moment, personne=cas.get("personne"))
    assert (refus is not None) == cas["refus"], refus


@pytest.mark.parametrize("cas", CAS["phrases"], ids=lambda c: c["phrase"])
def test_phrase(cas):
    assert (securite.phrase_protegee(cas["phrase"], cas.get("personne")) is not None) == cas["refus"]


@pytest.mark.parametrize("cas", CAS["plafonds"], ids=lambda c: c["note"])
def test_plafond_volume(cas):
    # verifier() plafonne sur place, sans refuser : ce qui part vers HA est la donnée plafonnée.
    donnees = json.loads(json.dumps(cas["donnees"]))
    assert securite.verifier(cas["service"], donnees) is None
    assert donnees == cas["attendu"]


def test_plafonner_volume():
    assert securite.VOLUME_MAX == 0.5
    assert securite.plafonner_volume(0.8) == 0.5
    assert securite.plafonner_volume(0.25) == 0.25
    assert securite.plafonner_volume(-1) == 0.0
    assert securite.plafonner_volume(float("nan")) == 0.0
    assert securite.plafonner_volume("illisible") == 0.0
    assert securite.plafonner_volume(None) == 0.0


def test_passerelle_plafonne_le_volume():
    # Passerelle de la tablette (acces.py) : le corps vérifié est celui transmis à HA.
    import acces
    corps = {"entity_id": "media_player.salon", "volume_level": 0.9}
    assert acces.verifier_requete_ha("POST", "/api/services/media_player/volume_set", corps) is None
    assert corps["volume_level"] == securite.VOLUME_MAX


def test_securite_active():
    assert securite.SECURITE_ACTIVE, "la sécurité en dur ne se lève qu'à la demande explicite du propriétaire"


def test_volume_up_refuse():
    """0.20.4 : monter le son par pas passerait au-dessus de 50 %, seul un volume précis passe."""
    assert securite.verifier("media_player.volume_up", {"entity_id": "media_player.salon"}) == securite.VOLUME_UP_REFUSE
    assert securite.verifier("media_player.volume_down", {"entity_id": "media_player.salon"}) is None
