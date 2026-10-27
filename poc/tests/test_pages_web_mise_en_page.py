"""Écrans d'appairage et de réglages du client web (S-W1b) : aucune superposition ni défaut de mise en page.

Les pages réelles sont servies avec des liens absolus et remplies par du JavaScript. Pour les contrôler dans
Chrome sans fenêtre, ce test fabrique dans un dossier temporaire une variante statique par étape (liens relatifs,
scripts retirés, texte des gabarits rempli, lignes d'exemple posées là où le script les construit), puis lance
`poc/outils/verifier_mise_en_page.py` en 360, 390 et 430 de large, thèmes clair et sombre. Ignoré sans Chrome.
"""
import math
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

GABARITS = {"{{version_client}}": "0.7.0", "{{version_serveur}}": "0.52.0", "{{date}}": "27/10/2026",
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


def sans_dialogues(html):
    return re.sub(r"<dialog\b.*?</dialog>\n?", "", html, flags=re.S)


def dialogue_ouvert(html, ident):
    seul = html
    for autre in re.findall(r'<dialog id="([^"]+)"', html):
        if autre != ident:
            seul = re.sub(r'<dialog id="%s".*?</dialog>\n?' % autre, "", seul, flags=re.S)
    return seul.replace(f'<dialog id="{ident}"', f'<dialog open data-superposition-voulue id="{ident}"')


def entree_journal(heure, titre, sous="", mien=False, statut="ok"):
    marques = ""
    if mien:
        marques += '<span class="pastille pastille--assistant">Vous</span>'
    classe = {"ok": "pastille pastille--ok", "refus": "pastille pastille--danger"}.get(statut, "pastille")
    libelle = {"ok": "Fait", "refus": "Refusé"}.get(statut, statut)
    marques += f'<span class="{classe}">{libelle}</span>'
    corps = f'<span class="fort entree-titre">{titre}</span>'
    if sous:
        corps += f'<span class="secondaire entree-sous">{sous}</span>'
    corps += f'<span class="entree-marques">{marques}</span>'
    return (f'<button type="button" class="entree"><span class="entree-heure chiffres">{heure}</span>'
            f'<span class="entree-corps">{corps}</span></button>')


def journal_exemple():
    return ('<h3 class="jour">Aujourd\'hui</h3>'
            + entree_journal("18:42", "Allume la lampe du salon", "Salon, lampe du salon", mien=True)
            + entree_journal("09:05", LONG_NOM + " : peux-tu baisser le chauffage dans toutes les pièces",
                             "Chambre d'amis, chauffage 19 degrés, volets, lumière du couloir")
            + '<h3 class="jour">Hier</h3>'
            + entree_journal("22:10", "Ouvre le portail", "Entrée", mien=True, statut="refus")
            + '<h3 class="jour">24 oct.</h3>'
            + '<button type="button" class="entree"><span class="entree-heure chiffres">07:30</span>'
              '<span class="entree-corps"><span class="fort entree-titre">Une demande</span>'
              '<span class="secondaire entree-sous">Détail non partagé</span></span></button>')


def variantes_journal():
    brut = gabarits(retirer_scripts(lien_relatif((WEB / "journal.html").read_text(encoding="utf-8"))))
    out = {}
    base = remplir(sans_dialogues(brut), "niveau-courant", "Action seulement")
    liste = montrer(remplir(base, "liste-journal", journal_exemple()), "bouton-plus")
    out["journal-liste"] = liste
    etapes = ('<li class="etape"><span class="fort">Entendu</span><span class="secondaire chiffres">0,0 s</span></li>'
              '<li class="etape"><span class="fort">Compris</span><span class="secondaire chiffres">0,4 s</span></li>')
    out["journal-encours"] = remplir(montrer(liste, "carte-encours"), "etapes-encours", etapes)
    out["journal-vide"] = montrer(base, "vide-journal")
    out["journal-erreur"] = remplir(montrer(liste, "erreur-journal"), "erreur-journal",
                                    "La connexion avec l'assistant est coupée. Nouvelle tentative.")
    detail = dialogue_ouvert(brut, "dialogue-detail")
    detail = remplir(detail, "titre-detail", "Allume la lampe du salon et baisse le chauffage de la chambre d'amis")
    detail = remplir(detail, "detail-pastille",
                     '<span class="pastille pastille--assistant">Vous</span><span class="pastille pastille--ok">Fait</span>')
    lignes = "".join(f"<div><dt>{n}</dt><dd>{v}</dd></div>" for n, v in (
        ("Jour", "Aujourd'hui"), ("Heure", "18:42"), ("Phrase", "Allume la lampe du salon"),
        ("Actions", "Salon, lampe du salon"), ("Réponse", "C'est fait."), ("Appareil", LONG_NOM),
        ("Chemin", "Satellite"), ("Durée", "1,2 s"), ("Vie privée alors", "Action seulement")))
    detail = remplir(detail, "detail-liste", lignes)
    detail = remplir(montrer(detail, "detail-etapes"), "detail-etapes", etapes)
    out["journal-detail"] = remplir(montrer(detail, "detail-note"), "detail-note",
                                    "Seul cet appareil voit les étapes de ses propres demandes.")
    return out


def variantes_demander():
    brut = gabarits(retirer_scripts(lien_relatif((WEB / "demander.html").read_text(encoding="utf-8"))))
    brut = montrer(brut, "bouton-micro")   # le script le montre quand le navigateur sait enregistrer
    out = {"demander-repos": brut}
    etapes = ('<li class="etape"><span class="fort">Entendu</span><span class="secondaire chiffres">0,0 s</span></li>'
              '<li class="etape"><span class="fort">Compris</span><span class="secondaire chiffres">0,4 s</span></li>'
              '<li class="etape"><span class="fort">Fait</span><span class="secondaire chiffres">0,9 s</span></li>'
              '<li class="etape"><span class="fort">Répondu</span><span class="secondaire chiffres">1,2 s</span></li>')
    reponse = montrer(brut, "carte-reponse", "carte-actions", "carte-etapes", "liens-reponse")
    reponse = remplir(reponse, "reponse-demande", "« Allume la lampe du salon »")
    reponse = remplir(reponse, "reponse-meta", "18:42, écrite sur cet appareil")
    reponse = remplir(reponse, "reponse-texte", "C'est fait, la lampe du salon est allumée.")
    reponse = remplir(reponse, "liste-actions", "<li>Salon, lampe du salon allumée</li>")
    reponse = remplir(reponse, "etapes-demande", etapes)
    out["demander-reponse"] = reponse
    essai = montrer(reponse, "bandeau-essai", "reponse-essai")
    essai = essai.replace('aria-checked="false"', 'aria-checked="true"')
    essai = remplir(essai, "essai-etat", "Oui")
    out["demander-essai"] = essai
    long = remplir(reponse, "reponse-demande", "« " + LONG_NOM + " : peux-tu baisser le chauffage dans toutes les "
                   "pièces et fermer les volets du rez-de-chaussée avant ce soir »")
    long = remplir(long, "reponse-texte", "Je baisse le chauffage à 19 degrés dans le salon, la cuisine, la chambre "
                   "d'amis et le couloir, puis je ferme les volets du rez-de-chaussée. " * 2)
    long = remplir(long, "liste-actions", "".join(
        f"<li>{LONG_NOM}, chauffage 19 degrés, pièce {i}</li>" for i in range(1, 4)))
    long = long.replace('placeholder=', 'value="' + LONG_NOM + ' avec une demande très longue" placeholder=')
    out["demander-long"] = long
    erreur = remplir(montrer(brut, "erreur-demande"), "erreur-demande",
                     "Vous avez atteint la limite de demandes de ce navigateur. Vous pourrez demander de nouveau "
                     "dans 8 min 20 s.")
    out["demander-erreur"] = erreur
    en_cours = remplir(montrer(brut, "statut-demande"), "statut-demande", "La demande est en cours de traitement.")
    en_cours = en_cours.replace('id="bouton-envoyer"', 'id="bouton-envoyer" disabled')
    debut = "".join(etapes.split("</li>")[:2]) + "</li>"
    out["demander-encours"] = remplir(montrer(en_cours, "carte-etapes"), "etapes-demande", debut)
    # 11a, écoute : l'orbe, le niveau du micro (hauteurs posées par le script, ici en dur), la saisie écrite à portée.
    ecoute = montrer(brut, "carte-ecoute")
    hauteurs = (18, 32, 55, 80, 62, 90, 48, 70, 36, 58, 24, 40, 16)
    barres = "".join(f'<i style="--h:{h}%"></i>' for h in hauteurs)
    ecoute = remplir(ecoute, "niveau-micro", barres).replace(" niveau-micro--repos", "")
    ecoute = remplir(ecoute, "duree-ecoute", "7 s sur 20 s")
    ecoute = ecoute.replace('aria-label="Dire la demande">', 'aria-label="Dire la demande" disabled>')
    ecoute = ecoute.replace('id="bouton-envoyer"', 'id="bouton-envoyer" disabled')
    out["demander-ecoute"] = ecoute
    out["demander-ecoute-repos"] = montrer(brut, "carte-ecoute")   # niveau au repos, avant le premier son
    long_ecoute = ecoute.replace('placeholder=', 'value="' + LONG_NOM + ' avec une demande très longue" placeholder=')
    out["demander-ecoute-long"] = remplir(montrer(long_ecoute, "erreur-demande"), "erreur-demande",
                                          "Le micro est refusé pour ce site. Autorisez-le dans les réglages du "
                                          "navigateur, ou écrivez la demande.")
    refus = remplir(montrer(brut, "erreur-demande"), "erreur-demande",
                    "Le micro est refusé pour ce site. Autorisez-le dans les réglages du navigateur, ou écrivez la "
                    "demande.")
    out["demander-micro-refuse"] = refus
    return out


def variantes_vie_privee():
    brut = gabarits(retirer_scripts(lien_relatif((WEB / "vie-privee.html").read_text(encoding="utf-8"))))
    out = {}
    base = sans_dialogues(brut)
    base = remplir(base, "apercu-titre", "Une demande")
    base = remplir(base, "apercu-sous", "Détail non partagé")
    base = remplir(base, "actuel", "Niveau actuel : Discret depuis le 27 oct. à 18:42.")
    base = base.replace('value="discret">', 'value="discret" checked>')
    out["vie-privee-discret"] = base
    action = base.replace(' checked>', '>').replace('value="action">', 'value="action" checked>')
    action = remplir(action, "apercu-titre", "Une demande")
    action = remplir(action, "apercu-sous", "Lampe du salon allumée")
    action = remplir(montrer(action, "alerte-niveau"), "alerte-niveau",
                     "Les actions seules en disent déjà long : une lumière éteinte ou une porte fermée à telle heure "
                     "révèle vos habitudes, par exemple l'heure du coucher ou votre présence.")
    action = action.replace(' disabled>Enregistrer', '>Enregistrer')
    out["vie-privee-action"] = action
    tout = action.replace(' checked>', '>').replace('value="tout">', 'value="tout" checked>')
    tout = remplir(tout, "apercu-titre", "Allume la lampe du salon")
    tout = remplir(tout, "apercu-sous", "Lampe du salon allumée. Réponse : c'est fait.")
    tout = remplir(tout, "alerte-niveau", "Les autres habitants verront vos phrases et les réponses de l'assistant, "
                                          "avec l'heure et l'appareil.")
    out["vie-privee-tout"] = remplir(montrer(tout, "erreur-niveau"), "erreur-niveau",
                                     "La clé d'accès n'a pas été reconnue. Réessayez.")
    succes = remplir(montrer(base, "succes-niveau"), "succes-niveau", "Niveau enregistré : Discret.")
    out["vie-privee-succes"] = remplir(montrer(succes, "succes-effacer"), "succes-effacer", "3 entrées effacées.")
    dialogue = dialogue_ouvert(brut, "dialogue-effacer")
    out["vie-privee-dialogue"] = remplir(montrer(dialogue, "erreur-dialogue-effacer"), "erreur-dialogue-effacer",
                                         "La clé d'accès n'a pas été reconnue. Réessayez.")
    return out


def _svg(*chemins, rect=False):
    """Les icônes que `maison.js` construit en SVG (mêmes tracés)."""
    formes = ('<rect x="3" y="5" width="18" height="12" rx="2"/>' if rect else "")
    formes += "".join(f'<path d="{c}"/>' for c in chemins)
    return f'<svg viewBox="0 0 24 24" class="i" aria-hidden="true" focusable="false">{formes}</svg>'


I_ALERTE = _svg("M12 4 2.8 20h18.4z", "M12 10v5M12 17.8v.2")
I_CHEVRON = _svg("m9 5 7 7-7 7")
I_FERMER = _svg("M6 6l12 12M18 6 6 18")
I_COCHE = _svg("m5 12.5 4.5 4.5L19 7.5")
I_BOUCLIER = _svg("M12 3 4.5 6v5.5c0 4.5 3 8 7.5 9.5 4.5-1.5 7.5-5 7.5-9.5V6z")
I_TELE = _svg("M9 21h6M12 17v4", rect=True)
I_AIR = _svg("M3 9h11a3 3 0 1 0-3-3", "M3 14h15a3 3 0 1 1-3 3", "M3 19h6")
I_LECTURE = _svg("M8 5v14l11-7z")
I_PAUSE = _svg("M8 5v14M16 5v14")
I_SUIVANT = _svg("M6 5v14l9-7zM18 5v14")
I_PRECEDENT = _svg("M18 5v14l-9-7zM6 5v14")
I_MUET = _svg("M4 9v6h4l5 4V5L8 9z", "M17 9l4 6M21 9l-4 6")

SPHERES = {
    "blanc": '<span class="sphere" aria-hidden="true" style="--lumiere-vif:rgb(255,207,143);--lumiere-profond:rgb(189,153,106)"></span>',
    "froid": '<span class="sphere" aria-hidden="true" style="--lumiere-vif:rgb(201,220,255);--lumiere-profond:rgb(149,163,189)"></span>',
    "couleur": '<span class="sphere sphere--teinte" aria-hidden="true" style="--t:hsl(220,75%,58%);--t2:hsl(220,70%,38%)"></span>',
    "eteinte": '<span class="sphere sphere--eteinte" aria-hidden="true"></span>',
}


def commutateur(nom, allumee, injoignable=False):
    etiquette = nom + (", injoignable" if injoignable else "")
    inactif = ' aria-disabled="true"' if injoignable else ""
    return (f'<button type="button" class="commutateur" role="switch" aria-checked="{"true" if allumee else "false"}" '
            f'aria-label="{etiquette}"{inactif}><span class="interrupteur"></span></button>')


def chevron(nom, ouvert=False):
    return (f'<button type="button" class="lampe-ouvrir" aria-label="Régler {nom}" aria-haspopup="dialog" '
            f'aria-expanded="{"true" if ouvert else "false"}">{I_CHEVRON}</button>')


def ligne_lampe(nom, sphere, texte, allumee, etat="ok", ouverte=False):
    """etat : ok, injoignable, attente ou non_applique, comme dans `ligneLampe` de maison.js."""
    if etat == "injoignable":
        sous = I_ALERTE + "Injoignable"
    elif etat == "non_applique":
        sous = I_ALERTE + "Réglage non appliqué"
    elif etat == "attente":
        sous = "En attente de la lampe"
    else:
        sous = texte
    ouvre = chevron(nom, ouverte) if etat != "injoignable" else ""
    classe = "lampe lampe--ouverte" if ouverte else "lampe"
    return (f'<div class="{classe}">{SPHERES[sphere]}<div class="texte"><b>{nom}</b><span>{sous}</span></div>'
            f'{commutateur(nom, allumee, etat == "injoignable")}{ouvre}</div>')


def ligne_tele(nom, texte, allumee, injoignable=False):
    sous = (I_ALERTE + "Injoignable") if injoignable else texte
    ouvre = "" if injoignable else chevron(nom)
    return (f'<div class="rangee"><span class="puce puce--assistant">{I_TELE}</span>'
            f'<div class="texte"><b>{nom}</b><span>{sous}</span></div>{commutateur(nom, allumee, injoignable)}{ouvre}</div>')


def mesure(classe, avant, gras="", apres=""):
    c = f"mesure mesure--{classe}" if classe else "mesure"
    return f'<li class="{c}">{avant}' + (f"<b>{gras}</b>" if gras else "") + f"{apres}</li>"


def carte_piece(nom, lampes=(), tele="", mesures=(), resume=""):
    tete = f'<div class="piece-tete"><h2>{nom}</h2>' + (f'<span class="secondaire">{resume}</span>' if resume else "") + "</div>"
    liste = ""
    if mesures:
        # Comme maison.js : la liste est cliquable et suivie du bouton d'historique, sauf sans aucun capteur.
        cliquable = not all("mesure--aucune" in m for m in mesures)
        classe = "mesures mesures--cliquable" if cliquable else "mesures"
        liste = f'<ul class="{classe}" aria-label="Mesures de la pièce">' + "".join(mesures) + "</ul>"
        if cliquable:
            liste += (f'<button type="button" class="bouton-air" aria-haspopup="dialog" aria-expanded="false" '
                      f'aria-label="Historique de l\'air, {nom}">{I_AIR}Historique de l\'air</button>')
    return f'<section class="carte carte--vide piece" aria-label="{nom}">{tete}{liste}{tele}{"".join(lampes)}</section>'


def carte_protegee(nom):
    return (f'<section class="carte carte--vide piece" aria-label="{nom}"><div class="piece-protegee">'
            f'<span class="puce">{I_BOUCLIER}</span><div class="texte"><b>{nom}</b><span>Pièce protégée</span></div></div></section>')


def alerte_air(texte, danger):
    classe = "alerte--danger" if danger else "alerte--air"
    role = "alert" if danger else "status"
    return f'<div class="alerte alerte--icone {classe}" role="{role}">{I_ALERTE}<div><b>{texte}</b></div></div>'


MESURES_SALON = (
    mesure("agreable", "Température ", "21°", ", agréable"),
    mesure("", "Humidité ", "48 %"),
    mesure("correct", "CO2 ", "820 ppm", ", correct"),
    mesure("bon", "PM2,5 ", "6 µg/m3", ", bon"),
)


def page_maison(brut, pieces, alertes="", lu_a="Mesures lues à 18:42."):
    html = brut.replace('<p id="statut-maison" class="secondaire" role="status">',
                        '<p id="statut-maison" class="secondaire" role="status" hidden>')
    assert "role=\"status\" hidden>" in html
    html = remplir(html, "liste-pieces", "".join(pieces))
    if alertes:
        html = remplir(montrer(html, "alertes-air"), "alertes-air", alertes)
    if lu_a:
        html = remplir(montrer(html, "lu-a"), "lu-a", lu_a)
    return html


def variantes_maison():
    brut = gabarits(retirer_scripts(lien_relatif((WEB / "maison.html").read_text(encoding="utf-8"))))
    brut = brut.replace("{{nom_assistant}}", "Iris")
    out = {}
    salon = carte_piece(
        "Salon", resume="2 allumées", mesures=MESURES_SALON,
        tele=ligne_tele("Télé du salon", "Allumée, volume 22 %", True),
        lampes=[ligne_lampe("Lampe du canapé", "blanc", "80 %, 2700 K, chaud", True),
                ligne_lampe("Lampe d'angle", "couleur", "60 %, bleu", True),
                ligne_lampe("Suspension", "eteinte", "Éteinte", False)])
    chambre = carte_piece(
        "Chambre", resume="Tout éteint",
        mesures=[mesure("absente", "Température absente depuis 14:02"), mesure("", "Humidité ", "51 %"),
                 mesure("aucune", "Pas de capteur d'air")],
        lampes=[ligne_lampe("Chevet", "eteinte", "Éteinte", False)])
    bureau = carte_protegee("Bureau")
    cuisine = carte_piece(
        "Cuisine", resume="1 allumée",
        mesures=[mesure("absente", "Mesures absentes depuis 17:10")],
        lampes=[ligne_lampe("Plan de travail", "froid", "100 %, 6000 K, froid", True)])
    sans_mesure = carte_piece("Garage", mesures=[mesure("aucune", "Pas de thermomètre"),
                                                  mesure("aucune", "Pas de capteur d'air")],
                              lampes=[ligne_lampe("Plafonnier", "eteinte", "Éteinte", False)], resume="Tout éteint")
    out["maison-repos"] = page_maison(brut, [salon, chambre, bureau, cuisine, sans_mesure])
    air = (alerte_air("Le CO2 du Salon est mauvais, 1 650 ppm. Ouvrez une fenêtre pour renouveler l'air.", True)
           + alerte_air("L'air de la Chambre est médiocre. Aérer quelques minutes aiderait.", False))
    mauvais = carte_piece(
        "Salon", resume="2 allumées",
        mesures=[mesure("chaud", "Température ", "27°", ", chaud"), mesure("", "Humidité ", "62 %"),
                 mesure("mauvais", "CO2 ", "1650 ppm", ", mauvais"), mesure("mediocre", "PM2,5 ", "21 µg/m3", ", médiocre")],
        lampes=[ligne_lampe("Lampe du canapé", "blanc", "80 %, 2700 K, chaud", True)])
    out["maison-alerte-air"] = page_maison(brut, [mauvais, chambre], alertes=air)
    pannes = carte_piece(
        "Salon", resume="1 allumée", mesures=MESURES_SALON,
        tele=ligne_tele("Télé du salon", "", False, injoignable=True),
        lampes=[ligne_lampe("Lampe du canapé", "blanc", "", True, etat="injoignable"),
                ligne_lampe("Lampe d'angle", "couleur", "", True, etat="attente"),
                ligne_lampe("Suspension", "blanc", "", True, etat="non_applique")])
    out["maison-lampes-en-defaut"] = page_maison(brut, [pannes])
    longs = carte_piece(
        LONG_NOM, resume="2 allumées", mesures=MESURES_SALON,
        tele=ligne_tele(LONG_NOM, "Allumée, volume 22 %", True),
        lampes=[ligne_lampe(LONG_NOM, "blanc", "80 %, 2700 K, chaud", True),
                ligne_lampe(LONG_NOM + " bis", "couleur", "60 %, bleu", True, etat="non_applique")])
    out["maison-noms-longs"] = page_maison(brut, [longs, carte_protegee(LONG_NOM)],
                                           alertes=alerte_air(LONG_NOM + " : le CO2 est mauvais, 1 650 ppm. "
                                                              "Ouvrez une fenêtre pour renouveler l'air.", True))
    essai = remplir(montrer(brut, "bandeau-essai"), "bandeau-essai",
                    "<b>Mode essai.</b> Rien ne sera fait dans la maison. Iris dit seulement ce qu'elle ferait.")
    out["maison-essai"] = page_maison(essai, [salon])
    vide = page_maison(brut, [], lu_a="")
    vide = remplir(montrer(vide, "carte-vide"), "texte-vide", "Ce navigateur n'a accès à aucune pièce.")
    out["maison-vide"] = vide
    coupe = brut.replace('<p id="statut-maison" class="secondaire" role="status">Lecture de la maison en cours.',
                         '<p id="statut-maison" class="secondaire" role="status">La connexion avec la maison est coupée. '
                         'Nouvelle tentative.')
    coupe = remplir(montrer(coupe, "erreur-maison"), "erreur-maison",
                    "Lampe du canapé ne répond pas. Les réglages reprendront quand elle sera de nouveau joignable.")
    out["maison-coupee"] = page_maison(coupe, [], lu_a="").replace(' hidden>La connexion', '>La connexion')
    return out


def glisseur(num, etiquette, valeur_texte, mini, maxi, valeur, classe="", rempli=False, bornes=None, desactive=False):
    p = "" if valeur is None else f"{(valeur - mini) / (maxi - mini) * 100}%"
    inactif = ' aria-disabled="true"' if desactive else ""
    pas_de_valeur = "" if valeur is None else f' aria-valuenow="{valeur}"'
    interieur = ('<span class="rempli"></span>' if rempli else "") + '<span class="pouce"></span>'
    pied_bornes = ('<div class="bornes">' + "".join(f"<span>{b}</span>" for b in bornes) + "</div>") if bornes else ""
    return (f'<div class="reglage"><div class="reglage-tete"><span class="etiquette" id="gl{num}-lib">{etiquette}</span>'
            f'<span class="valeur-reglage">{valeur_texte}</span></div>'
            f'<div class="glisseur{(" " + classe) if classe else ""}" role="slider" tabindex="0" aria-labelledby="gl{num}-lib" '
            f'aria-valuemin="{mini}" aria-valuemax="{maxi}"{pas_de_valeur}{inactif} style="--p:{p or "0%"}">{interieur}</div>'
            f'{pied_bornes}</div>')


def choix(nom, couleur, pet=None, choisi=False):
    coche = f'<span class="coche" aria-hidden="true">{I_COCHE}</span>' if choisi else ""
    petit = f"<small>{pet}</small>" if pet else ""
    return (f'<button type="button" class="choix-volet" aria-pressed="{"true" if choisi else "false"}">'
            f'<span class="echantillon" style="--t:{couleur}"></span><b>{nom}</b>{petit}{coche}</button>')


BLANCS_VOLET = [("Bougie", 2200, "rgb(255,180,94)"), ("Chaud", 2700, "rgb(255,207,143)"),
                ("Neutre", 4000, "rgb(247,242,230)"), ("Froid", 6000, "rgb(201,220,255)")]
COULEURS_VOLET = [("Rouge", 0), ("Orange", 30), ("Jaune", 55), ("Vert", 120), ("Cyan", 180), ("Bleu", 220),
                  ("Violet", 275), ("Rose", 330)]


def volet_lampe(nom, onglet="blanc", pied="", sous="80 %, 2700 K, chaud", sphere="blanc", kmin=2200, kmax=6000,
                intensite=80, kelvin=2700, teinte=None, injoignable=False):
    blancs = "".join(choix(n, c, f"{k} K", abs(kelvin - k) <= 100 if kelvin else False)
                     for n, k, c in BLANCS_VOLET if kmin <= k <= kmax)
    couleurs = "".join(choix(n, f"hsl({h},75%,58%)", None, teinte is not None and abs(teinte - h) <= 8)
                       for n, h in COULEURS_VOLET)
    barre = ('<div class="segments" role="tablist" aria-label="Type de réglage">'
             + "".join(f'<button type="button" class="segment" role="tab" id="onglet-{n}" aria-controls="panneau-{n}" '
                       f'aria-selected="{"true" if n == onglet else "false"}" tabindex="{0 if n == onglet else -1}">{t}</button>'
                       for n, t in (("blanc", "Blanc"), ("couleur", "Couleur"))) + "</div>")
    val_i = f"{intensite} %"
    panneau_blanc = (
        f'<div class="panneau" id="panneau-blanc" role="tabpanel" aria-labelledby="onglet-blanc"{"" if onglet == "blanc" else " hidden"}>'
        + glisseur(1, "Intensité", val_i, 1, 100, intensite, rempli=True, desactive=injoignable)
        + f'<div class="reglage"><span class="etiquette">Blancs</span><div class="choix-grille">{blancs}</div></div>'
        + glisseur(2, "Chaleur du blanc", f"{kelvin} K, chaud" if kelvin else "Pas en blanc", kmin, kmax,
                   kelvin, classe="glisseur--chaleur", bornes=[f"{kmin} K", "Bornes de cette ampoule", f"{kmax} K"],
                   desactive=injoignable)
        + "</div>")
    panneau_couleur = (
        f'<div class="panneau" id="panneau-couleur" role="tabpanel" aria-labelledby="onglet-couleur"{"" if onglet == "couleur" else " hidden"}>'
        + glisseur(3, "Intensité", val_i, 1, 100, intensite, rempli=True, desactive=injoignable)
        + f'<div class="reglage"><span class="etiquette">Couleurs</span><div class="choix-grille">{couleurs}</div></div>'
        + glisseur(4, "Teinte", "bleu" if teinte is not None else "Pas en couleur", 0, 360, teinte,
                   classe="glisseur--teinte", desactive=injoignable)
        + "</div>")
    return _feuille(nom, SPHERES[sphere], "Injoignable" if injoignable else sous, barre + panneau_blanc + panneau_couleur, pied)


def _feuille(nom, marque, sous, corps, pied):
    return ('<div id="volet-maison"><div class="voile" data-superposition-voulue="voile de la feuille"></div>'
            '<div class="feuille" role="dialog" aria-modal="true" aria-labelledby="volet-titre-1" '
            'data-superposition-voulue="feuille modale"><div class="poignee"></div>'
            f'<div class="volet-tete">{marque}<div class="texte"><h2 id="volet-titre-1">{nom}</h2><p>{sous}</p></div>'
            f'<button type="button" class="fermer" aria-label="Fermer">{I_FERMER}</button></div>'
            f'<div class="volet-corps">{corps}</div><div class="volet-pied">{pied}</div></div></div>')


def volet_tele(nom, allumee=True, pied="", injoignable=False):
    puce = f'<span class="puce puce--assistant">{I_TELE}</span>'
    if allumee and not injoignable:
        corps = glisseur(1, "Volume", "22 %", 0, 100, 22, rempli=True)
        sous = "Allumée, volume 22 %"
    else:
        corps = '<p class="secondaire">Allumez la télé pour régler le volume.</p>'
        sous = "Injoignable" if injoignable else "Éteinte"
    return _feuille(nom, puce, sous, corps, pied)


def avec_volet(page, volet):
    html = page.replace('<main id="contenu-maison" class="contenu">', '<main id="contenu-maison" class="contenu" inert aria-hidden="true">')
    assert "inert" in html
    return html.replace('<div id="volet-maison"></div>', volet)


def variantes_maison_volet():
    """Le volet est hors de `main` : cibles tactiles contrôlées sur toute la page (voir le test dédié)."""
    brut = gabarits(retirer_scripts(lien_relatif((WEB / "maison.html").read_text(encoding="utf-8"))))
    brut = brut.replace("{{nom_assistant}}", "Iris")
    fond = page_maison(brut, [carte_piece(
        "Salon", resume="2 allumées", mesures=MESURES_SALON,
        tele=ligne_tele("Télé du salon", "Allumée, volume 22 %", True),
        lampes=[ligne_lampe("Lampe du canapé", "blanc", "80 %, 2700 K, chaud", True, ouverte=True),
                ligne_lampe("Lampe d'angle", "couleur", "60 %, bleu", True)])])
    out = {}
    out["maison-volet-blanc"] = avec_volet(fond, volet_lampe("Lampe du canapé"))
    out["maison-volet-couleur"] = avec_volet(fond, volet_lampe(
        "Lampe d'angle", onglet="couleur", sous="60 %, bleu", sphere="couleur", kelvin=None, teinte=220, intensite=60))
    out["maison-volet-blanc-etroit"] = avec_volet(fond, volet_lampe(
        "Lampe du canapé", kmin=2700, kmax=4000, pied=""))
    attente = ('<div class="alerte alerte--info" role="status">Demandé : intensité à 40 %. Lampe du canapé n\'a pas encore '
               'répondu. Sans réponse dans 5 s, le réglage sera signalé comme non appliqué.</div>')
    out["maison-volet-attente"] = avec_volet(fond, volet_lampe("Lampe du canapé", pied=attente, intensite=40))
    non_applique = ('<div class="alerte alerte--icone alerte--danger" role="alert">' + I_ALERTE
                    + "<div>Lampe du canapé n'a pas appliqué le réglage. Demandé : intensité à 40 %. La lampe affiche : "
                      '80 %, 2700 K, chaud.<button type="button" class="bouton">Réessayer</button></div></div>')
    out["maison-volet-non-applique"] = avec_volet(fond, volet_lampe("Lampe du canapé", pied=non_applique))
    injoignable = ('<div class="alerte alerte--icone alerte--danger" role="alert">' + I_ALERTE
                   + "<div>Lampe du canapé ne répond pas. Les réglages reprendront quand la lampe sera de nouveau "
                     "joignable.</div></div>")
    out["maison-volet-injoignable"] = avec_volet(fond, volet_lampe(
        "Lampe du canapé", pied=injoignable, injoignable=True))
    refus = ('<div class="alerte alerte--icone alerte--danger" role="alert">' + I_ALERTE
             + "<div>Ce navigateur n'a pas le droit de régler cette lampe.</div></div>")
    out["maison-volet-refus"] = avec_volet(fond, volet_lampe("Lampe du canapé", pied=refus))
    out["maison-volet-nom-long"] = avec_volet(fond, volet_lampe(
        LONG_NOM, pied=non_applique.replace("Lampe du canapé", LONG_NOM)))
    out["maison-volet-tele"] = avec_volet(fond, volet_tele("Télé du salon"))
    out["maison-volet-tele-eteinte"] = avec_volet(fond, volet_tele("Télé du salon", allumee=False))
    out["maison-volet-tele-injoignable"] = avec_volet(fond, volet_tele(
        "Télé du salon", injoignable=True, pied=injoignable.replace("la lampe", "la télé").replace("Lampe du canapé", "Télé du salon")))
    return out


def commande_media(libelle, icone, presse=None):
    """Un bouton de lecture du volet de la télé, comme `construireTele` dans maison.js."""
    pression = "" if presse is None else f' aria-pressed="{"true" if presse else "false"}"'
    return (f'<button type="button" class="commande-media" data-cle="media:{libelle.lower()}"{pression} aria-disabled="false">'
            f'{icone}<span>{libelle}</span></button>')


def source_tele(nom, choisie=False):
    coche = f'<span class="coche" aria-hidden="true">{I_COCHE}</span>' if choisie else ""
    return (f'<button type="button" class="choix-volet" aria-pressed="{"true" if choisie else "false"}">'
            f'<b>{nom}</b>{coche}</button>')


def volet_tele_complet(nom, allumee=True, lecture="pause", muet=False, sources=("TV", "HDMI 1", "Lecteur", "Console"),
                       choisie=0, boutons=("precedent", "lecture", "suivant", "muet"), pied=""):
    """Volet de la télé avec volume, commandes de lecture et sources (ou la phrase de la télé éteinte)."""
    puce = f'<span class="puce puce--assistant">{I_TELE}</span>'
    if not allumee:
        corps = '<p class="secondaire">Allumez la télé pour la régler.</p>'
        return _feuille(nom, puce, "Éteinte", corps, pied)
    corps = glisseur(1, "Volume", "22 %", 0, 100, 22, rempli=True)
    cmds = []
    if "precedent" in boutons:
        cmds.append(commande_media("Précédent", I_PRECEDENT))
    if "lecture" in boutons:
        cmds.append(commande_media("Pause" if lecture == "lecture" else "Lecture",
                                   I_PAUSE if lecture == "lecture" else I_LECTURE))
    if "suivant" in boutons:
        cmds.append(commande_media("Suivant", I_SUIVANT))
    if "muet" in boutons:
        cmds.append(commande_media("Muet", I_MUET, presse=muet))
    if cmds:
        corps += f'<div class="commandes-media" role="group" aria-label="Lecture">{"".join(cmds)}</div>'
    if sources:
        tuiles = "".join(source_tele(s, i == choisie) for i, s in enumerate(sources))
        corps += ('<div class="reglage"><span class="etiquette">Source</span>'
                  f'<div class="choix-grille choix-grille--sources" role="group" aria-label="Source">{tuiles}</div></div>')
    corps += '<p class="secondaire" hidden>Allumez la télé pour la régler.</p>'
    return _feuille(nom, puce, "Allumée, volume 22 %", corps, pied)


def bouton_duree(texte, presse):
    return f'<button type="button" class="segment" aria-pressed="{"true" if presse else "false"}">{texte}</button>'


def barre_duree(heures=24):
    boutons = "".join(bouton_duree(t, h == heures) for h, t in ((6, "6 h"), (24, "24 h"), (168, "7 jours")))
    return f'<div class="segments segments--trois" role="group" aria-label="Durée affichée">{boutons}</div>'


def barre_serie(noms, choisie):
    boutons = "".join(bouton_duree(n, n == choisie) for n in noms)
    return f'<div class="segments segments--serie" role="group" aria-label="Mesure affichée">{boutons}</div>'


def graphique_air(nom="CO2", unite=" ppm", base=820, amplitude=300, dec=0):
    """La courbe que `courbeAir` dessine : mêmes classes, mêmes repères (viewBox 320 x 190)."""
    larg, haut, g, d, h0 = 320, 190, 44, 12, 12
    zone_l, zone_h = larg - g - d, haut - h0 - 28
    points = [(g + zone_l * i / 47, h0 + zone_h * (0.5 - 0.4 * math.sin(i / 7))) for i in range(48)]
    trace = " ".join(("L" if i else "M") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(points))
    grille = ""
    for i in range(3):
        y = h0 + zone_h * (1 - i / 2)
        valeur = str(base + (i - 1) * amplitude)
        grille += (f'<line x1="{g}" x2="{larg - d}" y1="{y:.1f}" y2="{y:.1f}" class="graph-grille"/>'
                   f'<text x="{g - 6}" y="{y + 4:.1f}" text-anchor="end" class="graph-axe">{valeur}</text>')
    axe = "".join(f'<text x="{x}" y="{haut - 8}" text-anchor="{a}" class="graph-axe">{t}</text>'
                  for x, a, t in ((g, "start", "12:00"), (g + zone_l / 2, "middle", "18:00"), (larg - d, "end", "00:00")))
    fx, fy = points[-1]
    synthese = (f"{nom} : dernière valeur {base + 40}{unite}, minimum {base - amplitude}{unite}, "
                f"maximum {base + amplitude}{unite}, sur 24 h.")
    svg = (f'<svg viewBox="0 0 {larg} {haut}" role="img" focusable="false" class="graph" aria-label="{synthese}">{grille}{axe}'
           f'<path d="{trace}" class="graph-ligne"/><circle cx="{fx:.1f}" cy="{fy:.1f}" r="3" class="graph-point graph-point--fin"/>'
           f'<line x1="0" x2="0" y1="{h0}" y2="{haut - 28}" class="graph-curseur" visibility="hidden"/>'
           f'<circle cx="0" cy="0" r="4" class="graph-point graph-point--curseur" visibility="hidden"/>'
           f'<rect x="{g}" y="{h0}" width="{zone_l}" height="{zone_h}" class="graph-capture"/></svg>')
    return (f'<div class="graphique">{svg}</div><p class="graphique-synthese">{synthese}</p>'
            '<p class="graphique-lecture secondaire">Touchez la courbe pour lire une valeur.</p>')


def volet_air(piece, zone, series=(), choisie="CO2", heures=24):
    puce = f'<span class="puce puce--assistant">{I_AIR}</span>'
    corps = barre_duree(heures)
    if len(series) >= 2:
        corps += barre_serie(series, choisie)
    corps += f'<div class="graphique-air" tabindex="-1" aria-live="polite">{zone}</div>'
    return _feuille(f"Air, {piece}", puce, "Historique des mesures", corps, "")


def alerte_air_volet(texte, reessayer=True):
    bouton = '<button type="button" class="bouton">Réessayer</button>' if reessayer else ""
    return ('<div class="alerte alerte--icone alerte--danger" role="alert">' + I_ALERTE + f"<div>{texte}{bouton}</div></div>")


def cadre_3d(page, iframe=True, entiere=False, echec=False):
    """L'écran Maison avec sa section 3D : iframe vide (la vraie page n'est pas servie ici) ou message d'échec."""
    html = montrer(page, "vue-3d")
    if iframe and not echec:
        html = remplir(html, "cadre-3d", '<iframe class="iframe-3d" sandbox="allow-scripts" title="Vue 3D de la maison" '
                                         'referrerpolicy="no-referrer"></iframe>')
    if entiere:
        html = montrer(html, "entiere-3d")
    if echec:
        html = remplir(montrer(html, "texte-3d"), "texte-3d", "La vue 3D n'est pas disponible pour le moment.")
    return html


def variantes_maison_s_w4b():
    """Lot S-W4b : volet de la télé complet, graphique de l'air, écran avec la vue 3D."""
    brut = gabarits(retirer_scripts(lien_relatif((WEB / "maison.html").read_text(encoding="utf-8"))))
    brut = brut.replace("{{nom_assistant}}", "Iris")
    salon = carte_piece(
        "Salon", resume="2 allumées", mesures=MESURES_SALON,
        tele=ligne_tele("Télé du salon", "Allumée, volume 22 %", True),
        lampes=[ligne_lampe("Lampe du canapé", "blanc", "80 %, 2700 K, chaud", True),
                ligne_lampe("Suspension", "eteinte", "Éteinte", False)])
    fond = page_maison(brut, [salon])
    out = {}
    out["maison-tele-complete"] = avec_volet(fond, volet_tele_complet("Télé du salon", lecture="lecture"))
    out["maison-tele-complete-muet"] = avec_volet(fond, volet_tele_complet("Télé du salon", muet=True, choisie=2))
    out["maison-tele-sans-source"] = avec_volet(fond, volet_tele_complet(
        "Télé du salon", sources=(), boutons=("lecture", "muet")))
    out["maison-tele-sans-commande"] = avec_volet(fond, volet_tele_complet("Télé du salon", sources=(), boutons=()))
    out["maison-tele-sources-longues"] = avec_volet(fond, volet_tele_complet(
        LONG_NOM, sources=("Télévision numérique terrestre", LONG_NOM, "HDMI 1", "HDMI 2 avec un nom un peu long", "AV")))
    out["maison-tele-complete-eteinte"] = avec_volet(fond, volet_tele_complet("Télé du salon", allumee=False))
    out["maison-air-courbe"] = avec_volet(fond, volet_air(
        "Salon", graphique_air(), series=("CO2", "PM2,5", "Température", "Humidité")))
    out["maison-air-une-serie"] = avec_volet(fond, volet_air(
        "Chambre", graphique_air("Température", "°", 21, 4, 1)))
    out["maison-air-chargement"] = avec_volet(fond, volet_air(
        "Salon", '<p class="secondaire">Chargement des mesures...</p>', heures=168))
    out["maison-air-vide"] = avec_volet(fond, volet_air(
        "Salon", '<p class="secondaire">Aucune mesure sur cette période.</p>', heures=6))
    out["maison-air-erreur"] = avec_volet(fond, volet_air(
        "Salon", alerte_air_volet("Les mesures ne sont pas arrivées. Réessayez.")))
    out["maison-air-droit"] = avec_volet(fond, volet_air(
        "Salon", alerte_air_volet("Ce navigateur n'a pas accès aux mesures de l'air.", reessayer=False)))
    out["maison-air-nom-long"] = avec_volet(fond, volet_air(
        LONG_NOM, graphique_air().replace("CO2 :", LONG_NOM + " :"), series=("CO2", "PM2,5", "Température", "Humidité")))
    out["maison-3d"] = cadre_3d(fond)
    out["maison-3d-piece-choisie"] = cadre_3d(fond, entiere=True)
    out["maison-3d-echec"] = cadre_3d(fond, echec=True)
    return out


def variante_accueil():
    brut = gabarits(retirer_scripts(lien_relatif((WEB / "index.html").read_text(encoding="utf-8"))))
    return {"accueil-connecte": garder(brut, {"carte-connecte"}, ["carte-appairage", "carte-connecte"])}


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
    toutes = {**variantes_appairage(), **variantes_associer(), **variantes_reglages(), **variantes_journal(),
              **variantes_demander(), **variantes_vie_privee(), **variante_accueil(), **variantes_admin(),
              **variantes_maison(), **variantes_maison_volet(), **variantes_maison_s_w4b()}
    assert len(toutes) >= 72
    assert {"maison-tele-complete", "maison-air-courbe", "maison-3d"} <= set(toutes)
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
    ecrire(pages, {**variantes_appairage(), **variantes_associer(), **variantes_reglages(), **variantes_journal(),
                   **variantes_demander(), **variantes_vie_privee(), **variante_accueil()})
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


def test_ecran_maison_sans_defaut_de_mise_en_page(tmp_path):
    """L'écran Maison et son volet, cibles tactiles contrôlées sur toute la page : le volet est hors de `main`."""
    if outil.trouver_chrome() is None:
        pytest.skip("Chrome est absent : contrôle de mise en page impossible")
    pages = tmp_path / "maison"
    pages.mkdir()
    shutil.copytree(WEB / "polices", pages / "polices")
    css = (WEB / "app.css").read_text(encoding="utf-8").replace('url("/polices/', 'url("polices/')
    (pages / "app.css").write_text(css, encoding="utf-8")
    ecrire(pages, {**variantes_maison(), **variantes_maison_volet(), **variantes_maison_s_w4b()})
    res = subprocess.run(
        [sys.executable, "-X", "utf8", str(OUTIL), str(pages), "--cibles", ""],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert res.returncode == 0, f"défauts de mise en page (code {res.returncode}) :\n{res.stdout}\n{res.stderr}"
