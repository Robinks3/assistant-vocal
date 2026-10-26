"""Amorçage de l'appairage : code à usage unique écrit dans le journal quand aucun administrateur n'est connecté."""
import acces


def test_code_a_huit_chiffres_stable_pendant_sa_duree():
    a = acces.Amorcage()
    code, nouveau = a.ouvrir(maintenant=1000)
    assert nouveau and len(code) == 8 and code.isdigit()
    assert a.ouvrir(maintenant=1100) == (code, False)


def test_usage_unique():
    a = acces.Amorcage()
    code, _ = a.ouvrir(maintenant=1000)
    assert a.verifier(code, maintenant=1001) == (True, 0)
    assert a.verifier(code, maintenant=1002)[0] is False


def test_expiration():
    a = acces.Amorcage()
    code, _ = a.ouvrir(maintenant=1000)
    assert a.verifier(code, maintenant=1000 + acces.Amorcage.DUREE + 1)[0] is False


def test_cinq_erreurs_detruisent_le_code():
    a = acces.Amorcage()
    code, _ = a.ouvrir(maintenant=1000)
    faux = "0" * 8 if code != "0" * 8 else "1" * 8
    restants = [a.verifier(faux, maintenant=1001)[1] for _ in range(acces.Amorcage.ESSAIS)]
    assert restants == [4, 3, 2, 1, 0]
    assert a.verifier(code, maintenant=1002)[0] is False


def test_nouveau_code_pas_plus_d_un_par_minute():
    a = acces.Amorcage()
    code, _ = a.ouvrir(maintenant=1000)
    a.verifier(code, maintenant=1001)
    assert a.ouvrir(maintenant=1002) == (None, False)
    assert a.ouvrir(maintenant=1000 + acces.Amorcage.PAUSE + 1)[1] is True


def test_saisie_tolerante_aux_espaces_mais_pas_aux_codes_courts():
    a = acces.Amorcage()
    code, _ = a.ouvrir(maintenant=1000)
    assert a.verifier(code[:4], maintenant=1001)[0] is False
    assert a.verifier(f"{code[:4]} {code[4:]}", maintenant=1002)[0] is True


def test_reseau_local_exclut_le_tailnet_et_le_public():
    assert acces.adresse_locale("192.168.0.20")
    assert acces.adresse_locale("127.0.0.1")
    assert not acces.adresse_locale("100.64.0.10")
    assert not acces.adresse_locale("fd7a:115c:a1e0::5")
    assert acces.adresse_locale("fd12:3456::1")
    assert not acces.adresse_locale("8.8.8.8")
    assert not acces.adresse_locale("pas une adresse")


def test_refus_gardes_pour_le_diagnostic(tmp_path):
    app = acces.Appareils(tmp_path, {})
    for i in range(25):
        app.noter_refus("jeton invalide", f"192.168.0.{i}")
    assert len(app.refus) == 20
    assert app.vue(avec_code=True)["refus"][-1]["ip"] == f"192.168.0.{i}"
    assert app.vue()["refus"] == []
