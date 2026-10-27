"""Amorçage local du premier propriétaire du client web (serveur 0.54.1)."""
import json

import appairage_web as AW
import webauthn as WA
from aide_webauthn import Authentificateur
from test_appairage_web import ORIGINE, RP, Boite, Horloge, appairer


def monter(tmp_path):
    horloge, boite, differes = Horloge(), Boite(), []
    amorcage = None

    def evenement(cible, message, conn=None):
        boite.evenement(cible, message, conn)
        if cible == "ha" and amorcage:
            amorcage.evenement(message)

    coeur = AW.AppairageWeb(tmp_path / "appareils_web.json", RP, {ORIGINE}, nom="Iris", horloge=horloge,
                            sur_evenement=evenement, sur_revocation=boite.revocation, journal=boite.journal.append)
    amorcage = AW.AmorcageLocal(coeur, tmp_path / "amorcage_web.json", differer=differes.append)
    return coeur, amorcage, horloge, boite, differes


def code_du_fichier(tmp_path):
    return json.loads((tmp_path / "amorcage_web.json").read_text(encoding="utf-8"))["code"]


def jusqu_a_l_attente(coeur, code, conn=1):
    rep = coeur.tenter_code(conn, code)
    assert rep["etat"] == "creation"
    tel = Authentificateur(RP)
    assert coeur.creation(conn, tel.creer(WA.deb64u(rep["options"]["challenge"], 100), ORIGINE))["etat"] == "attente"


def test_amorcage_confirme_seul_et_efface_le_code(tmp_path):
    coeur, amorcage, _, boite, differes = monter(tmp_path)
    duree = amorcage.ouvrir("Téléphone de test")
    assert duree == AW.VALIDITE_AMORCAGE_MAX_S
    code = code_du_fichier(tmp_path)
    assert len(code) == 6 and code.isdigit()
    jusqu_a_l_attente(coeur, code)
    assert not coeur.appareils.a_proprietaire(), "la confirmation part après la réponse « attente »"
    assert len(differes) == 1
    differes.pop()()
    assert coeur.appareils.a_proprietaire()
    assert any("ticket" in m for c, m, _ in boite.evenements if c == "ouverture")
    assert not (tmp_path / "amorcage_web.json").exists()
    assert not any(code in ligne for ligne in boite.journal)


def test_pas_d_amorcage_si_un_proprietaire_existe(tmp_path):
    coeur, amorcage, _, _, _ = monter(tmp_path)
    appairer(coeur)
    assert amorcage.ouvrir("Téléphone de test") is None
    assert not (tmp_path / "amorcage_web.json").exists()
    assert coeur.etat_ouverture() == {"ouverte": False}


def test_duree_plafonnee_et_reservee_a_ha(tmp_path):
    coeur, _, _, _, _ = monter(tmp_path)
    assert coeur.ouvrir("Téléphone de test", "administrateur", "ha", duree_s=10 ** 6)["duree"] == \
        AW.VALIDITE_AMORCAGE_MAX_S
    assert coeur.ouvrir("Téléphone de test", "administrateur", "ha", duree_s=1)["duree"] == AW.VALIDITE_CODE_S
    appareil, _, _ = appairer(coeur)
    try:
        coeur.ouvrir("Autre", "invite", AW.identite_de(appareil["id"]), duree_s=600)
        assert False, "un propriétaire web ne choisit pas la durée"
    except AW.ErreurAppairage as e:
        assert e.cause == "droit"


def test_une_autre_ouverture_n_est_pas_confirmee(tmp_path):
    coeur, amorcage, _, _, differes = monter(tmp_path)
    amorcage.ouvrir("Téléphone de test")
    autre = coeur.ouvrir("Remplaçant", "administrateur", "ha")  # remplace l'ouverture d'amorçage
    assert not (tmp_path / "amorcage_web.json").exists()
    jusqu_a_l_attente(coeur, autre["code"])
    for fn in differes:
        fn()
    assert not coeur.appareils.a_proprietaire(), "seule l'ouverture d'amorçage se confirme seule"


def test_expiration_efface_le_fichier(tmp_path):
    coeur, amorcage, horloge, _, _ = monter(tmp_path)
    duree = amorcage.ouvrir("Téléphone de test")
    horloge.avancer(duree + 1)
    amorcage.verifier()
    assert not (tmp_path / "amorcage_web.json").exists()
    assert coeur.etat_ouverture() == {"ouverte": False}
