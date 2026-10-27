"""Écrans d'appairage et de réglages du client web (S-W1b) : aucune superposition ni défaut de mise en page.

Les pages réelles sont servies avec des liens absolus et remplies par du JavaScript. Pour les contrôler dans
Chrome sans fenêtre, ce test fabrique dans un dossier temporaire une variante statique par étape (liens relatifs,
scripts retirés, texte des gabarits rempli, lignes d'exemple posées là où le script les construit), puis lance
`poc/outils/verifier_mise_en_page.py` en 360, 390 et 430 de large, thèmes clair et sombre. Ignoré sans Chrome.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
OUTIL = RACINE / "poc" / "outils" / "verifier_mise_en_page.py"
WEB = RACINE / "poc" / "web"
ADMIN = RACINE / "poc" / "admin"

sys.path.insert(0, str(OUTIL.parent))
import verifier_mise_en_page as outil  # noqa: E402

GABARITS = {"{{version_client}}": "0.3.0", "{{version_serveur}}": "0.47.0", "{{date}}": "27/10/2026",
            "{{nom_assistant}}": "Iris"}
QR = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'>"
      "<rect width='200' height='200' fill='white'/><rect x='20' y='20' width='160' height='160' fill='black'/></svg>")
LONG_NOM = "Téléphone de la chambre d'amis avec un nom beaucoup trop long pour tenir"


def lignes_appareils(avec_revoquer):
    def un(nom, role, courant, ligne, id_):
        pastille = '<span class="pastille pastille--assistant">Ce navigateur</span>' if courant else ""
        bouton = ""
        if avec_revoquer and not courant:
            bouton = (f'<button type="button" class="bouton bouton--danger bouton--appareil" '
                      f'aria-label="Révoquer {nom}">Révoquer</button>')
        return (f'<li class="appareil"><div class="appareil-infos"><span class="fort appareil-nom">{nom}</span>'
                f'<span class="secondaire">{role}</span>{pastille}<span class="secondaire">{ligne}</span>'
                f'<span class="aide-id">Identifiant {id_}</span></div>{bouton}</li>')
    return (un("Téléphone de Camille", "Propriétaire", True, "Connecté maintenant", "a1b2c3d4")
            + un(LONG_NOM, "Habitant", False, "Dernière connexion 24 octobre à 18:42", "e5f6a7b8")
            + un("Tablette du salon", "Invité", False, "Dernière connexion aujourd'hui à 09:05", "c9d0e1f2")
            .replace("</div><button", "<span class=\"secondaire\">Accès jusqu'au 3 novembre</span></div><button"))


def retirer_scripts(html):
    html = re.sub(r"<script\b[^>]*>\s*</script>", "", html)
    html = re.sub(r'<link rel="(?:manifest|icon)"[^>]*>', "", html)
    return html


def lien_relatif(html):
    return html.replace('href="/app.css"', 'href="app.css"')


def gabarits(html):
    for cle, valeur in GABARITS.items():
        html = html.replace(cle, valeur)
    return html


def garder(html, gardees, toutes):
    """Retire les sections non gardées et le `hidden` des sections gardées."""
    for sid in toutes:
        motif = re.compile(r'<section id="%s"[^>]*>.*?</section>\n?' % re.escape(sid), re.S)
        if sid in gardees:
            html = re.sub(r'(<section id="%s"[^>]*?) hidden' % re.escape(sid), r"\1", html)
        else:
            html = motif.sub("", html)
    return html


def montrer(html, *ids):
    for i in ids:
        html, n = re.subn(r'(<[a-z0-9]+ [^>]*?id="%s"[^>]*?) hidden' % re.escape(i), r"\1", html)
        assert n == 1, f"élément {i} introuvable ou déjà visible"
    return html


def remplir(html, ident, texte):
    motif = re.compile(r'(<([a-z0-9]+)\b[^>]*\bid="%s"[^>]*>)(.*?)(</\2>)' % re.escape(ident), re.S)
    html, n = motif.subn(lambda m: m.group(1) + texte + m.group(4), html, count=1)
    assert n == 1, f"élément {ident} introuvable"
    return html


def variantes_appairage():
    brut = gabarits(retirer_scripts(lien_relatif((WEB / "appairage.html").read_text(encoding="utf-8"))))
    etapes = ["etape-code", "etape-attente", "etape-interrompu", "etape-fait"]
    out = {}
    code = garder(brut, {"etape-code"}, etapes)
    out["appairage-code"] = code
    out["appairage-code-erreur"] = remplir(montrer(code, "erreur-code"), "erreur-code",
                                           "Ce code n'est pas valide. Il reste 2 essais. Vérifiez les 6 chiffres affichés par le propriétaire.")
    out["appairage-attente"] = garder(brut, {"etape-attente"}, etapes).replace(
        '<span id="reste-attente" class="chiffres"></span>', '<span id="reste-attente" class="chiffres">1 min 42 s</span>')
    attente_err = montrer(garder(brut, {"etape-attente"}, etapes), "erreur-creation")
    out["appairage-attente-erreur"] = remplir(attente_err, "erreur-creation",
                                              "La clé d'accès n'a pas pu être créée sur cet appareil. Réessayez avec un nouveau code.")
    out["appairage-interrompu"] = garder(brut, {"etape-interrompu"}, etapes)
    out["appairage-fait"] = garder(brut, {"etape-fait"}, etapes)
    return out


def variantes_associer():
    brut = gabarits(retirer_scripts(lien_relatif((WEB / "associer.html").read_text(encoding="utf-8"))))
    etapes = ["etape-1", "etape-2", "etape-3", "etape-fait", "etape-interrompu"]
    out = {}
    e1 = garder(brut, {"etape-1"}, etapes)
    out["associer-1"] = e1
    out["associer-1-proprietaire"] = remplir(montrer(e1, "avertissement-proprietaire", "erreur-ouvrir"), "erreur-ouvrir",
                                             "Cette ouverture n'est pas possible tout de suite. Réessayez dans une minute.")
    e2 = garder(brut, {"etape-2"}, etapes)
    e2 = remplir(e2, "nom-code", LONG_NOM)
    e2 = remplir(e2, "code-a", "482").replace('<span id="code-b"></span>', '<span id="code-b">915</span>')
    e2 = e2.replace('alt="QR code qui ouvre l\'association avec le code déjà rempli"',
                    f'src="{QR}" alt="QR code qui ouvre l\'association avec le code déjà rempli"')
    out["associer-2"] = montrer(remplir(e2, "statut-code", "Quelqu'un a saisi le code, en attente de la clé."),
                                "zone-qr", "statut-code")
    e3 = garder(brut, {"etape-3"}, etapes)
    e3 = remplir(e3, "nom-confirmer", LONG_NOM)
    e3 = remplir(e3, "resume-nom", LONG_NOM)
    e3 = remplir(e3, "resume-role", "Propriétaire")
    e3 = remplir(e3, "resume-heure", "aujourd'hui à 18:42")
    out["associer-3"] = montrer(remplir(e3, "erreur-confirmer", "La clé d'accès n'a pas été reconnue. Réessayez."),
                                "erreur-confirmer")
    fait = garder(brut, {"etape-fait"}, etapes)
    fait = remplir(fait, "fait-nom", LONG_NOM)
    out["associer-fait"] = remplir(fait, "fait-detail", "Rôle propriétaire. Accès sans limite de durée.")
    inter = garder(brut, {"etape-interrompu"}, etapes)
    out["associer-interrompu"] = remplir(montrer(inter, "heure-interrompu"), "heure-interrompu", "à 18:42")
    return out


def variantes_reglages():
    brut = gabarits(retirer_scripts(lien_relatif((WEB / "reglages.html").read_text(encoding="utf-8"))))
    out = {}
    cartes = ["carte-appareils", "carte-navigateur", "carte-serveur"]

    def liste(html, revoquer):
        html = remplir(html, "liste-appareils", lignes_appareils(revoquer))
        return remplir(html, "compte-appareils", "3 appareils")

    proprio = montrer(liste(brut, True), "bloc-associer")
    # Les dialogues fermés ne sont pas dessinés : on les retire, ils ont leurs propres variantes.
    sans_dialogues = re.sub(r"<dialog\b.*?</dialog>\n?", "", proprio, flags=re.S)
    out["reglages-proprietaire"] = sans_dialogues
    habitant = re.sub(r"<dialog\b.*?</dialog>\n?", "", liste(brut, False), flags=re.S)
    out["reglages-habitant"] = remplir(habitant, "compte-appareils", "1 appareil")
    erreur = montrer(sans_dialogues, "erreur-liste")
    out["reglages-erreur"] = remplir(erreur, "erreur-liste", "La liste des appareils n'a pas pu être chargée.")
    for dialogue, extra in (("dialogue-revoquer", "erreur-revoquer"), ("dialogue-oublier", "avertissement-dernier")):
        seul = brut
        for autre in cartes:
            seul = re.sub(r'<section id="%s"[^>]*>.*?</section>\n?' % autre, "", seul, flags=re.S)
        for d in ("dialogue-revoquer", "dialogue-oublier"):
            if d != dialogue:
                seul = re.sub(r'<dialog id="%s".*?</dialog>\n?' % d, "", seul, flags=re.S)
        seul = seul.replace(f'<dialog id="{dialogue}"', f'<dialog open data-superposition-voulue id="{dialogue}"')
        if dialogue == "dialogue-revoquer":
            seul = remplir(seul, "nom-revoquer", LONG_NOM)
        seul = montrer(seul, extra)
        if extra == "erreur-revoquer":
            seul = remplir(seul, extra, "La clé d'accès n'a pas été reconnue. Réessayez.")
        out[dialogue] = seul
    return out


def variantes_admin():
    brut = (ADMIN / "index.html").read_text(encoding="utf-8")
    brut = retirer_scripts(brut)
    brut = montrer(brut, "web-bloc", "web-ouverture", "web-confirmer")
    brut = remplir(brut, "web-aucun", "")
    brut = remplir(brut, "web-code", "482915")
    brut = remplir(brut, "web-etat", "Un navigateur attend votre confirmation.")
    brut = remplir(brut, "web-compte", "Valable encore 1 min 42 s")
    brut = remplir(brut, "web-role", '<option value="administrateur">Propriétaire</option><option value="habitant">Habitant</option>')
    carte = ('<li><div class="carte-tete"><span class="nom">' + LONG_NOM + '</span><span class="discret">En ligne</span></div>'
             '<p class="discret">Rôle : Propriétaire. Créé le 27/10/2026. Dernière connexion : aujourd\'hui à 18:42.</p>'
             '<div class="actions"><button type="button" class="danger" aria-label="Révoquer">Révoquer</button></div></li>')
    brut = remplir(brut, "web-appareils", carte)
    return {"admin-web": brut}


def ecrire(dossier, variantes):
    for nom, html in variantes.items():
        (dossier / f"{nom}.html").write_text(html, encoding="utf-8")


def test_les_variantes_sont_bien_fabriquees(tmp_path):
    """Garde-fou : les variantes statiques ne sont pas vides et ne gardent aucun gabarit non rempli."""
    toutes = {**variantes_appairage(), **variantes_associer(), **variantes_reglages(), **variantes_admin()}
    assert len(toutes) >= 15
    for nom, html in toutes.items():
        assert "{{" not in html, nom
        assert "<script" not in html, nom
        assert "<main" in html, nom


def test_ecrans_web_sans_defaut_de_mise_en_page(tmp_path):
    if outil.trouver_chrome() is None:
        pytest.skip("Chrome est absent : contrôle de mise en page impossible")
    pages = tmp_path / "pages"
    pages.mkdir()
    shutil.copytree(WEB / "polices", pages / "polices")
    css = (WEB / "app.css").read_text(encoding="utf-8").replace('url("/polices/', 'url("polices/')
    (pages / "app.css").write_text(css, encoding="utf-8")
    ecrire(pages, {**variantes_appairage(), **variantes_associer(), **variantes_reglages()})
    res = subprocess.run(
        [sys.executable, "-X", "utf8", str(OUTIL), str(pages), "--cibles", "main"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert res.returncode == 0, f"défauts de mise en page (code {res.returncode}) :\n{res.stdout}\n{res.stderr}"


def test_page_d_administration_sans_defaut_de_mise_en_page(tmp_path):
    if outil.trouver_chrome() is None:
        pytest.skip("Chrome est absent : contrôle de mise en page impossible")
    pages = tmp_path / "admin"
    pages.mkdir()
    shutil.copy(ADMIN / "admin.css", pages / "admin.css")
    ecrire(pages, variantes_admin())
    res = subprocess.run(
        [sys.executable, "-X", "utf8", str(OUTIL), str(pages), "--cibles", "main"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert res.returncode == 0, f"défauts de mise en page (code {res.returncode}) :\n{res.stdout}\n{res.stderr}"
