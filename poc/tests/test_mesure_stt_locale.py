"""Comparaison des moteurs de reconnaissance (S-D8) : la comparaison de mots de l'outil `mesure_stt_locale.py`.

Seule la partie pure est testée (normalisation, erreurs de mots, écritures acceptées pour un nombre, bruit). Les
moteurs eux-mêmes ne tournent pas ici : l'outil se lance à la main, hors ligne, sur les modèles du disque."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "outils"))
import mesure_stt_locale as M


def test_normaliser_ignore_accents_ponctuation_et_casse():
    assert M.normaliser("Éteins la lumière, s'il te plaît !") == ["eteins", "la", "lumiere", "s", "il", "te", "plait"]


def test_pourcentage_devient_deux_mots():
    assert M.normaliser("à 40%") == ["a", "40", "pour", "cent"]


def test_phrase_exacte_sans_erreur():
    assert M.erreurs_mots("Bonne nuit.", "bonne nuit") == (0, 2)


def test_un_mot_faux_compte_une_erreur():
    assert M.erreurs_mots("Éteins la télé.", "Éteint la télé.") == (1, 3)


def test_mot_manquant_et_mot_ajoute():
    assert M.erreurs_mots("Coupe le son.", "Coupe son.")[0] == 1
    assert M.erreurs_mots("Coupe le son.", "Coupe le son fort.")[0] == 1


def test_nombre_en_chiffres_accepte_comme_en_lettres():
    dit = "Mets un minuteur de douze minutes."
    assert M.erreurs_mots(dit, "Mets un minuteur de 12 minutes.")[0] == 0
    assert M.erreurs_mots(dit, "Mets un minuteur de douze minutes.")[0] == 0
    assert M.erreurs_mots(dit, "Mets un minuteur de 13 minutes.")[0] == 1


def test_heure_acceptee_sous_ses_deux_ecritures():
    dit = "Réveille-moi demain à sept heures et demie."
    assert M.erreurs_mots(dit, "Réveille-moi demain à 7h30.")[0] == 0
    assert M.erreurs_mots(dit, "Réveille-moi demain à 7 h 30.")[0] == 0


def test_wer_en_pourcentage_sur_plusieurs_phrases():
    paires = [("Bonne nuit.", "Bonne nuit."), ("Éteins la télé.", "Éteint la télé.")]
    assert round(M.wer(paires), 1) == 20.0  # 1 erreur sur 5 mots


def test_wer_vide():
    assert M.wer([]) == 0.0


def test_toutes_les_variantes_visent_une_phrase_de_la_liste():
    assert set(M.VARIANTES) <= set(M.PHRASES)


def test_bruit_reproductible_et_au_bon_rapport_signal_sur_bruit():
    x = (0.3 * np.sin(np.linspace(0, 200, 16000))).astype(np.float32)
    y = M.ajouter_bruit(x, 15, graine=3)
    assert np.array_equal(y, M.ajouter_bruit(x, 15, graine=3))
    rsb = 10 * np.log10(np.mean(x ** 2) / np.mean((y - x) ** 2))
    assert 14 < rsb < 16
