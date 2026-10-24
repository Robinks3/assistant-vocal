"""Exporte le dictionnaire de Jarvis pour l'appli Android (mode « Cet appareil »).

Lit commandes.yaml du dossier de configuration de la maison (poc/maison.py) et les phrases apprises de
cette machine (commandes_apprises.yaml du dossier de données), avec le même code que les serveurs
(poc/dictionnaire.py), développe toutes les formes et écrit genere/android/dictionnaire.json dans le
dossier de configuration, que build.gradle.kts range dans les assets de l'APK :
  {"version", "genere_le", "modeles": [{"actions", "reponse", "source", "ligne", "motif"}],
   "formes": [[cle, indice du modèle, {emplacement: valeur}]], "llm", "personnes", "services_permis"}
« cle » est la phrase normalisée (minuscules, sans accents ni ponctuation), « source » le fichier
d'origine et « ligne » le numéro de ligne du motif, affichés dans le déroulé de l'appli.

Usage : python android/outils/exporter_dictionnaire.py   (à relancer avant chaque compilation
quand le dictionnaire ou les phrases apprises ont changé)
        python android/outils/exporter_dictionnaire.py --exemple   (dictionnaire de config-exemple/, sans phrase
apprise ni date, pour les tests unitaires de l'appli : un test de poc/tests vérifie qu'il est à jour)
"""
import json, os, re, sys, time
from pathlib import Path

ICI = Path(__file__).resolve().parent
POC = ICI.parent.parent / "poc"
EXEMPLE = "--exemple" in sys.argv
if EXEMPLE:
    os.environ["ASSISTANT_VOCAL_CONFIG"] = str(POC.parent / "config-exemple")
sys.path.insert(0, str(POC))
import yaml  # noqa: E402
import assistant as A  # noqa: E402
import maison  # noqa: E402
from dictionnaire import developper, normaliser  # noqa: E402

SORTIE = maison.chemin("genere/android/dictionnaire.json")


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
    chemin_appris = A.DONNEES / "commandes_apprises.yaml"
    if chemin_appris.exists() and not EXEMPLE:
        texte_appris = chemin_appris.read_text(encoding="utf-8")
        lignes_appris = texte_appris.splitlines()
        for cmd in (yaml.safe_load(texte_appris) or {}).get("apprises") or []:
            cle = normaliser(cmd["phrase"])
            if cle and cle not in vus:
                vus.add(cle)
                actions = cmd["action"] if isinstance(cmd["action"], list) else [cmd["action"]]
                formes.append([cle, len(modeles)])
                modeles.append({"actions": actions, "reponse": cmd.get("reponse", "C'est fait."),
                                "source": "commandes_apprises.yaml", "appris": True,
                                "ligne": numero_ligne(lignes_appris, cmd["phrase"]), "motif": cmd["phrase"]})
    # Pour le LLM sur l'appareil (0.13.0) : même vue que le LLM des serveurs (appareils renommés,
    # masqués, notes) et même liste blanche de services.
    # L'exemple ne porte ni version ni date : il ne change que si son dictionnaire change.
    sortie = {"version": "exemple" if EXEMPLE else A.VERSION,
              "genere_le": "exemple" if EXEMPLE else time.strftime("%Y-%m-%d %H:%M"), "modeles": modeles, "formes": formes,
              "llm": donnees.get("llm") or {},
              # « Ma chambre » selon la personne qui parle (21/10/2026), appliqué par DictionnaireLocal.Personnes.
              "personnes": donnees.get("personnes") or {},
              "services_permis": {d: sorted(s) for d, s in A.SERVICES_PERMIS.items()}}
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(sortie, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(formes)} formes exportées vers {SORTIE} ({SORTIE.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
