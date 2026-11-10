# Captures du mot de réveil

Depuis l'appli 0.53.0, l'appareil peut garder les 30 dernières secondes de son en mémoire et les écrire sur un
événement, pour comprendre pourquoi le mot de réveil est manqué ou se déclenche sans raison. Fonction désactivée
par défaut : le micro entend tout le logement, la prévenir avant de l'activer dans une pièce commune.

## Sur l'appareil

Réglages, carte Mot de réveil, « Captures du réveil » : Activé. Le son reste en mémoire seulement, rien n'est écrit
sans l'un de ces événements :

| Étiquette | Quand |
|---|---|
| `manque` | l'orbe est touché alors que l'assistant est au repos (le réveil n'a pas entendu) |
| `reveil` | le mot de réveil a lancé l'écoute |
| `faux_probable` | un réveil suivi de rien entendu en 8 s, ou d'une transcription vide |
| `faux_signale` | bouton « C'était un faux réveil » de la carte Déroulé, dans les deux minutes après un réveil |

Chaque capture est un WAV de 30 s (16 kHz, mono, 16 bits) et un JSON, dans le dossier privé de l'appli
(`files/captures-reveil/`). Le JSON garde l'horodatage, l'appareil, la version de l'appli, le modèle et son
empreinte, le seuil, la règle de confirmation, le mode, la cause, l'issue de l'écoute et, par bloc de 80 ms, le
score du détecteur, la probabilité de parole de Silero, le niveau en dB et la phase. Ni texte transcrit ni prénom.
Le dernier bloc est celui de l'événement.

Au plus 200 captures (environ 195 Mo) et 14 jours, les plus anciennes partent seules. « Effacer les captures » vide
le dossier, couper la fonction vide le tampon en mémoire. Le surcoût est une copie de 2,5 Ko par bloc et 1 Mo de
mémoire : le micro et le détecteur tournent déjà en continu.

Limite : en mode serveur avec le réveil guetté par le serveur, l'appareil n'a pas de scores. Le son est capturé
et `rejouer` les recalcule.

## Sur le PC

Les captures sont des données d'usage : jamais dans un dépôt (le garde-fou les refuse). Dossier par défaut
`C:/Dev/captures-reveil` (variable `ASSISTANT_VOCAL_CAPTURES` pour un autre), hors de `Documents` pour rester
hors des sauvegardes en ligne.

```
.venv\Scripts\python poc\outils\analyser_captures.py recuperer --serie <série adb> [--effacer]
.venv\Scripts\python poc\outils\analyser_captures.py lister [--etiquette manque]
.venv\Scripts\python poc\outils\analyser_captures.py rejouer [noms...] [--csv scores.csv]
.venv\Scripts\python poc\outils\analyser_captures.py seuils [--source rejoue] [--de 0.2 --a 0.8 --pas 0.05]
.venv\Scripts\python poc\outils\analyser_captures.py ecouter <nom>
```

`recuperer` exige la série adb (`adb devices -l`), passe par `run-as` (APK de débogage) et ne copie que les
fichiers `capture-*`. Avec `--effacer`, seules les captures copiées et vérifiées sont effacées sur l'appareil.
`rejouer` refait passer openWakeWord sur le son avec le même modèle (celui de `reveil/` dans la configuration,
ou Hey Jarvis) et compare aux scores de l'appareil. `seuils` reprend la règle de confirmation de l'appli
(deux blocs de suite, parole vue dans les 1,2 s) pour chaque seuil, et compte les manqués qui auraient réveillé,
les réveils gardés et les faux évités. Une capture `manque` ne contient pas toujours le mot : à vérifier avec
`ecouter` avant d'en tirer un seuil.
