"""Banc des actions physiques : la phrase passe par l'assistant, puis l'état réel est relu dans HA.

Périmètre fixé le 11/10/2026 : les deux ampoules du séjour seulement.
Le LLM est verrouillé sur ces deux entités, toute autre cible est refusée sans être envoyée.
Les intentions de HA ne sont testées que sur ces deux ampoules nommées.
À la fin, chaque ampoule retrouve son état de départ.

Usage : python poc/outils/banc_actions.py
Résultats : poc/journal/banc_actions.csv (une ligne par cas, version de l'assistant comprise).
"""
import csv, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
import assistant as A  # noqa: E402

# Les deux lumières du banc (appareils.lumieres_banc de maison.json) : celle du salon, puis la lampe de la télé.
SALON, LAMPE = (list(A.APPAREILS.get("lumieres_banc") or []) + ["", ""])[:2]
PERIMETRE = {SALON, LAMPE}

# (voie forcée, phrase, entité vérifiée, état attendu, luminosité attendue en % ou None)
CAS = [
    ("auto", "Allume la lumière du salon", SALON, "on", None),
    ("auto", "Éteins la lumière du salon", SALON, "off", None),
    ("auto", "Est-ce que tu peux allumer la lampe de la télé ?", LAMPE, "on", None),
    ("auto", "Éteins la lampe de la télé s'il te plaît", LAMPE, "off", None),
    ("ha", "Allume Lampe TV", LAMPE, "on", None),
    ("ha", "Éteins Lampe TV", LAMPE, "off", None),
    ("ha", "Allume Salon", SALON, "on", None),
    ("ha", "Éteins Salon", SALON, "off", None),
    ("llm", "Il fait trop sombre près de la télé", LAMPE, "on", None),
    ("llm", "Mets la lampe de la télé à 30 % de luminosité", LAMPE, "on", 30),
    ("llm", "Éteins la lampe près de la télé", LAMPE, "off", None),
    ("llm", "Allume le salon à fond", SALON, "on", 100),
    ("llm", "Coupe la lumière du salon", SALON, "off", None),
]


class HAVerrouille(A.HomeAssistant):
    """Refuse toute action hors du périmètre du banc."""

    def service(self, domaine, service, entity_id=None, donnees=None):
        cibles = entity_id if isinstance(entity_id, list) else [entity_id]
        if not cibles or any(c not in PERIMETRE for c in cibles):
            return {"erreur": f"hors périmètre du banc : {entity_id}"}
        return super().service(domaine, service, entity_id, donnees)


def lire(ha, e):
    d = ha.client.get(f"{ha.url}/api/states/{e}").json()
    lum = d["attributes"].get("brightness")
    return d["state"], (round(lum / 5.55) if lum is not None else None)


def attendre(ha, e, etat, lum, delai=6.0):
    t0 = time.perf_counter()
    while True:
        lu = lire(ha, e)
        ok = lu[0] == etat and (lum is None or (lu[1] is not None and abs(lu[1] - lum) <= 5))
        if ok or time.perf_counter() - t0 > delai:
            return ok, lu, time.perf_counter() - t0
        time.sleep(0.2)


def main():
    cfg = A.charger_env()
    assistant = A.Assistant(cfg, avec_audio=False)
    ha = HAVerrouille(cfg["ha_url"], cfg["ha_token"])
    ha.vue_llm = assistant.dico.llm
    assistant.ha = assistant.cerveau.ha = ha
    depart = {e: lire(ha, e) for e in PERIMETRE}
    print(f"Banc des actions, assistant v{A.VERSION}. Départ : {depart}\n")
    sortie = A.ICI / "journal" / "banc_actions.csv"
    sortie.parent.mkdir(exist_ok=True)
    neuf = not sortie.exists()
    reussis = 0
    # Luminosité mémorisée par chaque ampoule, relevée au premier allumage par le dictionnaire
    # ou HA (avant que le LLM ne la change), puis remise à la fin.
    memoire = {}
    with open(sortie, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        if neuf:
            w.writerow(["horodatage", "version", "voie_forcee", "phrase", "voie_reelle", "reponse",
                        "actions", "entite", "attendu", "lu", "ok", "cerveau_s", "effet_s"])
        for voie, phrase, e, etat, lum in CAS:
            t = time.perf_counter()
            if voie == "auto":
                avant_journal = phrase
                reponse = assistant.traiter(phrase)
                reelle, actions = "auto (voir ligne ci-dessus)", ""
            elif voie == "ha":
                compris, reponse, code = ha.conversation(phrase)
                reelle, actions = f"ha ({'compris' if compris else code})", ""
            else:
                assistant.cerveau.historique = []
                reponse, liste = assistant.cerveau.repondre(phrase)
                reelle, actions = "llm", " | ".join(liste)
            t_cerveau = time.perf_counter() - t
            ok, lu, t_effet = attendre(ha, e, etat, lum)
            reussis += ok
            if voie != "llm" and lu[0] == "on" and e not in memoire:
                memoire[e] = lu[1]
            attendu = etat + (f" {lum} %" if lum else "")
            print(f"{'OK ' if ok else 'ÉCHEC'} [{voie}] {phrase}\n      réponse : {reponse}"
                  + (f"\n      actions : {actions}" if actions else "")
                  + f"\n      {e} attendu {attendu}, lu {lu[0]} {lu[1] if lu[1] is not None else ''}"
                  f" (cerveau {t_cerveau:.2f} s, effet {t_effet:.2f} s)\n")
            w.writerow([datetime.now().isoformat(timespec="seconds"), A.VERSION, voie, phrase, reelle,
                        reponse, actions, e, attendu, f"{lu[0]} {lu[1]}", ok,
                        f"{t_cerveau:.2f}", f"{t_effet:.2f}"])
            time.sleep(0.5)
    for e, (etat, lum) in depart.items():  # remise en état, luminosité mémorisée comprise
        cible = lum or memoire.get(e)
        if cible:
            ha.client.post(f"{ha.url}/api/services/light/turn_on",
                           json={"entity_id": e, "brightness_pct": cible})
            time.sleep(1.0)
        if etat == "off":
            ha.client.post(f"{ha.url}/api/services/light/turn_off", json={"entity_id": e})
    time.sleep(1.5)
    print(f"Luminosités remises : {memoire}")
    print(f"Résultat : {reussis}/{len(CAS)} réussis. État final : { {e: lire(ha, e) for e in PERIMETRE} }")


if __name__ == "__main__":
    main()
