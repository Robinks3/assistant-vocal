"""Test guidé à la voix : l'utilisateur lit les phrases affichées, le script vérifie l'effet réel dans HA.

Chaque phrase passe par toute la chaîne (micro, Canary, dictionnaire, HA, LLM, Piper) puis l'état
de l'appareil est relu. Périmètre : les deux ampoules du séjour et la télé. La télé est mise en
sourdine dès qu'elle s'allume. À la fin, tout est remis comme au départ.

Usage :
  python poc/outils/test_voix.py           actions réelles
  python poc/outils/test_voix.py --essai   rien n'est exécuté, on vérifie seulement la compréhension
Pendant le test : Entrée = dire la phrase, r + Entrée = recommencer la phrase, p + Entrée = passer,
q + Entrée = arrêter. Résultats : poc/journal/test_voix.csv
"""
import argparse, csv, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistant as A  # noqa: E402
from dictionnaire import normaliser  # noqa: E402

# Lumières du banc et télé de la configuration de la maison (appareils de maison.json).
SALON, LAMPE = (list(A.APPAREILS.get("lumieres_banc") or []) + ["", ""])[:2]
TELE = A.TELE
PERIMETRE = {SALON, LAMPE, TELE}

# (phrase à dire, entité vérifiée, état attendu)
PHRASES = [
    ("Allume la lumière du salon", SALON, "on"),
    ("Éteins la lumière du salon", SALON, "off"),
    ("Est-ce que tu peux allumer la lampe de la télé ?", LAMPE, "on"),
    ("Éteins la lampe de la télé s'il te plaît", LAMPE, "off"),
    ("Allume la télé", TELE, "on"),
    ("Éteins la télé", TELE, "off"),
    ("Il fait trop sombre près de la télé", LAMPE, "on"),
    ("Coupe la lumière près de la télé", LAMPE, "off"),
    ("Mets la lampe de la télé à 30 %", LAMPE, "on"),
    ("Merci, tu peux éteindre la lampe de la télé maintenant", LAMPE, "off"),
]


class HAVerrouille(A.HomeAssistant):
    """Le LLM ne peut agir que sur les appareils du test."""

    def service(self, domaine, service, entity_id=None, donnees=None):
        cibles = entity_id if isinstance(entity_id, list) else [entity_id]
        if not cibles or any(c not in PERIMETRE for c in cibles):
            return {"erreur": f"hors périmètre du test : {entity_id}"}
        return super().service(domaine, service, entity_id, donnees)


def lire(ha, e):
    d = ha.client.get(f"{ha.url}/api/states/{e}").json()
    return d["state"], d["attributes"].get("brightness")


def attendre(ha, e, attendu, delai=8.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < delai:
        etat = lire(ha, e)[0]
        if etat == attendu:
            if e == TELE and attendu == "on":  # sourdine dès que la télé démarre
                ha.client.post(f"{ha.url}/api/services/media_player/volume_mute",
                               json={"entity_id": TELE, "is_volume_muted": True})
            return True, time.perf_counter() - t0
        time.sleep(0.1)
    return False, None


def remettre(ha, depart, memoire):
    for e, (etat, lum) in depart.items():
        d = e.split(".")[0]
        if e.startswith("light.") and (lum or memoire.get(e)):
            ha.client.post(f"{ha.url}/api/services/light/turn_on",
                           json={"entity_id": e, "brightness": lum or memoire[e]})
            time.sleep(1)
        if etat == "off" and lire(ha, e)[0] != "off":
            ha.client.post(f"{ha.url}/api/services/{d}/turn_off", json={"entity_id": e})
    time.sleep(1.5)


def main():
    p = argparse.ArgumentParser(description="Test guidé à la voix")
    p.add_argument("--essai", action="store_true", help="rien n'est exécuté")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    A.activer_couleurs()
    print(f"Test à la voix, assistant v{A.VERSION} ({'ESSAI, rien ne bouge' if a.essai else 'actions réelles'})")
    cfg = A.charger_env()
    assistant = A.Assistant(cfg, essai=a.essai)
    ha = HAVerrouille(cfg["ha_url"], cfg["ha_token"])
    ha.essai, ha.vue_llm = a.essai, assistant.dico.llm
    assistant.cerveau.ha = ha
    oreille = A.Oreille(cfg["micro"])
    print("  calibrage du bruit ambiant, silence une seconde...")
    oreille.calibrer()
    print(f"  seuil de parole {oreille.seuil:.4f} : ta voix doit dépasser le | du vumètre.\n")
    depart = {e: lire(ha, e) for e in PERIMETRE}
    memoire = {e: lum for e, (etat, lum) in depart.items() if lum}
    sortie = A.ICI / "journal" / "test_voix.csv"
    sortie.parent.mkdir(exist_ok=True)
    neuf = not sortie.exists()
    bilan = []
    try:
        with open(sortie, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            if neuf:
                w.writerow(["horodatage", "version", "essai", "phrase_demandee", "entendu", "transcription_exacte",
                            "reponse", "entite", "attendu", "effet_ok", "stt_s", "cerveau_s", "effet_s"])
            i = 0
            while i < len(PHRASES):
                phrase, e, attendu = PHRASES[i]
                print(f"{A.CYAN}[{i + 1}/{len(PHRASES)}] Dites : « {phrase} »{A.RAZ}")
                choix = input(f"{A.GRIS}  Entrée pour parler (p = passer, q = arrêter) {A.RAZ}").strip().lower()
                if choix == "q":
                    break
                if choix == "p":
                    i += 1
                    continue
                assistant.voix.bip(880)
                signal = oreille.ecouter_phrase()
                if signal is None:
                    print(f"  {A.GRIS}rien entendu, on recommence{A.RAZ}\n")
                    continue
                assistant.voix.bip(440)
                t = time.perf_counter()
                texte = assistant.stt.transcrire(signal)
                t_stt = time.perf_counter() - t
                exact = normaliser(texte) == normaliser(phrase)
                print(f"  entendu : {texte}" + ("" if exact else f"  {A.JAUNE}(différent du texte){A.RAZ}"))
                t = time.perf_counter()
                reponse = assistant.traiter(texte, t_stt)
                t_cerveau = time.perf_counter() - t
                if a.essai:
                    ok, t_effet = None, None
                    print(f"  {A.GRIS}essai : effet non vérifié{A.RAZ}")
                else:
                    ok, t_effet = attendre(ha, e, attendu)
                    if e.startswith("light.") and lire(ha, e)[1] and e not in memoire and attendu == "on":
                        memoire[e] = lire(ha, e)[1]
                    print(f"  {A.VERT + 'OK' if ok else A.JAUNE + 'ÉCHEC'}{A.RAZ} : {e} attendu {attendu}, "
                          f"lu {lire(ha, e)[0]}" + (f" en {t_effet:.1f} s" if ok else ""))
                bilan.append(ok)
                w.writerow([datetime.now().isoformat(timespec="seconds"), A.VERSION, a.essai, phrase, texte, exact,
                            reponse, e, attendu, ok, f"{t_stt:.2f}", f"{t_cerveau:.2f}",
                            f"{t_effet:.2f}" if t_effet else ""])
                f.flush()
                if input(f"{A.GRIS}  Entrée = phrase suivante, r = refaire celle-ci {A.RAZ}").strip().lower() != "r":
                    i += 1
                print()
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
    finally:
        if not a.essai:
            print("Remise en état des appareils...")
            remettre(ha, depart, memoire)
        reussis = sum(1 for b in bilan if b)
        print(f"Bilan : {reussis}/{len(bilan)} effets confirmés" if not a.essai else f"{len(bilan)} phrases testées")
        print(f"État final : { {e: lire(ha, e)[0] for e in PERIMETRE} }. Détail : {sortie}")


if __name__ == "__main__":
    main()
