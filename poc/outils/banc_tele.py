"""Banc de la télé : allumer et éteindre par l'assistant, son coupé pour ne déranger personne.

Demande du 12/10/2026. La télé (appareils.tele de maison.json) sort le son sur ses
propres haut-parleurs et n'accepte la sourdine qu'une fois allumée : l'état est relu toutes les
0,1 s et la sourdine part dès qu'elle s'allume. L'enceinte du salon est aussi en sourdine
pendant tout le banc (appareils.musique.enceintes.salon), au cas où le son passerait par l'ARC. Tout est remis comme au départ.

Voies testées : dictionnaire et LLM (verrouillé sur la télé). Pas les intentions de HA : trois
entités portent le nom de la télé, dont deux lecteurs Music Assistant qui pourraient jouer.

Usage : python poc/outils/banc_tele.py
"""
import csv, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
import assistant as A  # noqa: E402

# La télé et l'enceinte du salon (appareils de maison.json).
TELE, ENCEINTE = A.TELE, (A.MUSIQUE_MAISON.get("enceintes") or {}).get("salon", "")


class HAVerrouille(A.HomeAssistant):
    def service(self, domaine, service, entity_id=None, donnees=None):
        cibles = entity_id if isinstance(entity_id, list) else [entity_id]
        if cibles != [TELE]:
            return {"erreur": f"hors périmètre du banc : {entity_id}"}
        return super().service(domaine, service, entity_id, donnees)


def etat(ha, e):
    d = ha.client.get(f"{ha.url}/api/states/{e}").json()
    return d["state"], d["attributes"].get("is_volume_muted")


def appeler(ha, service, **corps):
    d, s = service.split(".")
    return ha.client.post(f"{ha.url}/api/services/{d}/{s}", json=corps).status_code


def attendre_allumage(ha, t0, delai=40.0):
    """Sourdine dès que la télé passe à on. Renvoie (allumée, délai d'allumage, sourdine ok)."""
    while time.perf_counter() - t0 < delai:
        if etat(ha, TELE)[0] not in ("off", "unavailable", "unknown"):
            t_on = time.perf_counter() - t0
            for _ in range(10):  # la télé peut ignorer la première commande juste après le démarrage
                appeler(ha, "media_player.volume_mute", entity_id=TELE, is_volume_muted=True)
                time.sleep(1.0)
                if etat(ha, TELE)[1] is True:
                    return True, t_on, True
            return True, t_on, False
        time.sleep(0.1)
    return False, None, False


def attendre_extinction(ha, t0, delai=20.0):
    while time.perf_counter() - t0 < delai:
        if etat(ha, TELE)[0] == "off":
            return True, time.perf_counter() - t0
        time.sleep(0.2)
    return False, None


def main():
    cfg = A.charger_env()
    assistant = A.Assistant(cfg, avec_audio=False)
    ha = HAVerrouille(cfg["ha_url"], cfg["ha_token"])
    ha.vue_llm = assistant.dico.llm
    assistant.cerveau.ha = ha
    enceinte_depart = etat(ha, ENCEINTE)[1]
    tele_depart = etat(ha, TELE)[0]
    print(f"Banc télé, assistant v{A.VERSION}. Télé {tele_depart}, enceinte en sourdine : {enceinte_depart}")
    appeler(ha, "media_player.volume_mute", entity_id=ENCEINTE, is_volume_muted=True)
    time.sleep(2)  # l'état de l'enceinte met environ une seconde à remonter
    if etat(ha, ENCEINTE)[1] is not True:
        print("enceinte pas en sourdine, banc annulé pour ne déranger personne.")
        return
    print("enceinte Ray en sourdine : confirmé\n")

    cycles = [
        ("dictionnaire", lambda: assistant.traiter("Allume la télé"), lambda: assistant.traiter("Éteins la télé")),
        ("auto, phrases polies", lambda: assistant.traiter("Est-ce que tu peux allumer la télévision du séjour ?"),
         lambda: assistant.traiter("Merci, tu peux éteindre la télévision maintenant.")),
        ("llm", lambda: assistant.cerveau.repondre("J'aimerais regarder la télé")[0],
         lambda: assistant.cerveau.repondre("Tu peux couper la télévision ?")[0]),
    ]
    sortie = A.ICI / "journal" / "banc_tele.csv"
    neuf = not sortie.exists()
    reussis = total = 0
    try:
        with open(sortie, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            if neuf:
                w.writerow(["horodatage", "version", "voie", "commande", "reponse", "ok", "delai_s", "sourdine"])
            for voie, allumer, eteindre in cycles:
                assistant.cerveau.historique = []
                t0 = time.perf_counter()
                rep = allumer()
                ok, t_on, muet = attendre_allumage(ha, t0)
                total += 1
                reussis += ok
                print(f"{'OK ' if ok else 'ÉCHEC'} [{voie}] allumer : {rep}\n      allumée en "
                      f"{t_on if t_on is None else round(t_on, 1)} s, sourdine {'ok' if muet else 'NON CONFIRMÉE'}\n")
                w.writerow([A.maison.maintenant().strftime(A.maison.FORMAT_HORODATAGE), A.VERSION, voie, "allumer",
                            rep, ok, f"{t_on:.1f}" if t_on else "", muet])
                if not ok:
                    continue
                time.sleep(4)  # laisser la télé finir de démarrer
                t0 = time.perf_counter()
                rep = eteindre()
                ok, t_off = attendre_extinction(ha, t0)
                total += 1
                reussis += ok
                print(f"{'OK ' if ok else 'ÉCHEC'} [{voie}] éteindre : {rep}\n      éteinte en "
                      f"{t_off if t_off is None else round(t_off, 1)} s\n")
                w.writerow([A.maison.maintenant().strftime(A.maison.FORMAT_HORODATAGE), A.VERSION, voie, "éteindre",
                            rep, ok, f"{t_off:.1f}" if t_off else "", ""])
                time.sleep(3)
    finally:
        if etat(ha, TELE)[0] != "off" and tele_depart == "off":
            appeler(ha, "media_player.turn_off", entity_id=TELE)
            attendre_extinction(ha, time.perf_counter())
        appeler(ha, "media_player.volume_mute", entity_id=ENCEINTE, is_volume_muted=bool(enceinte_depart))
        for _ in range(30):  # l'état de l'enceinte peut mettre plus de 2 s à remonter dans HA
            if etat(ha, ENCEINTE)[1] == bool(enceinte_depart):
                break
            time.sleep(0.2)
        print(f"Résultat : {reussis}/{total}. Télé {etat(ha, TELE)[0]}, "
              f"enceinte en sourdine : {etat(ha, ENCEINTE)[1]} (départ : {enceinte_depart})")


if __name__ == "__main__":
    main()
