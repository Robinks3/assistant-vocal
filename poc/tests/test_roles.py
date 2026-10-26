"""Rôles réels (0.38.0) : rôle effectif, messages réservés à l'administrateur, personne effective des messages.

Les identités, prénoms et clés viennent de config-exemple/ (Sacha propriétaire, Camille habitante, tablette en
« partage »), jamais d'une vraie maison."""
import asyncio
import json
from types import SimpleNamespace

import pytest

import acces
import administration as adm
import maison

PROPRIETAIRE = maison.CLE_PROPRIETAIRE


def reglage_acces(monkeypatch, **acces_json):
    monkeypatch.setattr(maison, "ACCES", acces_json)


def appareils_avec(tmp_path, *entrees):
    """Appareils sur un dossier temporaire, avec des entrées d'appareils.json prêtes (sans empreinte réelle)."""
    app = acces.Appareils(tmp_path, {})
    app.liste = [dict({"nom": "Tab", "empreinte": "x", "cree": "2026-10-26 10:00:00", "dernier": ""}, **e)
                 for e in entrees]
    return app


def demander(app, nom="Tab"):
    """Une demande d'appairage en attente, avec le futur de sa connexion (dans la boucle en cours)."""
    return app.demande(nom, "192.0.2.10", asyncio.get_running_loop().create_future())[0]


# ---------------------------------------------------------------------------------------------------------------
# role_de et role_effectif
# ---------------------------------------------------------------------------------------------------------------

def test_role_de_entree_sans_champ_ou_inconnu_vaut_invite():
    assert acces.role_de({"id": "a1"}) == "invite"
    assert acces.role_de({"id": "a1", "role": "roi"}) == "invite"
    assert acces.role_de({"id": "a1", "role": None}) == "invite"
    assert acces.role_de(None) == "invite"


@pytest.mark.parametrize("role", ["administrateur", "habitant", "partage", "invite"])
def test_role_de_chaque_role_valable(role):
    assert acces.role_de({"id": "a1", "role": role}) == role


def test_role_par_defaut_et_absence_de_champ_sont_distincts():
    assert acces.ROLE_PAR_DEFAUT == "habitant"
    assert acces.ROLE_SANS_CHAMP == "invite"


def test_proprietaire_est_administrateur_quoi_que_dise_acces_roles(monkeypatch):
    assert acces.role_effectif(PROPRIETAIRE) == "administrateur"
    reglage_acces(monkeypatch, roles={PROPRIETAIRE: "invite"})
    assert acces.role_effectif(PROPRIETAIRE) == "administrateur"
    assert any(PROPRIETAIRE in phrase and "ignorée" in phrase for phrase in acces.avertissements_roles())


def test_cle_de_acces_administrateurs_est_administrateur(monkeypatch):
    reglage_acces(monkeypatch, administrateurs=["appareil:ab12cd34", "camille"], roles={"camille": "invite"})
    assert acces.role_effectif("appareil:ab12cd34") == "administrateur"
    assert acces.role_effectif("camille") == "administrateur"


def test_jeton_fixe_avec_et_sans_entree_roles(monkeypatch):
    reglage_acces(monkeypatch, roles={"camille": "invite", "tablette": "partage"})
    assert acces.role_effectif("camille") == "invite"
    assert acces.role_effectif("tablette") == "partage"
    assert acces.role_effectif("cuisine") == "habitant"  # absent de acces.roles
    reglage_acces(monkeypatch)
    assert acces.role_effectif("camille") == "habitant"


def test_jeton_fixe_au_role_inconnu_ou_reserve_vaut_invite(monkeypatch):
    reglage_acces(monkeypatch, roles={"camille": "roi", "tablette": "administrateur"})
    assert acces.role_effectif("camille") == "invite"
    assert acces.role_effectif("tablette") == "invite"  # « administrateur » est réservé
    phrases = " ".join(acces.avertissements_roles())
    assert "roi" in phrases and "réservé" in phrases


def test_valeurs_de_acces_roles_en_majuscules(monkeypatch):
    reglage_acces(monkeypatch, roles={"Camille": "PARTAGE"})
    assert acces.role_effectif("camille") == "partage"


def test_cle_du_proprietaire_declaree_autrement_reste_administrateur(monkeypatch):
    for valeur in ("habitant", "partage", "invite", "roi", "administrateur"):
        reglage_acces(monkeypatch, roles={PROPRIETAIRE.upper(): valeur})
        assert acces.role_effectif(PROPRIETAIRE) == "administrateur", valeur


def test_exemple_de_configuration():
    assert acces.role_effectif("camille") == "habitant"
    assert acces.role_effectif("tablette") == "partage"
    assert acces.avertissements_roles() == []


def test_appareil_appaire_prend_le_role_de_son_entree(tmp_path):
    app = appareils_avec(tmp_path,
                         {"id": "h1", "role": "habitant"}, {"id": "p1", "role": "partage"},
                         {"id": "i1", "role": "invite"}, {"id": "s1"}, {"id": "r1", "role": "roi"})
    attendu = {"h1": "habitant", "p1": "partage", "i1": "invite", "s1": "invite", "r1": "invite"}
    for ident, role in attendu.items():
        assert acces.role_effectif(f"appareil:{ident}", app) == role, ident


def test_appareil_inconnu_ou_sans_appareils_vaut_invite(tmp_path):
    app = appareils_avec(tmp_path)
    assert acces.role_effectif("appareil:zz", app) == "invite"
    assert acces.role_effectif("appareil:zz") == "invite"
    assert acces.role_effectif("ha:abc123", app) == "invite"
    assert acces.role_effectif(None, app) == "invite" and acces.role_effectif("", app) == "invite"


def test_entree_administrateur_d_appareils_json_ne_donne_pas_le_droit(tmp_path):
    """Un fichier appareils.json trafiqué ne fait pas un administrateur : seule la configuration le fait."""
    app = appareils_avec(tmp_path, {"id": "ad", "role": "administrateur"})
    assert acces.role_de(app.liste[0]) == "administrateur"  # lisible tel quel
    assert acces.role_effectif("appareil:ad", app) == "invite"
    assert not acces.est_administrateur("appareil:ad", app)


def test_aucune_identite_n_est_administrateur_sans_configuration():
    for non in (None, "", "camille", "tablette", "appareil:ab12cd34", "ha:abc123"):
        assert not acces.est_administrateur(non), non
    assert acces.est_administrateur(PROPRIETAIRE)


def test_role_effectif_ne_modifie_pas_le_fichier(tmp_path):
    app = appareils_avec(tmp_path, {"id": "s1"})
    app.enregistrer()
    avant = (tmp_path / "appareils.json").read_text(encoding="utf-8")
    acces.role_effectif("appareil:s1", app)
    app.vue()
    assert (tmp_path / "appareils.json").read_text(encoding="utf-8") == avant
    assert "role" not in json.loads(avant)[0]


# ---------------------------------------------------------------------------------------------------------------
# Messages réservés à l'administrateur (machine à états Satellite)
# ---------------------------------------------------------------------------------------------------------------

def faux_satellite(monkeypatch, identite, appareils):
    import serveur_satellite as S
    envoyes, appels = [], []

    class Moteur:
        satellites = set()
        pages_admin = set()
        verrou = None
        essai = False

        async def changer_stt(self, choix):
            appels.append(("transcription", choix))

        async def changer_mode(self, choix):
            appels.append(("mode", choix))

        async def changer_cerveau(self, choix):
            appels.append(("cerveau", choix))

    moteur = Moteur()
    moteur.appareils = appareils
    sat = object.__new__(S.Satellite)
    sat.moteur, sat.nom, sat.identite = moteur, "Tab", identite

    async def envoyer(**m):
        envoyes.append(m)
    sat.envoyer = envoyer
    monkeypatch.setattr(S.A, "lire_jsonl", lambda *a, **k: [])
    return S, sat, envoyes, appels


def message_de(genre):
    msg = {"type": genre, "id": "s1", "choix": "local", "role": "invite", "personne": "camille"}
    return json.dumps(msg)


def types_administrateur():
    import serveur_satellite as S
    return sorted(S.TYPES_ADMINISTRATEUR)


def est_le_refus_de_role(m):
    return m.get("etat") == "refuse" and m.get("message") == "réservé à un administrateur"


def test_liste_des_messages_administrateur():
    import serveur_satellite as S
    assert {"appareils", "appairer", "refuser_appareil", "revoquer", "changer_role", "changer_personne",
            "inviter", "annuler_invitation", "transcription", "mode", "cerveau", "manques"} == set(S.TYPES_ADMINISTRATEUR)


@pytest.mark.parametrize("genre", types_administrateur())
@pytest.mark.parametrize("role", ["habitant", "partage", "invite"])
def test_message_administrateur_refuse_a_chaque_role(monkeypatch, tmp_path, genre, role):
    app = appareils_avec(tmp_path, {"id": "r1", "role": role}, {"id": "s1", "role": "invite"})
    S, sat, envoyes, appels = faux_satellite(monkeypatch, "appareil:r1", app)

    async def scenario():
        await sat.recevoir_texte(message_de(genre))
        await asyncio.sleep(0)
    asyncio.run(scenario())
    assert len(envoyes) == 1 and est_le_refus_de_role(envoyes[0]) and envoyes[0]["type"] == genre
    assert appels == []
    assert [a["role"] for a in app.liste] == [role, "invite"]  # rien n'a bougé


@pytest.mark.parametrize("genre", types_administrateur())
@pytest.mark.parametrize("identite", ["camille", "tablette", "ha:abc123", "appareil:inconnu", None])
def test_message_administrateur_refuse_aux_jetons_fixes_et_inconnus(monkeypatch, tmp_path, genre, identite):
    S, sat, envoyes, appels = faux_satellite(monkeypatch, identite, appareils_avec(tmp_path, {"id": "s1"}))

    async def scenario():
        await sat.recevoir_texte(message_de(genre))
        await asyncio.sleep(0)
    asyncio.run(scenario())
    assert len(envoyes) == 1 and est_le_refus_de_role(envoyes[0])
    assert appels == []


@pytest.mark.parametrize("genre", types_administrateur())
def test_message_administrateur_accepte_au_proprietaire(monkeypatch, tmp_path, genre):
    app = appareils_avec(tmp_path, {"id": "s1", "role": "invite"})
    S, sat, envoyes, appels = faux_satellite(monkeypatch, PROPRIETAIRE, app)

    async def scenario():
        await sat.recevoir_texte(message_de(genre))
        await asyncio.sleep(0)
    asyncio.run(scenario())
    assert not any(est_le_refus_de_role(m) for m in envoyes), envoyes
    if genre in ("transcription", "mode", "cerveau"):
        assert appels == [(genre, "local")]


def test_message_administrateur_accepte_a_un_appareil_liste_administrateur(monkeypatch, tmp_path):
    reglage_acces(monkeypatch, administrateurs=["appareil:r1"])
    app = appareils_avec(tmp_path, {"id": "r1", "role": "habitant"}, {"id": "s1", "role": "invite"})
    S, sat, envoyes, appels = faux_satellite(monkeypatch, "appareil:r1", app)
    asyncio.run(sat.recevoir_texte(message_de("changer_role")))
    assert not any(est_le_refus_de_role(m) for m in envoyes)
    assert app.liste[1]["role"] == "invite"
    asyncio.run(sat.recevoir_texte(json.dumps({"type": "changer_role", "id": "s1", "role": "partage"})))
    assert app.liste[1]["role"] == "partage"


def test_gerer_appareils_refuse_aussi_hors_administrateur(monkeypatch, tmp_path):
    """Seconde barrière : même si recevoir_texte laissait passer, le traitement commun refuse."""
    app = appareils_avec(tmp_path, {"id": "r1", "role": "habitant"}, {"id": "s1", "role": "invite"})
    moteur = SimpleNamespace(appareils=app, satellites=set(), pages_admin=set())
    courant = SimpleNamespace(identite="appareil:r1")
    rep = asyncio.run(adm.gerer_appareils(moteur, {"type": "changer_role", "id": "s1", "role": "partage"},
                                          "Tab", courant=courant))
    assert len(rep) == 1 and est_le_refus_de_role(rep[0])
    assert app.liste[1]["role"] == "invite"


# ---------------------------------------------------------------------------------------------------------------
# « administrateur » ne s'attribue pas
# ---------------------------------------------------------------------------------------------------------------

def test_appairer_refuse_administrateur(tmp_path):
    app = appareils_avec(tmp_path)
    moteur = SimpleNamespace(appareils=app, satellites=set(), pages_admin=set())

    async def scenario():
        ident = demander(app)
        rep = await adm.gerer_appareils(moteur, {"type": "appairer", "id": ident, "role": "administrateur"},
                                        "Page", page=True)
        assert rep[0]["etat"] == "refuse" and rep[0]["message"] == "rôle non attribuable"
        assert app.liste == [] and ident in app.attente  # rien de créé, la demande reste en attente
        rep = await adm.gerer_appareils(moteur, {"type": "appairer", "id": ident, "role": "roi"}, "Page", page=True)
        assert rep[0]["etat"] == "refuse" and app.liste == []
        assert app.accepter(ident, "administrateur") is None and app.liste == []
        rep = await adm.gerer_appareils(moteur, {"type": "appairer", "id": ident, "role": "partage"}, "Page", page=True)
        assert rep[0]["etat"] == "appareils" and app.liste[0]["role"] == "partage"
    asyncio.run(scenario())


def test_appairer_sans_role_donne_habitant(tmp_path):
    app = appareils_avec(tmp_path)
    moteur = SimpleNamespace(appareils=app, satellites=set(), pages_admin=set())

    async def scenario():
        ident = demander(app)
        await adm.gerer_appareils(moteur, {"type": "appairer", "id": ident}, "Page", page=True)
    asyncio.run(scenario())
    assert app.liste[0]["role"] == "habitant"


def test_inviter_refuse_administrateur(tmp_path):
    app = appareils_avec(tmp_path)
    moteur = SimpleNamespace(appareils=app, satellites=set(), pages_admin=set())
    rep = asyncio.run(adm.gerer_appareils(moteur, {"type": "inviter", "role": "administrateur"}, "Page", page=True))
    assert rep[0]["etat"] == "refuse" and rep[0]["message"] == "rôle non attribuable"
    assert app.invitation.vue() is None
    with pytest.raises(ValueError):
        app.invitation.ouvrir("administrateur")
    rep = asyncio.run(adm.gerer_appareils(moteur, {"type": "inviter", "role": "invite"}, "Page", page=True))
    assert app.invitation.vue()["role"] == "invite" and rep[0]["etat"] != "refuse"


def test_changer_role_refuse_administrateur(tmp_path):
    app = appareils_avec(tmp_path, {"id": "s1", "role": "invite"})
    assert app.changer_role("s1", "administrateur") is None
    assert app.changer_role("s1", "roi") is None
    assert app.liste[0]["role"] == "invite"
    assert app.changer_role("s1", "partage") == ("Tab", "invite", "partage")


def test_changer_role_refuse_un_administrateur_de_la_configuration(monkeypatch, tmp_path):
    reglage_acces(monkeypatch, administrateurs=["appareil:ad"])
    app = appareils_avec(tmp_path, {"id": "ad", "role": "habitant"})
    assert app.changer_role("ad", "invite") is None
    assert app.liste[0]["role"] == "habitant"


def test_changer_role_sur_le_proprietaire_est_refuse(tmp_path):
    app = appareils_avec(tmp_path, {"id": "s1", "role": "invite"})
    moteur = SimpleNamespace(appareils=app, satellites=set(), pages_admin=set())
    for ident in (PROPRIETAIRE, f"appareil:{PROPRIETAIRE}"):
        rep = asyncio.run(adm.gerer_appareils(moteur, {"type": "changer_role", "id": ident, "role": "invite"},
                                              "Page", page=True))
        assert rep[0]["etat"] == "refuse" and rep[0]["type"] == "changer_role"
    assert [a["role"] for a in app.liste] == ["invite"]
    assert app.changer_role(PROPRIETAIRE, "invite") is None


# ---------------------------------------------------------------------------------------------------------------
# changer_personne et appairage avec personne
# ---------------------------------------------------------------------------------------------------------------

def test_changer_personne_connue_acceptee_inconnue_refusee(tmp_path):
    app = appareils_avec(tmp_path, {"id": "s1", "role": "habitant"})
    assert app.changer_personne("s1", "Camille") == ("Tab", None, "camille")
    assert app.liste[0]["personne"] == "camille"
    assert app.changer_personne("s1", "Sacha")[2] == PROPRIETAIRE
    assert app.changer_personne("s1", "Mallory") is None
    assert app.changer_personne("zz", "camille") is None
    assert app.liste[0]["personne"] == PROPRIETAIRE  # le refus n'a rien changé
    assert app.changer_personne("s1", "")[2] is None and "personne" not in app.liste[0]


def test_changer_personne_via_le_message(monkeypatch, tmp_path):
    app = appareils_avec(tmp_path, {"id": "s1", "role": "habitant"})
    S, sat, envoyes, _ = faux_satellite(monkeypatch, PROPRIETAIRE, app)

    async def scenario():
        await sat.recevoir_texte(json.dumps({"type": "changer_personne", "id": "s1", "personne": "camille"}))
        await sat.recevoir_texte(json.dumps({"type": "changer_personne", "id": "s1", "personne": "mallory"}))
    asyncio.run(scenario())
    assert app.liste[0]["personne"] == "camille"
    assert envoyes[0]["etat"] == "appareils"
    refus = [m for m in envoyes if m.get("etat") == "refuse"]
    assert len(refus) == 1 and refus[0]["message"] == "appareil ou personne inconnue"


def test_changer_personne_refuse_a_un_non_administrateur(monkeypatch, tmp_path):
    app = appareils_avec(tmp_path, {"id": "s1", "role": "habitant"}, {"id": "r1", "role": "partage"})
    S, sat, envoyes, _ = faux_satellite(monkeypatch, "appareil:r1", app)
    asyncio.run(sat.recevoir_texte(json.dumps({"type": "changer_personne", "id": "s1", "personne": "camille"})))
    assert len(envoyes) == 1 and est_le_refus_de_role(envoyes[0])
    assert "personne" not in app.liste[0]


def test_accepter_avec_personne(tmp_path):
    app = appareils_avec(tmp_path)

    async def scenario():
        ident = demander(app)
        assert app.accepter(ident, "habitant", "Mallory") is None and ident in app.attente  # rien de consommé
        assert app.accepter(ident, "habitant", "Camille") == "Tab"
    asyncio.run(scenario())
    assert app.liste[0]["personne"] == "camille" and app.liste[0]["role"] == "habitant"


def test_appairer_refuse_une_personne_inconnue(tmp_path):
    app = appareils_avec(tmp_path)
    moteur = SimpleNamespace(appareils=app, satellites=set(), pages_admin=set())

    async def scenario():
        ident = demander(app)
        rep = await adm.gerer_appareils(moteur, {"type": "appairer", "id": ident, "personne": "mallory"},
                                        "Page", page=True)
        assert rep[0]["etat"] == "refuse" and app.liste == []
    asyncio.run(scenario())


# ---------------------------------------------------------------------------------------------------------------
# Export (vue)
# ---------------------------------------------------------------------------------------------------------------

def test_vue_expose_role_effectif_et_personne_sans_secret(monkeypatch, tmp_path):
    reglage_acces(monkeypatch, administrateurs=["appareil:ad"], roles={"tablette": "partage", "camille": "invite"})
    app = acces.Appareils(tmp_path, {"jeton-1": "camille", "jeton-2": "tablette", "jeton-3": "cuisine"})
    app.liste = [
        {"id": "ad", "nom": "A", "empreinte": "e1", "role": "habitant", "personne": "sacha", "cree": "c", "dernier": ""},
        {"id": "s1", "nom": "B", "empreinte": "e2", "cree": "c", "dernier": ""},
        {"id": "r1", "nom": "C", "empreinte": "e3", "role": "partage", "cree": "c", "dernier": ""},
        {"id": "x1", "nom": "D", "empreinte": "e4", "role": "administrateur", "cree": "c", "dernier": ""},
    ]
    vue = app.vue(avec_code=True)
    par_id = {a["id"]: a for a in vue["appareils"]}
    assert par_id["ad"]["role"] == "administrateur" and par_id["ad"]["personne"] == "sacha"
    assert par_id["s1"]["role"] == "invite" and par_id["s1"]["personne"] is None
    assert par_id["r1"]["role"] == "partage"
    assert par_id["x1"]["role"] == "invite"  # « administrateur » écrit dans le fichier ne compte pas
    assert vue["jetons_fixes"] == ["camille", "cuisine", "tablette"]
    assert vue["roles_jetons_fixes"] == {"camille": "invite", "cuisine": "habitant", "tablette": "partage"}
    texte = json.dumps(vue)
    for secret in ("e1", "e2", "empreinte", "jeton-1", "jeton-2", "jeton-3"):
        assert secret not in texte, secret


# ---------------------------------------------------------------------------------------------------------------
# personne_effective : les six cas de la décision 4
# ---------------------------------------------------------------------------------------------------------------

@pytest.fixture
def parc(tmp_path):
    return appareils_avec(tmp_path,
                          {"id": "h1", "role": "habitant", "personne": "camille"},
                          {"id": "h2", "role": "habitant"},
                          {"id": "p1", "role": "partage"},
                          {"id": "i1", "role": "invite", "personne": "camille"},
                          {"id": "i2", "role": "invite"})


def test_personne_effective_administrateur_accepte_un_habitant_connu(parc):
    assert acces.personne_effective(PROPRIETAIRE, "camille", parc) == "camille"
    assert acces.personne_effective(PROPRIETAIRE, "Camille", parc) == "camille"
    assert acces.personne_effective(PROPRIETAIRE, "Sacha", parc) == PROPRIETAIRE


def test_personne_effective_administrateur_inconnu_et_declaration_invalide(parc):
    assert acces.personne_effective(PROPRIETAIRE, "mallory", parc) is None
    assert acces.personne_effective(PROPRIETAIRE, "", parc) is None
    assert acces.personne_effective(PROPRIETAIRE, None, parc) is None
    assert acces.personne_effective(PROPRIETAIRE, "inconnu", parc) == "inconnu"  # voir la docstring (tablette du salon)


def test_personne_effective_partage_se_comporte_comme_administrateur(parc):
    assert acces.personne_effective("appareil:p1", "camille", parc) == "camille"
    assert acces.personne_effective("appareil:p1", "mallory", parc) is None
    assert acces.personne_effective("tablette", "camille", parc) == "camille"  # jeton fixe en « partage » (exemple)


def test_personne_effective_habitant_jeton_fixe_vaut_sa_cle(parc):
    assert acces.personne_effective("camille", "sacha", parc) == "camille"  # la déclarée est ignorée
    assert acces.personne_effective("camille", None, parc) == "camille"
    assert acces.personne_effective("cuisine", "camille", parc) is None  # clé qui n'est pas un habitant


def test_personne_effective_habitant_appaire_vaut_le_champ_personne(parc):
    assert acces.personne_effective("appareil:h1", "sacha", parc) == "camille"
    assert acces.personne_effective("appareil:h1", None, parc) == "camille"
    assert acces.personne_effective("appareil:h2", "camille", parc) is None  # pas de champ : aucune
    assert acces.personne_effective("appareil:zz", "camille", parc) is None


def test_personne_effective_invite_ignore_la_declaration(parc):
    assert acces.personne_effective("appareil:i2", "camille", parc) is None
    assert acces.personne_effective("appareil:i1", "sacha", parc) == "camille"  # son champ, jamais sa déclaration


def test_invite_qui_se_declare_proprietaire_n_est_pas_proprietaire(parc):
    for declaree in ("sacha", "Sacha", PROPRIETAIRE, "propriétaire"):
        assert acces.personne_effective("appareil:i2", declaree, parc) is None
        assert acces.personne_effective("appareil:i1", declaree, parc) != PROPRIETAIRE
        assert acces.personne_effective("appareil:h2", declaree, parc) is None
    assert acces.personne_effective("ha:abc123", "sacha", parc) is None


def test_personne_du_message_passe_par_personne_effective(monkeypatch, parc):
    S, sat, _, _ = faux_satellite(monkeypatch, "appareil:i2", parc)
    assert sat.personne_du_message({"personne": "sacha"}) is None
    sat.identite = PROPRIETAIRE
    assert sat.personne_du_message({"personne": "camille"}) == "camille"
    assert sat.personne_du_message({"personne": "mallory"}) is None
    sat.identite = "appareil:h1"
    assert sat.personne_du_message({"personne": "sacha"}) == "camille"
