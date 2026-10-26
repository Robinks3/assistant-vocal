"""Modèles manquants (0.34.1) : le message clair quand un modèle non redistribué n'est pas là, sans réseau."""
import importlib.util
import io
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "outils" / "telecharger_modeles.py"


@pytest.fixture
def T():
    spec = importlib.util.spec_from_file_location("telecharger_modeles_essai", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def remplir(racine, T, groupe):
    for relatif in T.GROUPES[groupe]:
        chemin = racine / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(b"modele")


def test_android_sans_aucun_modele_cite_licence_source_et_commande(tmp_path, T):
    message = T.message_modeles_manquants("android", tmp_path)
    for nom in ("hey_jarvis_v0.1.onnx", "embedding_model.onnx", "melspectrogram.onnx", "sface.onnx"):
        assert nom in message
    assert "CC BY-NC-SA 4.0" in message
    assert "creativecommons.org/licenses/by-nc-sa/4.0" in message
    assert "openWakeWord" in message
    assert "python poc/outils/telecharger_modeles.py" in message


def test_rien_ne_manque_donne_un_message_vide(tmp_path, T):
    remplir(tmp_path, T, "android")
    assert T.modeles_manquants("android", tmp_path) == []
    assert T.message_modeles_manquants("android", tmp_path) == ""


def test_un_fichier_vide_compte_comme_manquant(tmp_path, T):
    remplir(tmp_path, T, "android")
    (tmp_path / T.ASSETS_REVEIL / "embedding_model.onnx").write_bytes(b"")
    assert T.modeles_manquants("android", tmp_path) == [f"{T.ASSETS_REVEIL}/embedding_model.onnx"]


def test_voix_manquante_du_serveur_sans_mention_de_licence_non_commerciale(tmp_path, T, monkeypatch):
    monkeypatch.setattr(T, "_dossier_openwakeword", lambda: tmp_path / "paquet-absent")
    absents = T.modeles_manquants("serveur", tmp_path)
    assert "poc/voix/fr_FR-siwis-medium.onnx" in absents
    message = T.message_modeles_manquants("serveur", tmp_path)
    assert "poc/voix/fr_FR-siwis-medium.onnx" in message
    assert "CC BY-NC-SA" not in "\n".join(
        ligne for ligne in message.splitlines() if "poc/voix" in ligne)


def test_mot_de_reveil_du_paquet_openwakeword_manquant_cite_la_licence(tmp_path, T, monkeypatch):
    remplir(tmp_path, T, "serveur")
    dossier = tmp_path / "paquet"
    dossier.mkdir()
    (dossier / "embedding_model.onnx").write_bytes(b"modele")
    (dossier / "melspectrogram.onnx").write_bytes(b"modele")
    monkeypatch.setattr(T, "_dossier_openwakeword", lambda: dossier)
    assert T.modeles_manquants("serveur", tmp_path) == ["openwakeword/resources/models/hey_jarvis_v0.1.onnx"]


def test_paquet_openwakeword_absent_ne_plante_pas(tmp_path, T, monkeypatch):
    remplir(tmp_path, T, "serveur")
    monkeypatch.setattr(T, "_dossier_openwakeword", lambda: None)
    assert T.modeles_manquants("serveur", tmp_path) == []


def test_verifier_au_demarrage_ecrit_le_message_et_renvoie_faux(tmp_path, T):
    sortie = io.StringIO()
    assert T.verifier_au_demarrage("android", tmp_path, sortie) is False
    assert "Modèles manquants" in sortie.getvalue()
    remplir(tmp_path, T, "android")
    sortie = io.StringIO()
    assert T.verifier_au_demarrage("android", tmp_path, sortie) is True
    assert sortie.getvalue() == ""


def test_groupe_inconnu_est_refuse(tmp_path, T):
    with pytest.raises(ValueError):
        T.modeles_manquants("autre", tmp_path)


def test_table_des_modeles_coherente(T):
    """Chaque modèle sous licence restreinte est dans MODELES, avec une empreinte SHA-256 et une adresse officielle."""
    par_chemin = {relatif: (url, empreinte) for relatif, url, empreinte in T.MODELES}
    assert len(par_chemin) == len(T.MODELES), "chemin en double dans MODELES"
    for relatif in T.LICENCES:
        assert relatif in par_chemin
        url, empreinte = par_chemin[relatif]
        assert url.startswith("https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/")
        assert len(empreinte) == 64 and set(empreinte) <= set("0123456789abcdef")
    copies = {destination for _source, destination in T.COPIES}
    for relatif in T.GROUPES["android"]:
        assert relatif in par_chemin or relatif in copies


def test_les_assets_versionnes_ont_l_empreinte_attendue(T):
    """Les trois modèles encore dans l'arbre (avant l'instantané public) sont ceux de la publication officielle."""
    racine = Path(__file__).resolve().parents[2]
    par_chemin = {relatif: empreinte for relatif, _url, empreinte in T.MODELES}
    for relatif in T.LICENCES:
        fichier = racine / relatif
        if fichier.is_file():
            assert T.empreinte(fichier) == par_chemin[relatif]
