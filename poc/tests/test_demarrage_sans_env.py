"""Démarrage sans réglage dans poc/.env (0.36.0) : micro par défaut du système, voix absente signalée proprement."""
import sys
import types

import pytest

import assistant as A


def _faux_sounddevice(monkeypatch):
    """sounddevice fictif qui échoue si on l'interroge : un micro par défaut ne doit pas toucher au matériel."""
    faux = types.ModuleType("sounddevice")

    def query_devices(*args, **kwargs):
        raise AssertionError("le matériel audio ne doit pas être interrogé")

    faux.query_devices = query_devices
    monkeypatch.setitem(sys.modules, "sounddevice", faux)


@pytest.mark.parametrize("nom", ["", None, "defaut", "DEFAUT", " default "])
def test_micro_par_defaut_accepte(monkeypatch, nom):
    _faux_sounddevice(monkeypatch)
    assert A.trouver_peripherique(nom, True) is None


def test_nom_de_micro_cherche_dans_les_peripheriques(monkeypatch):
    faux = types.ModuleType("sounddevice")
    faux.query_devices = lambda: [
        {"name": "Haut-parleurs", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
        {"name": "Micro de test", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 0},
    ]
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    assert A.trouver_peripherique("micro de", True) == 1
    assert A.trouver_peripherique("inconnu", True) is None


def test_micro_et_voix_ont_un_defaut_sans_env(monkeypatch):
    """Sans ligne MICRO ni VOIX (et sans lire le vrai poc/.env), charger_env donne le micro par défaut et la voix
    livrée par le script de téléchargement."""
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("MICRO", raising=False)
    monkeypatch.delenv("VOIX", raising=False)
    cfg = A.charger_env()
    assert cfg["micro"] == A.MICRO_DEFAUT == "defaut"
    assert cfg["voix"] == str(A.VOIX_DEFAUT)
    assert A.VOIX_DEFAUT.name == "fr_FR-siwis-medium.onnx"
    assert A.trouver_peripherique(cfg["micro"], True) is None


def test_micro_regle_dans_env_reste_prioritaire(monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("MICRO", "micro de test")
    assert A.charger_env()["micro"] == "micro de test"


def test_voix_absente_signalee_proprement(tmp_path):
    absente = tmp_path / "voix" / "inexistante.onnx"
    with pytest.raises(SystemExit) as erreur:
        A.verifier_voix(absente)
    message = str(erreur.value)
    assert "Voix Piper absente" in message
    assert str(absente) in message
    assert "VOIX" in message
    assert "telecharger_modeles.py" in message


def test_voix_presente_acceptee(tmp_path):
    fichier = tmp_path / "voix.onnx"
    fichier.write_bytes(b"modele fictif")
    A.verifier_voix(fichier)
