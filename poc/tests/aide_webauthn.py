"""Authentificateur virtuel pour les tests : fabrique de vraies créations et de vraies signatures WebAuthn
avec une clé P-256 générée par cryptography, comme le ferait un téléphone."""
import hashlib
import json
import os
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

import webauthn as WA


def cbor(valeur):
    """Encodeur CBOR minimal (entiers, octets, textes, tables, listes, booléens), juste ce qu'il faut aux tests."""
    def tete(majeur, n):
        if n < 24:
            return bytes([majeur << 5 | n])
        if n < 256:
            return bytes([majeur << 5 | 24, n])
        if n < 65536:
            return bytes([majeur << 5 | 25]) + struct.pack(">H", n)
        return bytes([majeur << 5 | 26]) + struct.pack(">I", n)
    if valeur is True:
        return b"\xf5"
    if valeur is False:
        return b"\xf4"
    if valeur is None:
        return b"\xf6"
    if isinstance(valeur, int):
        return tete(0, valeur) if valeur >= 0 else tete(1, -1 - valeur)
    if isinstance(valeur, bytes):
        return tete(2, len(valeur)) + valeur
    if isinstance(valeur, str):
        brut = valeur.encode("utf-8")
        return tete(3, len(brut)) + brut
    if isinstance(valeur, list):
        return tete(4, len(valeur)) + b"".join(cbor(v) for v in valeur)
    if isinstance(valeur, dict):
        return tete(5, len(valeur)) + b"".join(cbor(k) + cbor(v) for k, v in valeur.items())
    raise TypeError(valeur)


def client_data(type_, challenge, origine, **en_plus):
    donnees = {"type": type_, "challenge": WA.b64u(challenge), "origin": origine, "crossOrigin": False}
    donnees.update(en_plus)
    return json.dumps(donnees).encode()


class Authentificateur:
    """Une clé de téléphone : crée une clé (attestation none) puis signe des défis."""

    def __init__(self, rp_id="assistant.exemple.ts.net", compteur=0):
        self.rp_id = rp_id
        self.cle = ec.generate_private_key(ec.SECP256R1())
        self.id = os.urandom(32)
        self.compteur = compteur

    def cle_cose(self):
        n = self.cle.public_key().public_numbers()
        return {WA.COSE_KTY: WA.KTY_EC2, WA.COSE_ALG: WA.ALG_ES256, WA.COSE_CRV: WA.CRV_P256,
                WA.COSE_X: n.x.to_bytes(32, "big"), WA.COSE_Y: n.y.to_bytes(32, "big")}

    def _auth_data(self, drapeaux, rp_id=None, compteur=0, avec_cle=False):
        rp_hash = hashlib.sha256((rp_id or self.rp_id).encode()).digest()
        donnees = rp_hash + bytes([drapeaux]) + struct.pack(">I", compteur)
        if avec_cle:
            donnees += b"\x00" * 16 + struct.pack(">H", len(self.id)) + self.id + cbor(self.cle_cose())
        return donnees

    def creer(self, challenge, origine, rp_id=None, drapeaux=WA.DRAPEAU_UP | WA.DRAPEAU_UV | WA.DRAPEAU_AT, fmt="none",
              type_="webauthn.create", cle_cose=None, att_stmt=None):
        auth = self._auth_data(drapeaux, rp_id, self.compteur, avec_cle=True)
        if cle_cose is not None:
            auth = self._auth_data(drapeaux, rp_id, self.compteur)
            auth += b"\x00" * 16 + struct.pack(">H", len(self.id)) + self.id + cbor(cle_cose)
        attestation = cbor({"fmt": fmt, "attStmt": att_stmt if att_stmt is not None else {}, "authData": auth})
        return {"id": WA.b64u(self.id), "clientDataJSON": WA.b64u(client_data(type_, challenge, origine)),
                "attestationObject": WA.b64u(attestation)}

    def signer(self, challenge, origine, rp_id=None, drapeaux=WA.DRAPEAU_UP | WA.DRAPEAU_UV, compteur=None,
               type_="webauthn.get", client=None):
        if compteur is None:
            self.compteur += 1
            compteur = self.compteur
        auth = self._auth_data(drapeaux, rp_id, compteur)
        cd = client if client is not None else client_data(type_, challenge, origine)
        signature = self.cle.sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": WA.b64u(self.id), "clientDataJSON": WA.b64u(cd), "authenticatorData": WA.b64u(auth),
                "signature": WA.b64u(signature)}
