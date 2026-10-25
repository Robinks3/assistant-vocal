"""Nom affiché de l'assistant (0.26.0) : section assistant de maison.json, « Assistant » sans elle."""
import importlib, json

import maison


def test_nom_de_la_configuration_exemple():
    assert maison.NOM_ASSISTANT == "Iris"


def test_section_absente_ou_vide(monkeypatch, tmp_path):
    try:
        for section in (None, {}, {"nom": "  "}, "Iris", ["Iris"], {"nom": 42}, {"nom": None}):
            config = {"proprietaire": {"nom": "Sacha"}} | ({"assistant": section} if section is not None else {})
            (tmp_path / "maison.json").write_text(json.dumps(config), encoding="utf-8")
            monkeypatch.setenv("ASSISTANT_VOCAL_CONFIG", str(tmp_path))
            assert importlib.reload(maison).NOM_ASSISTANT == "Assistant"
        (tmp_path / "maison.json").write_text(json.dumps({"assistant": {"nom": " Jeeves "}}), encoding="utf-8")
        assert importlib.reload(maison).NOM_ASSISTANT == "Jeeves"
    finally:
        monkeypatch.undo()
        importlib.reload(maison)
