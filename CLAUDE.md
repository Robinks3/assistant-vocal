# Assistant vocal local

Assistant vocal local en français qui remplace Google Assistant et pilote la maison via Home Assistant.
Ce dépôt est le moteur : rien d'un logement réel n'y entre. Présentation complète dans `README.md`.

## Configuration

Tout ce qui décrit la maison est lu dans le dossier de configuration : `ASSISTANT_VOCAL_CONFIG`, sinon `config/`
(ignoré par git, souvent un dépôt privé cloné là). Ne jamais écrire dans le code une adresse, un identifiant
d'entité, un prénom, une pièce ou une coordonnée : ajouter une clé à `maison.json` et la même clé, fictive,
à `config-exemple/maison.json`. Les tests tournent sur `config-exemple/` (`poc/tests/conftest.py`,
`android/app/build.gradle.kts`).

## Règles

- Tests verts avant chaque commit : `python -m pytest poc/tests` et, dans `android/`,
  `./gradlew testDebugUnitTest`.
- Versions : serveur dans `poc/assistant.py` (`VERSION`), `ha-app/jarvis/config.yaml` et `VERSION.md`.
  Appli dans `android/app/build.gradle.kts` (`versionApplication`, `versionCode`) et `android/VERSION.md`.
  Le numéro change avec le code, partout en même temps.
- La sécurité en dur (`poc/securite.py` et `Securite.kt`, mêmes cas dans `poc/tests/cas_securite.json`) ne
  s'affaiblit jamais.
- Le garde-fou de `.githooks/` (`git config core.hooksPath .githooks`) refuse au commit et à l'envoi les
  secrets, les données d'usage et les fichiers de plus de 5 Mo. Ne jamais le contourner (`--no-verify`)
  sans l'accord du propriétaire du dépôt.
- Ne jamais lire `poc/.env` ni `android/local.properties` : ils contiennent des secrets.
- Aucun nom de dépôt, de dossier ni de variable ne contient « assistant » : c'est le nom du projet des
  auteurs inspiration, cité comme inspiration. Le mot de réveil « assistant » n'est qu'un réglage de configuration.
- Textes en français avec accents, sans tiret cadratin, sans point-virgule en phrase, sans emoji.
