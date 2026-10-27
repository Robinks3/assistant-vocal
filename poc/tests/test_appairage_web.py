import json
import os

import pytest

import appairage_web as AW
import webauthn as WA
from aide_webauthn import Authentificateur

RP = "assistant.exemple.ts.net"
ORIGINE = f"https://{RP}"


class Horloge:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t

    def avancer(self, s):
        self.t += s


class Boite:
    """Recueille les événements et les révocations émis par le coeur."""

    def __init__(self):
        self.evenements = []
        self.revoques = []
        self.journal = []

    def evenement(self, cible, message, conn=None):
        self.evenements.append((cible, message, conn))

    def revocation(self, identite):
        self.revoques.append(identite)

    def messages(self, cible, cle="evenement"):
        return [m for c, m, _ in self.evenements if c == cible and cle in m]


@pytest.fixture
def horloge():
    return Horloge()


@pytest.fixture
def boite():
    return Boite()


@pytest.fixture
def coeur(tmp_path, horloge, boite):
    return AW.AppairageWeb(tmp_path / "appareils_web.json", RP, {ORIGINE}, nom="Iris", horloge=horloge,
                           sur_evenement=boite.evenement, sur_revocation=boite.revocation, journal=boite.journal.append)


def appairer(coeur, nom="Téléphone de test", role="administrateur", acteur="ha", conn=1, tel=None, confirmer=True):
    """Parcours complet jusqu'au bout. Renvoie (appareil, authentificateur, ticket)."""
    tel = tel or Authentificateur(RP)
    ouverture = coeur.ouvrir(nom, role, acteur)
    rep = coeur.tenter_code(conn, ouverture["code"])
    assert rep["etat"] == "creation"
    challenge = WA.deb64u(rep["options"]["challenge"], 100)
    res = coeur.creation(conn, tel.creer(challenge, ORIGINE))
    assert res["etat"] == "attente"
    if not confirmer:
        return None, tel, None
    appareil = coeur.finaliser()
    return appareil, tel, None


def proprietaire(coeur, boite):
    appareil, tel, _ = appairer(coeur)
    return AW.identite_de(appareil["id"]), tel


def signer_defi(coeur, tel, conn, identite, action, cible=None):
    options = coeur.defi(conn, identite, action, cible)
    challenge = WA.deb64u(options["challenge"], 100)
    return tel.signer(challenge, ORIGINE)


def cause(fonction, *args, **kw):
    with pytest.raises(AW.ErreurAppairage) as e:
        fonction(*args, **kw)
    return e.value.cause


# Parcours complet

def test_parcours_complet_depuis_ha_puis_ticket(coeur, boite):
    ouverture = coeur.ouvrir("Téléphone de Camille", "administrateur", "ha")
    assert len(ouverture["code"]) == 6 and ouverture["code"].isdigit() and ouverture["duree"] == 120
    rep = coeur.tenter_code(7, ouverture["code"])
    assert rep["etat"] == "creation" and rep["options"]["rp"]["id"] == RP
    tel = Authentificateur(RP)
    assert coeur.creation(7, tel.creer(WA.deb64u(rep["options"]["challenge"], 100), ORIGINE))["etat"] == "attente"
    appareil = coeur.finaliser()
    assert appareil["role"] == "administrateur" and appareil["nom"] == "Téléphone de Camille"
    ticket = [m["ticket"] for c, m, conn in boite.evenements if c == "ouverture" and "ticket" in m][0]
    trouve = coeur.consommer_ticket(ticket)
    assert trouve and trouve["id"] == appareil["id"]
    assert coeur.consommer_ticket(ticket) is None, "un ticket ne sert qu'une fois"
    assert coeur.etat_ouverture() == {"ouverte": False}
    assert boite.messages("ha") and any(m["evenement"] == "appairage_fait" for m in boite.messages("proprietaires"))


def test_le_code_n_est_jamais_garde_ni_journalise(coeur, boite, tmp_path):
    ouverture = coeur.ouvrir("Tablette", "habitant", "ha")
    assert ouverture["code"] not in json.dumps(coeur.etat_ouverture())
    assert all(ouverture["code"] not in ligne for ligne in boite.journal)
    appairer(coeur, nom="Autre")
    assert ouverture["code"] not in (tmp_path / "appareils_web.json").read_text(encoding="utf-8")


def test_les_appareils_survivent_a_un_redemarrage(coeur, horloge, tmp_path):
    appareil, tel, _ = appairer(coeur)
    neuf = AW.AppairageWeb(tmp_path / "appareils_web.json", RP, {ORIGINE}, horloge=horloge)
    relu = neuf.appareils.get(appareil["id"])
    assert relu["credential"]["id"] == WA.b64u(tel.id) and relu["role"] == "administrateur"


def test_fichier_corrompu_ou_d_une_autre_version_donne_une_liste_vide(tmp_path, horloge):
    f = tmp_path / "appareils_web.json"
    for contenu in ("pas du json", "[]", json.dumps({"version": 99, "appareils": {}}),
                    json.dumps({"version": 1, "appareils": {"x": {"id": "y"}}})):
        f.write_text(contenu, encoding="utf-8")
        assert AW.AppairageWeb(f, RP, {ORIGINE}, horloge=horloge).appareils.tous() == []


def test_invite_expire_apres_invite_jours(tmp_path, horloge, boite):
    coeur = AW.AppairageWeb(tmp_path / "a.json", RP, {ORIGINE}, invite_jours=7, horloge=horloge,
                            sur_revocation=boite.revocation)
    appareil, _, _ = appairer(coeur, nom="Invité", role="invite")
    assert appareil["expire"] == horloge() + 7 * 86400
    horloge.avancer(7 * 86400 - 1)
    coeur.toucher(AW.identite_de(appareil["id"]))
    coeur.purger()
    assert coeur.appareils.get(appareil["id"])
    horloge.avancer(2)
    coeur.purger()
    assert coeur.appareils.get(appareil["id"]) is None and boite.revoques == [AW.identite_de(appareil["id"])]


def test_appareil_inactif_trente_jours_est_purge(coeur, horloge, boite):
    appareil, _, _ = appairer(coeur)
    horloge.avancer(30 * 86400 + 1)
    coeur.purger()
    assert coeur.appareils.tous() == [] and boite.revoques


def test_toucher_met_a_jour_dernier_au_plus_toutes_les_cinq_minutes(coeur, horloge):
    appareil, _, _ = appairer(coeur)
    identite = AW.identite_de(appareil["id"])
    avant = coeur.appareils.get(appareil["id"])["dernier"]
    horloge.avancer(60)
    coeur.toucher(identite)
    assert coeur.appareils.get(appareil["id"])["dernier"] == avant
    horloge.avancer(300)
    coeur.toucher(identite)
    assert coeur.appareils.get(appareil["id"])["dernier"] == horloge()


# Ouverture : droits, rôles, noms

def test_seul_un_proprietaire_ou_ha_ouvre(coeur, boite):
    identite, _ = proprietaire(coeur, boite)
    habitant, _, _ = appairer(coeur, nom="Habitant", role="habitant", acteur=identite)
    assert cause(coeur.ouvrir, "X", "habitant", AW.identite_de(habitant["id"])) == "droit"
    assert cause(coeur.ouvrir, "X", "habitant", "web:inconnu") == "droit"
    assert cause(coeur.ouvrir, "X", "habitant", "satellite:1") == "droit"


def test_ha_ne_cree_pas_un_deuxieme_proprietaire(coeur, boite):
    proprietaire(coeur, boite)
    assert cause(coeur.ouvrir, "Autre", "administrateur", "ha") == "role"
    coeur.ouvrir("Habitant", "habitant", "ha")  # les autres rôles restent possibles


def test_role_partage_ou_inconnu_refuse(coeur):
    for role in ("partage", "root", "", None, 3):
        assert cause(coeur.ouvrir, "Nom", role, "ha") == "role"


@pytest.mark.parametrize("nom", ["", "   ", "x" * 41, "a\u0000b", "a​b", "a\nb", 5, None, "a‮b"])
def test_noms_refuses(coeur, nom):
    assert cause(coeur.ouvrir, nom, "habitant", "ha") == "nom"


def test_nom_normalise():
    assert AW.nettoyer_nom("  Mon   téléphone ") == "Mon téléphone"
    assert AW.nettoyer_nom("ｔｅｓｔ") == "test"


def test_limite_d_ouvertures(coeur, horloge):
    for _ in range(5):
        coeur.ouvrir("Nom", "habitant", "ha")
    assert cause(coeur.ouvrir, "Nom", "habitant", "ha") == "limite"
    horloge.avancer(601)
    coeur.ouvrir("Nom", "habitant", "ha")


def test_une_nouvelle_ouverture_remplace_l_ancienne(coeur, boite):
    premiere = coeur.ouvrir("Un", "habitant", "ha")
    rep = coeur.tenter_code(4, premiere["code"])
    assert rep["etat"] == "creation"
    seconde = coeur.ouvrir("Deux", "habitant", "ha")
    assert (("ouverture", {"etat": "interrompu"}, 4)) in boite.evenements
    assert coeur.etat_ouverture()["nom"] == "Deux"
    assert coeur.tenter_code(4, seconde["code"])["etat"] == "creation"


# Le code

def test_code_faux_trois_essais_puis_destruction(coeur, boite):
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    faux = "000000" if ouverture["code"] != "000000" else "111111"
    assert coeur.tenter_code(1, faux) == {"etat": "code_refuse", "restant": 2}
    assert coeur.tenter_code(1, faux) == {"etat": "code_refuse", "restant": 1}
    assert coeur.tenter_code(1, faux) == {"etat": "interrompu"}
    assert coeur.etat_ouverture() == {"ouverte": False}
    assert coeur.tenter_code(1, ouverture["code"])["etat"] == "code_refuse", "le bon code ne sert plus après destruction"
    assert boite.messages("ha")[-1]["raison"] == "essais"


@pytest.mark.parametrize("code", [None, 482917, "", "12345", "1234567", "abcdef", "12 456", ["1"] * 6, {"a": 1}])
def test_code_mal_forme_compte_comme_un_essai(coeur, code):
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    assert coeur.tenter_code(1, code) == {"etat": "code_refuse", "restant": 2}
    assert coeur.tenter_code(1, ouverture["code"])["etat"] == "creation"


def test_code_expire_apres_deux_minutes(coeur, horloge, boite):
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    horloge.avancer(119)
    assert coeur.etat_ouverture()["ouverte"]
    horloge.avancer(2)
    assert coeur.tenter_code(1, ouverture["code"])["etat"] == "code_refuse"
    assert coeur.etat_ouverture() == {"ouverte": False}
    assert boite.messages("ha")[-1]["raison"] == "expiree"


def test_sans_ouverture_la_reponse_imite_un_premier_essai_rate(coeur):
    assert coeur.tenter_code(1, "123456") == {"etat": "code_refuse", "restant": 2}


def test_limite_de_codes_refuses_tous_appairages_confondus(coeur):
    for _ in range(10):
        coeur.tenter_code(1, "123456")
    assert coeur.tenter_code(1, "123456") == {"etat": "limite"}
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    assert coeur.tenter_code(1, ouverture["code"]) == {"etat": "limite"}, "même le bon code est refusé pendant la pause"


def test_code_a_usage_unique(coeur):
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    assert coeur.tenter_code(1, ouverture["code"])["etat"] == "creation"
    assert coeur.tenter_code(1, ouverture["code"]) == {"etat": "erreur"}


# Deuxième navigateur pendant la fenêtre

def test_deuxieme_navigateur_detruit_l_appairage_et_alerte(coeur, boite, horloge):
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    assert coeur.tenter_code(1, ouverture["code"])["etat"] == "creation"
    assert coeur.tenter_code(2, ouverture["code"]) == {"etat": "interrompu"}
    assert coeur.etat_ouverture() == {"ouverte": False}
    assert ("ouverture", {"etat": "interrompu"}, 1) in boite.evenements, "le premier navigateur est prévenu"
    alerte = boite.messages("proprietaires")[-1]
    assert alerte["raison"] == "concurrent" and alerte["tentative"] == horloge()
    assert cause(coeur.finaliser) == "etat"


def test_deuxieme_navigateur_avec_un_faux_code_detruit_aussi(coeur):
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    coeur.tenter_code(1, ouverture["code"])
    assert coeur.tenter_code(2, "000000") == {"etat": "interrompu"}
    assert coeur.etat_ouverture() == {"ouverte": False}


def test_deuxieme_navigateur_pendant_l_attente(coeur):
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    rep = coeur.tenter_code(1, ouverture["code"])
    coeur.creation(1, Authentificateur(RP).creer(WA.deb64u(rep["options"]["challenge"], 100), ORIGINE))
    assert coeur.etat_ouverture()["etat"] == "attente"
    assert coeur.tenter_code(2, "999999") == {"etat": "interrompu"}
    assert cause(coeur.finaliser) == "etat"


# Création de la clé

def ouverture_en_creation(coeur, conn=1):
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    rep = coeur.tenter_code(conn, ouverture["code"])
    return WA.deb64u(rep["options"]["challenge"], 100)


def test_creation_challenge_rejoue_ou_faux(coeur):
    challenge = ouverture_en_creation(coeur)
    tel = Authentificateur(RP)
    assert coeur.creation(1, tel.creer(os.urandom(32), ORIGINE)) == {"etat": "interrompu"}
    assert coeur.etat_ouverture() == {"ouverte": False}
    # rejeu : le bon challenge, mais l'ouverture a disparu
    assert coeur.creation(1, tel.creer(challenge, ORIGINE)) == {"etat": "erreur"}


def test_creation_challenge_consomme_meme_apres_un_echec(coeur):
    challenge = ouverture_en_creation(coeur)
    tel = Authentificateur(RP)
    coeur.creation(1, {"id": "x"})
    assert coeur.creation(1, tel.creer(challenge, ORIGINE)) == {"etat": "erreur"}


@pytest.mark.parametrize("variante", ["origine", "rp", "uv", "up", "attestation", "type", "id"])
def test_creation_refus_serveur(coeur, variante):
    challenge = ouverture_en_creation(coeur)
    tel = Authentificateur(RP)
    options = {"origine": {"origine": "https://pirate.example"}, "rp": {"rp_id": "pirate.example"},
               "uv": {"drapeaux": WA.DRAPEAU_UP | WA.DRAPEAU_AT}, "up": {"drapeaux": WA.DRAPEAU_UV | WA.DRAPEAU_AT},
               "attestation": {"fmt": "packed"}, "type": {"type_": "webauthn.get"}, "id": {}}[variante]
    options.setdefault("origine", ORIGINE)
    rep = tel.creer(challenge, **options)
    if variante == "id":
        rep["id"] = WA.b64u(b"autre")
    assert coeur.creation(1, rep) == {"etat": "interrompu"}
    assert coeur.etat_ouverture() == {"ouverte": False}
    assert coeur.appareils.tous() == []


def test_creation_par_une_autre_connexion_ou_sans_code(coeur):
    challenge = ouverture_en_creation(coeur, conn=1)
    rep = Authentificateur(RP).creer(challenge, ORIGINE)
    assert coeur.creation(2, rep) == {"etat": "erreur"}
    assert coeur.etat_ouverture()["etat"] == "creation", "une connexion étrangère ne détruit rien par ce chemin"


@pytest.mark.parametrize("corps", [None, "x", 5, [], {}, {"clientDataJSON": 3}])
def test_creation_corps_malformes(coeur, corps):
    ouverture_en_creation(coeur)
    assert coeur.creation(1, corps) == {"etat": "interrompu"}


def test_creation_refuse_une_cle_deja_enregistree(coeur):
    appareil, tel, _ = appairer(coeur)
    ouverture = coeur.ouvrir("Autre", "habitant", "ha")
    rep = coeur.tenter_code(2, ouverture["code"])
    assert coeur.creation(2, tel.creer(WA.deb64u(rep["options"]["challenge"], 100), ORIGINE)) == {"etat": "interrompu"}
    # et l'option « exclure » du navigateur la liste déjà
    assert WA.b64u(tel.id) in [c["id"] for c in rep["options"]["excludeCredentials"]]


def test_expiration_pendant_l_attente(coeur, horloge, boite):
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    rep = coeur.tenter_code(3, ouverture["code"])
    assert 0 < coeur.echeance(3) <= 120
    assert coeur.tick(3) is None
    horloge.avancer(121)
    assert coeur.tick(3) == {"etat": "interrompu"}
    assert coeur.creation(3, Authentificateur(RP).creer(WA.deb64u(rep["options"]["challenge"], 100), ORIGINE)) == {
        "etat": "erreur"}


def test_deconnexion_du_nouveau_navigateur_annule(coeur, boite):
    ouverture = coeur.ouvrir("Nom", "habitant", "ha")
    coeur.tenter_code(3, ouverture["code"])
    coeur.oublier_connexion(3)
    assert coeur.etat_ouverture() == {"ouverte": False}
    assert boite.messages("ha")[-1]["raison"] == "deconnecte"


def test_deconnexion_avant_le_bon_code_laisse_l_ouverture(coeur):
    coeur.ouvrir("Nom", "habitant", "ha")
    coeur.oublier_connexion(3)
    assert coeur.etat_ouverture()["ouverte"]


# Tickets

def test_ticket_expire_et_inconnu(coeur, horloge, boite):
    appairer(coeur)
    ticket = [m["ticket"] for c, m, _ in boite.evenements if "ticket" in m][0]
    horloge.avancer(61)
    assert coeur.consommer_ticket(ticket) is None
    for mauvais in (None, "", "x" * 200, 12, "inconnu"):
        assert coeur.consommer_ticket(mauvais) is None


# Défis du propriétaire

def test_confirmation_par_cle_du_proprietaire(coeur, boite):
    identite, tel = proprietaire(coeur, boite)
    ouverture = coeur.ouvrir("Tablette", "habitant", identite)
    rep = coeur.tenter_code(5, ouverture["code"])
    coeur.creation(5, Authentificateur(RP).creer(WA.deb64u(rep["options"]["challenge"], 100), ORIGINE))
    preuve = signer_defi(coeur, tel, 9, identite, "confirmer")
    res = coeur.preuve(9, preuve)
    assert res["action"] == "confirmer" and res["appareil"]["nom"] == "Tablette"
    assert len(coeur.appareils.tous()) == 2


def test_defi_confirmer_exige_une_ouverture_en_attente(coeur, boite):
    identite, _ = proprietaire(coeur, boite)
    assert cause(coeur.defi, 9, identite, "confirmer") == "etat"
    coeur.ouvrir("X", "habitant", identite)
    assert cause(coeur.defi, 9, identite, "confirmer") == "etat"


def test_defi_a_usage_unique(coeur, boite):
    identite, tel = proprietaire(coeur, boite)
    autre, _, _ = appairer(coeur, nom="Autre", role="habitant", acteur=identite, conn=2)
    preuve = signer_defi(coeur, tel, 9, identite, "revoquer", autre["id"])
    coeur.preuve(9, preuve)
    assert cause(coeur.preuve, 9, preuve) == "defi"


def test_defi_lie_a_la_connexion(coeur, boite):
    identite, tel = proprietaire(coeur, boite)
    autre, _, _ = appairer(coeur, nom="Autre", role="habitant", acteur=identite, conn=2)
    preuve = signer_defi(coeur, tel, 9, identite, "revoquer", autre["id"])
    assert cause(coeur.preuve, 10, preuve) == "defi"
    assert coeur.appareils.get(autre["id"]), "l'autre connexion n'a rien révoqué"


def test_defi_expire(coeur, boite, horloge):
    identite, tel = proprietaire(coeur, boite)
    autre, _, _ = appairer(coeur, nom="Autre", role="habitant", acteur=identite, conn=2)
    preuve = signer_defi(coeur, tel, 9, identite, "revoquer", autre["id"])
    horloge.avancer(61)
    assert cause(coeur.preuve, 9, preuve) == "defi"


def test_un_seul_defi_en_attente_par_connexion(coeur, boite):
    identite, tel = proprietaire(coeur, boite)
    a, _, _ = appairer(coeur, nom="A", role="habitant", acteur=identite, conn=2)
    b, _, _ = appairer(coeur, nom="B", role="habitant", acteur=identite, conn=3)
    ancien = signer_defi(coeur, tel, 9, identite, "revoquer", a["id"])
    signer_defi(coeur, tel, 9, identite, "revoquer", b["id"])
    # l'ancien défi est remplacé : une signature faite pour lui ne vaut plus
    assert cause(coeur.preuve, 9, ancien) == "preuve"
    assert coeur.appareils.get(a["id"]) and coeur.appareils.get(b["id"])


def test_preuve_lie_la_cible(coeur, boite):
    """Le défi nomme la cible : la signature ne peut pas servir à une autre action."""
    identite, tel = proprietaire(coeur, boite)
    a, _, _ = appairer(coeur, nom="A", role="habitant", acteur=identite, conn=2)
    b, _, _ = appairer(coeur, nom="B", role="habitant", acteur=identite, conn=3)
    preuve = signer_defi(coeur, tel, 9, identite, "revoquer", a["id"])
    res = coeur.preuve(9, preuve)
    assert res["cible"] == a["id"] and coeur.appareils.get(b["id"])


@pytest.mark.parametrize("variante", ["origine", "rp", "uv", "compteur", "cle", "challenge", "id"])
def test_preuve_refus(coeur, boite, variante):
    identite, tel = proprietaire(coeur, boite)
    cible, _, _ = appairer(coeur, nom="Cible", role="habitant", acteur=identite, conn=2)
    options = coeur.defi(9, identite, "revoquer", cible["id"])
    challenge = WA.deb64u(options["challenge"], 100)
    if variante == "origine":
        preuve = tel.signer(challenge, "https://pirate.example")
    elif variante == "rp":
        preuve = tel.signer(challenge, ORIGINE, rp_id="pirate.example")
    elif variante == "uv":
        preuve = tel.signer(challenge, ORIGINE, drapeaux=WA.DRAPEAU_UP)
    elif variante == "compteur":
        preuve = tel.signer(challenge, ORIGINE, compteur=0)
        coeur.appareils.maj(identite[4:], credential={**coeur.appareils.get(identite[4:])["credential"], "compteur": 50})
    elif variante == "cle":
        preuve = Authentificateur(RP).signer(challenge, ORIGINE)
        preuve["id"] = WA.b64u(tel.id)
    elif variante == "challenge":
        preuve = tel.signer(os.urandom(32), ORIGINE)
    else:
        preuve = tel.signer(challenge, ORIGINE)
        preuve["id"] = WA.b64u(b"inconnu")
    assert cause(coeur.preuve, 9, preuve) == "preuve"
    assert coeur.appareils.get(cible["id"]), "rien n'est révoqué sur une preuve refusée"
    # le défi est consommé même après un refus
    assert cause(coeur.preuve, 9, tel.signer(challenge, ORIGINE)) == "defi"


@pytest.mark.parametrize("corps", [None, "x", [], {}, {"id": 1}])
def test_preuve_corps_malformes(coeur, boite, corps):
    identite, _ = proprietaire(coeur, boite)
    cible, _, _ = appairer(coeur, nom="C", role="habitant", acteur=identite, conn=2)
    coeur.defi(9, identite, "revoquer", cible["id"])
    assert cause(coeur.preuve, 9, corps) == "preuve"


def test_compteur_de_la_cle_du_proprietaire_avance(coeur, boite):
    identite, tel = proprietaire(coeur, boite)
    avant = coeur.appareils.get(identite[4:])["credential"]["compteur"]
    cible, _, _ = appairer(coeur, nom="C", role="habitant", acteur=identite, conn=2)
    coeur.preuve(9, signer_defi(coeur, tel, 9, identite, "revoquer", cible["id"]))
    assert coeur.appareils.get(identite[4:])["credential"]["compteur"] > avant


def test_defis_reserves_au_proprietaire(coeur, boite):
    identite, _ = proprietaire(coeur, boite)
    habitant, _, _ = appairer(coeur, nom="H", role="habitant", acteur=identite, conn=2)
    assert cause(coeur.defi, 9, AW.identite_de(habitant["id"]), "revoquer", identite[4:]) == "droit"
    assert cause(coeur.defi, 9, "web:inconnu", "revoquer", "x") == "droit"


def test_defi_revoquer_cible_invalide_ou_soi_meme(coeur, boite):
    identite, _ = proprietaire(coeur, boite)
    assert cause(coeur.defi, 9, identite, "revoquer", identite[4:]) == "cible"
    assert cause(coeur.defi, 9, identite, "revoquer", "inconnu") == "cible"
    assert cause(coeur.defi, 9, identite, "revoquer", None) == "cible"
    assert cause(coeur.defi, 9, identite, "supprimer", "x") == "action"


def test_limite_de_defis_simultanes(coeur, boite):
    identite, _ = proprietaire(coeur, boite)
    cible, _, _ = appairer(coeur, nom="C", role="habitant", acteur=identite, conn=2)
    for conn in range(100, 100 + AW.DEFIS_MAX):
        coeur.defi(conn, identite, "revoquer", cible["id"])
    assert cause(coeur.defi, 999, identite, "revoquer", cible["id"]) == "limite"
    coeur.defi(100, identite, "revoquer", cible["id"])  # une connexion déjà présente peut renouveler


# Révocation et oubli

def test_revoquer_coupe_les_sessions(coeur, boite):
    identite, _ = proprietaire(coeur, boite)
    cible, _, _ = appairer(coeur, nom="C", role="habitant", acteur=identite, conn=2)
    coeur.revoquer(cible["id"])
    assert boite.revoques == [AW.identite_de(cible["id"])] and coeur.appareils.get(cible["id"]) is None
    assert cause(coeur.revoquer, cible["id"]) == "cible"


def test_oublier_signale_le_dernier_proprietaire(coeur, boite):
    identite, _ = proprietaire(coeur, boite)
    autre, _, _ = appairer(coeur, nom="Second", role="administrateur", acteur=identite, conn=2)
    # un deuxième propriétaire n'est pas ouvrable depuis HA, mais l'est par un propriétaire
    assert coeur.oublier(AW.identite_de(autre["id"])) is False
    assert coeur.oublier(identite) is True
    assert cause(coeur.oublier, identite) == "cible"


def test_vue_marque_l_appareil_courant_et_ne_contient_aucun_secret(coeur, boite):
    identite, _ = proprietaire(coeur, boite)
    cible, _, _ = appairer(coeur, nom="C", role="habitant", acteur=identite, conn=2)
    vue = coeur.vue(identite)
    assert sorted(v["courant"] for v in vue) == [False, True]
    assert [v["id"] for v in vue if v["courant"]] == [identite[4:]]
    assert all(set(v) == {"id", "nom", "role", "cree", "dernier", "expire", "courant"} for v in vue)


def test_fichier_ecrit_atomiquement_sans_residu(coeur, tmp_path):
    appairer(coeur)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["appareils_web.json"]


def test_reinitialiser_supprime_le_fichier(tmp_path, monkeypatch, capsys):
    import assistant as A
    monkeypatch.setattr(A, "DONNEES", tmp_path)
    (tmp_path / "appareils_web.json").write_text("{}", encoding="utf-8")
    assert AW.principal(["--reinitialiser"]) == 0
    assert not (tmp_path / "appareils_web.json").exists()
    assert AW.principal(["--reinitialiser"]) == 0
