"""Outil des captures du mot de réveil (poc/outils/analyser_captures.py), sur des captures synthétiques."""
import importlib.util
import io
import json
import tarfile
import wave
from pathlib import Path

import pytest

CHEMIN = Path(__file__).resolve().parents[1] / "outils" / "analyser_captures.py"
spec = importlib.util.spec_from_file_location("analyser_captures", CHEMIN)
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


def ecrire_capture(dossier, nom, etiquette, scores, vad=None, phases=None, seuil=0.5, blocs=None):
    blocs = blocs or len(scores)
    with wave.open(str(dossier / f"{nom}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * A.BLOC * blocs)
    meta = {
        "schema": 1, "id": nom, "etiquette": etiquette, "cause": "essai", "issue": None, "seuil": seuil,
        "scores": scores, "vad": vad if vad is not None else [0.9] * blocs, "db": [-40.0] * blocs,
        "phases": phases or "R" * blocs, "modele": {"fichier": A.MODELE_REPLI},
    }
    (dossier / f"{nom}.json").write_text(json.dumps(meta), encoding="utf-8")


def test_lire_captures_trie_filtre_et_ignore_les_incompletes(tmp_path):
    ecrire_capture(tmp_path, "capture-20261110-120000-000", "reveil", [0.1, 0.8])
    ecrire_capture(tmp_path, "capture-20261110-110000-000", "manque", [0.1, 0.2])
    (tmp_path / "capture-20261110-130000-000.json").write_text("{}", encoding="utf-8")  # sans WAV
    tout = A.lire_captures(tmp_path)
    assert [c.nom for c in tout] == ["capture-20261110-110000-000", "capture-20261110-120000-000"]
    assert [c.nom for c in A.lire_captures(tmp_path, etiquette="manque")] == ["capture-20261110-110000-000"]
    c = tout[1]
    assert c.score_max() == 0.8 and c.blocs_au_dessus() == 1 and c.son().size == 2 * A.BLOC
    assert A.lire_captures(tmp_path / "absent") == []


def test_premier_reveil_suit_la_confirmation_de_l_appli():
    # Un seul bloc au-dessus du seuil ne suffit pas, deux de suite oui.
    assert A.premier_reveil([0.1, 0.9, 0.1], [0.9] * 3, "RRR", 0.5) is None
    assert A.premier_reveil([0.1, 0.9, 0.9], [0.9] * 3, "RRR", 0.5) == 2
    assert A.premier_reveil([0.1, 0.9, 0.1], [0.9] * 3, "RRR", 0.5, blocs_score=1) == 1
    # Pas de parole vue par Silero dans les 15 derniers blocs : refus.
    scores = [0.0] * 20 + [0.9, 0.9]
    vad = [0.9] + [0.0] * 21
    assert A.premier_reveil(scores, vad, "R" * 22, 0.5) is None
    # Sans Silero (vad absent), seule la suite compte.
    assert A.premier_reveil(scores, [None] * 22, "R" * 22, 0.5) == 21
    # Hors repos, le détecteur repart à zéro, et les scores absents sont sautés.
    assert A.premier_reveil([0.9, 0.9, 0.9], [0.9] * 3, "RER", 0.5) is None
    assert A.premier_reveil([0.9, None, 0.9], [0.9] * 3, "RRR", 0.5) == 2


def test_balayer_compte_manques_reveils_et_faux(tmp_path):
    ecrire_capture(tmp_path, "capture-20261110-100000-000", "manque", [0.3, 0.35, 0.1])
    ecrire_capture(tmp_path, "capture-20261110-100100-000", "reveil", [0.6, 0.7, 0.1])
    ecrire_capture(tmp_path, "capture-20261110-100200-000", "faux_signale", [0.55, 0.52, 0.0])
    captures = A.lire_captures(tmp_path)
    bilans = {(b.seuil, b.blocs): b for b in A.balayer(captures, [0.3, 0.5, 0.6], regles=(2,))}
    b = bilans[(0.3, 2)]
    assert (b.manques, b.reveils, b.faux) == ([1, 1], [1, 1], [0, 1])
    b = bilans[(0.6, 2)]
    assert (b.manques, b.reveils, b.faux) == ([0, 1], [1, 1], [1, 1])
    assert A.plage(0.2, 0.3, 0.05) == [0.2, 0.25, 0.3]


def test_comparer_ignore_les_blocs_sans_score():
    assert A.comparer([None, 0.5, 0.2], [0.1, 0.4, 0.4]) == (pytest.approx(0.15), pytest.approx(0.2))
    assert A.comparer([None], [0.3]) == (None, None)


def archive(fichiers):
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as t:
        for nom, donnees in fichiers.items():
            info = tarfile.TarInfo(nom)
            info.size = len(donnees)
            t.addfile(info, io.BytesIO(donnees))
    return tampon.getvalue()


def test_extraire_ne_garde_que_les_captures_et_reste_dans_le_dossier(tmp_path):
    a = archive({
        "files/captures-reveil/capture-20261110-100000-000.wav": b"RIFF",
        "files/captures-reveil/capture-20261110-100000-000.json": b"{}",
        "files/captures-reveil/capture-20261110-100000-000.json.tmp": b"x",
        "files/../../shared_prefs/satellite.xml": b"secret",
        "../../capture-20261110-100000-001.wav": b"RIFF",
    })
    ecrits = A.extraire(a, tmp_path / "sortie")
    noms = sorted(n for n, _ in ecrits)
    assert noms == ["capture-20261110-100000-000.json", "capture-20261110-100000-000.wav",
                    "capture-20261110-100000-001.wav"]
    assert sorted(p.name for p in (tmp_path / "sortie").iterdir()) == noms
    assert not (tmp_path / "shared_prefs").exists()


def test_recuperer_exige_la_serie():
    with pytest.raises(SystemExit):
        A.recuperer("", "appli.exemple", "x")


def test_lister_et_seuils_s_affichent(tmp_path, capsys):
    ecrire_capture(tmp_path, "capture-20261110-100000-000", "reveil", [None, 0.7, 0.8])
    A.principal(["--dossier", str(tmp_path), "lister"])
    A.principal(["--dossier", str(tmp_path), "seuils", "--de", "0.5", "--a", "0.6", "--pas", "0.1"])
    sortie = capsys.readouterr().out
    assert "1 captures" in sortie and "reveil 1" in sortie and "réveils gardés" in sortie
    assert A.version() in sortie


def test_rejouer_avec_openwakeword(tmp_path):
    pytest.importorskip("openwakeword")
    ecrire_capture(tmp_path, "capture-20261110-100000-000", "reveil", [0.0] * 20, blocs=20)
    c = A.lire_captures(tmp_path)[0]
    try:
        r = A.scores_rejoues(c)
    except Exception as e:  # modèles d'openWakeWord non téléchargés sur ce poste
        pytest.skip(f"openWakeWord indisponible : {e}")
    assert len(r) == 20 and max(r) < 0.5
