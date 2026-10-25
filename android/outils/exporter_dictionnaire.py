"""Exporte le dictionnaire de Jarvis pour l'appli Android (mode « Cet appareil »).

Lit commandes.yaml du dossier de configuration de la maison (poc/maison.py) avec le même code que les
serveurs (poc/dictionnaire.py), développe toutes les formes et écrit genere/android/dictionnaire.json dans
le dossier de configuration, que build.gradle.kts range dans les assets de l'APK :
  {"version", "genere_le", "modeles": [{"actions", "reponse", "source", "ligne", "motif"}],
   "formes": [[cle, indice du modèle, {emplacement: valeur}]], "llm", "personnes", "services_permis"}
« cle » est la phrase normalisée (minuscules, sans accents ni ponctuation), « source » le fichier
d'origine et « ligne » le numéro de ligne du motif, affichés dans le déroulé de l'appli.

Les phrases apprises de cette machine (commandes_apprises.yaml du dossier de données) sont des données
d'usage, pas de la configuration : depuis l'appli 0.32.2 elles partent dans un export à part,
genere/android/dictionnaire_appris.json du dossier de données (JARVIS_DONNEES, poc/ par défaut), au même
format (« modeles » et « formes », sans « llm » ni « personnes »), sans les phrases déjà couvertes par
commandes.yaml. build.gradle.kts l'ajoute aux assets s'il existe, DictionnaireLocal.kt le fusionne.
Les deux fichiers portent le même jeton « export » : l'appli ignore des phrases apprises venues d'un autre
export (fichier périmé, autre machine, autre maison).

Usage : python android/outils/exporter_dictionnaire.py   (à relancer avant chaque compilation
quand le dictionnaire ou les phrases apprises ont changé)
        --exemple   dictionnaire de config-exemple/, sans phrase apprise, ni date, ni jeton, pour les tests
unitaires de l'appli : un test de poc/tests vérifie qu'il est à jour
        --sortie FICHIER   écrit dictionnaire.json ailleurs que dans genere/android/ (ce test compare ainsi sans
réécrire l'export d'exemple suivi par git). Hors --exemple, les phrases apprises restent écrites dans le
dossier de données.
        --donnees DOSSIER   dossier de données (JARVIS_DONNEES sinon). Un chemin relatif part de la racine
du dépôt, comme dans build.gradle.kts.
"""
import argparse, json, os, re, sys, time, uuid
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent.parent
POC = RACINE / "poc"
_args = argparse.ArgumentParser(description="Exporte le dictionnaire de Jarvis pour l'appli Android.")
_args.add_argument("--exemple", action="store_true")
_args.add_argument("--sortie", type=Path)
_args.add_argument("--donnees")
ARGS = _args.parse_args()
EXEMPLE = ARGS.exemple
if EXEMPLE:
    os.environ["ASSISTANT_VOCAL_CONFIG"] = str(RACINE / "config-exemple")
# Avant l'import d'assistant, qui lit JARVIS_DONNEES : même résolution d'un chemin relatif que Gradle.
_donnees = ARGS.donnees or os.getenv("JARVIS_DONNEES", "")
if _donnees.strip():
    os.environ["JARVIS_DONNEES"] = str(Path(_donnees) if Path(_donnees).is_absolute() else RACINE / _donnees)
sys.path.insert(0, str(POC))
import yaml  # noqa: E402
import assistant as A  # noqa: E402
import maison  # noqa: E402
from dictionnaire import developper, normaliser  # noqa: E402

SORTIE = ARGS.sortie or maison.chemin("genere/android/dictionnaire.json")
SORTIE_APPRIS = A.DONNEES / "genere" / "android" / "dictionnaire_appris.json"


def numero_ligne(lignes, motif, depuis=0):
    for i in range(depuis, len(lignes)):
        if motif in lignes[i]:
            return i + 1
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    chemin = maison.chemin("commandes.yaml")
    texte = chemin.read_text(encoding="utf-8")
    lignes = texte.splitlines()
    donnees = yaml.safe_load(texte)
    emplacements = {nom: [(normaliser(f), v) for motif, v in valeurs.items() for f in developper(motif)]
                    for nom, valeurs in (donnees.get("emplacements") or {}).items()}

    def remplir(forme):
        m = re.search(r"\{(\w+)\}", forme)
        if not m:
            yield " ".join(forme.split()), {}
            return
        for texte_val, val in emplacements[m.group(1)]:
            for t, valeurs in remplir(forme[:m.start()] + texte_val + forme[m.end():]):
                yield t, {m.group(1): val, **valeurs}

    # Format compact (0.13.3) : un « modèle » par motif (actions à trous, réponse, ligne), et une forme
    # = [clé, indice du modèle, valeurs des emplacements]. Avec la luminosité, 17 000 formes faisaient 6 Mo.
    modeles, formes, vus = [], [], set()
    debut_commandes = numero_ligne(lignes, "commandes:")
    for cmd in donnees["commandes"]:
        actions = cmd["action"] if isinstance(cmd["action"], list) else [cmd["action"]]
        for motif in cmd["phrases"]:
            indice = len(modeles)
            modeles.append({"actions": actions, "reponse": cmd.get("reponse", "C'est fait."),
                            "source": "commandes.yaml", "ligne": numero_ligne(lignes, motif, debut_commandes),
                            "motif": motif})
            for forme in developper(motif):
                for cle, valeurs in remplir(normaliser(forme)):
                    if cle not in vus:
                        vus.add(cle)
                        formes.append([cle, indice, valeurs] if valeurs else [cle, indice])
    # Phrases apprises : export à part dans le dossier de données (0.32.2), jamais pour l'exemple.
    modeles_appris, formes_appris = [], []
    chemin_appris = A.DONNEES / "commandes_apprises.yaml"
    if chemin_appris.exists() and not EXEMPLE:
        texte_appris = chemin_appris.read_text(encoding="utf-8")
        lignes_appris = texte_appris.splitlines()
        for cmd in (yaml.safe_load(texte_appris) or {}).get("apprises") or []:
            cle = normaliser(cmd["phrase"])
            if cle and cle not in vus:
                vus.add(cle)
                actions = cmd["action"] if isinstance(cmd["action"], list) else [cmd["action"]]
                formes_appris.append([cle, len(modeles_appris)])
                modeles_appris.append({"actions": actions, "reponse": cmd.get("reponse", "C'est fait."),
                                       "source": "commandes_apprises.yaml", "appris": True,
                                       "ligne": numero_ligne(lignes_appris, cmd["phrase"]), "motif": cmd["phrase"]})
    # Pour le LLM sur l'appareil (0.13.0) : même vue que le LLM des serveurs (appareils renommés,
    # masqués, notes) et même liste blanche de services.
    # L'exemple ne porte ni version ni date : il ne change que si son dictionnaire change.
    # Jeton commun aux deux fichiers de cet export, absent de l'exemple pour qu'il reste stable.
    jeton = "" if EXEMPLE else uuid.uuid4().hex
    sortie = {"version": "exemple" if EXEMPLE else A.VERSION,
              "genere_le": "exemple" if EXEMPLE else time.strftime("%Y-%m-%d %H:%M"), "modeles": modeles, "formes": formes,
              "llm": donnees.get("llm") or {},
              # « Ma chambre » selon la personne qui parle (21/10/2026), appliqué par DictionnaireLocal.Personnes.
              "personnes": donnees.get("personnes") or {},
              "services_permis": {d: sorted(s) for d, s in A.SERVICES_PERMIS.items()}}
    if jeton:
        sortie["export"] = jeton
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(sortie, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(formes)} formes exportées vers {SORTIE} ({SORTIE.stat().st_size // 1024} Ko)")
    if EXEMPLE:
        return
    # Toujours écrit, même vide, pour qu'une APK ne garde pas d'anciennes phrases oubliées depuis.
    SORTIE_APPRIS.parent.mkdir(parents=True, exist_ok=True)
    SORTIE_APPRIS.write_text(json.dumps({"version": A.VERSION, "genere_le": sortie["genere_le"], "export": jeton,
                                         "modeles": modeles_appris, "formes": formes_appris},
                                        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(formes_appris)} phrases apprises exportées vers {SORTIE_APPRIS}")


if __name__ == "__main__":
    main()
