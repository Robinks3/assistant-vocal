# Assistant vocal, versions du serveur

Journal du serveur (`poc/`) et de l'appli Home Assistant (`ha-app/`). L'appli Android a le sien dans
`android/VERSION.md`. La version s'affiche au démarrage du serveur et dans les capacités annoncées aux
satellites.

## Documentation (2026-10-26), maquettes du socle du client web (S-W0a), sans changement de version
Aucun code ni numéro de version ne change : le serveur et l'appli gardent leur numéro.
- `docs/maquettes/client-web/` : planches HTML autonomes (CSS inclus, aucune ressource distante, aucun script),
  lisibles en clair, en sombre et en ambiance du soir : Accueil, appairage en trois écrans (nouveau navigateur,
  propriétaire avec rôle, confirmation par clé d'accès), Réglages, révocation d'un appareil, composants et états.
  Noms fictifs de `config-exemple/maison.json`. Version des maquettes : 1.0.0.
- `docs/maquettes/client-web/` : planches du lot journal (S-W0b), Journal de jour et du soir, feuille de détail,
  Demander (écoute, réponse, essai) et Vie privée (niveau, aperçu, confirmation par clé d'accès).
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
  `JARVIS_ANCIEN_ACCES` l'emporte), `administrateurs`. Ports 8765 et ancien accès non coupés : décision de Alex.

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
  pourcentage : absent, `null` ou `100`, aucun plafond (le défaut). La configuration d'exemple et celle de
  Alex le règlent à 100. Une valeur illisible (texte, booléen) garde un plafond prudent de 50 %, une valeur
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
  `assistant-vocal/1.0`. Seules restent les citations du projet d'origine des auteurs inspiration.
- Commentaires de `poc/securite.py` reformulés sans changer les règles ni le réglage du plafond de volume.
- Test `poc/tests/test_assistant_nom.py`.

## Serveur 0.25.2 (2026-10-24), premier instantané du moteur
- Dépôt du moteur créé à partir d'un instantané, sans historique, après la séparation du moteur et de la
  configuration. Tout ce qui décrit un logement réel (adresses, appareils, pièces, dictionnaire, plan 3D,
  points de la météo marine, propriétaire, mot de réveil) est lu dans le dossier de configuration
  (`config/` ou `ASSISTANT_VOCAL_CONFIG`). `config-exemple/` porte une configuration fictive complète, qui fait
  tourner les tests.
- La numérotation continue celle du projet d'origine, dont le journal complet reste avec la configuration
  de Alex.
