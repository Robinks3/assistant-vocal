"""S-F3, fermer l'existant (0.39.0) : liste blanche des messages par rôle, historique filtré par destinataire,
journal sans phrases et à rétention bornée, essais du code d'invitation par adresse, Origin d'Ingress.

Prénoms et adresses viennent de config-exemple/ (Sacha propriétaire, Camille habitante) et des plages de
documentation (192.0.2.x, 198.51.100.x). 172.30.32.2 est le proxy Ingress documenté de Home Assistant."""
import asyncio
import csv
import json
import re
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import acces
import assistant as A
import maison
import serveur_satellite as S

PROXY = "172.30.32.2"
RACINE = Path(__file__).resolve().parents[2]


def appareils_avec(tmp_path, *entrees):
    app = acces.Appareils(tmp_path, {})
    app.liste = [dict({"nom": "Tab", "empreinte": "x", "cree": "2026-10-26 10:00:00", "dernier": ""}, **e)
                 for e in entrees]
    return app


# ---------------------------------------------------------------------------------------------------------------
# Point 5 : Origin d'Ingress
# ---------------------------------------------------------------------------------------------------------------

ORIGINE_HA = "https://ha.exemple.ts.net"


def test_ingress_origine_egale_a_x_forwarded_host_acceptee_depuis_le_proxy():
    entetes = {"Origin": ORIGINE_HA, "Host": f"{PROXY}:8099", "X-Forwarded-Host": "ha.exemple.ts.net"}
    assert acces.origine_acceptee(entetes, PROXY) is True
    assert acces.origine_acceptee(entetes, "::ffff:" + PROXY) is False  # forme non reconnue : refus, jamais d'ouverture


def test_ingress_sans_x_forwarded_host_depuis_le_proxy_est_refusee():
    entetes = {"Origin": ORIGINE_HA, "Host": f"{PROXY}:8099"}
    assert acces.origine_acceptee(entetes, PROXY) is False


def test_ingress_hors_proxy_sans_en_tete_origine_etrangere_refusee():
    entetes = {"Origin": "https://autre.exemple.org", "Host": "assistant.exemple.ts.net"}
    assert acces.origine_acceptee(entetes, "192.0.2.10") is False
    # Origin égale à Host reste acceptée de n'importe où, comme avant.
    assert acces.origine_acceptee({"Origin": "https://assistant.exemple.ts.net", "Host": "assistant.exemple.ts.net"},
                                  "192.0.2.10") is True


@pytest.mark.parametrize("ip", ["192.0.2.10", "198.51.100.7", "127.0.0.1", "", None])
def test_ingress_en_tete_present_mais_adresse_hors_proxy_refusee(ip):
    """Un client quelconque ne peut pas inventer X-Forwarded-Host pour faire passer l'Origin d'une page étrangère."""
    entetes = {"Origin": "https://pirate.exemple.org", "Host": "assistant.exemple.ts.net",
               "X-Forwarded-Host": "pirate.exemple.org"}
    assert acces.origine_acceptee(entetes, ip) is False


def test_origine_sans_adresse_ignore_x_forwarded_host():
    entetes = {"Origin": ORIGINE_HA, "Host": f"{PROXY}:8099", "X-Forwarded-Host": "ha.exemple.ts.net"}
    assert acces.origine_acceptee(entetes) is False


# ---------------------------------------------------------------------------------------------------------------
# Point 1 : liste blanche des types de messages par rôle
# ---------------------------------------------------------------------------------------------------------------

TYPES_ANDROID = {"appareils", "appairer", "refuser_appareil", "revoquer", "manque", "retour", "llm", "ha", "parler",
                 "meteo_mer", "vent_mesure", "transcription", "mode", "historique", "cerveau", "lecture_finie",
                 "reveil", "transcrire", "sante", "sante_periode", "sante_seances", "sante_seance",
                 "sante_records", "sante_jour", "vision"}
TYPES_CLIENT_ADMIN = {"appairer", "refuser_appareil", "changer_role", "revoquer", "inviter", "annuler_invitation"}


def test_la_table_a_une_entree_par_role_et_les_roles_emboites():
    assert set(acces.TYPES_PAR_ROLE) == set(acces.ROLES)
    t = acces.TYPES_PAR_ROLE
    assert t["invite"] < t["partage"] < t["habitant"] < t["administrateur"]


def test_chaque_type_envoye_par_l_appli_android_est_permis_a_un_role():
    tous = acces.TYPES_PAR_ROLE["administrateur"]
    assert TYPES_ANDROID <= tous


def test_chaque_type_trouve_dans_les_sources_kotlin_est_dans_la_table():
    """Garde-fou contre un nouveau message de l'appli oublié dans la table (il serait refusé sur le port chiffré)."""
    trouves = set()
    for f in (RACINE / "android" / "app" / "src" / "main").rglob("*.kt"):
        trouves |= set(re.findall(r'put\("type",\s*"([a-z_]+)"\)', f.read_text(encoding="utf-8")))
    trouves.discard("amorcage")  # poignée de main d'avant la session, traitée avant Satellite.recevoir_texte
    assert trouves, "aucun type trouvé : le motif de recherche ne correspond plus aux sources"
    assert trouves <= acces.TYPES_PAR_ROLE["administrateur"], trouves - acces.TYPES_PAR_ROLE["administrateur"]


def test_chaque_type_du_client_d_administration_est_permis_a_l_administrateur_seul():
    source = (RACINE / "poc" / "admin" / "admin.js").read_text(encoding="utf-8")
    trouves = set(re.findall(r'type:\s*"([a-z_]+)"', source))
    assert trouves == TYPES_CLIENT_ADMIN
    for genre in trouves:
        assert acces.type_permis("administrateur", genre), genre
        for role in ("habitant", "partage", "invite"):
            assert not acces.type_permis(role, genre), (genre, role)


def test_chaque_type_traite_par_le_serveur_figure_dans_la_table():
    """Un type géré dans recevoir_texte mais absent de la table serait mort sur le port chiffré."""
    source = (RACINE / "poc" / "serveur_satellite.py").read_text(encoding="utf-8")
    debut = source.index("async def recevoir_texte")
    corps = source[debut:source.index("\nasync def suivre_satellite")]
    traites = set(re.findall(r'msg\.get\("type"\) == "([a-z_]+)"', corps))
    assert traites, "aucun type trouvé : le motif ne correspond plus au code"
    assert traites <= acces.TYPES_PAR_ROLE["administrateur"], traites - acces.TYPES_PAR_ROLE["administrateur"]


def test_les_types_administrateur_du_serveur_sont_ceux_de_la_table():
    assert S.TYPES_ADMINISTRATEUR == acces.TYPES_ADMINISTRATION


@pytest.mark.parametrize("role,genre,attendu", [
    ("invite", "llm", True), ("invite", "parler", True), ("invite", "historique", True),
    ("invite", "sante_periode", False), ("invite", "vision", False), ("invite", "manque", False),
    ("invite", "appareils", False), ("invite", "inviter", False), ("invite", "mode", False),
    ("partage", "vision", True), ("partage", "sante", False), ("partage", "revoquer", False),
    ("habitant", "sante_jour", True), ("habitant", "vision", True), ("habitant", "changer_role", False),
    ("habitant", "cerveau", False), ("administrateur", "changer_role", True), ("administrateur", "sante", True),
    ("administrateur", "inconnu", False), ("administrateur", "", False), ("administrateur", None, False),
    ("administrateur", ["llm"], False), ("administrateur", {"llm": 1}, False), ("roi", "llm", False),
    (None, "llm", False),
])
def test_type_permis(role, genre, attendu):
    assert acces.type_permis(role, genre) is attendu


def satellite_de_test(monkeypatch, identite, appareils, chiffre=True):
    envoyes = []

    class Moteur:
        satellites = set()
        pages_admin = set()
        essai = False

    moteur = Moteur()
    moteur.appareils = appareils
    sat = object.__new__(S.Satellite)
    sat.moteur, sat.nom, sat.identite, sat.chiffre = moteur, "Tab", identite, chiffre

    async def envoyer(**m):
        envoyes.append(m)
    sat.envoyer = envoyer
    monkeypatch.setattr(S.A, "lire_jsonl", lambda *a, **k: [])
    monkeypatch.setattr(S.A, "lire_historique", lambda n: [])
    return sat, envoyes


def test_invite_type_inconnu_refuse_avec_reponse_claire_et_journal_sans_contenu(monkeypatch, tmp_path, capsys):
    app = appareils_avec(tmp_path, {"id": "i1", "role": "invite"})
    sat, envoyes = satellite_de_test(monkeypatch, "appareil:i1", app)
    secret = "PHRASE-SECRETE-4242"
    asyncio.run(sat.recevoir_texte(json.dumps({"type": "inconnu_xyz", "texte": secret, "id": 7})))
    assert envoyes == [{"etat": "refuse", "type": "inconnu_xyz", "message": "type de message non permis pour ce rôle"}]
    journal = capsys.readouterr().out
    assert "inconnu_xyz" in journal and "invite" in journal
    assert secret not in journal


def test_type_long_tronque_dans_la_reponse_et_le_journal(monkeypatch, tmp_path, capsys):
    app = appareils_avec(tmp_path, {"id": "i1", "role": "invite"})
    sat, envoyes = satellite_de_test(monkeypatch, "appareil:i1", app)
    asyncio.run(sat.recevoir_texte(json.dumps({"type": "x" * 5000})))
    assert len(envoyes[0]["type"]) <= 40
    assert len(capsys.readouterr().out) < 400


def test_type_mal_forme_ignore_sans_reponse(monkeypatch, tmp_path):
    app = appareils_avec(tmp_path, {"id": "i1", "role": "invite"})
    sat, envoyes = satellite_de_test(monkeypatch, "appareil:i1", app)
    for texte in ('{"type": []}', '{"type": {}}', '{"type": 3}', '{"texte": "sans type"}'):
        asyncio.run(sat.recevoir_texte(texte))
    assert envoyes == []


@pytest.mark.parametrize("genre", ["sante", "sante_periode", "sante_seances", "sante_seance", "sante_records",
                                   "sante_jour"])
def test_invite_sante_refuse_dans_la_forme_attendue_par_l_appli(monkeypatch, tmp_path, genre):
    app = appareils_avec(tmp_path, {"id": "i1", "role": "invite"})
    sat, envoyes = satellite_de_test(monkeypatch, "appareil:i1", app)
    asyncio.run(sat.recevoir_texte(json.dumps({"type": genre, "id": 12})))
    assert envoyes == [{"etat": genre, "id": 12, "erreur": "santé non permise pour cet appareil"}]


@pytest.mark.parametrize("genre", ["vision", "manque", "sante_jour"])
def test_types_du_foyer_refuses_a_l_invite_et_sante_refusee_au_partage(monkeypatch, tmp_path, genre):
    """L'invité n'a que les types communs, le partage y ajoute le foyer (vision, manque) mais pas la santé."""
    for role, refuse in (("invite", True), ("partage", genre == "sante_jour")):
        app = appareils_avec(tmp_path, {"id": "r1", "role": role})
        sat, envoyes = satellite_de_test(monkeypatch, "appareil:r1", app)
        asyncio.run(sat.recevoir_texte(json.dumps({"type": genre, "id": 3})))
        refus = any(e.get("etat") == "refuse" or "non permise" in str(e.get("erreur", "")) for e in envoyes)
        assert refus is refuse, (role, genre, envoyes)


def test_port_en_clair_garde_son_comportement(monkeypatch, tmp_path):
    """Le port 8765 (ancien accès ?jeton=) ne consulte pas la table : un type inconnu y est ignoré comme avant."""
    app = appareils_avec(tmp_path, {"id": "i1", "role": "invite"})
    sat, envoyes = satellite_de_test(monkeypatch, "appareil:i1", app, chiffre=False)
    asyncio.run(sat.recevoir_texte(json.dumps({"type": "inconnu_xyz"})))
    asyncio.run(sat.recevoir_texte(json.dumps({"type": "historique", "n": 5})))
    assert envoyes == [{"etat": "historique", "entrees": []}]


def test_les_types_administrateur_gardent_leur_refus_de_role(monkeypatch, tmp_path):
    """La barrière 0.38.0 passe avant la table : message et forme inchangés, même sur le port chiffré."""
    app = appareils_avec(tmp_path, {"id": "r1", "role": "habitant"})
    sat, envoyes = satellite_de_test(monkeypatch, "appareil:r1", app)
    asyncio.run(sat.recevoir_texte(json.dumps({"type": "revoquer", "id": "a1"})))
    assert envoyes == [{"etat": "refuse", "type": "revoquer", "message": "réservé à un administrateur"}]


def test_habitant_historique_permis(monkeypatch, tmp_path):
    app = appareils_avec(tmp_path, {"id": "r1", "role": "habitant", "personne": "camille"})
    sat, envoyes = satellite_de_test(monkeypatch, "appareil:r1", app)
    asyncio.run(sat.recevoir_texte(json.dumps({"type": "historique", "n": 5})))
    assert envoyes == [{"etat": "historique", "entrees": []}]


# ---------------------------------------------------------------------------------------------------------------
# Point 2 : historique filtré selon le destinataire
# ---------------------------------------------------------------------------------------------------------------

def ligne(appareil, personne, role, texte):
    return {"horodatage": "2026-10-26T10:00:00", "texte": texte, "voie": "dictionnaire", "total_s": "0.10",
            "reponse": "", "actions": "", "appareil": appareil, "personne": personne, "role": role}


L_CAMILLE = ligne("appareil:r1", "camille", "habitant", "phrase de camille")
L_CAMILLE_2 = ligne("appareil:r1b", "camille", "habitant", "phrase de camille sur un autre appareil")
L_SACHA = ligne("appareil:r2", "sacha", "habitant", "phrase de sacha")
L_INVITE = ligne("appareil:i1", None, "invite", "phrase d'un invité")
L_AUTRE_INVITE = ligne("appareil:i2", None, "invite", "phrase d'un autre invité")
L_TABLETTE = ligne("tablette/Salon", None, "partage", "phrase dite à la tablette")
L_LOCAL = ligne(None, None, "local", "phrase dite au micro du PC")
TOUTES = [L_CAMILLE, L_CAMILLE_2, L_SACHA, L_INVITE, L_AUTRE_INVITE, L_TABLETTE, L_LOCAL]


def textes(lignes):
    return [l["texte"] for l in lignes]


def test_administrateur_voit_tout():
    vues = S.entrees_visibles(TOUTES, "administrateur", maison.CLE_PROPRIETAIRE, "sacha/Tel", "sacha")
    assert vues == TOUTES


def test_habitant_voit_sa_personne_et_le_commun_pas_les_autres():
    vues = S.entrees_visibles(TOUTES, "habitant", "appareil:r1", "appareil:r1", "camille")
    assert textes(vues) == [L_CAMILLE["texte"], L_CAMILLE_2["texte"], L_TABLETTE["texte"]]


def test_habitant_sans_personne_ne_voit_que_son_appareil_et_le_commun():
    vues = S.entrees_visibles(TOUTES, "habitant", "appareil:r9", "appareil:r9", None)
    assert textes(vues) == [L_TABLETTE["texte"]]


def test_invite_ne_voit_que_son_appareil():
    vues = S.entrees_visibles(TOUTES, "invite", "appareil:i1", "appareil:i1", None)
    assert textes(vues) == [L_INVITE["texte"]]


def test_partage_ne_voit_que_son_appareil():
    vues = S.entrees_visibles(TOUTES, "partage", "tablette", "tablette/Salon", None)
    assert textes(vues) == [L_TABLETTE["texte"]]


@pytest.mark.parametrize("role", ["habitant", "partage", "invite", "inconnu", None])
def test_entree_sans_appareil_jamais_visible_hors_administrateur(role):
    assert S.entrees_visibles([L_LOCAL], role, "appareil:r1", "appareil:r1", "camille") == []


def test_ligne_sans_champ_appareil_d_avant_0_39_0_reservee_a_l_administrateur():
    ancienne = {"horodatage": "2026-10-20T10:00:00", "texte": "ancienne", "voie": "dictionnaire"}
    assert S.entrees_visibles([ancienne], "habitant", "appareil:r1", "appareil:r1", "camille") == []
    assert S.entrees_visibles([ancienne], "administrateur", "sacha", "sacha/Tel", "sacha") == [ancienne]


class FauxSat:
    def __init__(self, identite, cle):
        self.identite, self._cle, self.recus = identite, cle, []

    def cle_appareil(self):
        return self._cle

    async def envoyer(self, **m):
        self.recus.append(m)


def test_diffusion_de_historique_ajout_filtree_par_destinataire(tmp_path):
    app = appareils_avec(tmp_path,
                         {"id": "r1", "role": "habitant", "personne": "camille"},
                         {"id": "r2", "role": "habitant", "personne": "sacha"},
                         {"id": "i1", "role": "invite"},
                         {"id": "i2", "role": "invite"})
    moteur = object.__new__(S.Moteur)
    moteur.appareils, moteur.noms = app, {}
    camille, sacha = FauxSat("appareil:r1", "appareil:r1"), FauxSat("appareil:r2", "appareil:r2")
    invite1, invite2 = FauxSat("appareil:i1", "appareil:i1"), FauxSat("appareil:i2", "appareil:i2")
    proprio = FauxSat(maison.CLE_PROPRIETAIRE, f"{maison.CLE_PROPRIETAIRE}/Tel")
    page = FauxSat(None, None)
    moteur.satellites = [camille, sacha, invite1, invite2, proprio]
    moteur.pages_admin = {page}
    asyncio.run(moteur.diffuser_historique(L_INVITE))
    assert [len(s.recus) for s in (camille, sacha, invite1, invite2, proprio, page)] == [0, 0, 1, 0, 1, 1]
    recu = invite1.recus[0]
    assert recu["etat"] == "historique_ajout" and recu["entree"]["entendu"] == L_INVITE["texte"]
    assert not {"appareil", "personne", "role"} & set(recu["entree"])  # champs internes jamais envoyés
    asyncio.run(moteur.diffuser_historique(L_CAMILLE))
    assert [len(s.recus) for s in (camille, sacha, invite1, invite2, proprio, page)] == [1, 0, 1, 0, 2, 2]


def test_reponse_au_type_historique_filtree(monkeypatch, tmp_path):
    app = appareils_avec(tmp_path, {"id": "i1", "role": "invite"}, {"id": "i2", "role": "invite"})
    sat, envoyes = satellite_de_test(monkeypatch, "appareil:i1", app)
    sat.moteur.noms = {}
    sat.cle_appareil = lambda: "appareil:i1"
    monkeypatch.setattr(S.A, "lire_historique", lambda n: [L_AUTRE_INVITE, L_INVITE, L_CAMILLE][:n])
    asyncio.run(sat.recevoir_texte(json.dumps({"type": "historique", "n": 30})))
    assert [e["entendu"] for e in envoyes[0]["entrees"]] == [L_INVITE["texte"]]


# ---------------------------------------------------------------------------------------------------------------
# Point 3 : journal sans phrases, rétention et rotation bornées
# ---------------------------------------------------------------------------------------------------------------

@pytest.fixture
def dossier_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "JOURNAL", tmp_path / "journal" / "latences.csv")
    monkeypatch.setattr(A, "_PURGE", {"jour": None})
    monkeypatch.setattr(A, "ROLE_DE", None)
    monkeypatch.delenv("JARVIS_DIAGNOSTIC", raising=False)
    return tmp_path / "journal"


def lire_csv(dossier):
    with open(dossier / "latences.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def test_le_csv_des_durees_ne_contient_aucune_phrase(dossier_journal):
    phrase, reponse = "allume la lampe du salon de Camille", "d'accord, voilà la réponse secrète"
    A.journaliser(phrase, "dictionnaire (allume la lampe)", 0.1, 0.2, 0.3, reponse, ["light.salon"])
    brut = (dossier_journal / "latences.csv").read_text(encoding="utf-8")
    assert phrase not in brut and reponse not in brut and "lampe" not in brut and "light.salon" not in brut
    ligne_csv = lire_csv(dossier_journal)[0]
    assert ligne_csv["voie"] == "dictionnaire" and ligne_csv["issue"] == "ok" and ligne_csv["total_s"] == "0.60"
    assert ligne_csv["actions_nb"] == "1" and ligne_csv["role"] == "local" and ligne_csv["version"] == A.VERSION
    assert list(ligne_csv) == A.COLONNES_LATENCES


def test_l_historique_garde_la_phrase_pour_l_appli(dossier_journal):
    A.journaliser("allume le salon", "ha", 0, 0.1, 0, "voilà", ["light.salon"])
    entree = A.lire_historique(5)[0]
    assert entree["texte"] == "allume le salon" and entree["reponse"] == "voilà" and entree["actions"] == "light.salon"
    assert {"appareil", "personne", "role"} <= set(entree)


def test_role_appareil_et_personne_viennent_de_la_requete(dossier_journal, monkeypatch):
    monkeypatch.setattr(A, "ROLE_DE", lambda identite: "invite" if identite == "appareil:i1" else "habitant")
    jeton = A.REQUETE.set(A.Requete(essai=False, personne=None, appareil="appareil:i1"))
    try:
        A.journaliser("bonjour", "llm (claude)", 0, 0.5, 0, "salut", [])
    finally:
        A.REQUETE.reset(jeton)
    assert lire_csv(dossier_journal)[0]["role"] == "invite"
    assert A.lire_historique(1)[0]["appareil"] == "appareil:i1"


@pytest.mark.parametrize("voie,issue", [
    ("rien compris", "non compris"), ("llm erreur : délai", "erreur"), ("ha refus (protégé)", "refus"),
    ("ha non confirmé", "non confirmé"), ("dictionnaire (x)", "ok")])
def test_issue_de_la_voie(voie, issue):
    assert A.issue_de(voie) == issue


def test_voie_reduite_a_sa_categorie():
    assert A.voie_courte("dictionnaire (allume la lampe du salon)") == "dictionnaire"
    assert A.voie_courte("llm [essai] (phrase)") == "llm"
    assert A.voie_courte("") == "autre"


def test_phrases_masquees_de_la_console_hors_diagnostic(monkeypatch):
    monkeypatch.delenv("JARVIS_DIAGNOSTIC", raising=False)
    monkeypatch.setattr(maison, "JOURNAL", {})
    assert A.pour_console("allume le salon") == "[15 caractères]"
    monkeypatch.setenv("JARVIS_DIAGNOSTIC", "1")
    assert A.pour_console("allume le salon") == "allume le salon"
    monkeypatch.delenv("JARVIS_DIAGNOSTIC")
    monkeypatch.setattr(maison, "JOURNAL", {"phrases_dans_la_console": True})
    assert A.pour_console("allume le salon") == "allume le salon"
    monkeypatch.setattr(maison, "JOURNAL", {"phrases_dans_la_console": "oui"})  # valeur douteuse : fermé
    assert A.pour_console("allume le salon") == "[15 caractères]"


def test_rotation_du_csv_par_taille_et_nombre_de_fichiers(dossier_journal, monkeypatch):
    monkeypatch.setattr(maison, "JOURNAL", {"taille_max_ko": 1, "fichiers_max": 3})
    for _ in range(80):
        A.journaliser("x", "dictionnaire", 0.1, 0.1, 0.1, "", [])
    noms = sorted(p.name for p in dossier_journal.glob("latences*.csv"))
    assert noms == ["latences.1.csv", "latences.2.csv", "latences.3.csv", "latences.csv"]
    assert (dossier_journal / "latences.csv").stat().st_size <= 1024 + 200
    for p in dossier_journal.glob("latences*.csv"):  # chaque fichier garde son en-tête
        assert p.read_text(encoding="utf-8").startswith(";".join(A.COLONNES_LATENCES))


def test_valeurs_absurdes_de_retention_retombent_sur_les_defauts(dossier_journal, monkeypatch):
    monkeypatch.setattr(maison, "JOURNAL", {"conserver_jours": 0, "taille_max_ko": -5, "fichiers_max": "beaucoup"})
    assert maison.entier(maison.JOURNAL, "conserver_jours", A.CONSERVER_JOURS_DEFAUT) == 30
    assert maison.entier(maison.JOURNAL, "taille_max_ko", A.TAILLE_MAX_KO_DEFAUT) == 512
    assert maison.entier(maison.JOURNAL, "fichiers_max", A.FICHIERS_MAX_DEFAUT) == 5
    assert maison.entier({"a": True}, "a", 7) == 7  # un booléen n'est pas un entier


def test_retention_supprime_les_historiques_trop_vieux(dossier_journal, monkeypatch):
    monkeypatch.setattr(maison, "JOURNAL", {"conserver_jours": 10})
    dossier_journal.mkdir(parents=True)
    aujourdhui = maison.maintenant()
    vieux = (aujourdhui - timedelta(days=11)).strftime("%Y-%m-%d")
    limite = (aujourdhui - timedelta(days=9)).strftime("%Y-%m-%d")
    for jour in (vieux, limite):
        (dossier_journal / f"assistant-{jour}.jsonl").write_text("{}\n", encoding="utf-8")
    autre = dossier_journal / "manques.jsonl"
    autre.write_text("{}\n", encoding="utf-8")
    A.appliquer_retention(dossier_journal)
    assert not (dossier_journal / f"assistant-{vieux}.jsonl").exists()
    assert (dossier_journal / f"assistant-{limite}.jsonl").exists() and autre.exists()


def test_ancien_csv_avec_phrases_ecarte_puis_soumis_a_retention(dossier_journal):
    dossier_journal.mkdir(parents=True)
    (dossier_journal / "latences.csv").write_text(
        "horodatage;version;voie;stt_s;cerveau_s;tts_s;total_s;texte\n2026-10-01T10:00:00;0.30.0;ha;0;0;0;0;allume\n",
        encoding="utf-8")
    A.journaliser("bonjour", "dictionnaire", 0.1, 0.1, 0.1, "", [])
    assert not any("allume" in p.read_text(encoding="utf-8") for p in dossier_journal.glob("latences.csv"))
    ecartes = list(dossier_journal.glob("latences-ancien-*.csv"))
    assert len(ecartes) == 1
    lignes = lire_csv(dossier_journal)
    assert len(lignes) == 1 and list(lignes[0]) == A.COLONNES_LATENCES


def test_un_echec_d_ecriture_du_journal_ne_casse_pas_la_commande(dossier_journal, monkeypatch, capsys):
    def casse(*a, **k):
        raise OSError("disque plein")
    monkeypatch.setattr(Path, "mkdir", casse)
    A.journaliser("bonjour", "dictionnaire", 0, 0, 0, "", [])
    assert "journal impossible" in capsys.readouterr().out


def test_les_mesures_lisent_encore_le_csv_anonymise(dossier_journal):
    A.journaliser("bonjour", "dictionnaire", 0.1, 0.2, 0.3, "", [])
    lignes = lire_csv(dossier_journal)
    assert {"version", "voie", "stt_s", "cerveau_s", "tts_s", "total_s"} <= set(lignes[0])


# ---------------------------------------------------------------------------------------------------------------
# Point 4 : essais du code d'invitation par adresse
# ---------------------------------------------------------------------------------------------------------------

@pytest.fixture
def acces_vierge(monkeypatch):
    monkeypatch.setattr(maison, "ACCES", {})


def invitation_ouverte(role="habitant", maintenant=1000.0):
    inv = acces.Invitation()
    code = inv.ouvrir(role, maintenant)
    faux = "000000" if code != "000000" else "111111"
    return inv, code, faux


def test_une_adresse_bloquee_ne_detruit_pas_le_code_des_autres(acces_vierge):
    inv, code, faux = invitation_ouverte()
    for i in range(3):
        assert inv.verifier(faux, 1001 + i, ip="198.51.100.9") == (None, max(0, 2 - i))
    assert inv.verifier(code, 1005, ip="198.51.100.9") == (None, 0)  # même le bon code : cette adresse est bloquée
    assert inv.valide(1006)  # l'invitation vit toujours
    assert inv.verifier(code, 1007, ip="192.0.2.10") == ("habitant", 0)  # l'invité légitime entre


def test_sans_adresse_le_compteur_global_d_avant_est_conserve(acces_vierge):
    inv, code, faux = invitation_ouverte()
    for _ in range(2):
        inv.verifier(faux, 1001)
    assert inv.verifier(faux, 1002) == (None, 0)
    assert not inv.valide(1003)


def test_la_fenetre_est_glissante(acces_vierge):
    inv, code, faux = invitation_ouverte()
    for i in range(3):
        inv.verifier(faux, 1001 + i, ip="198.51.100.9")
    assert inv.bloquee("198.51.100.9", 1010)
    assert not inv.bloquee("198.51.100.9", 1001 + 3 + 120)  # fenêtre de 120 s écoulée (sur l'exemple, expire à 1120)
    assert not inv.bloquee("192.0.2.10", 1010)


def test_reglages_de_plafond_et_de_fenetre_lus_dans_la_configuration(monkeypatch):
    monkeypatch.setattr(maison, "ACCES", {"invitation_essais_par_ip": 5, "invitation_fenetre_s": 30})
    inv, code, faux = invitation_ouverte()
    for i in range(4):
        inv.verifier(faux, 1001 + i, ip="198.51.100.9")
    assert not inv.bloquee("198.51.100.9", 1005)
    inv.verifier(faux, 1006, ip="198.51.100.9")
    assert inv.bloquee("198.51.100.9", 1007)
    assert not inv.bloquee("198.51.100.9", 1006 + 31)


def test_reglages_absurdes_retombent_sur_les_defauts(monkeypatch):
    monkeypatch.setattr(maison, "ACCES", {"invitation_essais_par_ip": 0, "invitation_fenetre_s": -1,
                                          "invitation_essais_global": True})
    assert (acces.Invitation.plafond_par_adresse(), acces.Invitation.fenetre(), acces.Invitation.plafond_global()) \
        == (3, 120, 30)


def test_le_filet_global_detruit_le_code_contre_un_balayage_d_adresses(monkeypatch):
    monkeypatch.setattr(maison, "ACCES", {"invitation_essais_global": 6})
    inv, code, faux = invitation_ouverte()
    for i in range(6):
        inv.verifier(faux, 1001 + i, ip=f"203.0.113.{i + 1}")
    assert not inv.valide(1010)
    assert inv.verifier(code, 1011, ip="192.0.2.10") == (None, 0)


def test_la_table_des_adresses_suivies_reste_bornee(acces_vierge, monkeypatch):
    monkeypatch.setattr(maison, "ACCES", {"invitation_essais_global": 100000})
    inv, code, faux = invitation_ouverte()
    for i in range(acces.Invitation.ADRESSES_MAX + 50):
        inv.verifier(faux, 1001, ip=f"203.0.{i // 250}.{i % 250 + 1}")
    assert len(inv.echecs) <= acces.Invitation.ADRESSES_MAX


def test_ouvrir_une_invitation_remet_les_compteurs_a_zero(acces_vierge):
    inv, code, faux = invitation_ouverte()
    for i in range(3):
        inv.verifier(faux, 1001 + i, ip="198.51.100.9")
    nouveau = inv.ouvrir("habitant", 1010)
    assert inv.verifier(nouveau, 1011, ip="198.51.100.9") == ("habitant", 0)


def test_zone_ipv6_ignoree_dans_l_adresse(acces_vierge):
    inv, code, faux = invitation_ouverte()
    for i in range(3):
        inv.verifier(faux, 1001 + i, ip="fe80::1%eth0")
    assert inv.bloquee("fe80::1", 1005)
