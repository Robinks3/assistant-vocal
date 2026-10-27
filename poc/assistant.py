"""Assistant vocal local, POC.

Micro -> Canary 1B v2 en français (STT, CPU) -> dictionnaire de commandes (commandes.yaml de la configuration)
-> intentions locales de Home Assistant
-> sinon LLM (llama-server local ou Claude) avec outils HA -> Piper (TTS) -> haut-parleurs.

Usage :
  python poc/assistant.py               appui sur Entrée pour parler
  python poc/assistant.py --reveil      mot de réveil de la configuration (section reveil de maison.json)
  python poc/assistant.py --clavier     commandes tapées au clavier (sans micro)
  python poc/assistant.py --texte "allume la lumière"   une seule commande
  ajouter --essai : affiche ce qui serait fait, sans rien exécuter
  python poc/assistant.py --version
"""
import argparse, contextlib, contextvars, difflib, csv, json, os, re, sys, threading, time

import acces
import commandes_dynamiques
import journal_web
import maison
import routines
import securite
from liste_blanche import (SERVICES_PERMIS, DOMAINES_HORS_LLM, DOMAINES_ADMIN, NOMS_ECARTES, SERVICES_ECARTES,
                           SELECTEURS_VERS_UN_APPAREIL, _cible_son_domaine, _champ_vers_un_appareil)
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple


class Requete:
    """Ce qui vaut le temps d'une commande : essai effectif, personne qui parle, appareil d'origine, rôle et canal.

    Porté par une variable de contexte et non plus par les objets partagés (0.28.0) : une commande du
    client web et une phrase de la tablette ne se prennent plus leur essai ni leur personne.
    asyncio.to_thread copie le contexte, la requête suit donc la commande dans son fil.

    role : rôle effectif de l'appareil d'origine (acces.role_effectif : administrateur, habitant, partage ou
    invite), « local » pour le micro du PC, vide si inconnu. canal : voix, texte, appli ou web, vide si inconnu
    (0.40.0). Ni l'un ni l'autre ne vient du texte d'un message : le rôle sort de l'identité de la session, le
    canal de la voie par laquelle la commande est arrivée. La personne suit la même règle
    (acces.personne_effective)."""

    def __init__(self, essai=False, personne=None, appareil=None, indication="", role="", canal=""):
        self.essai, self.personne, self.appareil, self.indication = bool(essai), personne or None, appareil, indication
        self.role, self.canal = role or "", canal or ""


REQUETE = contextvars.ContextVar("requete", default=None)
# Identifiant de la demande en cours, posé par le serveur quand il l'annonce au journal du client web (étape
# « entendu »). journaliser le reprend pour que l'entrée finale remplace la carte « En cours ». Vide : un neuf.
ID_DEMANDE = contextvars.ContextVar("id_demande", default=None)


def requete_en_cours():
    return REQUETE.get()

# Appareils propres à la maison (section appareils de maison.json) : la télé, sa famille d'entités (même
# préfixe, pour la présélection du LLM) et la musique. Sans musique configurée (pas d'enceinte « toutes »),
# les commandes de musique sont refusées proprement.
APPAREILS = maison.CONFIG.get("appareils") or {}
TELE = str(APPAREILS.get("tele") or "")
TELE_FAMILLE = str(APPAREILS.get("tele_famille") or "")
MUSIQUE_MAISON = APPAREILS.get("musique") or {}
SCRIPT_LANCER = str(MUSIQUE_MAISON.get("script_lancer") or "")
LLM_MAISON = maison.CONFIG.get("llm") or {}

VERSION = "0.51.0"
DATE_VERSION = "2026-10-27"

ICI = Path(__file__).resolve().parent
# Données vivantes (dictionnaire, phrases apprises, journal) : à côté du code sur le PC, dans le
# dossier persistant /data dans l'appli Home Assistant (variable JARVIS_DONNEES).
DONNEES = Path(os.getenv("JARVIS_DONNEES", str(ICI)))
JOURNAL = DONNEES / "journal" / "latences.csv"
# Demande du 13/10/2026 : retenir chaque phrase que le dictionnaire n'a pas trouvée, et ses
# notes « bien » ou « pas bien » sur ce que l'assistant a fait, pour améliorer le dictionnaire.
MANQUES = DONNEES / "journal" / "manques.jsonl"
RETOURS = DONNEES / "journal" / "retours.jsonl"
MUSIQUE = DONNEES / "journal" / "musique.jsonl"
TAUX = 16000

# Services de Home Assistant permis : la table et ses listes d'exclusion vivent dans liste_blanche.py (0.41.0),
# lues aussi par la passerelle de l'appli (acces.controler_service). Importées en tête de fichier.
# Ce que le LLM voit dans la liste d'appareils, et le seul périmètre de ses appels (26/10/2026, D6) : la table
# s'élargit, pas la vue du LLM. Les entités des domaines ajoutés grossiraient le prompt de Qwen 9B sans mesure
# sur la vraie maison, et il ne peut viser que ce qu'il voit (HomeAssistant.service refuse le reste). Pour
# l'élargir : ajouter le domaine ici, après mesure de la latence (banc llm_maison) sur la vraie maison.
# Les boutons (36 chez aspirateur) gonflent le prompt sans servir à la voix.
# Ni boutons ni interrupteurs : dans la maison d'origine, ce sont des réglages (enceintes, aspirateur) qui embrouillent
# Qwen 9B (« Lecture automatique TV » pris pour la télé, banc du 12/10). Le dictionnaire les couvre.
DOMAINES_LLM = {"climate", "cover", "fan", "input_boolean", "light", "media_player", "music_assistant", "scene",
                "script", "vacuum"}
DOMAINES_CONTEXTE = sorted(DOMAINES_LLM | {"sensor", "binary_sensor", "weather"})
# Domaines de l'outil appeler_service : ceux du contexte, plus button et switch qui ont toujours été permis
# au LLM sans figurer dans sa liste.
DOMAINES_OUTIL_LLM = DOMAINES_LLM | {"button", "switch"}


def services_depuis_ha(liste):
    """Services que HA expose en plus de SERVICES_PERMIS, d'après la réponse de GET /api/services.

    Un service n'entre que s'il agit sur les entités de son propre domaine (cible « entity » filtrée sur ce
    domaine ou sur l'intégration du même nom) et ne désigne pas d'autres appareils dans ses données. Rien d'un
    domaine interdit, d'un domaine d'administration, ni d'un service de la liste SERVICES_ECARTES. Les services
    sans cible (mqtt.publish, logger.set_level, backup.create...) n'y entrent donc jamais. Une réponse illisible
    donne une table vide : le socle statique suffit."""
    trouves = {}
    if not isinstance(liste, list):
        return trouves
    for bloc in liste:
        domaine = bloc.get("domain") if isinstance(bloc, dict) else None
        services = bloc.get("services") if isinstance(bloc, dict) else None
        if not isinstance(domaine, str) or not isinstance(services, dict):
            continue
        if domaine in acces.DOMAINES_INTERDITS or domaine in DOMAINES_ADMIN:
            continue
        for nom, fiche in services.items():
            if not isinstance(nom, str) or not isinstance(fiche, dict) or not re.fullmatch(r"[a-z0-9_]+", nom):
                continue
            if nom in NOMS_ECARTES or nom.startswith("reload") or f"{domaine}.{nom}" in SERVICES_ECARTES:
                continue
            if nom in SERVICES_PERMIS.get(domaine, set()) or not _cible_son_domaine(domaine, fiche.get("target")):
                continue
            if _champ_vers_un_appareil(fiche.get("fields")):
                continue
            if f"{domaine}.{nom}" == "media_player.volume_up" and securite.plafond_actif():
                continue
            trouves.setdefault(domaine, set()).add(nom)
    return trouves


# Valeurs sûres d'un moteur sans poc/.env (0.36.0) : le micro est le périphérique d'entrée par défaut du système,
# la voix est celle que poc/outils/telecharger_modeles.py range dans poc/voix/.
MICRO_DEFAUT = "defaut"
VOIX_DEFAUT = ICI / "voix" / "fr_FR-siwis-medium.onnx"


def charger_env():
    from dotenv import load_dotenv
    load_dotenv(ICI / ".env")
    return {
        "ha_url": os.getenv("HA_URL", maison.reseau("ha_url")).rstrip("/"),
        "ha_token": os.getenv("HA_TOKEN", "").strip(),
        "llm_url": os.getenv("LLM_URL", "http://127.0.0.1:8080/v1").rstrip("/"),
        "llm_modele": os.getenv("LLM_MODELE", "assistant-vocal"),
        "micro": os.getenv("MICRO", MICRO_DEFAUT),
        "sortie": os.getenv("SORTIE", ""),
        "voix": os.getenv("VOIX", str(VOIX_DEFAUT)),
        "llm_fournisseur": os.getenv("LLM_FOURNISSEUR", "local").strip().lower(),
        "claude_modele": os.getenv("CLAUDE_MODELE", "claude-haiku-5-5"),
    }


# ---------------------------------------------------------------- audio
def trouver_peripherique(nom, entree):
    """Numéro du périphérique audio dont le nom contient [nom], ou None : sounddevice prend alors le périphérique
    par défaut du système. Un nom vide ou « defaut » désigne volontairement ce périphérique par défaut (MICRO et
    SORTIE de poc/.env, MICRO_DEFAUT sans réglage), sans interroger le matériel."""
    if not nom or nom.strip().lower() in ("defaut", "default"):
        return None
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        canaux = d["max_input_channels"] if entree else d["max_output_channels"]
        if nom.lower() in d["name"].lower() and canaux > 0 and d["hostapi"] == 0:
            return i
    return None


# Affichage de l'état dans le terminal : couleurs ANSI et vumètre sur une seule ligne.
VERT, JAUNE, GRIS, CYAN, RAZ = "\033[92m", "\033[93m", "\033[90m", "\033[96m", "\033[0m"
LARGEUR = 40


def activer_couleurs():
    if os.name == "nt":
        os.system("")  # active les séquences ANSI de la console Windows


def barre(niveau, seuil):
    """Vumètre de -60 à 0 dBFS, avec un | à la hauteur du seuil de parole."""
    import math
    def pos(v):
        return int(min(max((20 * math.log10(max(v, 1e-6)) + 60) / 60, 0), 1) * LARGEUR)
    n, s = pos(niveau), pos(seuil)
    cases = ["#" if i < n else "." for i in range(LARGEUR)]
    if s < LARGEUR:
        cases[s] = "|"
    return "".join(cases)


def etat(texte, couleur, niveau=None, seuil=None):
    ligne = f"  {couleur}{texte:<22}{RAZ}"
    if niveau is not None:
        ligne += f" [{couleur if niveau > seuil else GRIS}{barre(niveau, seuil)}{RAZ}]"
    print("\r" + ligne + " " * 4, end="", flush=True)


def fin_etat():
    print("\r" + " " * 80 + "\r", end="", flush=True)


class Oreille:
    """Capture du micro et découpage d'une phrase : Silero VAD si son modèle est là (poc/modeles),
    sinon l'énergie du signal. Avec Silero, la phrase se termine après 0,45 s de silence."""

    def __init__(self, micro):
        import sounddevice as sd
        import vad
        self.sd = sd
        self.dev = trouver_peripherique(micro, True)
        self.bruit = 0.004
        self.vad = vad.creer()

    @property
    def seuil(self):
        return max(self.bruit * 3.5, 0.012)

    def calibrer(self):
        import numpy as np
        x = self.sd.rec(int(0.6 * TAUX), samplerate=TAUX, channels=1, dtype="float32", device=self.dev)
        self.sd.wait()
        self.bruit = max(float(np.sqrt(np.mean(x ** 2))), 0.002)

    def ecouter_phrase(self, attente_max=6.0, silence_fin=None, duree_max=12.0):
        """Renvoie le signal de la phrase (float32, 16 kHz) ou None si rien n'est dit."""
        import numpy as np
        seuil = self.seuil
        if silence_fin is None:
            silence_fin = 0.45 if self.vad else 0.8
        if self.vad:
            self.vad.reinitialiser()
        bloc = int(0.032 * TAUX)  # une fenêtre de Silero
        morceaux, parle, silence, t0 = [], False, 0.0, time.time()
        avant = []  # 320 ms gardées avant le début de la parole
        with self.sd.InputStream(samplerate=TAUX, channels=1, dtype="float32",
                                 blocksize=bloc, device=self.dev) as flux:
            while True:
                x, _ = flux.read(bloc)
                x = x[:, 0].copy()
                niveau = float(np.sqrt(np.mean(x ** 2)))
                fort = self.vad.parole(x) if self.vad else niveau > seuil
                if not parle:
                    reste = attente_max - (time.time() - t0)
                    etat(f"PARLEZ ({reste:3.1f} s)", CYAN, niveau, seuil)
                    avant = (avant + [x])[-10:]
                    if fort:
                        parle, morceaux = True, avant[:]
                    elif reste <= 0:
                        fin_etat()
                        return None
                    continue
                morceaux.append(x)
                silence = 0.0 if fort else silence + 0.032
                etat("J'ÉCOUTE" if fort else f"fin dans {max(silence_fin - silence, 0):3.1f} s",
                     VERT, niveau, seuil)
                if silence >= silence_fin or len(morceaux) * 0.032 > duree_max:
                    break
        fin_etat()
        return np.concatenate(morceaux)


# Mot de réveil : seul modèle que openWakeWord sait détecter sans fichier de la configuration, et mot par défaut
# du moteur public (décision D5 du plan : un mot générique, réglable dans maison.json).
MODELE_REPLI, NOM_REPLI = "hey_jarvis", "Hey Jarvis"
MOT_REVEIL_DEFAUT = "assistant"


class ReglageReveil(NamedTuple):
    """Mot de réveil réellement guetté. [modele] : argument pour openWakeWord (chemin du .onnx ou MODELE_REPLI).
    [nom] : nom affiché à l'utilisateur, toujours celui du mot détecté. [mot] : mot demandé par la configuration.
    [repli] : phrase de journal quand le modèle du mot demandé est absent, chaîne vide sinon."""
    modele: str
    nom: str
    mot: str
    repli: str


def reglage_reveil():
    """Mot de réveil à guetter et son nom affiché. Ordre de priorité du mot demandé :
    1. `reveil.mot` de la section reveil de maison.json (nom affiché : `reveil.nom`, sinon le mot capitalisé) ;
    2. la variable MOT_REVEIL de poc/.env, réglage de secours qui ne casse pas une installation existante ;
    3. « assistant », le défaut du moteur public (décision D5).
    Le modèle de ce mot est le fichier reveil/<mot>.onnx du dossier de configuration. S'il est absent, le seul
    modèle détectable est MODELE_REPLI : le moteur se replie dessus, le nom affiché devient NOM_REPLI et
    [repli] porte la phrase à écrire dans le journal. Le nom affiché est donc toujours celui du mot détecté."""
    section = maison.CONFIG.get("reveil")
    section = section if isinstance(section, dict) else {}
    mot_config = str(section.get("mot") or "").strip().lower()
    mot = mot_config or os.getenv("MOT_REVEIL", "").strip().lower() or MOT_REVEIL_DEFAUT
    if mot in (MODELE_REPLI, MODELE_REPLI + "_v0.1"):
        return ReglageReveil(MODELE_REPLI, NOM_REPLI, mot, "")
    fichier = maison.DOSSIER / "reveil" / f"{mot}.onnx"
    if Path(mot).name == mot and fichier.exists():
        nom = str(section.get("nom") or "").strip() if mot_config == mot else ""
        return ReglageReveil(str(fichier), nom or mot.capitalize(), mot, "")
    return ReglageReveil(MODELE_REPLI, NOM_REPLI, mot,
                         f"modèle de réveil absent pour le mot {mot} (attendu : {fichier}), repli sur {NOM_REPLI}")


def modele_reveil():
    """Couple (argument pour openWakeWord, nom affiché) de reglage_reveil()."""
    r = reglage_reveil()
    return r.modele, r.nom


def annoncer_repli_reveil():
    """Écrit dans le journal la phrase de repli du mot de réveil, s'il y en a une. Renvoie le réglage utilisé."""
    r = reglage_reveil()
    if r.repli:
        print(f"  {r.repli}")
    return r


def prononciation_reveil():
    """Couple (texte, langue) à faire dire par une voix de synthèse pour déclencher le mot de réveil réellement
    guetté (outils de test dire.py et faux_telephone.py). Même source que le serveur : reglage_reveil().
    Langue « en » pour le modèle de repli (« Hey Jarvis » se prononce à l'anglaise) et pour un mot dont
    `reveil.langue` commence par « en », « fr » sinon (« fr », « français », ou langue non renseignée)."""
    r = reglage_reveil()
    if r.modele == MODELE_REPLI:
        return f"{r.nom}!", "en"
    section = maison.CONFIG.get("reveil")
    langue = str(section.get("langue") or "").strip().lower() if isinstance(section, dict) else ""
    return f"{r.nom}!", "en" if langue.startswith("en") else "fr"


class Reveil:
    """Mot de réveil openWakeWord (reglage_reveil : section reveil de maison.json, repli « Hey Jarvis »)."""

    def __init__(self, micro, seuil=0.5):
        import openwakeword
        from openwakeword.model import Model
        reglage = annoncer_repli_reveil()
        modele, self.nom = reglage.modele, reglage.nom
        if modele == MODELE_REPLI:
            openwakeword.utils.download_models([MODELE_REPLI])
        self.modele = Model(wakeword_models=[modele], inference_framework="onnx")
        self.dev = trouver_peripherique(micro, True)
        self.seuil = seuil

    def attendre(self, seuil_parole):
        import numpy as np, sounddevice as sd
        self.modele.reset()
        with sd.InputStream(samplerate=TAUX, channels=1, dtype="int16", blocksize=1280,
                            device=self.dev) as flux:
            while True:
                x, _ = flux.read(1280)
                niveau = float(np.sqrt(np.mean((x[:, 0] / 32768.0) ** 2)))
                score = max(self.modele.predict(x[:, 0]).values())
                etat(f"« {self.nom} » ? {score:4.2f}", GRIS, niveau, seuil_parole)
                if score >= self.seuil:
                    fin_etat()
                    return


def verifier_voix(chemin):
    """Arrête le démarrage avec un message clair quand le fichier de la voix Piper (VOIX de poc/.env, VOIX_DEFAUT
    sans réglage) est absent, plutôt qu'une exception obscure au chargement du modèle."""
    if not Path(chemin).is_file():
        raise SystemExit(f"Voix Piper absente ({chemin}). La récupérer par python poc/outils/telecharger_modeles.py, "
                         "ou régler VOIX dans poc/.env sur le fichier .onnx d'une autre voix.")


class Voix:
    def __init__(self, chemin, sortie):
        verifier_voix(chemin)
        from piper import PiperVoice
        self.voix = PiperVoice.load(chemin)
        self.taux = self.voix.config.sample_rate
        self.dev = trouver_peripherique(sortie, False)

    def synthetiser(self, texte):
        import numpy as np
        brut = b"".join(c.audio_int16_bytes for c in self.voix.synthesize(texte))
        return np.frombuffer(brut, np.int16)

    def jouer(self, signal, taux=None):
        import sounddevice as sd
        sd.play(signal, taux or self.taux, device=self.dev)
        sd.wait()

    def bip(self, freq=880, duree=0.12):
        import numpy as np
        t = np.arange(int(self.taux * duree)) / self.taux
        self.jouer((0.25 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16))


# ---------------------------------------------------------------- STT
class Transcripteur:
    """Canary 1B v2 int8, français imposé : 0,2 à 0,4 s par commande.

    Parakeet v3 (même vitesse) devine la langue à chaque phrase et a transcrit une
    commande française en « I mean. » le 11/10 : écarté."""

    def __init__(self):
        import onnx_asr
        self.modele = onnx_asr.load_model("nemo-canary-1b-v2", quantization="int8")

    def transcrire(self, signal):
        return self.modele.recognize(signal, language="fr").strip()


# ---------------------------------------------------------------- Home Assistant
ATTRIBUTS_LUS = ("friendly_name", "brightness", "temperature", "current_temperature",
                 "volume_level", "media_title", "media_artist", "source", "unit_of_measurement")
# Lampe (0.31.0) : mode de couleur et réglages, pour répondre à « elle est en quelle couleur ? ».
ATTRIBUTS_LAMPE = ("color_mode", "color_temp_kelvin", "hs_color", "rgb_color",
                   "min_color_temp_kelvin", "max_color_temp_kelvin")


def attributs_lus(attrs):
    """Attributs d'une entité que lire_etat montre au LLM. Les réglages de couleur d'une lampe éteinte
    (null dans HA) sont omis."""
    r = {k: v for k, v in attrs.items() if k in ATTRIBUTS_LUS}
    r.update({k: v for k, v in attrs.items() if k in ATTRIBUTS_LAMPE and v is not None})
    return r


class HomeAssistant:
    # Services ajoutés d'après HA (charger_services), remplacés en bloc et jamais modifiés sur place.
    services_dynamiques = {}

    def __init__(self, url, token):
        import httpx
        self.url = url
        self.client = httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=15)
        self.conv_id = None
        self.essai = False
        self.vue_llm = {}
        # Entités de la liste donnée au LLM (dernier inventaire) : les seules qu'il peut viser.
        # Idée reprise d'un projet d'inspiration : la liste part aussi en enum dans le schéma de l'outil.
        self.entites_llm = set()
        # Services que HA expose en plus de SERVICES_PERMIS (charger_services), vide tant que HA n'a pas répondu.
        self.services_dynamiques = {}

    def charger_services(self):
        """Complète SERVICES_PERMIS avec ce que HA expose (GET /api/services, filtré par services_depuis_ha).

        Appelé une fois au démarrage. HA injoignable, réponse illisible ou en erreur : aucune erreur, le socle
        statique suffit. Rend le nombre de services ajoutés."""
        try:
            r = self.client.get(f"{self.url}/api/services", timeout=5)
            r.raise_for_status()
            self.services_dynamiques = services_depuis_ha(r.json())
        except Exception as e:
            self.services_dynamiques = {}
            print(f"  services de HA non chargés ({type(e).__name__}) : socle statique seul")
        return sum(len(s) for s in self.services_dynamiques.values())

    def services_permis(self, domaine):
        """Services permis pour un domaine : le socle statique plus ce que HA expose en plus."""
        return SERVICES_PERMIS.get(domaine, set()) | self.services_dynamiques.get(domaine, set())

    # Essai de la commande en cours (Requete) ou du serveur : le réglage direct (ha.essai = True) est un
    # plancher, aucune requête ne le lève.
    @property
    def essai(self):
        r = REQUETE.get()
        return bool(r and r.essai) or getattr(self, "_essai", False)

    @essai.setter
    def essai(self, valeur):
        self._essai = bool(valeur)

    @property
    def personne(self):
        """Qui parle d'après la session (règle 3 de securite.py) : celle de la requête en cours, personne hors
        requête. Lecture seule depuis 0.40.0, plus aucun réglage direct sur l'objet partagé."""
        r = REQUETE.get()
        return r.personne if r else None

    def conversation(self, texte, personne=None):
        """Intentions locales de HA (agent intégré, aucun LLM), utilisées en repli quand le LLM échoue.

        Assist agit sans qu'on voie sa cible avant : sauté tant que la sécurité est en dur, sauf si le réglage
        securite.assist_repli l'ouvre ET que la phrase passe le filtre de securite.refus_phrase_assist (S-D9).
        Le code rendu en 3e valeur dit pourquoi le repli a été coupé, refusé ou tenté."""
        permis, motif = securite.repli_assist(texte, personne)
        if not permis:
            self.dernieres_cibles = []
            return False, "", f"Assist sauté (sécurité, {motif})"
        print(f"  [repli Assist] {motif}")
        r = self.client.post(f"{self.url}/api/conversation/process", json={
            "text": texte, "language": "fr", "agent_id": "conversation.home_assistant"})
        r.raise_for_status()
        rep = r.json()["response"]
        parole = rep.get("speech", {}).get("plain", {}).get("speech", "")
        compris = rep.get("response_type") != "error"
        # Appareils touchés par HA (intentions intégrées) : gardés pour l'historique de l'appli.
        self.dernieres_cibles = [f"ha {c.get('type', '')} {c.get('id') or c.get('name', '')}".strip()
                                 for c in (rep.get("data", {}).get("success") or [])]
        return compris, parole, rep.get("data", {}).get("code")

    def inventaire(self):
        """Renvoie (liste fixe « entity_id | nom | pièce », états du moment « entity_id=état »).

        La liste ne change pas d'une question à l'autre, donc llama-server la garde en cache.
        Les états partent à la fin, juste avant la demande : avec les états au milieu du prompt,
        chaque ampoule allumée faisait relire 4 000 tokens (3 à 5,5 s par commande, banc v0.5.1).
        Sans états du tout, Qwen annonçait « je vérifie » sans rien lire (essai v0.2.1)."""
        modele = ("{% for s in states if s.domain in " + json.dumps(DOMAINES_CONTEXTE) + " %}"
                  "{% if s.domain not in ['sensor','binary_sensor'] or s.attributes.device_class "
                  "in ['temperature','humidity','door','window'] %}"
                  "{{ s.entity_id }}\t{{ s.name }}\t{{ area_name(s.entity_id) or '' }}\t{{ s.state }}"
                  "{% if s.attributes.unit_of_measurement %} {{ s.attributes.unit_of_measurement }}{% endif %}"
                  "{% if s.domain == 'light' and s.attributes.brightness %} {{ (s.attributes.brightness / 5.55) | round }} %{% endif %}"
                  "\n{% endif %}{% endfor %}")
        r = self.client.post(f"{self.url}/api/template", json={"template": modele})
        r.raise_for_status()
        lignes = sorted(l.split("\t") for l in r.text.strip().splitlines() if l.count("\t") == 3)
        # Vue du LLM (section llm de commandes.yaml) : doublons masqués, noms clarifiés.
        masquer = set(self.vue_llm.get("masquer") or [])
        renommer = self.vue_llm.get("renommer") or {}
        notes = self.vue_llm.get("notes") or {}
        # Rien de l'occupant protégé, sauf ses lumières quand c'est lui que la tablette reconnaît (règle 3).
        permises = securite.entites_permises(self.personne)
        lignes = [[e, renommer.get(e, nom) + (f" [{notes[e]}]" if e in notes else ""), piece, etat]
                  for e, nom, piece, etat in lignes if e not in masquer
                  and (e in permises or (not securite.protege(e) and not securite.piece_protegee(piece)))]
        self.entites_llm = {e for e, _, _, _ in lignes}
        liste = "\n".join(f"{e} | {nom} | {piece}" for e, nom, piece, _ in lignes)
        # Seulement ce qui est allumé ou actif : 1 080 tokens d'états complets coûtaient 0,9 s
        # de lecture à chaque commande. Le reste est déclaré éteint dans la phrase d'en-tête.
        repos = ("off", "idle", "standby", "unavailable", "unknown", "docked", "paused")
        actifs = [f"{e}={etat}" for e, _, _, etat in lignes
                  if not e.startswith(("script.", "scene.", "button."))
                  and (e.startswith(("sensor.", "weather.")) or etat.split()[0] not in repos)]
        return liste, (", ".join(actifs) + ". Tout le reste est éteint, à l'arrêt ou au repos.")

    def etat(self, entity_id):
        r = self.client.get(f"{self.url}/api/states/{entity_id}")
        if r.status_code == 404:
            return {"erreur": f"entité inconnue : {entity_id}"}
        r.raise_for_status()
        e = r.json()
        return {"etat": e["state"], **attributs_lus(e["attributes"])}

    def etat_brut(self, entity_id):
        """Objet d'état de HA tel quel ({"state", "attributes"}), ou None si l'état n'a pas pu être lu.
        Sert à résoudre les actions dynamiques du dictionnaire (commandes_dynamiques.py), jamais au LLM."""
        try:
            r = self.client.get(f"{self.url}/api/states/{entity_id}")
            if r.status_code != 200:
                return None
            e = r.json()
            return e if isinstance(e, dict) else None
        except Exception:
            return None

    def service(self, domaine, service, entity_id=None, donnees=None, confirmer=True):
        """Service demandé par le LLM ou rejoué par une routine (confirmer=False : pas d'attente
        de l'état, la routine enchaîne ses étapes)."""
        corps = dict(donnees or {})
        if entity_id:
            corps["entity_id"] = entity_id
        # Point de contrôle unique (acces.controler_service), avec la liste blanche du LLM.
        refus = acces.controler_service(domaine, service, corps, personne=self.personne,
                                        services_permis=self.services_permis(domaine))
        if refus and refus.genre == "domaine":
            return {"erreur": f"refusé : domaine {domaine} interdit. Ne réessaie pas autrement, dis-le simplement."}
        if refus and refus.genre == "service":
            permis = ", ".join(sorted(self.services_permis(domaine))) or "aucun"
            return {"erreur": f"{refus}. Services permis pour {domaine} : {permis}. "
                              "Luminosité : light.turn_on avec donnees {\"brightness_pct\": N}."}
        if refus:  # schéma des données, launch_app, sécurité en dur (occupant protégé, son la nuit), même en essai
            return {"erreur": f"refusé : {refus}. Ne réessaie pas autrement, dis-le simplement."}
        # Les cibles du corps envoyé à HA, pas seulement l'argument : un entity_id glissé dans les données compte aussi.
        inconnues = [e for e in securite.cibles(corps.get("entity_id")) if self.entites_llm and e not in self.entites_llm]
        if inconnues:
            return {"erreur": f"entité absente de la liste des appareils : {', '.join(inconnues)}. "
                              "Choisis un entity_id exact de la liste."}
        if self.essai:
            # Mode essai : on répond comme si c'était fait. Le mot « essai » dans la réponse
            # poussait Claude à commenter le mode essai au lieu de confirmer l'action.
            return {"ok": True}
        r = self.client.post(f"{self.url}/api/services/{domaine}/{service}", json=corps)
        if r.status_code >= 400:
            return {"erreur": f"HTTP {r.status_code} : {r.text[:200]}"}
        if not confirmer:
            return {"ok": True}
        muets = self.confirmer(f"{domaine}.{service}", corps, delai=3.0)
        if muets:  # HA a accepté l'ordre mais l'appareil n'a pas changé d'état
            return {"ok": True, "confirme": False,
                    "attention": f"ordre accepté mais état inchangé : {', '.join(muets)}. "
                                 "Dis que l'ordre est parti sans que l'appareil ne réponde."}
        if self.manquantes:
            return {"ok": True, "note": phrase_manquantes(self.manquantes) + " Dis-le en une courte phrase."}
        return {"ok": True}

    # Musique : section appareils.musique de la configuration de la maison (maison.json).
    # Lecteurs Music Assistant des enceintes, par nom d'enceinte (« toutes » pour le groupe), masqués dans
    # la vue du LLM et choisis ici.
    ENCEINTES_MUSIQUE = dict(MUSIQUE_MAISON.get("enceintes") or {})
    # Entités de l'intégration Enceintes de HA derrière chaque lecteur de MA : elles seules disent si les
    # enceintes jouent. Le 22/10/2026, le groupe de MA affichait « playing » et un titre de Michael
    # Jackson pendant que chaque morceau échouait (« Timeout waiting for audio data »).
    enceintes_NATIFS = {lecteur: tuple(natifs) for lecteur, natifs in (MUSIQUE_MAISON.get("natifs") or {}).items()}
    # Le greffon Spotify Connect de MA annonce le groupe à Spotify sous le nom SPOTIFY_APPAREIL, et le
    # groupe prend la source SOURCE_CONNECT tant qu'une session Connect l'occupe.
    SPOTIFY = MUSIQUE_MAISON.get("spotify", "")
    SPOTIFY_APPAREIL = MUSIQUE_MAISON.get("spotify_appareil", "")
    SOURCE_CONNECT = MUSIQUE_MAISON.get("source_connect", "")
    # Appareil Spotify du moteur Soloist de MA quand MA lit lui-même un titre Spotify.
    SPOTIFY_LECTURE_MA = "Music Assistant Playback"
    # Enceintes du groupe restées muettes au dernier lancement de musique confirmé, (nom, hors ligne).
    manquantes = []
    SCRIPTS_MUSIQUE = set(MUSIQUE_MAISON.get("scripts") or [])
    # Échéance d'une commande de musique, recherche comprise (la tablette attend 45 s le LLM).
    DELAI_MUSIQUE = 36.0
    # Freinage de Spotify (« Spotify Rate Limiter », 5 à 15 s de pénalité) : une pause, puis un seul
    # nouvel essai. Recherches réussies gardées 10 min (MA ne refait alors aucun appel à Spotify).
    PAUSE_FREINAGE = 6.0
    DUREE_CACHE_RECHERCHE = 600.0

    def lire(self, entity_id):
        """État brut d'une entité (state, attributes), ou None si elle manque ou ne répond pas."""
        try:
            r = self.client.get(f"{self.url}/api/states/{entity_id}", timeout=5)
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    def chercher_musique(self, recherche, type_media, artiste="", fin=None):
        """Recherche avec cache et patience (demande du 23/10/2026) : Spotify freine la clé de MA dès
        4 ou 5 recherches rapprochées et rend alors une liste vide après 8 s. Une recherche lente, ou
        vide alors que d'autres viennent d'être faites, est refaite une fois après PAUSE_FREINAGE
        secondes (MA a souvent fini en fond entre-temps) : le résultat porte alors patience=True.
        Lève RechercheLente si le second essai échoue aussi, ou s'il ne tient pas avant fin."""
        cle = (normaliser(recherche), type_media, normaliser(artiste))
        cache = self.__dict__.setdefault("cache_recherche", {})
        maintenant = time.time()
        for c in [c for c, (t, _) in cache.items() if maintenant - t > self.DUREE_CACHE_RECHERCHE]:
            del cache[c]
        if cle in cache:
            return dict(cache[cle][1])
        recentes = [t for t in self.__dict__.setdefault("recherches_recentes", []) if maintenant - t < 30]
        self.recherches_recentes = recentes + [maintenant]
        try:
            trouve = self.chercher_musique_ma(recherche, type_media, artiste)
            if trouve is None and len(recentes) < 3:
                return None  # vide et rapide sans rafale : vraiment rien trouvé
        except RechercheLente:
            pass
        else:
            if trouve is not None:
                cache[cle] = (time.time(), trouve)
                return dict(trouve)
        # Pause, puis second essai, s'il tient avant l'échéance (une recherche dure jusqu'à 13 s : forme
        # rapide puis seconde forme en délai dépassé).
        if fin is not None and time.time() + self.PAUSE_FREINAGE + 13 > fin:
            raise RechercheLente()
        time.sleep(self.PAUSE_FREINAGE)
        self.recherches_recentes.append(time.time())
        trouve = self.chercher_musique_ma(recherche, type_media, artiste)
        if trouve is None:
            return None
        cache[cle] = (time.time(), trouve)
        return dict(trouve, patience=True)

    def chercher_musique_ma(self, recherche, type_media, artiste=""):
        """Meilleur résultat de Music Assistant {nom, uri, titre, artistes, type}, ou None. La recherche
        tolère les fautes de transcription (« Artiste Fictif » donne Artiste Fictif) et répond en 0 à 8 s, alors qu'un
        play_media sur un nom mal reconnu échoue ou dépasse le délai de la tablette (vu le 21/10/2026).
        Un résultat Spotify passe devant un élément de la bibliothèque de MA (« library://... »), que
        seule la lecture par MA saurait jouer.

        Lève RechercheLente quand MA rend une liste vide après 7 s ou ne répond pas : Spotify ne lui a
        pas répondu à temps (« Spotify Rate Limiter », 22/10/2026), ce qui n'est pas « rien trouvé ». MA
        continue alors la recherche en fond et la garde en cache : la même demande une minute plus tard
        aboutit."""
        import httpx
        if not getattr(self, "entree_mass", None):
            r = self.client.post(f"{self.url}/api/template",
                                 json={"template": "{{ config_entry_id('" + self.ENCEINTES_MUSIQUE["toutes"] + "') }}"}, timeout=5)
            self.entree_mass = r.text.strip()
        essais = [(recherche, artiste)] if artiste else [(recherche, "")]
        if type_media == "track" and not artiste and len(recherche.split()) > 2:
            essais.append((" ".join(recherche.split()[:-1]), recherche.split()[-1]))  # « titre artiste » dit d'un trait
        debut = time.time()
        for nom, art in essais:
            if time.time() - debut > 3:  # première forme déjà lente : la seconde attendrait autant
                break
            corps = {"config_entry_id": self.entree_mass, "name": nom, "media_type": [type_media], "limit": 3}
            if art:
                corps["artist"] = art
            try:
                r = self.client.post(f"{self.url}/api/services/music_assistant/search?return_response", json=corps, timeout=10)
            except httpx.TimeoutException:
                raise RechercheLente()
            if r.status_code >= 400:
                continue
            trouves = (r.json().get("service_response") or {}).get(type_media + "s") or []
            if trouves:
                t = next((x for x in trouves if uri_spotify(x.get("uri"))), trouves[0])
                artistes = [a.get("name", "") for a in t.get("artists") or []]
                return {"nom": t.get("name", nom) + (f" de {', '.join(artistes)}" if artistes else ""),
                        "uri": t.get("uri"), "titre": t.get("name", nom), "artistes": artistes, "type": type_media}
        if time.time() - debut >= 7:
            raise RechercheLente()
        return None

    def musique(self, recherche, type_media="track", enceinte="toutes", artiste=""):
        """Morceau, artiste, album ou playlist demandé à la voix (« mets Titre Fictif de Artiste Fictif »,
        21/10/2026) : Music Assistant cherche sur Spotify, puis on joue le meilleur résultat et on vérifie
        sur les enceintes qu'il passe vraiment. Sécurité en dur vérifiée. Une ligne de journal par
        commande (journal/musique.jsonl et sortie du serveur), même quand HA ne répond pas.

        Tout tient en DELAI_MUSIQUE secondes, recherche comprise : la tablette attend 45 s la réponse du
        LLM, dont un tour d'appel de l'outil et un tour de réponse (la boucle d'outils en permet six au plus)."""
        t0 = time.time()
        trace = {}
        try:
            res = self._musique(str(recherche or "").strip(), type_media, enceinte, str(artiste or "").strip(),
                                trace, t0 + self.DELAI_MUSIQUE)
        except Exception as e:  # HA qui redémarre, délai dépassé : l'ordre a pu partir quand même
            res = {"ok": False, "confirme": False, "attention": f"Home Assistant n'a pas répondu ({e.__class__.__name__}). "
                   "Dis que tu ne sais pas si la musique est partie, sans dire que c'est lancé."}
        journaliser_musique({"demande": str(recherche or "").strip(), "artiste": str(artiste or "").strip(),
                             "type": type_media, "enceinte": enceinte or "toutes", **trace,
                             "resultat": ("confirmé" if res.get("confirme") else "essai" if self.essai and "erreur" not in res
                                          else res.get("erreur") or res.get("attention") or "?"),
                             "duree_s": round(time.time() - t0, 1), "essai": self.essai})
        return res

    def _musique(self, recherche, type_media, enceinte, artiste, trace, fin):
        if not recherche:
            return {"erreur": "recherche vide"}
        if not self.ENCEINTES_MUSIQUE.get("toutes"):
            return {"erreur": "aucune enceinte de musique configurée (appareils.musique.enceintes de maison.json)"}
        type_media = type_media if type_media in ("track", "artist", "album", "playlist") else "track"
        cible = self.ENCEINTES_MUSIQUE.get(enceinte or "toutes") or self.ENCEINTES_MUSIQUE["toutes"]
        refus = acces.controler_service("music_assistant", "play_media", {"entity_id": cible}, personne=self.personne)
        if refus:
            return {"erreur": f"refusé : {refus}. Ne réessaie pas autrement, dis-le simplement."}
        try:
            trouve = self.chercher_musique(recherche, type_media, artiste, fin)
        except RechercheLente:
            return {"erreur": "Spotify fait patienter Music Assistant en ce moment, même après un second essai. "
                              "Dis-le simplement et propose de redemander dans une minute."}
        except Exception as e:
            return {"erreur": f"recherche impossible ({e.__class__.__name__}). Dis-le simplement."}
        if not trouve:
            return {"erreur": f"rien trouvé pour « {recherche} ». Demande de répéter le titre ou l'artiste."}
        trace.update(trouve=trouve["nom"], uri=trouve["uri"])
        if self.essai:
            return {"ok": True, "lance": trouve["nom"]}
        if cible == self.ENCEINTES_MUSIQUE["toutes"] and uri_spotify(trouve["uri"]):
            res = self.jouer_par_spotify(trouve, trace, fin)
            if res is not None:
                return res
        return self.jouer_par_mass(cible, trouve, trace, fin)

    def jouer_par_spotify(self, trouve, trace, fin):
        """Joue sur le groupe des Enceintes par l'intégration Spotify de HA (compte et clé d'API du propriétaire),
        vers l'appareil Spotify Connect que le greffon de MA donne au groupe. None si l'appareil manque,
        avant tout ordre : une fois la prise de la main envoyée, plus de repli par MA, qui se battrait
        avec la session Connect pour le compte.

        Pourquoi pas music_assistant.play_media (22/10/2026, « Lance Artiste Fictif sur Spotify » resté
        muet) : Spotify freine le fournisseur Spotify de MA dès quelques requêtes rapprochées
        (« Spotify Rate Limiter », 5 à 15 s de pénalité, avec la clé du propriétaire), un artiste lui fait charger tous ses titres (plus de 3 min
        ce soir-là, groupe verrouillé), et il lit par Spotify Soloist sur le même compte que la session
        Connect : un seul flux à la fois, la session tombe et les titres échouent. Ici, Spotify lit
        lui-même le titre ou l'artiste (context_uri) : play_media rendu en 1,3 s, Billie Jean confirmé
        sur les Enceintes en 1,5 s."""
        groupe_id = self.ENCEINTES_MUSIQUE["toutes"]
        sp = self.lire(self.SPOTIFY)
        if not sp or self.SPOTIFY_APPAREIL not in (sp["attributes"].get("source_list") or []):
            return None
        trace.update(voie="spotify connect", lecteur=self.SPOTIFY)
        en_connect = lambda: ((self.lire(groupe_id) or {}).get("attributes") or {}).get("source") == self.SOURCE_CONNECT
        if not en_connect() or sp["attributes"].get("source") != self.SPOTIFY_APPAREIL:
            # Prise de la main : le compte bascule sur les Enceintes (téléphone, PC ou lecture par MA), le
            # groupe passe en Spotify Connect en 1,5 s environ.
            r = self.client.post(f"{self.url}/api/services/media_player/select_source", timeout=10,
                                 json={"entity_id": self.SPOTIFY, "source": self.SPOTIFY_APPAREIL})
            if r.status_code >= 400 or not self.attendre(en_connect, min(8.0, fin - time.time())):
                return {"ok": False, "confirme": False, "attention": "les Enceintes ne sont pas passés sur Spotify. "
                        "Dis que ça n'a pas marché et propose de redemander, sans dire que c'est lancé."}
        # Sans lecture en cours sur le compte, l'entité Spotify de HA refuse play_media (fonction 512
        # absente) : elle ne le saura qu'à sa prochaine mise à jour.
        if not self.attendre(lambda: (self.lire(self.SPOTIFY) or {}).get("attributes", {}).get("supported_features", 0) & 512,
                             min(12.0, fin - time.time()), relancer=self.SPOTIFY):
            return {"ok": False, "confirme": False, "attention": "les Enceintes sont passés sur Spotify mais Spotify "
                    "n'accepte pas encore la demande. Dis que ça n'a pas marché et propose de redemander."}
        # Titre d'avant lu après la prise de la main, qui reprend d'abord la dernière écoute du compte.
        avant = ((self.lire(groupe_id) or {}).get("attributes") or {}).get("media_title")
        attendu = dict(trouve, avant=avant)
        try:
            r = self.client.post(f"{self.url}/api/services/media_player/play_media", timeout=10, json={
                "entity_id": self.SPOTIFY, "media_content_id": uri_spotify(trouve["uri"]), "media_content_type": trouve["type"]})
            if r.status_code >= 400:
                return {"erreur": f"Spotify n'a pas accepté (HTTP {r.status_code} : {r.text[:150]}). Dis que ça n'a pas marché."}
        except Exception:  # l'ordre a pu passer : l'état tranche
            pass
        # Jusqu'à l'échéance : après une pause de quelques minutes, MA dissout le groupe et met 12 s à le
        # reformer avant le premier son (essai du 22/10/2026 à 21 h 05).
        if self.attendre(lambda: self.lecture_connect(attendu), max(1.0, fin - time.time())):
            return self.signaler(dict({"ok": True, "confirme": True, "lance": trouve["nom"], "enceinte": groupe_id},
                                      **patience(trouve)), trace, fin)
        return {"ok": False, "confirme": False, "attention": f"les Enceintes ne jouent pas encore {trouve['nom']}. "
                "Dis que la demande est partie sans dire que c'est lancé."}

    def lecture_connect(self, attendu):
        """Le groupe joue-t-il en Spotify Connect ce qui était demandé ? Lecture réelle sur au moins une
        enceinte Enceintes, titre lu sur le groupe de MA, qui suit ce que les Enceintes reçoivent. L'entité
        Spotify, rafraîchie 1 s après l'ordre, annonce le nouveau titre avant que les Enceintes ne
        basculent : elle ne sert que si le groupe ne donne aucun titre."""
        groupe = self.lire(self.ENCEINTES_MUSIQUE["toutes"]) or {}
        ga = groupe.get("attributes") or {}
        if groupe.get("state") != "playing" or ga.get("source") != self.SOURCE_CONNECT:
            return False
        if not self.enceintes_joue(self.enceintes_NATIFS.get(self.ENCEINTES_MUSIQUE.get("toutes"), ())):
            return False
        if ga.get("media_title"):
            return correspond(ga, attendu)
        sa = (self.lire(self.SPOTIFY) or {}).get("attributes") or {}
        return sa.get("source") == self.SPOTIFY_APPAREIL and correspond(sa, attendu)

    def jouer_par_mass(self, cible, trouve, trace, fin):
        """Lecture par Music Assistant : une seule enceinte, ou repli quand l'appareil Spotify Connect
        manque. Lente quand Spotify bride MA (un artiste a mis plus de 3 min le 22/10/2026) : on ne dit
        « lancé » que si l'enceinte Enceintes joue le titre avant l'échéance."""
        trace.setdefault("voie", "music assistant")
        trace["lecteur"] = cible
        natifs = self.enceintes_NATIFS.get(cible, ())
        sp = self.lire(self.SPOTIFY)
        if sp and sp.get("state") == "playing" and sp["attributes"].get("source") != self.SPOTIFY_LECTURE_MA:
            # Un compte Spotify ne lit qu'un flux : MA (Soloist) échoue tant que le téléphone ou la session
            # Connect du groupe joue (« Timeout waiting for audio data », 22/10/2026). Les enceintes doivent
            # aussi quitter la lecture, sinon l'ancien morceau confirmerait la demande.
            self.client.post(f"{self.url}/api/services/media_player/media_pause", json={"entity_id": self.SPOTIFY}, timeout=10)
            self.attendre(lambda: not self.enceintes_joue(natifs), min(3.0, fin - time.time()))
        attendu = dict(trouve, avant=((self.lire(natifs[0]) or {}).get("attributes") or {}).get("media_title") if natifs else None)
        corps = {"entity_id": cible, "media_id": trouve["uri"], "media_type": trouve["type"], "enqueue": "replace"}
        try:
            r = self.client.post(f"{self.url}/api/services/music_assistant/play_media", json=corps,
                                 timeout=max(1.0, fin - time.time()))
            if r.status_code >= 400:
                return {"erreur": f"HTTP {r.status_code} : {r.text[:200]}"}
        except Exception:  # MA répond tard quand Spotify le bride, la lecture peut partir ensuite
            pass
        if self.attendre(lambda: self.enceintes_joue(natifs, attendu), max(1.0, fin - time.time())):
            res = dict({"ok": True, "confirme": True, "lance": trouve["nom"], "enceinte": cible}, **patience(trouve))
            return self.signaler(res, trace, fin) if cible == self.ENCEINTES_MUSIQUE["toutes"] else res
        return {"ok": False, "confirme": False, "attention": f"Music Assistant n'a pas encore démarré {trouve['nom']} "
                "(Spotify le freine en ce moment). Dis que la demande est partie et que la musique peut mettre "
                "une minute à venir, sans dire que c'est lancé."}

    def attendre(self, condition, delai, relancer=None):
        """Vrai dès que condition() l'est, faux après delai secondes. relancer : entité dont HA doit
        relire l'état quand la condition n'est pas encore remplie, au plus toutes les 10,5 s (HA ignore
        une relecture demandée moins de 10 s après la précédente), pour une intégration qui interroge
        son service toutes les 30 s."""
        fin, relance = time.time() + delai, None
        while True:
            with contextlib.suppress(Exception):
                if condition():
                    return True
            if time.time() >= fin:
                return False
            if relancer and (relance is None or time.time() - relance >= 10.5):
                relance = time.time()
                with contextlib.suppress(Exception):
                    self.client.post(f"{self.url}/api/services/homeassistant/update_entity",
                                     json={"entity_id": relancer}, timeout=5)
            time.sleep(0.4)

    def enceintes_joue(self, natifs, attendu=None):
        """Une des enceintes Enceintes natifs joue, et joue ce qui était attendu s'il est donné."""
        for n in natifs:
            e = self.lire(n) or {}
            if e.get("state") == "playing" and (attendu is None or correspond(e.get("attributes") or {}, attendu)):
                return True
        return False

    def absentes(self, delai=8.0):
        """Enceintes du groupe « toutes » qui ne jouent pas, après un lancement confirmé sur le groupe :
        [(nom, hors ligne)]. Le 25/10/2026, la cuisine débranchée, la musique partait sur le seul salon
        sans rien dire (un seul Enceintes suffit à confirmer). Une enceinte hors ligne est signalée tout de
        suite. Une enceinte en ligne a jusqu'à delai secondes pour se mettre à jouer : MA met jusqu'à 12 s
        à reformer le groupe après une pause."""
        groupe = set(self.enceintes_NATIFS.get(self.ENCEINTES_MUSIQUE.get("toutes"), ()))
        par_natifs = {}  # un synonyme dans maison.json ne fait pas citer deux fois la même enceinte
        for nom, lecteur in self.ENCEINTES_MUSIQUE.items():
            natifs = tuple(self.enceintes_NATIFS.get(lecteur) or ())
            if nom != "toutes" and natifs and set(natifs) <= groupe:
                par_natifs.setdefault(natifs, nom)
        dernier = []

        def releve():
            dernier.clear()
            for natifs, nom in par_natifs.items():
                etats = [(self.lire(n) or {}).get("state") for n in natifs]
                if "playing" not in etats:
                    dernier.append((nom, all(e in ("unavailable", "unknown") for e in etats)))
            return not any(not hors_ligne for _, hors_ligne in dernier)

        self.attendre(releve, max(0.5, delai))
        return list(dernier)

    def signaler(self, res, trace, fin):
        """Ajoute au résultat confirmé d'un lancement sur le groupe les enceintes qui ne jouent pas, sans
        dépasser l'échéance de la commande."""
        manquantes = self.absentes(min(8.0, fin - time.time()))
        if manquantes:
            trace["muettes"] = ", ".join(nom for nom, _ in manquantes)
            res["remarque"] = (phrase_manquantes(manquantes) + " Dis-le en une courte phrase après avoir "
                               "annoncé ce qui est lancé.")
        return res

    def musique_en_cours(self, delai):
        """Vrai si une enceinte Enceintes joue (ou se met à jouer dans le délai) : sert aux scripts de
        musique du dictionnaire et du LLM, qui rendent la main avant que le son parte. Jugé sur les
        enceintes, le groupe de MA pouvant afficher « playing » sans son."""
        return self.attendre(lambda: self.enceintes_joue(self.enceintes_NATIFS.get(self.ENCEINTES_MUSIQUE.get("toutes"), ())), delai)

    def confirmer(self, service, corps, delai=1.5):
        """Entités qui n'ont pas pris l'état attendu après l'ordre (« accepté » contre « confirmé »,
        idée d'un projet d'inspiration). Seulement la marche et l'arrêt des lumières, prises et ventilateurs : une
        télé met plusieurs secondes à s'allumer, un volume ou une couleur ne se vérifie pas simplement.
        Plus les scripts qui lancent la musique : le groupe des Enceintes doit jouer dans les 12 s (le
        transfert vers les Enceintes relance jusqu'à trois fois)."""
        domaine, _, action = service.partition(".")
        scripts = [e for e in securite.cibles(corps.get("entity_id")) if e in self.SCRIPTS_MUSIQUE]
        self.manquantes = []
        if (domaine == "script" and action == "turn_on" and scripts) or service in self.SCRIPTS_MUSIQUE:
            if not self.ENCEINTES_MUSIQUE.get("toutes"):
                return []  # sans enceinte « toutes » dans maison.json, aucun groupe à écouter (0.27.3)
            t0 = time.time()
            joue = self.musique_en_cours(max(delai, 12.0))
            # Seul le script de lancement vise tout le groupe (un transfert peut viser une seule enceinte).
            lancer = MUSIQUE_MAISON.get("script_lancer")
            self.manquantes = self.absentes() if joue and lancer and (lancer in scripts or service == lancer) else []
            journaliser_musique({"demande": ", ".join(scripts) or service, "type": "script", "enceinte": "toutes",
                                 "voie": "script", "lecteur": self.ENCEINTES_MUSIQUE["toutes"],
                                 "resultat": "confirmé" if joue else "les Enceintes ne jouent pas",
                                 **({"muettes": ", ".join(n for n, _ in self.manquantes)} if self.manquantes else {}),
                                 "duree_s": round(time.time() - t0, 1), "essai": self.essai})
            return [] if joue else [self.ENCEINTES_MUSIQUE["toutes"]]
        attendu = {"turn_on": "on", "turn_off": "off"}.get(action)
        entites = [e for e in securite.cibles(corps.get("entity_id"))
                   if e.split(".")[0] in ("light", "switch", "fan", "input_boolean")]
        if not attendu or domaine not in ("light", "switch", "fan", "input_boolean", "homeassistant") or not entites:
            return []
        fin = time.time() + delai
        restantes = set(entites)
        while restantes and time.time() < fin:
            time.sleep(0.15)
            for e in list(restantes):
                try:
                    if self.client.get(f"{self.url}/api/states/{e}", timeout=3).json().get("state") == attendu:
                        restantes.discard(e)
                except Exception:
                    pass
        return sorted(restantes)


def uri_spotify(uri):
    """« spotify--D7ai9Jsy://artist/3fMb... » de Music Assistant donne « spotify:artist:3fMb... », ce
    que l'intégration Spotify de HA sait jouer. None pour un élément qui ne vient pas de Spotify."""
    m = re.fullmatch(r"spotify[^:/]*://(track|artist|album|playlist)/([A-Za-z0-9]+)", str(uri or ""))
    return f"spotify:{m.group(1)}:{m.group(2)}" if m else None


def phrase_manquantes(manquantes):
    """« La musique est lancée, mais l'enceinte cuisine est hors ligne. » pour [("cuisine", True)]."""
    def une(nom, hors_ligne):
        return f"l'enceinte {nom} " + ("est hors ligne" if hors_ligne else "ne joue pas")
    return "La musique est lancée, mais " + " et ".join(une(n, h) for n, h in manquantes) + "."


def patience(trouve):
    """Champ ajouté au résultat de jouer_musique quand la recherche a dû attendre Spotify."""
    return {"note": "Spotify m'a fait patienter quelques secondes. Dis-le en une courte phrase avant "
                    "d'annoncer ce qui est lancé."} if trouve.get("patience") else {}


def normaliser(texte):
    """Minuscules, sans accents ni ponctuation : « Billie Jean - 2003 Remaster » donne
    « billie jean 2003 remaster ». Les lettres non latines restent (« 宇多田ヒカル »)."""
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFKD", str(texte or "")) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[\W_]+", " ", t.casefold()).split())


def titre_nu(texte):
    """Titre sans ce que Spotify y accroche : « Billie Jean - Single Version », « Beat It (Remastered) »
    donnent « billie jean », « beat it ». Une parenthèse en tête fait partie du titre."""
    return normaliser(re.split(r"\s+-\s+|(?<=\S)\s*[(\[]", str(texte or ""), maxsplit=1)[0])


def meme_titre(lu, voulu):
    return bool(titre_nu(voulu)) and titre_nu(lu) == titre_nu(voulu)


def correspond(attrs, attendu):
    """Le lecteur (ses attributs HA) joue-t-il ce qui était demandé ? Un morceau par son titre, au
    suffixe de Spotify près, un artiste parmi ceux du morceau, un album par son nom. Une playlist ne se
    reconnaît pas au morceau : par son nom si le lecteur le donne, sinon par un titre qui a changé
    depuis la demande (champ avant)."""
    voulu = normaliser(attendu.get("titre"))
    if not voulu:
        return False
    if attendu.get("type") == "artist":
        return f" {voulu} " in f" {normaliser(attrs.get('media_artist'))} "
    if attendu.get("type") == "album":
        return meme_titre(attrs.get("media_album_name"), attendu["titre"])
    if attendu.get("type") == "playlist":
        titre = normaliser(attrs.get("media_title"))
        return (normaliser(attrs.get("media_playlist")) == voulu
                or (attendu.get("avant") is not None and bool(titre) and titre != normaliser(attendu["avant"])))
    return meme_titre(attrs.get("media_title"), attendu["titre"])


# ---------------------------------------------------------------- LLM
OUTILS = [
    {"type": "function", "function": {
        "name": "appeler_service",
        "description": "Agit sur un appareil de la maison via un service Home Assistant.",
        "parameters": {"type": "object", "properties": {
            "domaine": {"type": "string", "enum": sorted(DOMAINES_OUTIL_LLM)},
            "service": {"type": "string", "description": "ex. turn_on, turn_off, volume_set, start. "
                        "La luminosité se règle avec light.turn_on, il n'existe pas de brightness_set."},
            "entity_id": {"type": ["string", "array"], "items": {"type": "string"},
                          "description": "entity_id exact tiré de la liste, ou liste d'entity_id"},
            "donnees": {"type": "object", "description": "paramètres facultatifs, ex. {\"brightness_pct\": 30}"}},
            "required": ["domaine", "service"]}}},
    {"type": "function", "function": {
        "name": "jouer_musique",
        "description": "Cherche et joue un morceau, un artiste, un album ou une playlist précis sur les enceintes "
                       "Enceintes (Spotify, recherche par Music Assistant). Pour « mets de la musique » sans rien de précis, "
                       f"utilise plutôt {SCRIPT_LANCER}.",
        "parameters": {"type": "object", "properties": {
            "recherche": {"type": "string", "description": "le titre (morceau, album, playlist) ou le nom de l'artiste, "
                          "tel que dit, ex. « Titre Fictif » ou « Artiste Fictif »"},
            "artiste": {"type": "string", "description": "l'artiste d'un morceau ou d'un album, s'il est dit, ex. « Artiste Fictif »"},
            "type": {"type": "string", "enum": ["track", "artist", "album", "playlist"],
                     "description": "track pour un morceau, artist pour « mets du Artiste Fictif », album, playlist"},
            "enceinte": {"type": "string", "enum": list(MUSIQUE_MAISON.get("enceintes") or {"toutes": ""}),
                         "description": "toutes (le groupe de toutes les enceintes) sauf si une enceinte précise "
                                        "est nommée dans la demande"}},
            "required": ["recherche", "type"]}}},
    {"type": "function", "function": {
        "name": "lire_etat",
        "description": "Lit l'état détaillé d'une entité Home Assistant.",
        "parameters": {"type": "object", "properties": {
            "entity_id": {"type": "string"}}, "required": ["entity_id"]}}},
]

# Outil de création d'une routine (0.42.0), proposé au seul mode « proposer » : il ne fait rien d'autre que
# soumettre une proposition à routines.valider_proposition, qui la valide, la reformule et la garde en brouillon.
# Constante séparée de OUTILS : le mode « commande » sans entités rend toujours OUTILS lui-même.
OUTIL_PROPOSER = {"type": "function", "function": {
    "name": "proposer_routine",
    "description": "Propose une routine : une phrase que la personne dira plus tard pour lancer une suite d'actions. "
                   "Le serveur valide, reformule et demande lui-même la confirmation. Un seul appel par demande.",
    "parameters": {"type": "object", "properties": {
        "nom": {"type": "string", "description": "nom court de la routine, ex. « Bonne nuit »"},
        "phrases": {"type": "array", "items": {"type": "string"},
                    "description": "la ou les phrases dites par la personne, telles qu'elle les a dites"},
        "variantes": {"type": "array", "items": {"type": "string"},
                      "description": "formulations proches qui lancent la même routine (cinq au plus)"},
        "reponse": {"type": "string", "description": "phrase dite après le lancement, facultative"},
        "remplace": {"type": "string", "description": "id d'une routine existante à remplacer, facultatif"},
        "etapes": {"type": "array", "description": "étapes dans l'ordre, huit au plus", "items": {
            "type": "object", "properties": {
                "etape": {"type": "string", "enum": ["service", "musique", "annonce", "question", "pause"]},
                "domaine": {"type": "string"}, "service": {"type": "string"},
                "entity_id": {"type": ["string", "array"], "items": {"type": "string"},
                              "description": "entity_id exacts de la liste, un par appareil, jamais une pièce"},
                "donnees": {"type": "object"},
                "recherche": {"type": "string"}, "artiste": {"type": "string"},
                "type": {"type": "string", "enum": list(routines.TYPES_MUSIQUE)},
                "enceinte": {"type": "string"},
                "texte": {"type": "string", "description": "texte d'une annonce ou d'une question"},
                "secondes": {"type": "number"}},
            "required": ["etape"]}}},
        "required": ["phrases", "etapes"]}}}

# Outils proposés au LLM selon le mode du tour (0.28.0). Un appel à un outil absent de la liste du tour
# n'est jamais exécuté : il reçoit « outil indisponible » (aiguillage fermé, Cerveau.executer_outil, voir la section 3.1
# de docs/plan/conception/routines.md).
# « proposer » (0.42.0) crée une routine, « question » (0.42.0) répond à une étape question d'une routine : ces
# deux modes partent sans historique et n'en laissent aucun (MODES_ISOLES).
MODES_OUTILS = {"commande": ("appeler_service", "jouer_musique", "lire_etat"),
                "proposer": ("proposer_routine", "lire_etat"),
                "question": ("lire_etat",)}
MODES_ISOLES = ("proposer", "question")
INDISPONIBLE = {"erreur": "outil indisponible"}
# Parole écrite par le serveur pendant ce tour (reformulation d'une routine) : elle remplace la réponse du LLM.
PAROLE_FIXEE = contextvars.ContextVar("parole_fixee", default=None)
# Au plus six allers-retours avec le LLM par demande (appel d'outil, résultat, nouvel appel), puis une phrase de repli.
TOURS_OUTILS_MAX = 6
PHRASE_ABANDON = "Je n'ai pas réussi à terminer cette demande."
PHRASE_REFUS_LLM = "Je ne peux pas traiter cette demande."


class TourLLM(NamedTuple):
    """Un tour du LLM vu par la boucle d'outils, quel que soit le format de l'API.

    reponse : texte nettoyé, renseigné seulement quand le LLM ne demande aucun outil. appels : les appels d'outils
    tels que l'API les renvoie, que seul l'adaptateur du format sait lire. refus : le modèle a refusé de répondre.
    brut : ce dont l'adaptateur a besoin pour rejouer ce tour dans les messages."""
    reponse: str = ""
    appels: tuple = ()
    refus: bool = False
    brut: object = None


CONSIGNES_MODE = {
    "proposer": (
        "\nMODE CRÉATION DE ROUTINE. La personne veut créer ou changer une routine : une phrase qu'elle dira plus tard "
        "pour lancer une suite d'actions. N'agis pas sur la maison toi-même. Appelle une seule fois l'outil "
        "proposer_routine. Les phrases sont celles qu'elle vient de dire, mot pour mot, sans le mot de réveil. "
        "Chaque étape nomme ses appareils un par un avec des entity_id exacts de la liste, jamais une pièce, un groupe ni "
        "« tout ». Étapes possibles : service (domaine, service, entity_id, donnees), musique (recherche, type, enceinte), "
        "annonce (texte), question (texte), pause (secondes). Ne dis jamais que la routine est enregistrée : le serveur "
        "la reformule et demande lui-même la confirmation. Si la demande est trop floue, pose une seule question courte."),
    "question": (
        "\nTu réponds à une question posée par une routine : une ou deux phrases courtes. Tu peux lire l'état d'un "
        "appareil, rien de plus, tu n'agis sur rien."),
}


def nom_outil(o):
    return o["function"]["name"]


def outils_avec_entites(entites, mode="commande"):
    """Outils du LLM pour ce mode, avec les entités permises en enum dans le schéma de appeler_service
    et lire_etat (outils retrouvés par leur nom).

    Pas de « strict » : l'objet libre « donnees » ne le permet pas (strict exige
    additionalProperties false partout). Le code refuse de toute façon une entité hors liste."""
    noms = MODES_OUTILS[mode]
    if not entites and mode == "commande":
        return OUTILS
    import copy
    outils = copy.deepcopy([o for o in OUTILS + [OUTIL_PROPOSER] if nom_outil(o) in noms])
    if not entites:
        return outils
    ids = sorted(entites)
    par_nom = {nom_outil(o): o for o in outils}
    if "appeler_service" in par_nom:
        props = par_nom["appeler_service"]["function"]["parameters"]["properties"]
        props["entity_id"] = {"anyOf": [{"type": "string", "enum": ids},
                                        {"type": "array", "items": {"type": "string", "enum": ids}}],
                              "description": props["entity_id"]["description"]}
    if "lire_etat" in par_nom:
        par_nom["lire_etat"]["function"]["parameters"]["properties"]["entity_id"] = {"type": "string", "enum": ids}
    return outils


CONSIGNE = """Tu es l'assistant vocal de @LIEU@. Tu réponds en français parlé,
en une ou deux phrases courtes, sans liste, sans markdown, sans emoji, car ta réponse est lue à voix haute.
Pour agir sur la maison, appelle l'outil appeler_service avec un entity_id exact de la liste ci-dessous,
ou une liste d'entity_id pour plusieurs appareils d'un coup. Agis d'abord, confirme ensuite en une phrase.
N'annonce jamais une action que tu n'as pas faite avec l'outil, et ne demande pas la permission.
Luminosité : domaine light, service turn_on, donnees {{"brightness_pct": N}} de 1 à 100.
Couleur : light.turn_on avec donnees {{"color_name": "red"}} (nom de couleur CSS en anglais : red, blue, green,
orange, purple, pink, yellow, white...), cumulable avec brightness_pct. Blanc chaud ou froid : {{"color_temp_kelvin": 2700}}
à 6500. La Lampe TV accepte les couleurs, les autres ampoules surtout le blanc réglable.
« À fond » ou « au maximum » = 100, « tamisé » ou « doucement » = 20, « à moitié » = 50.
Volume : media_player.volume_set avec donnees {{"volume_level": 0.3}} pour 30 %.@PLAFOND@
Un morceau, un artiste, un album ou une playlist précis (« mets Titre Fictif de Artiste Fictif », « mets du Artiste Fictif ») : outil
jouer_musique, avec le titre et l'artiste tels que dits. Annonce ensuite simplement ce qu'il a lancé (champ lance), sans commenter la recherche.
Sans champ lance dans le résultat de jouer_musique, ne dis jamais que c'est lancé : dis ce qu'indique le champ attention ou erreur. « Mets de la musique » sans précision : @SCRIPT_LANCER@.
Entrée HDMI, chaîne ou appli de la télé : media_player.select_source avec donnees {{"source": "HDMI3"}},
le nom exact de la source étant donné entre crochets sur la ligne de la télé.
Un appareil éteint ou en veille s'allume avec le service turn_on : « éteint » ne veut jamais dire « indisponible ».
@CONSIGNES@Si l'appareil demandé n'existe pas, dis-le simplement. Pour une question générale, réponds de mémoire
et préviens si l'information peut être datée. Les états actuels des appareils sont donnés avec chaque
demande, sous « États actuels ». N'invente jamais un état : lis-le là, ou appelle lire_etat pour le détail
(titre en cours, volume). Le nom d'une pièce (salon, séjour, cuisine) désigne la lumière de cette pièce.

Appareils (entity_id | nom | pièce) :
{inventaire}"""


def _sans_accolades(texte):
    """Texte de la configuration glissé dans CONSIGNE, qui passe ensuite par str.format."""
    return str(texte).replace("{", "{{").replace("}", "}}")


def consigne_plafond():
    """Phrase de la consigne sur le plafond de volume réglé dans la configuration (securite.plafond_volume),
    pour que le LLM n'annonce pas plus fort que ce qui part. Vide sans plafond (le défaut)."""
    if not securite.plafond_actif():
        return ""
    return (f" Le volume ne dépasse jamais {securite.pourcentage(securite.VOLUME_MAX)} % "
            f"(volume_level {securite.VOLUME_MAX:g}) : une valeur plus forte y est ramenée.")


# Parties propres à la maison (section llm de maison.json) : lieu, consignes en plus (une par ligne), script de
# lancement de la musique et plafond de volume, glissés à la place des repères @...@ du texte ci-dessus.
CONSIGNE = (CONSIGNE.replace("@LIEU@", _sans_accolades(LLM_MAISON.get("lieu") or "la maison"))
            .replace("@SCRIPT_LANCER@", _sans_accolades(SCRIPT_LANCER))
            .replace("@PLAFOND@", consigne_plafond())
            .replace("@CONSIGNES@", "".join(_sans_accolades(c) + "\n" for c in LLM_MAISON.get("consignes") or [])))


class Cerveau:
    """Le LLM local (Qwen par LM Studio, format OpenAI) qui comprend la demande hors règles et appelle les outils.

    Porte aussi tout ce que CerveauClaude partage : l'historique par appareil et par personne, l'aiguillage fermé
    des outils (executer_outil) et la boucle d'appel d'outils (boucle_outils). Seuls l'appel à l'API et la forme
    des messages changent d'un cerveau à l'autre."""
    # Posés par l'Assistant (0.42.0) : validation d'une proposition de routine et liste des routines de la personne.
    rappel_routine = None
    rappel_liste = None

    def supplement_mode(self, mode):
        """Texte ajouté à la consigne pour ce mode (vide en mode commande)."""
        texte = CONSIGNES_MODE.get(mode, "")
        if mode == "proposer" and self.rappel_liste:
            try:
                texte += self.rappel_liste()
            except Exception as e:
                print(f"  routines : liste illisible ({e.__class__.__name__})")
        return texte

    def __init__(self, cfg, ha):
        import httpx
        self.cfg, self.ha = cfg, ha
        self.client = httpx.Client(timeout=60)
        # Une conversation par appareil de la session et par personne (0.28.0, resserré en 0.41.0) : « éteins-la »
        # de l'un ne vise jamais ce dont parlait l'autre, même quand deux commandes se croisent.
        self.historiques = {}  # clé -> (heure du dernier échange, messages)
        self.dernieres_actions = []  # actions réussies de la dernière réponse, au format du dictionnaire

    @staticmethod
    def cle_conversation():
        """(personne, appareil) de la requête en cours, tels que la session les a posés (Assistant.requete) :
        l'appareil est l'identité appairée du téléphone ou de la tablette, la personne vient d'acces.personne_effective.
        Jamais le texte du message. Hors requête : (None, None)."""
        r = REQUETE.get()
        return (r.personne, r.appareil) if r else (None, None)

    @staticmethod
    def cle_historique():
        """Clé de l'historique du LLM, ou None quand la requête n'a pas d'identité d'appareil (0.41.0) : sans
        identité, rien n'est gardé d'une demande à l'autre, puisqu'une clé vide serait partagée par toutes les
        demandes anonymes."""
        personne, appareil = Cerveau.cle_conversation()
        if not appareil:
            return None
        return (personne, appareil)

    @property
    def indication_personne(self):
        """Qui parle et ce que désigne « ma chambre », ajouté à la demande (Assistant.requete)."""
        r = REQUETE.get()
        return r.indication if r else ""

    @property
    def historique(self):
        cle = self.cle_historique()
        if cle is None:
            return []
        t, messages = self.historiques.get(cle, (0.0, []))
        return [] if time.time() - t > 120 else messages  # conversation oubliée après 2 min de silence

    @historique.setter
    def historique(self, messages):
        cle = self.cle_historique()
        if cle is not None:
            self.historiques[cle] = (time.time(), list(messages)[-6:])

    def executer_outil(self, nom, args, texte, noms, actions, musiques):
        """Aiguillage fermé : seul un outil de la liste du tour s'exécute, tout autre nom reçoit
        « outil indisponible » (un appel halluciné ou soufflé par la phrase n'agit jamais)."""
        if nom not in noms or not self.ha:
            return dict(INDISPONIBLE)
        if nom == "appeler_service":
            domaine = args.get("domaine")
            # Le LLM n'appelle que les domaines de son schéma (DOMAINES_OUTIL_LLM), même si la table en permet d'autres
            # (D6) : l'enum du schéma, qu'un modèle peut contourner, n'est pas le seul garde.
            if domaine in DOMAINES_HORS_LLM or (isinstance(domaine, str) and domaine not in DOMAINES_OUTIL_LLM
                                                and self.ha.services_permis(domaine)):
                return {"erreur": f"domaine {args.get('domaine')} non disponible par la voix. Dis-le simplement."}
            refus = garde_fou_volume(texte, args)
            if refus:
                return {"erreur": refus}
            res = self.ha.service(args.get("domaine", ""), args.get("service", ""),
                                  args.get("entity_id"), args.get("donnees"))
            actions.append(resume_action(f"{args.get('domaine')}.{args.get('service')}",
                                         args.get("entity_id"), args.get("donnees"))
                           + (" (refusé : sécurité)" if "refusé" in str(res.get("erreur", ""))
                              else " (refusé par HA)" if "erreur" in res else ""))
            if "erreur" not in res:  # action réussie : candidate à l'apprentissage
                self.dernieres_actions.append(action_dictionnaire(args))
            return res
        if nom == "jouer_musique":
            res = self.ha.musique(args.get("recherche"), args.get("type", "track"), args.get("enceinte", "toutes"),
                                  args.get("artiste", ""))
            musiques.append(res)
            actions.append(resume_action("music_assistant.play_media",
                                         self.ha.ENCEINTES_MUSIQUE.get(args.get("enceinte") or "toutes"),
                                         {"media_id": args.get("recherche"), "media_type": args.get("type", "track")})
                           + (" (refusé : sécurité)" if str(res.get("erreur", "")).startswith("refusé :")
                              else " (non joué)" if "erreur" in res
                              else " (non confirmé)" if res.get("confirme") is False else ""))
            return res
        if nom == "proposer_routine":
            if not self.rappel_routine:
                return dict(INDISPONIBLE)
            res = self.rappel_routine(args, texte)
            PAROLE_FIXEE.set(res["parole"])
            return {"ok": bool(res["ok"]), "parole": res["parole"]}
        if nom == "lire_etat":
            demande = args.get("entity_id", "")
            if not isinstance(demande, str) or demande not in self.ha.entites_llm:  # même liste que l'enum du schéma, que le LLM peut contourner
                return {"erreur": f"refusé : {demande} n'est pas dans l'inventaire des appareils permis"}
            return self.ha.etat(demande)
        return dict(INDISPONIBLE)

    def boucle_outils(self, texte, noms, actions, musiques, demander, lire_appel, ajouter, relancer=None):
        """Boucle d'appel d'outils commune au serveur local (format OpenAI) et à Claude (format Anthropic).

        Elle porte tout ce qui ne dépend pas du format : la limite de tours, l'exécution de chaque outil par
        l'aiguillage fermé (executer_outil : liste blanche, garde-fou de volume, journal des actions), la parole
        fixée par le serveur et la phrase de repli. Le format reste dans les fonctions fournies par l'appelant :
        - demander() fait un appel au LLM et renvoie un TourLLM ;
        - lire_appel(appel) renvoie (nom de l'outil, arguments), arguments à None quand ils sont illisibles ;
        - ajouter(tour, retours) ajoute aux messages le tour du LLM puis les résultats, retours étant la liste de
          (appel, résultat) dans l'ordre des appels ;
        - relancer(reponse), facultative, renvoie vrai quand une réponse sans outil doit redemander un tour.

        Renvoie la réponse parlée. Les actions réussies ou refusées s'ajoutent à `actions`."""
        for _ in range(TOURS_OUTILS_MAX):
            tour = demander()
            if tour.refus:
                return PHRASE_REFUS_LLM
            if not tour.appels:
                if relancer and relancer(tour.reponse):
                    continue
                return tour.reponse
            retours = []
            for appel in tour.appels:
                nom, args = lire_appel(appel)
                res = (self.executer_outil(nom, args, texte, noms, actions, musiques)
                       if isinstance(args, dict) else {"erreur": "arguments illisibles"})
                retours.append((appel, res))
            ajouter(tour, retours)
            if PAROLE_FIXEE.get() is not None:  # reformulation écrite par le serveur : le tour s'arrête là
                return PAROLE_FIXEE.get()
        return PHRASE_ABANDON

    def terminer_tour(self, mode, historique, texte, reponse, actions, musiques, si_vide=""):
        """Fin commune d'une demande : le garde-fou de musique corrige la réponse, puis la conversation est gardée
        (sauf en mode isolé). `si_vide` ne remplace dans l'historique qu'une réponse vide."""
        reponse = garde_fou_musique(reponse, musiques)
        if mode in MODES_ISOLES:
            return reponse, actions
        self.historique = historique + [{"role": "user", "content": texte},
                                        {"role": "assistant", "content": reponse or si_vide}]
        return reponse, actions

    def repondre(self, texte, mode="commande"):
        """Une demande au LLM local (format OpenAI) : adaptateur mince autour de boucle_outils."""
        historique = [] if mode in MODES_ISOLES else self.historique
        PAROLE_FIXEE.set(None)
        liste, etats = self.ha.inventaire() if self.ha else ("(Home Assistant non connecté)", "")
        jour = date_francaise()
        # Tout ce qui change (date, états) va dans le dernier message : le début reste en cache.
        messages = [{"role": "system", "content": CONSIGNE.format(inventaire=liste) + self.supplement_mode(mode)}]
        probables = presélection(texte, liste)
        indice = f" Appareils probables pour cette demande : {probables}." if probables else ""
        messages += historique + [{"role": "user", "content":
                                   f"[Nous sommes le {jour}.{self.indication_personne} États actuels : {etats}{indice} Réponds en français.]\n\n{texte}"}]
        actions, relance = [], False
        self.dernieres_actions = []
        musiques = []  # résultats de jouer_musique, pour garde_fou_musique
        outils = outils_avec_entites(self.ha.entites_llm, mode) if self.ha else []
        noms = {nom_outil(o) for o in outils}

        def demander():
            corps = {"cache_prompt": True, "model": self.cfg["llm_modele"], "messages": messages,
                     "temperature": 0, "max_tokens": 300,
                     "chat_template_kwargs": {"enable_thinking": False}}
            if outils:
                corps["tools"] = outils
            r = self.client.post(f"{self.cfg['llm_url']}/chat/completions", json=corps)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            appels = msg.get("tool_calls") or []
            return TourLLM(reponse="" if appels else nettoyer(msg.get("content") or ""), appels=appels, brut=msg)

        def lire_appel(a):
            try:
                args = json.loads(a["function"].get("arguments") or "{}")
            except ValueError:
                args = None
            return a["function"].get("name"), args

        def ajouter(tour, retours):
            messages.append({"role": "assistant", "content": tour.brut.get("content") or "",
                             "tool_calls": tour.appels})
            for a, res in retours:
                messages.append({"role": "tool", "tool_call_id": a["id"],
                                 "content": json.dumps(res, ensure_ascii=False)})

        def relancer(reponse):
            # Qwen annonce « je vais éteindre », affirme « j'ai allumé » ou refuse à tort
            # (« déjà allumée » alors qu'elle est éteinte) sans appeler l'outil (vu les 11 et
            # 12/10). Une relance, une seule, avec l'état réel sous les yeux.
            nonlocal relance
            if ("appeler_service" in noms and not actions and not relance and re.search(
                    r"\bje (vais|peux|m'en occupe|lance|allume|éteins|coupe)|\bj'ai (allumé|éteint|lancé|coupé|mis|réglé|baissé|monté)"
                    r"|je ne peux pas|déjà (allumée?|éteinte?)|pas trouvé|n'est pas dans la liste", reponse, re.I)):
                relance = True
                messages.extend([{"role": "assistant", "content": reponse},
                                 {"role": "user", "content": "Tu n'as appelé aucun outil, donc rien n'a été fait. "
                                  f"Rappel des appareils actifs : {etats} Si ma demande est une action, appelle "
                                  f"appeler_service maintenant avec l'entity_id exact de la liste (la télé est {TELE}). "
                                  "Sinon réponds simplement."}])
                return True
            return False

        reponse = self.boucle_outils(texte, noms, actions, musiques, demander, lire_appel, ajouter, relancer)
        return self.terminer_tour(mode, historique, texte, reponse, actions, musiques)


def garde_fou_volume(texte, args):
    """Refuse un changement de volume non demandé, et plafonne le volume quand la configuration règle un
    plafond (securite.VOLUME_MAX, seule source, que verifier() applique aussi avant chaque envoi).

    Le 12/10, « Mets le salon à fond » a allumé la lumière ET mis la Enceintes au maximum (en essai,
    rien n'est parti). Modifie args sur place pour le plafond, renvoie un motif de refus ou None."""
    if not str(args.get("service", "")).startswith("volume"):
        return None
    # Demande explicite seulement : le mot « son » seul ne suffit pas, Canary transcrit souvent
    # « à fond » en « à son » (« la lumière de la télé à son » a touché la Enceintes, 12/10).
    if not re.search(r"\b(volume|sourdine|muet|plus fort|moins fort|entend"
                     r"|(monte|baisse|coupe|remets|mets|augmente|diminue)\w*\s+(le\s+|du\s+|un peu le\s+)?son)\b",
                     texte, re.I):
        return "volume non demandé dans la phrase, n'y touche pas"
    donnees = args.get("donnees") or {}
    if isinstance(donnees, dict) and isinstance(donnees.get("volume_level"), (int, float)):
        donnees["volume_level"] = securite.plafonner_volume(donnees["volume_level"])
        args["donnees"] = donnees
    return None


MOTS_VIDES = {"allume", "eteins", "eteint", "mets", "met", "lance", "coupe", "lumiere", "lumieres",
               "lampe", "fond", "tout", "toute", "toutes", "peux", "est", "que", "les", "des", "une",
               "dans", "sur", "pour", "avec", "maintenant", "merci", "plait", "fait", "trop", "peu"}


def presélection(texte, liste, maxi=4):
    """Appareils dont le nom, la pièce ou l'entity_id contient un mot de la demande.

    Qwen 9B ne trouvait pas la lumière « Salon » au milieu des lecteurs de musique du même nom
    (banc du 12/10) : on lui désigne les candidats au lieu de le laisser chercher.
    Une lumière passe devant un lecteur quand la demande parle de lumière ou de luminosité."""
    from dictionnaire import normaliser
    mots = {m for m in normaliser(texte).split() if len(m) > 2 and m not in MOTS_VIDES}
    if not mots:
        return ""
    lumiere = bool(re.search(r"lumi|lampe|fond|sombre|clair|%|luminosit", texte, re.I))
    scores = []
    for ligne in liste.splitlines():
        champs = [c.strip() for c in ligne.split("|")]
        if len(champs) < 3:
            continue
        e, nom, piece = champs[:3]
        cible = normaliser(f"{e.replace('_', ' ').replace('.', ' ')} {nom} {piece}").split()
        n = sum(1 for m in mots if any(m == c or (len(m) > 4 and c.startswith(m)) for c in cible))
        if n:
            bonus = 1 if (lumiere and e.startswith("light.")) or (not lumiere and TELE_FAMILLE and e.startswith(TELE_FAMILLE)) else 0
            scores.append((n + bonus, e, nom))
    scores.sort(key=lambda s: -s[0])
    return ", ".join(f"{e} ({nom})" for _, e, nom in scores[:maxi])


MANQUE_CLE_CLAUDE = ("ANTHROPIC_API_KEY vide (poc/.env, ou option anthropic_api_key de l'appli HA, "
                     "puis redémarrer le serveur) : le cerveau Claude ne peut répondre à aucune demande")


def cle_claude_absente():
    """Vrai quand le cerveau Claude n'a pas de clé (0.27.1) : sans cet avertissement, chaque demande au LLM
    échouait sur une erreur d'authentification du SDK, sans rien dire au démarrage. Le SDK accepte aussi un
    jeton ANTHROPIC_AUTH_TOKEN à la place de la clé (0.27.3)."""
    return not any(os.getenv(v, "").strip() for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))


class CerveauClaude(Cerveau):
    """Même rôle que Cerveau, mais avec Claude (API Anthropic, SDK officiel) au lieu de Qwen local.

    Mêmes outils, même consigne, mêmes garde-fous (liste blanche, volume, présélection).
    Réflexion coupée et consigne en cache : on vise la latence d'une commande vocale.
    La clé est lue dans ANTHROPIC_API_KEY (poc/.env) ou, dans l'appli HA, dans l'option anthropic_api_key. Le SDK
    accepte aussi un jeton ANTHROPIC_AUTH_TOKEN à la place. Elle n'est jamais affichée."""

    def __init__(self, cfg, ha):
        import anthropic
        super().__init__(cfg, ha)
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=1, timeout=20)
        # Variables vides ou faites d'espaces, ou rien trouvé par le client lui-même.
        self.sans_cle = cle_claude_absente() or not (getattr(self.client, "api_key", None)
                                                      or getattr(self.client, "auth_token", None))
        if self.sans_cle:
            print(f"  ! {MANQUE_CLE_CLAUDE}.")
        self.modele = cfg["claude_modele"]
        self.outils = {}  # mode -> (entités, liste) : même liste tant que l'inventaire ne change pas
        self.mesures = []  # (durée, tokens entrée, tokens lus en cache, tokens sortie) par appel

    @staticmethod
    def outils_claude(entites, mode="commande"):
        return [{"name": o["function"]["name"], "description": o["function"]["description"],
                 "input_schema": o["function"]["parameters"]} for o in outils_avec_entites(entites, mode)]

    def outils_du_mode(self, mode):
        """Liste du mode, gardée en cache : l'en-tête de la requête reste identique d'un tour à l'autre."""
        if not self.ha:
            return []
        entites = frozenset(self.ha.entites_llm)
        if mode not in self.outils or self.outils[mode][0] != entites:
            self.outils[mode] = (entites, self.outils_claude(entites, mode))
        return self.outils[mode][1]

    def repondre(self, texte, mode="commande"):
        if self.sans_cle:
            raise RuntimeError(MANQUE_CLE_CLAUDE)
        historique = [] if mode in MODES_ISOLES else self.historique
        PAROLE_FIXEE.set(None)
        liste, etats = self.ha.inventaire() if self.ha else ("(Home Assistant non connecté)", "")
        jour = date_francaise()
        probables = presélection(texte, liste)
        indice = f" Appareils probables pour cette demande : {probables}." if probables else ""
        systeme = [{"type": "text", "text": CONSIGNE.format(inventaire=liste),
                    "cache_control": {"type": "ephemeral"}}]
        if mode in CONSIGNES_MODE:
            systeme.append({"type": "text", "text": self.supplement_mode(mode)})
        messages = list(historique) + [{"role": "user", "content":
                                         f"[Nous sommes le {jour}.{self.indication_personne} États actuels : {etats}{indice} Réponds en français.]\n\n{texte}"}]
        actions = []
        self.dernieres_actions = []
        musiques = []  # résultats de jouer_musique, pour garde_fou_musique
        outils = self.outils_du_mode(mode)
        noms = {o["name"] for o in outils}

        def demander():
            t = time.perf_counter()
            r = self.client.messages.create(
                model=self.modele, max_tokens=1024, system=systeme, messages=messages,
                tools=outils, thinking={"type": "disabled"})
            u = r.usage
            self.mesures.append((time.perf_counter() - t, u.input_tokens,
                                 getattr(u, "cache_read_input_tokens", 0) or 0, u.output_tokens))
            if r.stop_reason == "refusal":
                return TourLLM(refus=True)
            appels = [b for b in r.content if b.type == "tool_use"]
            if appels:
                return TourLLM(appels=appels, brut=r)
            return TourLLM(reponse=nettoyer(" ".join(b.text for b in r.content if b.type == "text")), brut=r)

        def lire_appel(b):
            return b.name, dict(b.input or {})

        def ajouter(tour, retours):
            messages.append({"role": "assistant", "content": tour.brut.content})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(res, ensure_ascii=False),
                 **({"is_error": True} if "erreur" in res else {})} for b, res in retours]})

        reponse = self.boucle_outils(texte, noms, actions, musiques, demander, lire_appel, ajouter)
        return self.terminer_tour(mode, historique, texte, reponse, actions, musiques, si_vide="...")


ANNONCE_LANCEE = re.compile(r"lancée?s?\b|c'est parti|ça (joue|tourne)|en lecture|j'ai mis\b", re.I)


def garde_fou_musique(reponse, musiques):
    """Le LLM ne dit jamais « c'est lancé » quand jouer_musique n'a rien confirmé (champ lance absent).
    La consigne le demande, mais un petit modèle annonce parfois ce qu'il n'a pas fait (Qwen, 11 et
    12/10/2026) : la réponse est alors remplacée par une phrase fixe."""
    if not musiques or any("lance" in r for r in musiques) or not ANNONCE_LANCEE.search(reponse or ""):
        return reponse
    if any("erreur" in r for r in musiques):
        return "Je n'ai pas réussi à lancer cette musique."
    return "J'ai demandé la musique, mais les enceintes ne la jouent pas encore."


def resume_action(service, entity_id, donnees=None):
    """Ligne de journal d'une action, réglages compris : « light.turn_on light.x (color_name=red) »."""
    cible = " ".join(entity_id) if isinstance(entity_id, list) else (entity_id or "")
    reglages = ", ".join(f"{k}={v}" for k, v in (donnees or {}).items()) if isinstance(donnees, dict) else ""
    return f"{service} {cible}".strip() + (f" ({reglages})" if reglages else "")


def action_dictionnaire(args):
    """Appel d'outil du LLM converti au format d'une action de commandes.yaml."""
    action = {"service": f"{args.get('domaine')}.{args.get('service')}"}
    if args.get("entity_id"):
        action["entity_id"] = args["entity_id"]
    if isinstance(args.get("donnees"), dict):
        action.update(args["donnees"])
    return action


# Phrases qu'on n'apprend pas : leur effet dépend du moment ou de ce qui vient d'être dit.
NON_APPRENABLE = re.compile(r"-(la|le|les|lui|leur)\b|\b(ça|cela|ceci|pareil|même chose|aussi|encore|plus|moins"
                            r"|un peu|davantage|de nouveau|à nouveau|remets|refais|comme avant|celle|celui|ceux)\b",
                            re.I)
# Réponses qui trahissent un échec ou une question : rien à apprendre.
REPONSE_DOUTEUSE = re.compile(r"\?|je ne peux pas|pas réussi|n'ai pas pu|impossible|pas trouvé|n'existe pas", re.I)
# Correction vocale juste après une action apprise : la leçon est oubliée.
CORRECTION = re.compile(r"^\s*(non|annule|annuler|c'est pas ça|ce n'est pas ça|pas ça|mauvais|erreur|oublie)\b", re.I)
DELAI_CORRECTION = 30.0
# Demande de création ou de changement de routine (0.42.0, note des routines 4.1). Liste à ajuster sur des phrases
# réelles, la même que dans poc/tests/cas_routines.json. Élargie en 0.43.3 aux demandes dites naturellement : le mot
# « routine » reste exigé pour toute forme à verbe, et les verbes de création n'acceptent que « une » (« fais la
# routine du matin » est un lancement, pas une création). « scénario » n'est pas reconnu, le registre ne connaît que
# des routines.
_PRONOM_ROUTINE = r"(?:[-\s]+(?:moi|nous))?"
INTENTION_ROUTINE = re.compile(
    r"\b(?:quand|lorsque|si|(?:à|a) chaque fois que|chaque fois que)\s+je\s+(?:te\s+)?(?:dis|dirai|disais)\b"
    r"|\b(?:dorénavant|désormais|à partir de maintenant|a partir de maintenant)\b"
    # changer une routine existante, ou la créer avec ou sans « -moi »
    r"|\b(?:cr[ée]e[rsz]?|change[rz]?|modifie[rz]?|remplace[rz]?)" + _PRONOM_ROUTINE +
    r"\s+(?:une\s+|la\s+|ma\s+|cette\s+)?(?:(?:nouvelle|petite)\s+)?routine\b"
    r"|\bnouvelle\s+routine\b"
    # autres verbes de création : fais, ajoute, programme, mets en place, enregistre, configure, prépare
    r"|(?<!\bje )(?<!\bj')\b(?:fais|faire|faites|ajoute[rsz]?|programme[rsz]?|enregistre[rsz]?|configure[rsz]?"
    r"|pr[ée]pare[rsz]?|m(?:ets?|ettre|ettez)" + _PRONOM_ROUTINE + r"\s+en\s+place)" + _PRONOM_ROUTINE +
    r"\s+une\s+(?:(?:nouvelle|petite)\s+)?routine\b"
    # « je voudrais / je veux / j'aimerais (créer) une routine »
    r"|\b(?:je\s+(?:voudrais|veux|souhaite|souhaiterais)|j'aimerais|j'aimerai)\s+(?:bien\s+)?"
    r"(?:(?:cr[ée]er|faire|ajouter|avoir|programmer|enregistrer|configurer|pr[ée]parer|mettre\s+en\s+place)\s+)?"
    r"une\s+(?:(?:nouvelle|petite)\s+)?routine\b", re.I)
# Une suite de routine (musique, pauses) à la fois : l'assistant n'est pas réentrant et ha.personne est partagé.
VERROU_ROUTINES = threading.Lock()


def nettoyer(t):
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S)
    t = re.sub(r"[*_#`>]", "", t)
    return " ".join(t.split())


# ---------------------------------------------------------------- boucle
class Assistant:
    def __init__(self, cfg, avec_audio=True, essai=False):
        from dictionnaire import Dictionnaire
        self.cfg, self.essai = cfg, essai
        self.lecons = {}  # appareil -> (phrase apprise, heure) : « non » n'annule que la leçon de son appareil
        t = time.perf_counter()
        # Dictionnaire écrit à la main dans la configuration de la maison, phrases apprises sur cette machine.
        self.dico = Dictionnaire(maison.chemin("commandes.yaml"), DONNEES / "commandes_apprises.yaml")
        print(f"  dictionnaire : {len(self.dico.formes)} formes de phrases")
        self.ha = HomeAssistant(cfg["ha_url"], cfg["ha_token"]) if cfg["ha_token"] else None
        if self.ha:
            self.ha.essai = essai
            self.ha.vue_llm = self.dico.llm
            ajoutes = self.ha.charger_services()
            if ajoutes:
                print(f"  services de HA : {ajoutes} ajoutés au socle statique")
        else:
            print("  ! HA_TOKEN absent de poc/.env : pilotage de la maison désactivé, LLM seul.")
        if cfg.get("llm_fournisseur") == "claude":
            self.cerveau = CerveauClaude(cfg, self.ha)
            print(f"  cerveau : Claude ({cfg['claude_modele']}) par API")
        else:
            self.cerveau = Cerveau(cfg, self.ha)
            print("  cerveau : Qwen3.5-9B local (llama-server)")
        self.cerveau.rappel_routine = self.creer_routine
        self.cerveau.rappel_liste = self.liste_routines_llm
        self.suites_routine = []
        self.voix = Voix(cfg["voix"], cfg["sortie"]) if avec_audio else None
        self.stt = Transcripteur() if avec_audio else None
        print(f"  modèles chargés en {time.perf_counter() - t:.1f} s")

    def indication(self, personne):
        """Phrase ajoutée à la demande du LLM : qui parle et ce que désigne « ma chambre »."""
        from dictionnaire import INCONNU, normaliser
        pers = self.dico.personnes
        p = normaliser(personne or "")
        if not p:
            return ""
        if p == pers.defaut:
            return (f" La personne qui parle est {p.capitalize()}, reconnue par la tablette. « Ma chambre », "
                    f"« mes chevets » ou « mon plafond » désignent sa chambre à lui : {', '.join(sorted(pers.chambre))}.")
        table = pers.remplacer.get(p)
        if p != INCONNU and table:
            cibles = sorted({v if isinstance(v, str) else v.get("entity_id", "") for v in table.values()})
            return (f" La personne qui parle est {p.capitalize()}, reconnue par la tablette. « Ma chambre », "
                    f"« mes chevets », « mon plafond » ou « ma lumière » désignent ses lumières à lui : "
                    f"{', '.join(cibles)}. Il peut les allumer, les éteindre et les régler, rien d'autre chez lui.")
        return (" La caméra de la tablette voit une personne qu'elle n'a pas reconnue. Si elle parle de « ma chambre », "
                "« mes chevets », « mon plafond » ou « ma lumière », ne touche à aucune chambre : explique que tu ne sais "
                f"pas de quelle chambre il s'agit et propose-lui de dire « la chambre de {maison.NOM_PROPRIETAIRE} » si c'est elle.")

    @property
    def essai(self):
        r = REQUETE.get()
        return r.essai if r else getattr(self, "_essai", False)

    @essai.setter
    def essai(self, valeur):
        self._essai = bool(valeur)

    @contextlib.contextmanager
    def requete(self, essai=None, personne=None, appareil=None, role=None, canal=None):
        """Le temps d'une commande : essai, personne qui parle, appareil, rôle et canal, pour la sécurité,
        l'inventaire, la consigne et l'historique. Rien n'est écrit sur les objets partagés.
        Le rôle vient de l'appareil appairé (ROLE_DE) sauf si l'appelant le donne."""
        if essai is None:
            essai = getattr(self, "_essai", False)
        if role is None:
            role = role_du_contexte(appareil)
        jeton = REQUETE.set(Requete(essai, personne, appareil, self.indication(personne), role, canal))
        try:
            yield
        finally:
            REQUETE.reset(jeton)

    def traiter(self, texte, t_stt=0.0, personne=None, appareil=None, essai=None, canal=None):
        with self.requete(essai=essai, personne=personne, appareil=appareil, canal=canal):
            return self._traiter(texte, t_stt, personne)

    # ------------------------------------------------------------------------------------- routines (0.42.0)
    def contexte_routines(self, complet=True, creation=""):
        """Contexte du moteur de routines pour la requête en cours. Léger (sans inventaire) pour un brouillon ou la
        recherche d'un déclencheur, complet (inventaire de la personne qui parle) pour créer ou lancer."""
        r = REQUETE.get()
        ctx = routines.Contexte(
            personne=(r.personne if r else None) or "", role=(r.role if r else "") or "",
            appareil=(r.appareil if r else "") or "", essai=self.essai,
            enceintes=dict(self.ha.ENCEINTES_MUSIQUE) if self.ha else {},
            dico=self.dico, services_permis=self.ha.services_permis if self.ha else None,
            mots_reserves=[reglage_reveil().mot, reglage_reveil().nom],
            motifs_reserves=[CORRECTION, INTENTION_ROUTINE], garde_volume=garde_fou_volume, phrase_creation=creation)
        if complet and self.ha:
            try:
                liste, _ = self.ha.inventaire()
                ctx.entites = set(self.ha.entites_llm)
                for ligne in liste.splitlines():
                    morceaux = [m.strip() for m in ligne.split("|")]
                    if len(morceaux) >= 2 and morceaux[0]:
                        ctx.noms[morceaux[0]] = morceaux[1]
            except Exception as e:  # HA injoignable : rien ne passe (fermé par défaut)
                print(f"  routines : inventaire illisible ({e.__class__.__name__})")
                ctx.entites = None
        return ctx

    def liste_routines_llm(self):
        """Routines que la personne peut changer, ajoutées à la consigne du mode création pour qu'une modification
        revienne comme un remplacement complet."""
        ctx = self.contexte_routines(complet=False)
        lignes = []
        for r in routines.registre().visibles(ctx):
            if not routines.peut_gerer(r, ctx) or not r["declencheurs"]:
                continue
            d = r["declencheurs"][0]
            faits = ", puis ".join(routines._decrire_etape(e, ctx) for e in r["etapes"])
            lignes.append(f"- {r['id']} : {r['nom']}, phrases {d['phrases']}, étapes : {faits}")
        if not lignes:
            return ""
        return ("\nRoutines existantes de cette personne (pour en changer une, appelle proposer_routine avec "
                "remplace = son id et la routine complète) :\n" + "\n".join(lignes))

    def creer_routine(self, args, texte):
        """Appelé par l'outil proposer_routine : valide la proposition du LLM et garde le brouillon en attente."""
        reg = routines.registre()
        ctx = self.contexte_routines(complet=True, creation=texte)
        res = routines.valider_proposition(args, ctx, reg)
        if res["ok"]:
            reg.poser_brouillon(ctx, res["routine"], res["remplace"])
        else:
            routines.journal("proposition refusée", personne=ctx.personne, appareil=ctx.appareil, motif=res["parole"])
        return res

    def proposer_routine(self, texte):
        """Demande de création : la phrase part dans la boucle fermée du mode « proposer » (sans historique)."""
        personne = Cerveau.cle_conversation()[0]
        refus = securite.phrase_protegee(texte, personne)
        if refus:  # même règle qu'avant tout appel au LLM
            return f"Je ne le fais pas : {refus}."
        qui = routines.qui_est(self.contexte_routines(complet=False))
        if qui == "inconnu":
            return routines.MSG_INCONNU
        if qui == "invite":
            return routines.MSG_INVITE
        if not self.ha:
            return "Je n'arrive pas à joindre la maison, je ne crée pas de routine."
        try:
            parole, _ = self.cerveau.repondre(texte, mode="proposer")
        except Exception as e:
            if str(e) == MANQUE_CLE_CLAUDE:
                return "Je n'ai pas de clé Anthropic, Claude ne peut pas répondre."
            return "Le modèle de langage ne répond pas. Le PC est peut-être occupé."
        return parole

    def question_routine(self, texte):
        """Étape « question » d'une routine : le seul outil lire_etat, aucun historique."""
        parole, _ = self.cerveau.repondre(texte, mode="question")
        return parole

    def suite_routine(self, suite):
        """Partie de fond d'une routine (musique, pauses), dans le contexte de la requête et sous un verrou."""
        contexte = contextvars.copy_context()

        def tache():
            try:
                with VERROU_ROUTINES:
                    contexte.run(suite)
            except Exception as e:
                print(f"  routines : suite en erreur ({e.__class__.__name__})")
                routines.journal("suite en erreur", erreur=e.__class__.__name__)

        if self.essai:  # essai : ni pause ni musique, la suite ne fait que se noter
            tache()
            return
        fil = threading.Thread(target=tache, name="routine", daemon=True)
        self.suites_routine = [f for f in getattr(self, "suites_routine", []) if f.is_alive()] + [fil]
        fil.start()

    def lancer_routine(self, routine):
        """Lance une routine pour la personne de la requête en cours. Renvoie ce qu'il faut dire."""
        ctx = self.contexte_routines(complet=True)
        if not routines.peut_lancer(routine, ctx):
            return f"La routine {routine['nom']} n'est pas pour toi."
        parole, suite = routines.lancer(routine, ctx, self.ha, question=self.question_routine,
                                        reg=routines.registre())
        self.derniers_echecs = list(ctx.echecs)  # lus par la réponse réseau routine_lancee, sous le verrou du moteur
        if suite:
            self.suite_routine(suite)
        return parole

    @staticmethod
    def _res_routine(parole, voie, actions=None):
        appareil = (REQUETE.get().appareil if REQUETE.get() else "") or ""
        return {"parole": parole, "voie": voie, "actions": actions or [],
                "confirmation": appareil in routines.registre().brouillons}

    def routines_avant(self, texte):
        """Étapes 1 à 5 de l'ordre de traitement des routines (note de conception 5.1), appelées par _traiter et par
        le message llm de la tablette : brouillon en attente et « oui » qui suit, demande de création, déclencheur.
        commandes de gestion (lister, décrire, couper, réactiver, supprimer, lancer). Renvoie None (la chaîne ordinaire continue) ou un dict
        {parole, voie, actions, confirmation}. Le texte est déjà passé par epurer."""
        try:
            return self._routines_avant(texte)
        except Exception as e:
            print(f"  routines : erreur ({e.__class__.__name__}: {e})")
            routines.journal("erreur", erreur=e.__class__.__name__)
            if INTENTION_ROUTINE.search(texte):  # jamais au LLM ordinaire, qui agirait sur-le-champ
                return self._res_routine("Je n'arrive pas à gérer les routines pour le moment.", "routine erreur")
            return None

    def _routines_avant(self, texte):
        if not routines.reglage("active"):
            if INTENTION_ROUTINE.search(texte):
                return self._res_routine("Les routines sont désactivées.", "routine (désactivées)")
            return None
        reg = routines.registre()
        ctx = self.contexte_routines(complet=False)
        parole = reg.reponse_brouillon(texte, ctx)
        if parole is not None:
            return self._res_routine(parole, "routine (brouillon)")
        # Gestion à la voix (étape 2) : avant la correction, car « oublie la routine Arrivée » est aussi une CORRECTION
        gestion = routines.gerer(texte, ctx, reg, contexte_complet=lambda: self.contexte_routines(complet=True))
        if gestion is not None:
            if gestion["lancer"] is not None:
                routine = gestion["lancer"]
                parole = self.lancer_routine(routine)
                return self._res_routine(parole, f"routine ({routine['nom']})", [f"routine {routine['nom']}"])
            return self._res_routine(gestion["parole"], gestion["voie"], gestion["actions"])
        appareil = Cerveau.cle_conversation()[1]
        lecon = (getattr(self, "lecons", None) or {}).get(appareil)
        if lecon and CORRECTION.search(texte) and time.time() - lecon[1] < DELAI_CORRECTION:
            return None  # « non » juste après une leçon apprise : la correction ordinaire passe en premier
        if INTENTION_ROUTINE.search(texte):
            return self._res_routine(self.proposer_routine(texte), "routine (création)")
        routine, etat = reg.trouver(texte, ctx)
        if etat == "reservee":
            auteur = str(routine.get("auteur") or "").capitalize()
            return self._res_routine(f"Je ne t'ai pas reconnu, la routine {routine['nom']} est réservée à {auteur}.",
                                     "routine refus")
        if routine:
            parole = self.lancer_routine(routine)
            return self._res_routine(parole, f"routine ({routine['nom']})", [f"routine {routine['nom']}"])
        return None

    def _finir_routine(self, texte, pre, t_stt, t):
        """Fin d'un tour réglé par les routines : même sortie que _traiter (console, voix, journal)."""
        parole, voie, actions = pre["parole"], pre["voie"], pre["actions"]
        t_cerveau = time.perf_counter() - t
        print(f"  [{voie_courte(voie)}] {pour_console(parole)}" + (f"   actions : {'; '.join(actions)}" if actions else ""))
        t_tts = 0.0
        if self.voix and parole:
            t = time.perf_counter()
            signal = self.voix.synthetiser(parole)
            t_tts = time.perf_counter() - t
            self.voix.jouer(signal)
        journaliser(texte, voie + (" [essai]" if self.essai else ""), t_stt, t_cerveau, t_tts, parole, actions)
        return parole

    def routines_reseau(self, genre, msg, serveur=""):
        """Messages réseau des routines (note de conception 7.4), à appeler dans self.requete(...) : le moteur de
        routines filtre par la personne et le rôle de la requête. Renvoie le dict à envoyer. Le serveur WebSocket a
        déjà contrôlé le port chiffré et le rôle de l'appareil (acces.type_permis)."""
        from dictionnaire import epurer
        reg = routines.registre()
        ctx = self.contexte_routines(complet=False)
        actif = routines.reglage("active")
        ident = str(msg.get("id") or "")[:80]

        def refuse(raison):
            return {"etat": "refuse", "type": genre, "message": raison}

        if genre == "routines":
            reg.assurer()
            if not actif:
                droits = {"qui": routines.qui_est(ctx), "creer": False, "tout_gerer": False, "exporter": False}
                return {"etat": "routines", "routines": [], "serveur": serveur, "droits": droits, "version": reg.version}
            return {"etat": "routines", "routines": [reg.resume(r) for r in reg.visibles(ctx)], "serveur": serveur,
                    "droits": routines.droits(ctx), "version": reg.version}
        if not actif:
            return refuse("routines désactivées")
        if genre == "routine_lancer":
            r = reg.par_id(ident)
            if r is None or r not in reg.visibles(ctx):  # une routine invisible vaut une routine inconnue
                return {"etat": "routine_lancee", "id": ident, "parole": "Je ne trouve pas cette routine.",
                        "echecs": [], "ok": False}
            if not r["actif"]:
                return {"etat": "routine_lancee", "id": ident, "ok": False, "echecs": [],
                        "parole": f"La routine {r['nom']} est coupée."}
            t = time.perf_counter()
            parole = self.lancer_routine(r)
            echecs = list(getattr(self, "derniers_echecs", []))
            journaliser(f"routine {r['nom']}", f"routine ({r['nom']}, depuis l'appareil)"
                        + (" [essai]" if self.essai else ""), 0.0, time.perf_counter() - t, 0.0, parole,
                        [f"routine {r['nom']}"])
            return {"etat": "routine_lancee", "id": ident, "parole": parole, "echecs": echecs, "ok": True}
        if genre in ("routine_activer", "routine_supprimer"):
            if genre == "routine_activer":
                if not isinstance(msg.get("actif"), bool):
                    return refuse("champ actif attendu")
                fait = reg.activer(ident, msg["actif"], ctx)
            else:
                fait = reg.supprimer(ident, ctx)
            return {"etat": "routine_ok", "id": ident} if fait else refuse("routine inconnue ou non permise")
        if genre == "routine_texte":
            texte = epurer(str(msg.get("texte") or "").strip())[:500]
            if not texte:
                return {"etat": "routine_texte", "parole": "", "confirmation_attendue": 0}
            t = time.perf_counter()
            pre = self.routines_avant(texte)
            if pre is None:
                return {"etat": "routine_texte", "parole": "Ce n'est pas une demande de routine.",
                        "confirmation_attendue": 0}
            journaliser(texte, pre["voie"] + (" [essai]" if self.essai else ""), 0.0, time.perf_counter() - t, 0.0,
                        pre["parole"], pre["actions"])
            return {"etat": "routine_texte", "parole": pre["parole"],
                    "confirmation_attendue": routines.reglage("delai_confirmation_s") if pre["confirmation"] else 0}
        if genre == "routines_export":
            contenu = reg.exporter(ctx)
            if contenu is None:
                return refuse("réservé au propriétaire")
            return {"etat": "routines_export", "contenu": contenu}
        return refuse("type inconnu")

    def _traiter(self, texte, t_stt, personne):
        from dictionnaire import epurer
        t = time.perf_counter()
        voie, actions = "ha", []
        texte = epurer(texte)  # « est-ce que tu peux éteindre » devient « éteindre »
        pre = self.routines_avant(texte)  # brouillon, création, déclencheur : avant la correction et le dictionnaire
        if pre is not None:
            return self._finir_routine(texte, pre, t_stt, t)
        # Correction vocale de la dernière leçon : « non », « annule »... dans les 30 s.
        lecons = getattr(self, "lecons", None)
        if lecons is None:
            lecons = self.lecons = {}
        appareil = Cerveau.cle_conversation()[1]
        lecon = lecons.get(appareil)
        if lecon and CORRECTION.search(texte) and time.time() - lecon[1] < DELAI_CORRECTION:
            self.dico.oublier(lecon[0])
            lecons.pop(appareil, None)
            parole = f"D'accord, j'oublie ce que j'avais retenu pour « {lecon[0]} »."
            print(f"  [apprentissage annulé] {pour_console(lecon[0])}")
            journaliser(texte, "apprentissage annulé", t_stt, time.perf_counter() - t, 0.0, parole, [])
            if self.voix:
                self.voix.jouer(self.voix.synthetiser(parole))
            return parole
        trouve = self.dico.chercher(texte)
        if trouve:
            liste, parole, forme = trouve
            voie = f"dictionnaire ({forme})"
            # « Ma chambre » selon la personne qui parle (section personnes de commandes.yaml).
            liste, refus_personne, reponse_personne = self.dico.personnes.appliquer(liste, forme, personne)
            if refus_personne:
                parole, voie = refus_personne, voie + " refus personne inconnue"
            elif reponse_personne:
                parole = reponse_personne
            # Actions dynamiques (S-L4) : résolues d'après l'état des appareils, avant le contrôle de sécurité,
            # qui voit donc des actions ordinaires.
            liste, parole_vide = self.resoudre_dynamiques(liste)
            if parole_vide and not refus_personne:
                parole = parole_vide
            for a in liste:
                actions.append(resume_action(a["service"], a.get("entity_id"),
                                             {k: v for k, v in a.items() if k not in ("service", "entity_id")}))
                dom, _, srv = a["service"].partition(".")
                refus = acces.controler_service(dom, srv, {k: v for k, v in a.items() if k != "service"},
                                                personne=personne)
                if refus:
                    parole, voie = f"Je ne le fais pas : {refus}.", voie + " refus sécurité"
                    actions[-1] += " (refusé : sécurité)"
                    continue
                if not self.essai:
                    try:
                        remarque = self.executer(a, personne)
                        if remarque and "refus" not in voie and not refus_personne:
                            parole = remarque if not reponse_personne else f"{parole} {remarque}"
                    except RefusSecurite as e:
                        parole = f"Je ne le fais pas : {e}."
                        voie += " refus sécurité"
                    except NonConfirme as e:
                        parole = e.parole or f"J'ai envoyé l'ordre, mais {e} ne répond pas."
                        voie += " non confirmé"
                        actions[-1] += " (non confirmé)"
                    except Exception as e:
                        parole = "Je n'ai pas réussi à le faire, Home Assistant a refusé."
                        voie += f" erreur {e.__class__.__name__}"
            compris = True
        else:
            compris = False
        code = "essai, HA non sollicité" if self.essai else "Assist en repli seulement"
        refus_phrase = securite.phrase_protegee(texte, personne) if not compris else None
        if refus_phrase:  # parle de l'occupant protégé : jamais de LLM (il agirait sur une autre pièce)
            compris, parole, voie = True, f"Je ne le fais pas : {refus_phrase}.", "refus sécurité avant le LLM"
        if not compris:
            voie = f"llm ({code})"
            try:
                parole, actions = self.cerveau.repondre(texte)
                self.apprendre(texte, parole)
            except Exception as e:
                if str(e) == MANQUE_CLE_CLAUDE:  # 0.27.3 : la cause réelle, pas un PC soi-disant occupé
                    parole = "Je n'ai pas de clé Anthropic, Claude ne peut pas répondre."
                else:
                    parole = "Le modèle de langage ne répond pas. Le PC est peut-être occupé."
                voie += f" erreur {e.__class__.__name__} : {e}"
                # Repli Assist (S-D9) : le LLM a échoué, Assist peut tenter la phrase si le réglage l'ouvre et si
                # la sécurité laisse passer la phrase. HA exécute lui-même ses intentions : jamais en mode essai.
                if self.ha and not self.essai:
                    try:
                        compris_ha, parole_ha, code_ha = self.ha.conversation(texte, personne)
                        if compris_ha:
                            parole, voie = parole_ha or "C'est fait.", "assist (repli après échec du LLM)"
                            actions = list(getattr(self.ha, "dernieres_cibles", []))
                        else:  # coupé, refusé par la sécurité ou non compris : le motif reste au journal
                            voie += f" ; {code_ha}"
                    except Exception as e2:  # HA injoignable : la réponse d'échec reste
                        voie += f" ; repli Assist impossible {e2.__class__.__name__}"
        t_cerveau = time.perf_counter() - t
        print(f"  [{voie_courte(voie)}] {pour_console(parole)}" + (f"   actions : {'; '.join(actions)}" if actions else ""))
        t_tts = 0.0
        if self.voix and parole:
            t = time.perf_counter()
            signal = self.voix.synthetiser(parole)
            t_tts = time.perf_counter() - t
            print(f"  latences : stt {t_stt:.2f} s, cerveau {t_cerveau:.2f} s, tts {t_tts:.2f} s")
            self.voix.jouer(signal)
        else:
            print(f"  latence cerveau {t_cerveau:.2f} s")
        journaliser(texte, voie + (" [essai]" if self.essai else ""), t_stt, t_cerveau, t_tts,
                    parole, actions)
        if not trouve:
            try:
                cle, proches = candidats_proches(self.dico, texte)
                ajouter_jsonl(MANQUES, {"origine": "serveur", "texte": texte, "cle": cle, "candidats": proches,
                                        "traite_par": voie, "actions": actions, "reponse": parole,
                                        "essai": self.essai})
            except Exception as e:  # le journal des ratés ne doit jamais casser une commande
                print(f"  journal des ratés impossible : {e}")
        return parole

    def resoudre_dynamiques(self, liste):
        """Remplace les actions dynamiques d'une commande du dictionnaire par des actions ordinaires, d'après l'état
        de Home Assistant. Mode essai ou HA injoignable : aucun état lu, chaque action se résout comme pour un
        appareil dont l'état est inconnu. Renvoie (actions, réponse à dire quand il ne reste rien à faire)."""
        lues = commandes_dynamiques.entites_lues(liste)
        if not lues:
            return liste, None
        etats = {}
        if self.ha and not self.essai:
            etats = {e: self.ha.etat_brut(e) for e in lues}
        return commandes_dynamiques.resoudre_toutes(liste, etats)

    def apprendre(self, texte, parole):
        """Range dans le dictionnaire une phrase que le LLM vient de traiter avec succès.

        Demande du 12/10/2026 : ce qui est passé par le LLM une fois doit passer par le
        dictionnaire ensuite (instantané, sans LLM). Jamais en mode essai, jamais pour une question,
        un échec, ou une phrase dont l'effet dépend du moment (« encore », « éteins-la »)."""
        actions = getattr(self.cerveau, "dernieres_actions", [])
        try:
            if routines.registre().est_declencheur(texte):  # déclencheur de routine : jamais appris (note 5.3)
                return
        except Exception as e:
            print(f"  routines : déclencheurs illisibles ({e.__class__.__name__})")
        if (self.essai or not actions or NON_APPRENABLE.search(texte) or REPONSE_DOUTEUSE.search(parole or "")
                or len(texte.split()) < 2):
            return
        # Une action permise à l'occupant protégé reconnu (règle 3) ne devient jamais une phrase apprise : le
        # dictionnaire la rejouerait pour n'importe qui, et la sécurité la refuserait.
        if any(securite.protege(e) for a in actions for e in securite.cibles(a.get("entity_id"))):
            return
        if self.dico.apprendre(texte, actions, parole or "C'est fait.", maison.maintenant().strftime("%Y-%m-%d %H:%M")):
            if getattr(self, "lecons", None) is None:
                self.lecons = {}
            self.lecons[Cerveau.cle_conversation()[1]] = (texte, time.time())
            print(f"  [appris] {pour_console(texte)} sera traité directement la prochaine fois "
                  f"(dis « non » dans les {DELAI_CORRECTION:.0f} s pour l'oublier)")

    def executer(self, action, personne=None):
        """Action du dictionnaire : écrite par le propriétaire, donc pas de liste blanche."""
        domaine, service = action["service"].split(".", 1)
        corps = {k: v for k, v in action.items() if k != "service"}
        # Point de contrôle unique (0.40.0), sans liste blanche : le dictionnaire est écrit par le propriétaire.
        refus = acces.controler_service(domaine, service, corps, personne=personne)
        if refus:
            raise RefusSecurite(f"le domaine {domaine} est interdit" if refus.genre == "domaine" else refus)
        if not self.ha:
            raise RuntimeError("HA non connecté")
        r = self.ha.client.post(f"{self.ha.url}/api/services/{domaine}/{service}", json=corps)
        r.raise_for_status()
        muets = self.ha.confirmer(action["service"], corps, delai=1.5)
        if muets and muets == [self.ha.ENCEINTES_MUSIQUE.get("toutes")]:  # script de musique sans son au bout de 12 s
            raise NonConfirme("les Enceintes", "J'ai demandé la musique, mais les Enceintes ne jouent pas encore.")
        if muets:
            raise NonConfirme(", ".join(muets))
        # Musique lancée, mais pas sur toutes les enceintes du groupe : phrase toute prête.
        return phrase_manquantes(self.ha.manquantes) if self.ha.manquantes else None


JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


def date_francaise():
    """L'app HA tourne sans locale française : strftime y donnait « Tuesday 13 October », et Haiku a
    répondu en anglais le 13/10/2026 au matin. Date écrite à la main, au fuseau de la maison."""
    d = maison.maintenant()
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}, {d.hour} h {d.minute:02d}"


class RefusSecurite(Exception):
    pass


class NonConfirme(Exception):
    """HA a accepté l'ordre, mais l'appareil n'a pas pris l'état attendu (parole : phrase toute prête)."""

    def __init__(self, qui, parole=None):
        super().__init__(qui)
        self.parole = parole


class RechercheLente(Exception):
    """Music Assistant n'a pas eu la réponse de Spotify à temps (recherche vide après 7 s)."""


# Journal du serveur (0.39.0, S-F3). Deux fichiers aux rôles séparés :
# - latences.csv : durées, voie réduite à sa catégorie, rôle, issue. AUCUNE phrase, ni dite ni répondue. Rotation par
#   taille et par nombre de fichiers (latences.1.csv, latences.2.csv...).
# - assistant-AAAA-MM-JJ.jsonl : l'historique que l'appli affiche (la phrase, la réponse, ce qui a été fait), un
#   fichier par jour, supprimé au bout de journal.conserver_jours. Le filtre par rôle de serveur_satellite décide qui
#   en voit quoi.
# Valeurs de maison.json, section journal (défauts ci-dessous si la clé manque ou est absurde).
CONSERVER_JOURS_DEFAUT = 30
TAILLE_MAX_KO_DEFAUT = 512
FICHIERS_MAX_DEFAUT = 5
COLONNES_LATENCES = ["horodatage", "version", "voie", "stt_s", "cerveau_s", "tts_s", "total_s", "role", "issue",
                     "actions_nb", "essai"]
# Fonction identité -> rôle, posée par servir() (serveur_satellite). Sans elle, le rôle journalisé reste vide.
ROLE_DE = None
_PURGE = {"jour": None}
# Niveaux de vie privée du journal du client web (S-W2), un par auteur. Le niveau est lu à l'écriture et figé dans
# l'entrée : le changer n'agit pas sur les demandes déjà faites.
NIVEAUX_WEB = journal_web.Niveaux(DONNEES / "vie_privee_web.json")


def phrases_dans_la_console():
    """Vrai en diagnostic : variable JARVIS_DIAGNOSTIC ou journal.phrases_dans_la_console de maison.json. Sinon
    la sortie du serveur (qui part dans le journal de l'appli HA) ne contient pas les phrases."""
    if os.getenv("JARVIS_DIAGNOSTIC", "").strip().lower() in ("1", "true", "oui"):
        return True
    return maison.JOURNAL.get("phrases_dans_la_console") is True


def pour_console(texte):
    """Texte à afficher dans la sortie du serveur : la phrase en diagnostic, sinon sa seule longueur."""
    texte = str(texte or "")
    return texte if phrases_dans_la_console() else f"[{len(texte)} caractères]"


def voie_courte(voie):
    """Catégorie de la voie sans ce qu'elle porte entre parenthèses (la forme du dictionnaire est une phrase)."""
    return re.split(r" \(| \[| erreur| refus| non confirmé", str(voie or ""))[0].strip() or "autre"


def issue_de(voie):
    v = str(voie or "")
    if v.startswith("rien compris"):
        return "non compris"
    if " erreur" in v:
        return "erreur"
    if "refus" in v:
        return "refus"
    if "non confirmé" in v:
        return "non confirmé"
    return "ok"


def role_du_contexte(appareil):
    """Rôle de l'appareil de la requête en cours, vide si inconnu, « local » pour le micro du PC (pas d'appareil)."""
    if not appareil:
        return "local"
    if ROLE_DE is None:
        return ""
    identite = appareil if str(appareil).startswith("appareil:") else str(appareil).split("/")[0]
    try:
        return ROLE_DE(identite) or ""
    except Exception:
        return ""


def _preparer_csv(dossier):
    """Écarte un ancien latences.csv au format d'avant (il contient des phrases) et fait tourner le fichier trop gros."""
    if not JOURNAL.exists():
        return
    with open(JOURNAL, encoding="utf-8", newline="") as f:
        premiere = f.readline().strip()
    if premiere != ";".join(COLONNES_LATENCES):
        jour = maison.maintenant().strftime("%Y-%m-%d")
        cible, k = dossier / f"latences-ancien-{jour}.csv", 2
        while cible.exists():
            cible, k = dossier / f"latences-ancien-{jour}-{k}.csv", k + 1
        JOURNAL.replace(cible)
        return
    if JOURNAL.stat().st_size <= maison.entier(maison.JOURNAL, "taille_max_ko", TAILLE_MAX_KO_DEFAUT) * 1024:
        return
    garde = maison.entier(maison.JOURNAL, "fichiers_max", FICHIERS_MAX_DEFAUT)

    def nom(i):
        return JOURNAL.with_name(f"{JOURNAL.stem}.{i}{JOURNAL.suffix}")
    nom(garde).unlink(missing_ok=True)
    for i in range(garde - 1, 0, -1):
        if nom(i).exists():
            nom(i).replace(nom(i + 1))
    JOURNAL.replace(nom(1))


def appliquer_retention(dossier=None):
    """Supprime les historiques datés de plus de journal.conserver_jours jours, et les anciens latences.csv écartés.
    Une fois par jour et par processus, appelé par journaliser."""
    dossier = dossier or JOURNAL.parent
    jours = maison.entier(maison.JOURNAL, "conserver_jours", CONSERVER_JOURS_DEFAUT)
    limite = (maison.maintenant() - timedelta(days=jours)).strftime("%Y-%m-%d")
    for f in dossier.glob("assistant-????-??-??.jsonl"):
        if f.stem[len("assistant-"):] < limite:
            f.unlink(missing_ok=True)
    for f in dossier.glob("latences-ancien-*.csv"):
        if datetime.fromtimestamp(f.stat().st_mtime, maison.ZONE).strftime("%Y-%m-%d") < limite:
            f.unlink(missing_ok=True)


def etapes_de(fin, t_stt, t_cerveau, t_tts, voie, actions, parole):
    """Les étapes d'une demande reconstituées à l'écriture, avec leur heure : entendu, compris, fait, répondu.
    Les durées mesurées donnent les heures, la fin de la commande est l'instant de l'écriture. Une étape qui n'a
    pas eu lieu (pas d'action, pas de réponse) manque."""
    debut = fin - timedelta(seconds=t_stt + t_cerveau + t_tts)
    jalons = [("entendu", debut + timedelta(seconds=t_stt))]
    if not str(voie or "").startswith("rien compris"):
        jalons.append(("compris", debut + timedelta(seconds=t_stt + t_cerveau)))
    if actions:
        jalons.append(("fait", debut + timedelta(seconds=t_stt + t_cerveau)))
    if parole:
        jalons.append(("repondu", fin))
    return [{"nom": n, "t": t.strftime("%H:%M:%S")} for n, t in jalons]


def journaliser(texte, voie, t_stt, t_cerveau, t_tts, parole, actions):
    """Une commande dans les deux fichiers du journal (voir plus haut). Appareil et personne viennent de la requête
    en cours (Assistant.requete) : appeler dans le contexte d'une requête, sinon l'entrée n'a pas d'appareil.
    Un échec d'écriture ne casse jamais une commande."""
    r = REQUETE.get()
    appareil, personne = (r.appareil, r.personne) if r else (None, None)
    role = role_du_contexte(appareil)
    maintenant = maison.maintenant()
    total = t_stt + t_cerveau + t_tts
    ligne = {"horodatage": maintenant.strftime(maison.FORMAT_HORODATAGE), "texte": texte,
             "voie": voie, "total_s": f"{total:.2f}", "reponse": parole,
             "actions": " | ".join(actions), "appareil": appareil, "personne": personne,
             "role": role}
    try:
        niveau = NIVEAUX_WEB.niveau_de(journal_web.cle_auteur(personne, appareil))
    except Exception:  # un fichier de niveaux illisible ne doit pas casser la commande : le plus discret
        niveau = journal_web.NIVEAU_DEFAUT
    ligne.update({"id": ID_DEMANDE.get() or journal_web.nouvel_id(), "niveau": niveau, "statut": issue_de(voie),
                  "canal": (r.canal if r else "") or "", "etapes": etapes_de(maintenant, t_stt, t_cerveau, t_tts,
                                                                              voie, actions, parole)})
    try:
        dossier = JOURNAL.parent
        dossier.mkdir(parents=True, exist_ok=True)
        if _PURGE["jour"] != maintenant.date():
            _PURGE["jour"] = maintenant.date()
            appliquer_retention(dossier)
        _preparer_csv(dossier)
        neuf = not JOURNAL.exists()
        with open(JOURNAL, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            if neuf:
                w.writerow(COLONNES_LATENCES)
            w.writerow([maintenant.strftime(maison.FORMAT_HORODATAGE), VERSION, voie_courte(voie),
                        f"{t_stt:.2f}", f"{t_cerveau:.2f}", f"{t_tts:.2f}", f"{total:.2f}", role, issue_de(voie),
                        len(actions), 1 if "[essai]" in str(voie) else 0])
        with journal_web.VERROU_FICHIERS:
            with open(dossier / f"assistant-{maintenant.strftime('%Y-%m-%d')}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"  journal impossible : {e.__class__.__name__}")


def lire_historique(n):
    """Les n dernières entrées de l'historique (fichiers du jour puis des jours précédents), la plus récente en premier."""
    sortie = []
    for f in sorted(JOURNAL.parent.glob("assistant-????-??-??.jsonl"), reverse=True):
        try:
            lignes = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for l in reversed(lignes):
            try:
                e = json.loads(l)
            except ValueError:
                continue
            if isinstance(e, dict):
                sortie.append(e)
                if len(sortie) >= n:
                    return sortie
    return sortie


def journaliser_musique(entree):
    """Une ligne par commande de musique, dans journal/musique.jsonl et dans la sortie du serveur, donc
    dans le journal de l'appli HA (ha apps logs local_jarvis). Avant le 22/10/2026, le résultat d'une
    commande de musique n'était écrit nulle part. La demande (une phrase) n'est affichée qu'en diagnostic."""
    print(f"  [musique] {pour_console(entree.get('demande', ''))} ({entree.get('type', '')}, {entree.get('enceinte', '')})"
          f" par {entree.get('voie') or '-'} sur {entree.get('lecteur') or '-'} : {entree.get('resultat')}"
          f" en {entree.get('duree_s')} s", flush=True)
    try:
        ajouter_jsonl(MUSIQUE, entree)
    except Exception as e:  # le journal ne doit jamais casser une commande
        print(f"  journal de musique impossible : {e}")


def ajouter_jsonl(chemin, entree):
    chemin.parent.mkdir(exist_ok=True)
    entree = {"horodatage": maison.maintenant().strftime(maison.FORMAT_HORODATAGE), "version": VERSION, **entree}
    with open(chemin, "a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")


def lire_jsonl(chemin, n=200):
    if not chemin.exists():
        return []
    lignes = chemin.read_text(encoding="utf-8").splitlines()[-n:]
    sortie = []
    for l in lignes:
        try:
            sortie.append(json.loads(l))
        except json.JSONDecodeError:
            pass
    return sortie


def candidats_proches(dico, texte, n=5):
    """Les phrases du dictionnaire les plus proches, pour comprendre un raté."""
    from dictionnaire import normaliser, mots_compatibles
    cle = normaliser(texte)
    notes = sorted(((difflib.SequenceMatcher(None, f, cle).ratio(), f) for f in dico.formes), reverse=True)[:n]
    return cle, [{"cle": f, "ressemblance": round(r, 2), "compatible": mots_compatibles(cle, f),
                  "appris": "appris_le" in dico.formes[f][0]} for r, f in notes]


def main():
    p = argparse.ArgumentParser(description="Assistant vocal local, POC")
    p.add_argument("--version", action="store_true")
    p.add_argument("--reveil", action="store_true", help="mot de réveil de la configuration (« Hey Jarvis » sans son modèle)")
    p.add_argument("--clavier", action="store_true", help="commandes tapées, sans micro")
    p.add_argument("--texte", help="traite une seule commande écrite")
    p.add_argument("--essai", action="store_true", help="n'exécute rien, montre la voie choisie")
    p.add_argument("--claude", action="store_true", help="cerveau Claude par API au lieu du LLM local")
    a = p.parse_args()
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if not sys.stdin.isatty():  # texte reçu par tuyau : UTF-8, pas l'ancien encodage Windows
        sys.stdin.reconfigure(encoding="utf-8")
    print(f"Assistant vocal local v{VERSION} ({DATE_VERSION})")
    if a.version:
        return
    cfg = charger_env()
    if a.claude:
        cfg["llm_fournisseur"] = "claude"
    if a.texte or a.clavier:
        assistant = Assistant(cfg, avec_audio=False, essai=a.essai)
        if a.texte:
            assistant.traiter(a.texte)
            return
        while (ligne := input("\nVous > ").strip()):
            assistant.traiter(ligne)
        return

    activer_couleurs()
    assistant = Assistant(cfg, essai=a.essai)
    oreille = Oreille(cfg["micro"])
    reveil = Reveil(cfg["micro"]) if a.reveil else None
    print("  calibrage du bruit ambiant, silence une seconde...")
    oreille.calibrer()
    print(f"  bruit de fond {oreille.bruit:.4f}, seuil de parole {oreille.seuil:.4f} (le | du vumètre)")
    print(f"  prêt. {f'Dites « {reveil.nom} »' if reveil else 'Entrée, attendez le bip aigu, puis parlez'}."
          " Bip grave : j'ai fini d'écouter. Ctrl+C pour quitter.")
    try:
        while True:
            if reveil:
                reveil.attendre(oreille.seuil)
            else:
                input(f"\n{GRIS}[Entrée pour parler]{RAZ} ")
            assistant.voix.bip(880)
            signal = oreille.ecouter_phrase()
            if signal is None:
                print(f"  {GRIS}(rien entendu, rien envoyé){RAZ}")
                continue
            assistant.voix.bip(440)
            etat("je réfléchis...", JAUNE)
            t = time.perf_counter()
            texte = assistant.stt.transcrire(signal)
            t_stt = time.perf_counter() - t
            fin_etat()
            print(f"  Vous ({len(signal) / TAUX:.1f} s) : {pour_console(texte)}")
            if texte:
                assistant.traiter(texte, t_stt)
    except KeyboardInterrupt:
        print("\nAu revoir.")


if __name__ == "__main__":
    main()
