# Licences des modèles et du code tiers

Le code de cet assistant (nommé assistant chez Alex, à ne pas confondre avec le projet des auteurs inspiration) est de Alex Exemple1, tous droits réservés tant qu'aucune licence n'est choisie.
Les modèles ci-dessous gardent leur propre licence, et leur fichier de licence est rangé à côté.

| Élément | Où | Licence | Remarque |
|---|---|---|---|
| Mot de réveil « assistant » (`assistant.onnx`) | Dans la configuration de Alex (`reveil/`), plus dans ce dépôt depuis la 0.25.0 | CC BY-NC-SA 4.0, Les auteurs inspiration (un projet voisin) | Pas d'usage commercial, partage dans les mêmes conditions. Chacun range son propre modèle dans `reveil/` de sa configuration. |
| Mot de réveil « Hey Jarvis » et prétraitement openWakeWord | `android/.../assets/reveil/` | Apache 2.0 (openWakeWord, David Scripka) pour le code, modèles sous CC BY-NC-SA 4.0 selon leur dépôt | Vérifier la licence du modèle `hey_jarvis` avant publication. |
| Silero VAD v5.1.2 | `poc/modeles/silero_vad.onnx`, `android/.../assets/vad/` | MIT (snakers4/silero-vad) | |
| YuNet, détection de visages | `poc/modeles/vision/yunet.onnx`, assets `vision/` | MIT (Shiqi Yu, opencv_zoo) | |
| SFace, reconnaissance de visages | téléchargé (`poc/outils/telecharger_modeles.py`) | Apache 2.0 (opencv_zoo) | |
| Voix Piper fr_FR-siwis-medium | téléchargée | Voir la fiche de la voix dans rhasspy/piper-voices (jeu de données SIWIS) | |
| Canary 1B v2 | téléchargé par onnx-asr | CC BY 4.0 (NVIDIA) | |
| three.js 0.170.0 (vue 3D de l'appartement) | `android/.../assets/maison3d/vue3d.html`, `carte/3d/vendor/` | MIT (three.js authors), fichier LICENSE-three.txt à côté | |
| OpenCV pour Android 4.14.0, onnxruntime, OkHttp, LiteRT-LM, CameraX | dépendances Gradle | Apache 2.0 ou MIT | |
| Police Big Shoulders Display (heure de l'accueil et de l'AOD de la tablette) | `android/.../res/font/big_shoulders_display_200.ttf`, `big_shoulders_display_300.ttf`, `big_shoulders_display_400.ttf` (panneau Météo, 0.20.0) | SIL Open Font License 1.1, The Big Shoulders Project Authors (github.com/xotypeco/big_shoulders), fichier `assets/polices/OFL-BigShouldersDisplay.txt` | Prise dans le dépôt google/fonts (`ofl/bigshouldersdisplay`) le 22/10/2026. Depuis l'appli 0.18.1, instance statique de la police variable à la graisse 200 (fontTools `varLib.instancer`, aucun dessin modifié), chargée par `resources.getFont`. |
| Police Instrument Sans (texte de la tablette) | `android/.../res/font/instrument_sans_400.ttf`, `instrument_sans_500.ttf`, `instrument_sans_italique_400.ttf` | SIL Open Font License 1.1, The Instrument Sans Project Authors (github.com/Instrument/instrument-sans), fichier `assets/polices/OFL-InstrumentSans.txt` | Prise dans le dépôt google/fonts (`ofl/instrumentsans`) le 22/10/2026. Depuis l'appli 0.18.1, instances statiques (Exemple2 400 et 500, italique 400) de la police variable (fontTools `varLib.instancer`, aucun dessin modifié). La page 3D ne l'embarque plus (plan 0.4.1). |

Idées reprises d'un projet d'inspiration (github.com/projet-voisin/assistant, PolyForm Noncommercial 1.0.0) : le code
a été réécrit, aucun fichier n'a été copié. Le comparatif est dans `inspirations/comparatif-projet_inspiration.md`.
