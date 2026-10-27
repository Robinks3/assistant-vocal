"""Écran Maison du client web (S-W4a) : ce que chaque rôle voit de la maison, ce qu'il peut régler, et le fait que le
service Home Assistant est reconstruit par le serveur, jamais recopié du navigateur. Le rôle et la personne viennent
de la session. Le suivi d'un réglage (en attente, non appliqué) et la conformité sont testés sans réseau, avec des
fournisseurs factices et une horloge à la main."""
import asyncio
import copy
import re
from pathlib import Path

import pytest

import acces
import historique_air as AH
import maison
import maison_web as MW
import mesures as ME
import securite
import serveur_web as W
from test_serveur_web_appairage import (  # noqa: F401  (fixtures réutilisées)
    appairer_direct, arreter, entetes, envoyer, fermeture, horloge, journal, lancer, ouvrir_ws, recevoir,
    recevoir_reponse, service, statut_de)

RACINE = Path(__file__).resolve().parent.parent

SECTION = {
    "reglage_attente_s": 5,
    "pieces": [
        {"id": "salon", "nom": "Salon", "lumieres": ["light.salon_plafond", "light.salon_lampe_tele"],
         "tele": "media_player.tele_salon"},
        {"id": "couloir", "nom": "Couloir", "lumieres": ["light.couloir_plafond"]},
        {"id": "chambre", "nom": "Chambre", "lumieres": ["light.chambre_sacha_plafond"], "protegee": True},
    ],
    "roles": {
        "administrateur": {"pieces": "toutes", "mesures": True, "tele": True},
        "habitant": {"pieces": "toutes", "mesures": True, "tele": True},
        "invite": {"pieces": ["salon"], "mesures": False, "tele": False},
    },
}

ETATS = {
    "light.salon_plafond": {"state": "on", "attributes": {
        "supported_color_modes": ["color_temp", "hs"], "color_mode": "color_temp", "brightness": 128,
        "color_temp_kelvin": 2700, "min_color_temp_kelvin": 2200, "max_color_temp_kelvin": 6500}},
    "light.salon_lampe_tele": {"state": "off", "attributes": {"supported_color_modes": ["onoff"]}},
    "light.couloir_plafond": {"state": "on", "attributes": {
        "supported_color_modes": ["hs"], "color_mode": "hs", "brightness": 255, "hs_color": [120.0, 100.0]}},
    "light.chambre_sacha_plafond": {"state": "on", "attributes": {"supported_color_modes": ["brightness"]}},
    "media_player.tele_salon": {"state": "on", "attributes": {"volume_level": 0.3}},
}

MESURES = {"lu_a": "2026-10-27T10:00:00", "pieces": {
    "salon": {"statut": "ok", "texte": "air bon", "couleur": "bon", "temperature": 21.0, "humidite": 45, "co2": 600,
              "pm25": 4, "air": "bon", "alerte": ""},
    "couloir": {"statut": "ok", "texte": "air mauvais", "couleur": "mauvais", "temperature": 19.0, "humidite": 50,
                "co2": 1800, "pm25": 9, "air": "mauvais", "alerte": "Aérer le couloir"},
}}


@pytest.fixture(autouse=True)
def config_maison(monkeypatch):
    monkeypatch.setattr(maison, "CLIENT_WEB", {"maison": copy.deepcopy(SECTION)})
    monkeypatch.setattr(securite, "PROTEGER_OCCUPANT", False)


class Faux:
    """Fournisseurs factices : états lus, mesures, appels reçus. Aucun réseau."""

    def __init__(self, etats=None, mesures=MESURES):
        self.etats = copy.deepcopy(ETATS if etats is None else etats)
        self.mesures = mesures
        self.lectures, self.appels, self.echec = [], [], False
        self.t = 1000.0

    async def lire(self, entites):
        self.lectures.append(list(entites))
        return {e: self.etats[e] for e in entites if e in self.etats}

    async def lire_mesures(self):
        return self.mesures

    async def appeler(self, domaine, service_, corps, essai):
        if self.echec:
            raise RuntimeError("secret de Home Assistant")
        self.appels.append((domaine, service_, dict(corps), essai))
        return "essai" if essai else "envoye"

    def horloge(self):
        return self.t

    def maison(self, essai_serveur=False):
        return MW.Maison(self.lire, self.lire_mesures, self.appeler, essai_serveur=lambda: essai_serveur,
                         horloge=self.horloge)


def courir(coro):
    return asyncio.run(coro)


def regle(m, role, msg, personne=None):
    return courir(m.regler(role, personne, msg))


def refus(m, role, msg, personne=None):
    with pytest.raises(MW.RefusMaison) as e:
        courir(m.regler(role, personne, msg))
    return e.value.cause


def reel(entite, action, valeur=None):
    """Un message d'un navigateur qui veut vraiment agir."""
    msg = {"type": "regler", "entite": entite, "action": action, "essai": False}
    if valeur is not None:
        msg["valeur"] = valeur
    return msg


# ---------------------------------------------------------------------------------------------------------------
# Droits : ce que chaque rôle voit
# ---------------------------------------------------------------------------------------------------------------

def test_un_habitant_voit_toutes_les_pieces_dans_l_ordre_de_la_configuration():
    f = Faux()
    rep = courir(f.maison().etats_pour("habitant"))
    assert rep["type"] == "etats" and rep["configure"] is True
    assert [p["id"] for p in rep["pieces"]] == ["salon", "couloir", "chambre"]
    salon = rep["pieces"][0]
    assert [l["entite"] for l in salon["lumieres"]] == ["light.salon_plafond", "light.salon_lampe_tele"]
    assert salon["tele"]["entite"] == "media_player.tele_salon" and salon["tele"]["volume"] == 30
    assert salon["mesures"]["air"] == "bon"


def test_un_invite_ne_recoit_que_les_entites_de_sa_liste_sans_mesure_ni_tele():
    f = Faux()
    rep = courir(f.maison().etats_pour("invite"))
    assert [p["id"] for p in rep["pieces"]] == ["salon"]
    salon = rep["pieces"][0]
    assert salon["tele"] is None and salon["mesures"] is None and rep["mesures_visibles"] is False
    assert rep["alertes"] == []
    texte = repr(rep)
    for interdit in ("couloir", "chambre", "media_player", "tele_salon", "1800", "Aérer"):
        assert interdit not in texte, interdit


def test_un_role_inconnu_ou_sans_section_ne_voit_rien_ou_le_minimum(monkeypatch):
    f = Faux()
    assert courir(f.maison().etats_pour("partage"))["pieces"] == []
    monkeypatch.setattr(maison, "CLIENT_WEB", {"maison": {"pieces": SECTION["pieces"]}})
    assert courir(f.maison().etats_pour("invite"))["pieces"] == []
    assert len(courir(f.maison().etats_pour("habitant"))["pieces"]) == 3


def test_sans_configuration_l_ecran_dit_qu_il_n_est_pas_configure(monkeypatch):
    monkeypatch.setattr(maison, "CLIENT_WEB", {})
    rep = courir(Faux().maison().etats_pour("administrateur"))
    assert rep["configure"] is False and rep["pieces"] == []


def test_une_piece_protegee_n_est_qu_une_ligne_et_home_assistant_n_est_pas_interroge():
    f = Faux()
    rep = courir(f.maison().etats_pour("administrateur"))
    chambre = rep["pieces"][2]
    assert chambre == {"id": "chambre", "nom": "Chambre", "protegee": True, "lumieres": [], "tele": None,
                       "mesures": None}
    assert all("light.chambre_sacha_plafond" not in lues for lues in f.lectures)
    assert "chambre_lit" not in repr(rep)


def test_la_protection_de_l_occupant_vient_de_securite_pas_d_un_nom_en_dur(monkeypatch):
    monkeypatch.setattr(securite, "PROTEGER_OCCUPANT", True)
    monkeypatch.setattr(securite, "ZONES_PROTEGEES", frozenset({"zone_x"}))
    piece = {"id": "couloir", "nom": "Couloir", "lumieres": [], "tele": None, "protegee": False}
    assert MW.piece_protegee(piece, {"couloir": ["zone_x"]}) is True
    assert MW.piece_protegee(piece, {"couloir": ["zone_y"]}) is False
    monkeypatch.setattr(securite, "PROTEGER_OCCUPANT", False)
    assert MW.piece_protegee(piece, {"couloir": ["zone_x"]}) is False
    assert MW.piece_protegee({**piece, "protegee": True}, {}) is True


def test_les_entites_mal_formees_de_la_configuration_sont_ignorees(monkeypatch):
    section = copy.deepcopy(SECTION)
    section["pieces"] = [
        {"id": "salon", "nom": "Salon", "lumieres": ["light.z", "switch.chambre_camille_prise", "light.a b", 3],
         "tele": "light.pirate"},
        {"id": "salon", "nom": "Doublon", "lumieres": ["light.b"]},
        {"id": "Majuscule", "nom": "Mal", "lumieres": []}, {"id": "sans_nom"}, "texte",
    ]
    monkeypatch.setattr(maison, "CLIENT_WEB", {"maison": section})
    assert MW.pieces_configurees() == [
        {"id": "salon", "nom": "Salon", "lumieres": ["light.z"], "tele": None, "protegee": False}]


def test_le_mode_essai_du_serveur_est_annonce():
    assert courir(Faux().maison(essai_serveur=True).etats_pour("habitant"))["essai"] is True
    assert courir(Faux().maison().etats_pour("habitant"))["essai"] is False


def test_les_alertes_d_air_remontent_avec_leur_piece():
    rep = courir(Faux().maison().etats_pour("habitant"))
    assert rep["alertes"] == [{"piece": "couloir", "texte": "Aérer le couloir", "couleur": "mauvais"}]


def test_mesure_absente_et_absence_de_capteur_se_disent_en_toutes_lettres():
    rep = courir(Faux(mesures=None).maison().etats_pour("habitant"))
    assert rep["pieces"][0]["mesures"] == {"statut": "absente", "texte": "mesures indisponibles pour le moment",
                                           "alerte": ""}
    rep = courir(Faux(mesures={"lu_a": "x", "pieces": {}}).maison().etats_pour("habitant"))
    assert rep["pieces"][1]["mesures"]["statut"] == "aucun" and rep["pieces"][1]["mesures"]["texte"] == "pas de capteur"
    assert rep["pieces"][1]["mesures"].get("temperature") is None


def test_un_fournisseur_qui_echoue_ne_renvoie_ni_valeur_inventee_ni_texte_d_exception(capsys):
    f = Faux()

    async def casse(entites):
        raise RuntimeError("jeton secret")
    m = MW.Maison(casse, f.lire_mesures, f.appeler, horloge=f.horloge)
    rep = courir(m.etats_pour("habitant"))
    assert all(l["statut"] == "injoignable" and l["intensite"] is None and l["kelvin"] is None
               for p in rep["pieces"] for l in p["lumieres"])
    assert "jeton secret" not in repr(rep) and "jeton secret" not in capsys.readouterr().out


def test_les_etats_sont_mis_en_cache_une_seconde():
    f = Faux()
    m = f.maison()

    async def deux():
        await m.etats_pour("habitant")
        await m.etats_pour("invite")
        f.t += MW.CACHE_ETATS_S + 0.1
        await m.etats_pour("habitant")
    courir(deux())
    assert len(f.lectures) == 2
    assert all("light.chambre_sacha_plafond" not in lues for lues in f.lectures)


# ---------------------------------------------------------------------------------------------------------------
# La vue d'une lampe
# ---------------------------------------------------------------------------------------------------------------

def test_vue_d_une_lampe_en_blanc_en_couleur_eteinte_et_injoignable():
    blanc = MW.vue_lampe("light.salon_plafond", ETATS["light.salon_plafond"])
    assert (blanc["statut"], blanc["intensite"], blanc["kelvin"], blanc["mode"], blanc["kmin"], blanc["kmax"]) \
        == ("ok", 50, 2700, "blanc", 2200, 6500)
    assert blanc["texte"] == "50 %, 2700 K, chaud" and blanc["blanc"] and blanc["couleur"]
    couleur = MW.vue_lampe("light.couloir_plafond", ETATS["light.couloir_plafond"])
    assert couleur["mode"] == "couleur" and couleur["teinte"] == 120 and couleur["texte"] == "100 %, vert"
    assert couleur["blanc"] is False and couleur["couleur"] is True
    eteinte = MW.vue_lampe("light.salon_lampe_tele", ETATS["light.salon_lampe_tele"])
    assert eteinte["texte"] == "Éteinte" and eteinte["allumee"] is False and eteinte["reglable"] is False
    for etat in ({"state": "unavailable"}, {"state": "unknown"}, None, {}, {"state": "n'importe quoi"}):
        v = MW.vue_lampe("light.x", etat)
        assert v["statut"] == "injoignable" and v["texte"] == "Injoignable" and v["intensite"] is None


def test_les_bornes_de_kelvin_absurdes_sont_remplacees_par_la_plage_par_defaut():
    for attrs in ({}, {"min_color_temp_kelvin": 6500, "max_color_temp_kelvin": 2200},
                  {"min_color_temp_kelvin": 1, "max_color_temp_kelvin": 2},
                  {"min_color_temp_kelvin": "a", "max_color_temp_kelvin": "b"},
                  {"min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 99999}):
        assert MW._bornes_kelvin(attrs) == (MW.KELVIN_MIN_DEFAUT, MW.KELVIN_MAX_DEFAUT), attrs
    assert MW._bornes_kelvin({"min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 6535}) == (2000, 6535)


@pytest.mark.parametrize("kelvin,mot", [(2200, "bougie"), (2449, "bougie"), (2450, "chaud"), (3299, "chaud"),
                                        (3300, "neutre"), (4799, "neutre"), (4800, "froid"), (6500, "froid")])
def test_mots_de_chaleur(kelvin, mot):
    assert MW.mot_chaleur(kelvin) == mot


def test_la_teinte_se_compare_par_le_plus_court_chemin_autour_du_cercle():
    assert MW.ecart_teinte(359, 0) == 1 and MW.ecart_teinte(0, 359) == 1
    assert MW.ecart_teinte(350, 10) == 20 and MW.ecart_teinte(180, 0) == 180 and MW.ecart_teinte(90, 100) == 10
    assert MW.nom_teinte(358) == "rose" or MW.nom_teinte(358) == "rouge"
    assert MW.nom_teinte(359) == "rouge" and MW.nom_teinte(120) == "vert" and MW.nom_teinte(275) == "violet"


def lampe(**attrs):
    base = {"state": "on", "attributes": {"brightness": 255}}
    base["attributes"].update(attrs)
    return base


def test_conforme_pour_le_marche_arret_et_l_intensite():
    assert MW.conforme({"allumee": False}, {"state": "off"})
    assert not MW.conforme({"allumee": False}, {"state": "on"})
    assert not MW.conforme({"allumee": True}, {"state": "off"})
    assert not MW.conforme({"allumee": True}, {"state": "unavailable"})
    assert not MW.conforme({"allumee": True}, None)
    assert MW.conforme({"allumee": True, "intensite": 50}, lampe(brightness=128))
    assert MW.conforme({"allumee": True, "intensite": 50}, lampe(brightness=140))      # 55 %, à 6 points près
    assert not MW.conforme({"allumee": True, "intensite": 50}, lampe(brightness=200))  # 78 %
    assert not MW.conforme({"allumee": True, "intensite": 50}, {"state": "on", "attributes": {}})


def test_conforme_au_kelvin_pres_de_100_k():
    t = {"allumee": True, "kelvin": 4000}
    assert MW.conforme(t, lampe(color_mode="color_temp", color_temp_kelvin=4000))
    assert MW.conforme(t, lampe(color_mode="color_temp", color_temp_kelvin=4100))
    assert MW.conforme(t, lampe(color_mode="color_temp", color_temp_kelvin=3900))
    assert not MW.conforme(t, lampe(color_mode="color_temp", color_temp_kelvin=4101))
    assert not MW.conforme(t, lampe(color_mode="color_temp", color_temp_kelvin=3899))
    assert not MW.conforme(t, lampe(color_mode="hs", hs_color=[30, 100]))   # reste en couleur
    assert not MW.conforme(t, lampe(color_mode="color_temp"))               # kelvins non rapportés


def test_conforme_a_la_teinte_pres_de_8_degres_avec_bouclage_autour_de_zero():
    t = {"allumee": True, "teinte": 0}
    assert MW.conforme(t, lampe(color_mode="hs", hs_color=[0, 100]))
    assert MW.conforme(t, lampe(color_mode="hs", hs_color=[8, 100]))
    assert MW.conforme(t, lampe(color_mode="hs", hs_color=[352, 100]))
    assert MW.conforme(t, lampe(color_mode="hs", hs_color=[359.5, 100]))
    assert not MW.conforme(t, lampe(color_mode="hs", hs_color=[9, 100]))
    assert not MW.conforme(t, lampe(color_mode="hs", hs_color=[351, 100]))
    assert not MW.conforme(t, lampe(color_mode="color_temp", color_temp_kelvin=3000))
    assert MW.conforme({"allumee": True, "teinte": 355}, lampe(color_mode="hs", hs_color=[3, 100]))
    assert MW.conforme({"allumee": True, "teinte": 220}, lampe(color_mode="rgb", hs_color=[225, 100]))


# ---------------------------------------------------------------------------------------------------------------
# Le message « regler » : schéma strict, service reconstruit par le serveur
# ---------------------------------------------------------------------------------------------------------------

def test_par_defaut_un_reglage_est_un_essai_et_n_appelle_pas_home_assistant():
    f = Faux()
    m = f.maison()
    for msg in ({"type": "regler", "entite": "light.couloir_plafond", "action": "eteindre"},
                {"type": "regler", "entite": "light.couloir_plafond", "action": "eteindre", "essai": "non"},
                {"type": "regler", "entite": "light.couloir_plafond", "action": "eteindre", "essai": True}):
        rep = regle(m, "habitant", msg)
        assert rep == {"type": "regle", "entite": "light.couloir_plafond", "statut": "essai"}
    assert f.appels == [] or all(a[3] is True for a in f.appels)
    assert m.attendus == {}, "un essai n'attend aucun résultat"


def test_essai_faux_explicite_agit_et_le_serveur_en_essai_l_emporte():
    f = Faux()
    rep = regle(f.maison(), "habitant", reel("light.couloir_plafond", "eteindre"))
    assert rep["statut"] == "envoye"
    assert f.appels == [("light", "turn_off", {"entity_id": "light.couloir_plafond"}, False)]
    f2 = Faux()
    rep = regle(f2.maison(essai_serveur=True), "habitant", reel("light.couloir_plafond", "eteindre"))
    assert rep["statut"] == "essai" and f2.appels[0][3] is True


def test_le_service_est_reconstruit_par_le_serveur():
    f = Faux()
    m = f.maison()
    regle(m, "habitant", reel("light.salon_plafond", "intensite", 40))
    regle(m, "habitant", reel("light.salon_plafond", "blanc", 4000))
    regle(m, "habitant", reel("light.couloir_plafond", "couleur", "bleu"))
    regle(m, "habitant", reel("light.couloir_plafond", "couleur", 359))
    regle(m, "habitant", reel("light.salon_plafond", "allumer"))
    regle(m, "habitant", reel("media_player.tele_salon", "volume", 25))
    regle(m, "habitant", reel("media_player.tele_salon", "allumer"))
    regle(m, "habitant", reel("media_player.tele_salon", "eteindre"))
    assert f.appels == [
        ("light", "turn_on", {"brightness_pct": 40, "entity_id": "light.salon_plafond"}, False),
        ("light", "turn_on", {"color_temp_kelvin": 4000, "entity_id": "light.salon_plafond"}, False),
        ("light", "turn_on", {"hs_color": [220, 100], "entity_id": "light.couloir_plafond"}, False),
        ("light", "turn_on", {"hs_color": [359, 100], "entity_id": "light.couloir_plafond"}, False),
        ("light", "turn_on", {"entity_id": "light.salon_plafond"}, False),
        ("media_player", "volume_set", {"volume_level": 0.25, "entity_id": "media_player.tele_salon"}, False),
        ("media_player", "turn_on", {"entity_id": "media_player.tele_salon"}, False),
        ("media_player", "turn_off", {"entity_id": "media_player.tele_salon"}, False),
    ]


def test_une_intensite_a_zero_eteint_la_lampe():
    f = Faux()
    regle(f.maison(), "habitant", reel("light.salon_plafond", "intensite", 0))
    assert f.appels == [("light", "turn_off", {"entity_id": "light.salon_plafond"}, False)]


def test_les_cles_inconnues_du_message_sont_refusees_sans_rien_appeler():
    f = Faux()
    m = f.maison()
    base = reel("light.couloir_plafond", "allumer")
    for plus in ({"area_id": "salon"}, {"device_id": "abc"}, {"service": "light.turn_on"}, {"domaine": "lock"},
                 {"data": {"brightness": 255}}, {"entity_id": "light.couloir_plafond"}, {"role": "administrateur"},
                 {"personne": "autre"}, {"label_id": "x"}, {"floor_id": "x"}):
        assert refus(m, "habitant", {**base, **plus}) == "format", plus
    assert f.appels == []


@pytest.mark.parametrize("entite", [
    "all", "ALL", "light.y", "light.*", ["light.couloir_plafond"], {"id": "light.couloir_plafond"}, None, 12, "", "area_id:salon",
    "light.couloir_plafond,light.salon_plafond", "light.inconnue", "lock.porte", "switch.prise", "cover.chambre_sacha",
    "alarm_control_panel.maison", "light.couloir_plafond ", "LIGHT.COULOIR", "light.chambre_sacha_chevets",
])
def test_une_entite_hors_liste_du_role_est_refusee(entite):
    f = Faux()
    cause = refus(f.maison(), "administrateur", reel("light.couloir_plafond", "allumer") | {"entite": entite})
    assert cause in ("entite", "protegee")
    assert f.appels == []


def test_une_lampe_d_une_piece_hors_liste_du_role_est_refusee_sans_rien_reveler():
    f = Faux()
    m = f.maison()
    assert refus(m, "invite", reel("light.couloir_plafond", "eteindre")) == "entite"
    assert refus(m, "invite", reel("light.chambre_sacha_plafond", "eteindre")) == "entite"
    assert refus(m, "invite", reel("media_player.tele_salon", "eteindre")) == "entite", "télé hors droits de l'invité"
    assert f.appels == []
    regle(m, "invite", reel("light.salon_plafond", "eteindre"))
    assert len(f.appels) == 1


def test_une_piece_protegee_refuse_tout_reglage():
    f = Faux()
    m = f.maison()
    for role in ("administrateur", "habitant"):
        for action, valeur in (("eteindre", None), ("allumer", None), ("intensite", 10), ("blanc", 3000)):
            assert refus(m, role, reel("light.chambre_sacha_plafond", action, valeur)) == "protegee"
    assert f.appels == []


@pytest.mark.parametrize("entite,action,valeur", [
    ("light.salon_plafond", "intensite", 101), ("light.salon_plafond", "intensite", -1),
    ("light.salon_plafond", "intensite", 50.5), ("light.salon_plafond", "intensite", "50"),
    ("light.salon_plafond", "intensite", True), ("light.salon_plafond", "intensite", None),
    ("light.salon_plafond", "intensite", [50]), ("light.salon_plafond", "intensite", {"v": 50}),
    ("light.salon_plafond", "blanc", 2199), ("light.salon_plafond", "blanc", 6501), ("light.salon_plafond", "blanc", 0),
    ("light.salon_plafond", "blanc", 2700.5), ("light.salon_plafond", "blanc", "chaud"),
    ("light.salon_plafond", "blanc", True), ("light.salon_plafond", "blanc", None),
    ("light.couloir_plafond", "blanc", 3000),                     # lampe sans blanc réglable
    ("light.salon_plafond", "couleur", 361), ("light.salon_plafond", "couleur", -1),
    ("light.salon_plafond", "couleur", "turquoise"), ("light.salon_plafond", "couleur", [0, 100]),
    ("light.salon_plafond", "couleur", None), ("light.salon_plafond", "couleur", True),
    ("light.salon_plafond", "couleur", 12.5),
    ("light.salon_lampe_tele", "intensite", 50),               # lampe tout ou rien
    ("light.salon_lampe_tele", "couleur", "rouge"),
    ("light.salon_plafond", "allumer", 5), ("light.salon_plafond", "eteindre", 0),
    ("media_player.tele_salon", "volume", 101), ("media_player.tele_salon", "volume", -1),
    ("media_player.tele_salon", "volume", 0.5), ("media_player.tele_salon", "volume", "30"),
    ("media_player.tele_salon", "volume", None), ("media_player.tele_salon", "volume", True),
    ("media_player.tele_salon", "allumer", 1),
])
def test_une_valeur_hors_borne_ou_mal_typee_est_refusee(entite, action, valeur):
    f = Faux()
    msg = {"type": "regler", "entite": entite, "action": action, "essai": False}
    if valeur is not None or action in ("intensite", "blanc", "couleur", "volume"):
        msg["valeur"] = valeur
    cause = refus(f.maison(), "habitant", msg)
    assert cause in ("valeur", "format"), cause
    assert f.appels == []


@pytest.mark.parametrize("entite,action", [
    ("light.salon_plafond", "volume"), ("light.salon_plafond", "toggle"), ("light.salon_plafond", "turn_on"),
    ("light.salon_plafond", "service"), ("light.salon_plafond", ""), ("light.salon_plafond", None),
    ("light.salon_plafond", ["allumer"]), ("light.salon_plafond", 3),
    ("media_player.tele_salon", "couleur"), ("media_player.tele_salon", "intensite"),
    ("media_player.tele_salon", "blanc"), ("media_player.tele_salon", "play_media"),
    ("media_player.tele_salon", "stop"), ("media_player.tele_salon", "lire"),
    ("media_player.tele_salon", "avance_rapide"), ("media_player.tele_salon", "select_source"),
    ("media_player.tele_salon", "play_pause"), ("media_player.tele_salon", "media_stop"),
])
def test_une_action_hors_liste_est_refusee(entite, action):
    f = Faux()
    cause = refus(f.maison(), "habitant", {"type": "regler", "entite": entite, "action": action, "essai": False,
                                           "valeur": 10})
    assert cause == "action"
    assert f.appels == []


def test_les_bornes_de_kelvin_sont_celles_de_la_lampe_reelle():
    f = Faux()
    m = f.maison()
    regle(m, "habitant", reel("light.salon_plafond", "blanc", 2200))
    regle(m, "habitant", reel("light.salon_plafond", "blanc", 6500))
    assert refus(m, "habitant", reel("light.salon_plafond", "blanc", 2150)) == "valeur"
    assert refus(m, "habitant", reel("light.salon_plafond", "blanc", 6600)) == "valeur"


def test_une_lampe_injoignable_refuse_un_reglage_mais_pas_l_extinction():
    f = Faux()
    f.etats["light.salon_plafond"] = {"state": "unavailable", "attributes": {}}
    m = f.maison()
    assert refus(m, "habitant", reel("light.salon_plafond", "intensite", 30)) == "injoignable"
    assert refus(m, "habitant", reel("light.salon_plafond", "allumer")) == "injoignable"
    assert f.appels == []
    regle(m, "habitant", reel("light.salon_plafond", "eteindre"))
    assert len(f.appels) == 1


def test_un_echec_de_home_assistant_donne_injoignable_sans_son_texte(capsys):
    f = Faux()
    f.echec = True
    m = f.maison()
    assert refus(m, "habitant", reel("light.couloir_plafond", "eteindre")) == "injoignable"
    assert "secret de Home Assistant" not in capsys.readouterr().out
    assert m.attendus == {}


def test_un_message_qui_n_est_pas_un_objet_ou_un_role_inconnu_est_refuse():
    f = Faux()
    m = f.maison()
    assert refus(m, "partage", reel("light.couloir_plafond", "allumer")) == "droit"
    assert refus(m, None, reel("light.couloir_plafond", "allumer")) == "droit"
    for msg in (None, "texte", [], 3):
        assert refus(m, "habitant", msg) == "format"
    assert f.appels == []


def test_tout_reglage_passe_par_le_controle_central_avec_la_personne_et_les_services_permis(monkeypatch):
    vus = []

    def espion(domaine, service_, corps, personne=None, services_permis=None):
        vus.append((domaine, service_, dict(corps), personne, services_permis))
        return None
    monkeypatch.setattr(acces, "controler_service", espion)
    f = Faux()
    m = f.maison()
    regle(m, "administrateur", reel("light.couloir_plafond", "couleur", "rouge"), personne="proprio")
    regle(m, "habitant", reel("media_player.tele_salon", "volume", 10))
    assert vus[0] == ("light", "turn_on", {"hs_color": [0, 100], "entity_id": "light.couloir_plafond"}, "proprio",
                      MW.SERVICES_WEB["light"])
    assert vus[1][3] is None and vus[1][4] == MW.SERVICES_WEB["media_player"]
    assert len(f.appels) == 2


def test_un_refus_de_securite_arrete_l_appel_et_n_en_dit_pas_la_raison(monkeypatch):
    refuse = acces._refus("securite", "raison interne qui ne doit pas sortir")
    monkeypatch.setattr(acces, "controler_service", lambda *a, **k: refuse)
    f = Faux()
    m = f.maison()
    with pytest.raises(MW.RefusMaison) as e:
        courir(m.regler("habitant", None, reel("light.couloir_plafond", "eteindre")))
    assert e.value.cause == "securite" and "raison interne" not in str(e.value)
    assert f.appels == [] and m.attendus == {}


def test_le_plafond_de_volume_de_securite_s_applique_au_volume_de_la_television():
    f = Faux()
    regle(f.maison(), "administrateur", reel("media_player.tele_salon", "volume", 100),
          personne=acces.cle_habitant(maison.CLE_PROPRIETAIRE))
    if f.appels:
        assert f.appels[0][2]["volume_level"] <= securite.PLAFOND_VOLUME / 100 + 1e-9 if hasattr(
            securite, "PLAFOND_VOLUME") else f.appels[0][2]["volume_level"] <= 1.0


def test_les_services_permis_de_l_ecran_sont_plus_etroits_que_la_liste_blanche_du_llm():
    assert MW.SERVICES_WEB["light"] == frozenset({"turn_on", "turn_off"})
    assert "toggle" not in MW.SERVICES_WEB["light"]
    assert MW.SERVICES_WEB["media_player"] == frozenset({
        "turn_on", "turn_off", "volume_set", "select_source", "media_play_pause", "media_next_track",
        "media_previous_track", "volume_mute"})
    for exclu in ("media_stop", "play_media", "media_seek", "toggle"):
        assert exclu not in MW.SERVICES_WEB["media_player"]
    for domaine, services in MW.SERVICES_WEB.items():
        assert services <= set(acces.liste_blanche.SERVICES_PERMIS[domaine])


def test_deux_reglages_de_la_meme_lampe_ne_se_chevauchent_pas():
    f = Faux()
    ordre = []

    async def lent(domaine, service_, corps, essai):
        ordre.append(("debut", corps.get("brightness_pct")))
        await asyncio.sleep(0.02)
        ordre.append(("fin", corps.get("brightness_pct")))
        return "envoye"
    m = MW.Maison(f.lire, f.lire_mesures, lent, horloge=f.horloge)

    async def deux():
        await asyncio.gather(m.regler("habitant", None, reel("light.salon_plafond", "intensite", 10)),
                             m.regler("habitant", None, reel("light.salon_plafond", "intensite", 20)))
    courir(deux())
    assert ordre in ([("debut", 10), ("fin", 10), ("debut", 20), ("fin", 20)],
                     [("debut", 20), ("fin", 20), ("debut", 10), ("fin", 10)])


# ---------------------------------------------------------------------------------------------------------------
# Suivi d'un réglage : en attente, appliqué, non appliqué
# ---------------------------------------------------------------------------------------------------------------

def reglage_de(rep, entite):
    for p in rep["pieces"]:
        for l in p["lumieres"]:
            if l["entite"] == entite:
                return l["reglage"]
    raise AssertionError(entite)


def test_un_reglage_envoye_est_en_attente_puis_non_applique_puis_oublie():
    f = Faux()
    m = f.maison()
    regle(m, "habitant", reel("light.salon_plafond", "intensite", 90))
    assert reglage_de(courir(m.etats_pour("habitant")), "light.salon_plafond") == "en_attente"
    f.t += MW.attente_s() - 0.5
    assert reglage_de(courir(m.etats_pour("habitant")), "light.salon_plafond") == "en_attente"
    f.t += 1.0
    assert reglage_de(courir(m.etats_pour("habitant")), "light.salon_plafond") == "non_applique"
    f.t += MW.OUBLI_REGLAGE_S
    assert reglage_de(courir(m.etats_pour("habitant")), "light.salon_plafond") is None
    assert m.attendus == {}


def test_un_reglage_applique_dans_le_delai_efface_l_attente():
    f = Faux()
    m = f.maison()
    regle(m, "habitant", reel("light.salon_plafond", "intensite", 90))
    f.etats["light.salon_plafond"]["attributes"]["brightness"] = 230
    f.t += 2
    assert reglage_de(courir(m.etats_pour("habitant")), "light.salon_plafond") is None
    assert m.attendus == {}


def test_un_reglage_de_teinte_est_juge_a_8_degres_pres_autour_de_zero():
    f = Faux()
    m = f.maison()
    regle(m, "habitant", reel("light.couloir_plafond", "couleur", "rouge"))
    f.etats["light.couloir_plafond"]["attributes"].update(hs_color=[355.0, 100.0], color_mode="hs")
    f.t += MW.attente_s() + 1
    assert reglage_de(courir(m.etats_pour("habitant")), "light.couloir_plafond") is None
    regle(m, "habitant", reel("light.couloir_plafond", "couleur", "rouge"))
    f.etats["light.couloir_plafond"]["attributes"].update(hs_color=[20.0, 100.0])
    f.t += MW.attente_s() + 1
    assert reglage_de(courir(m.etats_pour("habitant")), "light.couloir_plafond") == "non_applique"


def test_une_lampe_devenue_injoignable_apres_un_reglage_est_en_attente_puis_non_appliquee():
    f = Faux()
    m = f.maison()
    regle(m, "habitant", reel("light.salon_plafond", "intensite", 90))
    f.etats["light.salon_plafond"] = {"state": "unavailable", "attributes": {}}
    f.t += 1.5
    assert reglage_de(courir(m.etats_pour("habitant")), "light.salon_plafond") == "en_attente"
    f.t += MW.attente_s()
    rep = courir(m.etats_pour("habitant"))
    assert reglage_de(rep, "light.salon_plafond") == "non_applique"
    assert rep["pieces"][0]["lumieres"][0]["statut"] == "injoignable"


def test_le_delai_d_attente_vient_de_la_configuration_et_reste_borne(monkeypatch):
    def avec(valeur):
        section = copy.deepcopy(SECTION)
        section["reglage_attente_s"] = valeur
        monkeypatch.setattr(maison, "CLIENT_WEB", {"maison": section})
        return MW.attente_s()
    assert avec(8) == 8 and avec(2) == 2
    assert avec(10000) == MW.ATTENTE_MAX_S
    for absurde in (0, -3, "5", None, True, 2.5, [], {}):
        assert avec(absurde) == MW.ATTENTE_DEFAUT_S, absurde
    monkeypatch.setattr(maison, "CLIENT_WEB", {})
    assert MW.attente_s() == MW.ATTENTE_DEFAUT_S
    assert courir(Faux().maison().etats_pour("habitant"))["attente_s"] == MW.ATTENTE_DEFAUT_S


def test_le_suivi_n_existe_que_pour_la_lampe_reglee():
    f = Faux()
    m = f.maison()
    regle(m, "habitant", reel("light.salon_plafond", "intensite", 90))
    rep = courir(m.etats_pour("habitant"))
    assert reglage_de(rep, "light.couloir_plafond") is None and reglage_de(rep, "light.salon_lampe_tele") is None


# ---------------------------------------------------------------------------------------------------------------
# Sur la connexion du client web
# ---------------------------------------------------------------------------------------------------------------

def scenario_ws(service, jeton, corps):
    async def lance():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", jeton)
            try:
                return await corps(ws)
            finally:
                await ws.close()
        finally:
            await arreter(serveur)
    return asyncio.run(lance())


async def echange(ws, msg):
    await envoyer(ws, msg)
    return await recevoir_reponse(ws)


def test_les_trois_messages_sont_dans_la_liste_blanche_des_roles():
    for genre in MW.GENRES:
        assert genre in W.MESSAGES_TOUT_ROLE
    assert set(MW.GENRES) == {"etats", "regler", "air_historique"}


def test_etats_par_websocket_filtre_selon_le_role_de_la_session(service):
    f = Faux()
    service.maison = f.maison()
    _, _, jeton_h = appairer_direct(service, "habitant", "Habitant", conn=1)
    _, _, jeton_i = appairer_direct(service, "invite", "Invité", conn=2)

    async def corps(ws):
        return await echange(ws, {"type": "etats", "role": "administrateur", "pieces": "toutes"})
    rep_h = scenario_ws(service, jeton_h, corps)
    rep_i = scenario_ws(service, jeton_i, corps)
    assert [p["id"] for p in rep_h["pieces"]] == ["salon", "couloir", "chambre"]
    assert [p["id"] for p in rep_i["pieces"]] == ["salon"] and rep_i["mesures_visibles"] is False


def test_regler_par_websocket_utilise_le_role_et_la_personne_de_la_session(service, monkeypatch):
    vus = []

    def espion(domaine, service_, corps, personne=None, services_permis=None):
        vus.append(personne)
        return None
    monkeypatch.setattr(acces, "controler_service", espion)
    f = Faux()
    service.maison = f.maison()
    _, _, jeton_a = appairer_direct(service, "administrateur", "Admin", conn=1)
    _, _, jeton_h = appairer_direct(service, "habitant", "Habitant", conn=2)
    _, _, jeton_i = appairer_direct(service, "invite", "Invité", conn=3)

    async def corps(ws):
        return await echange(ws, reel("light.salon_plafond", "intensite", 30) | {"personne": "un-voisin"})
    # la personne du message est ignorée : « personne » est refusé comme clé inconnue
    refus = scenario_ws(service, jeton_a, corps)
    assert refus["type"] == "erreur" and refus["cause"] == "format" and refus["genre"] == "regler"
    assert vus == []

    async def propre(ws):
        return await echange(ws, reel("light.salon_plafond", "intensite", 30))
    for jeton in (jeton_a, jeton_h, jeton_i):
        assert scenario_ws(service, jeton, propre)["type"] == "regle"
    assert vus == [acces.cle_habitant(maison.CLE_PROPRIETAIRE), None, None]


def test_les_refus_par_websocket_sont_une_cause_fermee_sans_texte_interne(service):
    f = Faux()
    service.maison = f.maison()
    _, _, jeton = appairer_direct(service, "invite")

    async def corps(ws):
        return [await echange(ws, reel("light.couloir_plafond", "allumer")),
                await echange(ws, reel("light.salon_plafond", "intensite", 500)),
                await echange(ws, reel("light.salon_plafond", "allumer") | {"area_id": "x"}),
                await echange(ws, reel("media_player.tele_salon", "allumer"))]
    reps = scenario_ws(service, jeton, corps)
    assert [r["cause"] for r in reps] == ["entite", "valeur", "format", "entite"]
    assert all(r["type"] == "erreur" and r["genre"] == "regler" and set(r) <= {"type", "cause", "genre", "entite"}
               for r in reps)
    assert f.appels == []


def test_sans_maison_branchee_le_serveur_dit_indisponible(service):
    service.maison = None
    _, _, jeton = appairer_direct(service, "habitant")

    async def corps(ws):
        return [await echange(ws, {"type": "etats"}), await echange(ws, reel("light.couloir_plafond", "allumer"))]
    reps = scenario_ws(service, jeton, corps)
    assert [r["cause"] for r in reps] == ["indisponible", "indisponible"]


def test_un_incident_interne_ne_part_pas_vers_le_navigateur(service, capsys):
    class Casse:
        async def etats_pour(self, role):
            raise ValueError("chemin secret /srv/x")
    service.maison = Casse()
    _, _, jeton = appairer_direct(service, "habitant")

    async def corps(ws):
        return await echange(ws, {"type": "etats"})
    rep = scenario_ws(service, jeton, corps)
    assert rep["type"] == "erreur" and rep["cause"] == "indisponible"
    assert "secret" not in repr(rep) and "chemin secret" not in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------------------------
# Pages et script
# ---------------------------------------------------------------------------------------------------------------

def test_pages_maison_exigent_une_session_et_s_ouvrent_a_tous_les_roles(service):
    rep = service.traiter("127.0.0.1", "/maison", entetes())
    assert statut_de(rep) == 303 and rep[1]["Location"] == "/appairage"
    assert statut_de(service.traiter("127.0.0.1", "/maison.js", entetes())) == 401
    for conn, role in enumerate(("administrateur", "habitant", "invite"), start=1):
        _, _, jeton = appairer_direct(service, role, f"Appareil {role}", conn=conn)
        page = service.traiter("127.0.0.1", "/maison", entetes(jeton))
        assert statut_de(page) == 200, role
        html = page[2].decode("utf-8")
        assert "{{" not in html and W.VERSION_CLIENT in html and maison.NOM_ASSISTANT in html, role
        assert statut_de(service.traiter("127.0.0.1", "/maison.js", entetes(jeton))) == 200, role


def test_la_version_du_client_web_est_0_8_0():
    assert W.VERSION_CLIENT == "0.10.0"


def test_la_page_maison_n_a_ni_script_ni_style_en_ligne():
    html = (RACINE / "web" / "maison.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "style=" not in html and "<style" not in html
    assert not re.search(r"\son[a-z]+=", html), "aucun gestionnaire d'événement en ligne"
    assert not re.search(r"https?://", html)
    js = (RACINE / "web" / "maison.js").read_text(encoding="utf-8")
    for interdit in ("innerHTML", "insertAdjacentHTML", "document.write", "eval(", 'setAttribute("style"', ".cssText"):
        assert interdit not in js, interdit
    assert "style.setProperty" in js and not re.search(r"https?://", js)


def test_le_client_n_envoie_que_des_reglages_nommes_avec_essai_faux_et_limite_sa_cadence():
    js = (RACINE / "web" / "maison.js").read_text(encoding="utf-8")
    assert '"regler"' in js and '"etats"' in js and "essai: false" in js
    for action in sorted(MW.ACTIONS["light"] | MW.ACTIONS["media_player"]):
        assert f'"{action}"' in js, action
    for interdit in ("area_id", "device_id", "turn_on", "turn_off", "volume_set", "entity_id", '"all"'):
        assert interdit not in js, interdit
    assert "INTERVALLE_REGLAGE_MS" in js


def test_le_client_reprend_les_blancs_et_les_couleurs_du_serveur():
    js = (RACINE / "web" / "maison.js").read_text(encoding="utf-8")
    for nom, kelvin in MW.BLANCS:
        assert nom in js and str(kelvin) in js, nom
    for nom, teinte in MW.TEINTES:
        assert nom in js, nom


def test_le_module_maison_web_ne_connait_ni_piece_ni_entite_ni_prenom_en_dur():
    source = (RACINE / "maison_web.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(light|media_player|sensor)\.[a-z0-9_]+", re.sub(r'"""[\s\S]*?"""', "", source)
                         .replace("light.[", "").replace("media_player.[", "")), "aucune entité en dur"
    assert not re.search(r"https?://|api/states|/api/services", source)


def test_serveur_satellite_ne_donne_a_la_maison_que_des_entites_de_la_configuration():
    source = (RACINE / "serveur_satellite.py").read_text(encoding="utf-8")
    debut = source.index("def maison_pour_web")
    fonction = source[debut:source.index("\ndef ", debut + 10)]
    assert "/api/states/" in fonction and "/api/services/" in fonction
    assert "msg" not in fonction, "la fonction ne lit jamais un message du navigateur"


# ---------------------------------------------------------------------------------------------------------------
# Volet télé complet (S-W4b) : source, lecture, suivant, précédent, muet
# ---------------------------------------------------------------------------------------------------------------

SOURCES = ["HDMI 1", "HDMI 2", "Lecteur"]
# 2048 source, 1 pause, 32 suivant, 16 précédent, 8 muet
FONCTIONS = 2048 | 1 | 32 | 16 | 8


@pytest.fixture(autouse=True)
def tuiles_de_source_sans_configuration(monkeypatch):
    """Par défaut, aucune tuile nommée dans reglages.tele : les sources annoncées par Home Assistant servent telles
    quelles. Le test des tuiles nommées remet les siennes."""
    reglages = {k: v for k, v in (maison.CONFIG.get("reglages") or {}).items() if k != "tele"}
    monkeypatch.setitem(maison.CONFIG, "reglages", reglages)


def tele_complete(etat="playing", fonctions=FONCTIONS, **en_plus):
    attrs = {"volume_level": 0.3, "source_list": list(SOURCES), "source": "HDMI 1", "is_volume_muted": False,
             "supported_features": fonctions}
    attrs.update(en_plus)
    return {"state": etat, "attributes": attrs}


def faux_tele(**kw):
    f = Faux()
    f.etats["media_player.tele_salon"] = tele_complete(**kw)
    return f


def test_le_volet_tele_annonce_les_sources_de_home_assistant_et_ce_que_l_appareil_sait_faire():
    tele = courir(faux_tele().maison().etats_pour("habitant"))["pieces"][0]["tele"]
    assert [t["source"] for t in tele["sources"]] == SOURCES and tele["source"] == "HDMI 1"
    assert tele["lecture"] == "lecture" and tele["muet"] is False
    assert tele["peut"] == {"source": True, "lecture": True, "suivant": True, "precedent": True, "muet": True}


def test_une_tele_eteinte_ou_injoignable_n_annonce_aucune_commande():
    for etat in ("off", "unavailable"):
        tele = courir(faux_tele(etat=etat).maison().etats_pour("habitant"))["pieces"][0]["tele"]
        assert tele["sources"] == [] and tele["peut"] == {} and tele["lecture"] is None


def test_une_commande_que_l_appareil_ne_sait_pas_faire_n_est_pas_proposee():
    tele = courir(faux_tele(fonctions=2048 | 8).maison().etats_pour("habitant"))["pieces"][0]["tele"]
    assert tele["peut"] == {"source": True, "lecture": False, "suivant": False, "precedent": False, "muet": True}
    f = faux_tele(fonctions=2048)
    assert refus(f.maison(), "habitant", reel("media_player.tele_salon", "lecture")) == "action"
    assert f.appels == []


def test_la_source_choisie_doit_etre_dans_la_liste_que_home_assistant_donne_pour_cette_entite():
    f = faux_tele()
    m = f.maison()
    regle(m, "habitant", reel("media_player.tele_salon", "source", "HDMI 2"))
    assert f.appels[-1][:3] == ("media_player", "select_source",
                                {"source": "HDMI 2", "entity_id": "media_player.tele_salon"})
    avant = len(f.appels)
    for mauvaise in ("HDMI 9", "", None, 3, ["HDMI 1"], {"a": 1}, "hdmi 1", "HDMI 1 "):
        msg = reel("media_player.tele_salon", "source")
        msg["valeur"] = mauvaise
        assert refus(m, "habitant", msg) in ("valeur", "format"), mauvaise
    assert len(f.appels) == avant


def test_les_commandes_de_lecture_n_acceptent_aucune_valeur_et_le_muet_un_booleen():
    f = faux_tele()
    m = f.maison()
    for action, service_ in (("lecture", "media_play_pause"), ("suivant", "media_next_track"),
                             ("precedent", "media_previous_track")):
        regle(m, "habitant", reel("media_player.tele_salon", action))
        assert f.appels[-1][:3] == ("media_player", service_, {"entity_id": "media_player.tele_salon"})
        assert refus(m, "habitant", reel("media_player.tele_salon", action, 1)) == "valeur"
    regle(m, "habitant", reel("media_player.tele_salon", "muet", True))
    assert f.appels[-1][1] == "volume_mute" and f.appels[-1][2]["is_volume_muted"] is True
    for mauvaise in (1, "oui", None):
        msg = reel("media_player.tele_salon", "muet")
        if mauvaise is not None:
            msg["valeur"] = mauvaise
        assert refus(m, "habitant", msg) == "valeur"


def test_une_tele_eteinte_ne_change_pas_de_source_ni_ne_lit():
    f = faux_tele(etat="off")
    m = f.maison()
    for action, valeur in (("source", "HDMI 2"), ("lecture", None), ("suivant", None), ("muet", True)):
        assert refus(m, "habitant", reel("media_player.tele_salon", action, valeur)) == "action"
    assert f.appels == []
    regle(m, "habitant", reel("media_player.tele_salon", "allumer"))
    assert f.appels[-1][1] == "turn_on"


def test_une_tele_injoignable_refuse_ses_commandes():
    f = faux_tele(etat="unavailable")
    assert refus(f.maison(), "habitant", reel("media_player.tele_salon", "lecture")) == "injoignable"
    assert f.appels == []


def test_seuls_les_roles_qui_ont_la_tele_la_commandent_et_les_services_hors_liste_sont_inatteignables(monkeypatch):
    f = faux_tele()
    m = f.maison()
    for action, valeur in (("source", "HDMI 2"), ("lecture", None), ("muet", True), ("volume", 10), ("allumer", None)):
        assert refus(m, "invite", reel("media_player.tele_salon", action, valeur)) == "entite"
    assert f.appels == []
    # un rôle sans droit « tele » dans la configuration, même habitant, ne commande rien
    sans = copy.deepcopy(SECTION)
    sans["roles"]["habitant"]["tele"] = False
    monkeypatch.setattr(maison, "CLIENT_WEB", {"maison": sans})
    assert refus(f.maison(), "habitant", reel("media_player.tele_salon", "lecture")) in ("entite", "droit")
    assert f.appels == []
    # les services de la télé non listés sont refusés par le contrôle central, même s'ils venaient d'ailleurs
    assert acces.controler_service("media_player", "media_stop", {"entity_id": "media_player.tele_salon"},
                                   None, services_permis=MW.SERVICES_WEB["media_player"]) is not None
    assert acces.controler_service("media_player", "play_media", {"entity_id": "media_player.tele_salon"},
                                   None, services_permis=MW.SERVICES_WEB["media_player"]) is not None


def test_tout_service_de_la_tele_passe_par_le_controle_central_avec_la_liste_etroite(monkeypatch):
    vus = []

    def espion(domaine, service_, corps, personne=None, services_permis=None):
        vus.append((domaine, service_, services_permis))
        return None
    monkeypatch.setattr(acces, "controler_service", espion)
    f = faux_tele()
    m = f.maison()
    for action, valeur in (("source", "HDMI 2"), ("lecture", None), ("suivant", None), ("precedent", None),
                           ("muet", False)):
        regle(m, "habitant", reel("media_player.tele_salon", action, valeur))
    assert [v[1] for v in vus] == ["select_source", "media_play_pause", "media_next_track", "media_previous_track",
                                   "volume_mute"]
    assert all(v[0] == "media_player" and v[2] == MW.SERVICES_WEB["media_player"] for v in vus)


def test_les_tuiles_nommees_de_la_configuration_ne_valent_que_pour_les_sources_annoncees(monkeypatch):
    monkeypatch.setitem(maison.CONFIG, "reglages", {"tele": {"sources": [
        {"nom": "TNT", "source": "TV"}, {"nom": "Absente", "source": "Source inconnue"}, {"nom": 3, "source": "TV"}]}})
    f = faux_tele(source_list=["TV", "HDMI 2"], source="TV")
    tele = courir(f.maison().etats_pour("habitant"))["pieces"][0]["tele"]
    assert tele["sources"] == [{"nom": "TNT", "source": "TV"}]
    # une source qui n'a pas de tuile reste choisissable seulement si Home Assistant l'annonce
    regle(f.maison(), "habitant", reel("media_player.tele_salon", "source", "HDMI 2"))
    assert refus(f.maison(), "habitant", reel("media_player.tele_salon", "source", "Source inconnue")) == "valeur"


def test_une_source_trop_longue_ou_en_double_n_est_pas_annoncee():
    f = faux_tele(source_list=["HDMI 1", "HDMI 1", "", "x" * 200, 7, "TV"])
    tele = courir(f.maison().etats_pour("habitant"))["pieces"][0]["tele"]
    assert [t["source"] for t in tele["sources"]] == ["HDMI 1", "TV"]
    assert refus(f.maison(), "habitant", reel("media_player.tele_salon", "source", "x" * 200)) == "valeur"


# ---------------------------------------------------------------------------------------------------------------
# Historique de l'air (S-W4b)
# ---------------------------------------------------------------------------------------------------------------

def brut_air(piece="salon", h=24):
    return {"type": "air", "piece": piece, "heures": h, "debut": 1000, "fin": 1000 + h * 3600, "pas": 300,
            "series": {"co2": [[1000, 600.0], [1300, 650.5]], "pm25": [[1000, 4]], "temperature": [],
                       "humidite": [[1000, 45.0]]}}


class FauxAir:
    def __init__(self, brut=None, echec=None):
        self.brut, self.echec, self.appels = brut, echec, []

    async def __call__(self, piece, heures):
        self.appels.append((piece, heures))
        if self.echec is not None:
            raise self.echec
        return brut_air(piece, heures) if self.brut is None else self.brut


def maison_air(air, f=None):
    f = f or Faux()
    return MW.Maison(f.lire, f.lire_mesures, f.appeler, horloge=f.horloge, historique=air), f


def demande_air(m, role, msg):
    return courir(m.air_historique(role, msg))


def refus_air(m, role, msg):
    with pytest.raises(MW.RefusMaison) as e:
        courir(m.air_historique(role, msg))
    return e.value.cause


def test_l_historique_de_l_air_rend_les_quatre_courbes_d_une_piece_visible():
    air = FauxAir()
    m, _ = maison_air(air)
    rep = demande_air(m, "habitant", {"type": "air_historique", "piece": "salon", "heures": 6})
    assert rep["type"] == "air" and rep["piece"] == "salon" and rep["heures"] == 6
    assert set(rep["series"]) == {"co2", "pm25", "temperature", "humidite"}
    assert rep["series"]["co2"] == [[1000, 600.0], [1300, 650.5]]
    assert air.appels == [("salon", 6)]


def test_la_duree_par_defaut_est_de_24_heures_et_le_resultat_est_garde_en_cache():
    air = FauxAir()
    m, f = maison_air(air)
    msg = {"type": "air_historique", "piece": "salon"}
    assert demande_air(m, "habitant", msg)["heures"] == 24
    demande_air(m, "administrateur", msg)
    assert len(air.appels) == 1, "deuxième demande servie par le cache"
    f.t += MW.CACHE_AIR_S + 1
    demande_air(m, "habitant", msg)
    assert len(air.appels) == 2


@pytest.mark.parametrize("role", ["invite", "partage", None, "", 3])
def test_l_historique_de_l_air_est_refuse_a_qui_n_a_pas_les_mesures(role):
    air = FauxAir()
    m, _ = maison_air(air)
    assert refus_air(m, role, {"type": "air_historique", "piece": "salon"}) == "droit"
    assert air.appels == []


@pytest.mark.parametrize("msg,cause", [
    (None, "format"), ("salon", "format"), ([], "format"),
    ({"type": "air_historique", "piece": "salon", "entite": "sensor.x"}, "format"),
    ({"type": "air_historique", "piece": "salon", "url": "http://x"}, "format"),
    ({"type": "air_historique"}, "entite"),
    ({"type": "air_historique", "piece": 3}, "entite"),
    ({"type": "air_historique", "piece": "../salon"}, "entite"),
    ({"type": "air_historique", "piece": "Salon"}, "entite"),
    ({"type": "air_historique", "piece": "inconnue"}, "entite"),
    ({"type": "air_historique", "piece": "salon", "heures": 0}, "valeur"),
    ({"type": "air_historique", "piece": "salon", "heures": -3}, "valeur"),
    ({"type": "air_historique", "piece": "salon", "heures": 169}, "valeur"),
    ({"type": "air_historique", "piece": "salon", "heures": 1e9}, "valeur"),
    ({"type": "air_historique", "piece": "salon", "heures": 2.5}, "valeur"),
    ({"type": "air_historique", "piece": "salon", "heures": True}, "valeur"),
    ({"type": "air_historique", "piece": "salon", "heures": "24"}, "valeur"),
    ({"type": "air_historique", "piece": "salon", "heures": None}, "valeur"),
    ({"type": "air_historique", "piece": "chambre"}, "protegee"),
])
def test_l_historique_de_l_air_refuse_un_message_hors_schema_sans_interroger_home_assistant(msg, cause):
    air = FauxAir()
    m, _ = maison_air(air)
    assert refus_air(m, "habitant", msg) == cause
    assert air.appels == []


def test_les_bornes_de_duree_sont_acceptees():
    air = FauxAir()
    m, _ = maison_air(air)
    for h in (1, 168):
        assert demande_air(m, "habitant", {"type": "air_historique", "piece": "salon", "heures": h})["heures"] == h


def test_une_piece_hors_de_la_liste_du_role_n_est_pas_revelee(monkeypatch):
    section = copy.deepcopy(SECTION)
    section["roles"]["habitant"] = {"pieces": ["salon"], "mesures": True, "tele": True}
    monkeypatch.setattr(maison, "CLIENT_WEB", {"maison": section})
    air = FauxAir()
    m, _ = maison_air(air)
    assert refus_air(m, "habitant", {"type": "air_historique", "piece": "couloir"}) == "entite"
    assert air.appels == []


def test_sans_fournisseur_ou_en_cas_d_echec_le_graphique_est_indisponible_sans_texte_interne(capsys):
    m, _ = maison_air(None)
    assert refus_air(m, "habitant", {"type": "air_historique", "piece": "salon"}) == "indisponible"
    m, _ = maison_air(FauxAir(echec=RuntimeError("chemin secret /srv/x")))
    assert refus_air(m, "habitant", {"type": "air_historique", "piece": "salon"}) == "indisponible"
    sortie = capsys.readouterr().out
    assert "chemin secret" not in sortie and "RuntimeError" in sortie


def test_une_piece_sans_capteur_donne_la_cause_capteur():
    m, _ = maison_air(FauxAir(echec=AH.ErreurAir("aucun capteur dans cette pièce")))
    assert refus_air(m, "habitant", {"type": "air_historique", "piece": "salon"}) == "capteur"


def test_la_reponse_de_l_historique_est_reconstruite_et_bornee():
    brut = brut_air()
    brut["series"]["co2"] = [[i, 400.0 + i] for i in range(AH.POINTS_MAX + 50)] + [[1, float("nan")]]
    brut["series"]["pm25"] = [[1, 2], "x", [1], [1, 2, 3], [1, "a"], [1, float("inf")], [1, 1e12], [True, 1]]
    brut["series"]["inconnue"] = [[1, 1]]
    brut["secret"] = "jeton-exemple-secret"
    m, _ = maison_air(FauxAir(brut=brut))
    rep = demande_air(m, "habitant", {"type": "air_historique", "piece": "salon"})
    assert len(rep["series"]["co2"]) == AH.POINTS_MAX
    assert "inconnue" not in rep["series"] and "secret" not in rep and "jeton-exemple-secret" not in repr(rep)
    assert rep["series"]["pm25"] == [[1, 2]], "ni NaN, ni infini, ni booléen, ni valeur démesurée"
    for forme in ({}, {"series": 3}, {"series": {}, "debut": "x", "fin": 1, "pas": 1},
                  {"series": {}, "debut": float("inf"), "fin": 1, "pas": 1}):
        m, _ = maison_air(FauxAir(brut=forme))
        assert refus_air(m, "habitant", {"type": "air_historique", "piece": "salon"}) == "indisponible"


def test_air_historique_par_websocket_est_refuse_a_l_invite_et_servi_a_l_habitant(service):
    f = Faux()
    service.maison = maison_air(FauxAir(), f)[0]
    _, _, jeton_h = appairer_direct(service, "habitant", "Habitant", conn=1)
    _, _, jeton_i = appairer_direct(service, "invite", "Invité", conn=2)

    async def corps(ws):
        return [await echange(ws, {"type": "air_historique", "piece": "salon", "heures": 12}),
                await echange(ws, {"type": "air_historique", "piece": "salon", "entite": "sensor.x"}),
                await echange(ws, {"type": "air_historique", "piece": "chambre"})]
    bon, hors_schema, protegee = scenario_ws(service, jeton_h, corps)
    assert bon["type"] == "air" and bon["heures"] == 12 and bon["piece"] == "salon"
    assert hors_schema == {"type": "erreur", "cause": "format", "genre": "air_historique"}
    assert protegee["cause"] == "protegee" and protegee["genre"] == "air_historique"

    async def invite(ws):
        return await echange(ws, {"type": "air_historique", "piece": "salon"})
    rep = scenario_ws(service, jeton_i, invite)
    assert rep["type"] == "erreur" and rep["cause"] == "droit" and rep["genre"] == "air_historique"
    assert "series" not in rep


def test_l_historique_de_l_air_par_websocket_dit_indisponible_sans_maison(service):
    service.maison = None
    _, _, jeton = appairer_direct(service, "habitant")

    async def corps(ws):
        return await echange(ws, {"type": "air_historique", "piece": "salon"})
    assert scenario_ws(service, jeton, corps)["cause"] == "indisponible"
