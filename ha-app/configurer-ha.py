"""Transfère le dictionnaire de l'assistant dans Home Assistant (accord du 12/10/2026).

1. Alias d'appareils (« télé », « lampe de la télé »...), ajoutés à ceux qui existent.
2. Exposition à Assist des appareils du dictionnaire qui ne l'étaient pas.
3. Une automatisation « <nom de l'assistant> : dictionnaire » (id jarvis_dictionnaire) avec un déclencheur vocal
   par commande de commandes.yaml (dossier de configuration) et par phrase apprise, et les mêmes actions et réponses.
   Speech-to-Phrase apprend les phrases des déclencheurs vocaux : il reconnaît alors toutes les
   commandes du propriétaire, et l'Assist natif de HA les exécute aussi. Le serveur de l'assistant passe toujours
   par son propre dictionnaire d'abord, donc rien ne s'exécute deux fois.
Les nombres sont écrits en lettres (Speech-to-Phrase ne sait pas prononcer « 3 »), les variantes
contenant d'autres signes (« disney+ ») sont retirées des phrases vocales.

Usage : python ha-app/configurer-ha.py [--essai]   (--essai : affiche sans rien envoyer)
"""
import asyncio, json, re, sys
from pathlib import Path

import yaml

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent / "poc"))
sys.path.insert(0, str(ICI.parent / "poc" / "outils"))
import assistant as A  # noqa: E402
import ha_registre as R  # noqa: E402

# Alias d'appareils et entités à exposer à Assist : section ha de maison.json.
ALIAS = dict((A.maison.CONFIG.get("ha") or {}).get("alias") or {})
A_EXPOSER = list((A.maison.CONFIG.get("ha") or {}).get("exposer") or [])
CHIFFRES = {"1": "un", "2": "deux", "3": "trois", "4": "quatre", "5": "cinq"}


def nettoyer_alternatives(texte):
    """Retire des groupes (a|b) et [a|b] les variantes avec chiffres ou signes non prononçables."""
    def groupe(m):
        ouvrant, interieur, fermant = m.group(1), m.group(2), m.group(3)
        alts = [a for a in interieur.split("|") if re.fullmatch(r"[\w\s'’-]*", a) and not re.search(r"\d", a)]
        alts = alts or [CHIFFRES.get(a.strip(), a) for a in interieur.split("|")]
        return ouvrant + "|".join(alts) + fermant
    precedent = None
    while precedent != texte:
        precedent = texte
        texte = re.sub(r"([\(\[])([^\(\)\[\]]*)([\)\]])", groupe, texte)
    return texte


def nettoyer_motif(motif):
    """Variantes de premier niveau d'une valeur d'emplacement, sans chiffres ni signes (« disney+ »)."""
    from dictionnaire import _decouper
    garde = []
    for alt in _decouper(motif):
        alt = CHIFFRES.get(alt.strip(), alt)
        if re.fullmatch(r"[\w\s'’\[\]-]*", alt) and not re.search(r"\d", alt):
            garde.append(alt)
    return "|".join(garde)


def declencheurs(donnees, apprises):
    """Liste de (phrases, actions, réponse) prêtes pour HA, emplacements développés valeur par valeur."""
    sortie = []
    emplacements = donnees.get("emplacements") or {}
    for cmd in donnees["commandes"]:
        actions = cmd["action"] if isinstance(cmd["action"], list) else [cmd["action"]]
        noms = sorted({n for p in cmd["phrases"] for n in re.findall(r"\{(\w+)\}", p)})
        if not noms:
            sortie.append(([nettoyer_alternatives(p) for p in cmd["phrases"]], actions, cmd.get("reponse")))
            continue
        if len(noms) > 1:  # deux emplacements (luminosité) : pas transférés à HA, l'assistant les traite seul
            continue
        nom = noms[0]
        for motif, valeur in emplacements[nom].items():
            motif = nettoyer_motif(motif)
            if not motif:
                continue
            phrases = [nettoyer_alternatives(p.replace("{" + nom + "}", f"({motif})")) for p in cmd["phrases"]]
            acts = [{k: (v.replace("{" + nom + "}", valeur) if isinstance(v, str) else v) for k, v in a.items()}
                    for a in actions]
            sortie.append((phrases, acts, cmd.get("reponse")))
    for cmd in apprises:
        actions = cmd["action"] if isinstance(cmd["action"], list) else [cmd["action"]]
        phrase = re.sub(r"[^\w\s'’-]", " ", cmd["phrase"]).strip()
        sortie.append(([phrase], actions, cmd.get("reponse")))
    return sortie


def action_ha(a):
    domaine_service = a["service"]
    donnees = {k: v for k, v in a.items() if k not in ("service", "entity_id")}
    action = {"action": domaine_service}
    if "entity_id" in a:
        action["target"] = {"entity_id": a["entity_id"]}
    if donnees:
        action["data"] = donnees
    return action


def sans_refus(liste):
    """Retire les commandes que la sécurité en dur refuse (occupant protégé, « all »), jugées en plein jour.
    Les actions gardées reprennent les données telles que la sécurité les laisse passer : un volume au-dessus
    du plafond réglé (securite.plafond_volume) part plafonné dans l'automatisation."""
    import securite
    from datetime import datetime
    midi = datetime(2026, 1, 1, 14)
    garde = []
    for phrases, actions, reponse in liste:
        verifiees, refus = [], []
        for a in actions:
            donnees = {k: v for k, v in a.items() if k != "service"}
            refus.append(securite.verifier(a["service"], donnees, midi))
            verifiees.append({"service": a["service"], **donnees})
        if any(refus):
            print(f"  retiré (sécurité) : {phrases[0]}")
        else:
            garde.append((phrases, verifiees, reponse))
    return garde


def automatisation(liste):
    triggers, choix = [], []
    liste = sans_refus(liste)
    for i, (phrases, actions, reponse) in enumerate(liste):
        ident = f"jarvis_{i:03d}"
        triggers.append({"trigger": "conversation", "command": phrases, "id": ident})
        choix.append({"conditions": [{"condition": "trigger", "id": ident}],
                      "sequence": [action_ha(a) for a in actions]
                      + [{"set_conversation_response": reponse or "C'est fait."}]})
    return {"alias": f"{A.maison.NOM_ASSISTANT} : dictionnaire",
            "description": "Généré par ASSISTANT-VOCAL/ha-app/configurer-ha.py depuis commandes.yaml et les "
                           "phrases apprises. Ne pas modifier à la main : relancer le script.",
            "mode": "queued", "triggers": triggers, "conditions": [], "actions": [{"choose": choix}]}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    essai = "--essai" in sys.argv
    donnees = yaml.safe_load(A.maison.chemin("commandes.yaml").read_text(encoding="utf-8"))
    chemin_appris = A.DONNEES / "commandes_apprises.yaml"
    apprises = (yaml.safe_load(chemin_appris.read_text(encoding="utf-8")) or {}).get("apprises", []) \
        if chemin_appris.exists() else []
    auto = automatisation(declencheurs(donnees, apprises))
    print(f"automatisation : {len(auto['triggers'])} déclencheurs vocaux")
    for t in auto["triggers"][:3]:
        print("  exemple :", t["command"][:2])
    if essai:
        apercu = A.maison.chemin("genere/ha/jarvis_dictionnaire.apercu.json")
        apercu.parent.mkdir(parents=True, exist_ok=True)
        apercu.write_text(json.dumps(auto, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"essai : rien envoyé, aperçu dans {apercu}")
        return
    # 1 et 2 : alias (fusionnés avec l'existant) et exposition à Assist
    lectures = asyncio.run(R.session([{"type": "config/entity_registry/get", "entity_id": e} for e in ALIAS]))
    commandes = []
    for e, lu in zip(ALIAS, lectures):
        existants = list((lu.get("result") or {}).get("aliases") or [])
        nouveaux = existants + [x for x in ALIAS[e] if x not in existants]
        commandes.append({"type": "config/entity_registry/update", "entity_id": e, "aliases": nouveaux})
    commandes.append({"type": "homeassistant/expose_entity", "assistants": ["conversation"],
                      "entity_ids": A_EXPOSER, "should_expose": True})
    for c, r in zip(commandes, asyncio.run(R.session(commandes))):
        print(f"  {c['type'].split('/')[-1]} {c.get('entity_id', A_EXPOSER)} : {'ok' if r.get('success') else r.get('error')}")
    # 3 : automatisation
    cfg = A.charger_env()
    ha = A.HomeAssistant(cfg["ha_url"], cfg["ha_token"])
    r = ha.client.post(f"{ha.url}/api/config/automation/config/jarvis_dictionnaire", json=auto)
    print("automatisation :", r.status_code, r.text[:200])


if __name__ == "__main__":
    main()
