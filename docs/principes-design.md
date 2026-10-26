# Principes de design

Résumé des règles suivies pour l'écran ambiant de la tablette (appli Android, mode station) et pour le
client web. Les maquettes qui montrent un logement réel et leurs revues détaillées restent dans le
dépôt de configuration de chacun. Les maquettes du client web, qui n'utilisent que des noms fictifs,
sont dans `docs/maquettes/client-web/`.

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

## Client web

Socle visuel du client web (PWA servie par le serveur Python). Les planches de référence sont dans
`docs/maquettes/client-web/` (ouvrir `index.html`) : Accueil, trois écrans d'appairage, Réglages,
révocation d'un appareil, Journal (jour, soir, feuille de détail), Demander, Vie privée, et `composants.html`
qui montre chaque jeton et chaque état. Le CSS commun
est répété tel quel dans chaque planche, la session de code le reprend dans un fichier unique.
Ces règles prolongent celles de l'appli Android sans les recopier : même famille de couleurs, même
typographie, même façon de donner du volume.

### Principes

- Du relief, de la matière : chaque surface est un panneau de verre (dégradé vertical, filet de
  lumière en haut, ombre portée en deux couches). Pas d'aplat anguleux.
- Sobre : aucun effet décoratif (pas de paillettes, de police script, de texte extrudé, de pastille
  brillante). Une seule couleur d'accent par écran, le bleu de l'assistant.
- Tout le relief s'obtient en CSS pur (dégradés, `box-shadow`, `inset`), sans image ni script, pour tenir
  la politique de sécurité stricte (pas de style ni de script en ligne dans le client final).
- Clair, sombre et soir sont trois thèmes d'un même jeu de jetons. Le thème suit
  `prefers-color-scheme`. L'attribut `data-ambiance="soir"` sur `html` bascule vers la palette
  Veillée (atténuée, brun de nuit) pour les écrans du soir.
- La version du client et du serveur reste visible sur Accueil, Appairage et Réglages, avec la date.

### Palette (variables CSS sur `:root`)

Clair dérive de Pastels, sombre et soir de Veillée (voir `Palette.kt`). Le contraste du texte
secondaire est d'au moins 4,5 pour 1, celui des bordures de contrôle d'au moins 3 pour 1.

| Jeton | Clair | Sombre | Soir (sombre) | Emploi |
|---|---|---|---|---|
| `--fond-haut` / `--fond-bas` | #F3EFE7 / #E8E2D6 | #171B22 / #0C0E11 | #1D1A16 / #0F0D0B | dégradé de page |
| `--surface-haut` / `--surface-bas` | #FFFFFF / #F6F2EA | #242931 / #1A1E24 | #2A2622 / #201D19 | panneaux en verre |
| `--champ` | #EFEAE0 | #13161B | #14120F | creux : champs, jauges |
| `--filet` | #D8D1C4 | #2E343D | #36322F | séparateurs, bords de panneau |
| `--bord-controle` | #857E72 | #6B7380 | #7A7268 | bord des champs et boutons |
| `--texte-1` / `-2` / `-3` | #23211D / #4A453D / #665F55 | #EEEAE2 / #BAB2A6 / #9A948A | #DCD2C5 / #A49A91 / #948D84 | titre, courant, discret |
| `--assistant` | #2A5CB8 | #8CB1F4 | #8096D1 | accent, focus, action principale |
| `--assistant-profond` | #1C418A | #4F78C4 | #4D63A0 | bas du dégradé du bouton |
| `--lumiere` | #8F5200 | #F7B56A | #D89C67 | lampes (texte, icône) |
| `--meteo` / `--musique` / `--sante` | #1B6682 / #A63350 / #7A5C0A | #80CBE0 / #F89DAD / #98D9B2 | #78A6BE / #D58D8B / #7EB396 | teinte des icônes de domaine |
| `--danger` | #B3261E | #FF9088 | #E8948B | texte et bord d'alerte |
| `--danger-solide` | #B3261E | #C73A32 | #B83A31 | fond du bouton destructif |
| `--ok` | #1F6B3E | #7ED3A0 | #7ED3A0 | état connecté, réussite |

Jetons de service : `--reflet` (filet de lumière du haut), `--ombre-rgb` (teinte des ombres, chaude en
clair, noire en sombre), `--voile` (fond d'une feuille modale), `--halo` (lueur bleue en haut de page).

### Typographie

- Instrument Sans (400 et 500) pour tout le texte, Big Shoulders Display (300) pour l'heure et les
  chiffres du code. Même fichiers que l'appli (`android/app/src/main/res/font/`), licence OFL.
- Pile : `"Instrument Sans", system-ui, sans-serif` et `"Big Shoulders Display", "Arial Narrow", sans-serif`.
- Échelle : texte 16 px (interligne 1,45), secondaire 15 px, aide et discret 14 px, pastille et
  surtitre 13 px, onglet 12 px (minimum absolu). Titre d'écran 24 px, titre de feuille 20 px, heure
  88 px, chiffre du code 48 px (affiché) ou 36 px (saisi). Chiffres en `tabular-nums`.
- Graisses : 400 pour le texte, 500 pour les titres, étiquettes et boutons. Pas de gras 700.
- Les maquettes lisent les polices par `local()` puis par un chemin relatif vers les TTF de l'appli.
  Le client final les sert en woff2 depuis son propre dossier (conversion à faire par la session de
  code), jamais depuis un site tiers.

### Espacement et formes

- Échelle de 4 px : `--e1` 4, `--e2` 8, `--e3` 12, `--e4` 16, `--e5` 20, `--e6` 24, `--e7` 32, `--e8` 40.
  Marge latérale d'écran 16 px, entre deux panneaux 12 px, entre sections 24 px.
- Rayons : `--r-s` 10 (puce), `--r-m` 16 (bouton, champ, alerte), `--r-l` 24 (panneau, feuille), pilule 999.
- Cible tactile : `--cible` 44 px au minimum, 48 px pour un bouton de formulaire, 52 px pour un champ,
  56 px pour un onglet. Deux cibles voisines sont séparées d'au moins 8 px.
- Écran de référence 390 x 844. En dessous de 430 px de large, l'écran prend toute la largeur.

### Recette du relief

| Élément | Recette |
|---|---|
| Panneau | `linear-gradient(surface-haut, surface-bas)`, bord `--filet` 1 px, ombre `0 1px 2px` plus `0 8px 20px -8px`, `inset 0 1px 0 --reflet` |
| Creux (champ, case de code, jauge) | fond `--champ`, `inset 0 2px 4px` d'ombre, filet de lumière dessous |
| Bouton principal | dégradé `--assistant` vers `--assistant-profond`, reflet blanc 28 % sur la moitié haute, halo bleu en dessous |
| Sphère (lampe, orbe) | dégradé radial : tache de lumière en haut à gauche, couleur, ombre intérieure en bas, halo extérieur |
| Feuille basse | voile `--voile` avec flou 3 px, feuille aux angles hauts arrondis, poignée de 40 x 5 px |

### États

Chaque contrôle montre les mêmes états, listés dans `composants.html`.

| État | Rendu |
|---|---|
| Repos | recette ci-dessus |
| Survol | `brightness(1.06)` sur un bouton, fond `rgba(ombre, .06)` sur une rangée |
| Focus clavier | contour de 3 px `--assistant`, décalé de 2 px, jamais supprimé |
| Pressé | descend de 1 px, ombre intérieure à la place de l'ombre portée |
| Désactivé | fond `--champ`, texte `--texte-3`, sans ombre, curseur interdit |
| Erreur | bord `--danger` de 2 px, message sous le champ, `aria-invalid="true"`, jamais la couleur seule |
| Chargement | rotor de 18 px dans le bouton, libellé conservé, `aria-busy="true"` |

### Composants réutilisables

Le nom donné est celui de la classe dans les maquettes.

| Composant | Rôle |
|---|---|
| `.telephone`, `.contenu` | cadre d'écran et zone défilante |
| `.barre-haut`, `.retour`, `.avatar` | titre d'écran, retour, pastille d'identité |
| `.carte`, `.titre-section`, `.surtitre` | panneau, titre de section, mini-titre de carte |
| `.rangee`, `.puce` | ligne tactile de 64 px minimum avec icône dans une puce |
| `.pastille` (`--ok`, `--assistant`, `--danger`, `--lumiere`) | état ou rôle, toujours avec un texte |
| `.bouton` (`--principal`, `--danger`, `--lien`, `--discret-danger`, `--plein`) | actions |
| `.champ`, `.etiquette`, `.aide` | champ de texte avec étiquette visible et aide liée par `aria-describedby` |
| `.case`, `.cases-code` | saisie du code à 6 chiffres |
| `.chiffre`, `.code-affiche`, `.jauge`, `.compte`, `.qr` | code affiché côté propriétaire, compte à rebours, QR code |
| `.etapes` | progression de l'appairage |
| `.roles`, `.role` (`--danger`) | choix du rôle, en boutons radio réels |
| `.alerte` (`--info`, `--ok`) | message d'état avec `role="alert"` |
| `.orbe`, `.sphere` | état de l'assistant, lampe |
| `.onglets`, `.onglet` (`--orbe`) | barre du bas : Accueil, Journal, Demander (orbe), Maison, Météo |
| `.voile`, `.feuille` | feuille modale basse |
| `.entree`, `.entree-pied` | entrée du journal : bouton de détail, pastille de résultat en mot, lien Ce n'était pas ça hors du bouton et seulement sur ses propres demandes |
| `.filtres`, `.filtre` | filtres du journal en boutons à état (`aria-pressed`), Tout par défaut |
| `.demande-en-cours`, `.pas` | demande en direct et ses étapes (fait, actuel, attente), chaque étape par une forme et un texte caché |
| `.feuille--haute`, `.fiche` | feuille de détail défilante et liste de définitions (heure, appareil, phrase, action, réponse) |
| `.orbe--l`, `.orbe-voix` | orbe de dictée à l'écoute, anneaux animés seulement hors `prefers-reduced-motion` |
| `.niveau-micro`, `.transcription` | niveau du micro et transcription en direct, partie provisoire en retrait |
| `.saisie`, `.bascule` | champ écrit avec envoi et option Essai, sans agir |
| `.reponse-iris` | réponse écrite de l'assistant et actions faites |
| `.roles` (niveau de vie privée), `.apercu` | sélecteur Tout, Action seulement, Discret en boutons radio réels, et aperçu en pointillé de ce que verrait un autre habitant |

La barre d'onglets est absente des écrans d'appairage et de la feuille de révocation. Réglages la
garde, sans onglet courant.

### Accessibilité

- Éléments natifs : `button`, `input`, `fieldset` et `legend`, `label for`. Les états passent par les
  attributs ARIA (`aria-current="page"`, `aria-invalid`, `aria-busy`, `aria-describedby`).
- Texte secondaire à 4,5 pour 1 au moins, bordure de contrôle à 3 pour 1 au moins, aucun texte sous 12 px.
- Une information n'est jamais portée par la couleur seule : icône ou texte l'accompagne.
- `prefers-reduced-motion` coupe les rotations.
- Saisie du code : la maquette dessine six cases à un chiffre (`inputmode="numeric"`,
  `autocomplete="one-time-code"`). À trancher par la session de code : un seul `input` de six
  chiffres habillé par six cases est plus fiable pour le collage, la saisie semi-automatique et les
  lecteurs d'écran que six champs, et le rendu reste identique.
- Avant l'appairage, aucun écran ne cite un prénom ni un nom de pièce.

## Charte

- Écran sobre et typographique, plan 3D du logement au centre, orbe pour l'état de l'assistant.
- Polices Big Shoulders Display (heure) et Instrument Sans (texte), sous licence OFL.
- Version de l'appli visible dans la couche de service et dans `android/VERSION.md`, toujours
  synchronisées.
- Textes en français avec accents, sans tiret cadratin, sans point-virgule en phrase, sans emoji.
- Ne pas copier le design d'un autre projet, assistant des auteurs inspiration compris.
