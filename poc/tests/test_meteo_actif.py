"""Météo et mer : avertissement mer sans vent (C1), titre par défaut de la mer (C3), clé « actif » par source (C9).

Tout tourne sur config-exemple/ (rade de Marseille fictive) et sur des sections écrites dans le test. Aucun
appel réseau : httpx.MockTransport, comme test_meteo_mer.py et test_vent_mesure.py."""
import asyncio
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

import maison
import meteo_mer as MM
import test_meteo_mer as TM
import test_vent_mesure as TV
import vent_mesure as VM

RACINE = Path(__file__).resolve().parents[2]
EXEMPLE = RACINE / "config-exemple"


def mer_exemple():
    return copy.deepcopy(MM.MER)


def vent_exemple():
    return copy.deepcopy(VM.VENT)


# ------------------------------------------------------------ source_active (règle commune)
@pytest.mark.parametrize("fiche, attendu", [
    ({}, True), ({"actif": True}, True), ({"actif": "true"}, True), ({"actif": "oui"}, True),
    ({"actif": False}, False), ({"actif": "false"}, False), ({"actif": "0"}, False), ({"actif": 0}, False),
    (None, True), ("texte", True),
])
def test_source_active_absent_vaut_vrai(fiche, attendu):
    assert maison.source_active(fiche) is attendu


def test_source_active_est_l_inverse_de_actif_pour_une_section():
    """Une section sans clé « actif » est éteinte, une source sans clé est allumée."""
    assert maison.actif({}) is False and maison.source_active({}) is True


# ------------------------------------------------------------ C1 : mer sans vent
def test_c1_mer_sans_section_vent_avertit():
    cfg = {"mer": {"actif": True}}
    [phrase] = maison.avertissements_meteo(cfg)
    assert "« mer »" in phrase and "« vent »" in phrase and "absente" in phrase


def test_c1_vent_inactif_ou_sans_source_avertit_avec_la_cause():
    inactive = maison.avertissements_meteo({"mer": {"actif": True}, "vent": {"actif": False, "station": {}}})
    assert "inactive" in inactive[0]
    vide = maison.avertissements_meteo({"mer": {"actif": True}, "vent": {"actif": True}})
    assert "aucune source" in vide[0]


def test_c1_pas_d_avertissement_quand_tout_va_bien_ou_sans_mer():
    assert maison.avertissements_meteo() == []                       # config-exemple/ : mer et vent actifs
    assert maison.avertissements_meteo({"vent": {"actif": True}}) == []
    assert maison.avertissements_meteo({"mer": {"actif": False}}) == []
    assert maison.avertissements_meteo({}) == []


def test_c1_formes_bizarres_sans_exception():
    for cfg in ({"mer": "texte"}, {"mer": {"actif": True}, "vent": [1, 2]}, {"mer": {"actif": True}, "vent": None}):
        assert isinstance(maison.avertissements_meteo(cfg), list)


def test_c1_le_chargement_ecrit_l_avertissement_dans_le_journal(tmp_path):
    """Au chargement de la configuration (import de maison), sur stderr, sans exception ni arrêt."""
    cfg = json.loads((EXEMPLE / "maison.json").read_text(encoding="utf-8"))
    del cfg["vent"]
    (tmp_path / "maison.json").write_text(json.dumps(cfg), encoding="utf-8")
    env = dict(os.environ, ASSISTANT_VOCAL_CONFIG=str(tmp_path))
    r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, 'poc'); import maison, meteo_mer"],
                       cwd=RACINE, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "la section « mer » est active mais la section « vent » est absente" in r.stderr


def test_c1_page_meteo_sans_vent_marche_seule(monkeypatch):
    """La prévision marine se sert sans section vent : le vent mesuré est éteint, pas la mer."""
    monkeypatch.setattr(VM, "ACTIF", False)
    assert VM.depuis_env() is None
    d = TM.lire(TM.mer(TM.Reseau()))
    assert [p["id"] for p in d["points"]] == ["prado", "pharo", "rade"]


# ------------------------------------------------------------ C3 : titre par défaut
def test_c3_nom_sert_de_titre_par_defaut():
    assert MM.titre_mer({"nom": "rade de Marseille"}) == "rade de Marseille"
    assert MM.titre_mer({"nom": "  baie fictive  "}) == "baie fictive"


def test_c3_titre_explicite_prioritaire_et_defaut_inchange():
    assert MM.titre_mer({"titre": "Mer à Marseille", "nom": "rade de Marseille"}) == "Mer à Marseille"
    assert MM.titre_mer({}) == "Mer"
    assert MM.titre_mer({"nom": "", "titre": " "}) == "Mer"
    assert MM.titre_mer({"nom": 12}) == "Mer"


def test_c3_titre_servi_dans_les_donnees():
    assert MM.TITRE == "Mer à Marseille"          # config-exemple/ donne un titre
    d = TM.lire(TM.mer(TM.Reseau()))
    assert d["titre"] == MM.TITRE


def test_c3_titre_servi_depuis_le_nom_sans_titre(monkeypatch):
    monkeypatch.setattr(MM, "TITRE", MM.titre_mer({"nom": "rade de Marseille"}))
    assert TM.lire(TM.mer(TM.Reseau()))["titre"] == "rade de Marseille"


# ------------------------------------------------------------ C9 : « actif » par source, mer
def lire_mer(mer_cfg, reseau):
    m = MM.MeteoMer(horloge=lambda: 0.0, maintenant=lambda: TM.MAINTENANT, transport=httpx.MockTransport(reseau),
                    mer=mer_cfg)
    return m, asyncio.run(m.donnees())


def test_c9_sans_cle_toutes_les_sources_sont_interrogees():
    cfg = mer_exemple()
    for source in ("modele_principal", "modele_second", "vagues_regional", "station"):
        cfg[source].pop("actif", None)
    reseau = TM.Reseau()
    m, d = lire_mer(cfg, reseau)
    assert set(reseau.vus) == {"principal", "second", "mfwam", "mr01", "mr02", "station"}
    assert m.inactives == [] and d["erreurs"] == []


def test_c9_source_inactive_n_est_pas_interrogee_ni_servie():
    cfg = mer_exemple()
    cfg["modele_second"]["actif"] = False
    cfg["mfwam"] = {"actif": False}
    cfg["station"]["actif"] = "false"
    reseau = TM.Reseau()
    m, d = lire_mer(cfg, reseau)
    assert set(reseau.vus) == {"principal", "mr01", "mr02"}
    assert sorted(m.inactives) == ["mfwam", "second", "station"]
    assert d["station"] is None and d["erreurs"] == []
    assert all(h["vent2"] is None and h["visi"] is None for p in d["points"] for h in p["heures"])
    assert "AROME" not in m.bilan() and "station" not in m.bilan()


def test_c9_un_lieu_vagues_regional_inactif_est_ignore():
    cfg = mer_exemple()
    cfg["vagues_regional"]["lieux"][1]["actif"] = False
    reseau = TM.Reseau()
    m, d = lire_mer(cfg, reseau)
    assert "mr02" not in reseau.vus and "mr01" in reseau.vus
    assert [s.nom for s in m.vagues_regional] == ["Vagues du Prado"]
    assert d["erreurs"] == []


def test_c9_vagues_regional_entier_inactif():
    cfg = mer_exemple()
    cfg["vagues_regional"]["actif"] = False
    reseau = TM.Reseau()
    m, d = lire_mer(cfg, reseau)
    assert not {"mr01", "mr02"} & set(reseau.vus) and m.vagues_regional == []
    assert {p["vagues_source"] for p in d["points"]} == {"mfwam"}


def test_c9_source_inactive_n_est_pas_une_panne():
    """Une source éteinte qui répondrait en erreur ne produit aucune erreur : elle n'est jamais appelée."""
    cfg = mer_exemple()
    cfg["station"]["actif"] = False
    reseau = TM.Reseau(station=httpx.Response(500))
    _, d = lire_mer(cfg, reseau)
    assert d["erreurs"] == [] and "station" not in reseau.vus


def test_c9_modele_principal_inactif_eteint_le_module(monkeypatch):
    cfg = mer_exemple()
    cfg["modele_principal"]["actif"] = False
    monkeypatch.setattr(MM, "MER", cfg)
    assert MM.depuis_env() is None
    reseau = TM.Reseau()
    m = MM.MeteoMer(horloge=lambda: 0.0, maintenant=lambda: TM.MAINTENANT, transport=httpx.MockTransport(reseau),
                    mer=cfg)
    with pytest.raises(MM.ErreurMer, match="désactivé"):
        asyncio.run(m.donnees())
    assert "principal" not in reseau.vus


def test_c9_libelle_sources_suit_les_cles():
    assert MM.libelle_sources() == ["ARPEGE", "AROME", "MFWAM", "vagues régionales d'exemple", "station"]
    cfg = mer_exemple()
    cfg["modele_second"]["actif"] = False
    cfg["station"]["actif"] = False
    assert MM.libelle_sources(cfg) == ["ARPEGE", "MFWAM", "vagues régionales d'exemple"]


# ------------------------------------------------------------ C9 : « actif » par source, vent
def lire_vent(vent_cfg, reseau):
    m = VM.VentMesure(horloge=lambda: 0.0, maintenant=lambda: TV.MAINTENANT, transport=httpx.MockTransport(reseau),
                      vent=vent_cfg)
    return m, asyncio.run(m.donnees())


def test_c9_vent_sans_cle_trois_sources():
    cfg = vent_exemple()
    for source in ("balises", "stations_officielles", "station"):
        cfg[source].pop("actif", None)
    reseau = TV.Reseau()
    m, d = lire_vent(cfg, reseau)
    assert set(reseau.vus) == {"pw", "mh", "terre"} and m.inactives == []


def test_c9_vent_source_inactive_pas_interrogee():
    cfg = vent_exemple()
    cfg["stations_officielles"]["actif"] = False
    cfg["station"]["actif"] = False
    reseau = TV.Reseau()
    m, d = lire_vent(cfg, reseau)
    assert set(reseau.vus) == {"pw"} and sorted(m.inactives) == ["station_terre", "stations_officielles"]
    assert d["erreurs"] == [] and d["stations"]
    assert "Stations officielles" not in m.bilan()


def test_c9_vent_tout_inactif_eteint_le_module(monkeypatch):
    cfg = vent_exemple()
    for source in ("balises", "stations_officielles", "station"):
        cfg[source]["actif"] = False
    monkeypatch.setattr(VM, "VENT", cfg)
    assert VM.libelle_sources() == []
    assert VM.depuis_env() is None


def test_c9_vent_libelle_sources():
    assert VM.libelle_sources() == ["Balises de la rade", "Stations officielles", "station"]
    cfg = vent_exemple()
    cfg["balises"]["actif"] = False
    assert VM.libelle_sources(cfg) == ["Stations officielles", "station"]


def test_c9_la_cle_actif_de_la_station_ne_fuit_pas_dans_la_fiche():
    assert "actif" not in VM.STATION_TERRE and "url" not in VM.STATION_TERRE


def test_c9_la_balise_inactive_est_retiree(tmp_path):
    """Une balise Balises de la rade avec "actif": false n'est pas gardée (lu à l'import, donc en sous-processus)."""
    cfg = json.loads((EXEMPLE / "maison.json").read_text(encoding="utf-8"))
    ident = next(iter(cfg["vent"]["balises"]["fiches"]))
    cfg["vent"]["balises"]["fiches"][ident]["actif"] = False
    (tmp_path / "maison.json").write_text(json.dumps(cfg), encoding="utf-8")
    env = dict(os.environ, ASSISTANT_VOCAL_CONFIG=str(tmp_path))
    code = f"import sys; sys.path.insert(0, 'poc'); import vent_mesure as V; print({int(ident)} in V.BALISES, len(V.BALISES))"
    r = subprocess.run([sys.executable, "-I", "-c", code], cwd=RACINE, env=env, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    avant = len(json.loads((EXEMPLE / "maison.json").read_text(encoding="utf-8"))["vent"]["balises"]["fiches"])
    assert r.stdout.strip() == f"False {avant - 1}"
