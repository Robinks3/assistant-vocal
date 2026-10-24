# Principes de design de la tablette

Résumé des règles suivies pour l'écran ambiant de la tablette (appli Android, mode station). Les
maquettes et les revues détaillées restent dans le dépôt de configuration de chacun, parce qu'elles
montrent un logement réel.

## Écran toujours allumé

La tablette est un écran OLED allumé en permanence : c'est le cas le plus exposé au marquage.

1. Deux régimes. Vivant, quand quelqu'un est là (visage, toucher, voix) : couleurs pleines, page en bleu de
   nuit. En retrait, 30 s après : noir pur (#000000), couleurs à 40 %, commandes éteintes. Un pixel noir est
   éteint et ne s'use pas. Surfaces très sombres, bords fins.
2. Rien d'immobile : toute l'interface se décale lentement, d'un pixel par minute, dans un carré de
   quelques pixels.
3. Pas de texte clair permanent : la version et les états restent en gris sombre, visibles au toucher
   ou quelques secondes après une commande. L'heure en graisse fine, jamais en blanc pur.
4. Luminosité basse par défaut, plus basse encore sans personne, au minimum la nuit.
5. Veille profonde après quelques minutes sans présence ni commande. La nuit sans personne, écran
   éteint, micro toujours à l'écoute, et la présence ou le mot de réveil le rallument.
6. Barres d'Android cachées, couleurs saturées en petites surfaces seulement.

## Interaction

- Toucher l'orbe lance l'écoute. Le toucher de nouveau coupe l'écoute, ou la réponse en cours.
- La réponse s'écrit sous l'orbe, sans ouvrir de nouvelle page. Une action confirmée donne une seule
  carte, effacée d'elle-même.
- Le bouton Retour d'Android ferme un panneau ouvert, jamais l'écran ambiant.
- « Parler en regardant » est désactivé par défaut : sinon l'assistant transcrit les conversations de
  la pièce.

## Vie privée à l'écran

- La santé ne s'affiche que lorsque la caméra reconnaît son propriétaire seul devant l'écran, et
  disparaît dès qu'un autre visage apparaît.
- Les appareils d'un autre occupant ne sont ni comptés ni montrés, sauf quand c'est lui qui est reconnu.
- L'historique montre des noms lisibles, jamais les identifiants techniques de Home Assistant.

## Charte

- Écran sobre et typographique, plan 3D du logement au centre, orbe pour l'état de l'assistant.
- Polices Big Shoulders Display (heure) et Instrument Sans (texte), sous licence OFL.
- Version de l'appli visible dans la couche de service et dans `android/VERSION.md`, toujours
  synchronisées.
- Textes en français avec accents, sans tiret cadratin, sans point-virgule en phrase, sans emoji.
- Ne pas copier le design d'un autre projet, assistant des auteurs inspiration compris.
