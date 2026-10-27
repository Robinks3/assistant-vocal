"""Mesures par pièce (S-L6) : température, humidité, CO2 et particules fines lues sur les capteurs de Home Assistant.

Logique pure, sans réseau, partagée avec l'appli Android (Mesures.kt) par les mêmes cas (tests/cas_mesures.json).

Découverte : un seul gabarit Jinja posté sur /api/template parcourt les capteurs de Home Assistant et garde ceux
dont la classe d'appareil est connue (temperature, humidity, carbon_dioxide, pm25, pm10, aqi,
volatile_organic_compounds, plus illuminance pour savoir qu'une pièce n'a que de la luminosité). Aucune entité
n'est écrite en dur. La zone d'un capteur est celle de l'entité, sinon celle de son appareil.

Correspondance : la clé « correspondance_pieces » de maison.json (remplie à la main, décision D10) relie chaque
pièce de la vue 3D (carte/pieces.json) à une ou plusieurs zones de Home Assistant. Aucune déduction automatique.

Seuils et mots (note de conception lampes-tele, section 8.2). Une valeur sous le premier seuil est « bon », puis
chaque seuil est inclus dans la classe du dessous : CO2 correct de 800 à 1000 ppm compris, médiocre au-dessus de 1000
jusqu'à 1500 compris, mauvais au-dessus de 1500. Même règle pour les particules PM2.5 (9, 35,4, 55,4 µg/m3).
Température : frais sous 19, agréable de 19 à 24 compris, chaud au-dessus. Le chiffre reste affiché avec le mot.
L'air d'une pièce prend le pire des deux mots (CO2, PM2.5). « À aérer » dès médiocre.

Sécurité : une pièce dont une zone figure dans securite.zones_protegees (ou dont l'identifiant ou le nom est
protégé) ne montre aucune valeur, même si un capteur existe. Le gabarit écarte aussi ces zones dès Home Assistant,
pour que leurs valeurs ne sortent jamais de la maison. Le serveur ne passe ces zones que tant que le drapeau
PROTEGER_OCCUPANT est vrai (levée complète le 27/10/2026) : coupé, toutes les pièces montrent leurs mesures.
"""
import json
import math
from datetime import datetime, timezone

# ------------------------------------------------------------------ seuils, mots et couleurs
MOTS_AIR = ("bon", "correct", "médiocre", "mauvais")
COULEURS_AIR = ("#D4E6C8", "#EDD48A", "#EE9A45", "#D6503A")
COULEUR_GRIS = "#9AA0A6"
SEUILS_CO2 = (800.0, 1000.0, 1500.0)
SEUILS_PM25 = (9.0, 35.4, 55.4)
SEUIL_FRAIS, SEUIL_CHAUD = 19.0, 24.0
# Au-delà de ce délai sans nouvelle valeur, une mesure n'est plus montrée ni colorée (8.3).
PEREMPTION_S = 2 * 3600

CLASSES_UTILES = ("temperature", "humidity", "carbon_dioxide", "pm25", "pm10", "aqi", "volatile_organic_compounds")
CLASSES_CONNUES = CLASSES_UTILES + ("illuminance",)
# Un appareil qui n'expose que la température et l'humidité est un thermomètre dédié, il l'emporte sur un capteur
# combiné (qui expose aussi une mesure d'air).
CLASSES_THERMOMETRE = ("temperature", "humidity")
ABSENTS = ("unavailable", "unknown", "none", "")

UNITES = {"carbon_dioxide": "ppm", "pm25": "µg/m3", "humidity": "%", "temperature": "°"}


def rang_air(valeur, seuils):
    """0 bon, 1 correct, 2 médiocre, 3 mauvais. Sous le premier seuil : bon. Un seuil appartient à la classe du dessous."""
    if valeur < seuils[0]:
        return 0
    if valeur <= seuils[1]:
        return 1
    if valeur <= seuils[2]:
        return 2
    return 3


def mot_co2(valeur):
    return MOTS_AIR[rang_air(valeur, SEUILS_CO2)]


def mot_pm25(valeur):
    return MOTS_AIR[rang_air(valeur, SEUILS_PM25)]


def mot_temperature(valeur):
    if valeur < SEUIL_FRAIS:
        return "frais"
    return "agréable" if valeur <= SEUIL_CHAUD else "chaud"


def couleur_air(rang):
    return COULEURS_AIR[rang]


def air_pire(rangs):
    """Mot, couleur et rang du pire des rangs donnés, ou None s'il n'y en a aucun."""
    rangs = [r for r in rangs if r is not None]
    if not rangs:
        return None
    r = max(rangs)
    return {"rang": r, "mot": MOTS_AIR[r], "couleur": COULEURS_AIR[r], "aerer": r >= 2}


def seuil_suivant(classe, valeur):
    """Phrase qui dit, en clair, où la mesure change de mot ('' si elle est déjà au pire). Classes carbon_dioxide et pm25."""
    seuils, unite = (SEUILS_CO2, "ppm") if classe == "carbon_dioxide" else (SEUILS_PM25, "µg/m3")
    r = rang_air(valeur, seuils)
    if r >= 3:
        return ""
    s = seuils[r]
    nombre = f"{s:g}".replace(".", ",")
    mot = MOTS_AIR[r + 1]
    return f"passe à {mot} dès {nombre} {unite}" if r == 0 else f"passe à {mot} au-dessus de {nombre} {unite}"


def arrondi(x):
    """Entier le plus proche, les demis vers le haut (même résultat qu'en Kotlin)."""
    return int(math.floor(x + 0.5))


# ------------------------------------------------------------------ découverte
_MODELE = """
{%- set classes = __CLASSES__ -%}
{%- set protegees = __PROTEGEES__ -%}
{%- set ns = namespace(a=[]) -%}
{%- for s in states.sensor if s.attributes.device_class in classes -%}
{%- set d = device_id(s.entity_id) or '' -%}
{%- set ze = area_id(s.entity_id) or '' -%}
{%- set za = (area_id(d) if d else '') or '' -%}
{%- if (ze or za) not in protegees and ze not in protegees and za not in protegees -%}
{%- set ns.a = ns.a + [{'id': s.entity_id, 'nom': s.name, 'classe': s.attributes.device_class, 'etat': s.state, 'unite': s.attributes.unit_of_measurement or '', 'zone': ze, 'zone_appareil': za, 'appareil': d, 'modifie': as_timestamp(s.last_reported or s.last_updated)}] -%}
{%- endif -%}
{%- endfor -%}
{{ {'maintenant': as_timestamp(now()), 'capteurs': ns.a} | tojson }}
"""


def gabarit(zones_protegees=()):
    """Gabarit de découverte à poster sur /api/template. Les zones protégées en sont écartées dès Home Assistant."""
    protegees = sorted({str(z).lower() for z in zones_protegees})
    return (_MODELE.replace("__CLASSES__", json.dumps(list(CLASSES_CONNUES)))
            .replace("__PROTEGEES__", json.dumps(protegees)).strip())


def lire_releve(texte):
    """Relevé {'maintenant', 'capteurs'} à partir de la réponse du gabarit. None si elle est illisible."""
    try:
        r = json.loads(texte) if isinstance(texte, (str, bytes)) else texte
    except ValueError:
        return None
    if not isinstance(r, dict) or not isinstance(r.get("capteurs"), list):
        return None
    return r


def correspondance(config):
    """Correspondance pièce de la vue 3D vers zones de Home Assistant, lue dans [config] (maison.json).
    Valeur : une zone ou une liste de zones. Zones en minuscules, entrées vides ignorées."""
    brute = config.get("correspondance_pieces") if isinstance(config, dict) else None
    sortie = {}
    if not isinstance(brute, dict):
        return sortie
    for piece, zones in brute.items():
        if str(piece).startswith("_"):
            continue
        if isinstance(zones, str):
            zones = [zones]
        if not isinstance(zones, list):
            continue
        z = [str(x).strip().lower() for x in zones if str(x).strip()]
        if z:
            sortie[str(piece)] = z
    return sortie


# ------------------------------------------------------------------ calcul par pièce
def _nombre(etat):
    """Valeur numérique d'un état Home Assistant, ou None (indisponible, inconnu, texte, nan, infini)."""
    if etat is None or str(etat).strip().lower() in ABSENTS:
        return None
    try:
        v = float(str(etat).replace(",", "."))
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def heure_locale(horodatage, fuseau):
    """« 14 h 30 » : heure de [horodatage] (secondes Unix) dans [fuseau] (nom de zone, ou objet tzinfo)."""
    if isinstance(fuseau, str):
        try:
            from zoneinfo import ZoneInfo
            fuseau = ZoneInfo(fuseau)
        except Exception:
            fuseau = timezone.utc
    d = datetime.fromtimestamp(float(horodatage), fuseau)
    return f"{d.hour} h {d.minute:02d}"


def _zone_de(c):
    return str(c.get("zone") or c.get("zone_appareil") or "").lower()


def _moyenne(xs):
    return sum(xs) / len(xs)


def _lecture(capteurs, classe, maintenant, fuseau):
    """Mesure d'une classe parmi les capteurs de la pièce : le thermomètre dédié l'emporte, sinon la moyenne.
    Retourne None si aucun capteur de cette classe, sinon {'valeur': float|None, 'depuis': 'H h MM'|None}."""
    ceux = [c for c in capteurs if c.get("classe") == classe]
    if not ceux:
        return None
    bons = []
    for c in ceux:
        v = _nombre(c.get("etat"))
        age = maintenant - float(c.get("modifie") or 0)
        if v is not None and age <= PEREMPTION_S:
            bons.append((c, v))
    if not bons:
        derniere = max(float(c.get("modifie") or 0) for c in ceux)
        return {"valeur": None, "ts": derniere, "depuis": heure_locale(derniere, fuseau)}
    dedies = [v for c, v in bons if c.get("dedie")]
    return {"valeur": _moyenne(dedies if dedies else [v for _, v in bons]), "ts": None, "depuis": None}


def marquer_dedies(capteurs):
    """Pose c['dedie'] : vrai pour un capteur d'un appareil qui n'expose que température et humidité (thermomètre
    dédié). Partagé avec l'historique de l'air (historique_air.py) pour choisir les mêmes capteurs que la carte."""
    classes_par_appareil = {}
    for c in capteurs:
        if c.get("appareil"):
            classes_par_appareil.setdefault(c["appareil"], set()).add(c.get("classe"))
    for c in capteurs:
        cl = classes_par_appareil.get(c.get("appareil"))
        c["dedie"] = bool(cl) and cl <= set(CLASSES_THERMOMETRE)


def mesures_par_piece(releve, corresp, protegees, fuseau="UTC", noms=None):
    """Mesures de chaque pièce de [corresp] à partir du [releve] du gabarit.

    [protegees] : zones, pièces ou noms protégés (aucune valeur pour ces pièces). [noms] : nom lisible de chaque pièce
    (sinon l'identifiant). Retourne {identifiant de pièce: dict} avec les clés :
      statut        ok, protegee, aucun, sans_air, sans_thermometre ou absente
      texte         résumé d'une ligne (« 21°, air bon »), vide jamais
      couleur       couleur du mot de l'air (gris sans mesure d'air)
      temperature, humidite, co2, pm25   {valeur, mot, couleur, suivant} ou {valeur: None, depuis} ou None
      air           {mot, couleur, rang, aerer} ou None
      alerte        « Aère la pièce X, CO2 1200 ppm » dès médiocre, sinon ''
    """
    noms = noms or {}
    protegees = {str(z).lower() for z in protegees}
    maintenant = float(releve.get("maintenant") or 0)
    capteurs = [c for c in releve.get("capteurs") or [] if isinstance(c, dict)]
    marquer_dedies(capteurs)
    sortie = {}
    for piece, zones in corresp.items():
        nom = noms.get(piece) or piece
        if piece.lower() in protegees or str(nom).lower() in protegees or any(z in protegees for z in zones):
            sortie[piece] = _vide("protegee", "pièce protégée")
            continue
        ici = [c for c in capteurs if _zone_de(c) in zones]
        sortie[piece] = _piece(nom, ici, maintenant, fuseau)
    return sortie


def _vide(statut, texte):
    return {"statut": statut, "texte": texte, "couleur": COULEUR_GRIS, "temperature": None, "humidite": None,
            "co2": None, "pm25": None, "air": None, "alerte": ""}


def _piece(nom, capteurs, maintenant, fuseau):
    if not capteurs:
        return _vide("aucun", "pas de capteur")
    t = _lecture(capteurs, "temperature", maintenant, fuseau)
    h = _lecture(capteurs, "humidity", maintenant, fuseau)
    co2 = _lecture(capteurs, "carbon_dioxide", maintenant, fuseau)
    pm = _lecture(capteurs, "pm25", maintenant, fuseau)
    r = _vide("ok", "")
    if t:
        r["temperature"] = _mesure_t(t)
    if h:
        r["humidite"] = {"valeur": h["valeur"], "depuis": h["depuis"]}
    rangs, alertes = [], []
    for cle, lec, seuils, classe, etiquette in (("co2", co2, SEUILS_CO2, "carbon_dioxide", "CO2"),
                                                  ("pm25", pm, SEUILS_PM25, "pm25", "PM2.5")):
        if not lec:
            continue
        if lec["valeur"] is None:
            r[cle] = {"valeur": None, "depuis": lec["depuis"]}
            continue
        rang = rang_air(lec["valeur"], seuils)
        r[cle] = {"valeur": lec["valeur"], "mot": MOTS_AIR[rang], "couleur": COULEURS_AIR[rang],
                  "suivant": seuil_suivant(classe, lec["valeur"])}
        rangs.append(rang)
        if rang >= 2:
            alertes.append((rang, f"{etiquette} {arrondi(lec['valeur'])} {UNITES[classe]}"))
    air = air_pire(rangs)
    r["air"] = air
    if air:
        r["couleur"] = air["couleur"]
    if air and air["aerer"]:
        r["alerte"] = f"Aère la pièce {nom}, " + max(alertes)[1]
    temp_ok = bool(t and t["valeur"] is not None)
    air_ok = air is not None
    a_air = bool(co2 or pm)
    absentes = [x for x in (t, co2, pm) if x and x["valeur"] is None]
    depuis = heure_locale(max(x["ts"] for x in absentes), fuseau) if absentes else ""
    # Texte d'une ligne et statut, dans l'ordre de la section 8.3.
    if not t and not a_air:
        r["statut"], r["texte"] = "sans_thermometre", "pas de thermomètre"
    elif t and not a_air:
        r["statut"] = "sans_air"
        r["texte"] = (f"{arrondi(t['valeur'])}°" if temp_ok else f"mesure absente depuis {depuis}") + ", pas de capteur d'air"
    elif not temp_ok and not air_ok and t:
        r["statut"], r["texte"] = "absente", f"mesure absente depuis {depuis}"
    else:
        if temp_ok:
            parties = [f"{arrondi(t['valeur'])}°"]
        elif t:
            parties = [f"température absente depuis {heure_locale(t['ts'], fuseau)}"]
        else:
            parties = []
        if air_ok:
            parties.append(f"air {air['mot']}")
        else:
            parties.append("air absent depuis " + heure_locale(max(x["ts"] for x in (co2, pm) if x and x["ts"]), fuseau))
        if not t:
            parties.append("pas de thermomètre")
            r["statut"] = "sans_thermometre"
        r["texte"] = ", ".join(parties)
    return r


def _mesure_t(t):
    if t["valeur"] is None:
        return {"valeur": None, "depuis": t["depuis"]}
    return {"valeur": t["valeur"], "mot": mot_temperature(t["valeur"])}
