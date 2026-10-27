# Assistant vocal, versions du serveur

Journal du serveur (`poc/`) et de l'appli Home Assistant (`ha-app/`). L'appli Android a le sien dans
`android/VERSION.md`. La version s'affiche au démarrage du serveur et dans les capacités annoncées aux
satellites.

## Serveur 0.57.0 (2026-10-27), client web installable
Mineure. Session S-W9 du plan. Appli Home Assistant 0.57.0 (le déploiement copie déjà tout `web/`), appli Android
inchangée. Client web 0.11.0.
- Service worker `/sw.js` (`poc/web/sw.js`), servi en JavaScript sans cache, portée `/`. Le serveur y injecte la
  version du client, qui donne le nom du cache (`coquille-<version>`). L'activation supprime tout autre cache.
- Listes blanches explicites : la coquille publique (styles, `app.js`, `client.js`, page hors ligne, icônes,
  polices) est précachée et servie réseau d'abord, les pages navigables sont toujours demandées au réseau et
  remplacées par la page « Serveur injoignable » (`/hors-ligne`, `hors-ligne.html`) quand il manque. Rien d'autre
  n'est intercepté : WebSocket, requêtes autres que GET, `/api`, `/appairage`, scripts des pages protégées, vue 3D.
  Aucune page protégée ni aucune donnée en cache. Une copie ne va que dans un cache encore présent.
- Inscription par `client.js` sur les pages d'une session et par l'accueil une fois la session vérifiée, jamais sur
  l'écran d'association. L'adresse passe par une politique Trusted Types `service-worker` qui n'accepte que
  `/sw.js` : la politique de contenu reste inchangée.
- Purge (caches vidés, service worker désinscrit) à « Oublier ce navigateur » et à l'arrivée sur l'écran
  d'association. Les réponses de révocation (cookie révoqué, appareil inconnu) portent
  `Clear-Site-Data: "cache", "storage"`.
- Réglages : ligne « Installer sur ce téléphone ». Bouton quand le navigateur propose l'installation, sinon la
  marche à suivre en mots pour Chrome, Samsung Internet et Safari sur iPhone, « Déjà installée » en mode autonome.
- Manifeste vérifié contre les critères d'installation de Chrome, déjà conforme.
- Tests : `test_serveur_web_installable.py` (en-têtes et version du service worker, listes blanches, inscription et
  purge rejouées sous Node, ligne Installer, révocation, manifeste), quatre variantes Réglages et hors ligne dans le
  contrôle de mise en page (zéro défaut à 360, 390 et 430 px, thèmes clair et sombre).

## Serveur 0.56.0 (2026-10-27), écran Routines dans le client web
Mineure. Session S-W6 du plan. Appli Home Assistant 0.56.0 (le déploiement copie aussi `routines_web.py`), appli Android
inchangée. Client web 0.10.0.
- Écran Routines (`/routines`, `routines.html`, `routines.js`), d'après les maquettes routines-liste, routines-detail
  et routines-suppression. Liste des routines visibles, puis détail : phrases qui la lancent, étapes en mots, qui la
  lance et qui la gère, dernière exécution. Actions selon les droits : Lancer maintenant, Mettre en pause ou
  Réactiver, Modifier (qui explique que la modification se fait à la voix) et Supprimer, en rouge et à l'écart.
  Aucun bouton de création, une routine se crée à la voix. Textes posés par `textContent` seulement, états de
  chargement, vide et erreur. Lien depuis l'accueil.
- Suppression confirmée par une feuille `alertdialog`, le focus sur « Garder la routine ». Après suppression, un
  bandeau `role="status"` sans bouton Annuler (la suppression est définitive).
- Six messages sur le port 8767 (`routines`, `routine_lancer`, `routine_activer`, `routine_supprimer`,
  `routine_texte`, `routines_export`), à schéma strict (`routines_web.py`) : une clé en trop, en moins ou du mauvais
  type donne un refus `format`. Le rôle et la personne viennent de la session, jamais du message : le propriétaire
  pour l'administrateur, l'identité de l'appareil associé pour un habitant, personne pour un invité. Lister, lancer
  et dicter pour tout rôle, mettre en pause et supprimer pour l'administrateur et l'habitant, exporter pour
  l'administrateur seulement. Chaque routine part avec un bloc `droits` calculé par le moteur, le navigateur n'en
  invente aucun. Une routine invisible reste inconnue, son existence ne fuit pas. Le signal `routines_maj` est relayé
  aux clients web. Le port 8765 refuse toujours ces messages.
- Mode développeur : l'identifiant technique d'une étape (service et entités) ne part que vers le propriétaire, et ne
  s'affiche qu'en mode développeur (classe `dev-seulement`).
- `config-exemple/routines-exemple.json` : trois routines fictives pour les essais et les maquettes.
- README et schémas des routines : l'écran du client web n'est plus annoncé comme à faire.
- Tests : `test_serveur_web_routines.py`, treize variantes de l'écran Routines dans le contrôle de mise en page (zéro
  défaut à 360, 390 et 430 px, thèmes clair et sombre), page ajoutée à `test_mode_developpeur.py`.

## Serveur 0.55.2 (2026-10-27), schémas et README remis à l'état du code
Correctif de documentation. Appli Home Assistant 0.55.2 (même code), appli Android et client web inchangés.
- Les quatre schémas de `docs/images/` (thèmes clair et sombre) ne marquent plus comme prévu ce qui est livré :
  client web sur le port 8767 et appairage par clé d'accès (architecture), contexte de requête (trajet d'une
  phrase), droits par rôle appliqués par le serveur (rôles et droits), moteur et gestion des routines à la voix
  (routines). Restent en pointillé la flèche de refus et les pastilles « Plus tard » des routines.
- README : mêmes corrections dans les légendes, les textes alternatifs et la section Rôles et routines. Restent
  annoncés comme à faire l'écran des routines du client web et les routines automatiques.

## Serveur 0.55.1 (2026-10-27), logement de l'orbe coupé en deux dans la barre du client web
Correctif. Appli Home Assistant 0.55.1 (même code), appli Android inchangée. Client web 0.9.1, page 3D inchangée.
- Le propriétaire ne garde que la moitié basse du logement : plus de berceau soulevé au-dessus de la barre, dont le
  bord haut redevient droit. Un demi-disque de 33 px de rayon est creusé dans la barre, centré sur ce bord, avec le
  filet qui suit son contour, l'ombre qui tombe de la lèvre et un liseré clair au fond. L'orbe garde sa place, sa
  moitié haute dépasse de la barre. Le masque SVG et le débord de 40 px des calques de la barre disparaissent.

## Serveur 0.55.0 (2026-10-27), barre d'onglets du bas et vue 3D lisible sur téléphone dans le client web
Mineure. Appli Home Assistant 0.55.0 (même code), appli Android inchangée. Client web 0.9.0, page 3D 0.9.0.
- Barre d'onglets fixe en bas de chaque écran du client web (Accueil, Journal, Maison, Météo), avec l'orbe du micro
  au centre, à la place de la grande page de menu de l'accueil (demande du propriétaire). Rendue par le serveur
  (`barre_onglets`, modèles `{{onglets:CLE}}` et `{{onglets-cache:CLE}}`), seul le nom de l'assistant y entre,
  échappé. L'accueil ne la montre qu'une fois la session vérifiée, Réglages et Vie privée passent par un bouton en
  haut de l'accueil.
- L'orbe ouvre `/ecouter` (la page Demander, qui lance le micro aussitôt et reprend l'adresse `/demander`). Sur la
  page Demander, il parle et se tait sans quitter la page. Si le navigateur garde le son bloqué faute de geste, la
  page invite à toucher le micro au lieu d'écouter dans le vide.
- Au centre, la matière de la barre se soulève en berceau derrière l'orbe (disque de 38 px raccordé au bord par
  deux congés de 12 px, masque SVG), creusé d'un logement éclairé d'en haut où l'orbe flotte sans le toucher, son
  ombre tombant au fond. Il remplace l'encoche des essais précédents, dont le raccord faisait une marche.
  Le libellé du micro ne s'affiche plus (l'`aria-label` le garde), les autres libellés partagent une même ligne
  de base, et le contenu réserve la hauteur de la barre en bas.
- Vue 3D sur téléphone (cadre de moins de 500 px) : le plan occupe tout le cadre (message `disposition`) et se voit
  de dessus (nouveau message `vue` du pont, `nom` à `dessus` ou `perspective`). Les noms des pièces passent à la
  ligne, et si deux noms se recouvrent encore, celui de la pièce la plus étroite à l'écran s'efface.
- Tests : `test_serveur_web_onglets.py`, cas `vue` et `disposition` dans `test_serveur_web_vue3d.py`.

## Serveur 0.54.1 (2026-10-27), amorçage local du premier propriétaire du client web
Correctif. Appli Home Assistant 0.54.1 (même code), appli Android et client web inchangés.
- Le serveur du PC n'a pas de page d'administration, donc rien pour confirmer un appairage. L'option
  `--amorcer-proprietaire NOM` ouvre, au démarrage et seulement si aucun propriétaire n'existe, un appairage
  propriétaire dont le code vaut 15 minutes (`VALIDITE_AMORCAGE_MAX_S`). Le code n'est écrit que dans
  `amorcage_web.json` du dossier de données, jamais dans le journal.
- Le code saisi sur le tailnet tient lieu de confirmation, comme la confirmation sans clé faite depuis Home
  Assistant : seule l'ouverture d'amorçage se confirme seule, après la réponse « attente » au navigateur
  (`AmorcageLocal`). Le fichier du code est effacé dès que l'appairage aboutit, se ferme ou expire.
- `ouvrir()` accepte `duree_s`, réservé à l'acteur « ha » et borné entre 2 et 15 minutes.
- `.gitignore` : `appareils_web.json`, `sessions_web.json` et `amorcage_web.json` n'entrent plus dans le dépôt.
- Tests : `test_amorcage_web.py`.

## Serveur 0.54.0 (2026-10-27), écran Météo et mer et mode développeur dans le client web
Mineure. Session S-W5 du plan. Appli Home Assistant 0.54.0 (le déploiement copie aussi `meteo_web.py`), appli Android
inchangée. Client web 0.8.0.
- Écran Météo et mer (`/meteo`, `meteo.html`, `meteo.js`), d'après la planche 14 des maquettes. Il n'ouvre aucune
  source réseau : il présente ce que le serveur produit déjà (`meteo_mer.py` pour le ciel, la houle et les heures,
  `vent_mesure.py` pour les balises). Un message dédié `meteo` à schéma strict (clés `type` et `point` seulement),
  filtré par rôle côté serveur (`meteo_web.py`) : le rôle vient de la session, jamais du message, l'invité reçoit un
  refus `droit`, aucune coordonnée ni adresse ne quitte le module. Six heures et trois jours au plus, vent en mots
  (force, secteur), symbole du ciel, balises avec leur âge et la mention « ancienne » au-delà du seuil. Une source
  éteinte n'est pas une panne, une source qui échoue donne un avertissement nommé, les deux absentes donnent
  `indisponible`, et aucun texte d'exception ne part vers le navigateur. Lien depuis l'accueil.
- Nouvelle clé de configuration `client_web.meteo.roles` (rôles qui ont l'écran, valeurs fictives dans `config-exemple/maison.json`). Les points
  et les balises viennent de la section `mer` déjà existante.
- Mode développeur du client web : réglage dans Réglages, actif par défaut, gardé dans le navigateur (`localStorage`,
  un « oui » ou un « non », repli en mémoire si le navigateur refuse). Coupé, il masque sur toutes les pages les
  versions, la date de génération, les durées, les identifiants et le détail des étapes (classe `dev-seulement`, attribut
  `data-dev` de `<html>`), jamais une information de sécurité ni un message d'erreur. L'état est transmis à la vue 3D
  isolée par un message `modeDeveloppeur` booléen à schéma strict, et la page 3D (générée par `carte/3d/generer_3d.py`,
  à régénérer pour en profiter) masque sa version et son panneau de démonstration.
- Tests : `test_meteo_web.py`, `test_serveur_web_meteo.py`, `test_mode_developpeur.py`, variantes de l'écran Météo dans
  le contrôle de mise en page (zéro défaut), pont de la vue 3D étendu.

## Serveur 0.53.0 (2026-10-27), HA au centre : relais santé et IA locale optionnels dans l'appli Home Assistant
Mineure. Lot « HA au centre », partie code. Le PC fixe devient un fournisseur de puissance facultatif, tout marche
PC éteint. Appli Home Assistant 0.53.0, appli Android inchangée. Deux options nouvelles, vides par défaut : tant
qu'elles sont vides, le comportement et l'exposition réseau sont exactement ceux de la 0.52.0.
- Relais santé en profil ha : option `sante_jeton` (SANTE_JETON), adresse par SANTE_URL ou `reseau.sante_url`. Le
  relais (`sante.py`) et l'historique (`sante_hist.py`) existent en profil ha dès qu'un jeton est renseigné, sans
  jeton ils n'existent pas (comme avant). Garde inchangée sur la destination (seulement une adresse Tailscale, jamais
  le jeton vers autre chose, jamais dans le journal, une erreur, une réponse ou les capacités). Garde de route
  adaptée : le conteneur est sur le réseau pont de Docker et ne voit pas la route de l'hôte, `route_tailscale` admet
  donc en profil ha une adresse source du pont privé (172.16.0.0/12, fc00::/7) en plus de Tailscale, le profil pc
  reste strict. En https la connexion vise l'adresse vérifiée et le certificat est contrôlé contre le nom (SNI).
  Risque résiduel : Tailscale coupé sur l'hôte de HA avec un DNS qui rend quand même une adresse en 100.x, un jeton
  en http clair partirait par la route par défaut, d'où la préférence pour une `sante_url` en https.
- IA locale du PC en fournisseur optionnel (`poc/llm_local.py`) : option `llm_local_url` (LLM_LOCAL_URL, serveur
  compatible OpenAI en `/v1`). Vide, rien ne change et le choix « local » n'existe pas en profil ha. Renseignée, le
  cerveau « local » est proposé, avec une sonde courte (`GET /models`, 2 s au plus, résultat gardé 45 s si oui et 30 s
  si non) et un repli automatique sur Claude, signalé au journal sans l'adresse. Le repli n'a lieu qu'avant la première
  exécution d'outil, pour qu'une action ne soit jamais faite deux fois. Les historiques sont partagés entre les deux
  cerveaux et la sécurité en dur s'applique quel que soit le cerveau. Le choix par défaut reste Claude. Sur le PC rien
  ne change.
- Correctif préexistant : `changer_cerveau` ne reposait pas `rappel_routine` ni `rappel_liste` sur le nouveau cerveau,
  qui ne savait plus proposer ni lister de routine après un changement de cerveau. Corrigé par `brancher_cerveau`.
- Note de conception `docs/conception/client-web-sur-ha.md` : comment servir le client web depuis l'appli HA.
- `deployer.sh` copie désormais `llm_local.py` dans l'image de l'appli (le test des modules importés l'exigeait).

## Serveur 0.52.0 (2026-10-27), vue 3D, volet télé complet et graphique de l'air dans le client web
Mineure. Session S-W4b du plan. Appli Home Assistant 0.52.0 (le déploiement copie aussi `vue3d.html` quand elle est
générée), appli Android inchangée. Client web 0.7.0.
- Vue 3D : la page `vue3d.html` (produite par `carte/3d/generer_3d.py`) est servie par la route `/vue3d`, réservée aux
  sessions ouvertes. Sa CSP est propre : un hachage SHA-256 par script et par style en ligne recalculé à chaque envoi,
  aucune source réseau, `frame-ancestors 'self'`, `sandbox allow-scripts`. Elle est montée dans une iframe
  `sandbox="allow-scripts"` sans `allow-same-origin` : origine opaque, aucun accès aux cookies ni à la page.
- Pont `postMessage` à schéma strict des deux côtés : types connus seulement, champs typés et bornés, identifiants au
  motif sûr, fenêtre et origine `null` vérifiées côté Maison, fenêtre parente vérifiée côté page. La page n'émet que
  `pret` et `designation` (jamais un ordre), l'écran Maison décide seul de ce qu'il en fait avec les droits du rôle.
  Les états envoyés à la 3D sont ceux déjà filtrés par rôle. `window.vue3d` remplace `window.maison3d`, gardé en alias
  pour la tablette Android.
- Volet de la télé complet : allumer, éteindre, volume, source (prise dans la liste renvoyée par Home Assistant),
  lecture et pause, piste suivante et précédente, muet, pour les seuls rôles qui ont la télé. `SERVICES_WEB` élargi à
  ces services, chacun passant par `acces.controler_service` avec la liste étroite `services_permis`, et le plafond de
  volume de sécurité s'applique. Une commande que l'appareil ne sait pas faire n'est pas proposée.
- Message `air_historique` (rôles qui ont les mesures seulement) : mêmes données que la tablette
  (`historique_air.py`), durée et nombre de points bornés, réponse reconstruite et mise en cache une minute.
  `serveur_satellite.air_historique_depuis_ha` factorise les deux appels à Home Assistant pour la tablette et le web.
- Client web 0.7.0 : toucher la carte des mesures d'une pièce ouvre un graphique en fonction du temps (6 h, 24 h,
  7 jours, quatre séries), dessiné en SVG par `createElementNS` (CSP sans style en ligne, sans `innerHTML`).

## Serveur 0.51.0 (2026-10-27), écran Maison du client web
Mineure. Session S-W4a du plan. Appli Home Assistant 0.51.0 (copie aussi `maison_web.py`), appli Android inchangée.
Client web 0.6.0.
- Nouveau `poc/maison_web.py` : la liste des pièces, lampes et télévisions vient de `client_web.maison` dans
  `maison.json`, jamais du code. Message `etats` filtré par rôle : un navigateur ne reçoit que les entités de la liste de
  son rôle, une pièce protégée n'est qu'une ligne sans entité ni mesure, une mesure absente ou un capteur manquant est
  dit tel quel (aucune valeur inventée).
- Message `regler` à schéma strict (entité, action nommée, valeur bornée, aucune clé en trop). Le service Home
  Assistant est reconstruit par le serveur, jamais recopié du navigateur, puis passé par `acces.controler_service` et
  donc par `securite.verifier`. Réponses `regle` et `erreur` à cause fermée (droit, format, entité, action, valeur,
  protégée, sécurité, injoignable, indisponible).
- Suivi du réglage : « en attente » puis « non appliqué » si la lampe ne rejoint pas la consigne dans le délai fixé par
  `client_web.maison.reglage_attente_s` (5 s par défaut, 60 s au plus). Tolérances de comparaison : 100 K, 8 degrés de
  teinte, 6 points d'intensité. Un échec n'est plus signalé au bout de 5 minutes.
- `serveur_web.py` : pages `/maison` et `/maison.js`, messages `etats` et `regler` ajoutés à la liste blanche, état lu
  au plus une fois par seconde pour tous les navigateurs, mesures au plus une fois par minute.
- Client web 0.6.0 : écran Maison (une carte par pièce dans l'ordre de la configuration, interrupteur et chevron par
  lampe, ligne de la télé avec allumer, éteindre et volume seulement, alerte d'air en haut avec la consigne en mots,
  mesures en lecture seule toujours accompagnées d'un mot). Volet lampe en feuille basse à deux onglets, Blanc
  (intensité, quatre blancs nommés, piste de chaleur bornée) et Couleur (huit couleurs nommées, bande de teintes).
  Réglages envoyés pendant le glissement, un par famille et par entité toutes les 500 ms, 24 messages par 10 secondes
  au plus. États d'échec de la planche 18 : lampe injoignable, réglage en attente, réglage non appliqué, pièce protégée.
- Hors de ce lot (S-W4b) : vue 3D en iframe isolée, volet de la télé complet (sources, lecture), graphique
  d'historique de l'air.

## Serveur 0.50.0 (2026-10-27), demander depuis le client web
Mineure. Session S-W3 du plan. Appli Home Assistant 0.50.0 (copie aussi `demande_web.py`), appli Android inchangée.
Client web 0.5.0.
- Nouveau `poc/demande_web.py` : quotas par appareil et par rôle (fenêtre glissante, `client_web.quotas` de
  `maison.json`, faibles pour l'invité), validation du texte, de l'enregistrement (PCM 16 bits, 16 kHz, mono, 20 s au
  plus) et liste fermée des causes de refus renvoyées au navigateur.
- Messages `demande_texte` et `demande_voix` acceptés sur la connexion web seulement, ouverts à tout rôle mais bornés
  par les quotas. Appareil, personne et rôle sont ceux de la session : le champ `personne` du message n'est jamais lu.
  L'essai effectif est celui du serveur OU celui du message, jamais l'inverse.
- `Moteur.repondre_web` : même chaîne que les autres appareils (`llm_texte`, donc phrase protégée, routines, cerveau,
  `acces.controler_service` et `securite.verifier` pour chaque action). La réponse revient en texte au navigateur, la
  tablette ne parle jamais pour une demande du téléphone. Les étapes vont au journal comme celles des satellites.
- `llm_texte` accepte le rôle de l'appelant. Le rôle d'un navigateur associé (`web:<id>`) est lu dans son entrée
  d'appairage (avant, `role_effectif` le voyait invité).
- Client web 0.5.0 : écran Demander (`/demander`), demande écrite puis demande vocale (bouton micro, planches 11a
  Écoute, 11b Réponse, 11c Essai de la maquette).
- Demande vocale : le navigateur envoie un enregistrement PCM 16 bits, 16 kHz, mono (de 0,2 à 20 s), échantillonné
  côté client. Le serveur le valide, le transcrit en local seulement (reconnaissance du PC, sinon Whisper de Home
  Assistant, jamais de repli en ligne) puis suit la chaîne du texte. Le texte compris revient avec la réponse. Limites
  du WebSocket : 64 Kio par message, 1 Mio pour la voix, fermeture 1009 au-delà. `Permissions-Policy` ouvre
  `microphone=(self)`.
- Hors de ce lot : le bouton « Ce n'était pas ça » (le mécanisme `A.RETOURS` est côté satellite) et la transcription
  en direct pendant l'écoute (le texte compris n'apparaît qu'avec la réponse).

## Serveur 0.49.0 (2026-10-27), journal du client web
Mineure. Session S-W2 du plan. Appli Home Assistant 0.49.0 (copie aussi `journal_web.py`), appli Android inchangée.
Client web 0.4.0. La 0.48.0 est celle du graphique de l'air (S-L8), sur une autre branche.
- Cœur `poc/journal_web.py` : trois niveaux de vie privée (Tout, Action seulement, Discret), visibilité calculée
  pour chaque spectateur (le propriétaire de la maison et un habitant n'ont pas les mêmes droits sur les entrées des
  autres), projection d'une entrée selon le spectateur, lecture par pages de sept jours, effacement des entrées d'une
  personne, conservation de 30 jours. Un navigateur ne reçoit jamais ce qu'il n'a pas le droit de voir : la
  projection se fait côté serveur, le client n'affiche que ce qu'il reçoit. Les demandes de santé des autres ne sont
  jamais diffusées aux habitants.
- Journal du serveur : chaque entrée garde son niveau d'alors, l'identifiant de la demande (`ID_DEMANDE`) relie la
  carte « En cours » à l'entrée écrite ensuite. Fichiers par jour `assistant-AAAA-MM-JJ.jsonl`, `vie_privee_web.json`
  pour le choix de chacun (niveau par défaut : Discret).
- Messages du WebSocket : `abonner_journal`, `desabonner_journal`, `journal_page`, `vie_privee`, et les envois
  `journal_ajout`, `journal_etape` (étape « entendu » seulement, en direct, pour l'auteur), `journal_retrait`,
  `journal_efface`. Changer de niveau ou effacer ses entrées exige la clé d'accès (`defi` puis `preuve`) pour tous les
  rôles, y compris pour devenir plus discret. Le niveau ne vaut que pour les demandes à venir.
- Écrans du client web : `/journal` (liste par jour, filtres Tout, Les miennes, Autres, Refus, feuille de détail, carte
  « En cours », jours plus anciens) et `/vie-privee` (trois niveaux, aperçu de ce que voient les autres, alertes,
  « Le journal garde vos demandes 30 jours. Le son n'est jamais conservé. », « Effacer mes entrées du journal »).
  Liens depuis l'accueil.
- Hors de ce lot : le client web n'émet pas encore de demandes (S-W3), les entrées viennent des satellites, des
  routines et du micro du PC. Le bouton « Ce n'était pas ça » et l'effacement de `musique.jsonl` restent à faire.
- Tests : droits par rôle et par spectateur (un appareil non auteur ne reçoit rien qu'il ne peut voir), retenue de 30
  jours, preuve obligatoire, pages protégées. Variantes de mise en page des deux écrans et de l'accueil.

## Outil (2026-10-27), profils Chrome fixes pour le contrôle de mise en page, sans changement de version
- `poc/outils/verifier_mise_en_page.py` ne crée plus un profil Chrome neuf à chaque lancement. Au premier
  démarrage d'un profil, Chrome teste sous Windows un mot de passe vide, compté comme un échec de connexion : à
  force, le compte Windows se verrouillait (seuil de 10). Quatre profils fixes réutilisés dans
  `%LOCALAPPDATA%\verifier-mise-en-page\profil-N`, un verrou par profil pour les exécutions en parallèle,
  `DevToolsActivePort` d'un lancement précédent effacé avant le démarrage.

## Serveur 0.48.0 (2026-10-27), historique de l'air d'une pièce
Mineure. Session S-L8 du plan. Appli Home Assistant 0.48.0 (copie aussi `historique_air.py`), appli Android 0.47.0.
- Nouveau message `air_historique` (le client donne une pièce et une durée en heures, rien d'autre). Le serveur
  déduit les entités du relevé des capteurs de la carte (`correspondance_pieces`, thermomètre dédié prioritaire,
  identifiants `sensor.*` validés), refuse une pièce inconnue ou protégée, plafonne la durée à 168 h, puis
  interroge `/api/history/period` de Home Assistant (états seuls, sans attributs).
- Mise en forme dans `poc/historique_air.py` : un état vaut jusqu'au suivant sans dépasser 2 h (comme la carte),
  `unavailable` et `unknown` font un trou et jamais un zéro, au plus 288 intervalles égaux en moyenne pondérée par
  le temps, puis moyenne entre capteurs d'une même grandeur. Réponse : CO2, PM2.5, température, humidité.
- Capacité `air_historique` annoncée, type permis aux rôles du foyer (administrateur, habitant, partage), refusé à
  l'invité (`poc/acces.py`). `mesures.marquer_dedies` extrait pour être partagé avec la carte.
- Tests : `poc/tests/test_historique_air.py`. `deployer.sh` copie le nouveau module.

## Documentation (2026-10-27), accès au client web par Tailscale Serve (S-W7), sans changement de version
Session S-W7 du plan. Nouveau `docs/ACCES-TAILSCALE.md` : publication du port 8767 par Tailscale Serve sur le port
443, réglage de `client_web.hote` et `administration.url_client`, ce que le serveur accepte comme `Host` et `Origin`,
lecture des refus du journal, retour arrière, et liste à cocher de l'essai depuis un téléphone. Nouveau modèle
`config-exemple/tailnet-acl.exemple.hujson` : ACL du tailnet en liste blanche, valeurs fictives, avec un bloc de
tests. Renvois ajoutés dans `README.md`, `docs/INSTALLER.md` et `docs/CONFIGURER.md`, dont la section `client_web`
décrit enfin `invite_jours` et l'appairage livré en S-W1b. Serveur, appli Home Assistant et appli inchangés.

## Serveur 0.47.0 (2026-10-27), appairage WebAuthn du client web
Mineure. Session S-W1b du plan. Appli Home Assistant 0.47.0 (copie aussi `webauthn.py` et `appairage_web.py`),
appli Android inchangée (0.46.2). Client web 0.3.0.
- Appairage d'un téléphone par une clé WebAuthn propre à l'appareil (ES256, attestation `none`), sans mot de passe.
  Module pur `poc/webauthn.py` (CBOR borné, vérifications de `type`, `origin`, `rpIdHash`, drapeaux UP et UV,
  compteur de signatures) et cœur `poc/appairage_web.py` (code à 6 chiffres de 2 minutes, trois essais, défis
  aléatoires à usage unique, tickets, un seul navigateur à la fois pendant la fenêtre).
- Transport : les échanges WebAuthn passent par un WebSocket de même origine (`process_request` ne voit pas le
  corps d'un POST). Seul le cookie `__Host-session` sort d'une réponse HTTP (`GET /appairage/fin` avec un ticket).
- Amorçage du premier propriétaire : depuis la page d'administration de Home Assistant (Ingress), nouvelle section
  « Navigateurs web ». Elle ne crée un propriétaire que s'il n'en existe aucun. Repli en console :
  `python poc/appairage_web.py --reinitialiser`.
- Stockage : `appareils_web.json` (clés publiques et compteurs, droits 0600, écriture atomique) et
  `sessions_web.json` (empreintes seulement) dans le dossier de données. La clé d'accès est redemandée pour
  appairer et révoquer. Le changement de confidentialité n'existe pas encore dans ce lot.
- Écrans du client web : `/appairage` (saisie du code), `/associer` (le propriétaire ouvre, confirme), `/reglages`
  (appareils associés, révocation, oubli de ce navigateur). Contrôle de mise en page à zéro défaut
  (`poc/tests/test_pages_web_mise_en_page.py`).
- Nouvelle clé de configuration `client_web.invite_jours` (7 par défaut), `hote` sert aussi de rpId.

## Serveur 0.46.1 (2026-10-27), levée complète de la règle 1
Correctif, demandé par le propriétaire : l'occupant se sert aussi de l'assistant. Appli Home Assistant 0.46.1,
appli Android 0.46.2.
- `PROTEGER_OCCUPANT` gouverne désormais tout ce qui le concerne. À False, le serveur ne passe plus les
  `zones_protegees` au relevé des mesures : sa chambre montre ses valeurs au lieu de « pièce protégée ».
- Le filtre de phrases du repli Assist ne garde plus ses mots (`MOTS_PROTEGES`, `MOTS_PIECES`, son nom) quand
  la règle est levée. Les autres refus du repli (identifiants bruts, étage, étiquette, serrures, alarmes,
  plafond de volume) sont inchangés.
- Tests : la règle active garde son comportement d'avant (drapeau forcé à True), la règle levée ne cache rien.

## Documentation (2026-10-27), superpositions des maquettes du client web (S-W0d), sans changement de version
Session S-W0d du plan. Les superpositions relevées dans les maquettes du client web sont corrigées (maquettes
1.0.1). Nouvel outil `poc/outils/verifier_mise_en_page.py`, qui mesure les chevauchements et débordements d'une
page dans un navigateur sans fenêtre, et test `poc/tests/test_maquettes_mise_en_page.py`. Serveur, appli Home
Assistant et appli inchangés.

## Serveur 0.46.0 (2026-10-27), socle HTTP du client web
Mineure. Session S-W1a du plan. Appli Home Assistant 0.46.0 (copie aussi `serveur_web.py` et `web/`), appli
Android inchangée (0.46.0).
- Nouveau serveur HTTP du client web pour téléphone, `poc/serveur_web.py`, sur 127.0.0.1:8767 par défaut
  (`--port-web`, `JARVIS_PORT_WEB`, 0 pour le couper, `--adresse-web`, `JARVIS_ADRESSE_WEB`). Port pris : le
  serveur le dit et les satellites continuent de servir.
- `Host` et `Origin` exacts : boucle locale, ou le nom de Tailscale Serve lu dans la nouvelle clé
  `client_web.hote`. Tout le reste reçoit un 403 sans détail.
- Cookie de session `__Host-session` (Secure, HttpOnly, SameSite=Strict), jeton de 256 bits gardé en empreinte
  seulement, durée glissante (`client_web.session_jours`, 30 jours) avec un plafond, révocation.
- En-têtes de sécurité sur toutes les réponses (CSP stricte sans rien en ligne, HSTS, nosniff, no-referrer,
  Permissions-Policy fermée). Page d'accueil installable (manifeste, icônes, polices locales) avec la version en
  pied de page. `/appairage` répond « pas encore disponible » (S-W1b).
- Journal : une ligne par refus, adresse et cause courte d'une liste fermée, jamais un cookie, un jeton ni un
  chemin.

## Serveur 0.45.1 (2026-10-26), connexions en clair restreintes
Correctif. Session S-D5 du plan (décision D7). Appli Home Assistant 0.45.1, pendant de l'appli 0.45.0.
- Nouvelle clé `acces.clair_restreint`. Quand elle vaut true, une connexion qui n'arrive pas en wss est fermée
  avec le code 4003, sauf depuis la boucle locale (127.0.0.1, ::1). Le motif est écrit au journal, jamais un jeton.
- Réglage absent ou faux : comportement inchangé, le port 8765 reste ouvert.

## Serveur 0.45.0 (2026-10-26), mesures par pièce
Mineure. Session S-L6 du plan. Appli Home Assistant 0.45.0, pendant de l'appli 0.44.0.
- Nouvelle demande `mesures` (capacité `mesures`, pas pour le rôle invité) : température, humidité, CO2 et
  particules fines par pièce, lues sur Home Assistant par un seul gabarit posté sur `/api/template`.
- Seuils de l'air communs avec l'appli (`poc/tests/cas_mesures.json`) : CO2 800, 1000 et 1500 ppm, PM2.5 9, 35,4
  et 55,4. Température en trois mots (frais, agréable, chaud), le chiffre reste affiché.
- Les zones de `securite.zones_protegees` sont écartées dès Home Assistant, leurs pièces ne portent aucune valeur.
- Nouvelle clé `correspondance_pieces` (pièce de la carte vers zones de Home Assistant). Sans elle, aucune mesure.

## Serveur 0.44.2 (2026-10-26), repli Assist coupé par défaut
Correctif. Session S-D9 du plan (décision D8, dette I9). Appli Home Assistant 0.44.2, appli Android inchangée.
- Le repli vers Assist de Home Assistant est coupé par défaut. Le réglage `securite.assist_repli` (booléen `true`
  seulement) l'ouvre, uniquement après un échec du LLM et jamais en mode essai.
- Même ouvert, le repli refuse toute phrase que la sécurité écarte ou ne sait pas contrôler d'avance (serrures,
  alarmes, cuisson, chauffage, visée en bloc, volume plafonné, occupant protégé), avec le motif au journal
  (`[repli Assist]`). `SECURITE_ACTIVE` et les règles de `verifier()` ne changent pas.

## Serveur 0.44.1 (2026-10-26), notes du LLM à l'export
Correctif. Session S-D7 du plan (constat C6). Appli Android 0.43.1, appli Home Assistant 0.44.1.
- L'export du dictionnaire pour l'appli porte `llm.notes` tel quel, couvert par de nouveaux tests (notes
  présentes, modifiées, absentes). Aucun changement du serveur lui-même.

## Serveur 0.44.0 (2026-10-26), lampes et télévision à la voix
Nouveauté. Session S-L4 du plan. Appli Android 0.43.0 (même moteur), appli Home Assistant 0.44.0.
- `config-exemple/commandes.yaml` : couleur (« mets le salon en bleu »), blanc nommé (bougie, chaud, neutre, froid),
  luminosité en pourcentage et relative, « plus chaud » et « plus froid », puis la télévision (chaîne suivante ou
  précédente, pause et reprise, volume par pas de trois, sourdine, son de nuit de la barre de son).
- Nouveau module `poc/commandes_dynamiques.py` : actions « dynamiques » dont le service dépend de l'état d'un appareil,
  lu juste avant d'agir. `selon_etat` (« monte » vise le volume si la télé est allumée, la lumière sinon, de même pour
  « baisse » et « pause ») et `kelvin_pas` (un pas de couleur de lumière borné par les minimum et maximum de chaque
  lampe). Résolues après `personnes.appliquer` et avant le contrôle de sécurité, qui voit donc des actions ordinaires :
  rien n'est contourné, le plafond de volume refuse toujours un `volume_up`. Mode essai ou Home Assistant injoignable :
  aucun état lu.
- Pièges de phrases traités et testés : « rose » et « orange » seulement derrière « en » (une rose dans le vase, une
  orange mangée ne font rien), « chaud » vise la lumière (« il fait chaud » et « mets le chauffage » ne la touchent
  pas), « monte » seul dépend de la télé.
- Piège YAML 1.1 : `on` non cité devient le booléen True dans la liste `etats`. Les listes de commandes.yaml citent
  `"on"` et `_nom_etat` ramène un booléen à son nom d'état.
- `ha-app/deployer.sh` copie le nouveau module. Tests : `cas_dynamique.json` (22 cas) et `cas_commandes_lampes_tele.json`
  (une cinquantaine de phrases, dont 11 qui ne doivent rien déclencher), partagés avec la tablette.

## Serveur 0.43.3 (2026-10-26), demandes de routine dites naturellement
Correctif court. Appli Android inchangée (0.38.1, elle devra appliquer le même motif), appli Home Assistant 0.43.3.
- `INTENTION_ROUTINE` (`poc/assistant.py`) ne reconnaissait que « crée une routine », « nouvelle routine », « quand je
  dis ... » et « désormais ». Une phrase comme « Crée-moi une routine qui ... » (le « -moi » cassait l'espace
  attendue) ou « Je voudrais une routine » partait au LLM ordinaire, qui n'a pas l'outil de création.
- Formes ajoutées : crée, fais, ajoute, programme, mets en place, enregistre, configure, prépare, avec « -moi » ou
  « -nous » facultatif et « une (nouvelle, petite) routine », puis « je voudrais / je veux / je souhaite /
  j'aimerais (créer) une routine ». Le mot « routine » reste exigé, « fais la routine du matin » reste un
  lancement, « je fais une routine » est ignoré, « scénario » n'est pas reconnu. Liste détaillée dans la note de
  conception des routines, 4.1.
- Chaque phrase de `cas_routines.json` est testée brute et après `epurer` (celle que reçoit `routines_avant`).
  22 phrases positives et 15 négatives ajoutées, soit 101 cas de test de plus.

## Serveur 0.43.1 (2026-10-26), boucle d'outils commune et commentaires
Session S-D6 du plan 1.2.0 (correctif, aucun changement de comportement). Appli Android inchangée (0.38.1), appli
Home Assistant 0.43.1.
- Les deux boucles d'appel d'outils de `poc/assistant.py` (`Cerveau.repondre` pour le serveur local, format OpenAI
  `tool_calls`, et `CerveauClaude.repondre` pour Claude, format Anthropic `tool_use`) partagent maintenant
  `Cerveau.boucle_outils` : limite de six tours, exécution des outils par l'aiguillage fermé `executer_outil`, parole
  fixée par une routine, phrase de repli. La fin d'une demande (garde-fou de musique, historique) est dans
  `Cerveau.terminer_tour`. Chaque format ne garde qu'un adaptateur mince (appel à l'API, lecture d'un appel, ajout
  aux messages) autour du type `TourLLM`. La relance unique du modèle local (« j'ai allumé » sans outil) reste dans
  son adaptateur, la mesure des appels et le refus du modèle dans celui de Claude.
- Nouveau `poc/tests/test_boucle_outils.py` (34 tests, écrits d'abord et vérifiés sur l'ancien code) : les deux
  chemins sont joués avec de faux clients, sur les mêmes cas (réponse directe, outil puis réponse, plusieurs appels,
  outil inconnu, domaine interdit, volume non demandé, musique non confirmée, parole fixée, modes isolés,
  historique, limite de six tours, relance, refus du modèle, arguments illisibles). Suite complète : 1537 réussis,
  8 ignorés.
- Commentaires corrigés : repère de substitution de `CONSIGNE` remis à côté de ce qu'il décrit, docstring de
  `Cerveau` ajoutée, source de la clé de `CerveauClaude` complète (option de l'appli HA, jeton), nombre de tours du
  LLM pour la musique, renvoi vers la note de conception des routines.

## Serveur 0.43.0 (2026-10-26), routines, lot 2 : gestion à la voix
Session S-R2 du plan 1.2.0. Appli Android inchangée (0.38.1), appli Home Assistant 0.43.0.
- Commandes de gestion sans LLM, par un petit analyseur de `poc/routines.py` (`analyser`, `gerer`) : « quelles sont
  mes routines », « que fait la routine X », « coupe la routine X », « réactive la routine X », « supprime la routine
  X », « lance la routine X ». La cible se cherche par le nom ou par une phrase, à l'identique puis approchée. Deux
  candidates ou aucune : la réponse le dit et cite les noms. Un verbe d'écriture sur « toutes mes routines » est refusé.
- Ordre de traitement : ces commandes passent après le brouillon et avant la correction vocale, donc « oublie la
  routine Arrivée » supprime la routine et non la dernière leçon apprise.
- Suppression : confirmation obligatoire (« Je supprime la routine X ? »), mêmes délai et absorption que la création.
  La copie complète de la routine reste dans `journal/routines.jsonl`.
- Réactivation : revalidation complète des étapes (inventaire de la personne, liste blanche, réglages). Une étape
  devenue refusée garde la routine coupée, avec le motif dans `a_revoir`.
- Modification : elle passe par la création (`remplace`). La reformulation dit maintenant ce qui change
  (« Avant : ... Après : ... Je remplace ? »), et élide « j'allume », « j'éteins ».
- Droits inchangés : le propriétaire gère tout, un habitant les siennes, un invité et une personne non reconnue
  listent, décrivent et lancent les routines « pour tous » sans rien modifier.
- Retour « mauvais » sur une commande de catégorie routine : noté dans les retours et dans `routines.jsonl`, sans
  oublier de phrase apprise.
- Les verbes de gestion existent aussi à l'infinitif (« peux-tu supprimer la routine X »). La note « je la remplace »
  n'impose plus « Le reste, je le garde ? » quand elle est seule : la question est « Je remplace ? ».
- Tests : `test_routines.py` complété de 65 tests (une phrase par commande, refus de droits, ordre de traitement,
  suppression confirmée, réactivation revalidée). Suite complète : 1503 réussis, 8 ignorés.

## Serveur 0.42.0 (2026-10-26), moteur de routines, lot 1
Session S-R1 du plan 1.2.0. Appli Android inchangée (0.38.1), appli Home Assistant 0.42.0.
- Nouveau module `poc/routines.py` : une phrase de déclenchement lance une suite d'étapes (service Home Assistant,
  annonce, question, pause, musique). Stockage dans `routines.json` du dossier de données, journal dans
  `journal/routines.jsonl`. Le moteur n'importe pas `assistant.py`.
- Création à la voix : `INTENTION_ROUTINE` reconnaît « quand je dis X, fais Y » et « crée une routine », le cerveau
  propose, le serveur reformule et attend un « oui » (`delai_confirmation_s`, absorption d'un « oui » tardif).
  `Assistant.routines_avant` passe avant le dictionnaire.
- Une routine ne permet jamais plus qu'une commande directe : chaque étape de service passe par
  `acces.controler_service` à la création et à chaque lancement, avec la personne qui lance. Cibles par pièce,
  étage, appareil, étiquette, `all`, joker ou `target` refusées. Routine revalidée au chargement, coupée et marquée
  « à revoir » si une étape est devenue refusée. `securite.py`, `Securite.kt` et `cas_securite.json` inchangés.
- Droits : le propriétaire crée, lance, gère et exporte tout, un habitant crée et gère les siennes, un invité et un
  appareil partagé lancent seulement. Une routine est « pour tous » ou « pour son auteur ».
- Protocole (port chiffré 8766 seulement, table `acces.TYPES_PAR_ROLE`) : `routines`, `routine_lancer`,
  `routine_texte` (tous les rôles), `routine_activer`, `routine_supprimer` (habitant et administrateur),
  `routines_export` (administrateur). Signal `routines_maj` (version seule). Capacité `routines` annoncée.
  Catégorie `routine` dans l'historique.
- Nouvelle section facultative `routines` de `maison.json` (12 clés, toutes facultatives), exemple fictif dans
  `config-exemple/`. Sans la section, comportement par défaut.
- `ha-app/deployer.sh` copie maintenant `routines.py`, et aussi `liste_blanche.py`, oublié à la 0.41.0 alors que
  `acces.py` l'importe (l'appli Home Assistant n'aurait pas démarré).
- Reste pour S-R2 : gestion à la voix (lister, couper, supprimer), écrans des clients.
- Tests : `test_routines.py` et `cas_routines.json`. Documentation : `docs/CONFIGURER.md`, `docs/ARCHITECTURE.md`.

## Serveur 0.41.1 (2026-10-26), correctif du déploiement Home Assistant
Appli Home Assistant 0.41.1, appli Android inchangée (0.38.1).
- `ha-app/deployer.sh` ne copiait pas `poc/liste_blanche.py`, nouveau en 0.41.0 : l'appli Home Assistant 0.41.0
  s'arrêtait au démarrage sur `ModuleNotFoundError: No module named 'liste_blanche'`, la passerelle de la tablette
  ne répondait plus et l'écran affichait « Maison hors ligne ». Le module est ajouté à la copie.
- Nouveau test `test_deployer_copie_tous_les_modules_importes` (`poc/tests/test_demarrage.py`) : tout module de
  `poc/` importé par un module copié doit figurer dans la ligne de copie du script.

## Serveur 0.41.0 (2026-10-26), historique par appareil et liste blanche commune
Session S-F5 du plan 1.2.0. Appli Android inchangée (0.38.1), appli Home Assistant 0.41.0.
- L'historique du LLM est tenu par appareil : la clé (`Cerveau.cle_historique`) est `(personne, appareil)` tirés du
  contexte de requête, donc de la session, jamais d'un nom écrit dans le message. Une requête sans identité d'appareil
  n'a plus d'historique persistant (le micro local du PC, sans appareil, ne garde donc rien d'une demande à l'autre).
  « Qu'est-ce qu'on t'a demandé juste avant » ne rend que les phrases du même appareil.
- Liste blanche commune : nouveau module `poc/liste_blanche.py`, seule copie de `SERVICES_PERMIS`,
  `DOMAINES_HORS_LLM`, des domaines d'administration et des services écartés. `assistant.py` la réexporte.
- Nouvelle section facultative `reglages` de `maison.json` (clés `applis`, `interrupteurs`, `attributs_refuses`),
  lue par `liste_blanche.refus_reglage`, appelée par `acces.controler_service` : les deux voies (LLM et passerelle de
  l'appli) donnent donc la même réponse sur les mêmes cas. Clé absente, règle inactive. L'exemple ouvre cinq applis.
- La passerelle applique aussi la table des services aux trois domaines réservés à l'appli (`domaine_tele`,
  `remote`, `select`) : `domaine_tele.reboot` ou `remote.learn_command` y sont refusés comme par le LLM.
- `securite.py`, `Securite.kt` et `cas_securite.json` sont inchangés : `device_id`, domaines interdits (serrure,
  alarme) et liste blanche sont intacts.
- Tests : `test_historique_appareil.py` (historique par appareil, personne annoncée) et
  `test_liste_blanche_commune.py` (parité des deux filtres). Documentation : `docs/ARCHITECTURE.md`.

## Serveur 0.40.0 (2026-10-26), contexte de requête et point de contrôle unique
Session S-F4 du plan 1.2.0. Appli Android 0.38.1 (versionCode 73, `Securite.kt` seul), appli Home Assistant 0.40.0.
- Contexte de requête (`REQUETE`, existant depuis la 0.28.0) complété : `Requete` porte aussi le `role` (pris de
  l'appareil appairé, ou donné par l'appelant) et le `canal` (`voix`, `texte`, `appli`, `web`). `Assistant.requete`
  et `Assistant.traiter` les acceptent, `Moteur.traiter` ouvre le canal `voix`, `llm_texte` le canal `appli`.
- La personne et le rôle viennent de la session (jeton, `appareils.json`), jamais du champ `personne` du message
  pour `llm`, `ha`, `parler` et `reveil`, qui passent par `acces.personne_effective` (S-F2), sans seconde fonction.
- Point de contrôle unique `acces.controler_service` : domaines interdits, service permis (liste blanche, voie
  du LLM seulement), forme des données (objet à clés textuelles, `entity_id` et `area_id` en texte ou liste de
  textes), URL de `launch_app`, puis `securite.verifier`. Il rend un `Refus` (texte avec son genre) ou rien.
  Appelé par `HomeAssistant.service` (LLM), `Assistant.executer` (dictionnaire appris) et `verifier_requete_ha`
  (passerelle de l'appli), ainsi que par `_musique`. Auparavant trois contrôles voisins divergeaient.
- `securite.verifier` refuse elle-même les domaines `lock` et `alarm_control_panel`, en service comme en cible
  (jusqu'ici seule la passerelle les écartait). Mêmes cas des deux côtés dans `cas_securite.json`, `Securite.kt` suit.
  La sécurité ne fait que se resserrer : `device_id`, `floor_id`, `label_id` et la liste blanche sont intacts.
- Plus d'écriture globale par requête : `ha.personne` devient une propriété en lecture seule alimentée par le
  contexte. Le réglage d'essai du serveur (`essai` de `Moteur`, `Assistant` et `HomeAssistant`) reste un réglage du
  serveur, écrit seulement par `Moteur.changer_mode` sous `moteur.verrou` et lu au début de chaque requête.
- Un corps de requête qui n'est pas un objet est désormais refusé par la passerelle (il passait en `{}`).
- Tests : `poc/tests/test_contexte_requete.py` (deux requêtes simultanées ne se croisent pas, personne forgée
  ignorée, rôle d'un invité tiré de l'appareil, point de contrôle sur les trois voies).

## Serveur 0.39.0 (2026-10-26), fermer l'existant
Session S-F3 du plan 1.2.0. Appli Android inchangée (0.38.0, versionCode 72), appli Home Assistant 0.39.0.
Le point 6 de la session (règles de pare-feu sur 8765 et 8766) n'est pas fait : il attend la décision D7 du
propriétaire, aucune règle n'a été touchée et aucun port fermé.
- Liste blanche des messages du port chiffré 8766 par rôle : une seule table (`acces.TYPES_PAR_ROLE`) et une
  seule fonction (`acces.type_permis`). Type absent de la ligne du rôle : réponse `refuse` claire, journal du
  type et du rôle sans le contenu. Message sans type exploitable : ignoré sans réponse. Les types envoyés par
  l'appli Android et par `poc/admin/` restent permis aux rôles concernés (un test relit les sources Kotlin et
  `admin.js`). Le port en clair 8765 garde son comportement. Table : invité, types communs. Partage, plus
  `vision` et `manque`. Habitant, plus `sante*`. Administrateur, plus les types de gestion.
- `historique` (réponse) et `historique_ajout` (diffusion) filtrés selon le destinataire : administrateur, tout.
  Habitant, son appareil, sa personne et le commun. Partage et invité, leur appareil seul. Une entrée sans
  appareil (micro du PC, écrite avant la 0.39.0) est réservée à l'administrateur.
- Journal : `latences.csv` ne contient plus aucune phrase ni réponse (voie réduite à sa catégorie, rôle, issue,
  nombre d'actions), avec rotation par taille et nombre de fichiers. Les phrases vivent dans l'historique
  quotidien `assistant-AAAA-MM-JJ.jsonl`, purgé après `journal.conserver_jours`. Les `print` de phrases sont
  masqués hors diagnostic (`JARVIS_DIAGNOSTIC` ou `journal.phrases_dans_la_console`). Un ancien `latences.csv` à
  phrases est mis de côté sous `latences-ancien-<date>.csv`.
- Code d'invitation : essais comptés par adresse source sur une fenêtre glissante, une adresse bloquée ne détruit
  plus le code des autres. Un filet global (30 par défaut) détruit le code contre un balayage d'adresses.
- Ingress : `Origin` égal à `X-Forwarded-Host` accepté seulement si la connexion vient de `172.30.32.2`.
- Nouvelles clés de `maison.json` : `acces.invitation_essais_par_ip` (3), `acces.invitation_fenetre_s` (120),
  `acces.invitation_essais_global` (30), section `journal` (`conserver_jours` 30, `taille_max_ko` 512,
  `fichiers_max` 5, `phrases_dans_la_console` false). Documentées dans `docs/CONFIGURER.md`.
- Tests : `poc/tests/test_fermer_existant.py`.

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
