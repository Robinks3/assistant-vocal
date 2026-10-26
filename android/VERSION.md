# Assistant vocal, versions de l'appli Android

Application Android `assistant.vocal.jarvis` : écran ambiant et assistant vocal de la maison sur une tablette posée
en paysage (mode « Cet appareil » ou serveur `poc/serveur_satellite.py`), satellite vocal sur les
téléphones. La version et la date de compilation s'affichent dans la couche de service de l'accueil de la
tablette (un toucher dans le noir), dans l'en-tête des réglages, en pied de l'écran du téléphone et dans la
notification du service.

## 0.45.0 (2026-10-26), durcissement
Mineure (versionCode 83). Session S-D5 du plan, pendant du serveur 0.45.1.
- Les extras d'intention `test_*` de l'activité principale ne sont lus que dans un build de débogage.
- Un fichier `network_security_config` refuse le trafic en clair, sauf la boucle locale de l'appareil. Le repli
  sur l'ancien port en clair 8765 et une adresse ws:// saisie à la main ne passent plus : seul wss (8766) reste.

## 0.44.0 (2026-10-26), mesures par pièce
Mineure (versionCode 82). Session S-L6 du plan, pendant du serveur 0.45.0.
- Les mesures des pièces (température, humidité, CO2, particules fines) sont lues toutes les 60 secondes et
  s'affichent sur le panneau de la maison en grand, avec le mot de l'air et sa couleur.
- Question à la voix comprise en local : « quelle température dans le salon », « comment est l'air de la chambre ».
  Une pièce protégée répond « pièce protégée », sans valeur.
- La vue 3D ne montre pas encore les mesures (lot suivant).

## 0.43.1 (2026-10-26), notes du LLM de l'appareil
Correctif (versionCode 81). Session S-D7 du plan, pendant du serveur 0.44.1.
- Le LLM de l'appareil lit `llm.notes` de la configuration exportée et ajoute la note entre crochets après le
  nom de l'appareil dans sa consigne, comme le LLM du serveur. Sans notes, la consigne est inchangée.
- Pour qu'une note ajoutée ou changée arrive sur la tablette, relancer
  `python android/outils/exporter_dictionnaire.py` puis recompiler.

## 0.43.0 (2026-10-26), lampes et télévision à la voix sur la tablette
Nouveauté (versionCode 80). Session S-L4 du plan, pendant du serveur 0.44.0. Numérotée 0.43.0 à la fusion,
après la 0.42.0 de S-L5 (le lot avait réservé la 0.41.0).
- Nouvel objet `CommandesDynamiques.kt`, même logique que `poc/commandes_dynamiques.py` : `selon_etat` et `kelvin_pas`.
  `MoteurLocal.comprendre` lit l'état des entités concernées par la passerelle (`GET /api/states/<entité>`, seulement
  hors mode essai), résout les actions après le choix de la personne et avant `Securite.verifier`, qui voit donc des
  actions ordinaires. Une action dynamique qui ne laisse rien à faire dit sa réponse (« Il n'y a rien à reprendre. »).
- Le dictionnaire exporté (`genere/android/dictionnaire.json`) porte les nouvelles phrases : couleur, blanc nommé,
  luminosité, « plus chaud », télévision.
- Tests : `CommandesDynamiquesTest` (cas de `cas_dynamique.json`) et, dans `DictionnaireTest`, les phrases de
  `cas_commandes_lampes_tele.json` avec leurs pièges (rose, orange, monte, chaud), les teintes et blancs alignés sur
  `ReglageLampe`, et les listes `etats` sans booléen.

## 0.42.0 (2026-10-26), retour d'état dans la vue 3D : lampes teintées, télé, maison entière
Nouveauté (versionCode 79). Session S-L5 du plan (la 0.41.0 est réservée au lot lampes et télé à la voix). Le serveur
n'a pas changé.
- Pont `Maison3dPont` : état réduit complet envoyé à la page (allumé ou éteint, luminosité 0 à 255, volume 0 à 1,
  chaleur en kelvins bornée de 1000 à 40000 en mode température, sinon couleur RVB à trois composantes de 0 à 255).
  Une lampe indisponible ou inconnue part sans attributs, un état vide devient « unknown », une valeur mal formée est
  ignorée.
- `Maison3d.etat3d` : lampes et lecteurs multimédias, les autres appareils ne sont pas transmis. La clé de
  déduplication de l'écran Maison est l'état réduit entier, donc un changement de couleur, de chaleur ou de volume
  repart vers la page sans rechargement.
- Correspondance entité vers objet 3D lue dans `reglages.vue3d.correspondances` de `maison.json` (clés vides et clés en
  `_` ignorées). Rien de propre à un logement dans `carte/3d/`. Exemple fictif dans `config-exemple/maison.json`.
- Page 3D : halo teinté de la vraie couleur, couche neutralisante sous la tache pour qu'un blanc froid ne vire pas à
  l'orange du sol, plus de halo ni de tache dans la vue maison entière (le voile de la pièce choisie reste), état appliqué
  tout de suite quand la page est masquée (la WebView gèle `requestAnimationFrame`), une lampe allumée sans couleur
  reprend le blanc chaud.
- Tests : `Maison3dPontTest` et `Maison3dTest` complétés (format des messages, couleur, bornes, indisponible ou
  inconnu, correspondances), `test_generer_3d.py` vérifie la page générée.

## 0.40.1 (2026-10-26), correctif : l'appli 0.40.0 plantait au démarrage
Correctif (versionCode 77). Le motif `INTENTION_ROUTINE` de `RoutinesLocal.kt` portait le drapeau `(?U)`, accepté
par la JVM des tests mais refusé par Android (ICU, PatternSyntaxException) : le moteur local ne se construisait
pas et la tablette restait sans assistant.
- Limites de mot écrites à la main (lettres et chiffres Unicode, accents compris), `RegexOption.IGNORE_CASE` seul.
- Motif aligné sur celui du serveur 0.43.3 : « j'aimerais que tu crées une routine » est une création, « fais la
  routine du matin » reste un lancement, apostrophe droite ou courbe.
- Nouveau test `aucun_motif_avec_le_drapeau_u_refuse_par_android` : aucune source de l'appli ne peut plus écrire ce
  drapeau.

## 0.40.0 (2026-10-26), routines sur la tablette : « bonne nuit » PC éteint comme PC allumé
Nouveauté (versionCode 76). Session S-R3 du plan (la 0.39.0 est réservée au lot télé). Les routines vivent et
s'exécutent côté serveur (`poc/routines.py`, 0.43.x) avec la sécurité en dur et tous les contrôles existants. La
tablette garde la liste reçue pour reconnaître la phrase sur place, et confie le reste au serveur par le port chiffré.
- `RoutinesLocal.kt` (nouveau, logique pure) : liste reçue (message `routines`, phrases et variantes sous leur forme
  comparée), une liste par personne, périmée par `routines_maj`. Décision d'une phrase : routine active que la personne
  peut lancer (`routine_lancer`), routine réservée à un autre, mot « routine », création ou changement à la voix
  (`routine_texte`), sinon la chaîne ordinaire continue. La portée (« tous » ou l'auteur reconnu) est appliquée aussi ici,
  le serveur reste le juge.
- Le motif de création (`INTENTION_ROUTINE`) couvre aussi « crée-moi / fais-moi / fais / ajoute / programme / mets en
  place / enregistre / configure / prépare une routine », « peux-tu me ... une routine » et « je voudrais / je veux /
  j'aimerais (créer) une routine ». Le mot « routine » reste exigé : « fais une pause » ou « ajoute du lait à la liste »
  ne déclenchent rien.
- `MoteurLocal.kt` : les routines passent avant la météo, la palette et le dictionnaire. Avant tout envoi, la phrase
  passe par `Securite.phraseProtegee`. Étape « Routine » dans le déroulé, essai honoré (rien d'exécuté pour une phrase
  écrite en essai), échecs d'étapes affichés. Serveur injoignable : « Je ne peux pas lancer la routine sans le serveur »
  (ou « gérer les routines »), jamais de repli vers le LLM qui agirait à la place.
- Brouillon en attente (`confirmation_attendue`) : à la fin de la réponse, l'écoute se rouvre sans mot de réveil et la
  phrase suivante, dans le délai (marge de 20 s pour la lecture de la proposition), repart en `routine_texte`.
- `PasserelleHa.kt` : message `routines_maj` (rappel `routinesMaj`), capacité `routines` suivie dans `routinesDispo`
  (faux sur le repli en clair, qui refuse les routines).
- Tests : `RoutinesLocalTest` (liste reçue, portée, décision, confirmation, motif de création sur les cas communs
  `poc/tests/cas_routines.json`).
- Limite : la liste n'est pas gardée sur disque, elle est relue au démarrage de l'appli dès que le serveur répond.
- Fin de lot locale requise : APK sur la tablette, « bonne nuit » dite PC éteint puis PC allumé.
## 0.39.0 (2026-10-26), volet de réglage de la télévision (lot S-L3)
Fonction (versionCode 75). Sur le modèle du volet des lampes, un toucher sur la ligne de la télé allumée, dans la
maison en grand, déplie un volet. Un seul volet est ouvert à la fois (`teinteOuverte` est partagé avec les lampes).
- `ReglageTele.kt` (nouveau, sans Android) : lecture des tuiles dans `reglages.tele.sources` de `maison.json` (nom
  affiché et nom de la source dans Home Assistant), comparaison des sources à la forme près (« HDMI 1 » vaut « HDMI1 »),
  tuiles offertes selon la liste de sources de la télé, texte d'état, geste de la ligne, commande de source, rangées
  de quatre, bornes et texte du curseur de volume.
- `VueMaisonGrand.kt` : `LigneTele` réécrite. État sous le nom : « éteinte », « hors ligne », « allumée » ou
  « allumée, sans doute Netflix ». La source est au conditionnel parce que la lecture de la source est peu fiable sur
  cette télé. Volet : tuiles de sources (surbrillance sur la source probable), tuile Toutes qui déplie toutes les
  sources annoncées par la télé, puis un seul curseur de volume avec sa valeur en pourcentage.
- Toute commande passe par les contrôles existants : `Securite.verifier` pour le choix d'une source, et pour le
  volume le chemin de `volume()` (plafond en dur `Securite.VOLUME_MAX`, puis revérification). `Securite.kt` et
  `poc/securite.py` ne changent pas, `media_player` permettait déjà `select_source`, `volume_set`, `turn_on` et
  `turn_off`.
- Configuration : nouvelle clé `reglages.tele.sources` (copie fictive dans `config-exemple/maison.json`, documentée
  dans `docs/CONFIGURER.md`). Sans elle, le volet n'a que le volume et la tuile Toutes. Aucun identifiant réel dans
  le code.
- Limite connue : la sortie audio de la télé (barre de son ou haut-parleurs, décision 14) n'est pas lue, le curseur
  règle le volume de l'entité de la télé et le libellé reste « Volume ».
- Tests : `ReglageTeleTest` (lecture de la configuration, comparaison des sources, états, gestes, commande, rangées,
  bornes et plafond du volume). Côté serveur, `poc/tests/test_tele_volet.py` (commandes du volet acceptées par
  `acces.controler_service`, plafond en dur toujours appliqué). Le serveur ne change pas (0.43.1).
- Rendu non vérifié sur appareil (pas de compilation de l'APK dans ce worktree).

## 0.38.2 (2026-10-26), passerelle Home Assistant : reconnexion robuste et journal
Correctif (versionCode 74). Le 26/10 au soir, la tablette est restée « Maison hors ligne » après des redémarrages de
l'appli de l'assistant sur HA, jusqu'à un `am force-stop`. La passerelle ne journalisait rien, la cause exacte n'a pas
pu être lue, mais le code avait deux chemins sans relance.
- `PasserelleHa.kt` : une socket ouverte dont les capacités annoncent `passerelle_ha` absent ou faux (appli sur HA en
  cours de redémarrage, jeton pas encore chargé) restait ouverte et saine, sans échec ni relance. Un chien de garde
  propre à la passerelle (`GardeReconnexion`, contrôle toutes les 10 s, aussi à chaque `ouvrir()`) annule maintenant la
  socket et rouvre quand elle existe sans être `disponible` depuis plus de 30 s.
- Course corrigée : `onOpen`, `onMessage` et `perdu` comparaient la socket reçue à `ws` sans verrou, alors que `ws`
  n'est enregistrée qu'au retour de `newWebSocket`. Un échec ou un message arrivé avant (appli sur HA qui redémarre,
  réponse immédiate) était écarté, et la socket morte restait enregistrée, donc `ouvrir()` ne faisait plus rien.
  La comparaison se fait sous le verrou d'`ouvrir()`.
- La relance est planifiée avant le rappel `changement()`, qui est protégé : une erreur de l'écran ne peut plus la
  faire perdre.
- Journal `JarvisPasserelle` : ouverture (adresse), connexion ouverte, capacités reçues (version, disponible), perte
  avec sa raison et le délai de relance, passage sur le repli en clair, déclenchement du chien de garde, clé annoncée
  différente. Aucun jeton ni en-tête d'authentification.
- L'épinglage de clé (`Confiance`) est inchangé.
- Test : `GardeReconnexionTest` (garde sans Android). La course de socket n'a pas de test JVM : elle exige un vrai
  `WebSocket` OkHttp et un `Context` Android.

## 0.38.1 (2026-10-26), serrures et alarmes refusées par la sécurité en dur
Session S-F4 du plan 1.2.0 (versionCode 73), accompagne le serveur 0.40.0.
- `Securite.kt` : `verifier` refuse tout service ou toute cible des domaines `lock` et `alarm_control_panel`, comme
  `securite.py`. Avant, seule la passerelle du serveur les écartait (`acces.DOMAINES_INTERDITS`), la sécurité en
  dur ne les connaissait pas. Aucune règle existante ne change, la sécurité ne fait que se resserrer.
- `poc/tests/cas_securite.json` : cinq cas de refus ajoutés (service `lock` avec et sans cible, service
  `alarm_control_panel`, une serrure dans la liste de cibles d'un autre service, domaine écrit en casse mixte), lus
  à l'identique par `SecuriteTest.actions` et par `test_securite.py`.

## 0.38.0 (2026-10-26), liste blanche des services élargie
Session S-F1 du plan 1.2.0 (versionCode 72), décision D6. L'appli reçoit la table élargie dans `services_permis`
du `dictionnaire.json` exporté par le serveur 0.37.0, sans changement de code de `CerveauAppareil.kt` : son
périmètre LLM (`DOMAINES`) reste le même, le complément dynamique pris à Home Assistant reste côté serveur.
- `Securite.kt` : aucune règle ne change (`device_id`, `floor_id`, `label_id`, plafond de volume, `volume_up`,
  drapeaux). Les nouveaux cas d'action de `poc/tests/cas_securite.json` (par domaine ajouté un cas accepté et un
  refusé) sont lus par `SecuriteTest.actions`.
- `SecuriteTest.servicesDeLaListeBlanche` : le bloc `services` de `cas_securite.json` (101 cas) est vérifié
  contre le dictionnaire exporté.

## 0.37.5 (2026-10-26), dossier de compilation par système, signature facultative
Session S-D4 du plan 1.2.0 (versionCode 71). Le numéro 0.37.4 est réservé à S-D1, menée en parallèle. Aucun
changement de comportement de l'appli.
- `build.gradle.kts` (racine) : le dossier de compilation `C:/Dev/assistant-vocal-build` n'est plus imposé qu'à Windows
  (Defender et Windows Search). Ailleurs, chaque module garde son dossier `build/` standard, ignoré par git.
  `-PdossierBuild=...` reste possible partout. Le paramètre n'est plus obligatoire hors de Windows.
- `app/build.gradle.kts` : signature de publication facultative. Si `android/keystore.properties` existe (ignoré
  par git, jamais versionné), la variante release est signée avec les clés `storeFile`, `storePassword`,
  `keyAlias` et `keyPassword`, et la compilation s'arrête si l'une manque. Sans le fichier, rien ne change. Aucun
  secret dans le dépôt ni dans un script.
- `outils/pousser_canary.sh` : installe une version d'essai par `adb`, voir `docs/INSTALLER.md`.
## 0.37.4 (2026-10-26), heures calmes qui passent minuit
Session S-D1 du plan 1.2.0 (versionCode 70). La règle des heures calmes reste coupée (`HEURE_CALME_ACTIVE` à
`false`), seul son calcul change.
- `Securite.enHeureCalme(heure, debut, fin)` : une plage dont le début est après la fin (22 h à 7 h) couvre la
  soirée et le début de matinée, comme `en_heure_calme` de `securite.py`. Avant, `heure in debut until fin` ne
  couvrait jamais rien pour une telle plage.
- `Securite.verifier` accepte un paramètre `plageCalme` (début, fin) qui force la règle sur cette plage, réservé
  aux tests, sans effet sur les appels existants.
- `SecuriteTest` : trois tests lisent la section `heures_calmes_nuit` de `poc/tests/cas_securite.json` (21 h, 22 h,
  3 h, 6 h, 7 h de la plage 22 h à 7 h), partagée avec `test_securite.py`.

## 0.37.3 (2026-10-26), titre de la page Mer, mot de réveil de l'exemple
Session S-D3 du plan 1.2.0.
- `MeteoMer.kt` : le titre par défaut de la page Mer est `titre`, sinon `nom`, de la section `mer`, sinon « Mer »
  (point laissé par S-D2).
- C14 : recherche d'un prénom ou d'un « Hey Jarvis » en dur dans `java/assistant/vocal/jarvis/` et `res/` qui devrait suivre
  la configuration. Rien à faire : les seuls textes affichés sont le nom du modèle de repli (« Hey Jarvis », le nom
  réel de ce modèle) et le mot annoncé par le serveur, et les prénoms ne figurent que dans des commentaires.
  `assistant.vocal.jarvis` et les noms de fichiers ne changent pas.
- `ReveilConfigTest` : `config-exemple/` décrit maintenant le mot « assistant » (nom « Assistant »), « Hey Jarvis »
  reste le modèle de repli.

## 0.37.2 (2026-10-26), commentaires sans référence à un projet tiers
Session S-C4 du plan 1.2.0. Aucun changement visible.
- `Reconnaissance.kt` et `SatelliteService.kt` ne citent plus de projet tiers dans leurs commentaires.
- Migration de la préférence du seuil du mot de réveil personnalisé : l'ancienne clé (jusqu'à la 0.30.x) est repérée
  par son préfixe `seuil_reveil_` au lieu d'un nom en dur, puis recopiée une fois sous `seuil_reveil_perso`. Le
  résultat est le même pour une installation existante.

## 0.37.1 (2026-10-26), tests sur l'exemple fictif et pages Mer et Vent sans lieu en dur
Session S-C3 du plan 1.2.0. Aucun changement visible avec une configuration existante.
- `MeteoMer.kt`, `MeteoVent.kt`, `EcranMer.kt`, `EcranVent.kt`, `Etat.kt` et `Transcription.kt` ne citent plus de lieu
  réel. Le fuseau, les modèles, les points et le fond de carte viennent de `maison.json`.
- Les tests (accueil, appareils, maison, historique, météo, sécurité, maison 3D) utilisent les identifiants fictifs
  de l'exemple et la rade de Marseille. Les prévisions de `MeteoMerTest` sont des valeurs d'exemple.
- Le trait de côte de l'exemple est un tracé simplifié dessiné à la main.

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
  qu'un indice. Disposition retenue par le propriétaire sur maquette (variante C) : le chevron suit le nom et la piste d'intensité
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
  L'ancien seuil du mot de réveil personnalisé est recopié une fois au démarrage, l'ancien choix enregistré reste
  lu comme mot personnalisé.
- Sons d'écoute : commentaire ICMT des WAV neutre, son inchangé.
- Test `ConfigMaisonTest`. versionCode 56.

## 0.30.1 (2026-10-24)
- Premier instantané du moteur, sans historique. La configuration de la maison (`maison.json`,
  dictionnaire exporté, page 3D, trait de côte, mot de réveil) vient du dossier de configuration et
  entre dans l'APK à la compilation. Une APK est refusée sans lui. La numérotation continue celle du
  projet d'origine. versionCode 55.
