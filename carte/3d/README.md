# Appartement en 3D

Vue 3D de l'appartement avec ses meubles et ses ampoules, pour voir sur l'écran de l'assistant ce qui s'allume et pour agir sur les lampes du doigt. Les données (`pieces.json`, `meubles.json`, `lampes.json`) sont dans le dossier `carte/` de la configuration de la maison (voir `../README.md`). La version de la page est celle de `meubles.json`, affichée en bas de la page, et le journal de ses versions vit avec la configuration.

## Fichiers

| Fichier | Rôle |
|---|---|
| `vue3d.html` | Généré dans `genere/android/maison3d/` de la configuration, rangé dans les assets de l'APK par `build.gradle.kts`. Page autonome, three.js 0.170.0 inclus : fonctionne hors ligne, depuis `file:///android_asset/` comme depuis un serveur. Environ 700 Ko. |
| `modele.glb` | Généré dans `carte/` de la configuration : le même appartement en glTF binaire, pour Home Assistant (cartes 3DHome ou floor3d) ou n'importe quel visualiseur. |
| `generer_3d.py` | Régénère les deux à partir des trois fichiers de la configuration. |
| `vue3d_modele.html` | Modèle de la page (le générateur y injecte three.js et les données). |
| `vendor/` | three.js 0.170.0 (`three.module.min.js`) et sa licence MIT. La page n'embarque plus de police depuis la 0.4.1 (plus d'étiquettes). |

Pour déplacer une lampe ou un meuble : corriger `lampes.json` ou `meubles.json` de la configuration, puis `python carte/3d/generer_3d.py`, et recompiler l'APK.

## Paramètres d'adresse

- `?panneau=0` : cache le panneau de démonstration (à utiliser dans l'appli).
- `?demo=1` : lance la démonstration au chargement.
- `?jeu=couleur&intensite=0.4` : jeu de teintes et clarté au chargement (0.5.0), pour essayer dans un navigateur.
- `?zone=0.278,0.27,0.444,0.46` et `?rotation=600,25,75` : zone de `disposition` et balancement de l'accueil (0.5.2).
- `?medias=media_player.tele_salon:on,media_player.barre_son_salon:playing:0.5` : télé et enceintes posées d'emblée, volume facultatif (0.6.0).
- `?regime=0` ou `1` : régime de l'accueil au chargement (0.7.0).
- `?angle=75` : angle de la vue fixe en degrés (0.6.0, -31,5 par défaut).
- `?allumer=light.salon_plafond,light.cuisine_suspensions` : lampes allumées d'emblée, sans animation (0.5.0), pour les captures des maquettes.
- `?pr=1.25` : résolution de la toile en pixels réels par pixel CSS (1,25 sur l'accueil de la tablette, 1,5 sans le paramètre), jamais au-dessus de celle de l'écran.

## Interface JavaScript `window.maison3d`

| Appel | Effet |
|---|---|
| `maison3d.etat(entite, e)` | Change une lampe ou un groupe (`light.cuisine_suspensions`, `light.chambre_sacha_chevets`, `light.chambre_camille_plafonds` sont développés en ampoules). `e` accepte un état Home Assistant (`{state: "on", attributes: {brightness, rgb_color, color_temp_kelvin}}`), `{on: true, niveau: 0.5}`, `"on"`/`"off"` ou un booléen. Allumage : montée avec un petit éclat, halo, tache de lumière au sol et onde qui s'élargit. Extinction : fondu. |
| `maison3d.etats(x)` | Plusieurs à la fois : tableau d'états Home Assistant (la réponse de `/api/states` telle quelle, les autres entités sont ignorées) ou objet `{entite: e}`. |
| `maison3d.poser(x)` | Comme `etats`, sans animation (premier affichage). |
| `maison3d.action({entite: effet})` | Action de l'assistant, jouée en entier par la page. Effet : `"allumer"`, `"eteindre"` ou `"regler"`, seul ou `{effet, state, attributes}` avec l'état lu dans Home Assistant. La lampe repart de son état d'avant, la caméra vole vers elle, un flux de particules se resserre sur l'ampoule, puis elle bascule à 1,15 s (éclat, lumière au sol, ondes, ou onde qui se referme et braises). Un état reçu pendant l'action attend la bascule. |
| `maison3d.montrer(cibles)` | Vol de caméra vers une lampe, un groupe, une pièce (`chambre_sacha`) ou une liste de ces éléments. Une seule pièce concernée : elle est cadrée en entier. Plusieurs : vue de tout l'appartement. |
| `maison3d.fondu(bool, bord)` | Bords de la scène fondus dans le noir (aperçu de l'appli), aussi par `?fondu=1`. `bord` : largeur du fondu en part de la vue (0,23 par défaut). |
| `maison3d.ensemble(duree)` | Revient à la vue de tout l'appartement, en `duree` ms si elle est donnée (puis la rotation reprend). |
| `maison3d.rotation(periode, ips, cadre)` | Écran d'accueil (0.4.0) : la caméra dérive autour de l'appartement, un tour en `periode` secondes (0 l'arrête), `ips` images par seconde au plus quand rien d'autre ne bouge, `cadre` agrandit (au-dessus de 1) ou rapproche le cadrage. Depuis la 0.4.1, l'angle de la caméra vaut l'angle de base plus une dérive, si bien qu'une action vise la pièce depuis l'angle du moment. L'appartement tient sous tous les angles. Une action la suspend, `ensemble` la reprend. |
| `maison3d.attenuer(opacite, duree)` | Scène atténuée, par exemple à 0,28 pendant l'écoute. |
| `maison3d.teintes({fond, murDessus, murFace, sol, meubleSombre, meubleClair, support, ampoule, lumiere, poussiere, flux, braise})` | 0.4.1 : couleurs de la scène, envoyées par l'appli au chargement depuis sa palette (`Palette.plan3d`). Les clés absentes gardent leur valeur. Une seule matière mate (Lambert, tramée) pour les murs, les sols et les meubles. |
| `maison3d.palette({lumiere, poussiere, flux, pluie})` | 0.4.2 : teintes du jeu de couleurs choisi dans l'appli (Palette.plan3dPalette), envoyées après `teintes`. |
| `maison3d.teintes({jeu, intensite, ...})` | 0.5.0 : `jeu` vaut `"neutre"` (gris sombres, par défaut) ou `"couleur"` (fond noir, murs clairs, sol teinté par type de pièce, meubles à leur vraie couleur de `meubles.json`). Le jeu repart de ses valeurs, puis les autres clés reçues s'appliquent par-dessus. `intensite` de 0 à 1 règle la clarté de l'appartement (8 % à 100 % de ses teintes vues, depuis la 0.5.1), pour la nuit ou la palette Veillée : 1 le jour, 0,1 à 0,25 la nuit. Plus elle baisse, plus les lampes éclairent fort (jusqu'à 3,5 fois), pour que les pièces allumées ressortent. Clés facultatives : `sol_sejour`, `sol_circulation`, `sol_chambre`, `sol_salle_de_bain`, `meublesReels` (booléen), `forceLampes` (lumières ponctuelles, 120 en neutre, 6 en couleur), `forceTache` (lumière au sol, 0,42 et 0,1), `forceHalo` (halo additif, 0,95 et 0,3), `ambiante` (part de la lumière ambiante, 1 dans les deux jeux depuis la 0.5.2) et `plafondBlanc` (0.5.2, aucun canal de surface au-delà de cette valeur, 0,8 en couleur, teinte et saturation gardées). |
| `maison3d.rotation(periode, ips, cadre, amplitudeDeg, angleDeg)` | 0.5.2 : avec `amplitudeDeg`, balancement de plus ou moins cette amplitude autour de `angleDeg` au lieu du tour complet, aller et retour en `periode` secondes. Le cadrage tient sur l'enveloppe du balancement : dans une zone de 0,444 x 0,46, 1,34 fois plus grand qu'un tour complet à ±25° autour de 75°. 75° couche le grand côté de l'appartement dans une zone en paysage. |
| `maison3d.disposition({x, y, largeur, hauteur, duree_ms})` | 0.5.0 : zone de la fenêtre où l'appartement est cadré, en fractions de la fenêtre (0 à 1). La toile couvre toujours toute la fenêtre, la projection est décalée vers la zone. Transition douce en `duree_ms` (zone et caméra ensemble), immédiate sans durée. `montrer()` cadre la pièce dans cette zone. Par défaut, depuis la 0.6.2, la zone A de l'accueil `{x: 0.5, y: 0.275, largeur: 0.444, hauteur: 0.45}`. |
| `maison3d.cadence(repos, action)` | 0.4.1 : images par seconde au plus au repos (rotation et poussières, 12 sur l'accueil) et pendant une animation (30). |
| `maison3d.pause(bool)` | 0.4.1 : plus aucune image, `requestAnimationFrame` et minuteur coupés. La reprise repart sans bond. |
| `maison3d.poussieres(bool)` | 0.4.1 : poussières ambre de 1 à 2 px qui dérivent dans les pièces allumées (20 à 40 par pièce selon sa surface, opacité 0,3 à 0,5), absentes quand tout est éteint. Accueil seulement. |
| `maison3d.desaturer(bool)` | 0.4.1 : maison qui ne répond plus, les lumières passent en gris (l'état montré n'est plus sûr). |
| `maison3d.dansLePlan(x, y)` | 0.4.1 : vrai si le point (pixels CSS de la page) tombe sur l'appartement (sol, murs, meubles), faux dans le noir autour. L'appli s'en sert pour séparer le toucher du plan de celui du vide. |
| `maison3d.nomsAuSol(bool)` | Montre ou cache les noms des pièces écrits au sol. |
| `maison3d.vue("dessus" ou "iso")`, `maison3d.murs(h)`, `maison3d.jour(bool)`, `maison3d.panneau(bool)`, `maison3d.demo()` | Réglages d'affichage. |
| `maison3d.lampes()` | Liste des ampoules avec leur état affiché. |
| `maison3d.etat("media_player....", e)` | 0.6.0 : télé et enceintes, par les mêmes `etat` et `etats` que les lampes (la réponse de `/api/states` peut être passée telle quelle). Entités connues dans `meubles.json` de la configuration (`medias`, avec les alias Music Assistant, et `groupes_medias` : `media_player.enceintes_maison` vise les deux enceintes). État lu dans `state` (`on`, `off`, `playing`, `paused`, `idle`...), volume dans `attributes.volume_level` (0 à 1). Télé : tout état sauf off, standby, unavailable, unknown l'allume. Enceinte : ondes au sol si `playing`, lueur seule si `paused`, rien sinon. Teintes `ecran` et `musique` dans `teintes`. |
| `maison3d.regime(niveau, duree_ms)` | 0.7.0 : régime de l'accueil, 1 vivant (fond en dégradé, ombre et flaque de lumière sous l'appartement, grain, particules dans la moitié droite, appartement saturé), 0 en retrait (noir pur, appartement désaturé), transition en `duree_ms`. Le soir (intensité 0,2 et moins), fond presque noir et effets à 45 %. Aussi par postMessage `{type: "regime", niveau, duree_ms}`. |
| `maison3d.version()`, `maison3d.dateVersion()` | 0.7.1 : version de la page et date des données. Dans l'appli, le libellé de version de la page est masqué, l'appli l'affiche avec ces appels. |
| `maison3d.medias()` | 0.6.0 : télé et enceintes, avec l'état et le volume montrés. |

La même chose passe par `postMessage` si la page est dans une iframe : `{type: "etat", entite, state, attributes}`, `{type: "etats", etats}`, `{type: "montrer", cibles}`, et depuis la 0.4.1 `teintes`, `poussieres`, `desaturer`, `pause`, puis `palette` (0.4.2).

## Retour vers l'appli

La page cherche un objet `window.Maison3dAndroid` (`WebView.addJavascriptInterface(..., "Maison3dAndroid")`) :

- `pret(version)` : appelé une fois la scène prête. L'appli envoie alors les états courants par `maison3d.etats(...)`.
- `battement()` : toutes les 10 s (0.4.1). L'appli recrée la vue si la page se tait 30 s alors qu'elle devrait vivre.
- `contextePerdu()` : contexte WebGL perdu (0.4.1), l'appli recrée la vue.
- `basculer(entite, on)` : l'utilisateur a touché une lampe. La page ne change rien elle-même : la lampe palpite jusqu'à ce que l'appli renvoie le vrai état par `maison3d.etat` (3 s au plus). C'est donc l'appli qui applique la sécurité en dur (lumières de Camille, personne qui parle) avant d'appeler Home Assistant.

Sans pont Android et hors iframe (ouverture directe dans un navigateur), un toucher bascule la lampe localement, pour la démonstration.

## Retour d'état dans la vue (0.42.0)

L'appli transmet l'état de chaque lampe, de la télé et des enceintes (`Maison3dPont.etatReduit`). Seuls `state`, `brightness`, la couleur (`rgb_color`, ou `color_temp_kelvin` quand la lampe est en mode température, la page convertit les kelvins) et `volume_level` partent, jamais le reste des attributs. Une lampe `unavailable` ou `unknown` part sans attribut et s'affiche éteinte.

- **Halo teinté** : chaque lampe allumée a un halo à sa vraie couleur ou chaleur. Allumée sans couleur reçue, elle reprend la lumière chaude de la palette (jamais la dernière couleur reçue).
- **Couche neutralisante** : un disque sombre sous la tache au sol, d'autant plus marqué que la lumière s'écarte du sol chaud (`forceNeutre` dans les jeux de teintes). Sans lui, le sol orangé du salon teinterait un blanc froid.
- **Pièce choisie** : le voile assombrit le reste, halos et taches restent sur la pièce.
- **Maison entière** (`grand` actif, aucune pièce) : ni halo, ni tache, ni couche neutralisante. Les lumières ponctuelles restent.
- **Vue masquée** : `pause(true)` gèle `requestAnimationFrame`. Un état reçu pendant la pause est posé sans animation, pour que la vue soit juste au retour.
- **Correspondances** : quand Home Assistant appelle une entité autrement que la maquette, la clé `reglages.vue3d.correspondances` de `maison.json` fait le lien (voir `docs/CONFIGURER.md`). Aucune entité réelle n'entre dans `carte/3d/`.

## Repère

Données en mètres dans le repère de `pieces.json` (z la hauteur). Dans `modele.glb`, repère glTF : X = x, Y = hauteur, Z = -y. Chaque ampoule y est un nœud nommé d'après l'objet Home Assistant sans le préfixe (`salon_plafond` pour `light.salon_plafond`) avec `extras.haEntity`, la convention de [3DHome](https://github.com/lukevink/3DHome).

## Limites

- Meubles en pavés droits, à 10 ou 20 cm près.
- Positions d'ampoules : `"position"` vaut `triangulee`, `deduite` ou `estimee` dans `lampes.json` (une position estimée est signalée dans le panneau).
- Une lumière ponctuelle par ampoule (11) : prévu pour la tablette, à surveiller si on en ajoute beaucoup. Le rendu ne tourne que pendant une animation, un geste, ou la rotation et les poussières de l'écran d'accueil (12 images par seconde au plus, 30 pendant une animation). Les lumières ponctuelles ne sont jamais cachées (en cacher une recompile les shaders), seuls halos, taches et ondes à zéro le sont.
