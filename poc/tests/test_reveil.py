"""Mot de réveil (0.25.0) : « hey_jarvis » par défaut, sinon le modèle reveil/<mot>.onnx du dossier de
configuration, avec le nom affiché de sa section reveil de maison.json."""
import assistant as A
import maison


def test_sans_modele_dans_la_configuration_hey_jarvis(monkeypatch):
    """config-exemple/ n'a pas de mot de réveil : MOT_REVEIL=assistant retombe sur Hey Jarvis."""
    monkeypatch.setenv("MOT_REVEIL", "assistant")
    assert A.modele_reveil() == ("hey_jarvis", "Hey Jarvis")


def test_modele_de_la_configuration(monkeypatch, tmp_path):
    (tmp_path / "reveil").mkdir()
    (tmp_path / "reveil" / "jeeves.onnx").write_bytes(b"modele")
    monkeypatch.setattr(maison, "DOSSIER", tmp_path)
    monkeypatch.setattr(maison, "CONFIG", {"reveil": {"mot": "jeeves", "nom": "Jeeves le majordome"}})
    monkeypatch.setenv("MOT_REVEIL", "Jeeves")
    assert A.modele_reveil() == (str(tmp_path / "reveil" / "jeeves.onnx"), "Jeeves le majordome")
    # Section reveil absente ou décrivant un autre mot : nom tiré du mot.
    monkeypatch.setattr(maison, "CONFIG", {"reveil": {"mot": "autre", "nom": "Autre"}})
    assert A.modele_reveil()[1] == "Jeeves"
