# Configurer l'assistant vocal

Référence de la configuration d'une maison, écrite pour le serveur 0.25.2 et l'appli Android 0.30.1
(24/10/2026). Le moteur ne contient aucune donnée réelle : tout ce qui décrit un logement vit dans un
dossier de configuration à part. Les exemples ci-dessous viennent de `config-exemple/` (valeurs fictives)
ou sont inventés.

Sommaire :

1. [Le dossier de configuration](#1-le-dossier-de-configuration)
2. [maison.json, section par section](#2-maisonjson-section-par-section)
3. [Le dictionnaire commandes.yaml](#3-le-dictionnaire-commandesyaml)
4. [Le plan du logement](#4-le-plan-du-logement)
5. [Les modules facultatifs](#5-les-modules-facultatifs)
6. [La sécurité et ce que la configuration en règle](#6-la-sécurité-et-ce-que-la-configuration-en-règle)

## 1. Le dossier de configuration

### Où le moteur le cherche

Côté Python (`poc/maison.py`), dans cet ordre :

1. La variable d'environnement `ASSISTANT_VOCAL_CONFIG`, ou son ancien nom `MAISON_DOSSIER`. Un chemin
   relatif part du dossier courant du programme.
2. Le dossier `config/` à la racine du dépôt.
3. L'ancien dossier `maison/`, seulement si `config/maison.json` n'existe pas et que `maison/maison.json`
   existe. Un avertissement demande alors de le renommer en `config/`.

Sans `maison.json` lisible (fichier absent, JSON invalide, ou contenu qui n'est pas un objet), le programme
s'arrête avec un message. Il ne retombe jamais sur `config-exemple/`, pour ne pas tourner avec des listes
de sécurité fictives.

Côté appli Android (`android/app/build.gradle.kts`), l'ordre est le même, avec deux propriétés Gradle en
tête : `-PconfigDossier=...` (ancien nom `-PmaisonDossier`), puis `ASSISTANT_VOCAL_CONFIG`, `MAISON_DOSSIER`,
`config/` et `maison/`. Un chemin relatif part de la racine du dépôt. Sans `maison.json`, la fabrication
d'une APK est refusée. Les tests unitaires tournent toujours sur `config-exemple/`, sauf avec
`-PmaisonTests=reel`.

Les tests Python (`poc/tests/conftest.py`) règlent `ASSISTANT_VOCAL_CONFIG` sur `config-exemple/` quand la
variable n'est pas déjà définie.

L'appli Home Assistant reçoit sa configuration par `bash ha-app/deployer.sh`, qui cherche le dossier dans le
même ordre, puis copie seulement `maison.json` et `commandes.yaml` dans `/app/config` du conteneur. Le
démarrage de l'appli règle `ASSISTANT_VOCAL_CONFIG=/app/config` et `JARVIS_DONNEES=/data`. Chaque
déploiement remplace `/app/config`. Le plan, le mot de réveil et `genere/` ne sont pas copiés.

### Ce qu'il contient

| Chemin | Rôle | Lu par |
|---|---|---|
| `maison.json` | Adresses, fuseau, propriétaire, appareils, consignes du LLM, alias pour Assist, listes de sécurité, météo marine, mot de réveil. | Tout le moteur, et l'APK qui le compile en entier dans `BuildConfig.MAISON_JSON`. |
| `commandes.yaml` | Dictionnaire des phrases et des actions Home Assistant, vue du LLM, "ma chambre" selon qui parle. | `poc/dictionnaire.py`, `android/outils/exporter_dictionnaire.py`, `ha-app/configurer-ha.py`. |
| `carte/` | Plan du logement : `pieces.json`, `meubles.json`, `lampes.json`, et les sorties `plan.svg`, `plan.png`, `modele.glb`. | `carte/generer_plan.py`, `carte/3d/generer_3d.py`. |
| `reveil/` | Facultatif : modèle `reveil/<mot>.onnx` du mot de réveil et sa licence `reveil/<mot>.onnx.LICENSE`. | `poc/assistant.py`, `build.gradle.kts`. |
| `genere/` | Fichiers produits, à refaire quand leur source change. | Voir ci-dessous. |

Contenu de `genere/` :

| Fichier | Produit par | Usage |
|---|---|---|
| `genere/android/dictionnaire.json` | `.venv\Scripts\python android/outils/exporter_dictionnaire.py` | Dictionnaire embarqué dans l'APK. Obligatoire pour fabriquer une APK. |
| `genere/android/maison3d/vue3d.html` | `.venv\Scripts\python carte/3d/generer_3d.py` | Vue 3D du logement embarquée dans l'APK. Obligatoire pour fabriquer une APK. |
| `genere/android/carte/*.txt` | À fournir (aucun générateur dans le moteur) | Trait de côte et terre de la carte du vent mesuré (section `vent`). |
| `genere/ha/jarvis_dictionnaire.apercu.json` | `python ha-app/configurer-ha.py --essai` | Aperçu de l'automatisation envoyée à Home Assistant. |

Tout le dossier `genere/android/` devient un dossier d'assets de l'APK.

### En faire un dépôt privé

Le dépôt du moteur ignore `/config/` (voir `.gitignore`). La configuration peut donc être son propre dépôt
privé, cloné à cet endroit :

```bash
cp -r config-exemple config
cd config
git init
git add .
git commit -m "Configuration de la maison"
git remote add origin <adresse de votre dépôt privé>
git push -u origin main
```

Sur un autre poste, il suffit de cloner ce dépôt dans `config/` à la racine du moteur, ou ailleurs avec
`ASSISTANT_VOCAL_CONFIG` qui pointe dessus.

`genere/android/dictionnaire.json` contient aussi les phrases apprises de la machine qui l'a produit (voir
[les phrases apprises](#les-phrases-apprises)). Le versionner revient à versionner ces phrases.

### Ce qui n'y va pas

La configuration décrit la maison, elle ne contient ni secret ni donnée d'usage.

| Donnée | Où elle reste |
|---|---|
| Jeton Home Assistant, jetons des satellites (`SATELLITE_JETON`, `SATELLITE_JETON_<NOM>`), clé Anthropic, clé de transcription en ligne, jeton du service de santé | `poc/.env` de chaque machine (modèle : `poc/.env.exemple`). Sur l'appli Home Assistant, ses options (`ha-app/configurer-options.py`). |
| Phrases apprises (`commandes_apprises.yaml`), journaux (`journal/`), appareils appairés (`appareils.json`), clés TLS (`tls/`) | Dossier de données de la machine : `JARVIS_DONNEES`, `poc/` par défaut sur le PC, `/data` dans l'appli Home Assistant. |
| Profils de visages | Fichier privé de l'appli, sur la tablette seulement. |
| APK | Nulle part : elle embarque `maison.json` en entier et le jeton `SATELLITE_JETON`, elle ne doit pas circuler. |

## 2. maison.json, section par section

### Vue d'ensemble

| Section | Lue par | Si elle manque |
|---|---|---|
| `_lisez_moi` | Personne | Texte d'aide, ignoré par le code. |
| `reseau` | `poc/maison.py`, `poc/assistant.py`, `poc/sante.py`, `poc/sante_hist.py`, `poc/serveur_satellite.py`, `ha-app/*`, `build.gradle.kts` | Adresses vides. `deployer.sh` s'arrête. |
| `fuseau` | `poc/securite.py`, `poc/assistant.py`, `Securite.kt` | `UTC`. |
| `securite` | `poc/securite.py`, `Securite.kt` | Listes vides. |
| `appareils` | `poc/assistant.py`, `SortieSon.kt`, `Appareils.kt`, `MaisonEnGrand.kt`, outils de banc | Musique refusée proprement, écran Musique sans enceinte. |
| `llm` | `poc/assistant.py`, `CerveauAppareil.kt` | Consignes génériques. |
| `ha` | `ha-app/configurer-ha.py` | Aucun alias ajouté, rien d'exposé en plus. |
| `assistant` | `poc/maison.py`, `ha-app/deployer.sh`, `ha-app/configurer-ha.py`, `ha-app/jarvis/app/demarrage.py`, `ConfigMaison.kt`, `build.gradle.kts` | Assistant nommé `Assistant`. |
| `proprietaire` | `poc/maison.py`, `poc/dictionnaire.py`, `poc/sante.py`, `poc/serveur_satellite.py`, `ConfigMaison.kt`, `DictionnaireLocal.kt`, `Sante.kt`, `build.gradle.kts` | Propriétaire nommé `Moi`, avertissement au démarrage et à la compilation. |
| `mer` | `poc/meteo_mer.py`, `MeteoMer.kt`, `MeteoQuestion.kt`, `EcranMeteo.kt` | Météo marine éteinte. |
| `vent` | `poc/vent_mesure.py`, `MeteoVent.kt`, `EcranVent.kt`, `build.gradle.kts` | Vent mesuré éteint. Dans l'appli, la page Mer disparaît aussi. |
| `reveil` | `poc/assistant.py`, `ReveilLocal.kt`, `SatelliteService.kt`, `build.gradle.kts` | Seul "Hey Jarvis" existe. |

Aucune autre section n'est lue par le code.

### `reseau`

Adresses des services de la maison.

| Champ | Type | Effet |
|---|---|---|
| `ha_url` | texte | Adresse de Home Assistant utilisée par l'assistant et le serveur du PC. `HA_URL` de `poc/.env`, quand elle est définie, passe devant. |
| `sante_url` | texte | Adresse du service de santé pour le relais (voir [la santé](#santé)). `SANTE_URL` de `poc/.env` passe devant. |
| `sante_donnees_url` | texte | Adresse du fichier `data-auto.js` du tableau de bord de santé, pour l'historique. Aucune variable ne la remplace. |
| `ssh_ha` | texte | Alias SSH de la machine Home Assistant. Sert à `ha-app/deployer.sh`, à `ha-app/configurer-options.py`, et au serveur du PC pour joindre les applis Wyoming de Home Assistant (`ssh <alias> nc <hôte> <port>`). |
| `android_serveur_pc` | texte | Adresse wss par défaut du serveur du PC, compilée dans l'APK (`BuildConfig.SERVEUR_PC_DEFAUT`) et modifiable dans les réglages de l'appli. |
| `android_serveur_ha` | texte | Adresse wss par défaut de l'appli Home Assistant, compilée de la même façon (`SERVEUR_HA_DEFAUT`). |

```json
"reseau": {
  "ha_url": "http://homeassistant.local:8123",
  "ssh_ha": "ha",
  "android_serveur_pc": "wss://192.168.0.10:8766",
  "android_serveur_ha": "wss://192.168.0.20:8766"
}
```

Un champ absent vaut une chaîne vide. Sans `ha_url` ni `HA_URL`, Home Assistant n'est pas joignable. Sans
`ssh_ha`, `deployer.sh` s'arrête sur une erreur Python.

### `fuseau`

Texte, nom de fuseau IANA (`"Europe/Paris"`). Il donne l'heure de la maison pour les heures calmes de la
sécurité (quand elles sont actives, voir la [section 6](#6-la-sécurité-et-ce-que-la-configuration-en-règle))
et la date et l'heure glissées dans la demande au LLM du PC. Absent : `UTC`. La santé et son historique
comptent les jours à l'heure de `Europe/Paris`, écrite dans le code, quel que soit ce champ.

### `securite`

Listes appliquées par la sécurité écrite en dur (`poc/securite.py` et sa copie `Securite.kt`). Dans cette
version, la plupart sont lues mais restent sans effet, parce que les règles qui s'en servent sont coupées
dans le code. Seul `plafond_volume` agit, dès qu'il est inférieur à 100. Le détail est à la
[section 6](#6-la-sécurité-et-ce-que-la-configuration-en-règle).

| Champ | Type | Effet quand la règle correspondante est active |
|---|---|---|
| `nom_occupant` | texte | Nom de l'occupant protégé, cité dans les refus. Par défaut : `l'occupant`. |
| `mots_proteges` | liste de textes | Tout identifiant d'entité, de zone ou de service qui contient l'un de ces mots (sans tenir compte de la casse) est intouchable. Une phrase qui en contient un est refusée avant le LLM. |
| `mots_pieces` | liste de textes | Mots d'un nom de pièce Home Assistant qui rendent la pièce protégée : ses appareils sont cachés au LLM et la pièce porte un cadenas dans la maison en grand. Vide : les `mots_proteges` servent. |
| `zones_protegees` | liste de textes | Identifiants de zones Home Assistant (`area_id`) refusées. |
| `entites_protegees` | liste de textes | Entités protégées dont l'identifiant ne contient aucun mot protégé (automatisation de réveil, script qui éteint tout). |
| `son_salon` | liste de textes | Lecteurs et scripts qui font du son dans la pièce de vie : pendant les heures calmes, seuls éteindre, mettre en pause, arrêter, baisser et couper le son passent. Comparaison exacte, casse comprise. |
| `heures_calmes` | objet `{debut, fin}`, heures entières | Plage des heures calmes, `debut` compris, `fin` exclue, à l'heure de `fuseau`. Par défaut : 0 et 9. |
| `permis_personne` | objet, clé = prénom en minuscules sans accent | Pour chaque personne reconnue par la tablette : `entites` et `services` qu'elle peut piloter parmi ses affaires protégées. |
| `plafond_volume` | nombre de 0 à 100 | Toujours actif : volume le plus fort permis, en pourcentage. Absent ou 100 : aucun plafond. Voir [le plafond de volume](#le-plafond-de-volume). |

```json
"securite": {
  "nom_occupant": "Camille",
  "mots_proteges": ["camille", "cam"],
  "zones_protegees": ["chambre_camille"],
  "heures_calmes": {"debut": 0, "fin": 9},
  "plafond_volume": 100,
  "permis_personne": {
    "camille": {"entites": ["light.chambre_camille"], "services": ["light.turn_on", "light.turn_off"]}
  }
}
```

Section absente : toutes les listes sont vides, rien n'est protégé même si les règles sont remises.

### `appareils`

Appareils propres à la maison, vus par le serveur et par l'appli.

| Champ | Type | Effet |
|---|---|---|
| `tele` | entité | La télé. Rappelée au LLM du PC quand il répond sans appeler d'outil. |
| `tele_famille` | préfixe d'entité | Les entités qui commencent par ce préfixe gagnent un point dans la présélection des appareils proposés au LLM quand la demande ne parle pas de lumière. |
| `musique` | objet | Musique par Music Assistant et Spotify, détaillé plus bas. |
| `sortie_son` | liste de `{entite, nom}` | Enceintes de l'écran Musique de l'appli, dans l'ordre, avec leur nom court. Seuls ces lecteurs et les télés apparaissent dans la liste des appareils de l'appli. |
| `noms_courts` | objet entité vers nom | Noms affichés dans le panneau de la maison en grand. Sans nom court : le nom de la vue 3D, puis celui de Home Assistant. |
| `lumieres_banc` | liste de deux entités | Lumière du salon puis lampe de la télé, pour les outils de banc `poc/outils/banc_actions.py` et `poc/outils/test_voix.py`. |
| `ordre_pieces` | liste de textes | Ordre des filtres par pièce de l'écran des appareils de l'appli. Ce sont les noms des pièces dans Home Assistant, comparés en minuscules. Une pièce absente de la liste passe à la fin. |

Champs de `musique` :

| Champ | Type | Effet |
|---|---|---|
| `enceintes` | objet nom vers lecteur | Lecteurs Music Assistant par nom d'enceinte. Ces noms forment la liste de choix de l'outil `jouer_musique` du LLM. La clé `toutes` (le groupe) est obligatoire : sans elle, toute demande de morceau précis répond "aucune enceinte de musique configurée". |
| `natifs` | objet lecteur vers liste d'entités | Entités de l'intégration native des enceintes derrière chaque lecteur. Elles seules servent à confirmer que le son sort vraiment. |
| `spotify` | entité | Lecteur Spotify de Home Assistant. |
| `spotify_appareil` | texte | Nom de l'appareil Spotify Connect qui représente le groupe `toutes`. |
| `source_connect` | texte | Source que prend le groupe pendant une session Spotify Connect. |
| `scripts` | liste d'entités | Scripts qui lancent la musique : après leur appel, le serveur attend jusqu'à 12 s que le groupe `toutes` joue, et le note dans le journal de la musique. |
| `script_lancer` | entité | Script proposé au LLM pour "mets de la musique" sans précision. |

Un titre Spotify demandé sur le groupe `toutes` part par Spotify Connect quand `spotify` existe et que
`spotify_appareil` figure dans ses sources. Sinon, il part par Music Assistant.

```json
"appareils": {
  "tele": "media_player.exemple20",
  "musique": {
    "enceintes": {"toutes": "media_player.exemple22", "salon": "media_player.salon"},
    "script_lancer": "script.lancer_musique"
  },
  "sortie_son": [{"entite": "media_player.salon", "nom": "Salon"}],
  "ordre_pieces": ["séjour", "entrée", "couloir"]
}
```

Section absente : pas de télé désignée, musique refusée avec un message, écran Musique vide, ordre des
pièces alphabétique selon Home Assistant.

### `llm`

Ce qui personnalise les consignes des deux LLM : celui du PC (Claude ou un modèle local) et celui de
l'appareil (mode "Cet appareil").

| Champ | Type | Lu par | Effet |
|---|---|---|---|
| `lieu` | texte | PC | Complète "Tu es l'assistant vocal de ...". Par défaut : `la maison`. |
| `consignes` | liste de textes | PC | Lignes ajoutées telles quelles à la consigne. |
| `utilisateur` | texte | Appareil | Personne nommée dans la consigne. Par défaut : `l'utilisateur`. |
| `consignes_appareil` | liste de textes | Appareil | Règles ajoutées à la consigne, une ligne chacune, écrites `- ...`. |
| `exemples_appareil` | liste de paires `[phrase, réponse JSON]` | Appareil | Exemples donnés au modèle. La réponse est un texte JSON `{"actions": [...], "reponse": "..."}`. |

```json
"llm": {
  "lieu": "l'appartement de Sacha",
  "consignes": ["La télé du séjour est media_player.exemple20."],
  "exemples_appareil": [
    ["allume la cuisine à moitié",
     "{\"actions\": [{\"service\": \"light.turn_on\", \"entity_id\": \"light.cuisine\", \"donnees\": {\"brightness_pct\": 50}}], \"reponse\": \"La cuisine est allumée à moitié.\"}"]
  ]
}
```

Les accolades des textes du PC sont protégées avant d'entrer dans la consigne. La vue des appareils
donnée au LLM (noms, appareils masqués) se règle dans `commandes.yaml`, pas ici.

### `ha`

Lu seulement par `python ha-app/configurer-ha.py`, qui pousse le dictionnaire dans Home Assistant.

| Champ | Type | Effet |
|---|---|---|
| `alias` | objet entité vers liste de textes | Alias ajoutés à ceux que l'entité a déjà dans Home Assistant (jamais retirés). |
| `exposer` | liste d'entités | Entités exposées à Assist. |

```json
"ha": {
  "alias": {"vacuum.robot": ["aspirateur"]},
  "exposer": ["media_player.salon"]
}
```

Le même script crée l'automatisation "<nom de l'assistant> : dictionnaire" (id `jarvis_dictionnaire`) avec un
déclencheur vocal par commande de `commandes.yaml` et par phrase apprise. Les commandes à deux emplacements
ne sont pas transférées, celles que la sécurité refuse à 14 h non plus (aujourd'hui : celles qui visent un
`device_id`, et celles qui utilisent `media_player.volume_up` quand `securite.plafond_volume` règle un
plafond). `--essai` écrit seulement l'aperçu dans `genere/ha/`.

### `assistant`

Le nom de l'assistant, tel qu'il s'affiche : nom de l'appli Android sur l'écran d'accueil et dans ses
messages, nom de l'appli Home Assistant et de son automatisation de dictionnaire, première ligne du
journal de l'appli HA.

| Champ | Type | Effet |
|---|---|---|
| `nom` | texte | Nom affiché. Par défaut : `Assistant`. |

```json
"assistant": {"nom": "Iris"}
```

Le nom affiché ne change pas le mot qui réveille l'assistant, réglé à part dans la section `reveil`. Les
deux peuvent différer. Après un changement : nouvel APK pour l'appli Android, nouveau déploiement
(`ha-app/deployer.sh`) pour l'appli HA, et `ha-app/configurer-ha.py` pour renommer l'automatisation.

### `proprietaire`

La personne à qui appartient l'installation.

| Champ | Type | Effet |
|---|---|---|
| `nom` | texte | Prénom affiché. Nom de l'APK par défaut, prénom proposé au LLM pour "la chambre de ...", seul prénom pour lequel la santé s'affiche (comparé au nom du profil de visage, sans tenir compte de la casse). Par défaut : `Moi`. |
| `cle` | texte | Clé du propriétaire : le jeton `SATELLITE_JETON` lui est attribué, `SANTE_PERSONNES` vaut cette clé par défaut, et `personnes.defaut` de `commandes.yaml` aussi. Par défaut : `nom` en minuscules. À écrire sans accent. |
| `variantes` | liste de textes | Transcriptions erronées du prénom, remplacées par `nom` avant la recherche dans le dictionnaire (mots entiers, casse ignorée). |

```json
"proprietaire": {"nom": "Sacha", "cle": "sacha", "variantes": ["sasha", "sachat"]}
```

Section absente : propriétaire `Moi`, avertissement au démarrage du serveur et à la compilation, et la
santé ne s'affiche pour personne.

### `mer`

Météo marine d'un plan d'eau : page Mer du panneau Météo de la tablette et questions sur la mer. Le module
n'existe que si `"actif": true` (un vrai booléen JSON). Le détail de l'activation est dans
[la section 5](#météo-marine-et-vent-mesuré).

| Champ | Type | Effet |
|---|---|---|
| `actif` | booléen | Allume le module. Absent ou faux : module éteint. |
| `fuseau` | texte | Fuseau des heures affichées et demandées aux sources. Par défaut : `UTC`. |
| `points` | liste d'objets | Points de prévision, tous en mer, dans l'ordre du message. Sans point, le module reste éteint. |
| `modele_principal` | `{modele, nom}` | Modèle Open-Meteo du vent, de l'air, de la pluie, de l'orage et du soleil. `nom` est affiché (par défaut : `prévision`). |
| `modele_second` | `{modele, nom}` | Second modèle Open-Meteo pour le vent et la visibilité (par défaut : `second modèle`). |
| `vagues_regional` | `{url, lieux}` | Vagues WaveWatch III de la source régionale. `url` contient `{lieu}`. Chaque lieu : `point` servi, `lieu` (code de la source), `nom`, `panne` (libellé affiché en cas d'échec). Facultatif : sans lieu, les vagues viennent d'Open-Meteo Marine. |
| `station` | `{url, nom, point}` | Station à terre : vent mesuré affiché dans le bloc du moment du `point` indiqué. |
| `alias` | liste de paires `[mot, point]` | Mots qui désignent un point dans une question, cherchés dans l'ordre. |
| `mots_lieu` | liste de textes | Autres noms du plan d'eau acceptés après "à" dans une question. |
| `titre` | texte | Titre par défaut de la page (par défaut : `Mer`). |
| `libelle_terre` | texte | Libellé de la page météo à terre vu depuis la mer (par défaut : `Météo`). |
| `attribution` | texte | Crédit des sources en pied de page. |
| `nom` | texte | Présent dans l'exemple, lu par aucun code. |

Champs d'un point :

| Champ | Type | Effet |
|---|---|---|
| `id` | texte | Identifiant du point. |
| `nom` | texte | Nom affiché. |
| `lat`, `lon` | texte | Coordonnées, recopiées telles quelles dans les adresses d'Open-Meteo. |
| `titre` | texte | Titre de la page pour ce point. |
| `stations` | liste d'identifiants | Stations du vent mesuré rattachées au point, la plus représentative d'abord. |
| `defaut` | booléen | Point par défaut. Sinon, le premier. |
| `soleil` | booléen | Point qui donne le lever et le coucher du soleil. Sinon, le premier. |
| `eau` | booléen | Point qui donne la température de l'eau. Sinon, aucune. |
| `sans_station` | booléen | Point sans station à lui : la réponse ne dit pas que sa balise n'émet pas. |

```json
"mer": {
  "actif": true,
  "fuseau": "Europe/Paris",
  "points": [
    {"id": "Exemple4", "nom": "Exemple4", "lat": "11.111", "lon": "11.111", "soleil": true,
     "titre": "Mer à Exemple4", "stations": ["Exemple4", "Exemple24"], "defaut": true}
  ],
  "modele_principal": {"modele": "Exemple46", "nom": "Exemple5"},
  "modele_second": {"modele": "Exemple47", "nom": "HARMONIE"},
  "titre": "Mer à Marseille"
}
```

Les sources interrogées sont fixées par le code : les deux modèles d'Open-Meteo, Open-Meteo Marine, les
lieux VaguesRegional et la station. Une source dont l'adresse manque ou ne répond pas reste en panne, son
libellé s'affiche dans les erreurs et les autres continuent. Le module ne renvoie une erreur que si le
modèle principal n'a jamais pu être lu.

### `vent`

Vent réellement mesuré autour du plan d'eau : page Vent mesuré du panneau Météo. Le module suppose la
section `mer` active, ses `points` servant de rattachement.

| Champ | Type | Effet |
|---|---|---|
| `actif` | booléen | Allume le module. Absent ou faux : éteint. |
| `cadre` | `[lat_min, lat_max, lon_min, lon_max]` | Emprise de la carte. Les stations hors cadre ne sont pas dessinées. L'appli exige quatre nombres. |
| `balises` | objet | Balises Balises : `doc_type`, `fenetre`, `latitude`, `longitude` de la requête, `user_agent` (en ASCII seulement), `panne` (libellé d'échec), `balises` (objet id Balises vers fiche). |
| `stations_officielles` | objet | Stations StationsOfficielles : `url` (contient `{q}`), `nommees` (stations reconnues par `nom_brut`, avec leur fiche), `reseau_amateur` (code du réseau des stations amateurs), `quartiers` (code de station amateur vers nom affiché). |
| `station` | fiche avec `url` | Station à terre. |
| `points_proches` | objet point vers `[lat, lon]` | Rattache une station sans `point` au point de prévision le plus proche. |
| `titre` | texte | Titre de la page (par défaut : `Vent mesuré`). |
| `preferees` | liste d'identifiants | Stations essayées d'abord comme station par défaut. |
| `note_regate` | texte | Phrase affichée sous la liste quand rien d'autre n'y est écrit. |
| `carte` | objet | Dessin de la carte, voir plus bas. |

Une fiche de station ou de balise contient `id`, `nom`, `genre` (texte affiché), `type` (`mer`, `abritee`,
`terre` ou `amateur`), `lat`, `lon` et `point` (point de rattachement, ou `null` pour une donnée hors carte).

Champs de `carte` :

| Champ | Type | Effet |
|---|---|---|
| `largeur`, `hauteur` | nombres | Taille de la carte en pixels de maquette (par défaut 640 et 423). |
| `cote`, `terre` | chemins relatifs à `genere/android/` | Trait de côte et terre, en chemin SVG. Obligatoires pour fabriquer une APK quand `vent` est actif. |
| `lieux` | liste de `{nom, lat, lon}` | Noms de lieux écrits sur la carte. |
| `decalages` | objet id vers `[dx, dy]` | Position de l'étiquette de chaque station par rapport à son point. Par défaut : `[0, 90]`. |
| `attribution` | texte | Crédit des sources en pied de page. |

```json
"vent": {
  "actif": true,
  "cadre": [11.111, 11.111, 11.1, 5.33],
  "station": {"url": "https://exemple.invalid/station", "id": "cds", "nom": "Station à terre",
              "genre": "station à terre", "type": "terre", "lat": 11.1111, "lon": 11.1111, "point": "Exemple4"},
  "points_proches": {"Exemple4": [11.111, 11.11]},
  "carte": {"largeur": 640, "hauteur": 423, "cote": "carte/golfe_cote.txt", "terre": "carte/golfe_terre.txt"}
}
```

Le serveur interroge toujours ses trois sources (Balises, StationsOfficielles et la station). Une source en échec
est réessayée après 1, 2, 4, 8 puis 15 minutes au plus, et son libellé apparaît dans les erreurs.

### `reveil`

Mot de réveil propre à la maison, en plus de "Hey Jarvis".

| Champ | Type | Effet |
|---|---|---|
| `mot` | texte | Nom du modèle : `reveil/<mot>.onnx` dans le dossier de configuration. Interdit : `melspectrogram`, `embedding_model`, `hey_jarvis`, `hey_jarvis_v0.1` (la compilation échoue). |
| `nom` | texte | Nom affiché. Par défaut : `mot` avec une majuscule. |
| `langue` | texte | Affichée sous le nom dans les réglages de l'appli. |
| `licence` | texte | Affichée dans les réglages de l'appli. |

```json
"reveil": {"mot": "jeeves", "nom": "Jeeves", "langue": "français", "licence": "Licence du modèle, en une phrase."}
```

Cette section n'a pas de champ `actif` : `"actif": false` n'y change rien. Pour l'éteindre, la retirer ou
vider `mot`. Détails dans [la section 5](#mot-de-réveil).

## 3. Le dictionnaire commandes.yaml

Le dictionnaire est consulté avant Home Assistant et avant le LLM. Une phrase trouvée donne l'action exacte
en quelques dizaines de millisecondes.

### Format

Quatre sections, toutes facultatives sauf `commandes`.

```yaml
llm:            # ce que voit le LLM, sans rien changer dans Home Assistant
  renommer:
    light.exemple7: "Lampe TV (lampe posée près de la télé, ce n'est pas la télé)"
  notes:        # ajoutées en bout de ligne de l'appareil (LLM du PC seulement)
    media_player.exemple20: "entrées via media_player.select_source"
  masquer:
    - media_player.tv

personnes:      # "ma chambre" selon qui parle, voir plus bas
  defaut: sacha

emplacements:   # listes de valeurs, utilisées par {nom} dans les phrases
  hdmi:
    "1|un": HDMI1
    "2|deux": HDMI2

commandes:
  - phrases: ["(éteins|coupe|ferme) [la] (télé|télévision|tv) [du séjour|du salon]"]
    action: {service: media_player.turn_off, entity_id: media_player.exemple20}
    reponse: "J'éteins la télé."
  - phrases: ["(mets|passe) [la télé] sur [l'entrée] hdmi {hdmi}"]
    action: {service: media_player.select_source, entity_id: media_player.exemple20, source: "{hdmi}"}
    reponse: "Je passe la télé sur l'entrée demandée."
```

Syntaxe d'une phrase, celle des phrases personnalisées de Home Assistant :

| Écriture | Sens |
|---|---|
| `(a\|b)` | l'un ou l'autre |
| `[mot]` | facultatif, `[a\|b]` pour un choix facultatif |
| `{nom}` | une valeur de `emplacements.nom` |

Les motifs des emplacements suivent la même syntaxe. Avant la comparaison, tout est mis en minuscules,
sans accents ni ponctuation. Une petite faute de transcription est tolérée (ressemblance de 0,88 au moins,
et chaque mot différent doit rester proche d'un mot de l'autre côté). Les formules de politesse ("est-ce que
tu peux", "s'il te plaît"), l'infinitif ("éteindre" devient "éteins") et les `variantes` du prénom du
propriétaire sont corrigés d'abord.

Une action est un objet, ou une liste d'objets pour plusieurs actions :

| Clé | Effet |
|---|---|
| `service` | Service Home Assistant exact, `domaine.service`. |
| `entity_id` | Une entité, une liste, ou plusieurs entités séparées par des virgules. |
| autres clés | Envoyées telles quelles comme données du service (`brightness_pct`, `source`, `transition`...). |

`{nom}` est remplacé dans toutes les valeurs texte de l'action, y compris l'identifiant
(`entity_id: "script.aspirer_{piece}"`). Les accolades d'une valeur texte sont donc réservées aux
emplacements. `reponse` est dite après coup (par défaut : "C'est fait.").

Les actions du dictionnaire ne passent pas par la liste blanche des services du LLM : elles sont écrites à
la main. Chacune passe par la sécurité en dur avant l'envoi.

Si deux commandes produisent la même phrase, la première du fichier gagne.

### Ajouter une commande

Ajouter un bloc sous `commandes:`, avec ses phrases, son action et sa réponse. Pour une famille de
commandes (une par pièce, une par source), passer par un emplacement plutôt que de répéter le bloc.

Pour l'essayer sans micro ni Home Assistant :

```powershell
.venv\Scripts\python poc/assistant.py --texte "ta phrase" --essai
```

Puis refaire l'export pour l'appli (`.venv\Scripts\python android/outils/exporter_dictionnaire.py`).

### Ajouter une pièce

Une pièce intervient à plusieurs endroits, selon ce qu'on veut en faire :

1. Dans un emplacement, par exemple `piece` de l'exemple, dont la valeur sert de suffixe aux scripts de
   l'aspirateur (`script.aspirer_{piece}`). Les scripts correspondants doivent exister dans Home Assistant :
   ```yaml
   piece:
     "[le] bureau": bureau
   ```
2. Dans l'emplacement `lumiere`, pour régler sa luminosité ("mets le bureau à 50 %").
3. Dans `appareils.ordre_pieces` de `maison.json`, sous son nom Home Assistant.
4. Dans le plan, `carte/pieces.json` (voir la [section 4](#4-le-plan-du-logement)).

### Ajouter un appareil

1. Des commandes pour lui dans `commandes:`.
2. Si le LLM doit le voir autrement : `llm.renommer`, `llm.notes`, ou `llm.masquer` pour un doublon.
3. Pour Assist : `ha.alias` de `maison.json`, puis `python ha-app/configurer-ha.py`.
4. Pour l'appli : `appareils.noms_courts`, et `appareils.sortie_son` pour une enceinte.
5. Pour la vue 3D : une lampe dans `carte/lampes.json`, ou une télé ou une enceinte dans `medias` de
   `carte/meubles.json`.

### Ajouter une personne et "ma chambre"

La section `personnes` dit ce que vise "ma chambre" selon la personne que la tablette reconnaît.

```yaml
personnes:
  defaut: sacha
  inconnu: "Je ne te reconnais pas, donc je ne sais pas de quelle chambre tu parles."
  sans_chambre: "Je ne sais pas quelle chambre est la tienne."
  camille:
    remplacer:
      light.exemple14: light.chambre_camille
      light.exemple11: light.exemple18
      script.lampes_nuit_eteindre:
        {service: light.turn_off, entity_id: light.exemple18, transition: 5,
         reponse: "J'éteins ton chevet. Bonne nuit."}
```

| Clé | Effet |
|---|---|
| `defaut` | Personne dont la chambre est celle du dictionnaire. Par défaut : `proprietaire.cle`. |
| `inconnu` | Réponse quand la tablette voit une seule personne sans la reconnaître. |
| `sans_chambre` | Réponse quand la personne reconnue n'a pas de chambre déclarée. Par défaut : le texte de `inconnu`. |
| `<personne>.remplacer` | Pour cette personne : entité de la chambre par défaut vers son entité à elle (texte), ou vers une action complète (objet, avec une `reponse` facultative qui remplace celle de la commande). |

La règle, identique dans `poc/dictionnaire.py` et `DictionnaireLocal.kt` :

- Une commande est "personnelle" quand toutes ses cibles sont des clés d'une table `remplacer` et que la
  phrase, une fois normalisée, ne contient pas la valeur de `defaut` comme mot ("la chambre de Sacha"
  garde toujours ses cibles).
- Quand on ne sait pas qui parle (pas de vision, plusieurs personnes, identité pas encore sûre), ou que
  c'est `defaut` qui parle, la commande reste telle quelle.
- Une personne vue mais inconnue reçoit la réponse `inconnu`, rien n'est fait.
- Une personne reconnue avec une table voit ses entités à elle. Une action complète ne remplace qu'une
  action à une seule cible. Une cible sans correspondance donne la réponse `sans_chambre`.
- Une personne reconnue sans table reçoit `sans_chambre`.

Pour ajouter une personne :

1. Lui donner une table `remplacer` ici. La clé est son prénom, comparé sans accent ni majuscule au nom
   de son profil de visage.
2. Enregistrer son visage sur la tablette ("Visages enregistrés" dans les réglages), sous ce prénom.
3. Si elle a son téléphone : `SATELLITE_JETON_<NOM>` dans `poc/.env`, puis
   `gradlew assembleDebug -Putilisateur=<nom>` pour son APK.
4. Si ses affaires sont protégées, `securite.permis_personne` de `maison.json` (voir la
   [section 6](#6-la-sécurité-et-ce-que-la-configuration-en-règle)).

Les cas communs aux deux langages sont dans `poc/tests/cas_personnes.json`.

### Les phrases apprises

Une phrase traitée avec succès par le LLM est rangée dans `commandes_apprises.yaml`, puis reconnue
directement la fois suivante. Ce fichier n'est pas de la configuration : il vit dans le dossier de données
de la machine (`JARVIS_DONNEES`, `poc/` par défaut sur le PC, `/data` dans l'appli Home Assistant).

```yaml
apprises:
- phrase: allume la lampe du bureau en bleu
  action:
  - service: light.turn_on
    entity_id: light.bureau
    color_name: blue
  reponse: La lampe du bureau est bleue.
  appris_le: 2026-10-20 18:42
```

Une phrase apprise ne vaut que mot pour mot (aucune tolérance aux fautes), et le dictionnaire écrit à la
main passe devant en cas de doublon. Ne sont jamais apprises : les phrases d'un seul mot, celles qui
dépendent du moment ("encore", "éteins-la"), les questions et les échecs, ni rien en mode essai. Pour en
retirer une : supprimer son bloc, ou dire "non" ou "annule" dans les 30 s qui suivent.

Les phrases apprises du PC partent aussi vers l'appli (par l'export ci-dessous) et vers Home Assistant (par
`configurer-ha.py`). `deployer.sh` copie celles du PC comme point de départ de l'appli Home Assistant,
qui garde ensuite les siennes dans `/data`.

### L'export à refaire avant de compiler l'APK

L'appli n'a pas de lecteur YAML : elle embarque `genere/android/dictionnaire.json`, avec toutes les formes
développées, la vue du LLM, la section `personnes` et la liste blanche des services. Après chaque
changement du dictionnaire ou des phrases apprises :

```powershell
.venv\Scripts\python android/outils/exporter_dictionnaire.py
```

Sans ce fichier, la compilation d'une APK échoue avec la commande à lancer.

Pour l'exemple, `.venv\Scripts\python android/outils/exporter_dictionnaire.py --exemple` exporte le dictionnaire de
`config-exemple/` sans phrase apprise ni date. Le test `test_export_exemple_a_jour` de
`poc/tests/test_dictionnaire.py` refait cet export et vérifie qu'il n'a pas changé. S'il échoue, l'export
vient d'être réécrit : il reste à le committer avec le `commandes.yaml` d'exemple modifié. Les tests de
l'appli (`DictionnaireTest.kt`) lisent ce même fichier.

## 4. Le plan du logement

Trois fichiers dans `carte/` de la configuration décrivent le logement. Ils servent au plan 2D de
référence et à la vue 3D de la tablette, qui montre les lampes allumées et permet de les toucher.

### Repère et unités

- Unité : le mètre. Repère direct, y vers le haut du plan.
- L'origine et les axes sont libres et décrits en texte dans `pieces.json` (`repere`). Le nord peut rester
  inconnu (`"nord": null`).
- Les hauteurs (`z`) partent du sol.
- Le générateur 3D ne traite correctement que les murs parallèles aux axes x et y. Une cloison en biais
  reste juste dans le plan 2D, pas dans la vue 3D.
- Dans la vue 3D, l'écran d'une télé fait face au sens +y du plan.

### `pieces.json`

| Champ | Contenu |
|---|---|
| `version`, `date` | Version et date du plan, écrites au pied du plan 2D et dans la vue 3D. |
| `logement`, `unite`, `source` | Texte descriptif (méthode du relevé, échelle, contrôles, précision), non interprété. |
| `repere` | `origine`, `axe_x`, `axe_y`, `sens` en texte, `emprise` `{xmin, ymin, xmax, ymax}` qui contient tout le plan, `nord`. |
| `pieces` | Liste des pièces, voir ci-dessous. |
| `portes` | Porte d'entrée : `{id, nom, segment: [[x1, y1], [x2, y2]]}`, dessinée en rouge sur le plan 2D. |
| `pied` | Facultatif, ajouté au pied du plan 2D. |
| `surface_totale_m2` | Recalculée par `generer_plan.py`. |

Une pièce :

| Champ | Contenu |
|---|---|
| `id` | Identifiant stable, sans accent (`chambre_sacha`). |
| `nom` | Nom affiché. |
| `nom_a_confirmer` | Facultatif : vrai ajoute "?" au nom sur le plan 2D. |
| `type` | `sejour`, `circulation`, `chambre` ou `salle_de_bain` (couleur du sol). |
| `confiance` | `haute`, `moyenne`, `basse` ou `estimee` (contour en pointillés). |
| `polygone` | Points `[x, y]` dans l'ordre du contour, sans répéter le premier. |
| `surface_m2` | Recalculée par `generer_plan.py`. |
| `remarque` | Texte libre. |

### `meubles.json`

| Champ | Contenu |
|---|---|
| `version` | Version de la vue 3D, affichée dans la page. |
| `hauteur_plafond` | Hauteur des murs, en mètres. |
| `meubles` | `{id, nom, piece, boite: [x0, y0, x1, y1, z0, z1], couleur}`, un pavé droit par meuble. |
| `ouvertures` | `{id, segment, porte}` : trou dans le mur sur ce segment (à moins de 20 cm du mur). `porte` vrai ajoute un linteau à 2,10 m. |
| `medias` | Télés et enceintes posées sur un meuble : `{entite, nom, type: "tele" ou "enceinte", meuble, alias, ondes}`. `alias` liste d'autres entités du même appareil. `ondes`, en degrés, limite les ondes d'une enceinte contre un mur à un demi-cercle tourné vers la pièce. |
| `groupes_medias` | Entité de groupe vers ses enceintes. |

### `lampes.json`

Une entrée par ampoule. C'est le lien entre la vue 3D et Home Assistant.

| Champ | Contenu |
|---|---|
| `entite` | Entité `light.` de Home Assistant, celle que la page allume et que l'appli pilote au toucher. |
| `nom` | Nom de l'ampoule. |
| `type` | `suspension`, `plafonnier`, `lampe`... |
| `piece` | `id` de la pièce de `pieces.json`. |
| `xyz` | Position en mètres, `z` = hauteur de l'ampoule. |
| `position` | `triangulee`, `deduite` ou `estimee` (une position estimée est signalée dans la page). |

`groupes` (obligatoire, même vide) relie une entité de groupe Home Assistant à ses ampoules :

```json
"groupes": {"light.cuisine": ["light.exemple15", "light.exemple16"]}
```

Un état reçu pour le groupe s'applique à toutes ses ampoules. Dans le panneau de la maison en grand, un
groupe dont toutes les ampoules sont dans la même pièce apparaît comme un seul objet.

### Faire le plan à la main

1. Choisir l'origine (un angle intérieur facile à retrouver) et les axes (le long d'un grand mur), et les
   décrire dans `repere`.
2. Mesurer chaque pièce et écrire son contour en mètres dans `pieces.json`. Des pièces voisines partagent
   les mêmes coordonnées de cloison.
3. Poser les meubles en pavés droits (10 à 20 cm près suffisent), les ouvertures et les télés ou enceintes.
4. Placer chaque ampoule avec l'entité Home Assistant exacte (Outils de développement, États), sa pièce et
   sa hauteur.
5. Régénérer (plus bas) et contrôler le plan 2D, qui affiche la surface de chaque pièce.

### Partir d'un relevé

- Plan coté (plan d'architecte, plan de vente) : reporter les cotes dans le repère choisi, en vérifiant
  que la somme des pièces retombe sur les cotes extérieures.
- Photogrammétrie ou balayage 3D (appli de relevé d'un téléphone, nuage de points) : ouvrir le modèle
  dans un visualiseur qui donne des coordonnées, aligner ses axes sur ceux du plan, puis relever les
  angles des pièces, les meubles et la position des ampoules.

Dans les deux cas, noter la méthode et la précision dans `source`, mettre `confiance` à `estimee` pour
une pièce vue seulement depuis la porte, et `position` à `estimee` pour une ampoule placée au jugé.

### Régénérer le plan 2D et la vue 3D

```powershell
.venv\Scripts\python carte/generer_plan.py
```

Recalcule les surfaces dans `pieces.json` (le fichier est réécrit), puis produit `carte/plan.svg` et
`carte/plan.png` (80 pixels par mètre, une balise `<polygon id="...">` par pièce). Demande Pillow. Ce plan
sert de référence, l'appli ne l'affiche pas.

```powershell
.venv\Scripts\python carte/3d/generer_3d.py
```

Produit `carte/modele.glb` (le logement en glTF, chaque ampoule nommée d'après son entité et portée par
`extras.haEntity`) et `genere/android/maison3d/vue3d.html` (page autonome embarquée dans l'APK). Il faut
ensuite recompiler l'APK. Pour l'exemple, régler d'abord la variable `ASSISTANT_VOCAL_CONFIG`, sous
PowerShell :

```powershell
$env:ASSISTANT_VOCAL_CONFIG = "config-exemple"
```

Sous Linux ou macOS, préfixer la commande par `ASSISTANT_VOCAL_CONFIG=config-exemple`. Les commandes de ce
document utilisent le Python de l'environnement virtuel, `.venv/bin/python` hors de Windows.

## 5. Les modules facultatifs

### Santé

Quelques chiffres de santé du propriétaire sur l'accueil de la tablette ("Tu as dormi ...", les pas du
jour) et un panneau Santé (onglets Tendances, Séances, Records et Jour pour l'historique).

Ce qu'il faut côté serveur :

- Le serveur du PC (profil `pc`). L'appli Home Assistant ne sert jamais la santé.
- Un service de santé joignable seulement par Tailscale, à l'adresse `reseau.sante_url` (ou `SANTE_URL`),
  qui répond à `GET /api/resume?jours=8` et `GET /api/commentaire?date=AAAA-MM-JJ` avec le jeton en
  `Authorization: Bearer`. Le relais refuse d'envoyer le jeton si le nom ne se résout pas dans les
  adresses de Tailscale et si la route ne part pas de l'interface Tailscale du PC.
- Pour l'historique, le fichier `data-auto.js` d'un tableau de bord de santé (`reseau.sante_donnees_url`),
  qui contient `window.HEALTHSTATS_AUTO = {...};`, lu sans jeton avec les mêmes contrôles.
- Dans `poc/.env` :

| Variable | Effet |
|---|---|
| `SANTE_JETON` | Jeton du service. Vide : relais et historique éteints. |
| `SANTE_URL` | Remplace `reseau.sante_url`. |
| `SANTE_PERSONNES` | Connexions permises, séparées par des virgules : clé d'un jeton fixe (`proprietaire.cle` pour `SATELLITE_JETON`, le nom en minuscules pour `SATELLITE_JETON_<NOM>`) ou `appareil:<id>` pour un téléphone appairé. Ligne absente : le propriétaire seul. Ligne présente mais vide : personne. |
| `SANTE_SEUIL_PAS` | Seuil d'une journée active (6000 par défaut). |
| `SANTE_SEUIL_NUIT_MIN` | Seuil d'une bonne nuit, en minutes (420 par défaut). |
| `SANTE_FC_MAX` | Fréquence cardiaque maximale de référence pour les zones (entre 100 et 250, sinon pas de bornes). |

Confidentialité :

- Servie seulement sur la liaison chiffrée (wss) et aux connexions permises.
- Rien sur disque ni dans les journaux du serveur, résumé gardé 10 minutes en mémoire.
- Sur la tablette, affichée seulement quand la vision reconnaît le propriétaire, seul et avec assurance,
  sur une image de moins d'une seconde. Le profil de visage doit porter le prénom `proprietaire.nom`. Une
  autre personne ou un inconnu à l'image la cache aussitôt. Jamais en veille, en AOD ni sur fond noir.

Pour l'éteindre : laisser `SANTE_JETON` vide, ou écrire `SANTE_PERSONNES=` sans valeur. Sans vision, rien
ne s'affiche non plus. L'accueil et le panneau perdent alors leurs lignes de santé.

### Météo marine et vent mesuré

La page Mer (prévisions de la journée sur les points en mer) et la page Vent mesuré (balises et stations,
sur une carte) s'ajoutent au panneau Météo de la tablette. Les sources sont publiques et sans clé, aucune
donnée personnelle ne part : les deux profils (PC et Home Assistant) les servent à toute connexion.

Pour les activer :

1. Section `mer` avec `"actif": true` et au moins un point.
2. Section `vent` avec `"actif": true` et un `cadre` de quatre nombres.
3. Le trait de côte et la terre dans `genere/android/`, aux chemins de `vent.carte.cote` et
   `vent.carte.terre`. Ce sont deux fichiers texte contenant un chemin SVG (`M x,y L x,y ...`), en
   coordonnées de la carte : `x = (lon - lon_min) / (lon_max - lon_min) * largeur` et
   `y = (lat_max - lat) / (lat_max - lat_min) * hauteur`. Le moteur ne fournit pas d'outil pour les
   produire. Ceux de l'exemple viennent d'OpenStreetMap (`natural=coastline`, licence ODbL, à créditer
   dans `vent.carte.attribution`).
4. Recompiler l'APK, qui refuse de se fabriquer si `vent` est actif sans ces deux fichiers.

L'appli n'affiche les deux pages que si `mer` et `vent` sont actives ensemble. Le serveur, lui, sert la
météo marine avec `mer` seule, et le vent mesuré seulement avec les deux.

Pour les éteindre :

| Moyen | Effet |
|---|---|
| Section `mer` absente, ou `"actif": false` | Serveur : ni météo marine ni vent mesuré. Appli : pages Mer et Vent masquées, aperçu de la mer caché, aucune question classée "mer". |
| Section `vent` absente, ou `"actif": false` | Serveur : vent mesuré éteint, météo marine gardée. Appli : pages Mer et Vent masquées toutes les deux. |
| `METEO_MER=0` dans `poc/.env` (ou `non`, `false`, `off`) | Le serveur ne sert plus la météo marine. Le vent mesuré reste servi tant que `VENT_MESURE` n'est pas à 0 : mettre les deux à 0 pour tout éteindre. Les pages de l'appli restent si la configuration les active, mais elles ne reçoivent plus rien de ce serveur. |
| `VENT_MESURE=0` dans `poc/.env` | Le serveur ne sert plus le vent mesuré. |

L'appli demande ces données au serveur du PC s'il les annonce, sinon à l'appli Home Assistant.

### Mot de réveil

Sans rien faire, l'assistant répond à "Hey Jarvis" (modèle anglais d'openWakeWord). Pour un mot à soi :

1. Obtenir un modèle openWakeWord au format ONNX.
2. Le ranger dans `reveil/<mot>.onnx` du dossier de configuration, avec sa licence dans
   `reveil/<mot>.onnx.LICENSE` (sans elle, la compilation avertit).
3. Le décrire dans la section `reveil` de `maison.json`.
4. Sur le PC, `MOT_REVEIL=<mot>` dans `poc/.env`.
5. Recompiler l'APK, qui range le modèle dans ses assets.

À l'écran, les réglages de l'appli proposent le mot de la configuration à côté de "Hey Jarvis", avec sa
langue et sa licence, et le prennent par défaut. Le PC n'annonce le nom de la section que si `reveil.mot`
vaut `MOT_REVEIL`. L'appli Home Assistant annonce toujours "Hey Jarvis", elle ne reçoit pas le dossier
`reveil/`.

Pour l'éteindre : retirer la section ou vider `mot`, et remettre `MOT_REVEIL=hey_jarvis`. Une section
`reveil` dont le modèle manque fait échouer la compilation de l'APK. Côté PC, un `MOT_REVEIL` sans modèle
retombe sur "Hey Jarvis".

### Vision des visages

La caméra avant de la tablette trouve les visages et reconnaît les profils enregistrés. Elle sert à savoir
qui parle (pour "ma chambre" et pour `permis_personne`) et à montrer la santé au seul propriétaire.

Aucun réglage dans `maison.json`. Elle s'active dans les réglages de l'appli, carte "Vision" :
"Désactivée" (par défaut), "Sur la tablette" ou "Sur le PC". Les profils se créent dans "Visages
enregistrés". Leurs empreintes restent sur la tablette, aucune image n'est gardée, ni sur la tablette ni
sur le PC. L'analyse sur le PC demande le profil `pc` et les modèles YuNet et SFace dans
`poc/modeles/vision/` (`python poc/outils/telecharger_modeles.py`). Si le PC ne répond pas, l'analyse
repasse sur la tablette.

Le nom d'un profil doit correspondre à `proprietaire.nom` pour la santé, et à la clé de la personne dans
`personnes` et `permis_personne` pour le reste. La caméra filme une pièce commune : l'appli rappelle de ne
l'activer qu'avec l'accord de tous les occupants.

Pour l'éteindre : "Désactivée". Plus aucune santé à l'écran, et "ma chambre" vise toujours la chambre de
`personnes.defaut`.

## 6. La sécurité et ce que la configuration en règle

La sécurité est écrite deux fois, dans `poc/securite.py` et dans `Securite.kt`, avec les mêmes règles. Les
cas communs sont dans `poc/tests/cas_securite.json`, vérifiés par `test_securite.py` et `SecuriteTest.kt`.

### Les règles et leurs drapeaux

| Règle | Drapeau dans le code | État dans cette version | Listes de la configuration |
|---|---|---|---|
| 1. Ne jamais toucher aux affaires de l'occupant protégé (entités, zones, `all`, pièces, phrases qui le nomment) | `PROTEGER_OCCUPANT` | Coupée (`False`) | `nom_occupant`, `mots_proteges`, `mots_pieces`, `zones_protegees`, `entites_protegees` |
| 2. Aucun son dans la pièce de vie pendant les heures calmes, sauf pour baisser ou couper | `HEURE_CALME_ACTIVE` | Coupée (`False`) | `son_salon`, `heures_calmes`, `fuseau` |
| 3. Exception à la règle 1 : l'occupant reconnu, seul devant la tablette, pilote ses lumières | dépend de la règle 1 | Sans effet tant que la règle 1 est coupée | `permis_personne` |

Ces drapeaux ne se règlent pas dans la configuration. Tant qu'ils restent à `False`, les listes ci-dessus
sont lues mais ne changent rien : le LLM voit aussi les appareils de l'occupant, aucune pièce ne porte de
cadenas, et le son passe à toute heure. Remettre une règle demande de repasser son drapeau à `True` dans
`poc/securite.py` et dans `Securite.kt`, puis d'adapter les cas de `cas_securite.json`.

Quand la règle 1 est active :

- Une action est refusée si son service ou l'une de ses entités contient un mot de `mots_proteges` ou
  figure dans `entites_protegees`, si elle vise `all`, ou si elle vise une zone de `zones_protegees`.
- Une phrase qui contient un mot protégé est refusée avant le LLM, sauf si la personne reconnue a une
  entrée dans `permis_personne` (ses actions restent vérifiées une à une).
- Les appareils protégés et ceux des pièces dont le nom contient un mot de `mots_pieces` sont cachés au LLM,
  sauf les `entites` de la personne reconnue.
- Une action permise par `permis_personne` n'est jamais apprise comme phrase.

Pour `permis_personne`, la clé est le prénom en minuscules sans accent. Le prénom reconnu est ramené à la
même forme avant la comparaison. Le droit tient seulement si le service est dans `services` et l'entité
dans `entites`.

Quand la règle 2 est active, entre `heures_calmes.debut` (compris) et `heures_calmes.fin` (exclue), à
l'heure de `fuseau`, un service sur une entité de `son_salon`, ou un script de `son_salon` appelé comme
service, est refusé, sauf `media_player.turn_off`, `media_player.media_pause`, `media_player.media_stop`,
`media_player.volume_down`, `media_player.volume_mute` (pas pour rétablir le son) et `script.turn_off`.
Cette liste de services est écrite dans le code. Le message de refus parle de "minuit et 9 h" quelles que
soient les heures configurées.

### Le plafond de volume

`securite.plafond_volume` fixe le volume le plus fort que l'assistant envoie, en pourcentage du volume de
l'enceinte. Il est lu au démarrage du serveur et compilé dans l'appli. Après un changement, relancer le
serveur, régénérer le dictionnaire (`python android/outils/exporter_dictionnaire.py`, qui recalcule les services
permis au LLM de l'appli, `volume_up` compris) puis reconstruire l'APK.

| Valeur | Effet |
|---|---|
| absente, `null` ou `100` | Aucun plafond (défaut). `media_player.volume_up` est permis, au LLM du serveur compris. |
| de `0` à moins de `100` | Un `volume_level` de `media_player.volume_set` est ramené entre 0 et cette valeur divisée par 100, quelle que soit la voie (voix, LLM, écrans, passerelle). `media_player.volume_up` est refusé quand il n'a pas pu devenir un volume précis (monter par pas passerait au-dessus). Les pistes de volume de l'appli s'arrêtent au plafond, marqué par un trait. |
| au-dessus de `100`, en dessous de `0` | Ramenée à 100 ou à 0. |
| autre chose (texte, `true`) | Plafond prudent de 50 %, pour qu'une faute de frappe ne lève pas un plafond voulu. |

Un niveau illisible dans une commande (`NaN`, texte) donne toujours 0.

### Ce qui ne se règle pas

Ces protections sont actives dans cette version et aucune configuration ne les change :

| Protection | Où |
|---|---|
| Un appareil visé par son identifiant brut (`device_id`) est refusé. | `securite.py`, `Securite.kt` |
| Le LLM ne peut appeler que les services d'une liste blanche (lumières, interrupteurs, ventilateurs, volets, climat, lecteurs, Music Assistant, aspirateur, scènes, scripts, booléens, boutons), rien qui ouvre une porte ou désarme une alarme. | `SERVICES_PERMIS` de `poc/assistant.py`, exportée dans `dictionnaire.json` pour l'appli |
| Assist de Home Assistant est sauté (il agit sans qu'on voie sa cible avant) : une phrase hors dictionnaire va directement au LLM. | `SECURITE_ACTIVE` de `securite.py` et `Securite.kt` |

Les actions du dictionnaire échappent à la liste blanche, mais pas à ces vérifications : chacune passe par
la sécurité avant d'être envoyée, avec la personne qui parle.
