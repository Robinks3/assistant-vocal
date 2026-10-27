"""Journal du client web (S-W2) : visibilité par spectateur, niveaux, figement, rétention, effacement."""
import json
from datetime import datetime, timedelta

import pytest

import assistant as A
import journal_web as J
import maison

PROPRIO = J.Spectateur("administrateur", "web:aaaa1111", maison.CLE_PROPRIETAIRE)
HABITANT = J.Spectateur("habitant", "web:bbbb2222", "web:bbbb2222")
INVITE = J.Spectateur("invite", "web:cccc3333", "web:cccc3333")
INCONNU = J.Spectateur("", "web:dddd4444", "web:dddd4444")


def ligne(texte="allume la lampe du bureau", personne="camille", appareil="appareil:tab1", niveau="tout",
          actions="light.turn_on ['light.salon_plafond']", horodatage="2026-10-27T09:15:00", **autres):
    base = {"horodatage": horodatage, "texte": texte, "voie": "dictionnaire", "total_s": "0.42",
            "reponse": "C'est fait.", "actions": actions, "appareil": appareil, "personne": personne,
            "role": "habitant", "id": "0123456789ab", "niveau": niveau, "statut": "ok", "canal": "voix",
            "etapes": [{"nom": "entendu", "t": "09:14:59"}, {"nom": "fait", "t": "09:15:00"}]}
    base.update(autres)
    return base


def ecrire(dossier, jour, *lignes):
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"assistant-{jour}.jsonl").write_text(
        "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lignes), encoding="utf-8")


# Qui voit quoi

def test_auteur_voit_tout_le_detail_et_ses_etapes():
    s = J.Spectateur("habitant", "web:bbbb2222", "camille")
    p = J.projeter(ligne(niveau="discret"), s)
    assert p["mien"] and p["detail"] == "complet"
    assert p["phrase"] == "allume la lampe du bureau" and p["reponse"] == "C'est fait."
    assert [e["nom"] for e in p["etapes"]] == ["entendu", "fait"]
    assert p["niveau"] == "discret"


def test_entree_de_mon_appareil_est_a_moi_sans_personne():
    p = J.projeter(ligne(personne=None, appareil="web:bbbb2222"), HABITANT)
    assert p["mien"] is True and p["detail"] == "complet"


def test_proprietaire_retrouve_ses_demandes_de_tous_ses_appareils():
    p = J.projeter(ligne(personne=maison.CLE_PROPRIETAIRE, appareil="appareil:tel1"), PROPRIO)
    assert p["mien"] is True


def test_niveau_tout_montre_la_phrase_et_la_reponse_aux_autres_mais_pas_les_etapes():
    p = J.projeter(ligne(niveau="tout"), PROPRIO)
    assert p["detail"] == "complet" and p["mien"] is False
    assert p["phrase"] and p["reponse"]
    assert "etapes" not in p and "niveau" not in p


def test_niveau_action_cache_la_phrase_et_la_reponse():
    p = J.projeter(ligne(niveau="action"), PROPRIO)
    assert p["detail"] == "action" and p["actions"]
    assert "phrase" not in p and "reponse" not in p and "etapes" not in p
    assert "lampe du bureau" not in json.dumps(p)


def test_niveau_discret_montre_seulement_l_existence_au_proprietaire():
    p = J.projeter(ligne(niveau="discret"), PROPRIO)
    assert set(p) == {"id", "horodatage", "mien", "detail"} and p["detail"] == "aucun"
    brut = json.dumps(p)
    assert "lampe" not in brut and "camille" not in brut and "tab1" not in brut


def test_niveau_discret_est_invisible_pour_un_habitant():
    assert J.projeter(ligne(niveau="discret"), HABITANT) is None


def test_niveau_manquant_ou_absurde_vaut_discret():
    assert J.projeter({k: v for k, v in ligne().items() if k != "niveau"}, HABITANT) is None
    assert J.projeter(ligne(niveau="partout"), HABITANT) is None
    assert J.projeter(ligne(niveau=["tout"]), HABITANT) is None


def test_habitant_voit_les_autres_seulement_quand_l_auteur_le_permet():
    assert J.projeter(ligne(niveau="tout"), HABITANT)["detail"] == "complet"
    assert J.projeter(ligne(niveau="action"), HABITANT)["detail"] == "action"


@pytest.mark.parametrize("spect", [INVITE, INCONNU])
@pytest.mark.parametrize("niveau", ["tout", "action", "discret"])
def test_invite_et_role_inconnu_ne_voient_rien_des_autres(spect, niveau):
    assert J.projeter(ligne(niveau=niveau), spect) is None


def test_invite_voit_ses_propres_entrees():
    p = J.projeter(ligne(personne=None, appareil="web:cccc3333"), INVITE)
    assert p["mien"] and p["detail"] == "complet"


def test_la_sante_reste_discrete_pour_les_autres_meme_au_niveau_tout():
    e = ligne(texte="quelle est ma tension ce matin", niveau="tout", actions="")
    assert J.projeter(e, HABITANT) is None
    p = J.projeter(e, PROPRIO)
    assert p["detail"] == "aucun" and "tension" not in json.dumps(p)


def test_la_sante_reste_visible_pour_son_auteur():
    e = ligne(texte="quelle est ma tension ce matin", niveau="tout", personne=None, appareil="web:bbbb2222")
    assert J.projeter(e, HABITANT)["phrase"] == "quelle est ma tension ce matin"


def test_un_refus_de_securite_suit_le_niveau_de_son_auteur():
    refus = ligne(niveau="action", voie="dictionnaire refus", statut="refus",
                  actions="light.turn_on ['light.chambre_sacha_plafond'] (refusé : sécurité)")
    p = J.projeter(refus, PROPRIO)
    assert p["statut"] == "refus" and p["motif"] == "refusé : sécurité"
    assert "phrase" not in p
    assert J.projeter({**refus, "niveau": "discret"}, HABITANT) is None
    assert set(J.projeter({**refus, "niveau": "discret"}, PROPRIO)) == {"id", "horodatage", "mien", "detail"}


def test_statut_et_id_des_anciennes_entrees():
    ancienne = {k: v for k, v in ligne(voie="rien compris").items() if k not in ("id", "statut", "etapes")}
    assert J.statut(ancienne) == "non compris"
    assert len(J.id_de(ancienne)) == 12 and J.id_de(ancienne) == J.id_de(dict(ancienne))
    assert "lampe" not in J.id_de(ancienne)
    assert J.projeter(ancienne, PROPRIO)["etapes"] == [] if J.est_a_moi(ancienne, PROPRIO) else True


def test_la_projection_n_expose_jamais_la_ligne_brute():
    p = J.projeter(ligne(niveau="tout"), PROPRIO)
    for interdit in ("personne", "role", "tab1", "camille", "appareil:"):
        assert interdit not in json.dumps(p), interdit


# Lecture par jours et rétention

def test_lire_ne_rend_que_ce_que_le_spectateur_a_le_droit_de_voir(tmp_path):
    maintenant = datetime(2026, 10, 27, 12, 0, tzinfo=maison.ZONE)
    ecrire(tmp_path, "2026-10-27",
           ligne(id="000000000001", niveau="discret", horodatage="2026-10-27T08:00:00"),
           ligne(id="000000000002", niveau="tout", horodatage="2026-10-27T09:00:00"),
           ligne(id="000000000003", niveau="action", horodatage="2026-10-27T10:00:00"))
    entrees, plus = J.lire(tmp_path, HABITANT, maintenant=maintenant)
    assert [e["id"] for e in entrees] == ["000000000003", "000000000002"] and plus is None
    entrees, _ = J.lire(tmp_path, PROPRIO, maintenant=maintenant)
    assert [e["id"] for e in entrees] == ["000000000003", "000000000002", "000000000001"]
    assert J.lire(tmp_path, INVITE, maintenant=maintenant)[0] == []


def test_lire_ignore_les_fichiers_de_plus_de_30_jours(tmp_path):
    maintenant = datetime(2026, 10, 27, 12, 0, tzinfo=maison.ZONE)
    ecrire(tmp_path, "2026-09-26", ligne(id="000000000010"))
    ecrire(tmp_path, "2026-09-27", ligne(id="000000000011"))
    ids = [e["id"] for e in J.lire(tmp_path, PROPRIO, maintenant=maintenant, jours=30)[0]]
    assert ids == ["000000000011"]


def test_lire_pagine_par_jours(tmp_path):
    maintenant = datetime(2026, 10, 27, 12, 0, tzinfo=maison.ZONE)
    for k in range(10):
        jour = (maintenant - timedelta(days=k)).strftime("%Y-%m-%d")
        ecrire(tmp_path, jour, ligne(id=f"{k:012x}", horodatage=jour + "T10:00:00"))
    premiere, plus = J.lire(tmp_path, PROPRIO, maintenant=maintenant)
    assert len(premiere) == J.JOURS_PAR_PAGE and plus == "2026-10-20"
    suite, plus2 = J.lire(tmp_path, PROPRIO, reprise=plus, maintenant=maintenant)
    # La page suivante reprend au jour annoncé, aucun jour n'est sauté.
    assert [e["id"] for e in suite] == [f"{k:012x}" for k in (7, 8, 9)]
    assert plus2 is None


def test_lire_s_arrete_entre_deux_jours_quand_le_plafond_est_atteint(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "ENTREES_MAX", 3)
    maintenant = datetime(2026, 10, 27, 12, 0, tzinfo=maison.ZONE)
    ecrire(tmp_path, "2026-10-27", *[ligne(id=f"{k:012x}") for k in range(5)])
    ecrire(tmp_path, "2026-10-26", ligne(id="00000000ffff"))
    entrees, plus = J.lire(tmp_path, PROPRIO, maintenant=maintenant)
    assert len(entrees) == 5 and plus == "2026-10-26"
    suite, fin = J.lire(tmp_path, PROPRIO, reprise=plus, maintenant=maintenant)
    assert [e["id"] for e in suite] == ["00000000ffff"] and fin is None


def test_lire_ignore_une_date_mal_formee_et_les_lignes_cassees(tmp_path):
    maintenant = datetime(2026, 10, 27, 12, 0, tzinfo=maison.ZONE)
    dossier = tmp_path
    dossier.mkdir(exist_ok=True)
    (dossier / "assistant-2026-10-27.jsonl").write_text(
        "pas du json\n[1,2]\n" + json.dumps(ligne()) + "\n", encoding="utf-8")
    entrees, _ = J.lire(dossier, PROPRIO, reprise="../../etc", maintenant=maintenant)
    assert len(entrees) == 1


# Niveaux

def test_niveaux_valeur_par_defaut_et_persistance(tmp_path):
    n = J.Niveaux(tmp_path / "n.json")
    assert n.niveau_de("camille") == "discret"
    n.definir("Camille", "action")
    assert J.Niveaux(tmp_path / "n.json").niveau_de("camille") == "action"
    with pytest.raises(ValueError):
        n.definir("camille", "tout le monde")
    assert n.niveau_de("camille") == "action"


def test_niveaux_fichier_corrompu_vaut_discret(tmp_path):
    f = tmp_path / "n.json"
    f.write_text("{pas du json", encoding="utf-8")
    assert J.Niveaux(f).niveau_de("camille") == "discret"
    f.write_text(json.dumps({"niveaux": {"camille": {"niveau": "n'importe quoi"}}}), encoding="utf-8")
    assert J.Niveaux(f).niveau_de("camille") == "discret"


def test_cle_auteur():
    assert J.cle_auteur("Camille", "appareil:t1") == "camille"
    assert J.cle_auteur(None, "appareil:t1") == "appareil:t1"
    assert J.cle_auteur("inconnu", "appareil:t1") == "appareil:t1"
    assert J.cle_auteur(None, None) == "local"


# Écriture par journaliser

@pytest.fixture
def journal_ecrit(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "JOURNAL", tmp_path / "journal" / "latences.csv")
    monkeypatch.setattr(A, "_PURGE", {"jour": None})
    return tmp_path / "journal"


def journaliser_comme(personne, appareil, canal="voix", voie="dictionnaire", actions=("light.turn_on ['light.salon_plafond']",),
                      texte="allume la lampe du bureau", parole="C'est fait."):
    jeton = A.REQUETE.set(A.Requete(personne=personne, appareil=appareil, canal=canal))
    try:
        A.journaliser(texte, voie, 0.5, 0.25, 0.25, parole, list(actions))
    finally:
        A.REQUETE.reset(jeton)


def lignes_ecrites(dossier):
    sortie = []
    for f in sorted(dossier.glob("assistant-*.jsonl")):
        sortie += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    return sortie


def test_journaliser_ajoute_id_niveau_statut_canal_et_etapes(journal_ecrit):
    journaliser_comme("camille", "appareil:tab1")
    (e,) = lignes_ecrites(journal_ecrit)
    assert len(e["id"]) == 12 and e["niveau"] == "discret" and e["statut"] == "ok" and e["canal"] == "voix"
    assert [x["nom"] for x in e["etapes"]] == ["entendu", "compris", "fait", "repondu"]
    assert e["etapes"][0]["t"] <= e["etapes"][-1]["t"]


def test_journaliser_fige_le_niveau_au_moment_de_l_ecriture(journal_ecrit, niveaux_web_temporaires):
    journaliser_comme("camille", "appareil:tab1")
    niveaux_web_temporaires.definir("camille", "tout")
    journaliser_comme("camille", "appareil:tab1")
    niveaux_web_temporaires.definir("camille", "discret")
    journaliser_comme("camille", "appareil:tab1")
    avant, apres, dernier = lignes_ecrites(journal_ecrit)
    assert (avant["niveau"], apres["niveau"], dernier["niveau"]) == ("discret", "tout", "discret")
    # Repasser en Discret ne referme pas ce qui a été écrit en Tout, passer en Tout n'ouvre pas le passé.
    assert J.projeter(avant, HABITANT) is None
    assert J.projeter(apres, HABITANT)["phrase"]


def test_journaliser_reprend_l_id_de_la_demande_annoncee(journal_ecrit):
    jeton = A.ID_DEMANDE.set("abcdef012345")
    try:
        journaliser_comme("camille", "appareil:tab1")
    finally:
        A.ID_DEMANDE.reset(jeton)
    assert lignes_ecrites(journal_ecrit)[0]["id"] == "abcdef012345"


def test_journaliser_un_refus_porte_le_statut_refus(journal_ecrit):
    journaliser_comme("camille", "appareil:tab1", voie="dictionnaire refus",
                      actions=("light.turn_on ['light.chambre_sacha_plafond'] (refusé : sécurité)",))
    (e,) = lignes_ecrites(journal_ecrit)
    assert e["statut"] == "refus" and J.motif(e) == "refusé : sécurité"


def test_journaliser_sans_requete_donne_une_entree_du_micro_du_pc(journal_ecrit):
    A.journaliser("quelle heure est-il", "dictionnaire", 0.1, 0.1, 0.1, "Il est midi.", [])
    (e,) = lignes_ecrites(journal_ecrit)
    assert e["appareil"] is None and e["canal"] == "" and e["niveau"] == "discret"


# Effacement

def test_effacer_retire_mes_entrees_et_garde_celles_des_autres(tmp_path):
    ecrire(tmp_path, "2026-10-26",
           ligne(id="000000000001", personne=maison.CLE_PROPRIETAIRE, appareil="appareil:tel1"),
           ligne(id="000000000002", personne="camille"))
    ecrire(tmp_path, "2026-10-27", ligne(id="000000000003", personne=maison.CLE_PROPRIETAIRE),
           ligne(id="000000000004", personne=None, appareil="web:aaaa1111"),
           ligne(id="000000000005", personne=None, appareil="appareil:salon"))
    retirees = J.effacer(tmp_path, PROPRIO)
    assert sorted(e["id"] for e in retirees) == ["000000000001", "000000000003", "000000000004"]
    restant = [json.loads(l)["id"] for f in sorted(tmp_path.glob("assistant-*.jsonl"))
               for l in f.read_text(encoding="utf-8").splitlines()]
    assert restant == ["000000000002", "000000000005"]


def test_effacer_supprime_un_fichier_devenu_vide_et_ne_touche_pas_aux_autres(tmp_path):
    ecrire(tmp_path, "2026-10-26", ligne(personne=maison.CLE_PROPRIETAIRE))
    ecrire(tmp_path, "2026-10-27", ligne(personne="camille"))
    J.effacer(tmp_path, PROPRIO)
    assert not (tmp_path / "assistant-2026-10-26.jsonl").exists()
    assert (tmp_path / "assistant-2026-10-27.jsonl").exists()


def test_effacer_par_un_habitant_ne_touche_que_ses_entrees(tmp_path):
    ecrire(tmp_path, "2026-10-27", ligne(id="000000000001", personne=None, appareil="web:bbbb2222"),
           ligne(id="000000000002", personne=maison.CLE_PROPRIETAIRE))
    assert [e["id"] for e in J.effacer(tmp_path, HABITANT)] == ["000000000001"]
    assert [e["id"] for e in J.lire(tmp_path, PROPRIO, maintenant=datetime(2026, 10, 27, 12, tzinfo=maison.ZONE))[0]] \
        == ["000000000002"]
