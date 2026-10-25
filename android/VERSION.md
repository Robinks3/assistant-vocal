# Assistant vocal, versions de l'appli Android

Application Android `assistant.vocal.jarvis` : écran ambiant et assistant vocal de la maison sur une tablette posée
en paysage (mode « Cet appareil » ou serveur `poc/serveur_satellite.py`), satellite vocal sur les
téléphones. La version et la date de compilation s'affichent dans la couche de service de l'accueil de la
tablette (un toucher dans le noir), dans l'en-tête des réglages, en pied de l'écran du téléphone et dans la
notification du service.

## 0.37.0 (2026-10-25), code d'invitation à 6 chiffres
- Écran Appareils : le champ de saisie accepte un code à 6 chiffres (invitation affichée dans la page d'administration
  de Home Assistant, valable 2 minutes) en plus du code à 8 chiffres du journal du serveur (amorçage). Seul le nombre de
  chiffres accepté change, le serveur départage les deux codes.
- Tests : `AppareilsTest` (longueurs de code acceptées).

## 0.36.0 (2026-10-25), lampes : l'icône bascule, la ligne déplie
- Écran des lampes : toucher le rond à gauche allume ou éteint (retour immédiat), toucher le reste de la ligne déplie
  le volet de réglage et un second toucher le replie. Le volet s'ouvre sur l'onglet du mode réel de la lampe (Couleur
  si elle est en couleur, Blanc sinon), même après un choix d'onglet fait lors d'une ouverture précédente. Une lampe
  sans réglage (marche / arrêt seulement) ou hors ligne garde le toucher de ligne qui bascule. Le chevron n'est plus
  qu'un indice. Disposition retenue par Alex sur maquette (variante C) : le chevron suit le nom et la piste d'intensité
  prend toute la largeur restante de la ligne, toujours visible.
- Volet : onglets, pastilles et pistes à 48 dp au moins, valeur actuelle en tête (« 2700 K chaud » ou nom de la
  couleur), y compris pour une lampe à un seul mode (valeur hors des onglets) et éteinte (dernière valeur, sinon
  « éteinte »). Descriptions de contenu et rôle bouton pour TalkBack, rond masqué à TalkBack quand la ligne fait la même
  chose (lampe sans réglage).
- Tests : `ReglageLampeTest` (geste de la ligne, onglet par défaut, nom de teinte, valeur du volet).

## 0.35.0 (2026-10-25), reconnexion robuste
- Découverte (`Decouverte.kt`) : l'adresse configurée reste l'identité du serveur (jeton et clé retenus rangés
  dessous), mais la connexion essaie dans l'ordre la dernière cible qui a répondu, les noms d'hôte de
  `android_hotes_pc` et `android_hotes_ha` (`maison.json`, par exemple un nom mDNS), puis l'adresse enregistrée. Une
  clé de serveur reste épinglée par identité : une autre cible doit présenter la même clé.
- Jeton refusé (4001) : la cause est affichée (révoqué, absent, inconnu), sur l'accueil, l'écran ambiant et l'orbe, avec
  une reconnexion ralentie à 15 s, et l'écran Appareils lance tout seul le réappairage à son ouverture.
- Amorçage : quand le serveur annonce qu'aucun administrateur n'est connecté, l'écran Appareils affiche un champ pour
  le code à 8 chiffres écrit dans le journal du serveur.
- Diagnostic : l'écran Appareils dit pourquoi une connexion échoue (réseau, certificat, jeton, réseau refusé, réponse
  inattendue), avec en plus les derniers refus notés par le serveur.
- Tests : `DecouverteTest`.

## 0.34.0 (2026-10-25), volet de réglage des lampes
- Chaque ligne de lampe de l'écran Maison a un chevron qui ouvre deux onglets. Blanc : quatre pastilles (Bougie, Chaud, Neutre, Froid) et une piste de kelvins bornée à la plage réelle de la lampe. Couleur : huit pastilles et une piste de teinte.
- Les pistes passent par `Cadence` (un ordre toutes les 300 ms, valeur finale au relâchement). L'état affiché sous le nom ajoute le blanc (« 2700 K chaud ») ou « couleur ».
- Confirmation étendue : `Attentes.conforme` et `Maison.conforme` vérifient le mode, les kelvins à 100 K près et la teinte à 8 degrés près (bouclage 0/360).
- Nouveau `ReglageLampe.kt` et tests `ReglageLampeTest`. Demande le serveur 0.32.0 pour la confirmation des couleurs (sans lui, rien n'est démenti).

## 0.33.1 (2026-10-25)
- `Securite.kt` : `floor_id` et `label_id` refusés comme cibles, à l'identique de `securite.py` (cas communs).

## 0.33.0 (2026-10-25)
- Écran Musique : une enceinte hors ligne (`unavailable` ou `unknown`) ne se coche plus. Sa ligne dit « hors
  ligne » en orange, la barre de volume est grisée et le pourcentage vaut « - ». Un toucher donne « La cuisine
  est hors ligne : vérifie qu'elle est branchée et sur le Wi-Fi. » au lieu d'un `media_player.join` qui
  échouait et d'une case qui revenait seule après 5 s. La ligne redevient normale quand l'enceinte revient.
- Carte « en cours » de l'accueil : elle suit d'abord une enceinte de la sortie du son qui joue (le meneur
  d'abord, reconnu en tête de `group_members`, `buffering` compris) au lieu du premier lecteur en lecture. Elle affichait 100 % (volume du compte Spotify) quand les
  Enceintes étaient à 30 %.
- Tests `SortieSonTest.enceinteHorsLigneNeSeCochePas` et `CarteEnCoursSuiviTest`. versionCode 61.

## 0.32.3 (2026-10-25)
- Écran Santé réservé au propriétaire : le nom du profil se compare sans accents ni casse, comme le nom
  des pièces (`personneNormalisee`). Un profil « Helene » vaut « Hélène ».
- Heures calmes : le refus de musique et l'écran Musique disent la plage tirée de `heures_calmes`
  (`Securite.PLAGE_CALME`) au lieu de « entre minuit et 9 h » figé.
- Test `SanteTest` (profil accentué). versionCode 60.

## 0.32.2 (2026-10-25)
- Phrases apprises sorties de l'export versionnable : `android/outils/exporter_dictionnaire.py` n'écrit plus
  dans `genere/android/dictionnaire.json` du dossier de configuration que ce qui vient de `commandes.yaml`.
  Les phrases apprises de la machine partent dans `genere/android/dictionnaire_appris.json` du dossier de
  données (`JARVIS_DONNEES`, `poc/` par défaut, `poc/genere/` ignoré par git), réécrit même vide pour ne
  jamais embarquer d'anciennes phrases. `build.gradle.kts` ajoute ce dossier aux assets s'il existe
  (`-PdonneesDossier=...` pour un autre), jamais avec `config-exemple/`. `DictionnaireLocal` fusionne les
  deux fichiers, une phrase apprise ne remplace jamais une phrase de `commandes.yaml`.
- Option `--sortie FICHIER` de l'exporteur : `test_export_exemple_a_jour` compare l'export d'exemple refait
  dans un dossier temporaire et ne réécrit plus `config-exemple/genere/android/dictionnaire.json` suivi par git.
- Jeton `export` commun aux deux fichiers d'un même export (absent de l'exemple) : `DictionnaireLocal` ignore
  des phrases apprises venues d'un autre export (fichier périmé, autre machine, autre maison). Un fichier de
  phrases apprises abîmé n'ajoute rien et ne casse plus le dictionnaire. L'étape « Dictionnaire » du
  déroulé dit ce qui est arrivé aux phrases apprises (nombre, ignorées, illisibles).
- Exporteur en `argparse` (`--exemple`, `--sortie`, `--donnees`), argument inconnu refusé. Un
  `JARVIS_DONNEES` ou `--donnees` relatif part de la racine du dépôt, comme `-PdonneesDossier` dans
  `build.gradle.kts`. Gradle compare les dossiers par chemin canonique (exemple, dossier de données égal à
  celui de la configuration) et écrit à la compilation le dossier de phrases apprises embarqué.
- Garde-fou : `dictionnaire_appris.json` refusé dans un commit.
- Tests : `test_phrases_apprises_hors_export_de_configuration` (jeton commun, phrase déjà couverte par
  `commandes.yaml` laissée hors de l'export à part), `test_export_donnees_relatives_depuis_la_racine`
  (Python), `phrasesApprisesFusionneesSansRemplacerLaConfiguration` (aucune tolérance aux fautes) et
  `phrasesApprisesEtrangeresOuAbimeesIgnorees` (Kotlin). versionCode 59.

## 0.32.1 (2026-10-25)
- Passerelle HA qui ne se remettait pas d'un redémarrage de l'appli Home Assistant : la poignée de main
  WebSocket n'avait aucun délai (`readTimeout(0)` sans `callTimeout`), un serveur qui accepte la connexion
  puis se tait bloquait l'appel pour toujours et la reconnexion n'était jamais tentée. Toutes les liaisons
  WebSocket de l'appli (passerelle HA, satellite, transcription, vision, appareils) passent par
  `Confiance.clientWebSocket()` : poignée de main bornée à 15 s, liaison montée sans délai de lecture, ping
  toutes les 20 s.
- Test `ConfianceWebSocketTest` : serveur muet après accept, liaison montée qui survit au délai. versionCode 58.

## 0.32.0 (2026-10-25)
- Plus de plafond de volume de 50 % : `Securite.VOLUME_MAX` vient de `securite.plafond_volume` de
  `maison.json` (1 sans plafond, le défaut), mêmes règles que le serveur, cas communs compris.
- Pistes de volume de l'accueil, de la maison en grand et de l'écran Musique de 0 au volume permis, 100 %
  sans plafond. Trait et mention du plafond seulement quand un plafond est réglé. Les crans restent sous le
  plafond (borné après l'arrondi), et un plafond de 0 % ne fait plus planter le calcul de la piste.
- Monter le son par pas reste converti en volume précis, borné au volume permis.
- Tests avec et sans plafond (`SecuriteTest`, `AccueilDispositionTest`, `MaisonEnGrandTest`). versionCode 57.

## 0.31.0 (2026-10-25)
- Nom affiché de l'assistant lu dans la section `assistant` de `maison.json` (`ConfigMaison.NOM_ASSISTANT`) :
  nom de l'appli sous l'icône (`resValue app_name` dans `build.gradle.kts`), textes de l'accueil, des
  réglages, de la météo, de la musique, de la vision et des notifications, en formulations neutres.
  « Assistant » sans la section.
- Identifiants neutres : pont de la page 3D `window.maison3d` et `Maison3dAndroid` (page 3D à régénérer
  avec `carte/3d/generer_3d.py`), mot de réveil personnalisé `perso` (`segmentPerso`, `CLE_SEUIL_PERSO`).
  L'ancien seuil `seuil_reveil_assistant` est recopié une fois au démarrage, l'ancien choix enregistré reste
  lu comme mot personnalisé.
- Sons d'écoute : commentaire ICMT des WAV neutre, son inchangé.
- Test `ConfigMaisonTest`. versionCode 56.

## 0.30.1 (2026-10-24)
- Premier instantané du moteur, sans historique. La configuration de la maison (`maison.json`,
  dictionnaire exporté, page 3D, trait de côte, mot de réveil) vient du dossier de configuration et
  entre dans l'APK à la compilation. Une APK est refusée sans lui. La numérotation continue celle du
  projet d'origine. versionCode 55.
