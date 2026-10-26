"""Confidentialité du moteur : aucun fichier suivi par git ne doit situer le logement ni nommer ses occupants.

Deux volets.

Le volet générique tourne partout (arbre de travail sans config/, session en ligne). Il parcourt les fichiers
texte suivis et refuse :
- toute adresse IPv4 hors de IP_PERMISES (plages de documentation, boucle locale, adresses de l'exemple...) ;
- tout nom d'hôte en .ts.net hors *.exemple.ts.net, et tout nom en .local hors HOTES_LOCAUX_PERMIS ;
- tout identifiant d'entité Home Assistant absent de config-exemple/ (maison.json et cartes), dans les tests et la
  documentation, hors IDS_GENERIQUES.

Le volet privé ne tourne que si config/maison.json existe (dossier principal du moteur). Il en extrait les chaînes
sensibles (identifiants d'entités, noms et prénoms, alias SSH, adresses, coordonnées) et lit config/mots-interdits.txt
(une chaîne par ligne). Aucune de ces chaînes ne doit apparaître dans un fichier suivi ni dans un nom de fichier.
Sans config/, il est sauté avec un message.

Les messages d'échec donnent le fichier, la ligne et la catégorie, jamais la valeur trouvée : les sorties des agents
finissent dans des journaux.

Exceptions : la liste ATTENDUS commence vide. Chaque entrée est un échec constaté sur le dépôt, marqué xfail (strict)
avec la fiche du plan qui le corrige. Quand la fiche a corrigé le fichier, le test passe, l'xfail strict échoue et
rappelle de retirer l'entrée. Pas d'exception permanente.
"""
import functools
import ipaddress
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
TAILLE_MAX = 2 * 1024 * 1024  # au-delà : fichier trop gros pour être balayé (le dictionnaire d'exemple, 1,7 Mo, reste balayé)

# --- Volet générique : valeurs permises ------------------------------------------------------------------------

# Adresses permises en clair. Les plages de documentation sont dans RESEAUX_PERMIS.
IP_PERMISES = frozenset({
    "127.0.0.1", "0.0.0.0",
    "172.30.32.2",                 # superviseur de Home Assistant
    "172.30.33.2", "172.30.33.3",  # add-ons de Home Assistant
    "8.8.8.8", "1.1.1.1",          # résolveurs publics génériques
    "1.2.3.4",
    "192.168.0.10", "192.168.0.20",  # adresses d'exemple de config-exemple/maison.json
    "8.8.4.4", "100.64.0.10",      # public et tailnet génériques des tests réseau (fiche S-C2)
    "10.0.0.10",                   # réseau privé 10.0.0.0/8, générique
    "100.128.0.1",                 # première adresse juste après 100.64.0.0/10, pour tester la limite
})
RESEAUX_PERMIS = tuple(ipaddress.ip_network(r) for r in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))
# Un réseau écrit en CIDR est permis tel quel (10.0.0.0/8, 100.64.0.0/10...), sauf une adresse seule (/31 et /32).
PREFIXE_RESEAU_MAX = 30

HOTES_LOCAUX_PERMIS = frozenset({"homeassistant.local", "pc-maison.local", "pc.local", "ha.local"})
SUFFIXE_TAILNET_PERMIS = "exemple.ts.net"

DOMAINES_TESTES = ("light", "cover", "switch", "media_player", "climate", "sensor")
# Identifiants génériques des tests unitaires (ils ne désignent aucun équipement).
IDS_GENERIQUES = frozenset({
    "light.a", "light.b", "light.x", "light.y", "light.z", "light.essai", "light.inconnue", "light.tout",
    "media_player.a", "media_player.b", "media_player.c", "media_player.autre", "media_player.inconnu",
    "switch.prise",
})
# Services de Home Assistant (domaine.service) : ce ne sont pas des entités.
SERVICES = frozenset({
    "turn_on", "turn_off", "toggle", "volume_up", "volume_down", "volume_set", "volume_mute", "media_play",
    "media_pause", "media_stop", "media_next_track", "media_previous_track", "play_media", "select_source",
    "join", "unjoin", "open_cover", "close_cover", "stop_cover", "set_cover_position", "set_temperature",
    "set_hvac_mode", "reload",
})

# Fichiers où l'on cherche des identifiants d'entités : tests et documentation.
PREFIXES_ENTITES = ("poc/tests/", "android/app/src/test/", "docs/")

# Échecs constatés sur le dépôt, à corriger par la fiche nommée. (catégorie, chemin) -> fiche.
# Catégories : ip, hote, entite (volet générique), prive (volet privé).
ATTENDUS = {}

# --- Lecture du dépôt -------------------------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def fichiers_suivis():
    """Chemin -> texte des fichiers suivis par git, hors binaires et hors fichiers de plus de 2 Mo."""
    try:
        sortie = subprocess.run(["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git indisponible ou dossier hors dépôt : rien à parcourir")
    textes = {}
    for chemin in sortie.decode("utf-8").split("\0"):
        if not chemin:
            continue
        fichier = RACINE / chemin
        try:
            if not fichier.is_file() or fichier.stat().st_size > TAILLE_MAX:
                continue
            octets = fichier.read_bytes()
        except OSError:
            continue
        if b"\0" in octets:
            continue
        try:
            textes[chemin] = octets.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return textes


def ligne_de(texte, position):
    return texte.count("\n", 0, position) + 1


# --- Détecteurs génériques --------------------------------------------------------------------------------------

OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
IPV4 = re.compile(rf"(?<![\w.])({OCTET}(?:\.{OCTET}){{3}})(?![\w]|\.\d)(?:/(\d{{1,2}}))?")
CONTEXTE_VERSION = re.compile(r"version\s*$", re.IGNORECASE)
HOTE_TAILNET = re.compile(r"(?<![\w.-])((?:[A-Za-z0-9-]+\.)*[A-Za-z0-9-]+\.ts\.net)(?![\w-])")
HOTE_LOCAL = re.compile(r"(?<![\w.-])((?:[A-Za-z0-9-]+\.)*[A-Za-z0-9-]+\.local)(?![\w-]|\.\w|\()", re.IGNORECASE)
ENTITE = re.compile(rf"(?<![\w.])((?:{'|'.join(DOMAINES_TESTES)})\.[a-z0-9_]+)(?![\w])")
# Tous les domaines de Home Assistant que la configuration peut citer (volet privé et entités de l'exemple).
ENTITE_LARGE = re.compile(
    r"(?<![\w.])((?:light|cover|switch|media_player|climate|sensor|binary_sensor|script|automation|scene|event|"
    r"update|input_boolean|input_number|input_select|input_text|input_datetime|number|select|button|camera|lock|"
    r"fan|vacuum|remote|weather|person|device_tracker|group|zone|todo|water_heater|humidifier|siren|"
    r"alarm_control_panel|valve|text|time|date|datetime|calendar)\.[a-z0-9_]+)(?![\w])")


def ip_permise(adresse, prefixe):
    if prefixe is not None:
        return int(prefixe) <= PREFIXE_RESEAU_MAX
    if adresse in IP_PERMISES:
        return True
    ip = ipaddress.ip_address(adresse)
    return any(ip in reseau for reseau in RESEAUX_PERMIS)


def dans_colonne_version(texte, position):
    """Vrai si la position tombe dans la cellule d'un tableau Markdown dont l'en-tête de colonne parle de version
    (un numéro à quatre composantes y est une version de paquet, pas une adresse)."""
    debut_ligne = texte.rfind("\n", 0, position) + 1
    if not texte[debut_ligne:position].lstrip().startswith("|"):
        return False
    colonne = texte[debut_ligne:position].count("|")
    entete = None
    for ligne in reversed(texte[:debut_ligne].splitlines()):
        if not ligne.lstrip().startswith("|"):
            break
        entete = ligne
    if entete is None:
        return False
    cellules = entete.split("|")
    return colonne < len(cellules) and "version" in cellules[colonne].lower()


def trouver_ip(texte):
    """Lignes où figure une adresse IPv4 qui n'est pas permise."""
    trouvees = []
    for m in IPV4.finditer(texte):
        if CONTEXTE_VERSION.search(texte[max(0, m.start() - 12):m.start()]):
            continue
        if dans_colonne_version(texte, m.start()):
            continue
        if not ip_permise(m.group(1), m.group(2)):
            trouvees.append(ligne_de(texte, m.start()))
    return trouvees


def trouver_hotes(texte):
    """Lignes où figure un nom en .ts.net hors *.exemple.ts.net, ou un nom en .local hors de la liste permise."""
    trouvees = []
    for m in HOTE_TAILNET.finditer(texte):
        hote = m.group(1).lower()
        if hote != SUFFIXE_TAILNET_PERMIS and not hote.endswith("." + SUFFIXE_TAILNET_PERMIS):
            trouvees.append(ligne_de(texte, m.start()))
    for m in HOTE_LOCAL.finditer(texte):
        if m.group(1).lower() not in HOTES_LOCAUX_PERMIS:
            trouvees.append(ligne_de(texte, m.start()))
    return sorted(trouvees)


def est_service(identifiant):
    return identifiant.split(".", 1)[1] in SERVICES


def entites_citees(texte, motif=ENTITE):
    return [(m.group(1), m.start()) for m in motif.finditer(texte) if not est_service(m.group(1))]


@functools.lru_cache(maxsize=1)
def entites_de_l_exemple():
    """Identifiants d'entités de config-exemple/maison.json et des cartes d'exemple."""
    connues = set()
    sources = [RACINE / "config-exemple" / "maison.json"] + sorted((RACINE / "config-exemple" / "carte").glob("*.json"))
    for source in sources:
        if source.is_file():
            connues.update(i for i, _ in entites_citees(source.read_text(encoding="utf-8"), ENTITE_LARGE))
    return frozenset(connues)


def trouver_entites(texte):
    """Lignes où figure un identifiant d'entité absent de l'exemple et des identifiants génériques."""
    permis = entites_de_l_exemple() | IDS_GENERIQUES
    return [ligne_de(texte, pos) for ident, pos in entites_citees(texte) if ident not in permis]


def concerne_les_entites(chemin):
    return chemin.startswith(PREFIXES_ENTITES) or chemin.endswith(".md")


DETECTEURS = {
    "ip": (trouver_ip, lambda chemin: True),
    "hote": (trouver_hotes, lambda chemin: True),
    "entite": (trouver_entites, concerne_les_entites),
}


def violations(categorie):
    """Chemin -> lignes fautives, pour une catégorie du volet générique."""
    detecter, concerne = DETECTEURS[categorie]
    trouvees = {}
    for chemin, texte in fichiers_suivis().items():
        if concerne(chemin):
            lignes = detecter(texte)
            if lignes:
                trouvees[chemin] = lignes
    return trouvees


def decrire(trouvees, categorie):
    return "\n".join(f"  {chemin}: lignes {sorted(set(lignes))[:8]} ({categorie})" for chemin, lignes in sorted(trouvees.items()))


def attendus(categorie):
    return sorted(chemin for (cat, chemin) in ATTENDUS if cat == categorie)


def cas_attendus(categories):
    return [
        pytest.param(cat, chemin, id=f"{cat}:{chemin}",
                     marks=pytest.mark.xfail(strict=(cat != "prive"), reason=ATTENDUS[(cat, chemin)]))
        for cat in categories for chemin in attendus(cat)
    ]


@pytest.mark.parametrize("categorie", ["ip", "hote", "entite"])
def test_aucune_valeur_reelle_hors_exceptions(categorie):
    """Plus aucune adresse, aucun nom d'hôte ni aucun identifiant d'entité hors des listes permises."""
    exclus = set(attendus(categorie))
    trouvees = {c: l for c, l in violations(categorie).items() if c not in exclus}
    assert not trouvees, "Valeurs hors des listes permises (valeurs non affichées) :\n" + decrire(trouvees, categorie)


@pytest.mark.parametrize("categorie,chemin", cas_attendus(["ip", "hote", "entite"]))
def test_echec_connu_a_corriger(categorie, chemin):
    """Échec constaté, marqué xfail avec la fiche qui le corrige. Réussir veut dire : retirer l'entrée de ATTENDUS."""
    trouvees = violations(categorie)
    assert chemin not in trouvees, decrire({chemin: trouvees[chemin]}, categorie) if chemin in trouvees else ""


# --- Volet privé ------------------------------------------------------------------------------------------------

DOSSIER_PRIVE = RACINE / "config"
LONGUEUR_MIN = 3

# Chemins pointés de maison.json qui portent des noms, prénoms, alias ou identifiants de personnes.
CHEMINS_NOMS = (
    "securite.nom_occupant", "securite.mots_proteges", "securite.mots_pieces", "securite.zones_protegees",
    "proprietaire.nom", "proprietaire.cle", "proprietaire.variantes",
    "reseau.ssh_ha", "administration.utilisateurs_ha",
)
COORDONNEE = re.compile(r"(?<![\w.])-?\d{1,3}\.\d{3,}(?![\w.])")


def valeur_au_chemin(donnees, chemin):
    for cle in chemin.split("."):
        if not isinstance(donnees, dict) or cle not in donnees:
            return None
        donnees = donnees[cle]
    return donnees


def chaines_de(valeur):
    if isinstance(valeur, str):
        return [valeur]
    if isinstance(valeur, list):
        return [s for v in valeur for s in chaines_de(v)]
    return []


def parcourir(donnees):
    """Toutes les chaînes d'un JSON, clés de dictionnaire comprises."""
    if isinstance(donnees, dict):
        for cle, valeur in donnees.items():
            yield cle
            yield from parcourir(valeur)
    elif isinstance(donnees, list):
        for valeur in donnees:
            yield from parcourir(valeur)
    elif isinstance(donnees, str):
        yield donnees


def motif_mot(chaines):
    """Une alternance qui reconnaît ces chaînes entières (pas au milieu d'un mot), sans tenir compte de la casse."""
    triees = sorted(set(chaines), key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(c) for c in triees) + r")(?!\w)", re.IGNORECASE)


def chaines_sensibles(maison, texte_maison, texte_exemple):
    """Chaînes sensibles de la configuration réelle, hors celles que l'exemple public contient déjà."""
    candidates = set()
    for chemin in CHEMINS_NOMS:
        candidates.update(chaines_de(valeur_au_chemin(maison, chemin)))
    permis = valeur_au_chemin(maison, "securite.permis_personne")
    if isinstance(permis, dict):
        candidates.update(permis)
    for chaine in parcourir(maison):
        candidates.update(i for i, _ in entites_citees(chaine, ENTITE_LARGE))
        candidates.update(m.group(1) for m in IPV4.finditer(chaine) if m.group(2) is None)
        candidates.update(m.group(1) for m in HOTE_TAILNET.finditer(chaine))
        candidates.update(m.group(1) for m in HOTE_LOCAL.finditer(chaine))
    candidates.update(m.group(0) for m in COORDONNEE.finditer(texte_maison))
    candidates = {c.strip() for c in candidates if len(c.strip()) >= LONGUEUR_MIN}
    # Une chaîne que l'exemple public contient déjà est publique par définition (Europe/Paris, salon...).
    return sorted(c for c in candidates if c not in IP_PERMISES and not motif_mot([c]).search(texte_exemple))


def lire_mots_interdits(chemin):
    if not chemin.is_file():
        return []
    lignes = (ligne.strip() for ligne in chemin.read_text(encoding="utf-8").splitlines())
    return [ligne for ligne in lignes if ligne and not ligne.startswith("#")]


def chercher_chaines(textes, chaines, mots_interdits):
    """Chemin -> [(ligne, origine)]. Les chaînes sensibles se cherchent en mots entiers, les mots interdits en
    sous-chaîne (ils visent aussi les noms de fichiers, de variables). Les valeurs ne sont jamais renvoyées."""
    trouvees = {}
    sensibles = motif_mot(chaines) if chaines else None
    interdits = re.compile("|".join(re.escape(m) for m in sorted(set(mots_interdits), key=len, reverse=True)),
                           re.IGNORECASE) if mots_interdits else None
    for chemin, texte in textes.items():
        lignes = []
        if interdits and interdits.search(chemin):
            lignes.append((0, "mot interdit dans le nom du fichier"))
        if sensibles:
            if sensibles.search(chemin):
                lignes.append((0, "chaîne de maison.json dans le nom du fichier"))
            lignes += [(ligne_de(texte, m.start()), "chaîne de maison.json") for m in sensibles.finditer(texte)]
        if interdits:
            lignes += [(ligne_de(texte, m.start()), "mot interdit") for m in interdits.finditer(texte)]
        if lignes:
            trouvees[chemin] = lignes
    return trouvees


class ContextePrive:
    """Chaînes et mots à chercher. Le repr est neutre : pytest l'affiche dans les traces d'échec."""

    def __init__(self, chaines, mots):
        self.chaines = chaines
        self.mots = mots

    def __iter__(self):
        return iter((self.chaines, self.mots))

    def __repr__(self):
        return f"<contexte privé : {len(self.chaines)} chaînes, {len(self.mots)} mots>"


@pytest.fixture(scope="module")
def contexte_prive():
    maison = DOSSIER_PRIVE / "maison.json"
    if not maison.is_file():
        pytest.skip("volet privé sauté : config/maison.json absent (arbre de travail sans la configuration réelle)")
    texte_maison = maison.read_text(encoding="utf-8")
    texte_exemple = (RACINE / "config-exemple" / "maison.json").read_text(encoding="utf-8")
    chaines = chaines_sensibles(json.loads(texte_maison), texte_maison, texte_exemple)
    mots = lire_mots_interdits(DOSSIER_PRIVE / "mots-interdits.txt")
    return ContextePrive(chaines, mots)


def decrire_prive(trouvees):
    return "\n".join(
        f"  {chemin}: " + ", ".join(sorted({f"ligne {l} ({o})" if l else o for l, o in lignes})[:6])
        for chemin, lignes in sorted(trouvees.items())
    )


def test_prive_aucune_chaine_sensible_hors_exceptions(contexte_prive):
    """Rien de config/maison.json ni de config/mots-interdits.txt dans les fichiers suivis ni dans leurs noms."""
    chaines, mots = contexte_prive
    exclus = set(attendus("prive"))
    trouvees = {c: l for c, l in chercher_chaines(fichiers_suivis(), chaines, mots).items() if c not in exclus}
    assert not trouvees, (f"{len(chaines)} chaînes sensibles et {len(mots)} mots interdits cherchés, valeurs non "
                          "affichées. Fichiers concernés :\n" + decrire_prive(trouvees))


@pytest.mark.parametrize("categorie,chemin", cas_attendus(["prive"]))
def test_prive_echec_connu_a_corriger(contexte_prive, categorie, chemin):
    """Échec constaté du volet privé, marqué xfail avec la fiche qui le corrige (aucun pour l'instant)."""
    chaines, mots = contexte_prive
    textes = {chemin: fichiers_suivis()[chemin]}
    trouvees = chercher_chaines(textes, chaines, mots)
    assert not trouvees, decrire_prive(trouvees)


# --- Le détecteur lui-même : il doit échouer sur une valeur réelle et laisser passer les permises ---------------


def fragments(*morceaux):
    """Assemble une valeur de test à l'exécution, pour que ce fichier ne contienne pas la valeur qu'il détecte."""
    return "".join(morceaux)


def test_detecte_une_adresse_hors_liste():
    ip_privee = fragments("192.168", ".7.", "41")
    ip_publique = fragments("93.184", ".216.", "34")
    assert trouver_ip(f"ligne 1\nhote = {ip_privee}\n") == [2]
    assert trouver_ip(f"ping {ip_publique} ok") == [1]
    assert trouver_ip(f"wss://{ip_privee}:8766") == [1]
    assert trouver_ip(f"::ffff:{ip_privee}") == [1]


def test_adresses_permises_et_reseaux():
    for permise in ("127.0.0.1", "0.0.0.0", "172.30.32.2", "192.168.0.10", "192.0.2.77", "198.51.100.9",
                    "203.0.113.200", "8.8.8.8", "1.1.1.1", "1.2.3.4"):
        assert trouver_ip(f"a {permise} b") == [], permise
    for reseau in ("10.0.0.0/8", "100.64.0.0/10", "192.168.0.0/16", "169.254.0.0/16"):
        assert trouver_ip(f"autorise {reseau}") == [], reseau
    assert trouver_ip(fragments("192.168.", "3.9/32")) == [1]


def test_numeros_de_version_ne_sont_pas_des_adresses():
    assert trouver_ip("v10.20.30.40") == []
    assert trouver_ip("version 10.20.30.40") == []
    assert trouver_ip("1.2.3.4.5") == []
    assert trouver_ip("2026.10.25.1") == []
    version = fragments("5.0.", "0.93")
    tableau = f"| Paquet | Version | Licence |\n|---|---|---|\n| opencv | {version} | Apache 2.0 |\n"
    assert trouver_ip(tableau) == []
    ip = fragments("93.184", ".216.", "34")
    assert trouver_ip(f"| Machine | Adresse |\n|---|---|\n| pc | {ip} |\n") == [3]
    assert trouver_ip(f"| Paquet | Version |\n|---|---|\n| pc | 1.2.3 | {ip} |\n") == [3]


def test_detecte_les_noms_d_hote_reels():
    assert trouver_hotes(fragments("machine.", "reelle", ".ts.net")) == [1]
    assert trouver_hotes(fragments("a\nb\nssh://", "serveur-x", ".local:22")) == [3]
    assert trouver_hotes("sante.exemple.ts.net et exemple.ts.net") == []
    assert trouver_hotes("homeassistant.local pc-maison.local PC.local ha.local") == []
    assert trouver_hotes("CLAUDE.local.md et threading.local()") == []


def test_detecte_les_entites_inconnues():
    inconnue = fragments("light.", "chambre_reelle_plafond")
    assert trouver_entites(f"x\n{inconnue}") == [2]
    assert trouver_entites(fragments("switch.", "prise_du_voisin")) == [1]
    exemple = sorted(entites_de_l_exemple())[0]
    assert trouver_entites(exemple) == []
    assert trouver_entites("light.turn_on media_player.volume_set cover.open_cover") == []
    assert trouver_entites("light.a et media_player.autre") == []
    assert trouver_entites(fragments("mon_li", "ght.truc")) == []


def test_l_exemple_public_fournit_des_entites():
    """Sans entités dans l'exemple, tout identifiant des tests passerait pour inconnu, ou l'inverse."""
    assert len(entites_de_l_exemple()) > 10


def test_ne_lit_que_des_textes_suivis():
    textes = fichiers_suivis()
    assert "poc/tests/conftest.py" in textes
    assert not any(c.endswith((".png", ".onnx", ".gif")) for c in textes)
    assert not any(c.startswith("config/") for c in textes)


def test_volet_prive_sur_une_configuration_fictive():
    """Le volet privé trouve les chaînes d'une configuration, sans afficher leurs valeurs, et épargne l'exemple."""
    prenom = fragments("Ys", "olde")
    entite = fragments("light.", "bureau_de_", "ysolde")
    ip = fragments("10.77", ".5.", "9")
    maison = {
        "securite": {"nom_occupant": prenom, "mots_proteges": [prenom.lower(), "ab"], "zones_protegees": ["salon"]},
        "reseau": {"ssh_ha": fragments("ha-", "ysolde"), "ha_url": f"http://{ip}:8123"},
        "appareils": {entite: "Bureau", "tele": "media_player.tele_salon"},
        "mer": {"lat": "43.2965", "lon": "5.3698"},
    }
    texte = json.dumps(maison)
    exemple = '{"securite": {"zones_protegees": ["salon"]}, "appareils": {"tele": "media_player.tele_salon"}}'
    chaines = chaines_sensibles(maison, texte, exemple)
    assert {prenom, prenom.lower(), entite, ip, fragments("ha-", "ysolde"), "43.2965", "5.3698"} <= set(chaines)
    assert "salon" not in chaines and "media_player.tele_salon" not in chaines and "ab" not in chaines
    textes = {
        "docs/propre.md": "Rien ici.\n",
        "docs/fuite.md": f"un\ndeux\nl'adresse {ip}\n",
        f"poc/{prenom.lower()}.py": "pass\n",
    }
    trouvees = chercher_chaines(textes, chaines, ["interdit-xyz"])
    assert set(trouvees) == {"docs/fuite.md", f"poc/{prenom.lower()}.py"}
    assert trouvees["docs/fuite.md"] == [(3, "chaîne de maison.json")]
    assert trouvees[f"poc/{prenom.lower()}.py"] == [(0, "chaîne de maison.json dans le nom du fichier")]
    mots = chercher_chaines({"poc/interdit-xyz.py": "x\nINTERDIT-xyz\n"}, [], ["interdit-xyz"])
    assert mots["poc/interdit-xyz.py"] == [(0, "mot interdit dans le nom du fichier"), (2, "mot interdit")]
    message = decrire_prive(trouvees)
    assert ip not in message and prenom not in message


def test_lire_mots_interdits(tmp_path):
    fichier = tmp_path / "mots-interdits.txt"
    assert lire_mots_interdits(fichier) == []
    fichier.write_text("# commentaire\n\nmot-un\n  mot-deux  \n", encoding="utf-8")
    assert lire_mots_interdits(fichier) == ["mot-un", "mot-deux"]


# --- Le garde-fou git lit la liste privée (D12) ------------------------------------------------------------------


def trouver_bash():
    """Le bash de Git for Windows (pas celui de WSL) ou le bash du système, ou None."""
    git = shutil.which("git")
    if sys.platform == "win32" and git:
        # git.exe peut être dans cmd/, bin/ ou mingw64/bin/ : on remonte jusqu'à la racine de Git for Windows.
        for parent in Path(git).resolve().parents:
            candidat = parent / "bin" / "bash.exe"
            if candidat.is_file():
                return str(candidat)
        return None
    return shutil.which("bash")


@pytest.fixture
def depot_factice(tmp_path):
    """Dépôt git jetable qui contient une copie du garde-fou, avec une liste privée factice (aucune vraie valeur)."""
    bash, git = trouver_bash(), shutil.which("git")
    if not bash or not git:
        pytest.skip("bash ou git introuvable")
    depot = tmp_path / "depot"
    (depot / ".githooks").mkdir(parents=True)
    (depot / "config").mkdir()
    shutil.copy(RACINE / ".githooks" / "garde-fou.sh", depot / ".githooks" / "garde-fou.sh")
    mot = fragments("zorg", "lub")
    (depot / "config" / "mots-interdits.txt").write_text(f"# commentaire\n\n  {mot}  \n", encoding="utf-8")
    subprocess.run([git, "init", "-q"], cwd=depot, check=True)

    def lancer(fichiers):
        for chemin, contenu in fichiers.items():
            cible = depot / chemin
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_text(contenu, encoding="utf-8")
            subprocess.run([git, "add", "--", chemin], cwd=depot, check=True, capture_output=True)
        r = subprocess.run([bash, ".githooks/garde-fou.sh", "--index"], cwd=depot, capture_output=True, text=True,
                           encoding="utf-8")
        for chemin in fichiers:
            subprocess.run([git, "rm", "-q", "--cached", "-f", "--", chemin], cwd=depot, capture_output=True)
        return r, mot

    return depot, lancer


def test_garde_fou_laisse_passer_un_fichier_neutre(depot_factice):
    _, lancer = depot_factice
    r, _ = lancer({"neutre.txt": "un commentaire ordinaire\n"})
    assert r.returncode == 0, r.stdout + r.stderr


def test_garde_fou_refuse_un_mot_interdit_dans_le_contenu(depot_factice):
    _, lancer = depot_factice
    r, mot = lancer({"notes.txt": f"ligne neutre\nune phrase avec {fragments('ZORG', 'LUB')} dedans\n"})
    assert r.returncode == 1
    assert mot not in (r.stdout + r.stderr).lower(), "le garde-fou ne doit pas afficher le mot trouvé"


def test_garde_fou_refuse_un_mot_interdit_dans_un_chemin(depot_factice):
    _, lancer = depot_factice
    mot = fragments("zorg", "lub")
    r, _ = lancer({f"dossier/essai_{mot.capitalize()}.txt": "contenu neutre\n"})
    assert r.returncode == 1
    assert mot not in (r.stdout + r.stderr).lower()


def test_garde_fou_sans_liste_avertit_et_garde_les_controles_generiques(depot_factice):
    depot, lancer = depot_factice
    (depot / "config" / "mots-interdits.txt").unlink()
    r, _ = lancer({"neutre.txt": "texte\n"})
    assert r.returncode == 0
    assert "mots-interdits.txt absent" in r.stderr
    r, _ = lancer({"poc/.env": "contenu\n"})
    assert r.returncode == 1, "les contrôles existants restent actifs sans la liste"


def test_garde_fou_ne_contient_aucun_mot_en_dur():
    """Le garde-fou lit la liste privée : aucun mot de config/mots-interdits.txt n'est écrit dans son code."""
    texte = (RACINE / ".githooks" / "garde-fou.sh").read_text(encoding="utf-8").lower()
    assert "config/mots-interdits.txt" in texte
    chemin = DOSSIER_PRIVE / "mots-interdits.txt"
    if chemin.is_file():
        assert not [m for m in lire_mots_interdits(chemin) if m.lower() in texte], "mot interdit écrit en dur"
