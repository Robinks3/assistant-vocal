# Assistant vocal, versions du serveur

Journal du serveur (`poc/`) et de l'appli Home Assistant (`ha-app/`). L'appli Android a le sien dans
`android/VERSION.md`. La version s'affiche au démarrage du serveur et dans les capacités annoncées aux
satellites.

## Serveur 0.38.0 (2026-10-26), rôles réels
Session S-F2 du plan 1.2.0. Le champ `role` d'`appareils.json` ne changeait aucun droit, les jetons fixes n'avaient
pas de rôle et la personne des messages `llm`, `parler` et `reveil` était reprise telle que déclarée. Désormais le
rôle de l'identité borne ses droits. Appli Android inchangée (0.38.0, versionCode 72).
- Rôle propriétaire : le rôle « propriétaire » de la conception s'appelle `administrateur` dans le code et les
  fichiers (aucun renommage de champ). Il est réservé à `proprietaire.cle` et aux clés de `acces.administrateurs`.
  Ni `changer_role`, ni une invitation, ni `appairer` ne l'attribuent (refus explicite).
- Nouvelle clé `acces.roles` (`maison.json`) : rôle de chaque jeton fixe de `poc/.env`. Un jeton absent vaut
  `habitant`, une valeur inconnue `invite`. La clé du propriétaire reste `administrateur` (valeur contraire ignorée,
  avertissement au démarrage). Le démarrage affiche le rôle de chaque jeton fixe.
- Appareils appairés : le champ `role` est effectif. Une entrée sans `role` ou au rôle inconnu vaut `invite`, sans
  réécrire le fichier. `ROLE_PAR_DEFAUT` reste `habitant` pour une acceptation ou une invitation explicites, la
  constante `ROLE_SANS_CHAMP` couvre l'absence de champ. Une entrée qui porte `administrateur` dans le fichier ne
  donne pas ce rôle.
- Nouveau champ `personne` d'un appareil : fixé par `Appareils.accepter(ident, role, personne)` ou par le message
  `changer_personne` (même garde que `changer_role`). La personne doit être un habitant connu (propriétaire, liste
  `habitants` de `maison.json`, clés de `securite.permis_personne`), sinon refus. Nouvelle liste `habitants` à la
  racine de `maison.json` et de `config-exemple/maison.json`.
- `acces.personne_effective(identite, declaree)` est l'unique décideur de la personne des messages `llm`, `parler`,
  `reveil` et `ha` (passerelle). Administrateur ou `partage` : la personne déclarée est acceptée si c'est un
  habitant connu (la valeur « inconnu » de la tablette passe, elle ne donne aucun droit). `habitant` ou `invite` :
  la déclaration est ignorée, un jeton fixe vaut sa clé, un appareil appairé vaut le champ `personne` de son
  entrée, sinon aucune. Un invité qui se déclare propriétaire n'obtient rien.
- Tous les messages de `TYPES_ADMINISTRATEUR`, plus `changer_personne`, sont refusés à toute identité dont le rôle
  effectif n'est pas `administrateur` (`acces.role_effectif`), à l'endroit unique de `recevoir_texte`. Le
  traitement commun `administration.gerer_appareils` refuse aussi, en seconde barrière.
- Export `appareils` : chaque appareil expose son `role` effectif et sa `personne`, et `roles_jetons_fixes` donne le
  rôle effectif de chaque jeton fixe. Aucun jeton ni empreinte en clair.
- Tests : `poc/tests/test_roles.py` (149 cas), `test_administration.py` et `test_aiguillage.py` adaptés.
- Hors périmètre, pour S-F3 et après : liste blanche des messages par rôle, expiration des invités à 7 jours,
  interface Android et Home Assistant des rôles.
- Transitoire : la tablette du salon porte encore le jeton du propriétaire, sa personne déclarée est donc acceptée
  jusqu'à ce qu'elle ait son propre jeton `partage`.

## Serveur 0.37.0 (2026-10-26), liste blanche des services élargie
Session S-F1 du plan 1.2.0, décision D6 du 26/10/2026 : tout ce que Home Assistant expose est permis, sauf les
cibles par `device_id`, `floor_id` et `label_id`, les domaines interdits et ce qui exige déjà une confirmation.
- `SERVICES_PERMIS` (`poc/assistant.py`) passe de 8 domaines à une table qui couvre les domaines d'équipement :
  `light`, `switch`, `fan`, `cover` (inclinaison comprise), `climate`, `humidifier`, `water_heater`, `valve`,
  `siren`, `media_player`, `music_assistant`, `vacuum`, `lawn_mower`, `camera` (marche, arrêt, détection de
  mouvement), `scene` (`turn_on`), `script`, `automation`, `input_boolean`, `input_number`, `input_select`,
  `input_text`, `input_datetime`, `input_button`, `button`, `number`, `text`, `timer`, `counter`, `remote`,
  `select` et `domaine_tele`. Un commentaire renvoie à la page `home-assistant.io/integrations/<domaine>` de
  chacun.
- Complément pris à Home Assistant : au démarrage, `GET /api/services` ajoute les services d'entité que le socle ne
  connaît pas (`HomeAssistant.charger_services`, `services_depuis_ha`). Un service n'entre que si sa cible est une
  entité de son propre domaine, sans champ qui désigne un autre appareil, hors domaines interdits et hors
  rechargements. Si Home Assistant ne répond pas, le socle statique suffit et le démarrage continue.
- Reste refusé : `device_id`, `floor_id` et `label_id` partout, les `DOMAINES_INTERDITS` (`lock`,
  `alarm_control_panel`, `homeassistant`, `hassio`, `shell_command`, `rest_command`, `python_script`, `notify`,
  `persistent_notification`, `recorder`, `system_log`), tous les `reload*`, `camera.snapshot`, `camera.record`,
  `camera.play_stream`, `scene.apply`, `scene.create`, `input_select.set_options`, `remote.learn_command`,
  `remote.delete_command`, `media_player.play_media` et `join` (la musique passe par `jouer_musique`),
  `music_assistant.transfer_queue` et `vacuum.send_command`.
- Inchangés : le périmètre du LLM (`DOMAINES_LLM`, `DOMAINES_CONTEXTE`, énumération de l'outil `appeler_service`,
  l'aiguillage refuse un domaine hors de ce périmètre), le plafond de volume, la règle `volume_up` (jamais ajoutée
  sous plafond, y compris par le complément), `PROTEGER_OCCUPANT` et `HEURE_CALME_ACTIVE`.
- Tests : `poc/tests/cas_securite.json` gagne 74 cas d'action (par domaine ajouté un cas accepté et un refusé par
  `device_id`, `floor_id` ou `label_id`) et un bloc `services` de 101 cas lus aussi par l'appli. Nouveau
  `poc/tests/test_services_permis.py`. L'export `config-exemple/genere/android/dictionnaire.json` est régénéré.

## Serveur 0.36.3 (2026-10-26), build et outillage
Session S-D4 du plan 1.2.0. Le numéro 0.36.2 est réservé à S-D1 (fuseau et heures calmes), menée en parallèle.
Aucun changement de comportement du serveur, seuls l'outillage, la documentation et deux outils de test bougent.
- Appli Home Assistant (`ha-app/jarvis/config.yaml`) : l'architecture `aarch64` s'ajoute à `amd64`. L'image
  `python:5.12-slim` et les dépendances de `requirements.txt` existent pour les deux. Un Raspberry Pi 4 ou 5 et
  un Home Assistant Green peuvent donc installer l'appli. Le profil `ha` ne change pas.
- `poc/tests/test_demarrage.py` (avec le harnais `demarrage_a_vide.py`) : le serveur des satellites démarre sans
  `poc/.env`, sans micro, sans réseau et sans Home Assistant, écoute quelques secondes puis s'arrête seul. Toute
  connexion hors de la machine est refusée et fait échouer le test. Si un module tiers manque, le test est sauté
  avec le motif. Un second test lance `shellcheck` sur les scripts shell du dépôt, sauté quand l'outil est absent.
- `android/outils/pousser_canary.sh` : installe une version d'essai de l'appli par `adb install -r`, sur
  l'appareil donné en argument. Aucun jeton ni adresse dans le script (ils sont dans l'APK, copiés par Gradle).
- `dire.py` et `faux_telephone.py` (`poc/outils/`) : l'option `--reveil` dit le mot de réveil réglé dans
  `maison.json` (nouvelle fonction `assistant.prononciation_reveil`, même source que le serveur, même repli sur
  « Hey Jarvis » à l'anglaise), au lieu de « Hey Jarvis » écrit en dur.
- Documentation (`docs/INSTALLER.md`) : compilation hors de Windows sans `-PdossierBuild`, signature par
  `keystore.properties`, version d'essai par `pousser_canary.sh`, ARM64 pour l'appli Home Assistant, dossier
  `reveil/` non copié par `deployer.sh`, `CLAUDE_MODELE` et `SATELLITE_JETON_<NOM>` dans le tableau du `.env`.
## Serveur 0.36.2 (2026-10-26), une seule heure pour le moteur, heures calmes qui passent minuit
Session S-D1 du plan 1.2.0. Aucune règle de sécurité n'est assouplie : la règle des heures calmes reste coupée
par le propriétaire (`HEURE_CALME_ACTIVE` à `False`), seul son calcul est corrigé pour le jour où elle sera rallumée.
- `maison.maintenant()` (`poc/maison.py`) est la seule source d'heure du moteur : l'heure dans le fuseau de
  `maison.json` (`fuseau`), UTC si la clé manque, si le nom est inconnu ou si la base des fuseaux est absente
  (avertissement sur la sortie d'erreur). `maison.ZONE` donne l'objet fuseau, `maison.FORMAT_HORODATAGE` la forme
  des horodatages écrits (`2026-10-26T14:05:09`, sans décalage, comme avant, pour que l'appli Android les affiche
  et les relise sans changement).
- `acces.py`, `assistant.py` (date en français, journaux, phrases apprises), `sante.py`, `sante_hist.py`,
  `securite.py`, `serveur_satellite.py` et les outils de banc (`poc/outils/`) lisent cette source. Plus aucun
  `datetime.now()` sans argument, ni `time.strftime`, ni `date.today()` dans `poc/` hors des tests : l'application
  Home Assistant tourne en UTC et la machine du serveur peut avoir n'importe quel fuseau. `date_du_jour()` de la
  santé ne force plus Paris, elle suit le fuseau de la configuration.
- `meteo_mer.FUSEAU_MER` prend par défaut le fuseau de la maison au lieu de son propre repli.
- `securite.en_heure_calme(heure, debut, fin)` : une plage dont le début est après la fin (22 h à 7 h) couvre la
  soirée et le début de matinée. Avant, `debut <= heure < fin` ne couvrait jamais rien. Début égal à la fin :
  plage vide. Même calcul dans `Securite.enHeureCalme` (appli 0.37.4).
- Tests : `poc/tests/test_fuseau.py` (nouveau, dont un fuseau `Pacific/Auckland` indépendant de la variable `TZ` de
  la machine, le repli UTC et un garde-fou contre l'heure de la machine) et cinq heures-clés de la plage 22 h à
  7 h dans `cas_securite.json` (section `heures_calmes_nuit`), lues par `test_securite.py` et `SecuriteTest.kt`.
- `ha-app/jarvis/config.yaml` passe à 0.36.2.

## Serveur 0.36.1 (2026-10-26), schémas du README et de la documentation refaits
Session S-V1 du plan 1.2.0, fusionnée après S-D3 (0.36.0), d'où le numéro 0.36.1. Aucun changement de comportement, seuls les schémas et le README bougent.
- Cinq schémas SVG écrits à la main, chacun en thème clair et en thème sombre, dans `docs/images/` :
  `architecture`, `trajet-phrase`, `config-architecture`, `roles-droits` et `routines`. Ils reprennent l'esprit des
  anciens (boîtes nettes, flèches lisibles, légendes courtes) et ne montrent que la maison d'exemple de
  `config-exemple/`.
- Ce qui n'existe pas encore dans le code est marqué « prévu » en pointillé : le client web et son port 8767, le
  contexte de requête, les droits différenciés par rôle et les routines. L'occupant protégé et les heures calmes
  sont indiqués éteints.
- README : chaque schéma est dans un `<picture>` qui suit le thème du lecteur, avec une légende courte. Trois
  nouveaux schémas sont placés, la séparation du moteur et de `config/` dans « Ce qui reste à la maison », puis les
  rôles et les routines dans une section marquée « prévus ».
- Les schémas sont statiques, l'ancien trajet de phrase animé est remplacé par un trajet numéroté.

## Serveur 0.36.0 (2026-10-26), mot de réveil de la configuration, micro et voix par défaut
Session S-D3 du plan 1.2.0 (décision D5 : un mot générique, réglable dans `maison.json`). Une installation qui
règle `MOT_REVEIL` dans `poc/.env` se comporte comme avant.
- Mot de réveil (`modele_reveil`, `reglage_reveil`) : le mot est lu d'abord dans la section `reveil` de
  `maison.json` (`mot`, `nom`, `langue`, `licence`), puis dans `MOT_REVEIL` (réglage de secours), puis vaut
  `assistant`. L'ordre est dans la docstring. Le nom affiché suit le mot réellement guetté : `reveil.nom` pour le mot
  de la configuration, sinon le mot avec une majuscule.
- Si `reveil/<mot>.onnx` est absent, repli sur `hey_jarvis` (seul modèle détectable sans fichier de la
  configuration), nom affiché « Hey Jarvis » et une ligne claire au démarrage : `modèle de réveil absent pour le mot
  X (attendu : ...), repli sur Hey Jarvis`. Une seule fonction, `annoncer_repli_reveil`, sert l'assistant et le
  serveur satellite.
- `serveur_satellite.py` et `assistant.py` : plus de « Hey Jarvis » en dur dans les textes (docstrings, message
  « prêt », aide de `--reveil`). Le profil `ha` demande toujours `hey_jarvis` à l'appli openWakeWord de HA par
  Wyoming et l'annonce sous ce nom.
- Micro (I3) : `MICRO` absent ou vide vaut désormais `defaut`, le micro par défaut du système, au lieu d'un morceau de
  nom de micro propre à une machine. `trouver_peripherique` accepte vide ou `defaut` sans interroger le matériel.
- Voix (I3) : `VOIX` garde `poc/voix/fr_FR-siwis-medium.onnx` par défaut. Un fichier absent arrête le démarrage avec
  un message qui nomme le fichier, `VOIX` et `poc/outils/telecharger_modeles.py` (`verifier_voix`).
- `config-exemple/maison.json` : section `reveil` fictive (mot `assistant`), `_lisez_moi` réécrit. L'exemple ne
  fournit pas de modèle : le déposer dans `reveil/` ou retirer la section avant de compiler l'APK.
- Tests : `test_reveil.py` réécrit (nom « Assistant » avec modèle fictif, repli et message, `MOT_REVEIL` en secours,
  priorité de la configuration), `test_demarrage_sans_env.py` (micro par défaut, voix absente).
- Documentation : `MICRO`, `VOIX` et l'ordre de priorité du réveil dans `docs/INSTALLER.md`, `docs/CONFIGURER.md`,
  `docs/FAQ.md`, `docs/ARCHITECTURE.md` et `docs/QUOI-TOURNE-OU.md`.

## Serveur 0.35.0 (2026-10-26), météo marine : sources désactivables, côte et plan 3D reproductibles
Session S-D2 du plan 1.2.0. Une configuration existante se comporte comme avant : tout ce qui est ajouté est
facultatif ou n'écrit qu'un avertissement.
- Clé `actif` par source météo ou mer (C9) : `modele_principal`, `modele_second`, `mfwam`, `vagues_regional` (entier et
  chacun de ses lieux), `station`, et côté vent `balises`, chaque balise, `stations_officielles`, `station`. Absent vaut
  vrai. Une source `actif: false` n'est pas interrogée, n'est pas comptée en panne et disparaît des erreurs et des
  crédits. Modèle principal inactif ou toutes les sources de vent inactives : le module s'éteint. Les lignes de
  démarrage du serveur satellite ne citent que les sources actives.
- Avertissement de démarrage (C1) : section `mer` active sans source de vent utilisable (section `vent` absente,
  inactive ou sans aucune source), `poc/maison.py` écrit une phrase claire sur la sortie d'erreur. Aucune exception.
- `mer.nom` sert de titre par défaut de la mer (C3), après `mer.titre` et avant « Mer ». Le titre choisi est servi dans
  `donnees["titre"]` (clé additive). L'appli Android calcule encore le sien, voir les points ouverts du rapport.
- Nouveau `carte/vent/generer_cote.py` (C10) : trait de côte et terre de la carte du vent depuis un GeoJSON de données
  ouvertes passé en argument, jamais téléchargé. Jonction des lignes, fermeture de la terre le long du cadre, îles,
  marge hors cadre, simplification facultative, sortie déterministe. Cadre, taille et chemins lus dans `maison.json`.
- `config-exemple/carte/cote_source.geojson` (fictif) et `golfe_cote.txt` et `golfe_terre.txt` régénérés par le
  générateur, qui les reproduit octet pour octet. `LISEZMOI.txt` mis à jour.
- `carte/3d/generer_3d.py` (C11) : exécution de bout en bout sur `config-exemple/` en dossier temporaire et sortie
  identique d'une exécution à l'autre, vérifiées par test.
- `docs/CONFIGURER.md` : clés `mer.nom`, `mer.titre` et `actif`, avertissement, nouvelle section « Régénérer la
  côte et le plan 3D ». `carte/README.md` et `docs/FAQ.md` renvoient vers le générateur.
- Tests ajoutés : `test_meteo_actif.py` (34), `test_generer_cote.py` (20), `test_generer_3d.py` (4).

## Serveur 0.34.4 (2026-10-26), garde-fou piloté par une liste, documentation sans référence à un projet tiers
Session S-C4 du plan 1.2.0. Aucun changement de comportement pour une configuration existante.
- `.githooks/garde-fou.sh` lit `config/mots-interdits.txt` (une chaîne par ligne, lignes vides et lignes commençant
  par `#` ignorées, insensible à la casse). Chaque chaîne est refusée dans les chemins indexés et dans leur contenu,
  le mot trouvé est masqué dans le message. Sans ce fichier, un avertissement sort sur l'erreur standard et seuls les
  contrôles génériques tournent. Aucun contrôle existant n'est retiré, et le script ne contient plus aucun mot en dur.
- Le mot interdit disparaît de tout le moteur, `docs/` compris : commentaires du serveur, des outils, des tests et de
  l'appli reformulés, valeur par défaut du mot de réveil devenue « Assistant ». Les entrées précédentes de ce journal
  sont reformulées avec le même sens. La règle de `CLAUDE.md` devient : aucun nom de dépôt, de dossier ni de variable
  ne contient un mot de `config/mots-interdits.txt`, et le mot de réveil n'est qu'un réglage.
- `inspirations/` n'est plus suivi : le fichier de comparaison est retiré de l'index et de `.gitignore`, plus rien
  dans le dépôt ne pointe vers ce dossier.
- `README.md` : la section « Inspiration » laisse place à un remerciement général, sans lien ni nom de projet. La
  licence passe à MIT (renvoi à `LICENSE` et à `LICENCES-TIERS.md`, qui est mis en cohérence).
- Les prénoms réels des journaux de versions, du README et des licences sont remplacés par « le propriétaire », « la
  colocataire », Sacha ou Camille. `docs/ARCHITECTURE.md` décrit une installation d'exemple avec du matériel générique.
- `poc/serveur_satellite.py` avertit au démarrage, sans jamais s'arrêter, des modèles manquants
  (`verifier_au_demarrage` de `poc/outils/telecharger_modeles.py`), sauf si la voix est choisie ailleurs. Deux tests
  dans `test_modeles_manquants.py`.
- `test_confidentialite.py` : les 19 attentes d'échec de S-C4 sont retirées (`ATTENDUS` est vide), le volet privé
  passe sans elles. Cinq tests exécutent le vrai garde-fou dans un dépôt jetable (contenu, chemin, liste absente).

## Serveur 0.34.3 (2026-10-26), exemple de configuration entièrement fictif
Session S-C3 du plan 1.2.0. Aucun changement de comportement pour une configuration existante.
- `config-exemple/` ne contient plus aucune valeur réelle. Les identifiants d'entités de `maison.json`,
  `commandes.yaml`, `carte/lampes.json` et `carte/meubles.json` suivent la conception de `docs/plan/conception/`
  (lumières du salon, de la cuisine, du couloir et des chambres de Sacha et de Camille, télévision, barre de son,
  enceintes, groupe d'enceintes). Les tests, les cas de sécurité et la documentation citent les mêmes identifiants.
- Le plan d'eau de l'exemple est la rade de Marseille (cadre, balises, stations, points de vagues, coordonnées
  arrondies à deux décimales, fuseau Europe/Paris). Le trait de côte de `genere/android/carte/` est un tracé simplifié
  dessiné à la main, sans donnée importée. `LISEZMOI.txt` le dit.
- `poc/meteo_mer.py` et `poc/vent_mesure.py` ne nomment plus aucun lieu. Le nom, le fuseau, les modèles (ARPEGE et
  AROME dans l'exemple), les points, les lieux de vagues et la station à terre sont lus dans la configuration. Les
  noms de variables `FUSEAU` et `paris()` deviennent `LOCAL` et `heure_locale()`.
- `poc/.env.exemple` : les noms de stations et de balises sont remplacés par des clés génériques commentées.
- `config-exemple/genere/android/dictionnaire.json` est régénéré (17 099 formes, 1,7 Mo). Il reste suivi, car
  `test_export_exemple_a_jour` le compare à l'export neuf et `android/app/build.gradle.kts` le lit.
- `docs/CONFIGURER.md`, `docs/INSTALLER.md`, `docs/QUOI-TOURNE-OU.md` et `carte/3d/README.md` ne décrivent plus que
  l'exemple fictif.
- `test_confidentialite.py` : toutes les attentes d'échec de S-C3 sont retirées, il ne reste que celles de S-C4. Les
  deux volets (générique et privé) passent sans elles. Le fichier de 1,7 Mo du dictionnaire est balayé comme le reste.
- Tests : 481 réussis, 5 ignorés, 19 échecs attendus (tous S-C4).

## Serveur 0.34.2 (2026-10-26), tests sur des valeurs fictives et volet privé nettoyé
Session S-C2 du plan 1.2.0. Aucun changement de comportement du serveur.
- Tests Python : les adresses précises d'appareils sont remplacées par des adresses génériques de même nature
  (réseau local en 192.168.0.x, tailnet en 100.64.0.10, public en 8.8.4.4 ou 1.1.1.1, privé 10.0.0.10), ajoutées à
  `IP_PERMISES` du test de confidentialité. Les plages de documentation ne remplacent pas une adresse privée ou publique.
- Les prénoms réels des tests d'aiguillage et de `poc/acces.py` (docstring) sont remplacés par Sacha et Camille ou
  par une formulation neutre.
- Volet privé nettoyé : `poc/.env.exemple`, `poc/sante.py`, `poc/sante_hist.py` et `poc/tests/test_failles_acces.py`
  ne portent plus d'alias SSH ni d'adresse du parc réel (`serveur-exemple`, `pc-exemple`).
- Nouveau test `poc/tests/test_prenoms_configuration.py` (dette C14) : le nom de l'occupant protégé et celui du
  propriétaire viennent de `maison.json` (vérifié aussi sur une configuration fictive dans un autre interpréteur),
  et aucune chaîne de code de `poc/*.py` hors tests ne contient un prénom de la configuration.
- `ATTENDUS` de `poc/tests/test_confidentialite.py` : les entrées de la session S-C2 sont retirées.
- Numéro `VERSION` de `poc/assistant.py` et `ha-app/jarvis/config.yaml` passés à 0.34.2.

## Documentation (2026-10-26), maquettes du socle du client web (S-W0a), sans changement de version
Aucun code ni numéro de version ne change : le serveur et l'appli gardent leur numéro.
- `docs/maquettes/client-web/` : planches HTML autonomes (CSS inclus, aucune ressource distante, aucun script),
  lisibles en clair, en sombre et en ambiance du soir : Accueil, appairage en trois écrans (nouveau navigateur,
  propriétaire avec rôle, confirmation par clé d'accès), Réglages, révocation d'un appareil, composants et états.
  Noms fictifs de `config-exemple/maison.json`. Version des maquettes : 1.0.0.
- `docs/maquettes/client-web/` : planches du lot journal (S-W0b), Journal de jour et du soir, feuille de détail,
  Demander (écoute, réponse, essai) et Vie privée (niveau, aperçu, confirmation par clé d'accès).
- `docs/maquettes/client-web/` : planches du lot maison (S-W0c), Maison avec le volet lampe en Blanc et en Couleur,
  Météo et mer, Routines (liste, détail, confirmation de suppression) et les états d'échec du volet lampe le soir.
  Index à 18 planches, bandeau "planche N sur 18".
- `docs/plan/conception/client-web.md` : choix de S-W0c et questions ouvertes pour le propriétaire.
- `docs/principes-design.md` : section Client web (palette en variables CSS, typographie, espacements, états,
  composants réutilisables, accessibilité).

## Serveur 0.34.1 (2026-10-26), licences : MIT pour le code, modèles non commerciaux téléchargés
Session S-C5 du plan 1.2.0 (décision D2). Aucun changement de comportement du serveur. Le numéro `VERSION` de
`poc/assistant.py` reste à passer à 0.34.1 à la fusion (fichier à écrivain unique, non touché par cette branche).
- `LICENSE` à la racine : MIT, titulaire neutre « les auteurs de l'assistant vocal local », avec un rappel que les
  modèles, polices et bibliothèques tiers gardent leur licence.
- `LICENCES-TIERS.md` réécrit (dette I15) : la phrase « tous droits réservés » est remplacée par la licence MIT,
  toutes les bibliothèques Python des deux `requirements.txt` et toutes les dépendances Gradle sont listées avec
  version contrôlée, licence et source, la note sur piper-tts (GPL-3.0-or-later) est ajoutée, la section « Modèles
  à retirer de l'instantané public » liste les trois modèles CC BY-NC-SA 4.0 d'openWakeWord avec leur adresse
  officielle et leur SHA-256, et la section « Reste à confirmer » dit ce qui n'a pas pu être vérifié.
- `poc/outils/telecharger_modeles.py` : les trois modèles d'openWakeWord (mot de réveil Hey Jarvis, prétraitement)
  sont téléchargés depuis la publication officielle v0.5.1 avec vérification SHA-256 et licence affichée avant le
  téléchargement. Nouvelles fonctions `modeles_manquants`, `message_modeles_manquants` et `verifier_au_demarrage`
  (message clair : fichiers manquants, licence, commande). Le branchement au démarrage du serveur reste à faire
  dans `poc/assistant.py`.
- Test `poc/tests/test_modeles_manquants.py` (10 cas, sans réseau). Le téléchargement n'a pas été lancé et les
  modèles restent dans le dépôt privé.

## Serveur 0.34.0 (2026-10-25), administration dans Home Assistant (Ingress), invitation par code
Lot : une page d'administration dans la barre latérale de Home Assistant, réservée aux administrateurs de HA de
la liste blanche. Doc HA : https://contributors.home-assistant.io/apps/guides/ingress/. Appli Android 0.37.0
(saisie du code).
- Service (`poc/administration.py`) : HTTP et WebSocket sur `0.0.0.0:JARVIS_ADMIN_PORT` (8099 dans l'appli HA, port
  non publié dans `ports:`), actif seulement si la variable est posée. Sans framework ni npm. Table de chemins
  fermée vers `poc/admin/` (index.html, admin.js, admin.css), 404 pour le reste. En-têtes de sécurité sur toutes les
  réponses (CSP sans script ni style en ligne, nosniff, no-referrer, no-store).
- Barrières d'entrée : adresse source `172.30.32.2` (le superviseur), `X-Remote-User-Id` dans
  `administration.utilisateurs_ha` (liste vide : personne n'entre, la page 403 affiche l'identifiant à ajouter),
  WebSocket fermée en 4003 si l'en-tête Origin est absent ou différent de l'hôte (le refus journalise Origin, Host et
  X-Forwarded-Host, pour diagnostiquer un Ingress réel). Le canal de la page n'accepte que `TYPES_PAGE`.
- Page : demandes en attente (nom, adresse, code à 4 chiffres, Accepter ou Refuser avec choix du rôle), appareils
  (rôle modifiable sauf administrateur, révocation avec confirmation dans la page), ajout d'appareil (rôle, code à
  6 chiffres en grand, QR code, compte à rebours, annulation), jetons fixes en lecture seule, derniers refus.
- Invitation (`acces.Invitation`) : 6 chiffres, 120 s, usage unique, 3 essais, une seule à la fois, rôle
  administrateur refusé. Le code n'apparaît que dans la page (ni journal, ni `vue()`, ni diffusion). Indépendante de
  l'amorçage à 8 chiffres. L'appli Android accepte 6 ou 8 chiffres.
- QR code : `<administration.url_client>#code=<6 chiffres>`, généré localement par `segno`. Sans `url_client`
  (le client web n'existe pas encore), la page affiche le code en grand et explique que le QR code arrivera avec le
  client web.
- Relectures (sécurité, accessibilité) intégrées : chiffres saisis limités à 0-9, en-têtes malformés ou en double
  refusés proprement, un administrateur ne se rétrograde pas par la page, focus et libellés de la page. Limite
  connue, non traitée : le compteur de 3 essais de l'invitation est global, un client du réseau qui joint
  `/appairage` peut donc la détruire (déni de service, sans contournement du code). À limiter par adresse plus tard.
- Rôles : champ `role` dans `appareils.json` (`administrateur`, `habitant`, `partage`, `invite`, défaut
  `habitant`, aucun rôle n'ouvre ni ne ferme de droit pour l'instant). Révocation par identité (`appareil:<id>`).
- À poser dans la vraie configuration (`config/maison.json`) : `administration.utilisateurs_ha` (identifiants HA,
  visibles sur la page 403) et plus tard `administration.url_client`. Déploiement : `ha-app/deployer.sh`, puis
  redémarrer l'appli HA. Le serveur du PC n'est pas concerné par la page.
- Non vérifié ici : le vrai Ingress. Le superviseur copie Host et Origin tels quels, la comparaison Origin et Host
  peut échouer derrière lui, auquel cas le journal donne les valeurs reçues.
- Tests : `poc/tests/test_administration.py`.

## Serveur 0.33.0 (2026-10-25), reconnexion après une coupure, amorçage de l'appairage, diagnostic
Contexte : après une coupure de courant, une tablette dont le jeton n'était plus connu du serveur ne pouvait plus
se reconnecter, et l'appairage demande un administrateur connecté pour accepter, donc personne.
- Amorçage (`acces.Amorcage`) : quand aucun administrateur n'est connecté et que la demande vient du réseau local
  (privé ou loopback, pas le tailnet), le serveur écrit dans son journal un code à 8 chiffres, à usage unique, valable
  10 minutes, 5 essais, un nouveau code au plus par minute. Le téléphone le saisit (`{"type":"amorcage","code"}`).
  Le code n'apparaît nulle part ailleurs que dans le journal. Un appareil amorcé n'est pas administrateur, sauf si
  `acces.administrateurs` le dit. Le message `appairage` annonce `"amorcage": true`, un code faux renvoie
  `{"etat":"amorcage_refuse","restant"}`.
- Diagnostic : le serveur journalise et retient (`Appareils.refus`, 20 derniers) la cause de chaque refus, réseau non
  autorisé (4003), jeton absent ou invalide avec les 8 premiers caractères de son empreinte (4001). La liste est
  envoyée aux administrateurs dans le message `appareils` (clé `refus`).
- Tests : `poc/tests/test_amorcage.py`.

## Serveur 0.32.0 (2026-10-25), état des lampes pour le volet de réglage
- `etat()` renvoie pour une lampe `color_mode`, `color_temp_kelvin`, `hs_color`, `rgb_color`, `min_color_temp_kelvin` et
  `max_color_temp_kelvin` (les valeurs absentes sont omises), pour que l'appli confirme un blanc ou une couleur demandés.

## Serveur 0.31.0 (2026-10-25), failles critiques de la conception du client web
- `securite.py` refuse `floor_id` et `label_id` comme cibles, comme `device_id` : un étage ou une étiquette visait un
  groupe d'entités sans passer par la liste blanche par appareil. Cas communs ajoutés à `cas_securite.json`.
- `recevoir_texte` contrôle un rôle : `appareils`, `appairer`, `refuser_appareil`, `revoquer`, `transcription`, `mode`,
  `cerveau` et `manques` ne passent que pour un administrateur (le propriétaire, plus `acces.administrateurs`). Les
  autres reçoivent `{"etat": "refuse"}`.
- Le code d'appairage n'est plus diffusé à tous : `appairage_demande` ne part qu'aux administrateurs et la vue des
  appareils ne donne le code qu'à eux. Le téléphone qui demande l'appairage voit toujours son code.
- Nouvelle section `acces` de `maison.json` (clé fictive dans `config-exemple/`) : `ecoute` (adresses d'écoute des ports
  8765 et 8766, `0.0.0.0` par défaut), `reseaux_autorises` (connexion refusée hors maison, tailnet et machine locale par
  défaut, `"*"` pour tout ouvrir), `ancien_acces` (jeton dans l'adresse sur 8765, permis par défaut,
  `JARVIS_ANCIEN_ACCES` l'emporte), `administrateurs`. Ports 8765 et ancien accès non coupés : décision du propriétaire.

## Serveur 0.30.0 (2026-10-25), services des réglages fins de la télé et des lampes
- Services ouverts au serveur (`SERVICES_PERMIS`) : `domaine_tele.launch_app`, `domaine_tele.send_text_input`,
  `domaine_tele.set_picture_setting`, `remote.send_command` et `select.select_option`. Ces trois domaines restent
  hors du contexte du LLM (`DOMAINES_CONTEXTE`) et hors de son outil `appeler_service` (`DOMAINES_HORS_LLM`, absents de
  l'enum et refusés à l'appel), ils servent aux routines, à la passerelle et aux volets de l'appli.
- `launch_app` : toute URL qui ne commence pas par `https://` est refusée (http:, javascript:, data:, espaces ou
  caractères de contrôle compris), au serveur (`HomeAssistant.service`) et à la passerelle
  (`acces.refus_launch_app`, appelée par `verifier_requete_ha`).
- Inchangés : refus de `device_id`, `DOMAINES_INTERDITS`, règles de `securite.py`. `light.turn_on` n'a pas de liste
  de clés, `flash` et `effect` passent donc déjà (test ajouté).
- Dictionnaire d'exemple exporté de nouveau (liste des services permis). Tests dans `test_services_reglages.py`.

## Serveur 0.29.1 (2026-10-25), deux défauts des routines
- `lire_etat` refuse toute entité absente de l'inventaire courant, sans appeler Home Assistant : le LLM ne
  peut plus contourner l'enum du schéma.
- En mode essai (conversation de HA comprise), la passerelle Home Assistant ne transmet plus les services (POST `/api/services/...`) :
  elle répond 200 avec `[]` et le note au journal. Les lectures restent transmises. La vérification d'accès
  passe toujours en premier.

## Serveur 0.29.0 (2026-10-25), musique sur toutes les enceintes
- Après un lancement confirmé sur le groupe « toutes » (Spotify Connect, Music Assistant ou script de
  musique), le serveur vérifie que chaque enceinte du groupe joue. Une enceinte hors ligne est signalée tout de
  suite, une enceinte en ligne a jusqu'à 8 s pour suivre (sans dépasser l'échéance de la commande). Seul le
  script de lancement (`script_lancer`) est concerné, pas un transfert. Une enceinte absente est
  signalée dans le résultat de l'outil et dans la réponse du dictionnaire : « La musique est lancée, mais
  l'enceinte cuisine est hors ligne. » (`HomeAssistant.absentes`, `signaler`, `phrase_manquantes`). Le journal
  de musique garde `muettes`. Le 25/10/2026, la cuisine débranchée, la musique partait sur le seul salon sans
  rien dire. La remarque ne remplace pas un refus déjà prononcé dans la même phrase du dictionnaire.
- Outil `jouer_musique` : l'enceinte vaut « toutes » sauf si une enceinte précise est nommée dans la demande.
- Tests dans `test_musique.py` (phrase, hors ligne contre muette, voie Spotify, enceinte nommée, script, transfert,
  synonyme).

## Serveur 0.28.0 (2026-10-25), socle des routines : aiguillage fermé et requête par appareil
- Aiguillage fermé des outils du LLM (Qwen et Claude, `Cerveau.executer_outil`) : seul un outil de la
  liste du tour s'exécute, tout autre nom (inventé, ou absent du mode) reçoit « outil indisponible » sans
  aucun appel à Home Assistant. Arguments illisibles refusés de même.
- Listes d'outils par mode (`MODES_OUTILS`, « commande » pour l'instant). `outils_avec_entites` retrouve
  les outils par leur nom et non plus par leur rang. Claude garde une liste en cache par mode.
- Essai, personne et appareil portés par la commande (`Requete`, variable de contexte) et non plus par
  les objets partagés : `Assistant.requete(...)` remplace `pour_personne`. Une phrase de la tablette et
  une commande du client web ne se prennent plus leur essai ni leur personne.
- Essai effectif côté serveur : celui du serveur ou celui du téléphone (`llm_texte`). Un téléphone en réel
  ne lève plus l'essai du serveur.
- Historique du LLM par personne et par appareil, oublié après 2 min. Leçon apprise annulable par « non »
  seulement depuis l'appareil qui l'a fait apprendre. L'identité de l'appareil appairé est transmise par
  `traiter` et `repondre_llm`.
- `acces.DOMAINES_INTERDITS` refusé aussi par `HomeAssistant.service` et par la voie du dictionnaire
  (`Assistant.executer`), plus seulement par la passerelle.
- `HomeAssistant.service(..., confirmer=False)` : pas d'attente de l'état, pour les étapes des routines.
- L'essai du serveur (`ha.essai = True`) est un plancher : aucune requête ne le lève.
- Clé d'appareil (`Satellite.cle_appareil`) : l'identité d'un téléphone appairé, ou le jeton fixe suivi du
  nom de l'appareil, pour que deux appareils sur le même jeton de `poc/.env` ne partagent pas leur historique.
- Tests dans `test_aiguillage.py`.

## Serveur 0.27.3 (2026-10-25), défauts relevés pendant la documentation
- Clé Claude : `ANTHROPIC_AUTH_TOKEN` compte comme une clé, comme dans le SDK. Sans clé, la réponse parlée
  dit « Je n'ai pas de clé Anthropic » au lieu de « Le PC est peut-être occupé », et le journal garde le
  texte de l'erreur. Le refus de passer sur Claude sans clé se décide hors du verrou et ne s'affiche
  qu'une fois. Tests dans `test_cle_claude.py`.
- Vent mesuré éteint : le message de démarrage donne toutes les causes (`VENT_MESURE=0`, `METEO_MER=0`,
  `"actif": false`). `maison.actif(section)` lit `"actif"` comme l'appli (vrai seulement pour `true`,
  donc `1` ou `"oui"` valent faux), pour `mer` et `vent`. `point_proche` ne plante plus (`ValueError`)
  quand aucun point n'est déclaré : il rend une chaîne vide et l'appli prend son point par défaut.
- Script de musique sans `appareils.musique.enceintes.toutes` : la confirmation d'écoute ne vérifie plus
  rien au lieu de chercher un groupe inexistant. Les autres commandes de musique demandent toujours cette
  enceinte.
- `poc/outils/telecharger_modeles.py` télécharge aussi la voix `en_US-lessac-medium` (modèle et `.json`,
  vérifiés par empreinte SHA-256).
- `maison.json` : message distinct pour un fichier absent (copier l'exemple) et un fichier illisible
  (le corriger, sans recopier l'exemple qui effacerait la configuration).
- `poc/.env` lu avant les options de `serveur_satellite.py` : `JARVIS_PORT_TLS` y prend effet (une ligne
  vide garde 8766).
  `poc/.env.exemple` liste les variables qui manquaient (`CLAUDE_MODELE`, `SEUIL_REVEIL`, `VOIX`,
  `STT_API_*`, `JARVIS_PROFIL`, `JARVIS_PORT_TLS`, `JARVIS_ANCIEN_ACCES`, `JARVIS_WYOMING_SSH`,
  `SATELLITE_JETON_<NOM>`) et dit lesquelles ne se lisent que dans l'environnement.
- `ha-app/deployer.sh` prend `python3` ou `python`, essayés tour à tour (le raccourci du Microsoft Store
  ne compte pas), et s'arrête sur `Python introuvable` sinon.
- Garde-fou : un fichier `.env` indexé reçoit un conseil adapté (`git rm --cached`), en plus de celui
  sur les secrets quand il y en a ailleurs.
- Vision : une erreur d'analyse renvoie son type seulement, le détail part dans le journal du serveur.
- Journal de calibration du réveil dans le dossier de données (`JARVIS_DONNEES`), plus dans `poc/` en dur.
- Heures calmes : le refus dit la plage de `heures_calmes` au lieu de « entre minuit et 9 h » figé.
- Docstrings de `assistant.py` et `serveur_satellite.py` à jour. `docs/FAQ.md` : section « Limites
  connues », messages de `maison.json`, du déployeur et du garde-fou.

## Serveur 0.27.2 (2026-10-25), METEO_MER=0 éteint aussi le vent mesuré
- `METEO_MER=0` (ou `non`, `false`, `off`) éteint désormais la météo marine et le vent mesuré, puisque la page
  Vent fait partie du panneau Mer. Avant, le vent restait servi et il fallait aussi `VENT_MESURE=0`.
  `VENT_MESURE=0` éteint toujours le vent seul. Le message de démarrage donne la variable en cause.
- Nouvelle fonction `meteo_mer.eteinte_par_env()`, lue par `vent_mesure.depuis_env()`. Test dans
  `test_vent_mesure.py`. Doc : `CONFIGURER.md`, `INSTALLER.md`, `FAQ.md`, `poc/.env.exemple`.

## Serveur 0.27.1 (2026-10-25), cerveau Claude sans clé Anthropic
- Avertissement au démarrage quand le cerveau Claude n'a pas de clé (`ANTHROPIC_API_KEY` vide dans
  `poc/.env`, ou option `anthropic_api_key` de l'appli HA). Chaque demande au LLM échoue alors sur une erreur
  claire, sans appel à l'API, au lieu de l'erreur d'authentification du SDK. Le message part aussi vers
  l'appli dans l'état du cerveau.
- Bascule vers Claude demandée depuis le téléphone refusée sans clé : le modèle local reste chargé au lieu
  d'être arrêté pour un cerveau qui ne répondrait pas.
- Test `poc/tests/test_cle_claude.py`.

## Serveur 0.27.0 (2026-10-25), plafond de volume réglable, aucun par défaut
- Le plafond fixe de 50 % du volume devient le réglage `securite.plafond_volume` de `maison.json`, en
  pourcentage : absent, `null` ou `100`, aucun plafond (le défaut). La configuration d'exemple et celle du
  propriétaire le règlent à 100. Une valeur illisible (texte, booléen) garde un plafond prudent de 50 %, une valeur
  hors de 0 à 100 y est ramenée (`securite.plafond_configure`).
- Avec un plafond, tout se règle sur sa valeur : `volume_level` ramené au plafond, refus de
  `media_player.volume_up` dont le message dit la valeur, phrase de la consigne du LLM. Sans plafond,
  `volume_up` est permis, au LLM du serveur compris, et la consigne ne parle plus de plafond.
- `configurer-ha.py` envoie à Home Assistant les données telles que la sécurité les laisse passer : un
  volume au-dessus d'un plafond réglé part plafonné dans l'automatisation.
- Les autres règles de la sécurité en dur sont inchangées.
- Cas communs `plafonds` étendus (avec et sans plafond, 0, 30, 72,5 et 100 %), nouveaux cas
  `plafonds_configures` et `pourcentages`, pourcentages arrondis au dixième comme dans l'appli.

## Serveur 0.26.0 (2026-10-25), nom de l'assistant lu dans la configuration
- Nouvelle section `assistant` de `maison.json` (`nom`), lue par `maison.NOM_ASSISTANT` : nom de
  l'automatisation du dictionnaire créée par `configurer-ha.py`, journal de démarrage de l'appli Home
  Assistant, nom de cette appli dans HA (ligne `name:` réécrite par `deployer.sh`) et, côté tablette, nom de
  l'appli Android. Les réponses parlées du serveur ne citent pas ce nom. « Assistant » quand la section est
  absente, vide ou mal formée, « Iris » dans `config-exemple/`. Distinct du mot de réveil (section `reveil`).
- Commentaires du moteur neutres (« l'assistant », « le mot de réveil »), agents HTTP et générateurs en
  `assistant-vocal/1.0`. Seules restaient alors des mentions d'un projet d'inspiration (retirées en 0.34.4).
- Commentaires de `poc/securite.py` reformulés sans changer les règles ni le réglage du plafond de volume.
- Test `poc/tests/test_assistant_nom.py`.

## Serveur 0.25.2 (2026-10-24), premier instantané du moteur
- Dépôt du moteur créé à partir d'un instantané, sans historique, après la séparation du moteur et de la
  configuration. Tout ce qui décrit un logement réel (adresses, appareils, pièces, dictionnaire, plan 3D,
  points de la météo marine, propriétaire, mot de réveil) est lu dans le dossier de configuration
  (`config/` ou `ASSISTANT_VOCAL_CONFIG`). `config-exemple/` porte une configuration fictive complète, qui fait
  tourner les tests.
- La numérotation continue celle du projet d'origine, dont le journal complet reste avec la configuration
  du propriétaire.
