# Assistant vocal, versions du serveur

Journal du serveur (`poc/`) et de l'appli Home Assistant (`ha-app/`). L'appli Android a le sien dans
`android/VERSION.md`. La version s'affiche au démarrage du serveur et dans les capacités annoncées aux
satellites.

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
