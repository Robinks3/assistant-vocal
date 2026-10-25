# Assistant vocal, versions du serveur

Journal du serveur (`poc/`) et de l'appli Home Assistant (`ha-app/`). L'appli Android a le sien dans
`android/VERSION.md`. La version s'affiche au démarrage du serveur et dans les capacités annoncées aux
satellites.

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
