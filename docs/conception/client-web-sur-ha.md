# Servir le client web depuis l'appli Home Assistant

Note de conception, lot HA au centre (0.53.0). Aucun code n'est écrit ici. La question : le client web
(`poc/serveur_web.py`, port 8767) tourne aujourd'hui sur le PC ou sur un nœud Tailscale. Pour que tout marche PC
éteint, l'appli HA doit pouvoir le servir elle-même, sans élargir l'exposition réseau par défaut.

## Ce que le client web impose

- Il écoute sur 127.0.0.1:8767 et n'est joint que par Tailscale Serve. Il contrôle le Host et l'Origin au nom exact
  (`client_web.hote` de la configuration) et refuse le reste par un 403.
- Son cookie `__Host-session` exige Secure, Path=/ et aucun Domain. L'appairage WebAuthn lie la clé au nom de domaine
  de la page. Changer de nom de domaine oblige à réappairer chaque téléphone.
- Sa politique de contenu interdit le cadrage (`frame-ancestors 'none'`), sauf pour la maquette 3D.
- Les pages et scripts du client contiennent une cinquantaine de chemins absolus (`/app.js`, `/ws/...`). Ils supposent
  d'être servis à la racine d'un nom de domaine.

## Piste 1 : Ingress de Home Assistant

L'appli expose déjà son administration par Ingress (port 8099, personne d'autre que le superviseur n'y accède).

- Exposition : aucune de plus. Le client web serait atteint partout où HA l'est (Nabu Casa ou Tailscale de l'hôte).
- Sécurité : l'authentification de HA s'ajoute à celle du client. Mais Ingress réécrit le chemin sous un préfixe à
  jeton, et le client web a besoin d'un nom de domaine propre. Le cookie `__Host-` serait posé sur le domaine de HA,
  et la clé WebAuthn serait liée à ce domaine, partagé avec toute HA.
- Travail de code : le plus lourd. Une appli n'a qu'un seul port Ingress, donc il faut un routeur entre
  l'administration et le client sur 8099. Il faut passer tous les chemins en relatif, lire l'en-tête du préfixe
  Ingress, assouplir le contrôle du Host et de l'Origin, et revoir le cookie et WebAuthn.

## Piste 2 : port publié et Tailscale de l'hôte HA

Publier 8767 dans `ports` et laisser l'hôte HA (module Tailscale) le proposer sur le tailnet.

- Exposition : un port publié par le superviseur écoute sur toutes les interfaces de l'hôte, donc sur le réseau local
  aussi, en HTTP clair. C'est un élargissement, à ne faire qu'avec une option vide par défaut.
- Sécurité : le Host exact et le cookie Secure rendent la porte du réseau local inutilisable, mais elle reste ouverte.
  Le module Tailscale de l'hôte sait surtout proxifier HA lui-même, la publication d'un autre port et son certificat
  HTTPS sont à vérifier.
- Travail de code : modéré. Une option de port (0 par défaut), l'écoute sur 0.0.0.0 dans le conteneur quand le port
  est publié, la lecture du nom tailnet dans `client_web.hote`.

## Piste 3 : un nœud Tailscale propre à l'appli

Embarquer `tailscaled` en mode réseau utilisateur dans l'image de l'appli, avec `tailscale serve` vers
127.0.0.1:8767. L'appli devient un nœud du tailnet sous son propre nom.

- Exposition : tailnet seulement, aucun port publié, aucun accès depuis le réseau local. Le client web reste lié à la
  boucle locale comme aujourd'hui.
- Sécurité : le contrôle du Host, le cookie `__Host-` et WebAuthn ne changent pas, avec un nom de domaine stable et
  dédié. Contrepartie : une clé d'authentification Tailscale à stocker dans les options (champ password) et à
  restreindre par étiquette et par ACL. Le nœud est un acteur de plus à surveiller.
- Travail de code : moyen, mais isolé. Tailscale dans le Dockerfile, deux options (clé, nom du nœud, vides par
  défaut, donc rien ne démarre), l'état conservé dans `/data`, un démarrage conditionnel dans `demarrage.py`. Le
  serveur web ne change pas.

## Recommandation

Piste 3. Elle seule garde le client tel qu'il est (racine d'un domaine à lui, cookie et WebAuthn inchangés,
écoute en boucle locale) et n'ajoute aucune exposition sur le réseau local. L'Ingress est séduisant par son absence
de port mais coûte une réécriture des chemins et casse le lien WebAuthn, donc il convient mal à un client conçu pour
sa propre origine. La piste 2 reste un repli simple si Tailscale dans l'image pose problème, à condition de
documenter l'ouverture sur le réseau local. Prochaine étape suggérée : un essai de la piste 3 sur la HA de test avec
une clé à usage unique et à courte durée, avant tout code dans la branche principale.
