"""Cerveau Claude sans clé Anthropic (0.27.1) : avertissement au démarrage, erreur claire à chaque demande,
et bascule depuis le téléphone refusée plutôt que d'arrêter le modèle local pour un cerveau muet."""
import asyncio

import pytest

import assistant as A


@pytest.mark.parametrize("valeur, absente", [(None, True), ("", True), ("   ", True), ("cle-de-test", False)])
def test_cle_absente(monkeypatch, valeur, absente):
    if valeur is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", valeur)
    assert A.cle_claude_absente() is absente


def test_cerveau_sans_cle_avertit_et_refuse(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cerveau = A.CerveauClaude({"claude_modele": "claude-haiku-5-5"}, None)
    assert "ANTHROPIC_API_KEY vide" in capsys.readouterr().out

    class SansAppel:
        def __getattr__(self, nom):
            raise AssertionError("l'API ne doit pas être appelée sans clé")
    cerveau.client = SansAppel()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        cerveau.repondre("allume le salon")


def test_cerveau_avec_cle_sans_avertissement(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
    assert not A.CerveauClaude({"claude_modele": "claude-haiku-5-5"}, None).sans_cle
    assert "ANTHROPIC_API_KEY" not in capsys.readouterr().out


def test_bascule_vers_claude_refusee_sans_cle(monkeypatch):
    import serveur_satellite as S
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    moteur = object.__new__(S.Moteur)
    moteur.cerveau_actif, moteur.cerveau_pret, moteur.cerveau_message = "local", True, ""
    moteur.capacites = lambda sat=None: {"cerveau": ["claude", "local"]}
    diffuses = []

    async def diffuser(message):
        diffuses.append(message)
    moteur.diffuser = diffuser

    async def scenario():
        moteur.verrou = asyncio.Lock()
        await moteur.changer_cerveau("claude")
    asyncio.run(scenario())
    assert moteur.cerveau_actif == "local" and moteur.cerveau_pret
    assert "ANTHROPIC_API_KEY vide" in diffuses[-1]["message"]
