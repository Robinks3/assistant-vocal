"""Médiane et 95e centile des latences par voie et par étape, lus dans journal/latences.csv.

Idée reprise d'un projet d'inspiration (scripts/mesures.ts) : suivre la latence ressentie par étape plutôt que
d'en juger à l'oreille. Les commandes en essai comptent aussi (elles mesurent le même chemin).
Usage : python poc/outils/mesures.py [--depuis 0.17.0] [--fichier chemin/latences.csv]"""
import argparse, csv, sys
from collections import defaultdict
from pathlib import Path


def centile(valeurs, p):
    v = sorted(valeurs)
    if not v:
        return float("nan")
    k = (len(v) - 1) * p / 100
    bas = int(k)
    haut = min(bas + 1, len(v) - 1)
    return v[bas] + (v[haut] - v[bas]) * (k - bas)


def version(texte):
    try:
        return tuple(int(x) for x in texte.split("."))
    except ValueError:
        return (0,)


def categorie(voie):
    for prefixe, nom in (("dictionnaire", "dictionnaire"), ("ha", "Assist de HA"), ("llm", "LLM"),
                         ("refus", "refus de sécurité"), ("rien compris", "rien compris"),
                         ("essai", "essai hors dico")):
        if voie.startswith(prefixe):
            return nom
    return (voie.split(" (")[0] or "autre")[:19]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--depuis", default="0.0.0", help="version minimale prise en compte")
    p.add_argument("--fichier", default=str(Path(__file__).resolve().parents[1] / "journal" / "latences.csv"))
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    groupes = defaultdict(lambda: defaultdict(list))
    with open(a.fichier, encoding="utf-8", newline="") as f:
        for ligne in csv.DictReader(f, delimiter=";"):
            if version(ligne["version"]) < version(a.depuis):
                continue
            g = groupes[categorie(ligne["voie"])]
            for etape in ("stt_s", "cerveau_s", "tts_s", "total_s"):
                try:
                    g[etape].append(float(ligne[etape]))
                except (ValueError, KeyError):
                    pass
    print(f"{'voie':<20}{'n':>5}  " + "  ".join(f"{e[:-2]:>17}" for e in ("stt_s", "cerveau_s", "tts_s", "total_s")))
    print(f"{'':<20}{'':>5}  " + "  ".join(f"{'médiane / p95':>17}" for _ in range(4)))
    for nom, g in sorted(groupes.items(), key=lambda kv: -len(kv[1]["total_s"])):
        cases = []
        for etape in ("stt_s", "cerveau_s", "tts_s", "total_s"):
            v = g[etape]
            cases.append(f"{centile(v, 50):7.2f} / {centile(v, 95):6.2f}" if v else f"{'-':>17}")
        print(f"{nom:<20}{len(g['total_s']):>5}  " + "  ".join(f"{c:>17}" for c in cases))


if __name__ == "__main__":
    main()
