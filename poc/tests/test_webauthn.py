import os

import pytest

import webauthn as WA
from aide_webauthn import Authentificateur, cbor, client_data

RP = "assistant.exemple.ts.net"
ORIGINE = f"https://{RP}"
ORIGINES = {ORIGINE}


@pytest.fixture
def tel():
    return Authentificateur(RP)


def cause(fonction, *args, **kw):
    with pytest.raises(WA.ErreurWebAuthn) as e:
        fonction(*args, **kw)
    return e.value.cause


def creation(tel, challenge=None, **kw):
    challenge = challenge or os.urandom(32)
    rep = tel.creer(challenge, ORIGINE, **kw)
    return challenge, rep


def verifier_creation(rep, challenge, origines=ORIGINES, rp=RP):
    return WA.verifier_creation(WA.deb64u(rep["clientDataJSON"], 2000), WA.deb64u(rep["attestationObject"], 5000),
                                challenge, origines, rp)


def verifier_assertion(rep, challenge, cle, compteur, origines=ORIGINES, rp=RP):
    return WA.verifier_assertion(WA.deb64u(rep["clientDataJSON"], 2000), WA.deb64u(rep["authenticatorData"], 3000),
                                 WA.deb64u(rep["signature"], 300), challenge, origines, rp, cle, compteur)


# CBOR

def test_cbor_aller_retour_des_types_utiles():
    valeur = {"a": [1, -7, 500, 70000, True, False, None], 3: b"\x00\x01", -2: "été"}
    assert WA.cbor_lire(cbor(valeur)) == valeur


@pytest.mark.parametrize("brut", [
    b"\xc1\x01",                      # étiquette
    b"\xf9\x3c\x00",                  # flottant
    b"\x5f\x41a\xff",                 # octets de longueur indéfinie
    b"\x9f\x01\xff",                  # liste de longueur indéfinie
    b"\x1c",                          # argument réservé
    b"\x18",                          # tronqué
    b"\x62\xff\xfe",                  # utf-8 invalide
    b"\xa2\x01\x01\x01\x02",          # clé en double
    b"\xa1\x80\x01",                  # clé de table qui est une liste
    b"\x01\x02",                      # octets en trop
    b"",                              # vide
])
def test_cbor_malforme_refuse(brut):
    assert cause(WA.cbor_lire, brut) == "format"


def test_cbor_borne_la_profondeur_et_le_nombre_d_elements():
    profond = b"\x81" * 20 + b"\x01"
    assert cause(WA.cbor_lire, profond) == "format"
    large = cbor(list(range(200)))
    assert cause(WA.cbor_lire, large) == "format"
    bombe = b"\x9b" + (2 ** 40).to_bytes(8, "big")  # annonce 2^40 éléments sans les fournir
    assert cause(WA.cbor_lire, bombe) == "format"


def test_base64url_strict():
    assert WA.deb64u(WA.b64u(b"abc\xff"), 10) == b"abc\xff"
    for mauvais in ("a+b/", "ab=", "abcde", 12, None):
        assert cause(WA.deb64u, mauvais, 10) == "format"
    assert cause(WA.deb64u, WA.b64u(b"x" * 50), 10) == "format"


# Création

def test_creation_valide_renvoie_identifiant_cle_et_compteur(tel):
    challenge, rep = creation(tel)
    res = verifier_creation(rep, challenge)
    assert res["id"] == WA.b64u(tel.id) and res["compteur"] == 0
    assert WA.deb64u(res["cle"], 300)[:2] == b"\x30\x59"  # SPKI DER d'une clé P-256


def test_creation_challenge_mauvais(tel):
    _, rep = creation(tel)
    assert cause(verifier_creation, rep, os.urandom(32)) == "challenge"


def test_creation_origine_et_type_et_rp(tel):
    challenge, rep = creation(tel)
    assert cause(verifier_creation, rep, challenge, origines={"https://pirate.example"}) == "origine"
    challenge, rep = creation(tel, type_="webauthn.get")
    assert cause(verifier_creation, rep, challenge) == "type"
    challenge, rep = creation(tel, rp_id="pirate.example")
    assert cause(verifier_creation, rep, challenge) == "rp"


def test_creation_sans_presence_ou_sans_verification_utilisateur(tel):
    challenge, rep = creation(tel, drapeaux=WA.DRAPEAU_UV | WA.DRAPEAU_AT)
    assert cause(verifier_creation, rep, challenge) == "presence"
    challenge, rep = creation(tel, drapeaux=WA.DRAPEAU_UP | WA.DRAPEAU_AT)
    assert cause(verifier_creation, rep, challenge) == "verification"


def test_creation_attestation_autre_que_none_refusee(tel):
    challenge, rep = creation(tel, fmt="packed")
    assert cause(verifier_creation, rep, challenge) == "attestation"
    challenge, rep = creation(tel, att_stmt={"alg": -7, "sig": b"x"})
    assert cause(verifier_creation, rep, challenge) == "attestation"


def test_creation_sans_cle_ou_cle_hors_norme(tel):
    challenge, rep = creation(tel, drapeaux=WA.DRAPEAU_UP | WA.DRAPEAU_UV)
    assert cause(verifier_creation, rep, challenge) == "format"
    base = tel.cle_cose()
    for cle in ({**base, WA.COSE_ALG: -257}, {**base, WA.COSE_CRV: 2}, {**base, WA.COSE_X: b"\x01" * 31},
                {**base, WA.COSE_X: b"\x01" * 32, WA.COSE_Y: b"\x02" * 32}):
        challenge, rep = creation(tel, cle_cose=cle)
        assert cause(verifier_creation, rep, challenge) in ("algorithme", "cle")


def test_creation_donnees_client_malformees(tel):
    challenge = os.urandom(32)
    rep = tel.creer(challenge, ORIGINE)
    for brut in (b"pas du json", b"[1]", b"", b"{" + b"x" * 2000):
        assert cause(WA.verifier_creation, brut, WA.deb64u(rep["attestationObject"], 5000), challenge, ORIGINES, RP) == "format"
    avec_cross = client_data("webauthn.create", challenge, ORIGINE, crossOrigin=True)
    assert cause(WA.verifier_creation, avec_cross, WA.deb64u(rep["attestationObject"], 5000), challenge, ORIGINES, RP) == "origine"


# Assertion

def preparer(tel):
    challenge, rep = creation(tel)
    return verifier_creation(rep, challenge)


def test_assertion_valide_et_compteur_croissant(tel):
    cle = preparer(tel)["cle"]
    c1 = os.urandom(32)
    assert verifier_assertion(tel.signer(c1, ORIGINE), c1, cle, 0) == 1
    c2 = os.urandom(32)
    assert verifier_assertion(tel.signer(c2, ORIGINE), c2, cle, 1) == 2


def test_assertion_passkey_synchronisee_compteur_toujours_zero(tel):
    cle = preparer(tel)["cle"]
    c = os.urandom(32)
    assert verifier_assertion(tel.signer(c, ORIGINE, compteur=0), c, cle, 0) == 0
    # mais un compteur à zéro après un compteur positif est un recul
    assert cause(verifier_assertion, tel.signer(c, ORIGINE, compteur=0), c, cle, 5) == "compteur"


def test_assertion_compteur_qui_recule_ou_stagne(tel):
    cle = preparer(tel)["cle"]
    c = os.urandom(32)
    assert cause(verifier_assertion, tel.signer(c, ORIGINE, compteur=4), c, cle, 9) == "compteur"
    assert cause(verifier_assertion, tel.signer(c, ORIGINE, compteur=9), c, cle, 9) == "compteur"


def test_assertion_refus_challenge_origine_type_rp(tel):
    cle = preparer(tel)["cle"]
    c = os.urandom(32)
    assert cause(verifier_assertion, tel.signer(os.urandom(32), ORIGINE), c, cle, 0) == "challenge"
    assert cause(verifier_assertion, tel.signer(c, "https://pirate.example"), c, cle, 0) == "origine"
    assert cause(verifier_assertion, tel.signer(c, ORIGINE, type_="webauthn.create"), c, cle, 0) == "type"
    assert cause(verifier_assertion, tel.signer(c, ORIGINE, rp_id="pirate.example"), c, cle, 0) == "rp"


def test_assertion_sans_presence_ni_verification(tel):
    cle = preparer(tel)["cle"]
    c = os.urandom(32)
    assert cause(verifier_assertion, tel.signer(c, ORIGINE, drapeaux=WA.DRAPEAU_UV), c, cle, 0) == "presence"
    assert cause(verifier_assertion, tel.signer(c, ORIGINE, drapeaux=WA.DRAPEAU_UP), c, cle, 0) == "verification"


def test_assertion_signature_d_une_autre_cle_ou_alteree(tel):
    cle = preparer(tel)["cle"]
    autre = Authentificateur(RP)
    c = os.urandom(32)
    assert cause(verifier_assertion, autre.signer(c, ORIGINE), c, cle, 0) == "signature"
    rep = tel.signer(c, ORIGINE)
    sig = bytearray(WA.deb64u(rep["signature"], 300))
    sig[-1] ^= 1
    rep["signature"] = WA.b64u(bytes(sig))
    assert cause(verifier_assertion, rep, c, cle, 0) == "signature"


def test_assertion_clientdata_modifie_apres_signature(tel):
    cle = preparer(tel)["cle"]
    c = os.urandom(32)
    rep = tel.signer(c, ORIGINE)
    rep["clientDataJSON"] = WA.b64u(client_data("webauthn.get", c, ORIGINE, extra="x"))
    assert cause(verifier_assertion, rep, c, cle, 0) == "signature"


def test_assertion_cle_stockee_illisible(tel):
    preparer(tel)
    c = os.urandom(32)
    assert cause(verifier_assertion, tel.signer(c, ORIGINE), c, "AAAA", 0) == "cle"


def test_options_pour_le_navigateur():
    o = WA.options_creation(RP, "Iris", b"\x01" * 16, "Téléphone", b"\x02" * 32, ["abc"])
    assert o["authenticatorSelection"]["userVerification"] == "required" and o["attestation"] == "none"
    assert o["pubKeyCredParams"] == [{"type": "public-key", "alg": -7}] and o["rp"]["id"] == RP
    a = WA.options_assertion(RP, b"\x03" * 32, ["abc"])
    assert a["userVerification"] == "required" and a["allowCredentials"][0]["id"] == "abc"
