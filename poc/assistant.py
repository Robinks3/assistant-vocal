"""Assistant vocal local, POC.

Micro -> Canary 1B v2 en français (STT, CPU) -> dictionnaire de commandes (commandes.yaml de la configuration)
-> intentions locales de Home Assistant
-> sinon LLM (llama-server local ou Claude) avec outils HA -> Piper (TTS) -> haut-parleurs.

Usage :
  python poc/assistant.py               appui sur Entrée pour parler
  python poc/assistant.py --reveil      mot de réveil « Hey Jarvis »
  python poc/assistant.py --clavier     commandes tapées au clavier (sans micro)
  python poc/assistant.py --texte "allume la lumière"   une seule commande
  ajouter --essai : affiche ce qui serait fait, sans rien exécuter
  python poc/assistant.py --version
"""
import argparse, contextlib, contextvars, difflib, csv, json, os, re, sys, time

import acces
import maison
import securite
from datetime import datetime
from pathlib import Path


class Requete:
    """Ce qui vaut le temps d'une commande : essai effectif, personne qui parle, appareil d'origine.

    Porté par une variable de contexte et non plus par les objets partagés (0.28.0) : une commande du
    client web et une phrase de la tablette ne se prennent plus leur essai ni leur personne.
    asyncio.to_thread copie le contexte, la requête suit donc la commande dans son fil."""

    def __init__(self, essai=False, personne=None, appareil=None, indication=""):
        self.essai, self.personne, self.appareil, self.indication = bool(essai), personne or None, appareil, indication


REQUETE = contextvars.ContextVar("requete", default=None)


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

VERSION = "0.35.0"
DATE_VERSION = "2026-10-26"

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

# Domaines et services que le LLM a le droit d'appeler. Rien qui ouvre une porte
# ou désarme une alarme.
SERVICES_PERMIS = {
    "light": {"turn_on", "turn_off", "toggle"},
    "switch": {"turn_on", "turn_off", "toggle"},
    "fan": {"turn_on", "turn_off", "toggle", "set_percentage"},
    "cover": {"open_cover", "close_cover", "stop_cover", "set_cover_position"},
    "climate": {"set_temperature", "set_hvac_mode", "turn_on", "turn_off"},
    "media_player": {"turn_on", "turn_off", "media_play", "media_pause", "media_stop",
                     "media_next_track", "media_previous_track", "volume_set",
                     "volume_mute", "volume_down", "select_source"},
    "music_assistant": {"play_media"},
    "vacuum": {"start", "pause", "stop", "return_to_base", "locate"},
    "scene": {"turn_on"},
    "script": {"turn_on"},
    "input_boolean": {"turn_on", "turn_off", "toggle"},
    "button": {"press"},
    # Réglages fins de la télé téléviseur et des lampes (0.30.0) : pour l'appli et la passerelle, jamais pour le LLM
    # (DOMAINES_HORS_LLM : hors enum de l'outil, hors contexte, refusés à l'appel).
    "domaine_tele": {"launch_app", "send_text_input", "set_picture_setting"},
    "remote": {"send_command"},
    "select": {"select_option"},
}
DOMAINES_HORS_LLM = {"domaine_tele", "remote", "select"}
# Monter le son par pas (volume_up) passerait au-dessus d'un plafond de volume : permis au LLM seulement
# quand la configuration n'en règle aucun (securite.plafond_volume à 100, le défaut).
if not securite.plafond_actif():
    SERVICES_PERMIS["media_player"].add("volume_up")
# Les boutons (36 chez aspirateur) gonflent le prompt sans servir à la voix.
# Ni boutons ni interrupteurs : dans la maison d'origine, ce sont des réglages (enceintes, aspirateur) qui embrouillent
# Qwen 9B (« Lecture automatique TV » pris pour la télé, banc du 12/10). Le dictionnaire les couvre.
DOMAINES_CONTEXTE = sorted((set(SERVICES_PERMIS) - ({"button", "switch"} | DOMAINES_HORS_LLM)) | {"sensor", "binary_sensor", "weather"})


def charger_env():
    from dotenv import load_dotenv
    load_dotenv(ICI / ".env")
    return {
        "ha_url": os.getenv("HA_URL", maison.reseau("ha_url")).rstrip("/"),
        "ha_token": os.getenv("HA_TOKEN", "").strip(),
        "llm_url": os.getenv("LLM_URL", "http://127.0.0.1:8080/v1").rstrip("/"),
        "llm_modele": os.getenv("LLM_MODELE", "assistant-vocal"),
        "micro": os.getenv("MICRO", "fifine"),
        "sortie": os.getenv("SORTIE", ""),
        "voix": os.getenv("VOIX", str(ICI / "voix" / "fr_FR-siwis-medium.onnx")),
        "llm_fournisseur": os.getenv("LLM_FOURNISSEUR", "local").strip().lower(),
        "claude_modele": os.getenv("CLAUDE_MODELE", "claude-haiku-5-5"),
    }


# ---------------------------------------------------------------- audio
def trouver_peripherique(nom, entree):
    import sounddevice as sd
    if not nom:
        return None
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


def modele_reveil():
    """Modèle du mot de réveil, variable MOT_REVEIL de poc/.env : « hey_jarvis » (anglais, par défaut) ou
    un mot dont le modèle openWakeWord est rangé dans reveil/<mot>.onnx du dossier de configuration. Le nom
    affiché vient de la section reveil de maison.json quand elle décrit ce mot (l'appli ne propose que ce
    mot-là : un MOT_REVEIL sans section reveil est annoncé, mais l'appli affiche alors Hey Jarvis). Renvoie (argument pour openWakeWord, nom affiché)."""
    nom = os.getenv("MOT_REVEIL", "hey_jarvis").strip().lower()
    fichier = maison.DOSSIER / "reveil" / f"{nom}.onnx"
    if nom != "hey_jarvis" and fichier.exists():
        reveil = maison.CONFIG.get("reveil") or {}
        affiche = str(reveil.get("nom") or "") if str(reveil.get("mot") or "").strip().lower() == nom else ""
        return str(fichier), affiche or nom.capitalize()
    return "hey_jarvis", "Hey Jarvis"


class Reveil:
    """Mot de réveil openWakeWord (modèle de MOT_REVEIL, « hey jarvis » par défaut)."""

    def __init__(self, micro, seuil=0.5):
        import openwakeword
        from openwakeword.model import Model
        modele, self.nom = modele_reveil()
        if modele == "hey_jarvis":
            openwakeword.utils.download_models(["hey_jarvis"])
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


class Voix:
    def __init__(self, chemin, sortie):
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
        self.personne = None

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
        """Qui parle, d'après la tablette (champ « personne », règle 3 de securite.py)."""
        r = REQUETE.get()
        return r.personne if r else getattr(self, "_personne", None)

    @personne.setter
    def personne(self, valeur):
        self._personne = valeur

    def conversation(self, texte):
        """Intentions locales de HA (agent intégré, aucun LLM)."""
        if securite.SECURITE_ACTIVE:
            # Assist agit sans qu'on voie sa cible avant : sauté tant que la sécurité est en dur.
            self.dernieres_cibles = []
            return False, "", "Assist sauté (sécurité)"
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

    def service(self, domaine, service, entity_id=None, donnees=None, confirmer=True):
        """Service demandé par le LLM ou rejoué par une routine (confirmer=False : pas d'attente
        de l'état, la routine enchaîne ses étapes)."""
        if domaine in acces.DOMAINES_INTERDITS:
            return {"erreur": f"refusé : domaine {domaine} interdit. Ne réessaie pas autrement, dis-le simplement."}
        if service not in SERVICES_PERMIS.get(domaine, set()):
            permis = ", ".join(sorted(SERVICES_PERMIS.get(domaine, set()))) or "aucun"
            return {"erreur": f"service {domaine}.{service} inexistant ou interdit. "
                              f"Services permis pour {domaine} : {permis}. "
                              "Luminosité : light.turn_on avec donnees {\"brightness_pct\": N}."}
        corps = dict(donnees or {})
        if entity_id:
            corps["entity_id"] = entity_id
        refus = (acces.refus_launch_app(f"{domaine}.{service}", corps)
                 or securite.verifier(f"{domaine}.{service}", corps, personne=self.personne))
        if refus:  # sécurité en dur (occupant protégé, son la nuit), même en essai
            return {"erreur": f"refusé : {refus}. Ne réessaie pas autrement, dis-le simplement."}
        inconnues = [e for e in securite.cibles(entity_id) if self.entites_llm and e not in self.entites_llm]
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
        LLM, qui fait deux tours autour de l'outil."""
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
        refus = securite.verifier("music_assistant.play_media", {"entity_id": cible}, personne=self.personne)
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
            "domaine": {"type": "string", "enum": sorted(set(SERVICES_PERMIS) - DOMAINES_HORS_LLM)},
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

# Outils proposés au LLM selon le mode du tour (0.28.0). Un appel à un outil absent de la liste du tour
# n'est jamais exécuté : il reçoit « outil indisponible » (aiguillage fermé, note des routines 3.1).
MODES_OUTILS = {"commande": ("appeler_service", "jouer_musique", "lire_etat")}
INDISPONIBLE = {"erreur": "outil indisponible"}


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
    outils = copy.deepcopy([o for o in OUTILS if nom_outil(o) in noms])
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
# Parties propres à la maison (section llm de maison.json) : lieu, consignes en plus, une par ligne.
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


CONSIGNE = (CONSIGNE.replace("@LIEU@", _sans_accolades(LLM_MAISON.get("lieu") or "la maison"))
            .replace("@SCRIPT_LANCER@", _sans_accolades(SCRIPT_LANCER))
            .replace("@PLAFOND@", consigne_plafond())
            .replace("@CONSIGNES@", "".join(_sans_accolades(c) + "\n" for c in LLM_MAISON.get("consignes") or [])))


class Cerveau:
    def __init__(self, cfg, ha):
        import httpx
        self.cfg, self.ha = cfg, ha
        self.client = httpx.Client(timeout=60)
        # Une conversation par personne et par appareil (0.28.0) : « éteins-la » de l'un ne vise jamais
        # ce dont parlait l'autre, même quand deux commandes se croisent.
        self.historiques = {}  # clé -> (heure du dernier échange, messages)
        self.dernieres_actions = []  # actions réussies de la dernière réponse, au format du dictionnaire

    @staticmethod
    def cle_conversation():
        r = REQUETE.get()
        return (r.personne, r.appareil) if r else (None, None)

    @property
    def indication_personne(self):
        """Qui parle et ce que désigne « ma chambre », ajouté à la demande (Assistant.requete)."""
        r = REQUETE.get()
        return r.indication if r else ""

    @property
    def historique(self):
        t, messages = self.historiques.get(self.cle_conversation(), (0.0, []))
        return [] if time.time() - t > 120 else messages  # conversation oubliée après 2 min de silence

    @historique.setter
    def historique(self, messages):
        self.historiques[self.cle_conversation()] = (time.time(), list(messages)[-6:])

    def executer_outil(self, nom, args, texte, noms, actions, musiques):
        """Aiguillage fermé : seul un outil de la liste du tour s'exécute, tout autre nom reçoit
        « outil indisponible » (un appel halluciné ou soufflé par la phrase n'agit jamais)."""
        if nom not in noms or not self.ha:
            return dict(INDISPONIBLE)
        if nom == "appeler_service":
            if args.get("domaine") in DOMAINES_HORS_LLM:
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
        if nom == "lire_etat":
            demande = args.get("entity_id", "")
            if not isinstance(demande, str) or demande not in self.ha.entites_llm:  # même liste que l'enum du schéma, que le LLM peut contourner
                return {"erreur": f"refusé : {demande} n'est pas dans l'inventaire des appareils permis"}
            return self.ha.etat(demande)
        return dict(INDISPONIBLE)

    def repondre(self, texte, mode="commande"):
        historique = self.historique
        liste, etats = self.ha.inventaire() if self.ha else ("(Home Assistant non connecté)", "")
        jour = date_francaise()
        # Tout ce qui change (date, états) va dans le dernier message : le début reste en cache.
        messages = [{"role": "system", "content": CONSIGNE.format(inventaire=liste)}]
        probables = presélection(texte, liste)
        indice = f" Appareils probables pour cette demande : {probables}." if probables else ""
        messages += historique + [{"role": "user", "content":
                                   f"[Nous sommes le {jour}.{self.indication_personne} États actuels : {etats}{indice} Réponds en français.]\n\n{texte}"}]
        actions, relance = [], False
        self.dernieres_actions = []
        musiques = []  # résultats de jouer_musique, pour garde_fou_musique
        outils = outils_avec_entites(self.ha.entites_llm, mode) if self.ha else []
        noms = {nom_outil(o) for o in outils}
        for _ in range(6):
            corps = {"cache_prompt": True, "model": self.cfg["llm_modele"], "messages": messages,
                     "temperature": 0, "max_tokens": 300,
                     "chat_template_kwargs": {"enable_thinking": False}}
            if outils:
                corps["tools"] = outils
            r = self.client.post(f"{self.cfg['llm_url']}/chat/completions", json=corps)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            appels = msg.get("tool_calls") or []
            if not appels:
                reponse = nettoyer(msg.get("content") or "")
                # Qwen annonce « je vais éteindre », affirme « j'ai allumé » ou refuse à tort
                # (« déjà allumée » alors qu'elle est éteinte) sans appeler l'outil (vu les 11 et
                # 12/10). Une relance, une seule, avec l'état réel sous les yeux.
                if ("appeler_service" in noms and not actions and not relance and re.search(
                        r"\bje (vais|peux|m'en occupe|lance|allume|éteins|coupe)|\bj'ai (allumé|éteint|lancé|coupé|mis|réglé|baissé|monté)"
                        r"|je ne peux pas|déjà (allumée?|éteinte?)|pas trouvé|n'est pas dans la liste", reponse, re.I)):
                    relance = True
                    messages += [{"role": "assistant", "content": reponse},
                                 {"role": "user", "content": "Tu n'as appelé aucun outil, donc rien n'a été fait. "
                                  f"Rappel des appareils actifs : {etats} Si ma demande est une action, appelle "
                                  f"appeler_service maintenant avec l'entity_id exact de la liste (la télé est {TELE}). "
                                  "Sinon réponds simplement."}]
                    continue
                break
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": appels})
            for a in appels:
                try:
                    args = json.loads(a["function"].get("arguments") or "{}")
                except ValueError:
                    args = None
                res = (self.executer_outil(a["function"].get("name"), args, texte, noms, actions, musiques)
                       if isinstance(args, dict) else {"erreur": "arguments illisibles"})
                messages.append({"role": "tool", "tool_call_id": a["id"],
                                 "content": json.dumps(res, ensure_ascii=False)})
        else:
            reponse = "Je n'ai pas réussi à terminer cette demande."
        reponse = garde_fou_musique(reponse, musiques)
        self.historique = historique + [{"role": "user", "content": texte},
                                        {"role": "assistant", "content": reponse}]
        return reponse, actions


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
    La clé est lue dans ANTHROPIC_API_KEY (poc/.env), jamais affichée."""

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
        historique = self.historique
        liste, etats = self.ha.inventaire() if self.ha else ("(Home Assistant non connecté)", "")
        jour = date_francaise()
        probables = presélection(texte, liste)
        indice = f" Appareils probables pour cette demande : {probables}." if probables else ""
        systeme = [{"type": "text", "text": CONSIGNE.format(inventaire=liste),
                    "cache_control": {"type": "ephemeral"}}]
        messages = list(historique) + [{"role": "user", "content":
                                         f"[Nous sommes le {jour}.{self.indication_personne} États actuels : {etats}{indice} Réponds en français.]\n\n{texte}"}]
        actions, reponse = [], ""
        self.dernieres_actions = []
        musiques = []  # résultats de jouer_musique, pour garde_fou_musique
        outils = self.outils_du_mode(mode)
        noms = {o["name"] for o in outils}
        for _ in range(6):
            t = time.perf_counter()
            r = self.client.messages.create(
                model=self.modele, max_tokens=1024, system=systeme, messages=messages,
                tools=outils, thinking={"type": "disabled"})
            u = r.usage
            self.mesures.append((time.perf_counter() - t, u.input_tokens,
                                 getattr(u, "cache_read_input_tokens", 0) or 0, u.output_tokens))
            if r.stop_reason == "refusal":
                reponse = "Je ne peux pas traiter cette demande."
                break
            appels = [b for b in r.content if b.type == "tool_use"]
            if not appels:
                reponse = nettoyer(" ".join(b.text for b in r.content if b.type == "text"))
                break
            messages.append({"role": "assistant", "content": r.content})
            resultats = []
            for b in appels:
                res = self.executer_outil(b.name, dict(b.input or {}), texte, noms, actions, musiques)
                resultats.append({"type": "tool_result", "tool_use_id": b.id,
                                  "content": json.dumps(res, ensure_ascii=False),
                                  **({"is_error": True} if "erreur" in res else {})})
            messages.append({"role": "user", "content": resultats})
        else:
            reponse = "Je n'ai pas réussi à terminer cette demande."
        reponse = garde_fou_musique(reponse, musiques)
        self.historique = historique + [{"role": "user", "content": texte},
                                        {"role": "assistant", "content": reponse or "..."}]
        return reponse, actions


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
        else:
            print("  ! HA_TOKEN absent de poc/.env : pilotage de la maison désactivé, LLM seul.")
        if cfg.get("llm_fournisseur") == "claude":
            self.cerveau = CerveauClaude(cfg, self.ha)
            print(f"  cerveau : Claude ({cfg['claude_modele']}) par API")
        else:
            self.cerveau = Cerveau(cfg, self.ha)
            print("  cerveau : Qwen3.5-9B local (llama-server)")
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
    def requete(self, essai=None, personne=None, appareil=None):
        """Le temps d'une commande : essai, personne qui parle et appareil, pour la sécurité, l'inventaire,
        la consigne et l'historique. Rien n'est écrit sur les objets partagés."""
        if essai is None:
            essai = getattr(self, "_essai", False)
        jeton = REQUETE.set(Requete(essai, personne, appareil, self.indication(personne)))
        try:
            yield
        finally:
            REQUETE.reset(jeton)

    def traiter(self, texte, t_stt=0.0, personne=None, appareil=None, essai=None):
        with self.requete(essai=essai, personne=personne, appareil=appareil):
            return self._traiter(texte, t_stt, personne)

    def _traiter(self, texte, t_stt, personne):
        from dictionnaire import epurer
        t = time.perf_counter()
        voie, actions = "ha", []
        texte = epurer(texte)  # « est-ce que tu peux éteindre » devient « éteindre »
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
            print(f"  [apprentissage annulé] {lecon[0]}")
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
            for a in liste:
                actions.append(resume_action(a["service"], a.get("entity_id"),
                                             {k: v for k, v in a.items() if k not in ("service", "entity_id")}))
                refus = securite.verifier(a["service"], {k: v for k, v in a.items() if k != "service"}, personne=personne)
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
        try:
            if self.essai and not compris:  # HA exécute ses intentions : on passe au LLM simulé
                code = "essai, HA non sollicité"
            elif not compris:
                compris, parole, code = self.ha.conversation(texte) if self.ha else (False, "", "sans_ha")
                if compris and self.ha:
                    actions = list(getattr(self.ha, "dernieres_cibles", []))
        except Exception as e:  # HA injoignable : le LLM prend le relais
            compris, parole, code = False, "", f"ha_injoignable {e.__class__.__name__}"
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
        t_cerveau = time.perf_counter() - t
        print(f"  [{voie}] {parole}" + (f"   actions : {'; '.join(actions)}" if actions else ""))
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

    def apprendre(self, texte, parole):
        """Range dans le dictionnaire une phrase que le LLM vient de traiter avec succès.

        Demande du 12/10/2026 : ce qui est passé par le LLM une fois doit passer par le
        dictionnaire ensuite (instantané, sans LLM). Jamais en mode essai, jamais pour une question,
        un échec, ou une phrase dont l'effet dépend du moment (« encore », « éteins-la »)."""
        actions = getattr(self.cerveau, "dernieres_actions", [])
        if (self.essai or not actions or NON_APPRENABLE.search(texte) or REPONSE_DOUTEUSE.search(parole or "")
                or len(texte.split()) < 2):
            return
        # Une action permise à l'occupant protégé reconnu (règle 3) ne devient jamais une phrase apprise : le
        # dictionnaire la rejouerait pour n'importe qui, et la sécurité la refuserait.
        if any(securite.protege(e) for a in actions for e in securite.cibles(a.get("entity_id"))):
            return
        if self.dico.apprendre(texte, actions, parole or "C'est fait.", datetime.now().strftime("%Y-%m-%d %H:%M")):
            if getattr(self, "lecons", None) is None:
                self.lecons = {}
            self.lecons[Cerveau.cle_conversation()[1]] = (texte, time.time())
            print(f"  [appris] « {texte} » sera traité directement la prochaine fois "
                  f"(dis « non » dans les {DELAI_CORRECTION:.0f} s pour l'oublier)")

    def executer(self, action, personne=None):
        """Action du dictionnaire : écrite par le propriétaire, donc pas de liste blanche."""
        domaine, service = action["service"].split(".", 1)
        if domaine in acces.DOMAINES_INTERDITS:  # même sur la voie du dictionnaire (0.28.0)
            raise RefusSecurite(f"le domaine {domaine} est interdit")
        corps = {k: v for k, v in action.items() if k != "service"}
        refus = securite.verifier(action["service"], corps, personne=personne)
        if refus:
            raise RefusSecurite(refus)
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
    d = datetime.now(securite.FUSEAU)
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


def journaliser(texte, voie, t_stt, t_cerveau, t_tts, parole, actions):
    JOURNAL.parent.mkdir(exist_ok=True)
    neuf = not JOURNAL.exists()
    with open(JOURNAL, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        if neuf:
            w.writerow(["horodatage", "version", "texte", "voie", "stt_s", "cerveau_s", "tts_s",
                        "total_s", "reponse", "actions"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), VERSION, texte, voie,
                    f"{t_stt:.2f}", f"{t_cerveau:.2f}", f"{t_tts:.2f}",
                    f"{t_stt + t_cerveau + t_tts:.2f}", parole, " | ".join(actions)])


def journaliser_musique(entree):
    """Une ligne par commande de musique, dans journal/musique.jsonl et dans la sortie du serveur, donc
    dans le journal de l'appli HA (ha apps logs local_jarvis). Avant le 22/10/2026, le résultat d'une
    commande de musique n'était écrit nulle part."""
    print(f"  [musique] « {entree.get('demande', '')} » ({entree.get('type', '')}, {entree.get('enceinte', '')})"
          f" par {entree.get('voie') or '-'} sur {entree.get('lecteur') or '-'} : {entree.get('resultat')}"
          f" en {entree.get('duree_s')} s", flush=True)
    try:
        ajouter_jsonl(MUSIQUE, entree)
    except Exception as e:  # le journal ne doit jamais casser une commande
        print(f"  journal de musique impossible : {e}")


def ajouter_jsonl(chemin, entree):
    chemin.parent.mkdir(exist_ok=True)
    entree = {"horodatage": datetime.now().isoformat(timespec="seconds"), "version": VERSION, **entree}
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
    p.add_argument("--reveil", action="store_true", help="mot de réveil « Hey Jarvis »")
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
    print(f"  prêt. {'Dites « Hey Jarvis »' if reveil else 'Entrée, attendez le bip aigu, puis parlez'}."
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
            print(f"  Vous ({len(signal) / TAUX:.1f} s) : {texte}")
            if texte:
                assistant.traiter(texte, t_stt)
    except KeyboardInterrupt:
        print("\nAu revoir.")


if __name__ == "__main__":
    main()
