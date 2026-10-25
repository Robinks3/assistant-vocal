# Assistant vocal, versions du serveur

Journal du serveur (`poc/`) et de l'appli Home Assistant (`ha-app/`). L'appli Android a le sien dans
`android/VERSION.md`. La version s'affiche au démarrage du serveur et dans les capacités annoncées aux
satellites.

## Serveur 0.30.0 (2026-10-25), services des réglages fins de la télé et des lampes
- Services ouverts au serveur (`SERVICES_PERMIS`) : `domaine_tele.launch_app`, `domaine_tele.send_text_input`,
  `domaine_tele.set_picture_setting`, `remote.send_command` et `select.select_option`. Ces trois domaines restent
  hors du contexte du LLM (`DOMAINES_CONTEXTE`), ils servent aux volets de l'appli.
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
