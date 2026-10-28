# Accéder au client web par Tailscale Serve

Le client web pour téléphone est servi par le serveur de l'assistant sur le port 8767, **en boucle locale
seulement**. Pour l'ouvrir depuis un téléphone, on le publie sur le tailnet en HTTPS avec Tailscale Serve, et on
ferme le reste du tailnet par une liste de contrôle d'accès (ACL) en liste blanche. Ce document donne la
procédure, les réglages du serveur, le modèle d'ACL et la liste à cocher de l'essai sur le téléphone (lot S-W7).

Rien ici ne s'applique tout seul : ni le dépôt ni le serveur ne lancent de commande `tailscale` ni ne touchent à
une ACL. Tous les noms de ce document (`assistant.exemple.ts.net`, `camille@exemple.org`, `tag:assistant-pc`) sont
fictifs. Le fonctionnement du client web est décrit dans `docs/ARCHITECTURE.md`.

## 1. Le principe

```
téléphone (Tailscale)  --HTTPS 443-->  Tailscale Serve du PC  --HTTP-->  127.0.0.1:8767 (serveur de l'assistant)
```

- Serve termine le HTTPS avec un certificat valide pour le nom du PC sur le tailnet (`<machine>.<tailnet>.ts.net`).
  Un certificat valide est ce qui rend possibles le micro, l'installation comme application (PWA) et WebAuthn.
- Le serveur de l'assistant n'écoute que sur `127.0.0.1:8767`. Rien du client n'est ouvert sur le Wi-Fi de la
  maison.
- Funnel (publication sur Internet) est exclu. Ne jamais lancer `tailscale funnel`.
- Tailscale filtre le réseau, il n'authentifie pas l'appareil. Le serveur ne lit jamais l'en-tête
  `Tailscale-User-Login` (tout processus du PC peut le forger en joignant `127.0.0.1`). L'accès repose sur
  l'appairage du navigateur (cookie `__Host-session` et clé d'accès WebAuthn), voir la section 6.
- Publier le client ne ferme pas les autres ports du PC. Les ports 8765 (clair) et 8766 (chiffré) des satellites
  écoutent sur toutes les adresses : c'est l'ACL de la section 5 qui les ferme au tailnet, et le pare-feu
  Windows qui les limite au réseau local.

## 2. Avant de commencer

- Un tailnet, avec Tailscale installé et connecté sur le PC qui fait tourner le serveur et sur le téléphone.
- Dans la console d'administration de Tailscale, onglet DNS : MagicDNS activé et **HTTPS Certificates** activé.
  Sans cela, Serve ne peut pas obtenir de certificat.
- Un nom de tailnet aléatoire (la console en propose) et un nom de machine neutre pour le PC. Les deux se
  retrouvent dans les journaux publics de transparence des certificats : n'y mettre ni prénom ni adresse.
- Le serveur lancé avec son client web actif. C'est le cas par défaut (`--port-web` vaut 8767 et
  `--adresse-web` vaut 127.0.0.1). Le démarrage affiche `Client web (HTTP) sur 127.0.0.1:8767`. Ne changez pas
  `--adresse-web` : ouvrir le client à une autre adresse que la boucle locale le sortirait de la protection de
  Serve.

## 3. Publier le port 8767

Sur le PC, dans un PowerShell :

```powershell
tailscale serve --bg --https=443 http://127.0.0.1:8767
tailscale serve status
```

`serve status` doit montrer `https://<machine>.<tailnet>.ts.net` redirigé vers `http://127.0.0.1:8767`, et lui
seul. Vérifiez aussi que Funnel est éteint :

```powershell
tailscale funnel status
```

La commande ne doit rien publier. Le premier accès demande un certificat à Tailscale et peut prendre quelques
secondes.

Le port public doit rester **443**. Le serveur accepte le nom de domaine de Serve sans numéro de port : une
publication sur un autre port (8443 par exemple) fait arriver `Host: assistant.exemple.ts.net:8443`, que le
serveur refuse.

Le nom à utiliser est celui que `tailscale serve status` affiche. C'est lui qu'on met dans `maison.json`.

## 4. Régler le serveur

Le serveur n'accepte qu'un nom de domaine en plus de la boucle locale. La clé `client_web.hote` de
`config/maison.json` porte ce nom. Le QR code d'appairage d'un navigateur (section Navigateurs web de la page
d'administration) est construit à partir d'elle. Le code du bouton « Créer un code » ne sert qu'à l'appli Android
et n'a pas de QR code. L'ancienne clé `administration.url_client` est ignorée depuis la version 0.58.3.

| Clé | Rôle | Valeur |
|---|---|---|
| `client_web.hote` | Nom de domaine de Serve, sans schéma ni port. Il fixe la valeur exacte de `Host` acceptée, l'origine exacte `https://<hote>` acceptée et le `rpId` de WebAuthn. | `assistant.exemple.ts.net` |
| `administration.utilisateurs_ha` | Identifiants des comptes Home Assistant autorisés à ouvrir la page d'administration. Liste vide ou absente : la page refuse tout le monde. | `["0123456789abcdef0123456789abcdef"]` |

Pour connaître l'identifiant de son compte, le propriétaire ouvre la page une première fois : dans Home Assistant,
entrée « Assistant vocal » de la barre latérale, ou Paramètres, Applications, l'appli, « Ouvrir l'interface web ».
Le refus écrit l'identifiant dans le journal de l'appli (`ha apps logs local_jarvis`, ligne
`utilisateur <id> hors de administration.utilisateurs_ha`). Il suffit de le recopier dans la liste, puis de
reconstruire l'appli.

Ce qui est accepté, et rien de plus :

| Contrôle | Accepté | Refusé (HTTP 403 sans explication) |
|---|---|---|
| `Host` | `127.0.0.1:8767`, `localhost:8767`, `[::1]:8767`, et la valeur de `client_web.hote` sans port | tout autre nom, y compris l'adresse IP du tailnet, un `Host` avec un autre port |
| `Origin` | les mêmes origines en `http://` locales, et `https://` plus `client_web.hote` | origine absente sur un WebSocket, `null`, toute autre origine |

Points à connaître :

- Le serveur ne propose aucune clé pour ajouter d'autres hôtes ou d'autres origines. Un second nom de domaine
  demanderait un changement de code, qui n'est pas prévu.
- `client_web.hote` sert aussi de `rpId` WebAuthn. **Le changer après un premier appairage invalide les clés d'accès
  déjà créées** : il faut réappairer chaque navigateur. Fixez donc le nom avant d'appairer.
- Sans `client_web.hote` (vide ou absent), seules les adresses locales passent, ce qui est le bon état tant que
  Serve n'est pas posé.
- Les clés se relisent au démarrage : relancez le serveur après modification.

Côté Windows, Serve est tenu par le service Tailscale et ne demande aucune règle de pare-feu pour le port 443.
Ne créez aucune règle d'entrée pour 8767 : il n'écoute qu'en boucle locale. Les ports 8765 et 8766 gardent la règle
du réseau privé décrite dans `docs/INSTALLER.md`, section 8.

## 5. L'ACL du tailnet

Le modèle est `config-exemple/tailnet-acl.exemple.hujson`. C'est une liste blanche : tout ce qui n'est pas
écrit est refusé. Il donne au propriétaire le port 443 du PC de l'assistant et rien d'autre, laisse le PC joindre
le relais santé, et se termine par un bloc `tests` qui prouve que 8765, 8766, 8767, SSH, bureau à distance et
partage de fichiers ne sont pas joignables du tailnet.

**Cette liste s'applique à tout le tailnet, pas seulement à l'assistant.** Une règle manquante coupe un flux qui
marche aujourd'hui (synchronisations, SSH, tableau de bord). La procédure, dans l'ordre :

1. Dans la console, onglet Access controls, copiez la politique actuelle dans un fichier à part. C'est le retour
   arrière.
2. Listez les flux existants : machines de `tailscale status`, services qui s'appellent par le tailnet,
   ports utilisés. Le bloc « À COMPLÉTER » du modèle attend une règle par flux, avec le port exact.
3. Copiez le modèle hors du dépôt et remplacez les noms fictifs : adresse du compte propriétaire, étiquettes,
   adresse du PC. Ne mettez pas ce fichier réel dans le dépôt du moteur.
4. Créez d'abord l'étiquette sans rien couper : ajoutez à la **politique actuelle** seulement le bloc `tagOwners`
   du modèle, enregistrez, puis dans la console étiquetez le PC `tag:assistant-pc` (Machines, menu du PC, Edit
   ACL tags). Un appareil étiqueté n'appartient plus à un utilisateur : les règles de l'ancienne politique qui le
   désignaient par son utilisateur doivent être réécrites avec l'étiquette.
5. Remplacez ensuite toute la politique par le modèle complété. Avant d'enregistrer, regardez le panneau de
   prévisualisation pour le compte propriétaire et pour chaque machine qui parle à une autre : les flux listés à
   l'étape 2 doivent rester ouverts. Le bloc `tests` est rejoué à chaque enregistrement et refuse la politique si
   un test échoue.
6. Après l'enregistrement, vérifiez à la main un flux ancien de chaque sorte (SSH, synchronisation, tableau de
   bord) avant de passer à la suite.

Les habitants qui n'ont pas Tailscale n'atteignent pas le client web. Pour eux, deux voies à décider avec le
propriétaire : le partage de nœud Tailscale avec leur propre compte (à tester dans la prévisualisation, car les
règles de la politique pèsent aussi sur les comptes invités), ou un secours local sur le réseau de la maison,
non fourni à ce jour.

Joindre Home Assistant par le réseau ne suffit pas. Le client web n'est pas servi par l'appli Home Assistant mais par
le PC, derrière Serve : un habitant qui atteint seulement Home Assistant (par son propre tailnet, par exemple) ne
peut pas suivre le QR code tant que le PC ne lui est pas partagé. La page d'administration, elle, reste réservée
aux comptes de `administration.utilisateurs_ha`, même pour un habitant qui a un compte Home Assistant. Quant aux
ports 8765 et 8766 de l'appli, ils exigent un jeton d'appareil appairé, et seul un administrateur accepte un
nouvel appareil.

## 6. Premier appairage d'un téléphone

Le tailnet décide qui peut frapper à la porte, l'appairage décide qui entre. Le téléphone du propriétaire s'appaire
ainsi :

1. Dans l'appli Home Assistant, page d'administration, section « Navigateurs web », le propriétaire ouvre un
   appairage. Le code à 6 chiffres vaut 2 minutes, trois essais, et n'est affiché que là.
2. Sur le téléphone, ouvrir `https://assistant.exemple.ts.net/appairage` (ou scanner le QR code) et saisir le code.
3. Confirmer avec la clé d'accès du téléphone (empreinte, visage ou verrouillage d'écran). Le serveur pose alors le
   cookie de session, valable 30 jours d'inactivité au plus.
4. L'écran `/reglages` liste les appareils associés et permet de les révoquer.

La page d'administration n'existe que dans l'appli Home Assistant. Un serveur lancé ailleurs (le PC, par exemple)
amorce son premier propriétaire au démarrage :

```bash
python poc/serveur_satellite.py --amorcer-proprietaire "Téléphone du propriétaire"
```

L'option n'agit que si aucun propriétaire n'existe. Le code vaut 15 minutes, trois essais, et se lit dans
`amorcage_web.json` du dossier de données (`JARVIS_DONNEES`, sinon `poc/`), jamais dans le journal. Le code saisi
tient lieu de confirmation : il n'y a pas d'étape 3 côté administration, seulement la clé d'accès du téléphone. Le
fichier disparaît dès que l'appairage aboutit, se ferme ou expire. Il suffit de relancer le serveur avec l'option
pour en obtenir un nouveau.

En cas de blocage, le repli en console est `python poc/appairage_web.py --reinitialiser`.

## 7. Lire un refus

Le serveur écrit chaque refus dans sa sortie sous la forme `serveur web : refus depuis <adresse> (<cause>)`, sans
jamais écrire de cookie, de jeton ni d'en-tête. Derrière Serve, l'adresse est toujours `127.0.0.1`.

| Cause | Ce que ça veut dire | Remède |
|---|---|---|
| `hôte refusé` | Le navigateur a joint le serveur sous un nom ou un port que `client_web.hote` n'autorise pas : adresse IP du tailnet, ancien nom de machine, Serve publié sur un autre port. | Ouvrir l'adresse en `https://<client_web.hote>/`. Vérifier `tailscale serve status` et la valeur de `client_web.hote`, puis relancer le serveur. |
| `origine refusée` | Une page d'un autre site, ou un autre nom que `hote`, a tenté d'ouvrir le WebSocket. | Même contrôle. Si le téléphone est le seul concerné, ouvrir l'adresse sans passer par un favori ancien. |
| `origine absente` | Un client WebSocket sans en-tête `Origin`, jamais un navigateur normal. | Rien à corriger côté navigateur. |
| `cookie absent`, `cookie inconnu`, `cookie expiré`, `cookie révoqué` | Le navigateur n'est pas ou plus appairé. | Réappairer (section 6). |

Une ACL qui bloque un port ne laisse aucune trace dans ce journal : la connexion n'arrive pas jusqu'au serveur.
Sur le téléphone, c'est un délai d'attente, pas un refus.

## 8. Retour arrière

Chaque étape se défait seule, dans cet ordre :

1. Dépublier le client : `tailscale serve --https=443 off` (ou `tailscale serve reset` pour tout effacer).
   Le client n'est plus joignable, le serveur continue de tourner sur la boucle locale.
2. Remettre l'ancienne politique d'accès, copiée à l'étape 1 de la section 5, dans la console.
3. Pour couper le client web sans toucher à Tailscale : lancer le serveur avec `--port-web 0`. Les satellites
   (8765 et 8766) ne sont pas touchés.

Les appareils web appairés (`appareils_web.json`) restent enregistrés et reprennent du service à la remise en
route, tant que `client_web.hote` n'a pas changé.

## 9. Ce qui reste hors de ce lot

- La fermeture du port 8765 (décision D7 du plan) attend un mot du propriétaire et sept jours de tablette sur
  8766. L'ACL et le pare-feu limitent l'exposition en attendant, ils ne remplacent pas cette décision.
- Le client quand le PC est éteint (conception, section 5.4) n'est pas livré : sans le PC, le client web ne
  répond pas.
- L'autorité de certification locale (secours sur le réseau local, section 5.3) n'est pas fournie.

## 10. Liste à cocher : fin de lot locale, essai depuis le téléphone

À faire par le propriétaire, sur sa machine et son tailnet. Cochez dans l'ordre, une case à la fois.

**Console Tailscale**

- [ ] MagicDNS et HTTPS Certificates sont activés (onglet DNS).
- [ ] Le nom du tailnet est aléatoire et le nom de la machine du PC est neutre.
- [ ] La politique actuelle est copiée dans un fichier à part (retour arrière).
- [ ] Le bloc `tagOwners` est ajouté à la politique actuelle, et le PC est étiqueté `tag:assistant-pc`.
- [ ] Le modèle `config-exemple/tailnet-acl.exemple.hujson` est copié hors du dépôt, avec les vrais noms et tous
      les flux existants écrits dans le bloc « À COMPLÉTER ».
- [ ] La prévisualisation montre que chaque flux existant reste ouvert, et le bloc `tests` passe.
- [ ] La politique est enregistrée, puis un flux ancien de chaque sorte est vérifié à la main (SSH, synchronisation,
      tableau de bord).

**PC**

- [ ] `tailscale serve --bg --https=443 http://127.0.0.1:8767` est lancé, `tailscale serve status` ne montre que
      cette publication, `tailscale funnel status` ne montre rien.
- [ ] `client_web.hote` de `config/maison.json` porte le nom affiché par `serve status`, et le serveur est
      relancé.
- [ ] Le démarrage du serveur affiche `Client web (HTTP) sur 127.0.0.1:8767`.
- [ ] La règle de pare-feu Windows de 8765 et 8766 est limitée au profil réseau privé, et il n'existe aucune règle
      pour 8767 ni 443.

**Téléphone, Wi-Fi coupé (données mobiles et Tailscale actifs)**

- [ ] `https://<client_web.hote>/` affiche la page d'accueil, avec un cadenas valide et sans avertissement.
- [ ] L'appairage de la section 6 aboutit, et le téléphone figure dans `/reglages`.
- [ ] Après fermeture complète du navigateur, la page se rouvre sans nouvel appairage.
- [ ] Le client s'installe sur l'écran d'accueil et se rouvre appairé.
- [ ] Le navigateur demande la permission du micro (HTTPS valide), et une demande écrite aboutit en mode essai.

**Contrôles négatifs**

- [ ] Depuis le téléphone, `https://<adresse IP du PC sur le tailnet>/` est refusé (403), et le journal du serveur
      écrit `hôte refusé`.
- [ ] Depuis le téléphone, `http://<adresse IP du PC sur le tailnet>:8765/` et `:8766` n'aboutissent pas (délai
      d'attente).
- [ ] Un appareil du tailnet qui n'est pas au propriétaire n'atteint pas le port 443 du PC.
- [ ] Révoquer le téléphone depuis `/reglages` fait demander un nouvel appairage à la visite suivante.

**Clôture**

- [ ] Les deux clés de `maison.json` et la date de l'essai sont notées dans la note du projet.
- [ ] Le lot est déclaré fait au directeur du plan, ou le retour arrière de la section 8 est déroulé et le motif
      noté.
