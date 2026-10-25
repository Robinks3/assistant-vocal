"""Failles du 25/10/2026 : réseaux autorisés, code d'appairage réservé aux administrateurs, rôle des messages."""
import asyncio
import json

import acces
import maison


def test_reseaux_par_defaut():
    r = acces.reseaux_autorises()
    for ok in ("192.0.2.1", "127.0.0.1", "192.0.2.1", "::1", "::ffff:192.0.2.1", "192.0.2.1"):
        assert acces.adresse_autorisee(ok, r), ok
    for non in ("8.8.8.8", "192.0.2.1", "2001:db8::1", "pas une adresse", "100.128.0.1"):
        assert not acces.adresse_autorisee(non, r), non


def test_reseaux_ouverts_et_illisibles(monkeypatch):
    monkeypatch.setattr(maison, "ACCES", {"reseaux_autorises": ["*"]})
    r = acces.reseaux_autorises()
    assert acces.adresse_autorisee("8.8.8.8", r) and acces.adresse_autorisee("2001:db8::1", r)
    monkeypatch.setattr(maison, "ACCES", {"reseaux_autorises": ["n'importe quoi", "192.0.2.1/24"]})
    r = acces.reseaux_autorises()
    assert acces.adresse_autorisee("192.0.2.1", r) and not acces.adresse_autorisee("192.0.2.1", r)


def test_ecoute_et_ancien_acces(monkeypatch):
    assert acces.adresses_ecoute() == ["0.0.0.0"]
    monkeypatch.setattr(maison, "ACCES", {"ecoute": ["192.168.0.10", "192.0.2.10"], "ancien_acces": False})
    assert acces.adresses_ecoute() == ["192.168.0.10", "192.0.2.10"]
    assert acces.ancien_acces_permis(None) is False
    assert acces.ancien_acces_permis("1") is True  # l'environnement l'emporte
    monkeypatch.setattr(maison, "ACCES", {})
    assert acces.ancien_acces_permis(None) is True and acces.ancien_acces_permis("0") is False


def test_administrateurs(monkeypatch):
    assert acces.est_administrateur(maison.CLE_PROPRIETAIRE)
    for non in (None, "", "camille", "appareil:ab12cd34"):
        assert not acces.est_administrateur(non)
    monkeypatch.setattr(maison, "ACCES", {"administrateurs": ["appareil:ab12cd34"]})
    assert acces.est_administrateur("appareil:ab12cd34")


def test_vue_sans_code_par_defaut(tmp_path):
    async def deroule():
        app = acces.Appareils(tmp_path, {})
        app.demande("Tab", "192.0.2.1", asyncio.get_running_loop().create_future())
        assert "code" not in app.vue()["attente"][0]
        assert len(app.vue(avec_code=True)["attente"][0]["code"]) == 4
    asyncio.run(deroule())


def faux_satellite(identite):
    import serveur_satellite as S
    envoyes = []

    class Moteur:
        satellites = set()
        appareils = None

    sat = object.__new__(S.Satellite)
    sat.moteur, sat.nom, sat.identite = Moteur(), "Tab", identite

    async def envoyer(**m):
        envoyes.append(m)
    sat.envoyer = envoyer
    return S, sat, envoyes


def test_messages_d_administration_refuses_aux_autres():
    for identite in ("camille", "appareil:ab12cd34", None):
        S, sat, envoyes = faux_satellite(identite)
        for genre in sorted(S.TYPES_ADMINISTRATEUR):
            asyncio.run(sat.recevoir_texte(json.dumps({"type": genre, "id": "x", "choix": "local"})))
        assert [m["etat"] for m in envoyes] == ["refuse"] * len(S.TYPES_ADMINISTRATEUR)


def test_appairage_diffuse_aux_seuls_administrateurs():
    import serveur_satellite as S

    class Faux:
        def __init__(self, identite):
            self.identite, self.recus = identite, []

        async def envoyer(self, **m):
            self.recus.append(m)
    proprio, autre = Faux(maison.CLE_PROPRIETAIRE), Faux("appareil:ab12cd34")
    moteur = object.__new__(S.Moteur)
    moteur.satellites = {proprio, autre}
    moteur.pages_admin = set()
    asyncio.run(moteur.diffuser({"etat": "appairage_demande", "code": "1234"}, administrateurs=True))
    assert proprio.recus and not autre.recus
