"""0.31.0 : lire_etat expose le mode de couleur et les kelvins d'une lampe."""
import assistant as A


def test_lampe_en_blanc():
    r = A.attributs_lus({"friendly_name": "Suspension", "brightness": 200, "color_mode": "color_temp",
                         "color_temp_kelvin": 2700, "hs_color": [30.1, 60.0], "rgb_color": [255, 190, 120],
                         "min_color_temp_kelvin": 2202, "max_color_temp_kelvin": 6535, "effect_list": ["a"]})
    assert r["color_mode"] == "color_temp" and r["color_temp_kelvin"] == 2700
    assert r["min_color_temp_kelvin"] == 2202 and r["max_color_temp_kelvin"] == 6535
    assert "effect_list" not in r


def test_lampe_en_couleur_et_eteinte():
    assert A.attributs_lus({"color_mode": "hs", "hs_color": [220, 100], "color_temp_kelvin": None})["hs_color"] == [220, 100]
    r = A.attributs_lus({"color_mode": None, "color_temp_kelvin": None, "min_color_temp_kelvin": 2202})
    assert "color_mode" not in r and "color_temp_kelvin" not in r and r["min_color_temp_kelvin"] == 2202


def test_attributs_historiques_inchanges():
    assert A.attributs_lus({"volume_level": 0.3, "media_title": "T", "secret": 1}) == {"volume_level": 0.3, "media_title": "T"}
