"""Lecture et renommage dans les registres de HA (API WebSocket, le REST ne le permet pas).

Usage : python poc/outils/ha_registre.py lire salon
        python poc/outils/ha_registre.py renommer-appareil <device_id> "Nouveau nom"
"""
import asyncio, json, sys
from pathlib import Path
import websockets
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistant as A  # noqa: E402


async def session(commandes):
    cfg = A.charger_env()
    url = cfg["ha_url"].replace("http", "ws", 1) + "/api/websocket"
    async with websockets.connect(url, max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": cfg["ha_token"]}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"
        sorties = []
        for i, c in enumerate(commandes, 1):
            await ws.send(json.dumps({"id": i, **c}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == i:
                    sorties.append(r)
                    break
        return sorties


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    action = sys.argv[1]
    if action == "lire":
        motif = sys.argv[2]
        ents, devs = asyncio.run(session([{"type": "config/entity_registry/list"},
                                          {"type": "config/device_registry/list"}]))
        appareils = {d["id"]: d for d in devs["result"]}
        vus = set()
        for e in ents["result"]:
            if motif in e["entity_id"]:
                d = appareils.get(e["device_id"]) or {}
                print(f"{e['entity_id']} | nom entité={e.get('name')} | nom d'origine={e.get('original_name')} "
                      f"| appareil={d.get('id')} name={d.get('name')} name_by_user={d.get('name_by_user')} "
                      f"| intégration={e.get('platform')} | pièce entité={e.get('area_id')} appareil={d.get('area_id')}")
                vus.add(d.get("id"))
    elif action == "renommer-appareil":
        r, = asyncio.run(session([{"type": "config/device_registry/update", "device_id": sys.argv[2],
                                   "name_by_user": sys.argv[3]}]))
        print("ok" if r.get("success") else r, "->", r.get("result", {}).get("name_by_user"))


if __name__ == "__main__":
    main()
