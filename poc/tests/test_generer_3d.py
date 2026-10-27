"""carte/3d/generer_3d.py : tourne de bout en bout sur config-exemple/ et donne deux fois la même sortie.

Le test travaille sur une copie en dossier temporaire : rien n'est écrit dans config-exemple/."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
EXEMPLE = RACINE / "config-exemple"
SCRIPT = RACINE / "carte" / "3d" / "generer_3d.py"


@pytest.fixture()
def copie(tmp_path):
    """Copie légère de la configuration d'exemple (maison.json et carte/, sans le dictionnaire généré)."""
    dest = tmp_path / "config"
    dest.mkdir()
    shutil.copy2(EXEMPLE / "maison.json", dest / "maison.json")
    shutil.copytree(EXEMPLE / "carte", dest / "carte", ignore=shutil.ignore_patterns("modele.glb"))
    return dest


def lancer(config):
    env = dict(os.environ, ASSISTANT_VOCAL_CONFIG=str(config))
    return subprocess.run([sys.executable, "-I", str(SCRIPT)], cwd=config, env=env, capture_output=True,
                          text=True, timeout=120)


def sorties(config):
    return (config / "carte" / "modele.glb", config / "genere" / "android" / "maison3d" / "vue3d.html")


def test_c11_tourne_de_bout_en_bout_sur_l_exemple(copie):
    r = lancer(copie)
    assert r.returncode == 0, r.stderr
    glb, page = sorties(copie)
    assert glb.read_bytes()[:4] == b"glTF" and glb.stat().st_size > 1000
    html = page.read_text(encoding="utf-8")
    meubles = json.loads((copie / "carte" / "meubles.json").read_text(encoding="utf-8"))
    assert meubles["version"] in html and "{{" not in html and "/*SCENE*/" not in html and "/*THREE*/" not in html
    assert "modele.glb" in r.stdout and "nœuds" in r.stdout


def test_s_l5_la_page_porte_le_retour_d_etat(copie):
    """0.42.0 : couche neutralisante sous la tache, pas de halo dans la maison entière, état posé sans animation
    quand la page est en pause (requestAnimationFrame gelé par la WebView masquée)."""
    assert lancer(copie).returncode == 0
    html = sorties(copie)[1].read_text(encoding="utf-8")
    # couche neutralisante, réglée par jeu de teintes
    assert "neutre" in html and html.count("forceNeutre") >= 3
    # maison entière : plus de halo ni de tache, et le calcul est refait à chaque changement de vue
    assert "grandEtat.actif && !grandEtat.piece" in html
    assert "!vueEntiere && lp.halo.material.opacity" in html and "!vueEntiere && lp.flaque.material.opacity" in html
    assert html.count("majVueEntiere()") >= 3
    # état reçu en pause : posé tout de suite
    assert "if (enPause) instant = true;" in html
    # kelvins convertis par la page, couleur de la lampe prise telle que l'appli l'envoie
    assert "kelvinVersCouleur(a.color_temp_kelvin)" in html and "a.rgb_color" in html


def test_s_l8_toucher_la_carte_des_mesures_est_designe_a_l_appli(copie):
    """La carte des mesures de la pièce choisie est touchable : la page désigne le genre `mesures` avec l'id de la pièce,
    sauf pièce protégée ou sans capteur (aucune ligne), pour que l'appli ouvre le graphique de l'air."""
    assert lancer(copie).returncode == 0
    html = sorties(copie)[1].read_text(encoding="utf-8")
    assert 'genre: "mesures", id: grandEtat.piece' in html
    assert 'mc.statut !== "protegee" && mc.statut !== "aucun"' in html
    # le hit-test passe avant la désignation d'une pièce par le sol
    debut = html.index("function designer(x, y)")
    assert debut < html.index('genre: "mesures"') < html.index("lanceur.setFromCamera(new T.Vector2(x / innerWidth", debut)


def test_s_l7_la_page_porte_les_mesures_par_piece(copie):
    """Mesures dans la vue 3D : pastille sous le nom de chaque pièce, carton de la pièce choisie, message du pont
    `mesures`, tout échappé, couleur validée, et aucune requête réseau dans la page."""
    assert lancer(copie).returncode == 0
    html = sorties(copie)[1].read_text(encoding="utf-8")
    # le pont : export, message, carton
    assert "choisir, etiquettes, pastilles, mesures," in html
    assert "mesures: [d =>" in html and 'id="mesures"' in html and "function rendreMesures()" in html
    # la pastille de l'étiquette ne prend que le texte et la couleur envoyés par l'appli, échappés et validés
    assert "q.mesure.texte" in html and "couleurSure(q.mesure.couleur)" in html
    assert "#[0-9A-Fa-f]{6}" in html
    # pièce protégée ou sans capteur : seulement le texte, jamais de lignes de valeurs
    assert 'm.statut === "protegee" || m.statut === "aucun"' in html
    # la carte s'efface en quittant la maison en grand ou en choisissant la vue entière
    assert html.count("grandEtat.mesures = null") >= 2
    # toujours un mot à côté de la couleur
    assert "l.mot" in html
    # pas de réseau dans le code de la page (la bibliothèque 3D embarquée n'est pas concernée)
    modele = (SCRIPT.parent / "vue3d_modele.html").read_text(encoding="utf-8")
    assert "fetch(" not in modele and "XMLHttpRequest" not in modele and "WebSocket" not in modele


def test_c11_deux_executions_donnent_la_meme_sortie(copie):
    premiere = []
    for _ in range(2):
        r = lancer(copie)
        assert r.returncode == 0, r.stderr
        glb, page = sorties(copie)
        premiere.append((glb.read_bytes(), page.read_bytes()))
        shutil.rmtree(copie / "genere")
        glb.unlink()
    assert premiere[0] == premiere[1]


def test_c11_le_script_n_ecrit_que_dans_la_configuration_pointee(copie):
    avant = {p.relative_to(EXEMPLE) for p in EXEMPLE.rglob("*") if p.is_file()}
    assert lancer(copie).returncode == 0
    apres = {p.relative_to(EXEMPLE) for p in EXEMPLE.rglob("*") if p.is_file()}
    assert avant == apres


def test_c11_plan_absent_donne_un_message_clair(tmp_path):
    vide = tmp_path / "vide"
    vide.mkdir()
    shutil.copy2(EXEMPLE / "maison.json", vide / "maison.json")
    r = lancer(vide)
    assert r.returncode != 0 and "pieces.json" in r.stderr and "config-exemple/carte/" in r.stderr
