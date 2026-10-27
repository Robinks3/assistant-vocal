"""WebAuthn côté serveur : décodage CBOR borné, lecture des données d'authentification, vérification d'une
création de clé (attestation « none ») et d'une signature (assertion ES256).

Module pur : aucune entrée-sortie, aucun état. Les défis, les appareils et les compteurs vivent dans
appairage_web.py. Seule dépendance : cryptography (ES256, courbe P-256).

Ce qui est accepté, et rien d'autre :
- clé ES256 (COSE kty 2, alg -7, crv 1) ;
- attestation « none » avec une déclaration vide ;
- présence (UP) et vérification de l'utilisateur (UV) obligatoires, au rejeu comme à la création ;
- origine égale à l'une des origines permises, identifiant de partie (rpId) vérifié par son empreinte.
"""
import base64
import hashlib
import hmac
import json
import re
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

# Tailles maximales acceptées (octets). Une clé réelle tient dans quelques centaines d'octets.
MAX_CLIENT_DATA = 1024
MAX_ATTESTATION = 4096
MAX_AUTH_DATA = 2048
MAX_SIGNATURE = 256
MAX_ID = 1023
# Limites du décodeur CBOR : profondeur, nombre total d'éléments, longueur d'une chaîne ou d'un octet.
CBOR_PROFONDEUR = 6
CBOR_ELEMENTS = 128

DRAPEAU_UP = 0x01
DRAPEAU_UV = 0x04
DRAPEAU_AT = 0x40
DRAPEAU_ED = 0x80

COSE_KTY, COSE_ALG, COSE_CRV, COSE_X, COSE_Y = 1, 3, -1, -2, -3
KTY_EC2, ALG_ES256, CRV_P256 = 2, -7, 1

# Causes de refus, liste fermée : elles servent au journal et aux tests, jamais au client.
CAUSES = frozenset({
    "format", "type", "challenge", "origine", "rp", "presence", "verification", "algorithme", "attestation",
    "cle", "signature", "compteur", "identifiant",
})


class ErreurWebAuthn(Exception):
    def __init__(self, cause, detail=""):
        assert cause in CAUSES, cause
        super().__init__(f"{cause} {detail}".strip())
        self.cause = cause


# --- base64url ---------------------------------------------------------------------------------------------

_B64U = re.compile(r"^[A-Za-z0-9_-]*$")


def b64u(octets):
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def deb64u(texte, maxi):
    """Décode du base64url strict (sans remplissage), borné en taille. ErreurWebAuthn « format » sinon."""
    if not isinstance(texte, str) or len(texte) > (maxi * 4) // 3 + 4 or not _B64U.match(texte) or len(texte) % 4 == 1:
        raise ErreurWebAuthn("format", "base64url")
    brut = base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))
    if len(brut) > maxi:
        raise ErreurWebAuthn("format", "taille")
    return brut


# --- CBOR borné ---------------------------------------------------------------------------------------------

class _Lecteur:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.elements = 0

    def prendre(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ErreurWebAuthn("format", "cbor tronqué")
        morceau = self.data[self.pos:self.pos + n]
        self.pos += n
        return morceau

    def argument(self, info):
        if info < 24:
            return info
        taille = {24: 1, 25: 2, 26: 4, 27: 8}.get(info)
        if taille is None:  # 28 à 30 réservés, 31 = longueur indéfinie : refusés
            raise ErreurWebAuthn("format", "cbor longueur")
        return int.from_bytes(self.prendre(taille), "big")

    def valeur(self, profondeur=0):
        if profondeur > CBOR_PROFONDEUR:
            raise ErreurWebAuthn("format", "cbor profondeur")
        self.elements += 1
        if self.elements > CBOR_ELEMENTS:
            raise ErreurWebAuthn("format", "cbor trop d'éléments")
        octet = self.prendre(1)[0]
        majeur, info = octet >> 5, octet & 0x1F
        if majeur == 7:
            if info == 20:
                return False
            if info == 21:
                return True
            if info == 22:
                return None
            raise ErreurWebAuthn("format", "cbor simple")  # flottants, undefined, break : non utilisés
        if majeur == 6:
            raise ErreurWebAuthn("format", "cbor étiquette")
        n = self.argument(info)
        if majeur == 0:
            return n
        if majeur == 1:
            return -1 - n
        if majeur in (2, 3):
            if n > MAX_ATTESTATION:
                raise ErreurWebAuthn("format", "cbor chaîne trop longue")
            brut = self.prendre(n)
            if majeur == 2:
                return bytes(brut)
            try:
                return bytes(brut).decode("utf-8")
            except UnicodeDecodeError:
                raise ErreurWebAuthn("format", "cbor utf-8") from None
        if n > CBOR_ELEMENTS:
            raise ErreurWebAuthn("format", "cbor trop d'éléments")
        if majeur == 4:
            return [self.valeur(profondeur + 1) for _ in range(n)]
        resultat = {}
        for _ in range(n):
            cle = self.valeur(profondeur + 1)
            if not isinstance(cle, (int, str)) or isinstance(cle, bool):
                raise ErreurWebAuthn("format", "cbor clé de table")
            if cle in resultat:
                raise ErreurWebAuthn("format", "cbor clé en double")
            resultat[cle] = self.valeur(profondeur + 1)
        return resultat


def cbor_lire(data):
    """Décode UN élément CBOR et exige que toute la donnée soit consommée."""
    valeur, reste = cbor_lire_prefixe(data)
    if reste:
        raise ErreurWebAuthn("format", "cbor octets en trop")
    return valeur


def cbor_lire_prefixe(data):
    """Décode le premier élément et renvoie (valeur, octets restants)."""
    if not isinstance(data, (bytes, bytearray)):
        raise ErreurWebAuthn("format", "cbor type")
    lecteur = _Lecteur(bytes(data))
    valeur = lecteur.valeur()
    return valeur, lecteur.data[lecteur.pos:]


# --- Données d'authentification -----------------------------------------------------------------------------

def lire_auth_data(auth_data, avec_cle=False):
    """Découpe les authData. Renvoie un dict : rp_hash, drapeaux, compteur et, si AT, id et cle (table COSE)."""
    if len(auth_data) < 37 or len(auth_data) > MAX_AUTH_DATA:
        raise ErreurWebAuthn("format", "authData")
    rp_hash, drapeaux = auth_data[:32], auth_data[32]
    compteur = struct.unpack(">I", auth_data[33:37])[0]
    sortie = {"rp_hash": rp_hash, "drapeaux": drapeaux, "compteur": compteur, "id": None, "cle": None}
    reste = auth_data[37:]
    if drapeaux & DRAPEAU_AT:
        if len(reste) < 18:
            raise ErreurWebAuthn("format", "authData identifiant")
        taille_id = struct.unpack(">H", reste[16:18])[0]
        if not 0 < taille_id <= MAX_ID or len(reste) < 18 + taille_id:
            raise ErreurWebAuthn("format", "authData identifiant")
        sortie["id"] = reste[18:18 + taille_id]
        cle, reste = cbor_lire_prefixe(reste[18 + taille_id:])
        if not isinstance(cle, dict):
            raise ErreurWebAuthn("cle", "pas une table COSE")
        sortie["cle"] = cle
    elif avec_cle:
        raise ErreurWebAuthn("format", "pas de clé")
    if drapeaux & DRAPEAU_ED:
        _, reste = cbor_lire_prefixe(reste)
    if reste:
        raise ErreurWebAuthn("format", "authData octets en trop")
    return sortie


def cle_publique_spki(cle_cose):
    """Clé COSE EC2 P-256/ES256 vers la clé publique (DER SubjectPublicKeyInfo). Vérifie que le point est sur la courbe."""
    if cle_cose.get(COSE_KTY) != KTY_EC2 or cle_cose.get(COSE_CRV) != CRV_P256:
        raise ErreurWebAuthn("algorithme", "courbe")
    if cle_cose.get(COSE_ALG) != ALG_ES256:
        raise ErreurWebAuthn("algorithme", "alg")
    x, y = cle_cose.get(COSE_X), cle_cose.get(COSE_Y)
    if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
        raise ErreurWebAuthn("cle", "coordonnées")
    try:
        cle = ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()).public_key()
    except ValueError:
        raise ErreurWebAuthn("cle", "point hors courbe") from None
    return cle.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


# --- Vérifications -------------------------------------------------------------------------------------------

def _client_data(brut, type_attendu, challenge, origines):
    if not isinstance(brut, (bytes, bytearray)) or not 2 <= len(brut) <= MAX_CLIENT_DATA:
        raise ErreurWebAuthn("format", "clientDataJSON")
    try:
        donnees = json.loads(bytes(brut).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ErreurWebAuthn("format", "clientDataJSON json") from None
    if not isinstance(donnees, dict):
        raise ErreurWebAuthn("format", "clientDataJSON objet")
    if donnees.get("type") != type_attendu:
        raise ErreurWebAuthn("type")
    recu = donnees.get("challenge")
    try:
        recu_octets = deb64u(recu, 64)
    except ErreurWebAuthn:
        raise ErreurWebAuthn("challenge", "format") from None
    if not hmac.compare_digest(recu_octets, challenge):
        raise ErreurWebAuthn("challenge")
    origine = donnees.get("origin")
    if not isinstance(origine, str) or origine not in origines:
        raise ErreurWebAuthn("origine")
    if donnees.get("crossOrigin") not in (None, False):
        raise ErreurWebAuthn("origine", "crossOrigin")
    return donnees


def _drapeaux_et_rp(auth, rp_id):
    attendu = hashlib.sha256(rp_id.encode("utf-8")).digest()
    if not hmac.compare_digest(auth["rp_hash"], attendu):
        raise ErreurWebAuthn("rp")
    if not auth["drapeaux"] & DRAPEAU_UP:
        raise ErreurWebAuthn("presence")
    if not auth["drapeaux"] & DRAPEAU_UV:
        raise ErreurWebAuthn("verification")


def verifier_creation(client_data_json, attestation_object, challenge, origines, rp_id):
    """Vérifie une création de clé. Renvoie {"id": b64url, "cle": b64url(SPKI DER), "compteur": int}."""
    _client_data(client_data_json, "webauthn.create", challenge, origines)
    if not isinstance(attestation_object, (bytes, bytearray)) or not 1 <= len(attestation_object) <= MAX_ATTESTATION:
        raise ErreurWebAuthn("format", "attestation taille")
    attestation = cbor_lire(bytes(attestation_object))
    if not isinstance(attestation, dict) or attestation.get("fmt") != "none" or attestation.get("attStmt") != {}:
        raise ErreurWebAuthn("attestation")
    auth_data = attestation.get("authData")
    if not isinstance(auth_data, bytes):
        raise ErreurWebAuthn("format", "authData absent")
    auth = lire_auth_data(auth_data)
    _drapeaux_et_rp(auth, rp_id)
    if auth["id"] is None or auth["cle"] is None:
        raise ErreurWebAuthn("format", "pas de clé créée")
    return {"id": b64u(auth["id"]), "cle": b64u(cle_publique_spki(auth["cle"])), "compteur": auth["compteur"]}


def verifier_assertion(client_data_json, auth_data, signature, challenge, origines, rp_id, cle_b64, compteur_stocke):
    """Vérifie une signature. Renvoie le nouveau compteur à stocker, sinon ErreurWebAuthn.

    Compteur : une passkey synchronisée renvoie toujours 0, accepté tant que le compteur stocké est 0. Sinon la
    valeur reçue doit être strictement supérieure à celle qui est stockée (un recul trahit une clé clonée)."""
    _client_data(client_data_json, "webauthn.get", challenge, origines)
    if not isinstance(auth_data, (bytes, bytearray)):
        raise ErreurWebAuthn("format", "authData")
    auth = lire_auth_data(bytes(auth_data))
    _drapeaux_et_rp(auth, rp_id)
    if not isinstance(signature, (bytes, bytearray)) or not 8 <= len(signature) <= MAX_SIGNATURE:
        raise ErreurWebAuthn("format", "signature")
    try:
        cle = serialization.load_der_public_key(deb64u(cle_b64, 256))
    except (ValueError, ErreurWebAuthn):
        raise ErreurWebAuthn("cle", "stockée") from None
    signe = bytes(auth_data) + hashlib.sha256(bytes(client_data_json)).digest()
    try:
        cle.verify(bytes(signature), signe, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise ErreurWebAuthn("signature") from None
    nouveau = auth["compteur"]
    if not (nouveau == 0 and compteur_stocke == 0) and nouveau <= compteur_stocke:
        raise ErreurWebAuthn("compteur")
    return nouveau


# --- Options envoyées au navigateur --------------------------------------------------------------------------

def options_creation(rp_id, rp_nom, identifiant_utilisateur, nom_utilisateur, challenge, exclure=()):
    """Options de navigator.credentials.create (champs binaires en base64url, le client les convertit)."""
    return {
        "challenge": b64u(challenge),
        "rp": {"id": rp_id, "name": rp_nom},
        "user": {"id": b64u(identifiant_utilisateur), "name": nom_utilisateur, "displayName": nom_utilisateur},
        "pubKeyCredParams": [{"type": "public-key", "alg": ALG_ES256}],
        "authenticatorSelection": {"residentKey": "preferred", "userVerification": "required"},
        "attestation": "none",
        "timeout": 120000,
        "excludeCredentials": [{"type": "public-key", "id": i} for i in exclure],
    }


def options_assertion(rp_id, challenge, identifiants):
    return {
        "challenge": b64u(challenge),
        "rpId": rp_id,
        "userVerification": "required",
        "timeout": 60000,
        "allowCredentials": [{"type": "public-key", "id": i} for i in identifiants],
    }
