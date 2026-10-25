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


def test_jeton_auth_accepte_a_la_place_de_la_cle(monkeypatch, capsys):
    """0.27.3 : le SDK accepte ANTHROPIC_AUTH_TOKEN, le serveur ne doit pas le déclarer sans clé."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "jeton-de-test")
    assert not A.cle_claude_absente()
    assert not A.CerveauClaude({"claude_modele": "claude-haiku-5-5"}, None).sans_cle
    assert "ANTHROPIC_API_KEY" not in capsys.readouterr().out


def test_sans_cle_la_voix_dit_la_vraie_cause(monkeypatch, tmp_path, capsys):
    """0.27.3 : sans clé, la réponse parlée nomme la clé au lieu d'un PC « peut-être occupé », et le journal
    garde le texte de l'erreur."""
    import tempfile
    from pathlib import Path
    import maison
    from dictionnaire import Dictionnaire
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    lignes = []
    monkeypatch.setattr(A, "journaliser", lambda *a: lignes.append(a))
    monkeypatch.setattr(A, "ajouter_jsonl", lambda *a, **k: None)
    assistant = object.__new__(A.Assistant)
    assistant.dico = Dictionnaire(maison.chemin("commandes.yaml"), Path(tempfile.mkdtemp()) / "commandes_apprises.yaml")
    assistant.ha, assistant.voix, assistant.essai = None, None, False
    assistant.cerveau = A.CerveauClaude({"claude_modele": "claude-haiku-5-5"}, None)
    parole = assistant._traiter("raconte moi une histoire de pirates", 0.0, None)
    assert "clé Anthropic" in parole and "occupé" not in parole
    assert A.MANQUE_CLE_CLAUDE in lignes[-1][1]


@pytest.mark.parametrize("mer, vent, attendu", [("0", "1", "METEO_MER=0"), ("1", "0", "VENT_MESURE=0"),
                                                ("0", "0", "METEO_MER=0 et VENT_MESURE=0")])
def test_causes_du_vent_eteint(monkeypatch, mer, vent, attendu):
    import serveur_satellite as S
    monkeypatch.setattr(S.VM, "ACTIF", True)
    monkeypatch.setattr(S.MM, "ACTIF", True)
    monkeypatch.setenv("METEO_MER", mer)
    monkeypatch.setenv("VENT_MESURE", vent)
    assert S.causes_vent_eteint() == attendu
    monkeypatch.setattr(S.VM, "ACTIF", False)
    assert "maison.json" in S.causes_vent_eteint()
