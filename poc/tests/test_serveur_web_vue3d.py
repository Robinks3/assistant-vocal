"""Vue 3D du client web (S-W4b) : la page vue3d.html servie par le serveur web avec sa propre CSP, et le pont
postMessage strict entre cette page et l'écran Maison.

La page est celle que produit carte/3d/generer_3d.py sur config-exemple/ (une seule génération pour tout le module).
Les empreintes de la CSP sont recalculées ici par un autre chemin que celui du serveur (un analyseur HTML, pas une
expression régulière). Le schéma du pont, côté page, est exécuté sous node avec des fenêtres factices : un message
mal formé ne doit rien appeler."""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

import serveur_web as W
from test_serveur_web_appairage import (  # noqa: F401  (fixtures réutilisées)
    appairer_direct, entetes, horloge, journal, service, statut_de)

RACINE = Path(__file__).resolve().parents[2]
EXEMPLE = RACINE / "config-exemple"
SCRIPT = RACINE / "carte" / "3d" / "generer_3d.py"
MODELE = RACINE / "carte" / "3d" / "vue3d_modele.html"
MAISON_JS = RACINE / "poc" / "web" / "maison.js"
MAISON_HTML = RACINE / "poc" / "web" / "maison.html"


@pytest.fixture(scope="module")
def page_reelle(tmp_path_factory):
    """vue3d.html produite sur la configuration d'exemple : (chemin du fichier, texte)."""
    config = tmp_path_factory.mktemp("config3d")
    shutil.copy2(EXEMPLE / "maison.json", config / "maison.json")
    shutil.copytree(EXEMPLE / "carte", config / "carte", ignore=shutil.ignore_patterns("modele.glb"))
    env = dict(os.environ, ASSISTANT_VOCAL_CONFIG=str(config))
    r = subprocess.run([sys.executable, "-I", str(SCRIPT)], cwd=config, env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    chemin = config / "genere" / "android" / "maison3d" / "vue3d.html"
    return chemin, chemin.read_text(encoding="utf-8")


class _Blocs(HTMLParser):
    """Contenu exact de chaque bloc script ou style en ligne, et de chaque script avec src."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.blocs = []        # [balise, texte]
        self.externes = []
        self.attributs = []    # (balise, nom) de chaque attribut style ou on...
        self._ouvert = None

    def handle_starttag(self, tag, attrs):
        for nom, _ in attrs:
            if nom == "style" or nom.startswith("on"):
                self.attributs.append((tag, nom))
        if tag in ("script", "style"):
            if tag == "script" and any(n == "src" for n, _ in attrs):
                self.externes.append(tag)
                return
            self._ouvert = [tag, ""]
            self.blocs.append(self._ouvert)

    def handle_endtag(self, tag):
        if self._ouvert and tag == self._ouvert[0]:
            self._ouvert = None

    def handle_data(self, data):
        if self._ouvert:
            self._ouvert[1] += data


def empreinte(texte):
    return "'sha256-" + base64.b64encode(hashlib.sha256(texte.encode("utf-8")).digest()).decode("ascii") + "'"


def directive(csp, nom):
    for d in csp.split(";"):
        d = d.strip()
        if d == nom or d.startswith(nom + " "):
            return d[len(nom):].split()
    return None


# La page réelle et ses empreintes

def test_la_page_reelle_n_a_ni_script_externe_ni_attribut_style_ni_gestionnaire_en_ligne(page_reelle):
    _, texte = page_reelle
    a = _Blocs()
    a.feed(texte)
    assert a.externes == [], "un script avec src serait refusé par la CSP (script-src sans 'self')"
    assert a.attributs == []
    assert len([b for b in a.blocs if b[0] == "script"]) >= 1 and len([b for b in a.blocs if b[0] == "style"]) >= 1


def test_les_empreintes_de_la_csp_sont_exactement_celles_des_blocs_de_la_page(page_reelle):
    _, texte = page_reelle
    a = _Blocs()
    a.feed(texte)
    scripts = [empreinte(t) for b, t in a.blocs if b == "script"]
    styles = [empreinte(t) for b, t in a.blocs if b == "style"]
    csp = W.csp_vue3d(texte)
    assert directive(csp, "script-src") == scripts
    assert directive(csp, "style-src") == styles
    # le serveur et l'analyseur indépendant s'accordent aussi sur la fonction publique
    assert W.empreintes_en_ligne(texte) == (scripts, styles)


def test_la_csp_de_la_vue_3d_ne_laisse_ni_reseau_ni_cadre_ni_formulaire_ni_worker(page_reelle):
    _, texte = page_reelle
    csp = W.csp_vue3d(texte)
    assert directive(csp, "default-src") == ["'none'"]
    for nom in ("connect-src", "font-src", "media-src", "object-src", "worker-src", "frame-src", "base-uri",
                "form-action"):
        assert directive(csp, nom) == ["'none'"], nom
    assert directive(csp, "frame-ancestors") == ["'self'"]
    assert directive(csp, "sandbox") == ["allow-scripts"]
    assert directive(csp, "require-trusted-types-for") == ["'script'"]
    assert directive(csp, "img-src") == ["data:", "blob:"]
    # aucune source large ni exception d'exécution
    sources = [s for d in csp.split(";") for s in d.split()[1:]]
    for interdit in ("'unsafe-inline'", "'unsafe-eval'", "*", "http:", "https:", "'unsafe-hashes'", "'strict-dynamic'"):
        assert interdit not in sources, interdit
    assert "'self'" not in directive(csp, "script-src") and "'self'" not in directive(csp, "style-src")


def test_une_page_sans_bloc_en_ligne_donne_none_et_un_script_externe_n_est_pas_compte():
    assert W.empreintes_en_ligne("<p>rien</p>") == ([], [])
    csp = W.csp_vue3d("<p>rien</p>")
    assert directive(csp, "script-src") == ["'none'"] and directive(csp, "style-src") == ["'none'"]
    scripts, styles = W.empreintes_en_ligne('<script src="/x.js"></script><script>let a=1;</script><style>b{}</style>')
    assert scripts == [empreinte("let a=1;")] and styles == [empreinte("b{}")]


def test_modifier_un_octet_de_la_page_change_l_empreinte():
    a = W.empreintes_en_ligne("<script>let a=1;</script>")[0]
    b = W.empreintes_en_ligne("<script>let a=2;</script>")[0]
    assert a != b


# La route /vue3d

def test_vue3d_exige_une_session_et_ne_redirige_pas(service, journal):
    rep = service.traiter("127.0.0.1", "/vue3d", entetes())
    assert statut_de(rep) == 401 and "Location" not in rep[1]


@pytest.mark.parametrize("role", ["administrateur", "habitant", "invite"])
def test_vue3d_est_servie_avec_sa_csp_a_chaque_role(service, journal, page_reelle, role):
    chemin, texte = page_reelle
    service.fichier_3d = str(chemin)
    _, _, jeton = appairer_direct(service, role, "Appareil " + role)
    rep = service.traiter("127.0.0.1", "/vue3d", entetes(jeton))
    assert statut_de(rep) == 200
    assert rep[2].decode("utf-8") == texte
    h = rep[1]
    assert h["Content-Security-Policy"] == W.csp_vue3d(texte)
    assert h["Content-Security-Policy"] != W.CSP
    assert "text/html" in h["Content-Type"]
    assert h["Cache-Control"] in ("no-store", "no-cache")
    assert h["X-Content-Type-Options"] == "nosniff"
    # cadrable par l'écran Maison seulement : ni DENY, ni cadre ouvert
    assert h.get("X-Frame-Options", "").upper() != "DENY"
    assert directive(h["Content-Security-Policy"], "frame-ancestors") == ["'self'"]


def test_vue3d_absente_donne_404_sans_casser_le_reste(service, journal, tmp_path):
    service.fichier_3d = str(tmp_path / "n-existe-pas.html")
    _, _, jeton = appairer_direct(service, "habitant")
    assert statut_de(service.traiter("127.0.0.1", "/vue3d", entetes(jeton))) == 404
    assert statut_de(service.traiter("127.0.0.1", "/maison", entetes(jeton))) == 200


def test_la_csp_globale_n_est_pas_celle_de_la_vue_3d_et_autorise_l_iframe_de_meme_origine():
    assert directive(W.CSP, "frame-src") == ["'self'"]
    assert directive(W.CSP, "frame-ancestors") == ["'none'"]
    assert "sandbox" not in W.CSP


def test_les_autres_pages_gardent_la_csp_globale(service, journal):
    _, _, jeton = appairer_direct(service, "habitant")
    rep = service.traiter("127.0.0.1", "/maison", entetes(jeton))
    assert statut_de(rep) == 200 and rep[1]["Content-Security-Policy"] == W.CSP


# L'iframe côté parent

def test_l_iframe_est_isolee_sans_same_origin_et_sans_autres_permissions():
    js = MAISON_JS.read_text(encoding="utf-8")
    assert "allow-same-origin" not in js
    assert js.count('setAttribute("sandbox", "allow-scripts")') == 1
    # le sandbox est posé avant l'adresse : la page ne charge jamais hors isolation
    assert js.index('setAttribute("sandbox"') < js.index('f.src = "/vue3d"')
    for permission in ("allow-forms", "allow-popups", "allow-top-navigation", "allow-modals", "allow-downloads"):
        assert permission not in js
    assert 'setAttribute("referrerpolicy", "no-referrer")' in js
    html = MAISON_HTML.read_text(encoding="utf-8")
    assert "<iframe" not in html and "allow-same-origin" not in html


def test_le_parent_verifie_la_fenetre_et_l_origine_opaque_et_ne_poste_jamais_ailleurs_que_vers_l_iframe():
    js = MAISON_JS.read_text(encoding="utf-8")
    assert "ev.source !== vue3d.iframe.contentWindow" in js
    assert 'ev.origin !== "null"' in js
    assert js.count(".postMessage(") == 1 and "vue3d.iframe.contentWindow.postMessage(m," in js
    # le seul appel réseau du parent vers la page reste son chargement ; la page n'appelle pas le serveur
    assert "window.parent.postMessage" not in js and "opener" not in js


def test_le_parent_n_accepte_que_des_cles_exactes_et_des_identifiants_surs():
    js = MAISON_JS.read_text(encoding="utf-8")
    assert 'cles(m, ["type", "version"])' in js and "m.version.length <= 32" in js
    assert 'cles(m, ["type", "genre", "entite"])' in js and 'cles(m, ["type", "genre", "id"])' in js
    assert "ID_SUR.test(m.entite)" in js and "ID_SUR.test(m.id)" in js
    assert "if (volet) { return; }" in js, "une désignation pendant qu'un volet est ouvert est ignorée"


def test_les_messages_du_parent_a_la_page_sont_des_types_connus_seulement():
    js = MAISON_JS.read_text(encoding="utf-8")
    envoyes = set(re.findall(r'poster3d\(\{ type: "([a-zA-Z]+)"', js))
    assert envoyes == {"etats", "etiquettes", "choisir", "pastilles", "mesures", "grand", "modeDeveloppeur", "disposition", "vue"}
    page = MODELE.read_text(encoding="utf-8")
    pont = set(re.findall(r"^  ([a-zA-Z]+): \[d => ", page[page.index("const PONT = {"):], re.M))
    assert envoyes <= pont


# Le pont côté page, exécuté sous node

NODE = shutil.which("node")

HARNAIS = r"""
const appels = [], envoyes = [];
const rec = nom => (...a) => { appels.push([nom, ...a]); };
for (const n of ["etat", "etats", "poser", "demo", "montrer", "action", "attenuer", "ensemble", "teintes", "disposition",
                 "regler", "choisir", "etiquettes", "pastilles", "mesures"]) globalThis[n] = rec(n);
const JEUX = { neutre: 1, couleur: 1 };
const PARENT = { postMessage: (m, cible) => envoyes.push([m, cible]) };
const AUTRE = {};
globalThis.window = { parent: PARENT, vue3d: {} };
for (const n of ["rotation", "fondu", "nomsAuSol", "poussieres", "desaturer", "pause", "grand", "modeDeveloppeur", "vue"]) window.vue3d[n] = rec(n);
let ecouteur = null;
globalThis.addEventListener = (type, f) => { if (type === "message") ecouteur = f; };
/*PONT*/
const sortie = { recus: [], envoyes: [] };
for (const c of /*CAS_RECUS*/ []) {
  appels.length = 0;
  const ev = { source: c.source === "autre" ? AUTRE : PARENT, data: c.data };
  sortie.recus.push({ retour: ecouteur(ev), appels: JSON.parse(JSON.stringify(appels)) });
}
for (const m of /*CAS_ENVOYES*/ []) {
  envoyes.length = 0;
  const r = versHote(m);
  sortie.envoyes.push({ retour: r, envoyes: JSON.parse(JSON.stringify(envoyes)) });
}
console.log(JSON.stringify(sortie));
"""


def _pont_de_la_page():
    page = MODELE.read_text(encoding="utf-8")
    debut = page.index("// ---------- pont postMessage avec l'hôte")
    fin = page.index("\nconstruireListe();", debut)
    return page[debut:fin]


def executer_pont(tmp_path, recus, envoyes=()):
    script = (HARNAIS.replace("/*PONT*/", _pont_de_la_page())
              .replace("/*CAS_RECUS*/ []", json.dumps(recus)).replace("/*CAS_ENVOYES*/ []", json.dumps(list(envoyes))))
    f = tmp_path / "pont.js"
    f.write_text(script, encoding="utf-8")
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def parent(data):
    return {"source": "parent", "data": data}


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_la_page_applique_un_message_valide_du_parent_et_un_seul(tmp_path):
    s = executer_pont(tmp_path, [
        parent({"type": "choisir", "id": "salon", "duree": 800}),
        parent({"type": "etats", "etats": {"light.salon_plafond": {"state": "on", "attributes": {"brightness": 128}}}}),
        parent({"type": "grand", "actif": True, "taille": 44, "police": 14}),
        parent({"type": "modeDeveloppeur", "actif": False}),
        parent({"type": "modeDeveloppeur", "actif": True, "intrus": "x"}),
        parent({"type": "vue", "nom": "dessus"}),
    ])["recus"]
    assert s[0] == {"retour": True, "appels": [["choisir", "salon", 800]]}
    assert s[1]["retour"] is True and s[1]["appels"][0][0] == "etats"
    assert s[1]["appels"][0][1]["light.salon_plafond"] == {"attributes": {"brightness": 128}, "state": "on"}
    assert s[2] == {"retour": True, "appels": [["grand", True, 44, 14]]}
    assert s[3] == {"retour": True, "appels": [["modeDeveloppeur", False]]}
    assert s[4] == {"retour": True, "appels": [["modeDeveloppeur", True]]}
    assert s[5] == {"retour": True, "appels": [["vue", "dessus"]]}


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_la_page_rejette_sans_rien_appeler_les_messages_mal_formes(tmp_path):
    rejetes = [
        None, "choisir", 12, [], [["choisir"]], True,
        {}, {"type": 3}, {"type": None}, {"type": "inconnu"}, {"type": "__proto__"}, {"type": "constructor"},
        {"type": "toString"}, {"type": "hasOwnProperty"},
        {"type": "etats", "etats": "x"}, {"type": "etats", "etats": None}, {"type": "etats"},
        {"type": "etats", "etats": {f"light.a{i}": "on" for i in range(201)}},
        {"type": "etats", "etats": [{"entity_id": f"l{i}", "state": "on"} for i in range(201)]},
        {"type": "fondu"}, {"type": "fondu", "actif": "oui"}, {"type": "fondu", "actif": 1},
        {"type": "grand", "actif": None}, {"type": "pause", "actif": "true"},
        {"type": "modeDeveloppeur"}, {"type": "modeDeveloppeur", "actif": "oui"}, {"type": "modeDeveloppeur", "actif": 1},
        {"type": "modeDeveloppeur", "actif": None},
        {"type": "vue"}, {"type": "vue", "nom": "dessous"}, {"type": "vue", "nom": 1},
        {"type": "montrer", "cibles": ["x"] * 41}, {"type": "montrer", "entite": "a b c"},
        {"type": "montrer", "entite": "<img src=x onerror=alert(1)>"}, {"type": "montrer", "entite": "a" * 81},
        {"type": "etiquettes", "liste": "x"}, {"type": "etiquettes", "liste": [{}] * 41},
        {"type": "pastilles", "liste": {"a": 1}}, {"type": "pastilles", "liste": [1] * 41},
        {"type": "mesures", "charge": "texte"}, {"type": "mesures", "charge": 5}, {"type": "mesures"},
        {"type": "action", "effets": "x"}, {"type": "action", "effets": {f"e{i}": "allumer" for i in range(21)}},
        {"type": "teintes", "teintes": "x"}, {"type": "palette", "teintes": [1]},
    ]
    s = executer_pont(tmp_path, [parent(d) for d in rejetes])["recus"]
    for d, r in zip(rejetes, s):
        # une valeur absente de charge ou une charge nulle est permise pour « mesures » (retirer le panneau), pas le reste
        assert r["retour"] is False and r["appels"] == [], d


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_la_page_ignore_tout_message_qui_ne_vient_pas_de_la_fenetre_parente(tmp_path):
    valide = {"type": "choisir", "id": "salon", "duree": 0}
    s = executer_pont(tmp_path, [{"source": "autre", "data": valide}, parent(valide)])["recus"]
    assert s[0] == {"retour": False, "appels": []}
    assert s[1]["retour"] is True


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_la_page_borne_les_nombres_et_nettoie_les_champs_inconnus(tmp_path):
    s = executer_pont(tmp_path, [
        parent({"type": "choisir", "id": "salon", "duree": 10 ** 9}),
        parent({"type": "rotation", "periode": -5, "ips": 999, "cadre": 3, "amplitude": 1000, "angle": 5000}),
        parent({"type": "grand", "actif": True, "taille": 1, "police": 1000, "intrus": "x"}),
        parent({"type": "etats", "etats": {"light.a": {"state": "on", "brightness": 9999, "intrus": {"a": 1}, "rgb_color": [1, 2]},
                                          "bad id!": "on", "x" * 81: "on"}}),
    ])["recus"]
    assert s[0]["appels"] == [["choisir", "salon", 10000]]
    assert s[1]["appels"] == [["rotation", 0, 30, 3, 180, 720]]
    assert s[2]["appels"] == [["grand", True, 8, 80]]
    assert s[3]["appels"][0][1] == {"light.a": {"attributes": {"brightness": 255}, "state": "on"}}


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_la_page_n_emet_que_pret_et_designation_avec_des_champs_sers(tmp_path):
    bons = [
        {"type": "pret", "version": "0.8.0"},
        {"type": "designation", "genre": "lampe", "entite": "light.salon_plafond"},
        {"type": "designation", "genre": "pastille", "entite": "media_player.tele_salon"},
        {"type": "designation", "genre": "piece", "id": "salon"},
        {"type": "designation", "genre": "mesures", "id": "salon"},
    ]
    mauvais = [
        None, "pret", [], {}, {"type": "pret"}, {"type": "pret", "version": 7}, {"type": "pret", "version": "x" * 33},
        {"type": "designation"}, {"type": "designation", "genre": "lampe"},
        {"type": "designation", "genre": "lampe", "entite": "a b"},
        {"type": "designation", "genre": "piece", "entite": "salon"},
        {"type": "designation", "genre": "mesures", "id": "<b>"}, {"type": "designation", "genre": "tele", "entite": "x"},
        {"type": "regler", "entite": "light.salon_plafond"}, {"type": "appel", "service": "light.turn_on"},
        {"type": "ws", "cible": "wss://exemple.invalide"},
    ]
    s = executer_pont(tmp_path, [], bons + mauvais)["envoyes"]
    for m, r in zip(bons, s[:len(bons)]):
        assert r["retour"] is True and r["envoyes"] == [[m, "*"]], m
    for m, r in zip(mauvais, s[len(bons):]):
        assert r["retour"] is False and r["envoyes"] == [], m


def test_le_code_de_la_page_ne_porte_aucun_appel_direct_au_serveur():
    """Le serveur ne reçoit rien de la page 3D : aucun réseau, aucun stockage, aucun cookie lu depuis elle. Le test
    porte sur le modèle, hors bibliothèque three.js (qui contient des chargeurs que la CSP rend inopérants)."""
    a = _Blocs()
    a.feed(MODELE.read_text(encoding="utf-8"))
    code = "\n".join(t for b, t in a.blocs if b == "script")
    for motif in (r"\bfetch\s*\(", r"XMLHttpRequest", r"new\s+WebSocket", r"EventSource", r"sendBeacon", r"new\s+Worker",
                  r"document\.cookie", r"localStorage", r"sessionStorage", r"indexedDB", r"window\.open", r"location\s*=",
                  r"location\.(href|assign|replace)", r"window\.top", r"parent\.document"):
        assert not re.search(motif, code), motif
    assert code.count("window.parent.postMessage(") == 1, "un seul point de sortie, protégé par versHote"
