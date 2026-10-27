"""Client web installable (S-W9) : service worker de la coquille, page hors ligne, purge à la révocation, ligne
Installer sur ce téléphone des Réglages."""
import json
import re
import shutil
import subprocess

import pytest

import serveur_web as W
from test_serveur_web import (  # noqa: F401  (fixtures réutilisées)
    avec_serveur, cookie, get, horloge, sessions, verifier_entetes_securite)

SW = (W.DOSSIER / "sw.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def liste_js(nom):
    """Les chaînes d'un tableau var NOM = [...] de sw.js."""
    bloc = re.search(r"var " + nom + r" = \[(.*?)\];", SW, re.S)
    assert bloc, nom
    return re.findall(r'"([^"]*)"', bloc.group(1))


COQUILLE = liste_js("COQUILLE")
PAGES_SW = liste_js("PAGES")


def test_sw_servi_en_javascript_sans_cache_avec_la_version_du_client(sessions):
    async def scenario(port):
        return await get(port, "/sw.js")
    statut, entetes, corps = avec_serveur(sessions, scenario)
    assert statut == 200
    assert entetes["content-type"] == "text/javascript; charset=utf-8"
    assert entetes["cache-control"] == "no-cache"
    verifier_entetes_securite(entetes)
    texte = corps.decode("utf-8")
    assert "{{" not in texte
    assert f'var VERSION = "{W.VERSION_CLIENT}";' in texte
    assert 'var CACHE = "coquille-" + VERSION;' in texte
    assert "service-worker-allowed" not in entetes  # portée / par défaut, rien à élargir


def test_nom_du_cache_suit_la_version_du_client(sessions, monkeypatch):
    monkeypatch.setattr(W, "VERSION_CLIENT", "7.8.9")

    async def scenario(port):
        return await get(port, "/sw.js")
    assert b'var VERSION = "7.8.9";' in avec_serveur(sessions, scenario)[2]
    # La version n'est écrite qu'à un endroit : le gabarit de sw.js, jamais une valeur en dur.
    assert re.search(r"\d+\.\d+\.\d+", SW.split("var CACHE")[0].split("var VERSION")[1]) is None


def test_liste_blanche_de_la_coquille_sans_route_protegee_ni_donnee():
    assert COQUILLE and len(set(COQUILLE)) == len(COQUILLE)
    assert set(COQUILLE) <= set(W.FICHIERS), set(COQUILLE) - set(W.FICHIERS)
    assert not set(COQUILLE) & (set(W.PAGES_PROTEGEES) | set(W.SCRIPTS_PROTEGES))
    for chemin in COQUILLE + PAGES_SW:
        for interdit in ("/api", "/ws", "/appairage", "/oublier", "/vue3d", "/sw.js", "/manifest"):
            assert not chemin.startswith(interdit), chemin
    assert "/hors-ligne" in COQUILLE and "/client.js" in COQUILLE and "/app.css" in COQUILLE
    # Les pages ne passent jamais par le cache : elles sont seulement remplacées par la page hors ligne sans réseau.
    assert set(PAGES_SW) <= set(W.PAGES_PROTEGEES) | {"/"}
    assert not set(PAGES_SW) & set(COQUILLE)
    assert SW.count("cache.put(") == 1 and SW.count("respondWith(") == 2
    # Vu dans Chrome : après « Oublier ce navigateur », la page encore contrôlée recréait le cache avec une icône.
    # La copie ne va que dans un cache encore présent.
    assert "caches.has(CACHE)" in SW and "if (!present) { return null; }" in SW


def test_sw_ignore_les_requetes_autres_que_get_et_les_autres_origines():
    assert 'requete.method !== "GET"' in SW and "url.origin !== self.location.origin" in SW
    assert 'requete.mode === "navigate"' in SW
    # Purge des anciens caches à l'activation.
    assert "caches.keys()" in SW and "nom !== CACHE" in SW and "caches.delete(nom)" in SW


def test_page_hors_ligne_publique_sans_donnee(sessions):
    async def scenario(port):
        return await get(port, "/hors-ligne")
    statut, entetes, corps = avec_serveur(sessions, scenario)
    html = corps.decode("utf-8")
    assert statut == 200 and entetes["content-type"].startswith("text/html")
    verifier_entetes_securite(entetes)
    assert "Serveur injoignable" in html and "Iris" in html and "{{" not in html
    assert "onglets" not in html  # pas de barre d'onglets : rien n'y marche sans serveur


def test_scripts_d_inscription_et_de_purge_sur_toutes_les_pages():
    client = (W.DOSSIER / "client.js").read_text(encoding="utf-8")
    assert 'navigator.serviceWorker.register(adresseSw(), { scope: "/" })' in client
    # Trusted Types : une politique dédiée qui n'accepte que /sw.js, la politique de contenu reste intacte.
    assert 'var URL_SW = "/sw.js";' in client and 'createPolicy("service-worker"' in client
    assert "if (u !== URL_SW) { throw" in client
    assert "require-trusted-types-for 'script'" in W.CSP and "unsafe" not in W.CSP
    assert "magasin.delete(nom)" in client and "unregister()" in client
    assert "beforeinstallprompt" in client and "(display-mode: standalone)" in client
    for page in W.DOSSIER.glob("*.html"):
        assert '<script src="/client.js" defer></script>' in page.read_text(encoding="utf-8"), page.name
    reglages = (W.DOSSIER / "reglages.js").read_text(encoding="utf-8")
    assert reglages.count("C.purgerHorsLigne()") == 1 and reglages.count("quitter();") == 2
    assert 'C.purgerHorsLigne().then(function () { window.location.replace("/appairage"); });' in reglages


# Comportement de client.js sous node : inscription, purge, proposition d'installation.
HARNAIS = r"""
const journal = [];
const evenements = {};
globalThis.document = { documentElement: { setAttribute() {} } };
const inscriptions = [{ unregister: () => { journal.push("desinscrit"); return Promise.resolve(true); } }];
globalThis.window = {
  addEventListener: (t, f) => { evenements[t] = f; },
  location: { pathname: /*CHEMIN*/ "" },
  isSecureContext: true,
  /*TT*/
  matchMedia: q => ({ matches: /*AUTONOME*/ false && q === "(display-mode: standalone)" }),
  caches: {
    keys: () => Promise.resolve(["coquille-0.10.0", "coquille-0.11.0"]),
    delete: n => { journal.push("efface " + n); return Promise.resolve(true); }
  }
};
// node 21+ a son propre navigator, en lecture seule : il est remplacé, pas affecté.
Object.defineProperty(globalThis, "navigator", { configurable: true, value: { serviceWorker: {
  register: (url, o) => {
    journal.push("inscrit " + (typeof url === "object" ? "confiance:" + url.adresse : url) + " " + o.scope);
    return Promise.resolve({});
  },
  getRegistrations: () => Promise.resolve(inscriptions)
} } });
/*CLIENT*/
const C = window.Client;
(async () => {
  /*SCENARIO*/
  await new Promise(r => setTimeout(r, 20));
  console.log(JSON.stringify(journal));
})();
"""


CONFIANCE = """trustedTypes: { createPolicy: (nom, regles) => {
    journal.push("politique " + nom);
    globalThis.regles = regles;
    return { createScriptURL: u => ({ adresse: regles.createScriptURL(u) }) };
  } },"""


def executer(tmp_path, chemin, scenario="", autonome=False, confiance=False):
    if NODE is None:
        pytest.skip("node absent")
    script = (HARNAIS.replace("/*TT*/", CONFIANCE if confiance else "")
              .replace("/*CLIENT*/", (W.DOSSIER / "client.js").read_text(encoding="utf-8"))
              .replace('/*CHEMIN*/ ""', json.dumps(chemin)).replace("/*AUTONOME*/ false", json.dumps(autonome))
              .replace("/*SCENARIO*/", scenario))
    fichier = tmp_path / "client_installable.js"
    fichier.write_text(script, encoding="utf-8")
    r = subprocess.run([NODE, str(fichier)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_inscription_sur_les_pages_d_une_session_seulement(tmp_path):
    for chemin in ("/reglages", "/maison", "/demander", "/ecouter"):
        assert executer(tmp_path, chemin) == ['inscrit /sw.js /'], chemin
    for chemin in ("/", "/hors-ligne"):
        assert executer(tmp_path, chemin) == [], chemin  # l'accueil inscrit après /api/etat, la page hors ligne jamais


def test_inscription_par_une_adresse_de_confiance_limitee_a_sw_js(tmp_path):
    """Sous require-trusted-types-for 'script', register() refuse une simple chaîne (vu dans Chrome) : l'adresse passe
    par une politique qui n'accepte que /sw.js."""
    scenario = """
    for (const u of ["/app.js", "/sw.js?x=1", "https://ailleurs.example/sw.js"]) {
      try { regles.createScriptURL(u); journal.push("accepte " + u); } catch (e) { journal.push("refuse " + u); }
    }
    C.installerHorsLigne();
    """
    assert executer(tmp_path, "/reglages", scenario, confiance=True) == [
        "politique service-worker", "inscrit confiance:/sw.js /", "refuse /app.js", "refuse /sw.js?x=1",
        "refuse https://ailleurs.example/sw.js", "inscrit confiance:/sw.js /"]


def test_l_ecran_d_association_vide_le_cache_et_desinscrit(tmp_path):
    journal = executer(tmp_path, "/appairage")
    assert sorted(journal) == ["desinscrit", "efface coquille-0.10.0", "efface coquille-0.11.0"]


def test_purge_appelee_par_une_page(tmp_path):
    journal = executer(tmp_path, "/hors-ligne", 'await C.purgerHorsLigne(); journal.push("suite");')
    assert journal[-1] == "suite" and "desinscrit" in journal and "efface coquille-0.11.0" in journal


def test_proposition_d_installation_gardee_puis_utilisee(tmp_path):
    scenario = """
    journal.push("avant " + C.propositionDisponible());
    C.surInstallation(() => journal.push("change " + C.propositionDisponible()));
    let empeche = false;
    evenements.beforeinstallprompt({ preventDefault: () => { empeche = true; },
      prompt: () => { journal.push("propose"); return Promise.resolve(); },
      userChoice: Promise.resolve({ outcome: "accepted" }) });
    journal.push("empeche " + empeche);
    journal.push("accepte " + await C.proposerInstallation());
    journal.push("encore " + await C.proposerInstallation());
    """
    assert executer(tmp_path, "/hors-ligne", scenario) == [
        "avant false", "change true", "empeche true", "propose", "change false", "accepte true", "encore false"]


def test_application_deja_installee(tmp_path):
    assert executer(tmp_path, "/hors-ligne", 'journal.push(String(C.dejaInstallee()));', autonome=True) == ["true"]
    assert executer(tmp_path, "/hors-ligne", 'journal.push(String(C.dejaInstallee()));') == ["false"]


def test_ligne_installer_dans_les_reglages():
    html = (W.DOSSIER / "reglages.html").read_text(encoding="utf-8")
    for ident in ("carte-installer", "etat-installer", "texte-installer", "bouton-installer", "aide-installer"):
        assert f'id="{ident}"' in html, ident
    assert "Installer sur ce téléphone" in html and "Déjà installée" in html
    js = (W.DOSSIER / "reglages.js").read_text(encoding="utf-8")
    for texte in ("« Installer l'application »", "« Ajouter la page à »", "« Sur l'écran d'accueil »"):
        assert texte in js, texte
    assert "C.proposerInstallation()" in js and "C.dejaInstallee()" in js


def test_revocation_vide_le_cache_et_le_stockage(sessions):
    jeton = sessions.creer("proprietaire")
    absent = sessions.creer("proprietaire")

    async def scenario(port):
        sessions.revoquer(jeton)
        return (await get(port, "/reglages", cookie(jeton)), await get(port, "/api/etat", cookie(jeton)),
                await get(port, "/reglages"), await get(port, "/api/etat"), await get(port, "/reglages", cookie(absent)))
    page, api, sans_page, sans_api, valide = avec_serveur(sessions, scenario)
    assert page[0] == 303 and page[1]["location"] == "/appairage"
    assert page[1]["clear-site-data"] == '"cache", "storage"'
    assert api[0] == 401 and api[1]["clear-site-data"] == '"cache", "storage"'
    # Sans cookie ou avec une session valide, rien n'est effacé.
    for r in (sans_page, sans_api, valide):
        assert "clear-site-data" not in r[1]
    assert sans_page[0] == 303 and sans_api[0] == 401 and valide[0] == 200


def test_manifeste_conforme_aux_criteres_d_installation(sessions):
    async def scenario(port):
        return await get(port, "/manifest.webmanifest")
    m = json.loads(avec_serveur(sessions, scenario)[2])
    assert m["name"] == "Iris" and m["short_name"] and m["start_url"] == "/" and m["display"] == "standalone"
    tailles = {(i["sizes"], i["purpose"]) for i in m["icons"]}
    assert ("192x192", "any") in tailles and ("512x512", "any") in tailles and ("512x512", "maskable") in tailles
