"""Démarrage à vide du serveur des satellites, lancé en sous-processus par test_demarrage.py.

Le serveur démarre sans poc/.env (le chargement du fichier est neutralisé, un vrai .env d'un poste de
travail n'est jamais lu), sans micro ni haut-parleur, sans Home Assistant et sans réseau : toute connexion
hors de la machine est refusée et comptée. Il se termine seul après quelques secondes d'écoute.

Arguments : port chiffré à ouvrir, durée d'écoute en secondes.
Codes de sortie : 0 démarrage réussi, 3 tentative de connexion réseau, 4 module tiers absent."""
import asyncio
import ipaddress
import socket
import sys
import types
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

tentatives = []
_LOCAL = ("127.0.0.1", "::1", "localhost")


def _hote(adresse):
    return adresse[0] if isinstance(adresse, tuple) else adresse


_connect = socket.socket.connect
_getaddrinfo = socket.getaddrinfo


def _connect_local(self, adresse):
    if _hote(adresse) not in _LOCAL:
        tentatives.append(f"connect {adresse}")
        raise OSError("réseau coupé pour le test")
    return _connect(self, adresse)


def _est_adresse_ip(texte):
    try:
        ipaddress.ip_address(texte)
        return True
    except ValueError:
        return False


def _getaddrinfo_local(hote, *args, **kwargs):
    # Un nom d'hôte (hors localhost) demanderait un serveur DNS : refusé. Une adresse IP passe, le filtre
    # de connect() décide ensuite.
    if isinstance(hote, str) and hote not in _LOCAL and hote != "" and not _est_adresse_ip(hote):
        tentatives.append(f"getaddrinfo {hote}")
        raise OSError("résolution coupée pour le test")
    return _getaddrinfo(hote, *args, **kwargs)


socket.socket.connect = _connect_local
socket.getaddrinfo = _getaddrinfo_local

try:
    import dotenv
    dotenv.load_dotenv = lambda *a, **k: False  # ni poc/.env ni aucun autre fichier de réglages
    import acces
    import serveur_satellite as S
except ImportError as e:
    print(f"MODULE_ABSENT {e.name}")
    sys.exit(4)

acces.adresses_ecoute = lambda: ["127.0.0.1"]  # jamais d'écoute sur les autres interfaces pendant un test


async def essai(port_tls, duree):
    args = types.SimpleNamespace(essai=True, port=0, port_tls=port_tls, seuil=0.5, calibrer=False)
    try:
        await asyncio.wait_for(S.servir(args), timeout=duree)
    except asyncio.TimeoutError:
        print("DEMARRAGE_OK")


if __name__ == "__main__":
    asyncio.run(essai(int(sys.argv[1]), float(sys.argv[2])))
    if tentatives:
        print("TENTATIVES_RESEAU " + "; ".join(tentatives))
        sys.exit(3)
