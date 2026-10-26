"""S-D5, acces.clair_restreint (D7) : hors wss, connexion fermée en 4003 sauf boucle locale.

Aucun réseau réel : la fausse connexion note les appels, les adresses sont des plages de documentation
(192.0.2.x, 198.51.100.x) et la boucle locale."""
import asyncio
import inspect

import pytest

import acces
import maison
import serveur_satellite as S


class FauxWs:
    def __init__(self, ip):
        self.remote_address = (ip, 50000)
        self.fermetures = []

    async def close(self, code=1000, reason=""):
        self.fermetures.append((code, reason))


class FauxAppareils:
    def __init__(self):
        self.refus = []

    def noter_refus(self, cause, ip):
        self.refus.append((cause, ip))


def fermer(ip, chiffre):
    ws, app = FauxWs(ip), FauxAppareils()
    ferme = asyncio.run(S.fermer_si_clair_restreint(ws, chiffre, app))
    return ferme, ws, app


@pytest.fixture
def actif(monkeypatch):
    monkeypatch.setattr(maison, "ACCES", {"clair_restreint": True})


def test_actif_clair_distant_ferme_en_4003(actif, capsys):
    ferme, ws, app = fermer("192.0.2.10", chiffre=False)
    assert ferme and ws.fermetures == [(4003, "connexion en clair refusée")]
    assert app.refus == [("clair restreint", "192.0.2.10")]
    sortie = capsys.readouterr().out
    assert "192.0.2.10" in sortie and "acces.clair_restreint" in sortie


@pytest.mark.parametrize("ip", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_actif_boucle_locale_acceptee(actif, ip):
    ferme, ws, app = fermer(ip, chiffre=False)
    assert not ferme and ws.fermetures == [] and app.refus == []


@pytest.mark.parametrize("ip", ["192.0.2.10", "198.51.100.7", "100.64.0.10", "::ffff:192.0.2.10", "127.0.0.1"])
def test_actif_wss_accepte(actif, ip):
    ferme, ws, app = fermer(ip, chiffre=True)
    assert not ferme and ws.fermetures == []


def test_actif_adresse_illisible_refusee(actif):
    ferme, ws, _ = fermer("pas une adresse", chiffre=False)
    assert ferme and ws.fermetures[0][0] == 4003


@pytest.mark.parametrize("acces_conf", [{}, {"clair_restreint": False}, {"clair_restreint": "true"},
                                        {"clair_restreint": 1}, {"clair_restreint": None}])
def test_absent_ou_faux_comportement_inchange(monkeypatch, acces_conf):
    monkeypatch.setattr(maison, "ACCES", acces_conf)
    assert acces.clair_restreint() is False
    for ip in ("192.0.2.10", "127.0.0.1", "::1"):
        for chiffre in (False, True):
            ferme, ws, app = fermer(ip, chiffre)
            assert not ferme and ws.fermetures == [] and app.refus == []


def test_exemple_ne_restreint_pas():
    assert acces.clair_restreint() is False


def test_le_journal_ne_porte_aucun_jeton(actif, capsys):
    motif = acces.refus_clair_restreint("192.0.2.10", False)
    assert motif and "jeton" not in motif.lower() and "?" not in motif
    fermer("192.0.2.10", False)
    assert "Bearer" not in capsys.readouterr().out


def test_accueil_appelle_le_filtre():
    """La porte d'entrée consulte le filtre après le contrôle des réseaux et avant la lecture du jeton."""
    src = inspect.getsource(S.servir)
    i_reseau = src.index("réseau non autorisé")
    i_clair = src.index("fermer_si_clair_restreint")
    i_jeton = src.index("jeton_de_la_requete")
    assert i_reseau < i_clair < i_jeton
