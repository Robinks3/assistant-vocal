"""Serveur des satellites vocaux (téléphone téléphone posé dans un coin).

Le téléphone envoie le son de son micro en continu (PCM 16 bits, 16 kHz, mono) par WebSocket.
Le serveur guette le mot de réveil (openWakeWord, section reveil de maison.json, sinon le modèle de repli),
découpe la phrase qui suit, la passe dans la chaîne du POC (Canary, dictionnaire, HA, LLM) et renvoie la réponse en WAV
(voix Piper). Le téléphone la joue, puis signale la fin de lecture pour que le serveur se
remette à écouter sans se déclencher sur sa propre voix.

Messages texte (JSON) envoyés au téléphone :
  {"etat": "repos"}                         guette le mot de réveil
  {"etat": "ecoute"}                        mot entendu, parlez (le téléphone bipe)
  {"etat": "reflexion", "texte": "..."}     phrase transcrite, traitement en cours
  {"etat": "reponse", "texte", "reponse", "voie"}   puis un message binaire WAV
  {"etat": "niveau", "score": 0.42}         score du mot de réveil quand il dépasse 0,2
Messages texte reçus du téléphone :
  {"type": "lecture_finie"}   la réponse a fini d'être jouée
  {"type": "parler"}          bouton « Parler » : comme si le mot avait été dit
  {"type": "llm", "texte", "essai"}  phrase transcrite sur l'appareil que ni son dictionnaire ni
                              Assist n'ont comprise : réponse {"etat":"llm","reponse","actions","cerveau","ms","erreur"}
  {"type": "manque", ...}      raté du dictionnaire sur un appareil, ajouté à journal/manques.jsonl
  {"type": "retour", "verdict": "bien"|"mauvais", "entendu", "compris_par", ...}  note du propriétaire,
                              journal/retours.jsonl, phrase apprise oubliée si mauvaise
  {"type": "manques", "n"}    lecture des deux journaux, manques et retours
  {"type": "reveil", "score"} mot de réveil détecté sur le téléphone (appli 0.9.0+) : le téléphone
                              n'envoie alors le son que pendant l'écoute d'une phrase

Depuis 0.17.0 (idées d'un projet d'inspiration, voir acces.py) :
  {"type": "ha", "id", "methode", "chemin", "corps"}  passerelle vers Home Assistant pour le mode
                              « Cet appareil », réponse {"etat":"ha","id","code","corps"} (texte brut), ou
                              pour une image (pochette, GET /api/media_player_proxy/...) {"type","base64"}
  {"type": "appareils"}       liste des téléphones et des demandes d'appairage {"etat":"appareils",...}
  {"type": "appairer"|"refuser_appareil"|"revoquer", "id"}   gestion des appareils ("appairer" accepte "role",
                              "changer_role" {"id","role"} ; "inviter" et "annuler_invitation" : page d'administration seule)
  {"etat": "appairage_demande", "id", "nom", "code"}  diffusé aux téléphones connus quand un nouveau
                              téléphone demande l'accès
  {"etat": "repos", "raison": "arbitre"}  un autre téléphone a mieux entendu le mot de réveil
Depuis 0.18.0 (serveur du PC seulement, capacité "vision") :
  {"type": "transcrire", "id", "pcm": base64, "moteur"?}  (0.18.4) phrase découpée par la tablette,
                              transcrite ici, réponse {"etat":"transcrit","id","texte","moteur","ms"} ou "erreur"
  {"type": "vision", "id", "jpeg": base64}  image de la caméra d'une tablette, réponse
                              {"etat":"vision","id","ms","largeur","hauteur","visages":[{boite,score,
                              points,regard,lacet,empreinte}]}, rien n'est gardé sur le serveur
Depuis 0.19.0 :
  passerelle {"type": "ha"} : POST /api/services/weather/get_forecasts?return_response permis, ce
                              chemin exact seulement, corps exactement {"entity_id": "weather.<nom>",
                              "type": "hourly"|"daily"|"twice_daily"} (capacité "previsions", vraie si
                              Home Assistant est configuré)
  {"type": "sante", "id"}     (serveur du PC seulement) résumé de sante-api pour l'écran, réponse
                              {"etat":"sante","id","donnees":{date, lu_a, aujourdhui, nuit, jours,
                              seances}} ou {"etat":"sante","id","erreur"}. Seulement sur la liaison
                              chiffrée et pour une clé de SANTE_PERSONNES (le propriétaire par défaut, voir
                              sante.py), sinon refus sans appel à sante-api. La capacité "sante" est
                              calculée pour chaque connexion. Forme détaillée de donnees dans sante.py.
                              Cache de 10 min en mémoire, rien sur disque.
Depuis 0.20.0 (serveur du PC seulement, capacité "sante_historique", même contrôle d'accès que "sante") :
  {"type": "sante_periode", "id", "jours": 7|30|90|365}   onglet Tendances
  {"type": "sante_seances", "id", "jours", "sport": "tous"|"course"|"course"|...}   onglet Séances
  {"type": "sante_seance", "id", "seance_id"}   détail d'une séance, avec l'analyse écrite du jour
  {"type": "sante_records", "id"}               onglet Records
  {"type": "sante_jour", "id", "date": "AAAA-MM-JJ"}   vue Jour, avec l'hypnogramme de la nuit
                              Réponse {"etat": <type>, "id", "donnees"} ou {"etat": <type>, "id",
                              "erreur"}. Lu dans le data-auto.js du tableau de bord HealthStats, forme
                              détaillée de donnees dans sante_hist.py. Rien sur disque.
Depuis 0.22.0 (deux profils, capacité "meteo_mer", avec une section « mer » active dans maison.json,
éteinte par METEO_MER=0) :
  {"type": "meteo_mer", "id"}  page « Mer » du panneau Météo : prévisions marines du plan d'eau sur les
                              points en mer de la configuration, réponse {"etat":"meteo_mer","id",
                              "donnees":{lu_a, points, eau, soleil, station, erreurs}} ou {"etat":
                              "meteo_mer","id","erreur"}. Sources publiques, aucune donnée personnelle :
                              servi à toute connexion. Forme détaillée de donnees dans meteo_mer.py.
Depuis 0.24.0 (deux profils, capacité "vent_mesure", avec les sections « mer » et « vent » actives,
éteinte par VENT_MESURE=0) :
  {"type": "vent_mesure", "id"}  page « Vent mesuré » : mesures réelles de vent (balises Balises,
                              stations StationsOfficielles nommées et amateurs, station à terre de la configuration),
                              réponse {"etat":"vent_mesure","id","donnees":{lu_a, stations, erreurs}} ou
                              {"etat":"vent_mesure","id","erreur"} si aucune source n'a jamais rien
                              donné. Sources publiques, aucune donnée personnelle : servi à toute
                              connexion. Forme détaillée de donnees dans vent_mesure.py.
Appairage d'un nouveau téléphone : wss://<hôte>:8766/appairage?nom=<nom>, sans jeton. Le serveur
envoie {"etat":"appairage","code"}, puis {"etat":"appaire","jeton"} quand un téléphone connu accepte,
ou {"etat":"appairage_refuse"}. Sans administrateur connecté et depuis le réseau local, le message `appairage`
porte "amorcage": true : le téléphone envoie {"type":"amorcage","code"} avec le code à 8 chiffres du journal du
serveur, réponse {"etat":"amorcage_refuse","restant"} si le code est faux.

Usage : python poc/serveur_satellite.py [--essai] [--port 8765] [--port-tls 8766] [--seuil 0.5]
Connexion : wss://<IP>:8766/ avec l'en-tête « Authorization: Bearer <jeton> » (ou, tant que
JARVIS_ANCIEN_ACCES=1, l'ancienne forme ws://<IP>:8765/?jeton=<jeton>)
"""
import argparse, asyncio, io, json, os, re, ssl, sys, time, wave
from urllib.parse import parse_qs, urlparse

import numpy as np
import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assistant as A  # noqa: E402
import acces  # noqa: E402
import administration  # noqa: E402
import maison  # noqa: E402
import vad as V  # noqa: E402
import vision as VI  # noqa: E402
import sante as SA  # noqa: E402
import sante_hist as SH  # noqa: E402
import meteo_mer as MM  # noqa: E402
import vent_mesure as VM  # noqa: E402

TAUX = 16000
BLOC = 1280            # 80 ms, taille attendue par openWakeWord
SILENCE_FIN = 0.8      # secondes de silence qui terminent la phrase (seuil d'énergie)
SILENCE_FIN_VAD = 0.45  # avec Silero VAD, qui ne confond pas un souffle ou la télé avec la parole
ATTENTE_MAX = 6.0      # secondes pour commencer à parler après le mot
DUREE_MAX = 12.0


def wav_de(signal_int16, taux):
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taux)
        w.writeframes(signal_int16.astype(np.int16).tobytes())
    return tampon.getvalue()


def causes_vent_eteint():
    """Toutes les raisons pour lesquelles le vent mesuré est éteint, pour la ligne du démarrage (0.27.3)."""
    if not (VM.ACTIF and MM.ACTIF):
        return "pas de sections « mer » et « vent » actives dans maison.json"
    causes = [n for n, eteint in (("METEO_MER=0", MM.eteinte_par_env()), ("VENT_MESURE=0", VM.eteint_par_env()))
              if eteint]
    return " et ".join(causes) or "raison inconnue"


class Moteur:
    """Ressources partagées entre les satellites : chargées une seule fois."""

    def __init__(self, essai):
        cfg = A.charger_env()
        self.cfg = cfg
        self.assistant = A.Assistant(cfg, avec_audio=False, essai=essai)
        # Profil « pc » : Canary, Piper et openWakeWord tournent ici. Profil « ha » (appli Home
        # Assistant sur le petit serveur) : aucun modèle local, tout passe par les applis Wyoming de HA.
        self.profil = profil()
        if self.profil == "pc":
            t = time.perf_counter()
            self.stt = A.Transcripteur()
            self.voix = A.Voix(cfg["voix"], "")
            print(f"  transcription et voix chargées en {time.perf_counter() - t:.1f} s")
            A.annoncer_repli_reveil()  # modèle du mot de réveil absent : repli sur le modèle de secours, dit au journal
        else:
            self.stt = self.voix = None
            print("  profil ha : Speech-to-Phrase, Piper et openWakeWord des applis de Home Assistant")
        self.verrou = asyncio.Lock()  # une commande à la fois, l'assistant n'est pas réentrant
        self.calibration = None
        self.satellites = set()
        self.pages_admin = set()  # pages d'administration ouvertes (Ingress), voir administration.py
        self.cerveau_actif = "claude" if cfg.get("llm_fournisseur") == "claude" else "local"
        self.cerveau_pret, self.cerveau_message = True, ""
        self.essai = essai
        self.noms = Noms(self)
        self.stt_actif = "pc" if self.profil == "pc" else "ha_stp"
        if self.profil == "ha":
            self.cerveau_actif = "claude"  # pas de carte graphique sur le petit serveur
        # Après le forçage du profil ha (0.27.3) : sur HA, Claude est le seul cerveau, quel que soit llm_fournisseur.
        if self.cerveau_actif == "claude" and A.cle_claude_absente():
            self.cerveau_message = A.MANQUE_CLE_CLAUDE  # affiché par l'appli dans les réglages
        self.arbitre = Arbitre(self)
        self.appareils = None    # acces.Appareils, réglé par servir()
        self.empreinte_tls = ""  # clé publique du port chiffré, pour l'épinglage côté téléphone
        print(f"  détection de parole : {'Silero VAD' if V.disponible() else 'seuil d énergie (modèle Silero absent)'}")
        # Vision déportée pour la tablette (0.18.0) : seulement sur le PC, le petit serveur de HA est trop lent.
        self.vision, self.verrou_vision = None, asyncio.Lock()
        self.verrou_stt = asyncio.Lock()  # une transcription déportée à la fois
        if self.profil == "pc" and VI.disponible():
            try:
                self.vision = VI.Vision()
                print("  vision : YuNet et SFace prêts pour les tablettes")
            except Exception as e:
                print(f"  vision indisponible ({e.__class__.__name__} : {e})")
        # Données de santé pour l'écran (0.19.0) : sante-api n'est joignable que par Tailscale, donc
        # seulement depuis le PC. Sans SANTE_JETON dans poc/.env, le relais reste éteint. Servi seulement
        # sur la liaison chiffrée et aux clés de SANTE_PERSONNES (voir sante.py et acces.Appareils.identite).
        self.sante = SA.depuis_env(self.profil)
        self.sante_personnes = SA.personnes_permises()
        if self.profil == "pc":
            print("  santé : " + (f"relais vers {self.sante.url}, permis à {', '.join(sorted(self.sante_personnes)) or 'personne'}"
                                  if self.sante else "relais éteint (SANTE_JETON absent)"))
        # Historique pour les onglets Tendances, Séances, Records et Jour (0.20.0) : lu dans le
        # data-auto.js du tableau de bord santé, mêmes conditions et même accès que le relais.
        self.sante_hist = SH.depuis_env(self.profil) if self.sante else None
        if self.profil == "pc":
            print("  historique santé : " + ("tableau de bord HealthStats" if self.sante_hist else "éteint"))
        # Météo marine du plan d'eau (section « mer » de maison.json) pour la page « Mer » (0.22.0) : sources
        # publiques, aucune donnée personnelle, dans les deux profils. METEO_MER=0 l'éteint (voir meteo_mer.py).
        self.meteo_mer = MM.depuis_env()
        print("  météo marine : " + (", ".join(MM.libelle_sources()) if self.meteo_mer
                                     else "éteinte (" + (
                                         "METEO_MER=0" if MM.ACTIF and MM.POINTS and MM.eteinte_par_env()
                                         else "modèle principal désactivé (actif: false)" if MM.ACTIF and MM.POINTS
                                         else "pas de section « mer » active dans maison.json") + ")"))
        # Vent réellement mesuré sur le plan d'eau (section « vent ») (0.24.0) : sources publiques, aucune donnée
        # personnelle, dans les deux profils. VENT_MESURE=0 ou METEO_MER=0 l'éteint (voir vent_mesure.py).
        self.vent_mesure = VM.depuis_env()
        print("  vent mesuré : " + (", ".join(VM.libelle_sources()) if self.vent_mesure
                                    else "éteint (" + causes_vent_eteint() + ")"))

    def refus_sante(self, sat):
        """Raison du refus du relais santé pour cette connexion, ou None (sat : un Satellite)."""
        return SA.refus(self.sante, getattr(sat, "chiffre", False), getattr(sat, "identite", None),
                        self.sante_personnes)

    def refus_sante_hist(self, sat):
        """Comme refus_sante, pour l'historique (sante_periode, sante_seances, sante_seance...)."""
        return SA.refus(getattr(self, "sante_hist", None), getattr(sat, "chiffre", False),
                        getattr(sat, "identite", None), self.sante_personnes)

    def capacites(self, sat=None):
        """Ce que ce serveur sait faire : l'appli n'affiche que ces choix-là. « sante » dépend de la
        connexion (sat) : vraie seulement pour un appareil permis sur la liaison chiffrée."""
        transcriptions = (["pc"] if self.profil == "pc" else []) + list(SERVICES_STT_HA)
        if stt_api_configuree():
            transcriptions.append("api")
        return {"etat": "capacites", "serveur": self.profil, "version": A.VERSION,
                "transcription": transcriptions,
                "libelles": {"pc": "PC (Canary)", "ha_stp": "Home Assistant (Speech-to-Phrase)",
                             "ha_whisper": "Home Assistant (Whisper, très lent)",
                             "api": f"En ligne ({os.getenv('STT_API_NOM', 'API')})"},
                "cerveau": ["claude", "local"] if self.profil == "pc" else ["claude"],
                "reveil_appareil": True,
                "mot_reveil": A.modele_reveil()[1] if self.profil == "pc" else A.NOM_REPLI,
                "vad": "silero" if V.disponible() else "energie",
                "passerelle_ha": self.assistant.ha is not None, "appairage": bool(self.empreinte_tls),
                "vision": self.vision is not None,
                "previsions": self.assistant.ha is not None,
                "sante": sat is not None and self.refus_sante(sat) is None,
                "sante_historique": sat is not None and self.refus_sante_hist(sat) is None,
                "meteo_mer": getattr(self, "meteo_mer", None) is not None,
                "vent_mesure": getattr(self, "vent_mesure", None) is not None,
                "empreinte": self.empreinte_tls}

    def etat_stt(self):
        if self.stt_actif == "api":
            message = f"En ligne ({os.getenv('STT_API_NOM', 'API')}) : comprend tout, la voix quitte la maison"
        elif self.stt_actif == "ha_stp" and stt_api_configuree():
            message = SERVICES_STT_HA["ha_stp"][1] + ", repli en ligne si rien n'est reconnu"
        else:
            message = SERVICES_STT_HA.get(self.stt_actif, (None, "Canary 1B sur le processeur du PC, environ 0,3 s"))[1]
        return {"etat": "transcription", "actif": self.stt_actif, "message": message}

    async def changer_stt(self, choix):
        """Où transcrire la voix : « pc » (Canary), « ha_stp » ou « ha_whisper » (petit serveur de HA)."""
        if choix not in self.capacites()["transcription"]:
            await self.diffuser(self.etat_stt())
            return
        async with self.verrou:
            self.stt_actif = choix
        print(f"  transcription : {choix}")
        await self.diffuser(self.etat_stt())

    def etat_mode(self):
        return {"etat": "mode", "actif": "essai" if self.essai else "reel",
                "message": "Essai : rien n'est exécuté dans la maison" if self.essai
                else "Réel : les commandes agissent sur Home Assistant"}

    async def changer_mode(self, choix):
        """Bascule essai ou réel à chaud, demandée depuis le téléphone (12/10/2026)."""
        if choix not in ("essai", "reel"):
            return
        # S-F4 (0.40.0) : l'essai du serveur est un réglage commun, pas un état de requête. Il n'est écrit
        # qu'ici, sous le verrou du cerveau (aucune commande en cours), et lu par les requêtes à leur début.
        async with self.verrou:  # jamais au milieu d'une commande
            self.essai = choix == "essai"
            self.assistant.essai = self.essai
            if self.assistant.ha:
                self.assistant.ha.essai = self.essai
        print(f"  mode : {'ESSAI, rien n est exécuté' if self.essai else 'RÉEL, actions sur Home Assistant'}")
        await self.diffuser(self.etat_mode())

    def etat_cerveau(self):
        return {"etat": "cerveau", "actif": self.cerveau_actif, "pret": self.cerveau_pret,
                "message": self.cerveau_message}

    async def diffuser(self, message, administrateurs=False):
        """Envoie [message] aux satellites connectés, ou aux seuls administrateurs (appairage : le code
        ne doit arriver qu'à qui a le droit d'accepter la demande)."""
        for sat in list(self.satellites):
            if administrateurs and not acces.est_administrateur(sat.identite):
                continue
            try:
                await sat.envoyer(**message)
            except Exception:
                pass
        if administrateurs:  # les pages d'administration sont administratrices le temps de leur connexion
            for page in list(self.pages_admin):
                try:
                    await page.envoyer(**message)
                except Exception:
                    pass

    async def diffuser_historique(self, ligne):
        """Diffuse la ligne d'historique qui vient d'être écrite, destinataire par destinataire (0.39.0) : chacun ne
        reçoit que ce que entrees_visibles lui laisse voir. Les pages d'administration sont administratrices."""
        appareils = getattr(self, "appareils", None)
        for sat in list(self.satellites):
            role = acces.role_effectif(sat.identite, appareils)
            personne = acces.personne_effective(sat.identite, None, appareils)
            if not entrees_visibles([ligne], role, sat.identite, sat.cle_appareil(), personne):
                continue
            try:
                await sat.envoyer(etat="historique_ajout", entree=entree_historique(ligne, self.noms))
            except Exception:
                pass
        for page in list(self.pages_admin):
            try:
                await page.envoyer(etat="historique_ajout", entree=entree_historique(ligne, self.noms))
            except Exception:
                pass

    def admin_connecte(self):
        """Vrai si un administrateur (téléphone ou page d'administration) est connecté : ferme l'amorçage."""
        return bool(self.pages_admin) or any(acces.est_administrateur(s.identite) for s in self.satellites)

    async def changer_cerveau(self, choix):
        """Bascule demandée depuis le téléphone : « claude » (en ligne) ou « local » (carte graphique).

        Passer en local démarre llama-server s'il ne tourne pas. Repasser sur Claude arrête
        llama-server pour rendre la carte graphique (le PC sert aussi aux jeux)."""
        if choix not in self.capacites()["cerveau"]:
            await self.diffuser(self.etat_cerveau())
            return
        if choix == self.cerveau_actif and self.cerveau_pret:
            await self.diffuser(self.etat_cerveau())
            return
        if choix == "claude" and A.cle_claude_absente():  # garder le modèle local plutôt que plus rien
            # Hors du verrou (0.27.3) : le refus ne doit pas attendre une commande en cours, et une appli qui
            # redemande Claude à chaque reconnexion ne répète pas la même ligne dans le journal.
            refus = f"{A.MANQUE_CLE_CLAUDE}, je reste sur le modèle local"
            if self.cerveau_message != refus:
                self.cerveau_message = refus
                print(f"  cerveau : {self.cerveau_actif} ({refus})")
            await self.diffuser(self.etat_cerveau())
            return
        async with self.verrou:
            self.cerveau_actif, self.cerveau_pret = choix, False
            if choix == "claude":
                self.cerveau_message = "Bascule sur Claude en ligne..."
                await self.diffuser(self.etat_cerveau())
                self.assistant.cerveau = A.CerveauClaude(self.cfg, self.assistant.ha)
                arretes = await asyncio.to_thread(arreter_llm_local)
                self.cerveau_message = "Claude en ligne, carte graphique libérée" if arretes else "Claude en ligne"
            else:
                self.cerveau_message = "Démarrage du modèle sur la carte graphique..."
                await self.diffuser(self.etat_cerveau())
                pret = await asyncio.to_thread(demarrer_llm_local)
                if not pret:
                    self.cerveau_actif, self.cerveau_message = "claude", (
                        f"Carte graphique indisponible et pas de clé Claude : aucun cerveau ne répond ({A.MANQUE_CLE_CLAUDE})"
                        if A.cle_claude_absente() else "Carte graphique indisponible, je reste sur Claude")
                    self.assistant.cerveau = A.CerveauClaude(self.cfg, self.assistant.ha)
                else:
                    self.assistant.cerveau = A.Cerveau(self.cfg, self.assistant.ha)
                    self.cerveau_message = "Modèle local prêt sur la carte graphique"
            self.cerveau_pret = True
        print(f"  cerveau : {self.cerveau_actif} ({self.cerveau_message})")
        await self.diffuser(self.etat_cerveau())


    def noter_retour(self, msg, appareil):
        """Note « bien » ou « mauvais » du propriétaire sur une commande. Une phrase apprise jugée mauvaise
        est oubliée tout de suite. Une ligne écrite à la main reste à corriger par Claude."""
        from dictionnaire import epurer
        verdict = "bien" if msg.get("verdict") == "bien" else "mauvais"
        entendu = str(msg.get("entendu", "")).strip()
        effet = ""
        if verdict == "mauvais" and entendu:
            dico = self.assistant.dico
            for phrase in (entendu, epurer(entendu)):
                if dico.oublier(phrase):
                    effet = f"phrase apprise « {phrase} » oubliée"
                    break
            if not effet:
                effet = "à corriger dans commandes.yaml" if "dictionnaire" in str(msg.get("compris_par", "")) \
                    else "noté pour améliorer le dictionnaire"
        A.ajouter_jsonl(A.RETOURS, {"appareil": appareil, "verdict": verdict, "effet": effet,
                                    **{k: v for k, v in msg.items() if k not in ("type", "verdict")}})
        print(f"[{appareil}] note {verdict} : {A.pour_console(entendu)}" + (f" ({A.pour_console(effet)})" if effet else ""))
        return effet or "noté"

    def llm_texte(self, texte, essai, personne=None, appareil=None, canal="appli"):
        """Phrase déjà transcrite et non comprise par le téléphone (mode « Cet appareil », appli 0.10.0) :
        seulement le LLM du serveur, avec ses garde-fous. Essai effectif : celui du serveur ou celui du
        téléphone (0.28.0, un téléphone en réel ne lève plus l'essai du serveur).
        personne : qui parle d'après la tablette (règle 3 de securite.py, « ma chambre »), ou rien.
        appareil : identité de l'appareil appairé, pour l'historique et la leçon à annuler."""
        import securite
        essai = self.essai or bool(essai)
        refus = securite.phrase_protegee(texte, personne)
        if refus:
            return {"reponse": f"Je ne le fais pas : {refus}.", "actions": [], "cerveau": "sécurité", "ms": 0,
                    "erreur": "", "essai": essai}
        a = self.assistant
        t = time.perf_counter()
        erreur = ""
        with a.requete(essai=essai, personne=personne, appareil=appareil, canal=canal):
            try:
                parole, actions = a.cerveau.repondre(texte)
                a.apprendre(texte, parole)  # jamais en essai, comme pour une phrase entendue ici
            except Exception as e:
                parole, actions, erreur = "Le modèle de langage ne répond pas.", [], f"{e.__class__.__name__} : {e}"
            duree = time.perf_counter() - t
            nom = "Claude Haiku" if self.cerveau_actif == "claude" else "Qwen sur le PC"
            # Dans le contexte de la requête : le journal y lit l'appareil et la personne (filtre de l'historique).
            A.journaliser(texte, f"llm ({nom}, depuis l'appareil" + (f", {personne}" if personne else "") + ")"
                          + (" [essai]" if essai else ""), 0.0, duree, 0.0,
                          parole, actions)
        return {"reponse": parole, "actions": list(actions), "cerveau": nom, "ms": round(duree * 1000),
                "erreur": erreur, "essai": essai}

    def transcrire(self, signal_f32, moteur=None):
        """Texte de la phrase par le moteur demandé (« pc », « api », « ha_stp », « ha_whisper »),
        sinon par celui choisi pour ce serveur. Renvoie (texte, moteur réellement utilisé)."""
        moteur = moteur or self.stt_actif
        source = moteur
        if moteur == "pc" and self.stt:
            texte = self.stt.transcrire(signal_f32)
        elif moteur == "api":
            texte = transcrire_api(signal_f32)
        else:
            try:
                texte = transcrire_ha(SERVICES_STT_HA[moteur][0], signal_f32)
            except Exception as e:
                print(f"  transcription HA en échec ({e.__class__.__name__} : {e})"
                      + (", repli sur le PC" if self.stt else ""))
                texte = self.stt.transcrire(signal_f32) if self.stt else ""
            # Speech-to-Phrase rend un texte vide sur toute phrase qu'il ne connaît pas (essais du
            # 12/10) : repli sur la transcription en ligne si elle est configurée.
            if not texte and moteur == "ha_stp" and stt_api_configuree():
                texte, source = transcrire_api(signal_f32), "ha_stp puis api"
        return texte, source

    def traiter(self, signal_f32, personne=None, appareil=None):
        t = time.perf_counter()
        texte, source = self.transcrire(signal_f32)
        t_stt = time.perf_counter() - t
        print(f"  transcription {source} : {t_stt:.2f} s")
        print(f"  Vous ({len(signal_f32) / TAUX:.1f} s) : {A.pour_console(texte)}")
        if not texte:  # noté aussi, pour que le propriétaire voie dans l'historique ce qui n'a pas été compris
            with self.assistant.requete(essai=self.essai, personne=personne, appareil=appareil, canal="voix"):
                A.journaliser("", f"rien compris ({source})" + (" [essai]" if self.essai else ""), t_stt, 0.0, 0.0, "", [])
            return texte, "", "rien compris", None
        reponse = self.assistant.traiter(texte, t_stt, personne, appareil=appareil, essai=self.essai, canal="voix")
        voie = derniere_voie(0)
        if not reponse:
            audio = None
        elif self.voix:
            audio = wav_de(self.voix.synthetiser(reponse), self.voix.taux)
        else:
            audio = synthetiser_ha(reponse)
        return texte, reponse, voie, audio


def profil():
    """« pc » (serveur sur le PC fixe) ou « ha » (appli Home Assistant), variable JARVIS_PROFIL."""
    return os.getenv("JARVIS_PROFIL", "pc").strip().lower()


# Applis vocales de Home Assistant (petite machine, petit serveur à l'origine), par leur nom d'hôte sur le réseau interne de HA.
# Depuis l'appli de l'assistant dans HA : connexion directe. Depuis le PC : elles ne sont pas ouvertes sur
# le LAN et le SSH de HA interdit les tunnels, le protocole Wyoming passe donc par
# `ssh <alias de HA> nc <hôte> <port>` (environ 0,5 s de plus par phrase). Mesures du 12/10/2026.
SERVICES_STT_HA = {
    "ha_stp": ("core-speech-to-phrase:10300", "Speech-to-Phrase sur HA : phrases connues de HA seulement, environ 1 s"),
    "ha_whisper": ("core-whisper:10300", "Whisper sur HA, modèle turbo : environ 90 s par phrase, test seulement"),
}
# Transcription en ligne, tout service compatible avec l'API de transcription d'OpenAI
# (POST multipart /v1/audio/transcriptions, réponse {"text": ...}) : Mistral (Voxtral), Groq, OpenAI.
# Variables : STT_API_CLE (obligatoire), STT_API_URL, STT_API_MODELE, STT_API_NOM (libellé affiché).
STT_API_DEFAUTS = {"url": "https://api.mistral.ai/v1/audio/transcriptions", "modele": "voxtral-mini-latest"}


def stt_api_configuree():
    return len(os.getenv("STT_API_CLE", "").strip()) > 10


def transcrire_api(signal_f32, delai=20):
    """Envoie la phrase au service en ligne. La voix quitte la maison : choix explicite du propriétaire."""
    import httpx
    wav = wav_de((np.clip(signal_f32, -1, 1) * 32767).astype(np.int16), TAUX)
    r = httpx.post(os.getenv("STT_API_URL", STT_API_DEFAUTS["url"]),
                   headers={"Authorization": f"Bearer {os.getenv('STT_API_CLE', '').strip()}"},
                   data={"model": os.getenv("STT_API_MODELE", STT_API_DEFAUTS["modele"]), "language": "fr"},
                   files={"file": ("phrase.wav", wav, "audio/wav")}, timeout=delai)
    if r.status_code >= 400:
        print(f"  transcription en ligne refusée : HTTP {r.status_code} {r.text[:160]}")
        return ""
    return (r.json().get("text") or "").strip()


PIPER_HA = "core-piper:10200"
REVEIL_HA = "core-openwakeword:10400"
VOIX_HA = "fr_FR-siwis-medium"


class CanalWyoming:
    """Connexion Wyoming vers une appli de HA : directe en profil ha, par `ssh nc` en profil pc."""

    def __init__(self, cible):
        self.hote, self.port = cible.split(":")
        self.proc = None

    async def __aenter__(self):
        # JARVIS_WYOMING_SSH=1 : tester le profil ha depuis le PC, par SSH.
        if profil() == "ha" and not os.getenv("JARVIS_WYOMING_SSH"):
            self.lecteur, self.ecrivain = await asyncio.open_connection(self.hote, int(self.port))
        else:
            self.proc = await asyncio.create_subprocess_exec(
                "ssh", "-o", "ConnectTimeout=10", maison.reseau("ssh_ha"), "nc", self.hote, self.port,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            self.lecteur, self.ecrivain = self.proc.stdout, self.proc.stdin
        return self

    async def ecrire(self, ev):
        from wyoming.event import async_write_event
        await async_write_event(ev, self.ecrivain)

    async def lire(self, delai=240):
        from wyoming.event import async_read_event
        return await asyncio.wait_for(async_read_event(self.lecteur), delai)

    async def __aexit__(self, *exc):
        if self.proc:
            self.proc.kill()
            await self.proc.wait()
        else:
            self.ecrivain.close()


def transcrire_ha(cible, signal_f32, delai=240):
    """Transcrit par une appli Wyoming de HA (Speech-to-Phrase ou Whisper)."""
    from wyoming.asr import Transcribe, Transcript
    from wyoming.audio import AudioStart, AudioChunk, AudioStop
    audio = (np.clip(signal_f32, -1, 1) * 32767).astype(np.int16).tobytes()

    async def dialogue():
        async with CanalWyoming(cible) as c:
            await c.ecrire(Transcribe(language="fr").event())
            await c.ecrire(AudioStart(rate=TAUX, width=2, channels=1).event())
            for i in range(0, len(audio), 3200):
                await c.ecrire(AudioChunk(rate=TAUX, width=2, channels=1, audio=audio[i:i + 3200]).event())
            await c.ecrire(AudioStop().event())
            while True:
                ev = await c.lire(delai)
                if ev is None:
                    raise ConnectionError("connexion fermée sans transcription")
                if Transcript.is_type(ev.type):
                    return Transcript.from_event(ev).text.strip()

    return asyncio.run(dialogue())  # appelé depuis un thread de travail, jamais depuis la boucle principale


def synthetiser_ha(texte, delai=60):
    """Voix de la réponse par l'appli Piper de HA, voix française. Renvoie un WAV complet."""
    from wyoming.tts import Synthesize, SynthesizeVoice
    from wyoming.audio import AudioChunk, AudioStop

    async def dialogue():
        morceaux, taux = [], 22050
        async with CanalWyoming(PIPER_HA) as c:
            await c.ecrire(Synthesize(text=texte, voice=SynthesizeVoice(name=VOIX_HA)).event())
            while True:
                ev = await c.lire(delai)
                if ev is None or AudioStop.is_type(ev.type):
                    break
                if AudioChunk.is_type(ev.type):
                    ch = AudioChunk.from_event(ev)
                    taux = ch.rate
                    morceaux.append(ch.audio)
        return wav_de(np.frombuffer(b"".join(morceaux), dtype=np.int16), taux)

    return asyncio.run(dialogue())


class ReveilWyoming:
    """Mot de réveil par l'appli openWakeWord de HA : flux continu, événement Detection en retour. Cette appli ne
    porte que le modèle de repli (A.MODELE_REPLI), le dossier reveil/ de la configuration ne lui est pas copié."""

    def __init__(self, sur_detection):
        self.sur_detection = sur_detection
        self.canal, self.tache = None, None

    async def ouvrir(self):
        from wyoming.wake import Detect
        from wyoming.audio import AudioStart
        self.canal = await CanalWyoming(REVEIL_HA).__aenter__()
        await self.canal.ecrire(Detect(names=[A.MODELE_REPLI]).event())
        await self.canal.ecrire(AudioStart(rate=TAUX, width=2, channels=1).event())
        self.tache = asyncio.create_task(self.ecouter())

    async def ecouter(self):
        from wyoming.wake import Detection
        try:
            while True:
                ev = await self.canal.lire(delai=None)
                if ev is None:
                    break
                if Detection.is_type(ev.type):
                    await self.sur_detection(Detection.from_event(ev).name)
        except Exception as e:
            print(f"  mot de réveil HA : flux coupé ({e.__class__.__name__})")
        self.canal = None

    async def envoyer(self, bloc_int16):
        from wyoming.audio import AudioChunk
        if self.canal is None:
            await self.ouvrir()
        try:
            await self.canal.ecrire(AudioChunk(rate=TAUX, width=2, channels=1, audio=bloc_int16.tobytes()).event())
        except Exception:
            self.canal = None  # rouvert au bloc suivant

    async def fermer(self):
        if self.tache:
            self.tache.cancel()
        if self.canal:
            await self.canal.__aexit__(None, None, None)


def llm_local_pret():
    import httpx
    try:
        return httpx.get("http://127.0.0.1:8080/health", timeout=2).status_code == 200
    except Exception:
        return False


def demarrer_llm_local(delai=90):
    if llm_local_pret():
        return True
    import subprocess
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", str(A.ICI / "lancer-llm.ps1")], creationflags=0x08000000)  # pas de fenêtre
    t0 = time.time()
    while time.time() - t0 < delai:
        if llm_local_pret():
            return True
        time.sleep(1)
    return False


def arreter_llm_local():
    import subprocess
    r = subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True)
    return r.returncode == 0

def derniere_voie(taille_avant=0):
    """Voie (dictionnaire, ha, llm) lue dans la ligne que l'assistant vient de journaliser."""
    entrees = lire_journal(1)
    return entrees[0].get("voie", "") if entrees else ""


def lire_journal(n):
    """Les n dernières entrées de l'historique (journal/assistant-AAAA-MM-JJ.jsonl), la plus récente en premier.
    Chaque entrée porte aussi appareil, personne et role (0.39.0), que entree_historique n'envoie jamais."""
    return A.lire_historique(n)


def entrees_visibles(lignes, role, identite, appareil, personne):
    """Entrées de l'historique que ce destinataire a le droit de voir (0.39.0). Règle la plus fermée de
    client-web.md 4.4 :
    - administrateur : tout ;
    - habitant : ce qu'il a dit (même appareil ou même personne) et le commun, c'est-à-dire ce qu'un appareil
      partagé a traité sans personne identifiée ;
    - partage et invité : seulement ce qui vient de leur propre appareil, jamais le commun ;
    - rôle inconnu : rien.
    Une entrée sans appareil (écrite avant 0.39.0, ou par le micro du PC) n'est vue que d'un administrateur."""
    if role == "administrateur":
        return list(lignes)
    sortie = []
    for l in lignes:
        a, p, r = l.get("appareil"), l.get("personne"), l.get("role")
        if not a:
            continue
        if a == appareil:
            sortie.append(l)
        elif role == "habitant" and ((personne and p == personne) or (not p and r == "partage")):
            sortie.append(l)
    return sortie


VERBES = {"turn_on": "allumer", "turn_off": "éteindre", "toggle": "basculer", "select_source": "mettre sur une source",
          "volume_set": "régler le volume de", "volume_mute": "couper ou rétablir le son de", "media_play": "lancer la lecture sur",
          "media_pause": "mettre en pause", "media_stop": "arrêter", "media_next_track": "passer au morceau suivant sur",
          "start": "démarrer", "pause": "mettre en pause", "stop": "arrêter", "return_to_base": "renvoyer à sa base",
          "play_media": "jouer de la musique sur", "press": "appuyer sur", "set_temperature": "régler la température de",
          "open_cover": "ouvrir", "close_cover": "fermer", "set_percentage": "régler"}


class Noms:
    """Noms lisibles des appareils (Home Assistant, ou ceux de la vue du LLM), rafraîchis toutes les 5 min."""

    def __init__(self, moteur):
        self.moteur, self.cache, self.t = moteur, {}, 0.0

    def __call__(self, entity_id):
        if time.time() - self.t > 300 and self.moteur.assistant.ha:
            try:
                ha = self.moteur.assistant.ha
                etats = ha.client.get(f"{ha.url}/api/states", timeout=10).json()
                self.cache = {e["entity_id"]: e["attributes"].get("friendly_name", e["entity_id"]) for e in etats}
                renommer = (ha.vue_llm or {}).get("renommer") or {}
                self.cache.update({k: v.split(" (")[0] for k, v in renommer.items()})
            except Exception:
                pass
            self.t = time.time()
        return self.cache.get(entity_id, entity_id)


def actions_lisibles(texte_actions, noms):
    """« light.turn_on ['light.salon_lampe_tele'] » devient « allumer Lampe TV »."""
    sortie = []
    for brut in [a.strip() for a in (texte_actions or "").split(" | ") if a.strip()]:
        if brut.startswith("ha "):  # action faite par Home Assistant lui-même : « ha entity light.x » ou « ha area Séjour »
            morceaux = brut.split(maxsplit=2)
            sortie.append("Home Assistant : " + (noms(morceaux[2]) if len(morceaux) > 2 else brut))
            continue
        refuse = re.search(r"\s*\((refusé[^)]*)\)\s*$", brut)  # action refusée : dite telle quelle
        if refuse:
            brut = brut[:refuse.start()]
        service = brut.split()[0]
        domaine, _, action = service.partition(".")
        cibles = [e for e in re.findall(r"[a-z_]+\.[a-z0-9_]+", brut[len(service):])]
        source = re.search(r"\(([^)]*)\)\s*$", brut)
        if source:  # réglages en clair : couleur, luminosité, source, volume
            brut = brut[:source.start()]
            cibles = [e for e in re.findall(r"[a-z_]+\.[a-z0-9_]+", brut[len(service):])]
        quoi = ", ".join(noms(c) for c in cibles) or ("toutes les lumières" if "all" in brut else "")
        if domaine == "script" and action == "turn_on":
            phrase = "lancer le script " + quoi
        else:
            phrase = f"{VERBES.get(action, action)} {quoi}".strip()
        if source and action == "select_source":
            phrase = f"mettre {quoi} sur {traduire_reglages(source.group(1))}"
        elif source:
            phrase += " (" + traduire_reglages(source.group(1)) + ")"
        sortie.append(phrase + (f" ({refuse.group(1)}, rien fait)" if refuse else ""))
    return sortie


REGLAGES = {"color_name": "couleur", "brightness_pct": "luminosité", "source": "source", "volume_level": "volume",
            "color_temp_kelvin": "blanc K", "is_volume_muted": "muet", "media_content_id": "média"}
COULEURS = {"red": "rouge", "blue": "bleu", "green": "vert", "orange": "orange", "purple": "violet", "pink": "rose",
            "yellow": "jaune", "white": "blanc", "cyan": "cyan"}


def traduire_reglages(texte):
    morceaux = []
    for m in [x.strip() for x in texte.split(",") if x.strip()]:
        cle, _, val = m.partition("=")
        if cle in ("source",):
            morceaux.append(val)
        elif cle == "brightness_pct":
            morceaux.append(f"luminosité {val} %")
        elif cle == "volume_level":
            try:
                morceaux.append(f"volume {round(float(val) * 100)} %")
            except ValueError:
                morceaux.append(f"volume {val}")
        else:
            morceaux.append(f"{REGLAGES.get(cle, cle)} {COULEURS.get(val, val)}".strip())
    return ", ".join(morceaux)


def entree_historique(ligne, noms):
    voie = ligne.get("voie", "")
    categorie = ("dictionnaire" if voie.startswith("dictionnaire") else "Home Assistant" if voie.startswith("ha")
                 else "Claude ou modèle local" if voie.startswith("llm") else voie.split(" (")[0])
    return {"heure": ligne.get("horodatage", "")[11:16], "date": ligne.get("horodatage", "")[:10],
            "essai": "[essai]" in voie, "entendu": ligne.get("texte", ""), "compris_par": categorie,
            "detail_voie": voie, "fait": actions_lisibles(ligne.get("actions"), noms),
            "erreur": "erreur" in voie, "reponse": ligne.get("reponse", ""), "duree": ligne.get("total_s", "")}


class Calibration:
    """Calibrage guidé du mot de réveil (option --calibrer), aucune commande n'est exécutée.

    Phase bruit : 45 s de vie normale de la pièce, on relève le plus haut score obtenu à tort.
    Phase mot : l'utilisateur dit le mot de réveil de la configuration 10 fois, un essai = un pic de score au-dessus de 0,1.
    Le seuil recommandé est placé entre les deux, puis écrit dans SEUIL_REVEIL (poc/.env)."""

    DUREE_BRUIT = 45.0
    ESSAIS = 10

    def __init__(self, seuil_actuel):
        self.seuil = seuil_actuel
        self.phase = "attente"
        self.scores_bruit = []
        self.pics, self.pic_en_cours = [], 0.0
        self.bips = 0
        self.fin_phase = asyncio.Event()

    def score(self, s):
        if self.phase == "bruit":
            self.scores_bruit.append(s)
        elif self.phase == "mot":
            if s >= 0.1:
                self.pic_en_cours = max(self.pic_en_cours, s)
            elif self.pic_en_cours and s < 0.05:
                self.pics.append(self.pic_en_cours)
                print(f"   essai {len(self.pics)} : score {self.pic_en_cours:.2f}"
                      + ("  (détecté au seuil actuel)" if self.pic_en_cours >= self.seuil else "  (raté au seuil actuel)"))
                if self.pic_en_cours >= self.seuil:
                    self.bips += 1
                self.pic_en_cours = 0.0
                if len(self.pics) >= self.ESSAIS:
                    self.fin_phase.set()

    async def deroule(self, connecte):
        print("\n=== Calibrage du mot de réveil ===")
        print("Pose le téléphone à sa place habituelle. Attente de sa connexion...")
        await connecte.wait()
        await asyncio.to_thread(input, "\n[1/2] BRUIT DE FOND : ne dis pas le mot pendant 45 s, laisse la pièce vivre "
                                        "(télé, discussion). Entrée pour commencer. ")
        self.phase = "bruit"
        t0 = time.time()
        while time.time() - t0 < self.DUREE_BRUIT:
            await asyncio.sleep(5)
            haut = max(self.scores_bruit, default=0)
            print(f"   {time.time() - t0:4.0f} s, score le plus haut obtenu à tort : {haut:.2f}")
        self.phase = "pause"
        await asyncio.to_thread(input, f"\n[2/2] LE MOT : dis « {A.modele_reveil()[1]} » {self.ESSAIS} fois, en "
                                        "laissant 3 s entre chaque, en variant la distance et le volume. Entrée pour commencer. ")
        self.phase = "mot"
        try:
            await asyncio.wait_for(self.fin_phase.wait(), 150)
        except asyncio.TimeoutError:
            print("   temps écoulé")
        self.phase = "fini"
        return self.bilan()

    def bilan(self):
        bruit = sorted(self.scores_bruit)
        haut = bruit[-1] if bruit else 0.0
        p99 = bruit[int(len(bruit) * 0.99) - 1] if len(bruit) > 100 else haut
        pics = sorted(self.pics)
        print("\n=== Bilan ===")
        print(f"Bruit : {len(bruit)} mesures, score max à tort {haut:.2f}, 99 % sous {p99:.2f}")
        if not pics:
            print("Aucun essai capté : le mot n'est pas reconnu du tout. Vérifie le micro (vumètre de l'appli) "
                  "et la prononciation à l'anglaise.")
            return None
        print(f"Mot : {len(pics)} essais captés, scores " + ", ".join(f"{p:.2f}" for p in pics))
        bas = pics[max(0, int(len(pics) * 0.2) - 1)]  # on accepte de rater les 20 % d'essais les plus faibles
        seuil = round(min(max((haut + bas) / 2, haut + 0.1, 0.25), 0.9), 2)
        rates = sum(1 for p in pics if p < seuil)
        print(f"Seuil recommandé : {seuil:.2f} (actuel {self.seuil:.2f}). Avec lui : {len(pics) - rates}/{len(pics)} "
              f"essais détectés, marge de {seuil - haut:.2f} au-dessus du bruit.")
        if bas <= haut:
            print("ATTENTION : des essais faibles se confondent avec le bruit. Rapproche le téléphone, réduis le bruit "
                  "ou prononce plus nettement.")
        return seuil


def enregistrer_seuil(seuil):
    env = A.ICI / ".env"
    lignes = [l for l in env.read_text(encoding="utf-8").splitlines() if not l.startswith("SEUIL_REVEIL=")]
    lignes.append(f"SEUIL_REVEIL={seuil}")
    env.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    journal = A.DONNEES / "journal" / "calibration_reveil.csv"  # dossier de données (0.27.3), plus poc/ en dur
    journal.parent.mkdir(parents=True, exist_ok=True)
    neuf = not journal.exists()
    with open(journal, "a", encoding="utf-8") as f:
        if neuf:
            f.write("horodatage;version;seuil\n")
        f.write(f"{maison.maintenant().strftime(maison.FORMAT_HORODATAGE)};{A.VERSION};{seuil}\n")


class Arbitre:
    """Un seul téléphone répond quand plusieurs ont entendu le mot de réveil.

    Idée reprise d'un projet d'inspiration, réécrite ici. Avec un seul téléphone au repos,
    il répond tout de suite. Sinon, la première détection ouvre une fenêtre de 250 ms, le meilleur score
    gagne, et les détections du même appel qui arrivent ensuite (écho, retard réseau) sont ignorées
    pendant 1,5 s."""

    FENETRE, ECHO = 0.25, 1.5

    def __init__(self, moteur):
        self.moteur = moteur
        self.candidats, self.futur, self.fin_dernier = None, None, 0.0

    async def demander(self, sat, score):
        if time.monotonic() - self.fin_dernier < self.ECHO:
            return False
        if self.candidats is not None:  # fenêtre déjà ouverte par un autre téléphone
            self.candidats[sat] = max(score, self.candidats.get(sat, 0.0))
            return (await self.futur) is sat
        # Seulement les téléphones qui écoutent vraiment (son reçu ou réveil signalé) : la passerelle HA
        # du mode « Cet appareil » est aussi une connexion, mais n'entend rien.
        au_repos = [s for s in self.moteur.satellites if s.etat == "repos" and getattr(s, "ecoute_reveil", True)]
        if len(au_repos) <= 1:
            self.fin_dernier = time.monotonic()
            return True
        self.candidats, self.futur = {sat: score}, asyncio.get_running_loop().create_future()
        await asyncio.sleep(self.FENETRE)
        gagnant = max(self.candidats, key=self.candidats.get)
        if len(self.candidats) > 1:
            print("  arbitre : " + ", ".join(f"{s.nom} {v:.2f}" for s, v in self.candidats.items())
                  + f", c'est {gagnant.nom} qui répond")
        self.candidats, self.fin_dernier = None, time.monotonic()
        self.futur.set_result(gagnant)
        return gagnant is sat


def passerelle_ha(moteur, msg, identite=None):
    """Requête Home Assistant demandée par un téléphone en mode « Cet appareil » (voir acces.py).
    identite : clé du téléphone, qui borne la personne reconnue (acces.personne_effective). Sans elle, aucune."""
    ha = moteur.assistant.ha
    ident = msg.get("id")
    if not ha:
        return {"etat": "ha", "id": ident, "code": 503, "corps": "Home Assistant non configuré sur ce serveur"}
    methode, chemin, corps = str(msg.get("methode", "GET")).upper(), str(msg.get("chemin", "")), msg.get("corps")
    # La personne reconnue par la tablette (règle 3) : seule exception à la règle 1, vérifiée par securite.py.
    personne = acces.personne_effective(identite, msg.get("personne"), getattr(moteur, "appareils", None))
    refus = acces.verifier_requete_ha(methode, chemin, corps, personne=personne)
    if refus:
        return {"etat": "ha", "id": ident, "code": 403, "corps": f"refusé : {refus}"}
    if moteur.essai and methode == "POST" and (chemin.startswith("/api/services/")
                                               or chemin == "/api/conversation/process"):  # l'agent de HA agit aussi
        print(f"  passerelle HA [essai] : {chemin} non transmis")
        return {"etat": "ha", "id": ident, "code": 200, "corps": "[]"}
    try:
        r = ha.client.request(methode, f"{ha.url}{chemin}", json=corps if methode == "POST" else None, timeout=15)
        type_contenu = r.headers.get("content-type", "")
        if type_contenu.startswith("image/"):  # pochette d'album : base64, 2 Mo au plus
            if len(r.content) > 2_000_000:
                return {"etat": "ha", "id": ident, "code": 413, "corps": "image trop grande"}
            import base64
            return {"etat": "ha", "id": ident, "code": r.status_code, "corps": "", "type": type_contenu,
                    "base64": base64.b64encode(r.content).decode()}
        return {"etat": "ha", "id": ident, "code": r.status_code, "corps": r.text}
    except Exception as e:
        return {"etat": "ha", "id": ident, "code": 502, "corps": f"{e.__class__.__name__} : {e}"}


# Messages réservés au propriétaire et aux administrateurs de acces.administrateurs : gestion des appareils et de
# l'appairage, réglages communs à tous (transcription, mode, cerveau), lecture des phrases ratées et des retours.
# La table complète des types permis par rôle est dans acces.py (TYPES_PAR_ROLE, acces.type_permis).
TYPES_ADMINISTRATEUR = acces.TYPES_ADMINISTRATION


def nom_de_type(genre):
    """Type de message pour le journal du serveur : court et imprimable, puisque le client le choisit librement
    (jamais de contenu du message, seulement le type)."""
    if not isinstance(genre, str):
        return f"<{type(genre).__name__}>"
    propre = "".join(c if c.isprintable() else "?" for c in genre[:40])
    return propre + ("..." if len(genre) > 40 else "")


class Satellite:
    """Machine à états d'un téléphone connecté."""

    def __init__(self, ws, moteur, seuil, nom):
        self.ws, self.moteur, self.seuil, self.nom = ws, moteur, seuil, nom
        if moteur.profil == "pc":
            from openwakeword.model import Model
            self.reveil = Model(wakeword_models=[A.modele_reveil()[0]], inference_framework="onnx")
            self.reveil_ha = None
        else:  # appli openWakeWord de HA, seuil réglé dans cette appli
            self.reveil, self.reveil_ha = None, ReveilWyoming(self.sur_detection_ha)
        self.vad = V.creer()
        self.ecoute_reveil = False  # devient vrai au premier son ou au premier réveil signalé
        self.tampon = np.zeros(0, dtype=np.int16)
        self.etat = "repos"
        self.bruit = 0.004
        self.capture, self.parle, self.silence, self.t_ecoute = [], False, 0.0, 0.0
        self.sourd_jusqua = 0.0  # pendant la lecture de la réponse, on n'écoute pas
        self.dernier_score_envoye = 0.0
        # Qui parle d'après la tablette (champ « personne » de parler et reveil, règle 3 de securite.py),
        # pour la phrase en cours seulement. À ne pas confondre avec self.personne, propriétaire du jeton.
        self.qui_parle = None
        # Réglés par accueil() : clé de l'appareil et liaison chiffrée (relais santé). Par défaut, refus.
        self.identite, self.chiffre = None, False

    async def envoyer(self, **message):
        await self.ws.send(json.dumps(message, ensure_ascii=False))

    def personne_du_message(self, msg):
        """Personne dont les droits valent pour ce message (llm, parler, reveil, ha), jamais celle que le
        message déclare sans contrôle : voir acces.personne_effective."""
        return acces.personne_effective(self.identite, msg.get("personne"), getattr(self.moteur, "appareils", None))

    def cle_appareil(self):
        """Clé de l'historique et de la leçon : l'identité d'un téléphone appairé, unique. Un jeton fixe de
        poc/.env peut servir à plusieurs appareils, son nom d'appareil les sépare."""
        if self.identite and self.identite.startswith("appareil:"):
            return self.identite
        return f"{self.identite or ''}/{self.nom}"

    def reinitialiser_reveil(self):
        if self.reveil:
            self.reveil.reset()

    async def sur_detection_ha(self, nom):
        if self.etat == "repos" and time.time() >= self.sourd_jusqua:
            # openWakeWord de HA ne renvoie pas de score : à égalité, le premier arrivé gagne.
            if await self.moteur.arbitre.demander(self, 0.5):
                self.qui_parle = None
                await self.commencer_ecoute(f"openWakeWord de HA ({nom})")

    async def perdu_arbitrage(self):
        print(f"[{self.nom}] un autre téléphone répond")
        self.reinitialiser_reveil()
        await self.envoyer(etat="repos", raison="arbitre", message="Un autre appareil a répondu")

    async def commencer_ecoute(self, origine):
        print(f"[{self.nom}] réveil ({origine})")
        self.etat, self.capture, self.parle, self.silence = "ecoute", [], False, 0.0
        self.t_ecoute = time.time()
        if self.vad:
            self.vad.reinitialiser()
        # Le téléphone bipe en recevant « ecoute » et son micro capte ce bip : sans cette pause,
        # le bip passait pour le début de la phrase, qui se terminait avant qu'on parle
        # (transcrit « Merci. » le 12/10). On ignore le son pendant le bip, latence réseau comprise.
        # Après le mot de réveil, la fin du mot traîne encore : on ignore 0,3 s de plus,
        # sinon Speech-to-Phrase la colle au début de la phrase et ne reconnaît plus rien.
        self.sourd_jusqua = time.time() + (0.6 if origine == "bouton Parler" or origine.startswith("téléphone") else 0.9)
        self.tampon = np.zeros(0, dtype=np.int16)
        await self.envoyer(etat="ecoute")

    async def recevoir_audio(self, octets):
        self.ecoute_reveil = True
        if time.time() < self.sourd_jusqua or self.etat == "reflexion":
            return
        self.tampon = np.concatenate([self.tampon, np.frombuffer(octets, dtype=np.int16)])
        while len(self.tampon) >= BLOC:
            bloc, self.tampon = self.tampon[:BLOC], self.tampon[BLOC:]
            await self.bloc(bloc)

    async def bloc(self, bloc):
        niveau = float(np.sqrt(np.mean((bloc / 32768.0) ** 2)))
        if self.etat == "repos":
            self.bruit = 0.95 * self.bruit + 0.05 * min(niveau, 0.05)  # bruit de fond lissé
            if self.reveil_ha:
                await self.reveil_ha.envoyer(bloc)  # la détection revient par sur_detection_ha
                return
            score = float(max(self.reveil.predict(bloc).values()))
            calib = self.moteur.calibration
            if calib:
                calib.score(score)
                if calib.bips:  # bip sur le téléphone quand un essai passe le seuil actuel
                    calib.bips -= 1
                    await self.envoyer(etat="ecoute")
                    await self.envoyer(etat="repos")
                if score >= 0.2:
                    await self.envoyer(etat="niveau", score=round(score, 2))
                return
            if score >= 0.2 and abs(score - self.dernier_score_envoye) > 0.1:
                self.dernier_score_envoye = score
                await self.envoyer(etat="niveau", score=round(score, 2))
            if score >= self.seuil:
                self.reinitialiser_reveil()
                if await self.moteur.arbitre.demander(self, score):
                    self.qui_parle = None
                    await self.commencer_ecoute(f"score {score:.2f}")
                else:
                    await self.perdu_arbitrage()
            return
        if self.etat != "ecoute":
            return
        if self.vad:
            fort = self.vad.parole(bloc.astype(np.float32) / 32768.0)
        else:
            fort = niveau > max(self.bruit * 3.5, 0.012)
        self.capture.append(bloc)
        if not self.parle:
            if fort:
                self.parle = True
            elif time.time() - self.t_ecoute > ATTENTE_MAX:
                print(f"[{self.nom}] rien entendu après le réveil")
                self.etat = "repos"
                await self.envoyer(etat="repos")
            else:
                self.capture = self.capture[-4:]  # garder 320 ms avant la parole
            return
        self.silence = 0.0 if fort else self.silence + BLOC / TAUX
        if self.silence >= (SILENCE_FIN_VAD if self.vad else SILENCE_FIN) or len(self.capture) * BLOC / TAUX > DUREE_MAX:
            await self.terminer_phrase()

    async def terminer_phrase(self):
        self.etat = "reflexion"
        signal = np.concatenate(self.capture).astype(np.float32) / 32768.0
        await self.envoyer(etat="reflexion", texte="")
        async with self.moteur.verrou:
            texte, reponse, voie, audio = await asyncio.to_thread(self.moteur.traiter, signal, self.qui_parle,
                                                                 self.cle_appareil())
        self.qui_parle = None
        await self.envoyer(etat="reponse", texte=texte, reponse=reponse, voie=voie)
        derniere = lire_journal(1)
        if derniere:  # l'historique de l'appli s'enrichit en direct, chez ceux qui ont le droit de le voir
            await self.moteur.diffuser_historique(derniere[0])
        if audio:
            duree = (len(audio) - 44) / 2 / int.from_bytes(audio[24:28], "little")
            self.sourd_jusqua = time.time() + duree + 3.0  # filet si la fin de lecture se perd
            await self.ws.send(audio)
        self.etat = "repos"
        self.reinitialiser_reveil()
        await self.envoyer(etat="repos")

    async def transcrire_pour_appareil(self, msg):
        """Transcription déportée (0.18.4, demande du 21/10/2026) : la tablette en mode « Cet
        appareil » garde réveil, détection de parole et dictionnaire, mais confie la phrase découpée au
        moteur de ce serveur. Son brut PCM 16 bits, 16 kHz, mono, en base64, 20 s au plus."""
        import base64
        ident, moteur = msg.get("id"), str(msg.get("moteur") or "")
        permis = self.moteur.capacites()["transcription"]
        if moteur and moteur not in permis:
            await self.envoyer(etat="transcrit", id=ident, texte="", erreur=f"moteur {moteur} indisponible ici",
                               moteurs=permis)
            return
        try:
            brut = base64.b64decode(str(msg.get("pcm", "")))
        except Exception:
            brut = b""
        if not brut or len(brut) > 2 * TAUX * 20:
            await self.envoyer(etat="transcrit", id=ident, texte="", erreur="son absent ou trop long")
            return
        signal = np.frombuffer(brut[: len(brut) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
        t = time.perf_counter()
        async with self.moteur.verrou_stt:
            texte, source = await asyncio.to_thread(self.moteur.transcrire, signal, moteur or None)
        ms = round((time.perf_counter() - t) * 1000)
        print(f"[{self.nom}] transcription déportée {source} : {ms} ms pour {len(signal) / TAUX:.1f} s, {A.pour_console(texte)}")
        await self.envoyer(etat="transcrit", id=ident, texte=texte, moteur=source, ms=ms)

    async def repondre_sante(self, msg):
        """Résumé de santé pour l'écran de la tablette (0.19.0). Aucune valeur dans le journal.
        Refusé, sans appel à sante-api, en clair ou pour une clé hors de SANTE_PERSONNES."""
        ident = msg.get("id")
        refus = self.moteur.refus_sante(self)
        if refus:
            print(f"[{self.nom}] santé : refusé ({refus})")
            await self.envoyer(etat="sante", id=ident, erreur=refus)
            return
        try:
            donnees = await self.moteur.sante.resume()
        except SA.ErreurSante as e:
            print(f"[{self.nom}] santé : {e}")
            await self.envoyer(etat="sante", id=ident, erreur=str(e))
            return
        except Exception as e:  # le texte d'une exception pourrait citer une valeur : seulement sa classe
            print(f"[{self.nom}] santé : erreur inattendue ({e.__class__.__name__})")
            await self.envoyer(etat="sante", id=ident, erreur=f"erreur inattendue ({e.__class__.__name__})")
            return
        print(f"[{self.nom}] santé : résumé servi ({SA.jours_renseignes(donnees)} jours)")
        await self.envoyer(etat="sante", id=ident, donnees=donnees)
        # L'écran santé est ouvert : l'historique se charge en tâche de fond s'il n'est pas déjà là.
        if self.moteur.refus_sante_hist(self) is None:
            self.moteur.sante_hist.prechauffer()

    async def repondre_sante_hist(self, msg):
        """Historique de santé pour les onglets de la tablette (0.20.0). Une ligne de journal par
        type, jamais de date, d'identifiant ni de valeur. Refusé sans lecture, comme « sante »."""
        genre, ident = msg.get("type"), msg.get("id")
        refus = self.moteur.refus_sante_hist(self)
        if refus:
            print(f"[{self.nom}] santé : refusé ({refus})")
            await self.envoyer(etat=genre, id=ident, erreur=refus)
            return
        try:
            donnees = await self.moteur.sante_hist.repondre(msg)
        except SA.ErreurSante as e:
            print(f"[{self.nom}] santé : {e}")
            await self.envoyer(etat=genre, id=ident, erreur=str(e))
            return
        except Exception as e:  # le texte d'une exception pourrait citer une valeur : seulement sa classe
            print(f"[{self.nom}] santé : erreur inattendue ({e.__class__.__name__})")
            await self.envoyer(etat=genre, id=ident, erreur=f"erreur inattendue ({e.__class__.__name__})")
            return
        print(f"[{self.nom}] santé : {SH.JOURNAL[genre]}")
        await self.envoyer(etat=genre, id=ident, donnees=donnees)

    async def repondre_meteo_mer(self, msg):
        """Prévisions marines du plan d'eau pour la page « Mer » (0.22.0). Aucune donnée
        personnelle : servi à toute connexion, chiffrée ou non. Une ligne de journal par réponse."""
        ident, mer = msg.get("id"), getattr(self.moteur, "meteo_mer", None)
        if mer is None:
            await self.envoyer(etat="meteo_mer", id=ident, erreur="météo marine éteinte sur ce serveur")
            return
        try:
            donnees = await mer.donnees()
        except MM.ErreurMer as e:
            print(f"[{self.nom}] mer : {e}")
            await self.envoyer(etat="meteo_mer", id=ident, erreur=str(e))
            return
        except Exception as e:  # jamais d'exception brute vers la tablette : seulement sa classe
            print(f"[{self.nom}] mer : erreur inattendue ({e.__class__.__name__})")
            await self.envoyer(etat="meteo_mer", id=ident, erreur=f"erreur inattendue ({e.__class__.__name__})")
            return
        print(f"[{self.nom}] mer : {mer.bilan()}")
        await self.envoyer(etat="meteo_mer", id=ident, donnees=donnees)

    async def repondre_vent_mesure(self, msg):
        """Vent mesuré sur le plan d'eau pour la page « Vent mesuré » (0.24.0). Aucune donnée
        personnelle : servi à toute connexion, chiffrée ou non. Une ligne de journal par réponse."""
        ident, vent = msg.get("id"), getattr(self.moteur, "vent_mesure", None)
        if vent is None:
            await self.envoyer(etat="vent_mesure", id=ident, erreur="vent mesuré éteint sur ce serveur")
            return
        try:
            donnees = await vent.donnees()
        except VM.ErreurVent as e:
            print(f"[{self.nom}] vent : {e}")
            await self.envoyer(etat="vent_mesure", id=ident, erreur=str(e))
            return
        except Exception as e:  # jamais d'exception brute vers la tablette : seulement sa classe
            print(f"[{self.nom}] vent : erreur inattendue ({e.__class__.__name__})")
            await self.envoyer(etat="vent_mesure", id=ident, erreur=f"erreur inattendue ({e.__class__.__name__})")
            return
        print(f"[{self.nom}] vent : {vent.bilan()}")
        await self.envoyer(etat="vent_mesure", id=ident, donnees=donnees)

    async def repondre_llm(self, msg):
        texte = str(msg.get("texte", "")).strip()
        if not texte:
            await self.envoyer(etat="llm", reponse="", actions=[], erreur="texte vide")
            return
        personne = self.personne_du_message(msg)
        print(f"[{self.nom}] LLM demandé par l'appareil : {A.pour_console(texte)}" + (f" (personne : {personne})" if personne else ""))
        async with self.moteur.verrou:
            res = await asyncio.to_thread(self.moteur.llm_texte, texte, bool(msg.get("essai", True)),
                                          personne, self.cle_appareil())
        await self.envoyer(etat="llm", **res)
        derniere = lire_journal(1)
        if derniere:
            await self.moteur.diffuser_historique(derniere[0])

    async def recevoir_texte(self, texte):
        try:
            msg = json.loads(texte)
        except (ValueError, RecursionError):  # JSONDecodeError, ou imbrication démesurée
            return
        if not isinstance(msg, dict):  # [], "x", 3 : rien à faire, sans lever d'exception
            return
        genre = msg.get("type")
        role = acces.role_effectif(self.identite, getattr(self.moteur, "appareils", None))
        if isinstance(genre, str) and genre in TYPES_ADMINISTRATEUR and role != "administrateur":
            print(f"[{self.nom}] message « {genre} » refusé : réservé à un administrateur")
            await self.envoyer(etat="refuse", type=genre, message="réservé à un administrateur")
            return
        # Liste blanche par rôle (0.39.0), sur le port chiffré seulement : le port en clair (ancien accès ?jeton=)
        # garde son comportement d'avant. Un type absent de la table est refusé même si le serveur sait le traiter.
        # Le journal ne reçoit que le type et le rôle, jamais le contenu du message.
        if getattr(self, "chiffre", False) and not acces.type_permis(role, genre):
            print(f"[{self.nom}] message « {nom_de_type(genre)} » refusé : non permis au rôle {role}")
            if not isinstance(genre, str):  # type absent ou mal formé : ignoré sans réponse, comme avant
                return
            if genre.startswith("sante"):  # l'appli attend la réponse de la requête (etat + id) : même forme que le refus fin
                await self.envoyer(etat=genre[:40], id=msg.get("id"), erreur="santé non permise pour cet appareil")
            else:
                await self.envoyer(etat="refuse", type=genre[:40], message="type de message non permis pour ce rôle")
            return
        if msg.get("type") == "lecture_finie":
            self.sourd_jusqua = time.time() + 0.3
            self.tampon = np.zeros(0, dtype=np.int16)
            self.reinitialiser_reveil()
        elif msg.get("type") == "parler" and self.etat == "repos":
            self.qui_parle = self.personne_du_message(msg)
            await self.commencer_ecoute("bouton Parler")
        elif msg.get("type") == "reveil" and self.etat == "repos" and time.time() >= self.sourd_jusqua:
            self.ecoute_reveil = True
            # Le téléphone a entendu le mot de réveil lui-même et n'envoie le son qu'à partir de maintenant :
            # même pause que pour le bouton (bip du téléphone). Arbitrage si plusieurs l'ont entendu.
            try:
                score = float(msg.get("score") or 0.5)
            except (TypeError, ValueError):
                score = 0.5
            if await self.moteur.arbitre.demander(self, score):
                self.qui_parle = self.personne_du_message(msg)
                await self.commencer_ecoute(f"téléphone, score {msg.get('score')}")
            else:
                await self.perdu_arbitrage()
        elif msg.get("type") == "transcrire":
            asyncio.create_task(self.transcrire_pour_appareil(msg))
        elif msg.get("type") == "vision":
            async def repondre_vision():
                async with self.moteur.verrou_vision:  # un détecteur OpenCV n'est pas réentrant
                    rep = await asyncio.to_thread(VI.traiter_message, self.moteur.vision, msg)
                await self.envoyer(**rep)
            asyncio.create_task(repondre_vision())
        elif msg.get("type") == "sante":
            asyncio.create_task(self.repondre_sante(msg))
        elif isinstance(genre, str) and genre in SH.TYPES:  # {"type": []} ne doit pas lever TypeError
            asyncio.create_task(self.repondre_sante_hist(msg))
        elif msg.get("type") == "meteo_mer":
            asyncio.create_task(self.repondre_meteo_mer(msg))
        elif msg.get("type") == "vent_mesure":
            asyncio.create_task(self.repondre_vent_mesure(msg))
        elif msg.get("type") == "ha":
            async def repondre_ha():
                await self.envoyer(**await asyncio.to_thread(passerelle_ha, self.moteur, msg, self.identite))
            asyncio.create_task(repondre_ha())
        elif msg.get("type") in ("appareils", "appairer", "refuser_appareil", "revoquer", "changer_role",
                                 "changer_personne", "inviter", "annuler_invitation"):
            # Traitement commun avec la page d'administration (administration.py). Le code d'invitation n'est
            # montré que dans la page : un satellite qui demande « inviter » est refusé.
            for rep in await administration.gerer_appareils(self.moteur, msg, self.nom, courant=self):
                await self.envoyer(**rep)
        elif msg.get("type") == "llm":
            asyncio.create_task(self.repondre_llm(msg))
        elif msg.get("type") == "manque":
            # Raté du dictionnaire sur un appareil en mode « Cet appareil » : centralisé ici.
            entree = {k: v for k, v in msg.items() if k != "type"}
            await asyncio.to_thread(A.ajouter_jsonl, A.MANQUES, {"origine": self.nom, **entree})
            await self.envoyer(etat="manque", message="noté")
        elif msg.get("type") == "retour":
            await self.envoyer(etat="retour", message=await asyncio.to_thread(self.moteur.noter_retour, msg, self.nom))
        elif msg.get("type") == "manques":
            n = max(1, min(int(msg.get("n", 200)), 2000))
            await self.envoyer(etat="manques", manques=A.lire_jsonl(A.MANQUES, n), retours=A.lire_jsonl(A.RETOURS, n))
        elif msg.get("type") == "historique":
            n = max(1, min(int(msg.get("n", 30)), 200))
            appareils = getattr(self.moteur, "appareils", None)
            personne = acces.personne_effective(self.identite, None, appareils)
            cle = self.cle_appareil()

            def visibles():  # les dernières n entrées que CE destinataire peut voir (filtre avant la coupe à n)
                lignes = entrees_visibles(lire_journal(max(n * 5, 200)), role, self.identite, cle, personne)
                return [entree_historique(l, self.moteur.noms) for l in lignes[:n]]
            await self.envoyer(etat="historique", entrees=await asyncio.to_thread(visibles))
        elif msg.get("type") == "transcription":
            print(f"[{self.nom}] transcription demandée : {msg.get('choix')}")
            asyncio.create_task(self.moteur.changer_stt(msg.get("choix")))
        elif msg.get("type") == "mode":
            print(f"[{self.nom}] bascule de mode demandée : {msg.get('choix')}")
            asyncio.create_task(self.moteur.changer_mode(msg.get("choix")))
        elif msg.get("type") == "cerveau":
            print(f"[{self.nom}] bascule de cerveau demandée : {msg.get('choix')}")
            asyncio.create_task(self.moteur.changer_cerveau(msg.get("choix")))


async def suivre_satellite(sat, ws, moteur, nom):
    """Vie d'une connexion déjà ajoutée à moteur.satellites : messages d'accueil, puis boucle de
    réception. Le satellite est retiré dans tous les cas (fermeture, coupure pendant l'accueil, erreur
    inattendue) : un satellite fantôme compterait encore parmi ceux au repos de l'arbitre."""
    try:
        await sat.envoyer(etat="repos", version=A.VERSION)
        await sat.envoyer(**moteur.etat_cerveau())
        await sat.envoyer(**moteur.etat_mode())
        await sat.envoyer(**moteur.etat_stt())
        await sat.envoyer(**moteur.capacites(sat))
        async for message in ws:
            if isinstance(message, (bytes, bytearray)):
                await sat.recevoir_audio(message)
            else:
                await sat.recevoir_texte(message)
    except websockets.ConnectionClosed:
        pass
    except Exception as e:  # le texte d'une exception pourrait citer une valeur : seulement sa classe
        print(f"[{nom}] connexion coupée sur une erreur inattendue ({e.__class__.__name__})")
    finally:
        moteur.satellites.discard(sat)
        try:
            if getattr(sat, "reveil_ha", None):
                await sat.reveil_ha.fermer()
        except Exception as e:
            print(f"[{nom}] fermeture du réveil HA en échec ({e.__class__.__name__})")
        print(f"[{nom}] satellite déconnecté")


def avertir_modeles_manquants(racine=None, sortie=None):
    """Au démarrage : affiche le message des modèles absents (voix) avec la commande qui les récupère.

    Avertissement seulement, le démarrage continue. Rien n'est dit si VOIX désigne une autre voix."""
    if os.getenv("VOIX"):
        return True
    try:
        from outils import telecharger_modeles as TM
    except ImportError:
        return True
    return TM.verifier_au_demarrage("serveur", racine or TM.RACINE, sortie)


async def servir(args):
    # Un jeton par personne : SATELLITE_JETON (le propriétaire, proprietaire.cle de maison.json) et
    # SATELLITE_JETON_<NOM> pour les autres.
    # Supprimer la ligne d'une personne dans poc/.env coupe son accès au prochain démarrage.
    jetons = {v.strip(): (k[len("SATELLITE_JETON_"):].lower() if k != "SATELLITE_JETON" else maison.CLE_PROPRIETAIRE)
              for k, v in os.environ.items() if k.startswith("SATELLITE_JETON") and len(v.strip()) >= 16}
    if not jetons:
        sys.exit("SATELLITE_JETON absent ou trop court dans poc/.env")
    moteur = Moteur(args.essai)
    moteur.appareils = acces.Appareils(A.DONNEES, jetons)
    A.ROLE_DE = lambda identite: acces.role_effectif(identite, moteur.appareils)  # rôle écrit dans le journal
    print("  jetons fixes acceptés : "
          + ", ".join(f"{n} ({acces.role_effectif(n, moteur.appareils)})" for n in sorted(set(jetons.values()))))
    for phrase in acces.avertissements_roles():
        print(f"  attention, {phrase}")
    print(f"  appareils appairés : {', '.join(a['nom'] for a in moteur.appareils.liste) or 'aucun'}")
    ancien_acces = acces.ancien_acces_permis(os.getenv("JARVIS_ANCIEN_ACCES"))
    reseaux = acces.reseaux_autorises()
    adresses = acces.adresses_ecoute()
    contexte_tls = None
    if args.port_tls:
        cert, cle, moteur.empreinte_tls = acces.certificat(A.DONNEES)
        contexte_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexte_tls.load_cert_chain(cert, cle)
        print(f"  port chiffré {args.port_tls}, empreinte de la clé sha256/{moteur.empreinte_tls}")
    connecte = asyncio.Event()
    seuil = {"valeur": args.seuil}

    async def calibrer():
        moteur.calibration = Calibration(seuil["valeur"])
        nouveau = await moteur.calibration.deroule(connecte)
        if nouveau is not None:
            rep = await asyncio.to_thread(input, f"Enregistrer le seuil {nouveau:.2f} dans poc/.env ? (o/n) ")
            if rep.strip().lower().startswith("o"):
                enregistrer_seuil(nouveau)
                seuil["valeur"] = nouveau
                for sat in moteur.satellites:
                    sat.seuil = nouveau
                print(f"Seuil {nouveau:.2f} enregistré et appliqué.")
        moteur.calibration = None
        print("Calibrage terminé, le serveur reprend son fonctionnement normal.\n")

    async def appairage(ws, chemin):
        """Nouveau téléphone sans jeton, seulement sur le port chiffré : un administrateur connecté accepte la
        demande, ou, quand il n'y en a aucun (amorçage), le code à 8 chiffres écrit dans le journal du serveur."""
        ip = ws.remote_address[0]
        demande = parse_qs(urlparse(chemin).query).get("nom", [""])[0]
        futur = asyncio.get_running_loop().create_future()
        ident, code, nom = moteur.appareils.demande(demande, ip, futur)
        sans_admin = not moteur.admin_connecte()
        amorcage = sans_admin and acces.adresse_locale(ip)
        print(f"demande d'appairage de « {nom} » ({ip}), code {code}"
              + (", aucun administrateur connecté" if sans_admin else ""))
        message = "Accepte cette demande depuis un appareil déjà connecté"
        invitation = moteur.appareils.invitation.valide()
        if invitation:  # code à 6 chiffres affiché dans Home Assistant : prime, même avec un administrateur connecté
            message = "Saisis le code affiché dans Home Assistant"
        if amorcage and not invitation:
            code_amorcage, nouveau = moteur.appareils.amorcage.ouvrir()
            if code_amorcage and nouveau:
                print(f"CODE D'AMORÇAGE pour « {nom} » ({ip}) : {code_amorcage} "
                      f"(à saisir sur le téléphone, valable {acces.Amorcage.DUREE // 60} min, "
                      f"{acces.Amorcage.ESSAIS} essais, une seule fois)")
            elif code_amorcage:
                print("code d'amorçage déjà affiché plus haut dans ce journal, toujours valable")
            message = ("Aucun appareil administrateur n'est connecté : saisis le code d'amorçage écrit dans le "
                       "journal du serveur" if code_amorcage else
                       "Aucun appareil administrateur n'est connecté. Un code d'amorçage vient d'être refusé "
                       "ou expiré, réessaie dans une minute")
        await ws.send(json.dumps({"etat": "appairage", "code": code, "id": ident, "message": message,
                                  "amorcage": bool(amorcage or invitation)}, ensure_ascii=False))
        # Le code n'est dit qu'aux administrateurs, qui seuls peuvent accepter la demande.
        await moteur.diffuser({"etat": "appairage_demande", "id": ident, "nom": nom, "code": code}, administrateurs=True)

        async def ecouter():
            """Saisies du code d'amorçage envoyées par le téléphone pendant l'attente."""
            try:
                async for brut in ws:
                    try:
                        msg = json.loads(brut)
                    except (ValueError, RecursionError):
                        continue
                    if not isinstance(msg, dict) or msg.get("type") != "amorcage":
                        continue
                    chiffres = re.sub(r"[^0-9]", "", str(msg.get("code") or ""))
                    if len(chiffres) == acces.Invitation.LONGUEUR:  # code d'invitation, jamais écrit dans le journal
                        role, restant = moteur.appareils.invitation.verifier(chiffres, ip=ip)  # essais comptés par adresse (0.39.0)
                        if role:
                            print(f"invitation acceptée pour « {nom} » ({ip}), rôle {role}")
                            moteur.appareils.accepter(ident, role)
                            await administration.notifier_pages(moteur)
                            return
                        print(f"invitation refusée pour « {nom} » ({ip}) : code faux ou expiré, "
                              f"{restant} essai(s) restant(s)")
                        await ws.send(json.dumps({"etat": "amorcage_refuse", "restant": restant}, ensure_ascii=False))
                        continue
                    if not amorcage or moteur.admin_connecte():
                        await ws.send(json.dumps({"etat": "amorcage_refuse", "restant": 0,
                                                  "message": "amorçage impossible : un administrateur est connecté "
                                                             "ou l'appareil n'est pas sur le réseau local"},
                                                 ensure_ascii=False))
                        continue
                    ok, restant = moteur.appareils.amorcage.verifier(msg.get("code"))
                    if ok:
                        print(f"amorçage accepté pour « {nom} » ({ip})")
                        moteur.appareils.accepter(ident)
                        return
                    print(f"amorçage refusé pour « {nom} » ({ip}) : code faux, {restant} essai(s) restant(s)")
                    await ws.send(json.dumps({"etat": "amorcage_refuse", "restant": restant}, ensure_ascii=False))
            except Exception:
                pass  # connexion tombée en cours d'envoi : même issue qu'une fermeture
            moteur.appareils.refuser(ident)  # le téléphone a fermé : inutile d'attendre les 300 s

        lecteur = asyncio.create_task(ecouter())
        try:
            jeton = await asyncio.wait_for(futur, 300)
        except asyncio.TimeoutError:
            jeton = None
            moteur.appareils.refuser(ident)
        finally:
            lecteur.cancel()
            moteur.appareils.refuser(ident)  # sans effet si déjà accepté ou refusé
        if jeton:
            await ws.send(json.dumps({"etat": "appaire", "jeton": jeton, "nom": nom}, ensure_ascii=False))
            print(f"« {nom} » appairé")
        else:
            await ws.send(json.dumps({"etat": "appairage_refuse"}))
        await ws.close()

    async def accueil(ws, chiffre=False):
        requete = getattr(ws, "request", None)
        chemin = requete.path if requete is not None else ws.path
        if not acces.adresse_autorisee(ws.remote_address[0], reseaux):
            print(f"connexion refusée (réseau non autorisé) depuis {ws.remote_address[0]} : "
                  f"hors des réseaux {', '.join(str(r) for r in reseaux)}")
            moteur.appareils.noter_refus("réseau non autorisé", ws.remote_address[0])
            await ws.close(code=4003, reason="réseau non autorisé")
            return
        if chiffre and urlparse(chemin).path.rstrip("/") == "/appairage":
            await appairage(ws, chemin)
            return
        # Ancienne forme ?jeton= : seulement sur le port en clair et tant que JARVIS_ANCIEN_ACCES=1.
        jeton = acces.jeton_de_la_requete(requete, chemin, ancien_acces and not chiffre)
        personne, identite = moteur.appareils.identite(jeton)
        if not personne:
            if not jeton:
                cause = "jeton absent"
                detail = "aucun jeton dans la requête"
            else:
                cause = "jeton invalide"
                detail = f"jeton inconnu du serveur (empreinte {acces.empreinte(jeton)[:8]}), appairage à refaire"
            print(f"connexion refusée ({cause}) depuis {ws.remote_address[0]}"
                  f"{' (chiffré)' if chiffre else ''} : {detail}")
            moteur.appareils.noter_refus(cause, ws.remote_address[0])
            await ws.close(code=4001, reason=cause)
            return
        nom = f"{personne} {ws.remote_address[0]}" + (" (chiffré)" if chiffre else "")
        print(f"[{nom}] satellite connecté")
        sat = Satellite(ws, moteur, seuil["valeur"], nom)
        # personne : nom affiché (sert à la révocation). identite : clé unique des listes blanches
        # (le propriétaire, « camille » ou « appareil:<id> »). chiffre : liaison wss du port 8766.
        sat.personne, sat.identite, sat.chiffre = personne, identite, chiffre
        moteur.satellites.add(sat)
        connecte.set()
        await suivre_satellite(sat, ws, moteur, nom)

    async def accueil_chiffre(ws):
        await accueil(ws, chiffre=True)

    serveurs = []
    if args.port:
        serveurs.append(await websockets.serve(accueil, adresses, args.port, max_size=2 ** 22, ping_interval=20))
    if contexte_tls:
        serveurs.append(await websockets.serve(accueil_chiffre, adresses, args.port_tls, ssl=contexte_tls,
                                               max_size=2 ** 22, ping_interval=20))
    port_admin = os.getenv("JARVIS_ADMIN_PORT", "").strip()
    if port_admin.isdigit() and int(port_admin) > 0:  # appli HA : administration par Ingress, port non publié
        serveurs.append(await administration.demarrer(moteur, int(port_admin), A.VERSION))
        print(f"Administration (Ingress) sur le port {port_admin}, réservée à administration.utilisateurs_ha")
    print(f"Serveur satellite v{A.VERSION}, port {args.port}"
          + (" (ancien accès ?jeton= permis)" if ancien_acces else " (jeton en en-tête seulement)")
          + (f" et port chiffré {args.port_tls}" if contexte_tls else "")
          + f", écoute {', '.join(adresses)}, réseaux {', '.join(str(r) for r in reseaux)}"
          + f", seuil du mot de réveil {seuil['valeur']:.2f}, cerveau {moteur.cerveau_actif} "
          f"({'ESSAI, rien n est exécuté' if args.essai else 'actions réelles'}). Ctrl+C pour arrêter.")
    if args.calibrer:
        asyncio.create_task(calibrer())
    try:
        await asyncio.Future()
    finally:
        for srv in serveurs:
            srv.close()


def main():
    # poc/.env lu avant les options (0.27.3) : JARVIS_PORT_TLS y était sans effet.
    from dotenv import load_dotenv
    load_dotenv(A.ICI / ".env")
    p = argparse.ArgumentParser(description="Serveur des satellites vocaux")
    p.add_argument("--essai", action="store_true")
    p.add_argument("--port", type=int, default=8765, help="port en clair (0 pour le couper)")
    p.add_argument("--port-tls", type=int, default=int(os.getenv("JARVIS_PORT_TLS") or "8766"),
                   help="port chiffré wss (0 pour le couper)")
    p.add_argument("--seuil", type=float, default=None,
                   help="score du mot de réveil (0 à 1), sinon SEUIL_REVEIL de poc/.env, sinon 0,5")
    p.add_argument("--calibrer", action="store_true", help="calibrage guidé du mot de réveil au démarrage")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.seuil is None:
        a.seuil = float(os.getenv("SEUIL_REVEIL", "0.5"))
    avertir_modeles_manquants()
    try:
        asyncio.run(servir(a))
    except KeyboardInterrupt:
        print("Arrêt.")


if __name__ == "__main__":
    main()
