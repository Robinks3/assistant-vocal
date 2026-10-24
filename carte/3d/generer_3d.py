"""Construit le modèle 3D de l'appartement à partir de pieces.json, meubles.json et lampes.json.

Les données de l'appartement sont dans le dossier carte/ de la configuration de la maison (ASSISTANT_VOCAL_CONFIG,
sinon config/ à la racine du dépôt, voir poc/maison.py). Sorties :
- carte/modele.glb de la configuration : murs, sols, meubles et ampoules. Chaque ampoule est un nœud
  nommé d'après l'objet Home Assistant (convention de 3DHome : `sejour_salon` pour `light.exemple6`),
  avec `extras.haEntity`. Repère glTF : y vers le haut, x et -z = x et y du plan.
- genere/android/maison3d/vue3d.html de la configuration : page autonome (three.js inclus, aucune
  connexion requise) qui affiche la scène et anime les lampes, rangée dans les assets de l'APK par
  build.gradle.kts. Voir README.md pour l'interface `window.assistant`.
Le modèle de page (vue3d_modele.html) et three.js restent ici, dans le moteur.

Usage : python carte/3d/generer_3d.py
"""
import base64
import json
import re
import struct
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parents[1] / "poc"))
import maison  # noqa: E402

CARTE = maison.chemin("carte")
PAGE = maison.chemin("genere/android/maison3d/vue3d.html")
EP = 0.10  # épaisseur des murs, en m
LINTEAU = 5.10  # haut des portes

COUL_SOL = {"sejour": "#C9B79C", "circulation": "#B9B4AC", "chambre": "#A9B8C9", "salle_de_bain": "#A7C4BE"}
COUL_MUR = "#EDEBE6"


# ---------- géométrie du plan ----------

def aire_signee(poly):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1])) / 2


def trianguler(poly):
    """Découpe en oreilles d'un polygone simple, renvoie des triangles d'indices (sens trigonométrique)."""
    pts = list(range(len(poly)))
    if aire_signee(poly) < 0:
        pts.reverse()

    def dans(p, a, b, c):
        def s(u, v, w):
            return (u[0] - w[0]) * (v[1] - w[1]) - (v[0] - w[0]) * (u[1] - w[1])
        d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))

    tris = []
    garde = 0
    while len(pts) > 3 and garde < 1000:
        garde += 1
        for i in range(len(pts)):
            ia, ib, ic = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            a, b, c = poly[ia], poly[ib], poly[ic]
            if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) <= 1e-9:
                continue
            if any(dans(poly[j], a, b, c) for j in pts if j not in (ia, ib, ic)):
                continue
            tris.append((ia, ib, ic))
            pts.pop(i)
            break
    tris.append(tuple(pts))
    return tris


def murs(pieces, ouvertures, hauteur):
    """Pavés de murs le long des contours des pièces, posés à l'extérieur, troués aux ouvertures."""
    boites, linteaux, vus = [], [], set()
    for p in pieces:
        poly = p["polygone"]
        sens = 1 if aire_signee(poly) > 0 else -1
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
            horiz = abs(y1 - y2) < 1e-6
            if horiz:
                c, a, b = y1, min(x1, x2), max(x1, x2)
                # normale extérieure : à droite du parcours pour un polygone direct
                ext = -1 if (x2 - x1) * sens > 0 else 1
            else:
                c, a, b = x1, min(y1, y2), max(y1, y2)
                ext = 1 if (y2 - y1) * sens > 0 else -1
            a, b = a - EP, b + EP
            trous = []
            for o in ouvertures:
                (u1, v1), (u2, v2) = o["segment"]
                oh = abs(v1 - v2) < 1e-6
                if oh != horiz:
                    continue
                oc, oa, ob = (v1, min(u1, u2), max(u1, u2)) if oh else (u1, min(v1, v2), max(v1, v2))
                if abs(oc - c) < 0.2 and ob > a and oa < b:
                    trous.append((max(oa, a), min(ob, b), o["porte"]))
            trous.sort()
            morceaux, debut = [], a
            for ta, tb, porte in trous:
                if ta > debut:
                    morceaux.append((debut, ta))
                if porte:
                    linteaux.append((horiz, c, ext, ta, tb))
                debut = max(debut, tb)
            if debut < b:
                morceaux.append((debut, b))
            for ma, mb in morceaux:
                if mb - ma < 0.02:
                    continue
                c0, c1 = sorted((c, c + ext * EP))
                boite = (ma, c0, mb, c1) if horiz else (c0, ma, c1, mb)
                cle = tuple(round(v, 2) for v in boite)
                if cle not in vus:
                    vus.add(cle)
                    boites.append([*boite, 0.0, hauteur])
    lint = []
    for horiz, c, ext, ta, tb in linteaux:
        c0, c1 = sorted((c, c + ext * EP))
        boite = (ta, c0, tb, c1) if horiz else (c0, ta, c1, tb)
        cle = tuple(round(v, 2) for v in boite)
        if cle not in vus:
            vus.add(cle)
            lint.append([*boite, LINTEAU, hauteur])
    return boites, lint


# ---------- maillages (repère glTF : X = x, Y = hauteur, Z = -y) ----------

def boite_maillage(b):
    x0, y0, x1, y1, z0, z1 = b
    faces = [  # (normale, 4 coins en (x, hauteur, -y))
        ((0, 1, 0), [(x0, z1, -y0), (x1, z1, -y0), (x1, z1, -y1), (x0, z1, -y1)]),
        ((0, -1, 0), [(x0, z0, -y1), (x1, z0, -y1), (x1, z0, -y0), (x0, z0, -y0)]),
        ((0, 0, 1), [(x0, z0, -y0), (x1, z0, -y0), (x1, z1, -y0), (x0, z1, -y0)]),
        ((0, 0, -1), [(x1, z0, -y1), (x0, z0, -y1), (x0, z1, -y1), (x1, z1, -y1)]),
        ((1, 0, 0), [(x1, z0, -y0), (x1, z0, -y1), (x1, z1, -y1), (x1, z1, -y0)]),
        ((-1, 0, 0), [(x0, z0, -y1), (x0, z0, -y0), (x0, z1, -y0), (x0, z1, -y1)]),
    ]
    pos, nor, idx = [], [], []
    for n, coins in faces:
        k = len(pos)
        pos += coins
        nor += [n] * 4
        idx += [k, k + 1, k + 2, k, k + 2, k + 3]
    return pos, nor, idx


def fusion(maillages):
    pos, nor, idx = [], [], []
    for p, n, i in maillages:
        k = len(pos)
        pos += p
        nor += n
        idx += [k + j for j in i]
    return pos, nor, idx


def sol_maillage(poly, ep=0.02):
    pos = [(x, 0.0, -y) for x, y in poly]
    nor = [(0, 1, 0)] * len(poly)
    idx = [i for t in trianguler(poly) for i in t]
    return pos, nor, idx


def sphere_maillage(c, r, n=10):
    import math
    pos, nor, idx = [], [], []
    for i in range(n + 1):
        th = math.pi * i / n
        for j in range(2 * n + 1):
            ph = 2 * math.pi * j / (2 * n)
            d = (math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph))
            pos.append((c[0] + r * d[0], c[1] + r * d[1], c[2] + r * d[2]))
            nor.append(d)
    w = 2 * n + 1
    for i in range(n):
        for j in range(2 * n):
            a, b = i * w + j, (i + 1) * w + j
            idx += [a, a + 1, b, b, a + 1, b + 1]
    return pos, nor, idx


def hexa(c):
    c = c.lstrip("#")
    return [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def lineaire(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def ecrire_glb(objets, chemin, version):
    """objets : liste de (nom, maillage, couleur, emissif, extras)."""
    binaire = bytearray()
    vues, accesseurs, maillages, noeuds, materiaux = [], [], [], [], []

    def ajouter(donnees, fmt, compte, type_, cible, mini=None, maxi=None):
        while len(binaire) % 4:
            binaire.append(0)
        debut = len(binaire)
        binaire.extend(struct.pack(f"<{len(donnees)}{fmt}", *donnees))
        vues.append({"buffer": 0, "byteOffset": debut, "byteLength": len(binaire) - debut, "target": cible})
        acc = {"bufferView": len(vues) - 1, "componentType": 5126 if fmt == "f" else 5125, "count": compte, "type": type_}
        if mini is not None:
            acc["min"], acc["max"] = mini, maxi
        accesseurs.append(acc)
        return len(accesseurs) - 1

    for nom, (pos, nor, idx), couleur, emissif, extras in objets:
        plat = [v for p in pos for v in p]
        mini = [min(p[i] for p in pos) for i in range(3)]
        maxi = [max(p[i] for p in pos) for i in range(3)]
        a_pos = ajouter(plat, "f", len(pos), "VEC3", 34962, mini, maxi)
        a_nor = ajouter([v for n in nor for v in n], "f", len(nor), "VEC3", 34962)
        a_idx = ajouter(idx, "I", len(idx), "SCALAR", 34963)
        mat = {"name": nom, "doubleSided": True, "pbrMetallicRoughness": {"baseColorFactor": [*map(lineaire, hexa(couleur)), 1.0],
                                                     "metallicFactor": 0.0, "roughnessFactor": 0.85}}
        if emissif:
            mat["emissiveFactor"] = list(map(lineaire, hexa(emissif)))
        materiaux.append(mat)
        maillages.append({"name": nom, "primitives": [{"attributes": {"POSITION": a_pos, "NORMAL": a_nor},
                                                         "indices": a_idx, "material": len(materiaux) - 1}]})
        noeud = {"name": nom, "mesh": len(maillages) - 1}
        if extras:
            noeud["extras"] = extras
        noeuds.append(noeud)
    while len(binaire) % 4:
        binaire.append(0)
    gltf = {"asset": {"version": "2.0", "generator": f"assistant generer_3d.py {version}"},
            "scene": 0, "scenes": [{"name": "appartement", "nodes": list(range(len(noeuds)))}],
            "nodes": noeuds, "meshes": maillages, "materials": materiaux, "accessors": accesseurs,
            "bufferViews": vues, "buffers": [{"byteLength": len(binaire)}]}
    js = json.dumps(gltf, ensure_ascii=False).encode("utf-8")
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(binaire)
    with open(chemin, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(binaire), 0x004E4942) + bytes(binaire))


def main():
    if not (CARTE / "pieces.json").exists():
        raise SystemExit(f"{CARTE / 'pieces.json'} absent : le plan de l'appartement va dans carte/ du dossier de configuration "
                         "(modèle : config-exemple/carte/).")
    pieces = json.loads((CARTE / "pieces.json").read_text(encoding="utf-8"))
    meubles = json.loads((CARTE / "meubles.json").read_text(encoding="utf-8"))
    lampes = json.loads((CARTE / "lampes.json").read_text(encoding="utf-8"))
    version = meubles["version"]
    h = meubles["hauteur_plafond"]
    b_murs, b_linteaux = murs(pieces["pieces"], meubles["ouvertures"], h)

    objets = [("murs", fusion([boite_maillage(b) for b in b_murs]), COUL_MUR, None, {"role": "murs"}),
              ("linteaux", fusion([boite_maillage(b) for b in b_linteaux]), COUL_MUR, None, {"role": "linteaux"})]
    for p in pieces["pieces"]:
        objets.append((f"sol_{p['id']}", sol_maillage(p["polygone"]), COUL_SOL.get(p["type"], "#BBBBBB"), None,
                       {"role": "sol", "piece": p["id"], "nom": p["nom"]}))
    for m in meubles["meubles"]:
        objets.append((m["id"], boite_maillage(m["boite"]), m["couleur"], None,
                       {"role": "meuble", "piece": m["piece"], "nom": m["nom"]}))
    for l in lampes["lampes"]:
        x, y, z = l["xyz"]
        objets.append((l["entite"].split(".", 1)[1], sphere_maillage((x, z, -y), 0.07), "#FFF4D6", "#000000",
                       {"role": "lampe", "haEntity": l["entite"], "nom": l["nom"], "type": l["type"], "piece": l["piece"]}))
    ecrire_glb(objets, CARTE / "modele.glb", version)

    # données de la page : tout en mètres dans le repère du plan
    scene = {
        "version": version, "date": pieces["date"], "hauteur": h,
        "murs": [[round(v, 3) for v in b] for b in b_murs],
        "linteaux": [[round(v, 3) for v in b] for b in b_linteaux],
        "pieces": [{"id": p["id"], "nom": p["nom"], "type": p["type"], "couleur": COUL_SOL.get(p["type"], "#BBBBBB"),
                    "polygone": p["polygone"], "triangles": trianguler(p["polygone"]),
                    "confiance": p["confiance"]} for p in pieces["pieces"]],
        "meubles": [{"id": m["id"], "nom": m["nom"], "piece": m.get("piece"), "boite": m["boite"], "couleur": m["couleur"]} for m in meubles["meubles"]],
        "lampes": lampes["lampes"], "groupes": lampes["groupes"],
        "medias": meubles.get("medias", []), "groupes_medias": meubles.get("groupes_medias", {}),
        "emprise": pieces["repere"]["emprise"],
    }
    modele = (ICI / "vue3d_modele.html").read_text(encoding="utf-8")
    three = (ICI / "vendor" / "three.module.min.js").read_text(encoding="utf-8")
    # le module three.js se termine par « export{a as B,...} » : on l'expose en window.THREE
    m = re.search(r"export\s*\{([^}]*)\}\s*;?\s*$", three)
    paires = [e.strip().split(" as ") for e in m.group(1).split(",")]
    three = three[:m.start()] + "window.THREE={" + ",".join(f"{p[-1]}:{p[0]}" for p in paires) + "};"
    page = (modele.replace("/*THREE*/", three.replace("</script", "<\\/script"))
                  .replace("/*SCENE*/", json.dumps(scene, ensure_ascii=False))
                  .replace("{{VERSION}}", version).replace("{{DATE}}", pieces["date"]))
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page, encoding="utf-8")
    print(f"modele.glb : {len(objets)} nœuds ({len(b_murs)} pans de mur, {len(meubles['meubles'])} meubles, "
          f"{len(lampes['lampes'])} ampoules). vue3d.html : {len(page) // 1024} Ko")


if __name__ == "__main__":
    main()
