"""Dictionnaire de commandes vocales (commandes.yaml du dossier de configuration) : phrase exacte vers action HA.

Syntaxe des phrases, reprise des phrases personnalisées de Home Assistant :
(a|b) alternative, [mot] facultatif, {emplacement} valeur tirée de la section emplacements.
"""
import difflib, re, unicodedata
from pathlib import Path

SEUIL_FLOU = 0.88  # tolérance aux petites erreurs de transcription


def normaliser(texte):
    t = unicodedata.normalize("NFD", texte.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9{}]+", " ", t)
    return " ".join(t.split())


# Formules de politesse qui ne changent pas la commande. « et ce que » = « est-ce que » mal transcrit.
_DEBUT = re.compile(r"^\s*(?:(?:est|et)[- ]ce (?:que|qu')\s*)?(?:tu peux|tu pourrais|peux[- ]tu|"
                    r"pourrais[- ]tu|vous pouvez|pouvez[- ]vous|pourriez[- ]vous|"
                    r"j'aimerais que tu|je veux que tu|merci de|merci|ok|okay|bon|alors|dis)[\s,]+", re.I)
_FIN = re.compile(r"[\s,]*(?:s'il te pla[iî]t|s'il vous pla[iî]t|stp|svp|merci|maintenant|tout de suite|vite)[\s.!?]*$", re.I)
_INFINITIF = {"éteindre": "éteins", "eteindre": "éteins", "allumer": "allume", "lancer": "lance",
              "mettre": "mets", "couper": "coupe", "arrêter": "arrête", "aspirer": "aspire",
              "laver": "lave", "nettoyer": "nettoie", "transférer": "transfère", "ramener": "ramène",
              "baisser": "baisse", "monter": "monte", "remettre": "remets", "passer": "passe"}


# Canary entend mal le prénom du propriétaire (dès le 13/10/2026). Ces formes
# (proprietaire.variantes de maison.json) sont corrigées avant toute recherche.
import maison  # noqa: E402

_VARIANTES = [re.escape(v) for v in (maison.PROPRIETAIRE.get("variantes") or []) if str(v).strip()]
_PRENOM = re.compile(r"\b(" + "|".join(_VARIANTES) + r")\b", re.I) if _VARIANTES else None


def epurer(phrase):
    """« Est-ce que tu peux éteindre la télé s'il te plaît ? » devient « éteins la télé »."""
    t = (_PRENOM.sub(maison.NOM_PROPRIETAIRE, phrase.strip()) if _PRENOM else phrase.strip()).rstrip(" ?.!")
    avant = None
    while avant != t:
        avant = t
        t = _DEBUT.sub("", t)
    t = _FIN.sub("", t)
    mots = t.split(" ", 1)
    if mots and mots[0].lower() in _INFINITIF:
        mots[0] = _INFINITIF[mots[0].lower()]
    # Canary entend souvent « Mais » pour « Mets » en début de phrase (journal du 12/10) :
    # on corrige seulement devant un article, un vrai « mais » n'en est pas suivi.
    if (len(mots) == 2 and mots[0].lower() in ("mais", "met", "mes")
            and re.match(r"(le|la|les|l'|toutes?|tous|un|une|du|des|ma|mon|mes|ta|ton|une)\b", mots[1], re.I)):
        mots[0] = "mets"
    return " ".join(mots) if t else phrase


def mots_compatibles(a, b):
    """Vrai si les deux phrases ne diffèrent que par des mots proches (fautes) ou des petits mots.

    Chaque mot présent d'un seul côté doit ressembler à un mot de l'autre côté : ratio de 0,75 au
    moins, ou de 0,5 avec la même première lettre (« enceint » et « enceinte » passent, « rouge » et
    « orange » ou « bleu » non), ou faire au plus 3 lettres (« la », « du », « les »)."""
    def proche(m, o):
        r = difflib.SequenceMatcher(None, m, o).ratio()
        return r >= 0.75 or (r >= 0.5 and m[0] == o[0])
    ma, mb = a.split(), b.split()
    for seuls, autres in ((set(ma) - set(mb), mb), (set(mb) - set(ma), ma)):
        for m in seuls:
            if len(m) > 3 and not any(proche(m, o) for o in autres):
                return False
    return True


def _decouper(s, sep="|"):
    """Coupe s sur sep, seulement hors des parenthèses, crochets et accolades."""
    parts, prof, cour = [], 0, ""
    for c in s:
        if c in "([{":
            prof += 1
        elif c in ")]}":
            prof -= 1
        if c == sep and prof == 0:
            parts.append(cour)
            cour = ""
        else:
            cour += c
    return parts + [cour]


def developper(motif):
    """Toutes les formes d'un motif, accolades laissées telles quelles."""
    alternatives = _decouper(motif)
    if len(alternatives) > 1:
        return [f for a in alternatives for f in developper(a)]
    m = re.search(r"[\(\[]", motif)
    if not m:
        return [motif]
    debut, ouvrant = m.start(), m.group()
    fermant, prof = (")" if ouvrant == "(" else "]"), 0
    for fin in range(debut, len(motif)):
        prof += motif[fin] in "(["
        prof -= motif[fin] in ")]"
        if prof == 0:
            break
    interieur = developper(motif[debut + 1:fin])
    if ouvrant == "[":
        interieur.append("")
    suite = developper(motif[fin + 1:])
    return [motif[:debut] + i + s for i in interieur for s in suite]


# Valeur du champ « personne » quand la tablette voit une seule personne sans la reconnaître.
INCONNU = "inconnu"


def _cibles(action):
    v = action.get("entity_id")
    if v is None:
        return []
    return [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else [str(x) for x in v]


class Personnes:
    """« Ma chambre » selon la personne qui parle (section personnes de commandes.yaml, 21/10/2026).

    Même règle dans android/.../DictionnaireLocal.kt (classe Personnes), cas communs dans
    poc/tests/cas_personnes.json."""

    def __init__(self, section):
        section = section or {}
        self.defaut = normaliser(str(section.get("defaut") or maison.CLE_PROPRIETAIRE))
        self.inconnu = section.get("inconnu") or "Je ne sais pas de quelle chambre tu parles."
        self.sans_chambre = section.get("sans_chambre") or self.inconnu
        self.remplacer = {normaliser(nom): dict(v.get("remplacer") or {})
                          for nom, v in section.items() if isinstance(v, dict)}
        # La chambre « par défaut » : tout ce qu'une personne peut voir remplacé chez elle.
        self.chambre = {e for r in self.remplacer.values() for e in r}

    def personnelle(self, actions, cle):
        """Vrai si la commande ne vise que la chambre par défaut sans la nommer (« ma chambre »)."""
        if not self.chambre or not actions or self.defaut in cle.split():
            return False
        return all(_cibles(a) and set(_cibles(a)) <= self.chambre for a in actions)

    def appliquer(self, actions, cle, personne):
        """Rend (actions, refus, réponse de remplacement). Rien ne change hors d'une commande personnelle."""
        if not self.personnelle(actions, cle):
            return actions, None, None
        p = normaliser(personne or "")
        if not p or p == self.defaut:
            return actions, None, None
        if p == INCONNU:
            return [], self.inconnu, None
        table = self.remplacer.get(p)
        if not table:
            return [], self.sans_chambre, None
        sortie, reponse = [], None
        for a in actions:
            entites = _cibles(a)
            if len(entites) == 1 and isinstance(table.get(entites[0]), dict):
                nouvelle = dict(table[entites[0]])
                reponse = nouvelle.pop("reponse", None) or reponse
                sortie.append(nouvelle)
                continue
            if any(e not in table or isinstance(table[e], dict) for e in entites):
                return [], self.sans_chambre, None
            nouvelles = list(dict.fromkeys(table[e] for e in entites))
            sortie.append({**a, "entity_id": nouvelles if isinstance(a["entity_id"], list) else ",".join(nouvelles)})
        return sortie, None, reponse


def _formater(valeur, valeurs):
    """Remplace {emplacement} dans tous les textes d'une action, y compris dans ses listes et ses objets
    imbriqués (hs_color: ["{couleur}", 100], actions dynamiques). Pendant Kotlin : Forme.actions, qui remplace
    dans le JSON entier. Les clés ne sont jamais touchées."""
    if isinstance(valeur, str):
        return valeur.format(**valeurs)
    if isinstance(valeur, list):
        return [_formater(v, valeurs) for v in valeur]
    if isinstance(valeur, dict):
        return {k: _formater(v, valeurs) for k, v in valeur.items()}
    return valeur


class Dictionnaire:
    def __init__(self, chemin, chemin_appris):
        """[chemin] : commandes.yaml du dossier de configuration. [chemin_appris] : phrases apprises, propres à
        la machine (dossier de données), jamais dans la configuration (sur HA, /app/maison est remplacé à
        chaque déploiement)."""
        import yaml
        self.chemin = Path(chemin)
        donnees = yaml.safe_load(self.chemin.read_text(encoding="utf-8"))
        self.llm = donnees.get("llm") or {}
        self.personnes = Personnes(donnees.get("personnes"))
        emplacements = {}
        for nom, valeurs in (donnees.get("emplacements") or {}).items():
            emplacements[nom] = [(normaliser(f), v) for motif, v in valeurs.items()
                                 for f in developper(motif)]
        self.formes = {}  # forme normalisée -> (commande, valeurs des emplacements)
        for cmd in donnees["commandes"]:
            for motif in cmd["phrases"]:
                for forme in developper(motif):
                    for texte, valeurs in self._remplir(normaliser(forme), emplacements):
                        self.formes.setdefault(texte, (cmd, valeurs))
        # Phrases apprises du LLM (commandes_apprises.yaml) : le dictionnaire écrit à la main passe
        # toujours en premier en cas de doublon.
        self.chemin_appris = Path(chemin_appris)
        self.apprises = []
        if self.chemin_appris.exists():
            self.apprises = (yaml.safe_load(self.chemin_appris.read_text(encoding="utf-8")) or {}).get("apprises") or []
        for cmd in self.apprises:
            self.formes.setdefault(normaliser(cmd["phrase"]), (cmd, {}))

    def apprendre(self, phrase, actions, reponse, date):
        """Ajoute une phrase traitée avec succès par le LLM. Renvoie False si elle est déjà connue."""
        cle = normaliser(phrase)
        if not cle or cle in self.formes:
            return False
        cmd = {"phrase": phrase, "action": actions, "reponse": reponse, "appris_le": date}
        self.apprises.append(cmd)
        self.formes[cle] = (cmd, {})
        self._sauver()
        return True

    def oublier(self, phrase):
        cle = normaliser(phrase)
        avant = len(self.apprises)
        self.apprises = [c for c in self.apprises if normaliser(c["phrase"]) != cle]
        if len(self.apprises) == avant:
            return False
        trouve = self.formes.get(cle)
        if trouve and "appris_le" in trouve[0]:
            del self.formes[cle]
        self._sauver()
        return True

    def _sauver(self):
        import yaml
        entete = ("# Phrases apprises automatiquement du LLM (assistant vocal v0.9.0).\n"
                  "# Une phrase traitée avec succès par le LLM est rangée ici, puis reconnue directement la fois\n"
                  "# suivante. Pour en retirer une : supprime son bloc, ou dis « non » / « annule » dans les 30 s.\n")
        corps = yaml.safe_dump({"apprises": self.apprises}, allow_unicode=True, sort_keys=False, width=120)
        self.chemin_appris.write_text(entete + corps, encoding="utf-8")

    def _remplir(self, forme, emplacements):
        m = re.search(r"\{(\w+)\}", forme)
        if not m:
            yield " ".join(forme.split()), {}
            return
        for texte_val, val in emplacements[m.group(1)]:
            for texte, valeurs in self._remplir(forme[:m.start()] + texte_val + forme[m.end():], emplacements):
                yield texte, {m.group(1): val, **valeurs}

    def chercher(self, phrase):
        """Renvoie (actions, réponse, forme reconnue) ou None."""
        cle = normaliser(phrase)
        trouve = self.formes.get(cle)
        if not trouve:
            # Tolérance aux fautes de transcription (« enceint » pour « enceinte »), mais jamais à un mot
            # remplacé par un autre (« rouge » pris pour « bleu » le 12/10, la lampe est repassée en
            # bleu), et jamais pour les phrases apprises, qui ne valent que mot pour mot.
            proches = [c for c in difflib.get_close_matches(cle, self.formes, n=5, cutoff=SEUIL_FLOU)
                       if "appris_le" not in self.formes[c][0] and mots_compatibles(cle, c)]
            if not proches:
                return None
            cle = proches[0]
            trouve = self.formes[cle]
        cmd, valeurs = trouve
        actions = cmd["action"] if isinstance(cmd["action"], list) else [cmd["action"]]
        actions = [_formater(a, valeurs) for a in actions]
        return actions, cmd.get("reponse", "C'est fait."), cle
