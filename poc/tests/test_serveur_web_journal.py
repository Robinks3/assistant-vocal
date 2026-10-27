"""Journal du client web (S-W2) vu depuis le serveur : ce que chaque navigateur reçoit, en liste, en direct et à
l'effacement. Un appareil qui n'est pas l'auteur ne reçoit rien qu'il n'a pas le droit de voir."""
import asyncio
import json
from datetime import timedelta

import journal_web as J
import maison
import serveur_satellite as S
import serveur_web as W
import webauthn as WA
from test_serveur_web_appairage import (  # noqa: F401  (fixtures réutilisées)
    ORIGINE, appairer_direct, arreter, attendre, entetes, envoyer, horloge, journal, lancer, ouvrir_ws, recevoir,
    recevoir_reponse, service, signer, statut_de)


def aujourd_hui():
    return maison.maintenant().strftime("%Y-%m-%d")


def il_y_a(jours):
    return (maison.maintenant() - timedelta(days=jours)).strftime("%Y-%m-%d")


def ligne(texte="allume la lampe du bureau", personne="camille", appareil="appareil:tab1", niveau="tout",
          actions="light.turn_on ['light.salon_plafond']", ident="0123456789ab", jour=None, **autres):
    base = {"horodatage": (jour or aujourd_hui()) + "T09:15:00", "texte": texte, "voie": "dictionnaire",
            "total_s": "0.42", "reponse": "C'est fait.", "actions": actions, "appareil": appareil,
            "personne": personne, "role": "habitant", "id": ident, "niveau": niveau, "statut": "ok",
            "canal": "voix", "etapes": [{"nom": "entendu", "t": "09:14:59"}, {"nom": "fait", "t": "09:15:00"}]}
    base.update(autres)
    return base


def ecrire(dossier, lignes, jour=None):
    dossier.mkdir(parents=True, exist_ok=True)
    f = dossier / f"assistant-{jour or aujourd_hui()}.jsonl"
    with open(f, "a", encoding="utf-8") as sortie:
        for l in lignes:
            sortie.write(json.dumps(l, ensure_ascii=False) + "\n")


class Faux(W.Connexion):
    """Une connexion cliente qui range ce qu'on lui envoie, sans réseau."""

    def __init__(self, ident, identite):
        super().__init__(ident, None, "client", identite)
        self.recus = []

    def envoyer(self, message, fermer=None):
        self.recus.append(message)


class Monde:
    """Un propriétaire, un habitant et un invité, un dossier de journal et trois connexions fausses abonnées."""

    def __init__(self, service, tmp_path):
        self.service = service
        self.dossier = tmp_path / "journal"
        self.niveaux = J.Niveaux(tmp_path / "vie_privee_web.json")
        service.brancher_journal(self.dossier, self.niveaux)
        self.proprio, self.tel_p, self.jeton_p = appairer_direct(service, "administrateur", "Propriétaire", conn=1)
        self.habitant, self.tel_h, self.jeton_h = appairer_direct(service, "habitant", "Habitant", conn=2)
        self.invite, self.tel_i, self.jeton_i = appairer_direct(service, "invite", "Invité", conn=3)
        self.fausses = {}
        for i, (nom, a) in enumerate((("proprio", self.proprio), ("habitant", self.habitant),
                                      ("invite", self.invite)), start=100):
            c = Faux(i, "web:" + a["id"])
            c.abonne_journal = True
            service.connexions[i] = c
            self.fausses[nom] = c

    def recus(self, nom):
        return [m for m in self.fausses[nom].recus if m and m.get("type") == "journal_ajout"]


def monde(service, tmp_path):
    return Monde(service, tmp_path)


# Diffusion en direct

def test_une_entree_neuve_arrive_filtree_par_destinataire(service, tmp_path):
    m = monde(service, tmp_path)
    service.publier_ajout(ligne(niveau="tout", appareil="appareil:tab1"))
    assert [e["entree"]["detail"] for e in m.recus("proprio")] == ["complet"]
    assert [e["entree"]["detail"] for e in m.recus("habitant")] == ["complet"]
    assert m.recus("invite") == []


def test_niveau_action_cache_la_phrase_a_tous_les_navigateurs_non_auteurs(service, tmp_path):
    m = monde(service, tmp_path)
    service.publier_ajout(ligne(niveau="action", texte="allume la lampe du bureau"))
    for nom in ("proprio", "habitant"):
        e = m.recus(nom)[0]["entree"]
        assert e["detail"] == "action" and "phrase" not in e
        assert "lampe du bureau" not in json.dumps(m.fausses[nom].recus)
    assert m.recus("invite") == []


def test_niveau_discret_ne_laisse_voir_que_l_existence_au_proprietaire(service, tmp_path):
    m = monde(service, tmp_path)
    service.publier_ajout(ligne(niveau="discret", texte="une demande confidentielle"))
    assert [e["entree"]["detail"] for e in m.recus("proprio")] == ["aucun"]
    assert "confidentielle" not in json.dumps(m.fausses["proprio"].recus)
    assert m.recus("habitant") == [] and m.recus("invite") == []


def test_l_auteur_recoit_le_detail_complet_et_les_etapes_meme_en_discret(service, tmp_path):
    m = monde(service, tmp_path)
    service.publier_ajout(ligne(niveau="discret", personne=None, appareil="web:" + m.habitant["id"]))
    e = m.recus("habitant")[0]["entree"]
    assert e["mien"] and e["detail"] == "complet" and [x["nom"] for x in e["etapes"]] == ["entendu", "fait"]
    assert m.recus("proprio")[0]["entree"]["detail"] == "aucun"
    assert m.recus("invite") == []


def test_un_navigateur_non_abonne_ne_recoit_rien(service, tmp_path):
    m = monde(service, tmp_path)
    m.fausses["habitant"].abonne_journal = False
    service.publier_ajout(ligne(niveau="tout"))
    assert m.recus("habitant") == [] and len(m.recus("proprio")) == 1


def test_un_navigateur_retire_ne_recoit_plus_rien(service, tmp_path):
    m = monde(service, tmp_path)
    service.appairage.revoquer(m.habitant["id"])
    service.publier_ajout(ligne(niveau="tout"))
    assert m.recus("habitant") == [] and len(m.recus("proprio")) == 1


def test_la_sante_des_autres_n_est_jamais_diffusee_aux_habitants(service, tmp_path):
    m = monde(service, tmp_path)
    service.publier_ajout(ligne(texte="quelle est ma tension ce matin", niveau="tout", actions=""))
    assert m.recus("habitant") == []
    assert m.recus("proprio")[0]["entree"]["detail"] == "aucun"


def test_sans_journal_branche_rien_n_est_diffuse(service, tmp_path):
    m = monde(service, tmp_path)
    service.journal_dossier = None
    service.publier_ajout(ligne())
    service.publier_etape("0123456789ab", {"appareil": "web:" + m.habitant["id"], "personne": None}, "entendu", "09:14")
    assert all(not c.recus for c in m.fausses.values())


def test_etape_en_direct_seulement_pour_son_auteur(service, tmp_path):
    m = monde(service, tmp_path)
    auteur = {"appareil": "web:" + m.habitant["id"], "personne": None}
    service.publier_etape("0123456789ab", auteur, "entendu", "09:14:59")
    etapes = {nom: [x for x in c.recus if x.get("type") == "journal_etape"] for nom, c in m.fausses.items()}
    assert etapes["habitant"] == [{"type": "journal_etape", "id": "0123456789ab", "nom": "entendu", "t": "09:14:59"}]
    assert etapes["proprio"] == [] and etapes["invite"] == []


def test_etape_du_proprietaire_reste_au_proprietaire(service, tmp_path):
    m = monde(service, tmp_path)
    service.publier_etape("0123456789ab", {"appareil": "appareil:tel1", "personne": maison.CLE_PROPRIETAIRE},
                          "entendu", "09:14:59")
    assert len(m.fausses["proprio"].recus) == 1
    assert not m.fausses["habitant"].recus and not m.fausses["invite"].recus


def test_etape_inconnue_n_est_pas_diffusee(service, tmp_path):
    m = monde(service, tmp_path)
    service.publier_etape("0123456789ab", {"appareil": "web:" + m.habitant["id"], "personne": None}, "bidule", "09:14")
    assert not m.fausses["habitant"].recus


# Satellites : la diffusion d'historique passe par le client web, jamais par historique_ajout

def test_diffuser_historique_appelle_la_projection_du_client_web(service, tmp_path):
    m = monde(service, tmp_path)
    moteur = object.__new__(S.Moteur)
    moteur.satellites = []
    moteur.pages_admin = []
    moteur.noms = {}
    moteur.appareils = None
    moteur.service_web = service
    asyncio.run(moteur.diffuser_historique(ligne(niveau="action")))
    assert m.recus("proprio")[0]["entree"]["detail"] == "action"
    assert m.recus("invite") == []
    assert not any(x.get("type") == "historique_ajout" for c in m.fausses.values() for x in c.recus)


def test_diffuser_historique_survit_a_une_panne_du_client_web(service, tmp_path, capsys):
    class Casse:
        def publier_ajout(self, ligne):
            raise RuntimeError("panne")
    moteur = object.__new__(S.Moteur)
    moteur.satellites = []
    moteur.pages_admin = []
    moteur.noms = {}
    moteur.appareils = None
    moteur.service_web = Casse()
    asyncio.run(moteur.diffuser_historique(ligne()))
    assert "Journal web" in capsys.readouterr().out


# Lecture par WebSocket

def preparer_journal(m):
    ecrire(m.dossier, [
        ligne(niveau="tout", ident="aaaaaaaaaaa1", texte="allume la lampe du bureau", personne="camille"),
        ligne(niveau="action", ident="aaaaaaaaaaa2", texte="mets la lumière du salon à fond", personne="camille"),
        ligne(niveau="discret", ident="aaaaaaaaaaa3", texte="texte confidentiel de Camille", personne="camille"),
        ligne(niveau="tout", ident="aaaaaaaaaaa4", texte="demande de l'habitant", personne=None,
              appareil="web:" + m.habitant["id"]),
        ligne(niveau="discret", ident="aaaaaaaaaaa5", texte="demande de l'invité", personne=None,
              appareil="web:" + m.invite["id"]),
    ])


def test_abonnement_filtre_par_role_sur_une_vraie_connexion(service, tmp_path):
    m = monde(service, tmp_path)
    preparer_journal(m)

    async def scenario():
        serveur, port = await lancer(service)
        try:
            reponses = {}
            for nom, jeton in (("proprio", m.jeton_p), ("habitant", m.jeton_h), ("invite", m.jeton_i)):
                ws = await ouvrir_ws(port, "/ws", jeton)
                await envoyer(ws, {"type": "abonner_journal"})
                reponses[nom] = await recevoir_reponse(ws)
                await ws.close()
            return reponses
        finally:
            await arreter(serveur)
    rep = asyncio.run(scenario())
    # Propriétaire : l'existence de chaque entrée, mais jamais le texte d'un discret.
    ids = {e["id"]: e for e in rep["proprio"]["entrees"]}
    assert set(ids) == {"aaaaaaaaaaa1", "aaaaaaaaaaa2", "aaaaaaaaaaa3", "aaaaaaaaaaa4", "aaaaaaaaaaa5"}
    assert ids["aaaaaaaaaaa3"]["detail"] == "aucun" and ids["aaaaaaaaaaa5"]["detail"] == "aucun"
    assert "confidentiel" not in json.dumps(rep["proprio"]) and "invité" not in json.dumps(rep["proprio"])
    # Habitant : le niveau Tout, l'Action sans phrase, et ses propres entrées. Rien du discret du propriétaire.
    ids = {e["id"]: e for e in rep["habitant"]["entrees"]}
    assert set(ids) == {"aaaaaaaaaaa1", "aaaaaaaaaaa2", "aaaaaaaaaaa4"}
    assert ids["aaaaaaaaaaa2"]["detail"] == "action" and "phrase" not in ids["aaaaaaaaaaa2"]
    assert "confidentiel" not in json.dumps(rep["habitant"])
    # Invité : seulement ce qu'il a lui-même demandé.
    ids = {e["id"]: e for e in rep["invite"]["entrees"]}
    assert set(ids) == {"aaaaaaaaaaa5"} and ids["aaaaaaaaaaa5"]["mien"]
    for nom in ("proprio", "habitant", "invite"):
        assert rep[nom]["type"] == "journal" and rep[nom]["conserve_jours"] == 30


def test_la_liste_ne_contient_jamais_une_cle_ou_un_identifiant_d_appareil(service, tmp_path):
    m = monde(service, tmp_path)
    preparer_journal(m)
    for spect in (J.spectateur_de(m.proprio), J.spectateur_de(m.habitant)):
        entrees, _ = J.lire(m.dossier, spect, None, service.nom_appareil)
        brut = json.dumps(entrees)
        assert "appareil:tab1" not in brut and "web:" not in brut and "sacha" not in brut


def test_page_suivante_et_reprise_illisible(service, tmp_path):
    m = monde(service, tmp_path)
    for jour in range(9):
        ecrire(m.dossier, [ligne(niveau="tout", ident=f"{jour:012x}", jour=il_y_a(jour))], jour=il_y_a(jour))

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", m.jeton_p)
            await envoyer(ws, {"type": "abonner_journal"})
            premiere = await recevoir_reponse(ws)
            await envoyer(ws, {"type": "journal_page", "reprise": premiere["plus"]})
            suite = await recevoir_reponse(ws)
            await envoyer(ws, {"type": "journal_page", "reprise": ["pas", "une", "date"]})
            illisible = await recevoir_reponse(ws)
            await ws.close()
            return premiere, suite, illisible
        finally:
            await arreter(serveur)
    premiere, suite, illisible = asyncio.run(scenario())
    assert len(premiere["entrees"]) == 7 and premiere["plus"] == il_y_a(7)
    assert len(suite["entrees"]) == 2 and suite["plus"] is None and suite["type"] == "journal_page"
    assert len(illisible["entrees"]) == 7


def test_retention_de_30_jours(service, tmp_path):
    m = monde(service, tmp_path)
    ecrire(m.dossier, [ligne(ident="bbbbbbbbbbb1", jour=il_y_a(45))], jour=il_y_a(45))
    ecrire(m.dossier, [ligne(ident="bbbbbbbbbbb2")])
    entrees, plus = J.lire(m.dossier, J.spectateur_de(m.proprio), None, service.nom_appareil, jours=30)
    assert [e["id"] for e in entrees] == ["bbbbbbbbbbb2"] and plus is None


def test_desabonnement_arrete_la_diffusion(service, tmp_path):
    m = monde(service, tmp_path)
    preparer_journal(m)

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", m.jeton_h)
            await envoyer(ws, {"type": "abonner_journal"})
            await recevoir_reponse(ws)
            def abonnes():
                return [c for c in service.connexions.values() if c.genre == "client" and c.abonne_journal
                        and c.identite == "web:" + m.habitant["id"] and not isinstance(c, Faux)]
            abonnes_avant = abonnes()
            await envoyer(ws, {"type": "desabonner_journal"})
            rep = await recevoir_reponse(ws)
            abonnes_apres = abonnes()
            await ws.close()
            return abonnes_avant, rep, abonnes_apres
        finally:
            await arreter(serveur)
    avant, rep, apres = asyncio.run(scenario())
    assert len(avant) == 1 and rep == {"type": "journal_ferme"} and apres == []


def test_messages_du_journal_refuses_quand_le_journal_n_est_pas_branche(service, tmp_path):
    _, _, jeton = appairer_direct(service, "habitant")

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", jeton)
            await envoyer(ws, {"type": "abonner_journal"})
            rep = await recevoir_reponse(ws)
            await ws.close()
            return rep
        finally:
            await arreter(serveur)
    assert asyncio.run(scenario()) == {"type": "erreur", "cause": "action"}


def test_un_habitant_ne_peut_toujours_pas_gerer_les_appareils(service, tmp_path):
    m = monde(service, tmp_path)

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", m.jeton_h)
            sortie = []
            for message in ({"type": "appareils"}, {"type": "ouvrir", "nom": "X", "role": "invite"},
                            {"type": "defi", "action": "revoquer", "cible": m.invite["id"]},
                            {"type": "defi", "action": "confirmer", "cible": "x"}):
                await envoyer(ws, message)
                sortie.append(await recevoir_reponse(ws))
            await ws.close()
            return sortie
        finally:
            await arreter(serveur)
    assert all(r == {"type": "erreur", "cause": "droit"} for r in asyncio.run(scenario()))
    assert service.appairage.appareils.get(m.invite["id"]) is not None


# Vie privée

def test_vie_privee_par_defaut_est_discret_et_se_lit_sans_preuve(service, tmp_path):
    m = monde(service, tmp_path)

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", m.jeton_h)
            await envoyer(ws, {"type": "vie_privee"})
            rep = await recevoir_reponse(ws)
            await ws.close()
            return rep
        finally:
            await arreter(serveur)
    rep = asyncio.run(scenario())
    assert rep["type"] == "vie_privee" and rep["niveau"] == "discret" and rep["niveaux"] == ["tout", "action", "discret"]


def test_changer_de_niveau_exige_la_cle_d_acces_et_ne_vaut_que_pour_soi(service, tmp_path):
    m = monde(service, tmp_path)

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", m.jeton_h)
            # Un niveau absurde est refusé dès le défi, sans signature.
            await envoyer(ws, {"type": "defi", "action": "vie_privee", "cible": "partout"})
            refus = await recevoir_reponse(ws)
            # Une signature d'un autre authentificateur est refusée, et le niveau ne bouge pas.
            mauvaise = await signer(ws, "vie_privee", m.tel_p, cible="tout")
            niveau_apres_refus = service.niveaux.niveau_de("web:" + m.habitant["id"])
            bonne = await signer(ws, "vie_privee", m.tel_h, cible="action")
            await ws.close()
            return refus, mauvaise, niveau_apres_refus, bonne
        finally:
            await arreter(serveur)
    refus, mauvaise, apres_refus, bonne = asyncio.run(scenario())
    assert refus == {"type": "erreur", "cause": "cible"}
    assert mauvaise == {"type": "erreur", "cause": "preuve"} and apres_refus == "discret"
    assert bonne["type"] == "vie_privee" and bonne["niveau"] == "action"
    assert service.niveaux.niveau_de("web:" + m.habitant["id"]) == "action"
    # Le niveau du propriétaire et celui de l'invité n'ont pas bougé.
    assert service.niveaux.niveau_de(maison.CLE_PROPRIETAIRE) == "discret"
    assert service.niveaux.niveau_de("web:" + m.invite["id"]) == "discret"


def test_le_proprietaire_regle_le_niveau_de_la_maison(service, tmp_path):
    m = monde(service, tmp_path)

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", m.jeton_p)
            rep = await signer(ws, "vie_privee", m.tel_p, cible="tout")
            await ws.close()
            return rep
        finally:
            await arreter(serveur)
    assert asyncio.run(scenario())["niveau"] == "tout"
    assert service.niveaux.niveau_de(maison.CLE_PROPRIETAIRE) == "tout"


def test_defi_de_vie_privee_ne_sert_pas_a_une_autre_action(service, tmp_path):
    """Une preuve signée pour régler la vie privée ne révoque personne : l'action d'un défi est figée."""
    m = monde(service, tmp_path)

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", m.jeton_h)
            await envoyer(ws, {"type": "defi", "action": "vie_privee", "cible": "tout"})
            d = await attendre(ws, "defi")
            reponse = m.tel_h.signer(WA.deb64u(d["options"]["challenge"], 100), ORIGINE)
            await envoyer(ws, {"type": "preuve", "reponse": reponse})
            rep = await recevoir_reponse(ws)
            await ws.close()
            return rep
        finally:
            await arreter(serveur)
    assert asyncio.run(scenario())["type"] == "vie_privee"
    assert service.appairage.appareils.get(m.invite["id"]) is not None
    assert service.appairage.appareils.get(m.proprio["id"]) is not None


# Effacement

def test_effacer_mes_entrees_ne_touche_que_les_miennes_et_previent_les_autres_ecrans(service, tmp_path):
    m = monde(service, tmp_path)
    preparer_journal(m)
    ecrire(m.dossier, [ligne(niveau="tout", ident="ccccccccccc1", personne=None,
                             appareil="web:" + m.habitant["id"], jour=il_y_a(2))], jour=il_y_a(2))

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", m.jeton_h)
            rep = await signer(ws, "journal_effacer", m.tel_h)
            await ws.close()
            return rep
        finally:
            await arreter(serveur)
    rep = asyncio.run(scenario())
    assert rep == {"type": "journal_efface", "n": 2}
    restant = []
    for f in sorted(m.dossier.glob("assistant-*.jsonl")):
        restant += [json.loads(l)["id"] for l in f.read_text(encoding="utf-8").splitlines()]
    assert "aaaaaaaaaaa4" not in restant and "ccccccccccc1" not in restant
    assert {"aaaaaaaaaaa1", "aaaaaaaaaaa2", "aaaaaaaaaaa3", "aaaaaaaaaaa5"} <= set(restant)
    # Le propriétaire voyait l'entrée de l'habitant (niveau Tout) : son écran est prévenu, et lui seul.
    retraits = [x for x in m.fausses["proprio"].recus if x.get("type") == "journal_retrait"]
    assert len(retraits) == 1 and set(retraits[0]["ids"]) == {"aaaaaaaaaaa4", "ccccccccccc1"}
    assert not m.fausses["invite"].recus


def test_effacer_ne_demande_aucun_effet_sans_preuve(service, tmp_path):
    m = monde(service, tmp_path)
    preparer_journal(m)
    avant = [f.read_text(encoding="utf-8") for f in sorted(m.dossier.glob("assistant-*.jsonl"))]

    async def scenario():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", m.jeton_h)
            await envoyer(ws, {"type": "journal_effacer"})
            direct = await recevoir_reponse(ws)
            faux = await signer(ws, "journal_effacer", m.tel_i)
            await ws.close()
            return direct, faux
        finally:
            await arreter(serveur)
    direct, faux = asyncio.run(scenario())
    assert direct == {"type": "erreur", "cause": "droit"} and faux == {"type": "erreur", "cause": "preuve"}
    assert [f.read_text(encoding="utf-8") for f in sorted(m.dossier.glob("assistant-*.jsonl"))] == avant


# Pages Journal et Vie privée

def test_pages_journal_et_vie_privee_exigent_une_session_et_s_ouvrent_a_tous_les_roles(service):
    for chemin in ("/journal", "/vie-privee"):
        rep = service.traiter("127.0.0.1", chemin, entetes())
        assert statut_de(rep) == 303 and rep[1]["Location"] == "/appairage", chemin
    for chemin in ("/journal.js", "/vie-privee.js"):
        assert statut_de(service.traiter("127.0.0.1", chemin, entetes())) == 401, chemin
    for conn, role in enumerate(("administrateur", "habitant", "invite"), start=1):
        _, _, jeton = appairer_direct(service, role, f"Appareil {role}", conn=conn)
        for chemin in ("/journal", "/vie-privee"):
            rep = service.traiter("127.0.0.1", chemin, entetes(jeton))
            assert statut_de(rep) == 200, (role, chemin)
            assert "{{" not in rep[2].decode("utf-8"), (role, chemin)
        for chemin in ("/journal.js", "/vie-privee.js"):
            assert statut_de(service.traiter("127.0.0.1", chemin, entetes(jeton))) == 200, (role, chemin)


