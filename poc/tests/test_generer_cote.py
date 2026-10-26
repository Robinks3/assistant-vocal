"""carte/vent/generer_cote.py : trait de côte et terre de la carte du vent, depuis un GeoJSON fourni.

Aucun réseau : le générateur lit un fichier. La côte fictive de config-exemple/ (rade de Marseille arrondie) doit
rester reproductible octet pour octet depuis son GeoJSON source."""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
EXEMPLE = RACINE / "config-exemple"
SCRIPT = RACINE / "carte" / "vent" / "generer_cote.py"

spec = importlib.util.spec_from_file_location("generer_cote", SCRIPT)
GC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(GC)

CADRE = (0.0, 1.0, 0.0, 1.0)         # lat_min, lat_max, lon_min, lon_max
TAILLE = (100, 100)


def ligne(*points):
    return {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": [list(p) for p in points]}}


def anneau(*points):
    return {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon",
                                                              "coordinates": [[list(p) for p in points]]}}


def collection(*elements):
    return {"type": "FeatureCollection", "features": list(elements)}


def sans_cr(texte):
    return texte.replace("\r\n", "\n")


def cadre_et_taille_exemple():
    cfg = json.loads((EXEMPLE / "maison.json").read_text(encoding="utf-8"))["vent"]
    return tuple(cfg["cadre"]), (cfg["carte"]["largeur"], cfg["carte"]["hauteur"]), cfg["carte"]


# ------------------------------------------------------------ la côte fictive de l'exemple
def test_la_cote_d_exemple_est_reproductible_depuis_sa_source():
    cadre, taille, carte = cadre_et_taille_exemple()
    source = json.loads((EXEMPLE / "carte" / "cote_source.geojson").read_text(encoding="utf-8"))
    cote, terre, bilan = GC.generer(source, cadre, taille)
    dossier = EXEMPLE / "genere" / "android"
    assert cote == sans_cr((dossier / carte["cote"]).read_text(encoding="utf-8")).strip()
    assert terre == sans_cr((dossier / carte["terre"]).read_text(encoding="utf-8")).strip()
    assert bilan == {"lignes": 1, "terres": 1, "iles": 4, "ouvertes_non_fermees": 0}


def test_deux_executions_donnent_les_memes_octets(tmp_path):
    sorties = []
    for n in (1, 2):
        dossier = tmp_path / str(n)
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(EXEMPLE / "carte" / "cote_source.geojson"),
                            "--cadre", "43.2", "43.32", "5.22", "5.47", "--taille", "640", "423",
                            "--sortie", str(dossier), "--cote", "c.txt", "--terre", "t.txt"],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        sorties.append((dossier / "c.txt").read_bytes() + (dossier / "t.txt").read_bytes())
    assert sorties[0] == sorties[1] and len(sorties[0]) > 800


def test_la_ligne_de_commande_suit_la_configuration(tmp_path):
    """Sans --cadre ni --taille, le cadre et les chemins viennent de maison.json (config-exemple/ ici)."""
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(EXEMPLE / "carte" / "cote_source.geojson"),
                        "--sortie", str(tmp_path)], capture_output=True, text=True, timeout=60,
                       env={"ASSISTANT_VOCAL_CONFIG": str(EXEMPLE), "SystemRoot": str(Path(sys.executable).anchor)})
    assert r.returncode == 0, r.stderr
    cadre, taille, carte = cadre_et_taille_exemple()
    for cle in ("cote", "terre"):
        attendu = sans_cr((EXEMPLE / "genere" / "android" / carte[cle]).read_text(encoding="utf-8")).strip()
        assert sans_cr((tmp_path / carte[cle]).read_text(encoding="utf-8")).strip() == attendu


# ------------------------------------------------------------ géométrie
def test_terre_a_gauche_de_la_ligne_comme_openstreetmap():
    """Côte du nord au sud : la terre est à l'est, refermée par les coins du cadre agrandi."""
    src = collection(ligne((0.5, 1.2), (0.5, -0.2)))
    cote, terre, _ = GC.generer(src, CADRE, TAILLE, marge=10)
    assert cote == "M50,-10 L50,110"
    assert terre == "M50,-10 L50,110 L110,110 L110,-10 Z"


def test_terre_a_droite_si_demande():
    src = collection(ligne((0.5, 1.2), (0.5, -0.2)))
    _, terre, _ = GC.generer(src, CADRE, TAILLE, marge=10, terre_a_gauche=False)
    assert terre == "M50,-10 L50,110 L-10,110 L-10,-10 Z"


def test_la_projection_est_celle_de_l_appli():
    """y vers le bas : lat_max en haut. Un point au quart du cadre tombe au quart de la carte."""
    proj = GC.projeteur((10.0, 12.0, 4.0, 8.0), (400, 200))
    assert proj(4.0, 12.0) == (0.0, 0.0)
    assert proj(8.0, 10.0) == (400.0, 200.0)
    assert proj(5.0, 11.5) == (100.0, 50.0)


def test_les_lignes_jointes_forment_une_seule_cote():
    a = ligne((0.5, 1.2), (0.5, 0.5))
    b = ligne((0.5, -0.2), (0.5, 0.5))          # sens inverse, extrémité commune
    cote, terre, bilan = GC.generer(collection(a, b), CADRE, TAILLE, marge=10)
    assert bilan["lignes"] == 1 and cote == "M50,-10 L50,50 L50,110"
    assert terre.startswith("M50,-10")


def test_les_iles_sont_dans_les_deux_fichiers_et_celles_hors_cadre_sautent():
    ile = anneau((0.2, 0.2), (0.3, 0.2), (0.3, 0.3), (0.2, 0.2))
    loin = anneau((5, 5), (5.1, 5), (5.1, 5.1), (5, 5))
    cote, terre, bilan = GC.generer(collection(ligne((0.5, 1.2), (0.5, -0.2)), ile, loin), CADRE, TAILLE, marge=10)
    assert bilan["iles"] == 1
    motif = "M20,80 L30,80 L30,70 Z"
    assert motif in cote and motif in terre


def test_deux_morceaux_de_cote_referment_deux_terres():
    """Une baie : la côte sort du cadre et y rentre, la terre est refermée morceau par morceau."""
    nord = ligne((0.1, 1.2), (0.1, 0.8), (0.3, 0.8), (0.3, 1.2))        # presqu'île au nord, terre à l'est
    sud = ligne((0.9, -0.2), (0.9, 0.2), (0.7, 0.2), (0.7, -0.2))
    cote, terre, bilan = GC.generer(collection(nord, sud), CADRE, TAILLE, marge=10)
    assert bilan["lignes"] == 2 and bilan["ouvertes_non_fermees"] == 0
    assert bilan["terres"] >= 1 and terre.count("Z") == bilan["terres"]


def test_une_ligne_qui_ne_touche_pas_le_bord_n_enferme_rien():
    cote, terre, bilan = GC.generer(collection(ligne((0.3, 0.3), (0.6, 0.6))), CADRE, TAILLE, marge=10)
    assert cote == "M30,70 L60,40" and terre == "" and bilan["ouvertes_non_fermees"] == 1


def test_simplification_reduit_les_points_sans_toucher_aux_extremites():
    pts = [(0.5 + (0.01 if i % 2 else 0.0), 1.2 - i * 0.02) for i in range(70)]
    src = collection(ligne(*pts))
    brut, _, _ = GC.generer(src, CADRE, TAILLE, marge=10)
    simple, _, _ = GC.generer(src, CADRE, TAILLE, marge=10, tolerance=1.5)
    assert simple.count("L") < brut.count("L") and brut.count("L") > 40
    assert re.fullmatch(r"M5[01],-10 L5[01],110", simple)


# ------------------------------------------------------------ entrées invalides
@pytest.mark.parametrize("objet", [[], {"type": "FeatureCollection", "features": []}, {"type": "Point", "coordinates": [1, 2]},
                                   {"type": "FeatureCollection", "features": [ligne((1, 2))]}])
def test_entree_sans_ligne_ni_contour(objet):
    with pytest.raises(GC.ErreurCote):
        GC.generer(objet, CADRE, TAILLE)


def test_point_illisible_dit_ce_qui_ne_va_pas():
    mauvais = {"type": "LineString", "coordinates": [[0.1, 0.2], ["a", "b"]]}
    with pytest.raises(GC.ErreurCote, match="point GeoJSON illisible"):
        GC.generer(mauvais, CADRE, TAILLE)


def test_cote_hors_cadre():
    with pytest.raises(GC.ErreurCote, match="aucune côte dans le cadre"):
        GC.generer(collection(ligne((50, 50), (51, 51))), CADRE, TAILLE)


def test_cadre_incoherent():
    with pytest.raises(GC.ErreurCote, match="incohérent"):
        GC.generer(collection(ligne((0.5, 0.5), (0.6, 0.6))), (1.0, 0.0, 0.0, 1.0), TAILLE)


def test_ligne_de_commande_fichier_absent_ou_abime(tmp_path):
    for contenu in (None, "pas du json"):
        entree = tmp_path / "source.geojson"
        if contenu is not None:
            entree.write_text(contenu, encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(entree), "--cadre", "0", "1", "0", "1",
                            "--taille", "100", "100", "--sortie", str(tmp_path / "s")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 1 and "generer_cote : fichier GeoJSON illisible" in r.stderr
        assert not (tmp_path / "s").exists()


def test_le_script_ne_cite_aucune_valeur_de_configuration_reelle():
    """Le générateur lit tout dans la configuration ou les arguments : pas de coordonnée en dur."""
    texte = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{1,2}\.\d{3,}\b", texte.split('"""', 2)[2])
