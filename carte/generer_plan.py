"""Génère plan.svg et plan.png à partir de pieces.json, et y recalcule les surfaces.

Les trois fichiers sont dans le dossier carte/ de la configuration de la maison (ASSISTANT_VOCAL_CONFIG, sinon
config/ à la racine du dépôt, voir poc/maison.py).

Usage : python carte/generer_plan.py  (depuis n'importe quel dossier)
"""
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "poc"))
import maison  # noqa: E402

ICI = maison.chemin("carte")
PX_PAR_M = 80
MARGE = 60
COULEURS = {
    "sejour": "#F3E6CF",
    "circulation": "#ECECEC",
    "chambre": "#DCE8F5",
    "salle_de_bain": "#D5EFEA",
}
TRAIT = "#2B2B2B"
TEXTE = "#1E1E1E"


def surface(poly):
    """Surface d'un polygone simple (formule du lacet), en m²."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def centre(poly):
    """Centre de gravité d'un polygone simple."""
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    a /= 2
    return cx / (6 * a), cy / (6 * a)


def police(taille, gras=False):
    for nom in (("segoeuib.ttf" if gras else "segoeui.ttf"), ("arialbd.ttf" if gras else "arial.ttf")):
        try:
            return ImageFont.truetype(nom, taille)
        except OSError:
            continue
    return ImageFont.load_default()


def couper(texte, font, largeur):
    """Coupe un nom en lignes qui tiennent dans la largeur de la pièce, en pixels."""
    lignes, courante = [], ""
    for mot in texte.split():
        essai = f"{courante} {mot}".strip()
        if courante and font.getlength(essai) > largeur:
            lignes.append(courante)
            courante = mot
        else:
            courante = essai
    return lignes + [courante]


def main():
    chemin = ICI / "pieces.json"
    data = json.loads(chemin.read_text(encoding="utf-8"))
    for p in data["pieces"]:
        p["surface_m2"] = round(surface(p["polygone"]), 1)
    data["surface_totale_m2"] = round(sum(p["surface_m2"] for p in data["pieces"]), 1)
    texte = json.dumps(data, ensure_ascii=False, indent=2)
    # un point par ligne : [x, y] plutôt que trois lignes
    texte = re.sub(r"\[\s+(-?[\d.]+),\s+(-?[\d.]+)\s+\]", r"[\1, \2]", texte)
    chemin.write_text(texte + "\n", encoding="utf-8")

    e = data["repere"]["emprise"]
    largeur = int((e["xmax"] - e["xmin"]) * PX_PAR_M + 2 * MARGE)
    hauteur = int((e["ymax"] - e["ymin"]) * PX_PAR_M + 2 * MARGE + 50)

    def ecran(x, y):
        return MARGE + (x - e["xmin"]) * PX_PAR_M, MARGE + (e["ymax"] - y) * PX_PAR_M

    # Précisions sur le relevé (clé « pied » de pieces.json, facultative), ajoutées au pied du plan.
    pied = f"Plan v{data['version']} du {data['date']}" + (f", {data['pied']}" if data.get("pied") else "")
    f_nom, f_surf, f_pied = police(15, True), police(13), police(11)
    etiquettes = {}
    for p in data["pieces"]:
        xs = [x for x, _ in p["polygone"]]
        lignes = couper(p["nom"], f_nom, (max(xs) - min(xs)) * PX_PAR_M - 24)
        if p.get("nom_a_confirmer"):
            lignes[-1] += " ?"
        cx, cy = ecran(*centre(p["polygone"]))
        y0 = cy - 9 * len(lignes) + 9
        etiquettes[p["id"]] = (cx, [(l, y0 + 18 * i - 4) for i, l in enumerate(lignes)],
                                y0 + 18 * len(lignes) - 3, f'{str(p["surface_m2"]).replace(".", ",")} m²')

    # SVG
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{largeur}" height="{hauteur}" viewBox="0 0 {largeur} {hauteur}" font-family="Segoe UI, Arial, sans-serif">',
           f'<rect width="{largeur}" height="{hauteur}" fill="#FFFFFF"/>']
    for p in data["pieces"]:
        pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in (ecran(x, y) for x, y in p["polygone"]))
        tiret = ' stroke-dasharray="8 6"' if p["confiance"] == "estimee" else ""
        svg.append(f'<polygon id="{p["id"]}" points="{pts}" fill="{COULEURS.get(p["type"], "#EEEEEE")}" stroke="{TRAIT}" stroke-width="3"{tiret}/>')
    for cx, lignes, ys, surf in etiquettes.values():
        for l, y in lignes:
            svg.append(f'<text x="{cx:.1f}" y="{y:.1f}" text-anchor="middle" font-size="15" font-weight="600" fill="{TEXTE}">{l}</text>')
        svg.append(f'<text x="{cx:.1f}" y="{ys:.1f}" text-anchor="middle" font-size="13" fill="{TEXTE}">{surf}</text>')
    for porte in data.get("portes", []):
        (x1, y1), (x2, y2) = (ecran(*q) for q in porte["segment"])
        svg.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#C0392B" stroke-width="7"/>')
        svg.append(f'<text x="{(x1 + x2) / 2:.1f}" y="{y1 + 20:.1f}" text-anchor="middle" font-size="12" fill="#C0392B">{porte["nom"]}</text>')
    bx, by = MARGE, hauteur - 40
    svg.append(f'<line x1="{bx}" y1="{by}" x2="{bx + 2 * PX_PAR_M}" y2="{by}" stroke="{TRAIT}" stroke-width="3"/>')
    svg.append(f'<text x="{bx + PX_PAR_M}" y="{by - 6}" text-anchor="middle" font-size="12" fill="{TEXTE}">2 m</text>')
    svg.append(f'<text x="{largeur - MARGE}" y="{by + 4}" text-anchor="end" font-size="11" fill="#666666">{pied}</text>')
    svg.append("</svg>")
    (ICI / "plan.svg").write_text("\n".join(svg) + "\n", encoding="utf-8")

    # PNG
    img = Image.new("RGB", (largeur, hauteur), "white")
    d = ImageDraw.Draw(img)
    for p in data["pieces"]:
        pts = [ecran(x, y) for x, y in p["polygone"]]
        d.polygon(pts, fill=COULEURS.get(p["type"], "#EEEEEE"))
    for p in data["pieces"]:
        pts = [ecran(x, y) for x, y in p["polygone"]]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            if p["confiance"] == "estimee":
                n = max(1, int(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 / 14))
                for i in range(0, n, 2):
                    t0, t1 = i / n, min(1, (i + 1) / n)
                    d.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                            (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)], fill=TRAIT, width=3)
            else:
                d.line([a, b], fill=TRAIT, width=3)
    for cx, lignes, ys, surf in etiquettes.values():
        for l, y in lignes:
            d.text((cx, y), l, font=f_nom, fill=TEXTE, anchor="ms")
        d.text((cx, ys), surf, font=f_surf, fill=TEXTE, anchor="ms")
    for porte in data.get("portes", []):
        (x1, y1), (x2, y2) = (ecran(*q) for q in porte["segment"])
        d.line([(x1, y1), (x2, y2)], fill="#C0392B", width=7)
        d.text(((x1 + x2) / 2, y1 + 20), porte["nom"], font=f_pied, fill="#C0392B", anchor="ms")
    d.line([(bx, by), (bx + 2 * PX_PAR_M, by)], fill=TRAIT, width=3)
    d.text((bx + PX_PAR_M, by - 6), "2 m", font=f_pied, fill=TEXTE, anchor="ms")
    d.text((largeur - MARGE, by + 4), pied, font=f_pied, fill="#666666", anchor="rs")
    img.save(ICI / "plan.png")
    print(f"{len(data['pieces'])} pièces, {data['surface_totale_m2']} m² au total, plan.svg et plan.png écrits")


if __name__ == "__main__":
    main()
