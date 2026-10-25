# Assistant vocal, versions de l'appli Android

Application Android `assistant.vocal.jarvis` : écran ambiant et assistant vocal de la maison sur une tablette posée
en paysage (mode « Cet appareil » ou serveur `poc/serveur_satellite.py`), satellite vocal sur les
téléphones. La version et la date de compilation s'affichent dans la couche de service de l'accueil de la
tablette (un toucher dans le noir), dans l'en-tête des réglages, en pied de l'écran du téléphone et dans la
notification du service.

## 0.31.0 (2026-10-25)
- Nom affiché de l'assistant lu dans la section `assistant` de `maison.json` (`ConfigMaison.NOM_ASSISTANT`) :
  nom de l'appli sous l'icône (`resValue app_name` dans `build.gradle.kts`), textes de l'accueil, des
  réglages, de la météo, de la musique, de la vision et des notifications, en formulations neutres.
  « Assistant » sans la section.
- Identifiants neutres : pont de la page 3D `window.maison3d` et `Maison3dAndroid` (page 3D à régénérer
  avec `carte/3d/generer_3d.py`), mot de réveil personnalisé `perso` (`segmentPerso`, `CLE_SEUIL_PERSO`).
  L'ancien seuil `seuil_reveil_assistant` est recopié une fois au démarrage, l'ancien choix enregistré reste
  lu comme mot personnalisé.
- Sons d'écoute : commentaire ICMT des WAV neutre, son inchangé.
- Test `ConfigMaisonTest`. versionCode 56.

## 0.30.1 (2026-10-24)
- Premier instantané du moteur, sans historique. La configuration de la maison (`maison.json`,
  dictionnaire exporté, page 3D, trait de côte, mot de réveil) vient du dossier de configuration et
  entre dans l'APK à la compilation. Une APK est refusée sans lui. La numérotation continue celle du
  projet d'origine. versionCode 55.
