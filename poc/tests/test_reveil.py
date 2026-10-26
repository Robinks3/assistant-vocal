"""Mot de réveil (0.36.0) : la section reveil de maison.json d'abord, MOT_REVEIL en secours, « assistant » par défaut.
Sans le fichier reveil/<mot>.onnx, repli sur « Hey Jarvis » avec une ligne claire au journal."""
import assistant as A
import maison


def _configuration(monkeypatch, tmp_path, section, modeles=()):
    """Dossier de configuration temporaire : jamais la vraie configuration."""
    (tmp_path / "reveil").mkdir(exist_ok=True)
    for mot in modeles:
        (tmp_path / "reveil" / f"{mot}.onnx").write_bytes(b"modele fictif")
    monkeypatch.setattr(maison, "DOSSIER", tmp_path)
    monkeypatch.setattr(maison, "CONFIG", {"reveil": section} if section is not None else {})


def test_exemple_sans_modele_se_replie_sur_hey_jarvis(monkeypatch):
    """config-exemple/ décrit le mot « assistant » mais ne fournit pas son modèle : repli, avec la raison."""
    monkeypatch.delenv("MOT_REVEIL", raising=False)
    r = A.reglage_reveil()
    assert (r.modele, r.nom, r.mot) == ("hey_jarvis", "Hey Jarvis", "assistant")
    assert "modèle de réveil absent pour le mot assistant" in r.repli
    assert "repli sur Hey Jarvis" in r.repli


def test_nom_assistant_quand_le_modele_existe(monkeypatch, tmp_path):
    _configuration(monkeypatch, tmp_path, {"mot": "assistant", "nom": "Assistant"}, ["assistant"])
    monkeypatch.delenv("MOT_REVEIL", raising=False)
    assert A.modele_reveil() == (str(tmp_path / "reveil" / "assistant.onnx"), "Assistant")
    assert A.reglage_reveil().repli == ""


def test_repli_hey_jarvis_et_message_quand_le_modele_manque(monkeypatch, tmp_path, capsys):
    _configuration(monkeypatch, tmp_path, {"mot": "assistant", "nom": "Assistant"})
    monkeypatch.delenv("MOT_REVEIL", raising=False)
    assert A.modele_reveil() == ("hey_jarvis", "Hey Jarvis")
    A.annoncer_repli_reveil()
    sortie = capsys.readouterr().out
    assert "modèle de réveil absent pour le mot assistant" in sortie
    assert "repli sur Hey Jarvis" in sortie


def test_pas_de_message_quand_le_modele_est_present(monkeypatch, tmp_path, capsys):
    _configuration(monkeypatch, tmp_path, {"mot": "assistant"}, ["assistant"])
    monkeypatch.delenv("MOT_REVEIL", raising=False)
    A.annoncer_repli_reveil()
    assert capsys.readouterr().out == ""


def test_sans_nom_le_mot_est_capitalise(monkeypatch, tmp_path):
    _configuration(monkeypatch, tmp_path, {"mot": "jeeves"}, ["jeeves"])
    assert A.modele_reveil()[1] == "Jeeves"


def test_mot_de_la_configuration_prime_sur_mot_reveil(monkeypatch, tmp_path):
    _configuration(monkeypatch, tmp_path, {"mot": "jeeves", "nom": "Jeeves le majordome"}, ["jeeves", "autre"])
    monkeypatch.setenv("MOT_REVEIL", "autre")
    assert A.modele_reveil() == (str(tmp_path / "reveil" / "jeeves.onnx"), "Jeeves le majordome")


def test_mot_reveil_honore_en_secours(monkeypatch, tmp_path):
    """Sans section reveil, MOT_REVEIL désigne le mot. Son nom n'est pas celui d'une section : mot capitalisé."""
    _configuration(monkeypatch, tmp_path, None, ["jeeves"])
    monkeypatch.setenv("MOT_REVEIL", "Jeeves")
    assert A.modele_reveil() == (str(tmp_path / "reveil" / "jeeves.onnx"), "Jeeves")


def test_mot_par_defaut_sans_section_ni_variable(monkeypatch, tmp_path):
    _configuration(monkeypatch, tmp_path, None, ["assistant"])
    monkeypatch.delenv("MOT_REVEIL", raising=False)
    assert A.modele_reveil() == (str(tmp_path / "reveil" / "assistant.onnx"), "Assistant")


def test_hey_jarvis_demande_explicitement_sans_repli(monkeypatch, tmp_path, capsys):
    _configuration(monkeypatch, tmp_path, {"mot": "hey_jarvis"})
    assert A.modele_reveil() == ("hey_jarvis", "Hey Jarvis")
    A.annoncer_repli_reveil()
    assert capsys.readouterr().out == ""


def test_mot_avec_chemin_refuse(monkeypatch, tmp_path):
    """Un mot qui sort du dossier reveil/ (../) n'ouvre jamais un fichier : repli."""
    _configuration(monkeypatch, tmp_path, {"mot": "../secret"})
    assert A.modele_reveil() == ("hey_jarvis", "Hey Jarvis")
