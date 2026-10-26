"""Actions « dynamiques » de commandes.yaml : celles dont le service dépend de l'état d'un appareil (S-L4, 0.44.0).

Une action ordinaire de commandes.yaml porte un `service`. Une action dynamique porte à la place une clé
`dynamique` et se résout en actions ordinaires APRÈS lecture de l'état des appareils, jamais avant. Ce que
cette résolution produit passe ensuite par le contrôle habituel (acces.controler_service, securite.verifier,
et leur pendant Kotlin Securite.verifier) exactement comme une action écrite à la main : rien ici ne
contourne ni n'affaiblit la sécurité en dur.

Deux types :

  selon_etat   « monte » vise le volume si la télé est allumée, la lumière sinon.
               {dynamique: selon_etat, entite: media_player.tele_salon, etats: [on, playing],
                alors: {action ou liste}, sinon: {action ou liste, facultatif}, reponse_vide: "..."}
               L'entité dans l'un des `etats` donne `alors`, tout autre état (éteinte, indisponible, illisible)
               donne `sinon`. Sans `sinon`, rien n'est fait et `reponse_vide` est dite.

  kelvin_pas   « plus chaud », « plus froid » : un pas de couleur de lumière, borné par chaque lampe.
               {dynamique: kelvin_pas, entity_id: light.x ou [light.x, ...], pas: -500, reponse_vide: "..."}
               Chaque lampe allumée en blanc réglable (color_temp_kelvin lu) reçoit son propre
               light.turn_on, de kelvin + pas ramené entre ses min_color_temp_kelvin et max_color_temp_kelvin.
               Une lampe éteinte, en couleur ou déjà à la borne est laissée telle quelle.

Même logique côté tablette : android/.../CommandesDynamiques.kt. Cas communs aux deux langages :
poc/tests/cas_dynamique.json (test_commandes_dynamiques.py, CommandesDynamiquesTest.kt).
"""

KELVIN_MIN_DEFAUT = 2700
KELVIN_MAX_DEFAUT = 6500
REPONSE_VIDE_DEFAUT = "Je n'ai rien à régler pour l'instant."


def est_dynamique(action):
    return isinstance(action, dict) and "dynamique" in action


def _en_liste(valeur):
    if valeur is None:
        return []
    return list(valeur) if isinstance(valeur, (list, tuple)) else [valeur]


def _cibles(valeur):
    if isinstance(valeur, str):
        return [c.strip() for c in valeur.split(",") if c.strip()]
    return [c for c in _en_liste(valeur) if isinstance(c, str)]


def entites_lues(actions):
    """Entités dont l'état est nécessaire pour résoudre ces actions, sans doublon et dans l'ordre."""
    lues = []
    for a in actions:
        if not est_dynamique(a):
            continue
        if a.get("dynamique") == "selon_etat":
            candidates = [a.get("entite")]
        elif a.get("dynamique") == "kelvin_pas":
            candidates = _cibles(a.get("entity_id"))
        else:
            candidates = []
        for e in candidates:
            if isinstance(e, str) and e and e not in lues:
                lues.append(e)
    return lues


def _entier(valeur):
    """Un nombre lu dans les attributs de HA (int, float ou texte), ou None."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float)):
        return int(round(valeur))
    if isinstance(valeur, str):
        try:
            return int(round(float(valeur)))
        except ValueError:
            return None
    return None


def _nom_etat(valeur):
    """État écrit dans la liste `etats` d'un YAML : `on` et `off` non cités y deviennent des booléens (YAML 1.1),
    on les ramène à leur nom d'état Home Assistant."""
    if valeur is True:
        return "on"
    if valeur is False:
        return "off"
    return str(valeur)


def _kelvin_pas(action, etats):
    pas = _entier(action.get("pas")) or 0
    actions = []
    for e in _cibles(action.get("entity_id")):
        etat = etats.get(e)
        if not isinstance(etat, dict) or etat.get("state") != "on":
            continue
        attributs = etat.get("attributes") if isinstance(etat.get("attributes"), dict) else {}
        kelvin = _entier(attributs.get("color_temp_kelvin"))
        if kelvin is None:
            continue  # lampe en couleur : « plus chaud » n'a pas de sens, on ne la touche pas
        kmin = _entier(attributs.get("min_color_temp_kelvin")) or KELVIN_MIN_DEFAUT
        kmax = _entier(attributs.get("max_color_temp_kelvin")) or max(KELVIN_MAX_DEFAUT, kmin + 1)
        nouveau = max(kmin, min(kmax, kelvin + pas))
        if nouveau != kelvin:
            actions.append({"service": "light.turn_on", "entity_id": e, "color_temp_kelvin": nouveau})
    return actions


def resoudre(action, etats):
    """Actions ordinaires qui répondent à une action dynamique, d'après `etats` (entité -> objet d'état de HA,
    {"state": ..., "attributes": {...}}, ou None quand l'état n'a pas pu être lu).
    Renvoie (actions, réponse à dire quand il n'y en a aucune)."""
    vide = action.get("reponse_vide") or REPONSE_VIDE_DEFAUT
    genre = action.get("dynamique")
    if genre == "selon_etat":
        etat = etats.get(action.get("entite"))
        courant = etat.get("state") if isinstance(etat, dict) else None
        permis = [_nom_etat(e) for e in _en_liste(action.get("etats"))]
        choisies = action.get("alors") if courant in permis else action.get("sinon")
        return [dict(a) for a in _en_liste(choisies) if isinstance(a, dict)], vide
    if genre == "kelvin_pas":
        return _kelvin_pas(action, etats), vide
    return [], vide


def resoudre_toutes(actions, etats):
    """Remplace chaque action dynamique de la liste par ses actions ordinaires, les autres passent telles quelles.
    Renvoie (actions, réponse à dire si la liste est vide alors qu'elle contenait une action dynamique, sinon None)."""
    sortie, vide, dynamique = [], None, False
    for a in actions:
        if est_dynamique(a):
            dynamique = True
            resolues, vide = resoudre(a, etats)
            sortie.extend(resolues)
        else:
            sortie.append(a)
    return sortie, (vide if dynamique and not sortie else None)
