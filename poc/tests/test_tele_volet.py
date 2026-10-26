"""S-L3 (appli 0.39.0) : les commandes du volet de la télévision passent par les contrôles existants.

Le volet de l'appli n'envoie que media_player.select_source, volume_set, turn_on et turn_off. Aucune règle de
sécurité n'est élargie pour lui : ces services sont déjà dans la liste blanche et traversent
acces.controler_service comme toute commande. La liste des sources vient de reglages.tele.sources de maison.json."""
import acces
import liste_blanche
import maison
import securite

TELE = "media_player.tele_salon"


def test_la_configuration_d_exemple_decrit_les_tuiles_de_sources():
    tele = maison.CONFIG.get("reglages", {}).get("tele", {})
    sources = tele.get("sources", [])
    assert len(sources) == 7
    for s in sources:
        assert set(s) == {"nom", "source"}
        assert s["nom"].strip() and s["source"].strip()
    assert [s["nom"] for s in sources] == ["TNT", "Netflix", "YouTube", "Prime Video", "Disney+", "CANAL+", "HDMI 1"]
    # La tuile « Toutes » est ajoutée par l'appli, jamais déclarée dans la configuration.
    assert "Toutes" not in [s["nom"] for s in sources]


def test_la_cle_tele_n_est_pas_un_reglage_de_securite():
    # reglages.tele ne change aucune règle : refus_reglage ne lit que applis, interrupteurs et attributs_refuses.
    assert liste_blanche.refus_reglage("media_player", "select_source", {"entity_id": TELE, "source": "Netflix"}) is None


def test_les_services_du_volet_sont_deja_permis():
    permis = liste_blanche.SERVICES_PERMIS["media_player"]
    for service in ("select_source", "volume_set", "turn_on", "turn_off"):
        assert service in permis


def test_choisir_une_source_est_accepte():
    for s in maison.CONFIG["reglages"]["tele"]["sources"]:
        corps = {"entity_id": TELE, "source": s["source"]}
        assert acces.controler_service("media_player", "select_source", corps) is None


def test_allumer_et_eteindre_sont_acceptes():
    assert acces.controler_service("media_player", "turn_on", {"entity_id": TELE}) is None
    assert acces.controler_service("media_player", "turn_off", {"entity_id": TELE}) is None


def test_regler_le_volume_est_accepte_sous_le_plafond():
    niveau = min(0.35, securite.VOLUME_MAX)
    assert acces.controler_service("media_player", "volume_set", {"entity_id": TELE, "volume_level": niveau}) is None


def test_le_plafond_de_volume_en_dur_reste_applique():
    # Le volet plafonne côté appli, et securite.verifier refuse de son côté tout volume au-dessus du plafond.
    if securite.VOLUME_MAX >= 1.0:
        return
    trop_fort = min(1.0, securite.VOLUME_MAX + 0.1)
    refus = acces.controler_service("media_player", "volume_set", {"entity_id": TELE, "volume_level": trop_fort})
    assert refus is not None
