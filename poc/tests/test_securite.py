"""Sécurité en dur : mêmes cas que SecuriteTest.kt côté Android (cas_securite.json)."""
import json
from datetime import datetime
from pathlib import Path

import pytest

import securite

CAS = json.loads((Path(__file__).parent / "cas_securite.json").read_text(encoding="utf-8"))


def regler_plafond(monkeypatch, pourcentage):
    """Plafond du volume pour un test, comme securite.plafond_volume dans la configuration (None : aucun)."""
    monkeypatch.setattr(securite, "VOLUME_MAX", securite.plafond_configure(pourcentage) / 100)


@pytest.mark.parametrize("cas", CAS["actions"], ids=lambda c: c["note"])
def test_action(cas, monkeypatch):
    regler_plafond(monkeypatch, cas.get("plafond_volume"))
    moment = datetime(2026, 10, 21, cas["heure"], 30, tzinfo=securite.FUSEAU)
    refus = securite.verifier(cas["service"], cas["donnees"], maintenant=moment, personne=cas.get("personne"))
    assert (refus is not None) == cas["refus"], refus


@pytest.mark.parametrize("cas", CAS["phrases"], ids=lambda c: c["phrase"])
def test_phrase(cas):
    assert (securite.phrase_protegee(cas["phrase"], cas.get("personne")) is not None) == cas["refus"]


@pytest.mark.parametrize("cas", CAS["plafonds"], ids=lambda c: c["note"])
def test_plafond_volume(cas, monkeypatch):
    # verifier() plafonne sur place, sans refuser : ce qui part vers HA est la donnée plafonnée.
    regler_plafond(monkeypatch, cas.get("plafond_volume"))
    donnees = json.loads(json.dumps(cas["donnees"]))
    assert securite.verifier(cas["service"], donnees) is None
    assert donnees == cas["attendu"]


@pytest.mark.parametrize("cas", CAS["plafonds_configures"], ids=lambda c: c["note"])
def test_plafond_configure(cas):
    assert securite.plafond_configure(cas.get("valeur")) == cas["attendu"]


def test_plafond_configure_nan():
    # Absent du fichier commun (JSON n'a pas de NaN) : illisible, plafond prudent.
    assert securite.plafond_configure(float("nan")) == securite.PLAFOND_SI_ILLISIBLE


@pytest.mark.parametrize("cas", CAS["pourcentages"], ids=lambda c: c["attendu"])
def test_pourcentage(cas):
    assert securite.pourcentage(cas["niveau"]) == cas["attendu"]


def test_configuration_sans_plafond():
    """25/10/2026 : plus de plafond de 50 % par défaut. config-exemple règle plafond_volume à 100, comme celle
    du propriétaire : aucun plafond, volume_up permis à la sécurité comme au LLM du serveur."""
    import assistant
    assert securite.plafond_configure(securite.maison.SECURITE.get("plafond_volume")) == 100
    assert securite.VOLUME_MAX == 1.0
    assert not securite.plafond_actif()
    assert securite.plafonner_volume(0.8) == 0.8
    assert securite.verifier("media_player.volume_up", {"entity_id": "media_player.barre_son_salon"}) is None
    assert "volume_up" in assistant.SERVICES_PERMIS["media_player"]
    assert assistant.consigne_plafond() == ""
    assert "@PLAFOND@" not in assistant.CONSIGNE and "plafonn" not in assistant.CONSIGNE


def test_consigne_avec_plafond(monkeypatch):
    import assistant
    regler_plafond(monkeypatch, 50)
    assert "50 %" in assistant.consigne_plafond() and "volume_level 0.5" in assistant.consigne_plafond()
    regler_plafond(monkeypatch, 72.5)
    assert "72,5 %" in assistant.consigne_plafond()


def test_plafonner_volume(monkeypatch):
    regler_plafond(monkeypatch, 50)
    assert securite.plafond_actif()
    assert securite.plafonner_volume(0.8) == 0.5
    assert securite.plafonner_volume(0.25) == 0.25
    assert securite.plafonner_volume(-1) == 0.0
    assert securite.plafonner_volume(float("nan")) == 0.0
    assert securite.plafonner_volume("illisible") == 0.0
    assert securite.plafonner_volume(None) == 0.0


def test_plafonner_volume_sans_plafond(monkeypatch):
    regler_plafond(monkeypatch, None)
    assert securite.plafonner_volume(0.8) == 0.8
    assert securite.plafonner_volume(1.5) == 1.0
    assert securite.plafonner_volume(-1) == 0.0
    assert securite.plafonner_volume(float("nan")) == 0.0
    assert securite.plafonner_volume("illisible") == 0.0


@pytest.mark.parametrize("plafond, attendu", [(50, 0.5), (None, 0.9)])
def test_passerelle_plafonne_le_volume(monkeypatch, plafond, attendu):
    # Passerelle de la tablette (acces.py) : le corps vérifié est celui transmis à HA.
    import acces
    regler_plafond(monkeypatch, plafond)
    corps = {"entity_id": "media_player.barre_son_salon", "volume_level": 0.9}
    assert acces.verifier_requete_ha("POST", "/api/services/media_player/volume_set", corps) is None
    assert corps["volume_level"] == attendu


def test_securite_active():
    assert securite.SECURITE_ACTIVE, "la sécurité en dur ne se lève qu'à la demande explicite du propriétaire"


def test_volume_up_refuse_avec_plafond(monkeypatch):
    """0.20.4 : monter le son par pas passerait au-dessus du plafond, seul un volume précis passe. Depuis le
    25/10/2026, seulement quand la configuration règle un plafond, dont le message dit la valeur."""
    regler_plafond(monkeypatch, 50)
    refus = securite.verifier("media_player.volume_up", {"entity_id": "media_player.barre_son_salon"})
    assert refus == securite.refus_volume_up() and "plafonné à 50 %" in refus
    assert securite.verifier("media_player.volume_down", {"entity_id": "media_player.barre_son_salon"}) is None
    regler_plafond(monkeypatch, 72.5)
    assert "plafonné à 72,5 %" in securite.verifier("media_player.volume_up", {"entity_id": "media_player.barre_son_salon"})


def test_volume_up_permis_sans_plafond(monkeypatch):
    regler_plafond(monkeypatch, 100)
    assert securite.verifier("media_player.volume_up", {"entity_id": "media_player.barre_son_salon"}) is None
    # Les autres sécurités restent : un appareil visé par son identifiant brut est toujours refusé.
    assert securite.verifier("media_player.volume_up", {"device_id": "abc"}) is not None
