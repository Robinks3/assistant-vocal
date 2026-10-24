# Plan de l'appartement

Générateur du plan 2D à l'échelle, pièce par pièce, pour l'écran de la tablette. Les données de l'appartement ne
sont pas ici : elles sont dans le dossier `carte/` de la configuration de la maison (`ASSISTANT_VOCAL_CONFIG`, sinon
`config/` à la racine du dépôt, voir `poc/maison.py`). La configuration d'exemple (`config-exemple/carte/`) en donne
un petit appartement fictif de quatre pièces.

## Fichiers

| Fichier | Où | Rôle |
|---|---|---|
| `generer_plan.py` | ici | Recalcule les surfaces et régénère `plan.svg` et `plan.png` à partir de `pieces.json` (Python 3 et Pillow). |
| `3d/` | ici | Générateur de la vue 3D, voir `3d/README.md`. |
| `pieces.json` | configuration, `carte/` | Source de vérité : pièces, polygones en mètres, surfaces, porte d'entrée, repère. |
| `meubles.json`, `lampes.json` | configuration, `carte/` | Meubles, ouvertures, télé et enceintes, ampoules de Home Assistant, pour la vue 3D. |
| `plan.svg`, `plan.png` | configuration, `carte/` | Plan généré, une balise `<polygon id="...">` par pièce (l'`id` est celui de `pieces.json`), 80 pixels par mètre plus 60 pixels de marge. |

Pour corriger une cloison : modifier les coordonnées dans `pieces.json`, puis lancer `python carte/generer_plan.py`.
Pour le plan d'exemple : `ASSISTANT_VOCAL_CONFIG=config-exemple python carte/generer_plan.py`.

## Repère

- Unité : le mètre, repère direct, y vers le haut du plan, comme sur `plan.png`.
- L'origine et les axes sont décrits dans `repere` de `pieces.json`. Le nord peut rester inconnu (`"nord": null`).

## Format de `pieces.json`

Chaque élément de `pieces` contient :

| Champ | Contenu |
|---|---|
| `id` | Identifiant stable, sans accent (`sejour_cuisine`, `chambre_sacha`...). |
| `nom` | Nom affiché. |
| `nom_a_confirmer` | Facultatif. Présent et vrai quand le nom reste à confirmer (le plan ajoute alors « ? »). |
| `type` | `sejour`, `circulation`, `chambre` ou `salle_de_bain`. |
| `confiance` | `haute`, `moyenne`, `basse` ou `estimee` (pièce vue seulement depuis la porte, à dessiner en pointillés). |
| `polygone` | Liste de points `[x, y]` en mètres, dans l'ordre du contour, sans répéter le premier point. |
| `surface_m2` | Surface intérieure du polygone, arrondie à 0,1 m². |
| `remarque` | Ce qu'il faut savoir sur le tracé. |

`portes` contient la porte d'entrée sous forme d'un segment `[[x1, y1], [x2, y2]]`. `surface_totale_m2` est la somme des pièces. `pied`, facultatif, complète le pied du plan (échelle, précision du relevé). `repere` décrit l'origine et les axes, `repere.emprise` le rectangle qui contient tout le plan.

## Afficher le plan dans l'appli Android

Le plus simple est de lire `pieces.json` et de dessiner les polygones sur un `Canvas`, ce qui permet ensuite de colorer une pièce selon l'état de Home Assistant (lumière allumée, présence). Pour passer des mètres aux pixels d'une vue de largeur `L` et de hauteur `H` :

```kotlin
val e = repere.emprise
val echelle = min(L / (e.xmax - e.xmin), H / (e.ymax - e.ymin))
fun versEcran(x: Double, y: Double) = PointF(
    ((x - e.xmin) * echelle).toFloat(),
    ((e.ymax - y) * echelle).toFloat()   // y inversé : l'écran compte vers le bas
)
```

Pour un affichage figé, `plan.svg` (ou `plan.png`) suffit, et l'`id` de chaque polygone du SVG permet de retrouver la pièce.
