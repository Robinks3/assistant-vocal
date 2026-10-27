"""Réglage « mode développeur » du client web (0.8.0) : actif par défaut, gardé dans le navigateur, il masque sur toutes
les pages ce qui sert à déboguer (versions, durées, identifiants, détail des étapes) et jamais une information de
sécurité ni un message d'erreur utile. Il est transmis à la vue 3D isolée par un message booléen à schéma strict."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
WEB = RACINE / "web"
NODE = shutil.which("node")

PAGES = ("index", "appairage", "associer", "demander", "journal", "maison", "meteo", "reglages", "routines")


def lire(nom):
    return (WEB / nom).read_text(encoding="utf-8")


# ------------------------------------------------------------------ pages et feuille de style

def test_la_feuille_de_style_masque_ce_qui_est_marque_quand_le_mode_est_coupe():
    css = lire("app.css")
    assert 'html[data-dev="non"] .dev-seulement{display:none!important}' in css


@pytest.mark.parametrize("nom", [p for p in PAGES if p not in ("reglages", "journal")])  # ces deux-là n'ont pas de pied
def test_le_pied_de_page_des_versions_se_masque_avec_le_mode_developpeur(nom):
    html = lire(nom + ".html")
    pied = re.search(r'<p class="([^"]*)" aria-label="Versions">', html)
    assert pied, nom
    assert "dev-seulement" in pied.group(1).split(), nom
    for marque in ("{{version_client}}", "{{version_serveur}}", "{{date}}"):
        assert marque in html, (nom, marque)


def test_toutes_les_pages_chargent_le_client_qui_pose_l_attribut_avant_l_affichage():
    for nom in PAGES:
        html = lire(nom + ".html")
        assert 'src="/client.js"' in html, nom
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), nom


def test_le_resume_des_versions_des_reglages_se_masque_aussi():
    html = lire("reglages.html")
    assert re.search(r'<dl class="resume dev-seulement">\s*<div><dt>Client web</dt>', html)


def test_la_carte_du_reglage_est_active_par_defaut_et_accessible():
    html = lire("reglages.html")
    carte = html[html.index('id="carte-developpeur"'):]
    carte = carte[:carte.index("</section>")]
    assert 'aria-labelledby="titre-developpeur"' in html and 'id="titre-developpeur"' in carte
    bouton = re.search(r'<button id="bascule-dev"[^>]*>', carte)
    assert bouton and 'role="switch"' in bouton.group(0) and 'aria-checked="true"' in bouton.group(0)
    assert 'type="button"' in bouton.group(0)
    assert re.search(r'id="dev-etat"[^>]*>Oui<', carte)


def test_le_script_des_reglages_branche_la_bascule_sur_le_client():
    js = lire("reglages.js")
    assert 'C.reglerDeveloppeur(!C.modeDeveloppeur())' in js and "C.surModeDeveloppeur(afficherDev)" in js
    assert 'setAttribute("aria-checked"' in js


def test_ce_qui_est_technique_est_marque_et_rien_de_securite_ne_l_est():
    marques = {nom: lire(nom).count("dev-seulement") for nom in ("journal.js", "reglages.js", "demander.html",
                                                                  "journal.html")}
    assert all(n >= 1 for n in marques.values()), marques
    # jamais un message d'erreur, une alerte ou une information de sécurité derrière la classe
    for nom in [p + ".html" for p in PAGES] + ["journal.js", "reglages.js", "meteo.js", "maison.js", "demander.js",
                                                   "routines.js"]:
        chemin = WEB / nom
        if not chemin.exists():
            continue
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            if "dev-seulement" not in ligne:
                continue
            assert not re.search(r'role="(alert|status)"|erreur|sécurité|securite|jeton|clé d|mot de passe', ligne, re.I), (
                nom, ligne.strip())


def test_le_client_est_le_seul_script_a_toucher_le_stockage_local_et_ne_garde_qu_un_oui_ou_non():
    for chemin in sorted(WEB.glob("*.js")):
        js = chemin.read_text(encoding="utf-8")
        assert "sessionStorage" not in js and "indexedDB" not in js and "document.cookie" not in js, chemin.name
        if chemin.name != "client.js":
            assert "localStorage" not in js, chemin.name
    client = lire("client.js")
    assert client.count("localStorage") == 2, "une lecture, une écriture"
    assert 'var CLE_DEV = "modeDeveloppeur";' in client
    assert 'actif ? "oui" : "non"' in client
    assert client.count("try {") >= 3, "chaque accès au stockage est protégé"


def test_les_trois_ecrans_techniques_masquent_les_durees_et_le_detail_des_etapes():
    demander = lire("demander.html")
    assert re.search(r'id="duree-ecoute" class="[^"]*\bdev-seulement\b', demander)
    assert re.search(r'id="carte-etapes" class="[^"]*\bdev-seulement\b', demander)
    journal = lire("journal.html")
    assert re.search(r'id="etapes-encours" class="[^"]*\bdev-seulement\b', journal)
    assert re.search(r'id="detail-etapes" class="[^"]*\bdev-seulement\b', journal)


# ------------------------------------------------------------------ comportement du client sous node

HARNAIS = r"""
const evenements = {};
let magasin = /*MAGASIN*/ {};
const stockage = /*STOCKAGE*/ null;
const racine = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } };
globalThis.document = { documentElement: racine };
globalThis.window = {
  addEventListener: (t, f) => { evenements[t] = f; },
  atob: globalThis.atob,
};
if (stockage === "ok") {
  window.localStorage = { getItem: k => (k in magasin ? magasin[k] : null), setItem: (k, v) => { magasin[k] = String(v); } };
} else if (stockage === "refus") {
  Object.defineProperty(window, "localStorage", { get() { throw new Error("refusé"); } });
}
globalThis.crypto = {}; globalThis.navigator = {};
/*CLIENT*/
const C = window.Client;
const sortie = { initial: racine.attrs["data-dev"], etapes: [] };
/*SCENARIO*/
console.log(JSON.stringify(sortie));
"""


def executer(tmp_path, stockage, magasin, scenario):
    script = (HARNAIS.replace("/*CLIENT*/", lire("client.js")).replace("/*SCENARIO*/", scenario)
              .replace("/*MAGASIN*/ {}", json.dumps(magasin)).replace("/*STOCKAGE*/ null", json.dumps(stockage)))
    fichier = tmp_path / "client_dev.js"
    fichier.write_text(script, encoding="utf-8")
    r = subprocess.run([NODE, str(fichier)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


SCENARIO_BASCULE = """
const vus = [];
C.surModeDeveloppeur(a => vus.push(a));
sortie.etapes.push([C.modeDeveloppeur(), racine.attrs["data-dev"]]);
sortie.etapes.push([C.reglerDeveloppeur(false), C.modeDeveloppeur(), racine.attrs["data-dev"], magasin["modeDeveloppeur"]]);
sortie.etapes.push([C.reglerDeveloppeur(true), C.modeDeveloppeur(), racine.attrs["data-dev"], magasin["modeDeveloppeur"]]);
sortie.vus = vus;
"""


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_actif_par_defaut_sans_rien_de_stocke(tmp_path):
    s = executer(tmp_path, "ok", {}, SCENARIO_BASCULE)
    assert s["initial"] == "oui"
    assert s["etapes"][0] == [True, "oui"]


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_la_bascule_est_gardee_appliquee_et_annoncee_aux_ecouteurs(tmp_path):
    s = executer(tmp_path, "ok", {}, SCENARIO_BASCULE)
    assert s["etapes"][1] == [False, False, "non", "non"]
    assert s["etapes"][2] == [True, True, "oui", "oui"]
    assert s["vus"] == [True, False, True], "appel immédiat, puis un appel par changement"


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_un_reglage_coupe_est_relu_au_chargement_de_la_page(tmp_path):
    s = executer(tmp_path, "ok", {"modeDeveloppeur": "non"}, "sortie.etapes.push(C.modeDeveloppeur());")
    assert s["initial"] == "non" and s["etapes"] == [False]


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_une_valeur_stockee_inconnue_laisse_le_mode_actif(tmp_path):
    for valeur in ("peut-etre", "", "0", "false", "NON"):
        s = executer(tmp_path, "ok", {"modeDeveloppeur": valeur}, "sortie.etapes.push(C.modeDeveloppeur());")
        assert s["initial"] == "oui" and s["etapes"] == [True], valeur


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_un_navigateur_qui_refuse_le_stockage_garde_le_reglage_en_memoire(tmp_path):
    s = executer(tmp_path, "refus", {}, SCENARIO_BASCULE)
    assert s["initial"] == "oui"
    assert s["etapes"][0] == [True, "oui"]
    assert s["etapes"][1][:3] == [False, False, "non"]
    assert s["etapes"][2][:3] == [True, True, "oui"]


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_sans_objet_de_stockage_le_mode_reste_actif_et_la_bascule_fonctionne(tmp_path):
    s = executer(tmp_path, None, {}, SCENARIO_BASCULE)
    assert s["initial"] == "oui" and s["etapes"][1][:3] == [False, False, "non"]


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_un_changement_venu_d_un_autre_onglet_est_repris(tmp_path):
    scenario = """
const vus = [];
C.surModeDeveloppeur(a => vus.push(a));
magasin["modeDeveloppeur"] = "non";
evenements.storage({ key: "modeDeveloppeur" });
sortie.etapes.push([racine.attrs["data-dev"], vus.slice()]);
magasin["modeDeveloppeur"] = "oui";
evenements.storage({ key: "autre" });
sortie.etapes.push([racine.attrs["data-dev"], vus.slice()]);
evenements.storage({ key: null });
sortie.etapes.push([racine.attrs["data-dev"], vus.slice()]);
"""
    s = executer(tmp_path, "ok", {}, scenario)
    assert s["etapes"][0] == ["non", [True, False]]
    assert s["etapes"][1] == ["non", [True, False]], "une autre clé ne change rien"
    assert s["etapes"][2] == ["oui", [True, False, True]], "un effacement complet remet l'état stocké"


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_un_ecouteur_fautif_n_empeche_ni_la_bascule_ni_les_autres_ecouteurs(tmp_path):
    scenario = """
const vus = [];
C.surModeDeveloppeur(() => { throw new Error("écouteur cassé"); });
C.surModeDeveloppeur(a => vus.push(a));
C.reglerDeveloppeur(false);
sortie.etapes.push([racine.attrs["data-dev"], vus]);
"""
    s = executer(tmp_path, "ok", {}, scenario)
    assert s["etapes"][0] == ["non", [True, False]]


# ------------------------------------------------------------------ pont vers la vue 3D isolée

def test_la_page_parente_envoie_l_etat_a_l_ouverture_et_a_chaque_changement():
    js = lire("maison.js")
    assert 'poster3d({ type: "modeDeveloppeur", actif: C.modeDeveloppeur() });' in js
    assert re.search(r'C\.surModeDeveloppeur\(function \(actif\) \{ poster3d\(\{ type: "modeDeveloppeur", actif: actif \}\); \}\);',
                     js)


def test_la_vue_3d_declare_le_message_booleen_et_masque_version_et_panneau():
    texte = (RACINE.parent / "carte" / "3d" / "vue3d_modele.html").read_text(encoding="utf-8")
    assert "modeDeveloppeur: actif => { document.body.classList.toggle(\"sans-dev\", !actif); }," in texte
    assert "modeDeveloppeur: [d => [bo(d.actif)], a => window.vue3d.modeDeveloppeur(a)]," in texte
    assert re.search(r"const PONT_BOOL = \{[^}]*\bmodeDeveloppeur: 0\b", texte)
    assert "body.sans-dev #version, body.sans-dev #panneau { display: none; }" in texte
    # la page isolée ne lit jamais le stockage : l'hôte lui transmet l'état
    assert "localStorage" not in texte
