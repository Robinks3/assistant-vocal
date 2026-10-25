# -*- coding: utf-8 -*-
"""Fabrique les sons de début et de fin d'écoute de l'assistant (série 2).

Tout est synthétisé ici, aucun son tiers n'est chargé. Sortie mono 48 kHz 16 bits.
Quatre paires : bronze (bol de bronze tenu à la main), corde (corde pincée sur
caisse de bois), declic (cran d'un bouton mécanique avec un reflet métallique),
halo (accord FM qui s'ouvre puis se referme).

Usage :
    python fabriquer_sons.py            fabrique les WAV et l'analyse
    python fabriquer_sons.py --version  affiche la version
"""
import os
import struct
import sys
import zlib

import numpy as np
from scipy import signal as sg

VERSION = "2.0.0"
DATE = "2026-10-22"
SR = 48000
ICI = os.path.dirname(os.path.abspath(__file__))
ANALYSE = os.path.join(ICI, "analyse")

CIBLE_DEBUT = -20.0   # LUFS, sonie momentanée maximale (fenêtre 400 ms)
CIBLE_FIN = -22.0     # la fin est un peu plus discrète
NUIT_DB = -6.0


# ---------------------------------------------------------------- outils de base

def n_de(d):
    return int(round(d * SR))


def temps(n):
    return np.arange(n) / SR


def lissee(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def sos_bande(lo, hi, ordre=2):
    return sg.butter(ordre, [lo, hi], btype="band", fs=SR, output="sos")


def sos_haut(fc, ordre=2):
    return sg.butter(ordre, fc, btype="high", fs=SR, output="sos")


def sos_bas(fc, ordre=2):
    return sg.butter(ordre, fc, btype="low", fs=SR, output="sos")


def sos_cloche(f0, gain_db, q):
    """Correcteur en cloche (RBJ)."""
    A = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / SR
    al = np.sin(w) / (2 * q)
    b = [1 + al * A, -2 * np.cos(w), 1 - al * A]
    a = [1 + al / A, -2 * np.cos(w), 1 - al / A]
    return sg.tf2sos(b, a)


def filtrer(x, *soss):
    for s in soss:
        x = sg.sosfilt(s, x)
    return x


def impulsion_maillet(fc):
    """Force de contact t/tau^2 exp(-t/tau) : passe-bas doux du 2e ordre sans
    zéro spectral, départ à zéro donc sans clic. Aire unité."""
    tau = 1 / (2 * np.pi * fc)
    t = temps(max(16, n_de(14 * tau)))
    p = t / tau ** 2 * np.exp(-t / tau)
    return p / p.sum()


def frapper(x, fc):
    return sg.fftconvolve(x, impulsion_maillet(fc))[: len(x)]


def modes(n, specs, t0=0.0, t_etouffe=None, rampe=0.03, glisse=None):
    """Synthèse modale : somme de modes amortis partant de la phase nulle
    (réponse impulsionnelle d'un résonateur). specs = (fréquence, gain, tau,
    tau après étouffement ou None). L'étouffement (main ou paume posée) fait
    passer progressivement l'amortissement de tau à tau_etouffe."""
    out = np.zeros(n)
    i0 = n_de(t0)
    m = n - i0
    if m <= 0:
        return out
    t = temps(m)
    for f, g, tau, tau_e in specs:
        if f >= 0.45 * SR:
            continue
        taux = np.full(m, 1.0 / tau)
        if t_etouffe is not None and tau_e is not None:
            s = lissee((t - (t_etouffe - t0)) / rampe)
            taux = taux + (1.0 / tau_e - 1.0 / tau) * s
        amp = np.exp(-np.cumsum(taux) / SR)
        ph = 2 * np.pi * f * t
        if glisse is not None:
            prof, tg = glisse
            ph = ph + 2 * np.pi * f * prof * tg * (1 - np.exp(-t / tg))
        out[i0:] += g * amp * np.sin(ph)
    return out


def bruit(n, t0, montee, chute, lo, hi, gain, graine):
    """Bouffée de bruit filtré, enveloppe (1 - e^-t/montee) e^-t/chute."""
    rng = np.random.default_rng(graine)
    out = np.zeros(n)
    i0 = n_de(t0)
    m = n - i0
    t = temps(m)
    w = filtrer(rng.standard_normal(m + 2000), sos_bande(lo, hi))[2000:]
    w /= np.sqrt(np.mean(w ** 2))
    env = (1 - np.exp(-t / montee)) * np.exp(-t / chute)
    out[i0:] = gain * env * w
    return out


# ---------------------------------------------------------------- pièce

def reponse_piece(rt60, graine, longueur=0.34):
    """Réponse impulsionnelle d'une petite pièce : premières réflexions
    adoucies puis champ diffus en trois bandes, les aigus s'éteignent plus vite."""
    rng = np.random.default_rng(graine)
    n = n_de(longueur)
    t = temps(n)
    w = rng.standard_normal(n)
    bas = filtrer(w, sos_bas(700))
    mil = filtrer(w, sos_bande(700, 2800))
    hau = filtrer(w, sos_haut(2800))

    def chute(rt):
        return np.exp(-6.908 * t / rt)

    diffus = bas * chute(rt60 * 1.1) + mil * chute(rt60) + 0.45 * hau * chute(rt60 * 0.5)
    diffus *= lissee((t - 0.006) / 0.02)
    ir = 0.55 * diffus / np.sqrt(np.mean(diffus[: n_de(0.05)] ** 2) + 1e-12) * 0.05
    for d, g in [(0.0047, 0.50), (0.0073, -0.40), (0.0101, 0.34), (0.0137, -0.28),
                 (0.0176, 0.22), (0.0224, -0.18), (0.0281, 0.14)]:
        ir[n_de(d)] += g
    ir = filtrer(ir, sos_bas(5200))
    return ir / np.sqrt(np.sum(ir ** 2))


def reverberer(x, wet_db, rt60, graine):
    ir = reponse_piece(rt60, graine)
    wet = sg.fftconvolve(x, ir)[: len(x)]
    wet = filtrer(wet, sos_haut(260))
    wet *= np.sqrt(np.sum(x ** 2) / (np.sum(wet ** 2) + 1e-20) * 10 ** (wet_db / 10))
    return x + wet


def finir(x, wet_db, rt60, graine, fondu=0.045):
    """Pièce, correction commune (pas de grave inutile, creux doux vers 3,3 kHz,
    pas d'extrême aigu) puis fondu final jusqu'au zéro exact."""
    x = reverberer(x, wet_db, rt60, graine)
    x = filtrer(x, sos_haut(140), sos_cloche(3300, -3.0, 0.7), sos_bas(10000, 4))
    nf = n_de(fondu)
    x[-nf:] *= np.cos(np.linspace(0, np.pi / 2, nf)) ** 2
    x[0] = 0.0
    x[-1] = 0.0
    return x


# ---------------------------------------------------------------- 1. bronze

# Modes d'un bol : les quatre modes d'anneau (1, 2,83, 5,41, 8,7) et trois modes
# secondaires plus faibles (flexion de la paroi), qui donnent la matière.
RAPPORTS_BOL = [1.000, 2.828, 5.405, 8.700, 1.531, 2.054, 3.912]
GAINS_BOL = [1.0, 1.00, 0.40, 0.18, 0.13, 0.10, 0.08]
TAUS_BOL = [0.70, 0.30, 0.08, 0.035, 0.12, 0.10, 0.04]
TAUS_E_BOL = [0.060, 0.045, 0.030, 0.020, 0.040, 0.035, 0.020]
ECARTS_BOL = [1.3, 2.9, 4.6, 7.0, 1.9, 2.4, 3.3]   # modes dédoublés par l'asymétrie


def bol(n, f0, durete, t_etouffe, graine):
    specs = []
    for r, g, ta, te, e in zip(RAPPORTS_BOL, GAINS_BOL, TAUS_BOL, TAUS_E_BOL, ECARTS_BOL):
        specs.append((f0 * r, g, ta, te))
        specs.append((f0 * r + e, 0.75 * g, ta * 0.85, te))
    y = modes(n, specs, t_etouffe=t_etouffe, rampe=0.035)
    y = frapper(y, durete)
    y += bruit(n, 0.0, 0.0003, 0.0015, 500, 2500, 0.06, graine)          # feutre sur métal
    y += bruit(n, t_etouffe - 0.005, 0.005, 0.025, 250, 1000, 0.006, graine + 1)  # main posée
    return y


def bronze_debut():
    n = n_de(0.44)
    return finir(bol(n, 587.33, 2200, 0.19, 101), -14, 0.30, 1)


def bronze_fin():
    n = n_de(0.34)
    return finir(bol(n, 440.00, 1500, 0.10, 111), -14, 0.30, 1)


# ---------------------------------------------------------------- 2. corde

def corde_pincee(n, f0, t0, amp, position, douceur, t_etouffe):
    specs = []
    B = 1.5e-4
    k = 1
    while True:
        fk = k * f0 * np.sqrt(1 + B * k * k)
        if fk > 8000:
            break
        a = abs(np.sin(k * np.pi * position)) / k ** 1.1 / (1 + (fk / douceur) ** 2)
        tau = 1.1 / (1 + (fk / 1000) ** 1.6)
        tau_e = 0.035 / (1 + fk / 2500)
        specs.append((fk, a, tau, tau_e))
        specs.append((fk + 0.35, 0.3 * a, tau * 1.7, tau_e))   # seconde polarisation
        k += 1
    y = modes(n, specs, t0=t0, t_etouffe=t_etouffe, rampe=0.025, glisse=(0.0015, 0.025))
    return amp * y


def caisse(y):
    """Résonances d'une caisse de bois."""
    return filtrer(y, sos_cloche(205, 4, 1.8), sos_cloche(400, 4, 2.5), sos_cloche(880, 3, 2.0),
                   sos_cloche(1650, 2, 2.5), sos_cloche(3000, -4, 0.9), sos_bas(5500))


def corde_debut():
    n = n_de(0.40)
    y = corde_pincee(n, 440.00, 0.000, 1.00, 0.17, 3200, 0.22)
    y += corde_pincee(n, 659.26, 0.045, 0.80, 0.20, 3200, 0.22)
    y = frapper(y, 4000)
    y = caisse(y)
    y += bruit(n, 0.000, 0.0005, 0.004, 400, 2500, 0.040, 201)
    y += bruit(n, 0.045, 0.0005, 0.004, 400, 2500, 0.032, 202)
    return finir(y, -15, 0.30, 2)


def corde_fin():
    n = n_de(0.26)
    y = corde_pincee(n, 440.00, 0.0, 1.0, 0.22, 2200, 0.075)
    y = frapper(y, 4000)
    y = caisse(y)
    y += bruit(n, 0.0, 0.0005, 0.004, 300, 1500, 0.030, 211)
    return finir(y, -15, 0.30, 2)


# ---------------------------------------------------------------- 3. declic

def cran(n, t0, k, amp, f_reflet, graine, t_amorti=0.14):
    specs = [
        (480 * k, 1.00, 0.060, 0.025), (705 * k, 0.70, 0.036, 0.020), (1060 * k, 0.45, 0.020, 0.012),
        (1460 * k, 0.30, 0.010, None), (2180 * k, 0.12, 0.006, None),
    ]
    reflet = [(f_reflet, 0.34, 0.16, 0.030), (f_reflet + 2.2, 0.22, 0.13, 0.030),
              (f_reflet * 2.32, 0.05, 0.03, 0.015)]
    # le reflet part 0,6 ms après le choc : l'onde met ce temps à atteindre la pièce qui sonne
    y = modes(n, specs, t0=t0, t_etouffe=t0 + t_amorti, rampe=0.04) + modes(n, reflet, t0=t0 + 0.0006, t_etouffe=t0 + t_amorti, rampe=0.04)
    y = frapper(y, 2800)
    y += bruit(n, t0, 0.0002, 0.0012, 600, 2500, 0.15, graine)
    return amp * y


def declic_debut():
    n = n_de(0.32)
    y = cran(n, 0.000, 1.00, 0.70, 783.99, 301, 0.17) + cran(n, 0.082, 1.12, 1.00, 1046.50, 302, 0.12)
    return finir(y, -11, 0.28, 3)


def declic_fin():
    n = n_de(0.25)
    y = cran(n, 0.000, 0.84, 1.00, 659.26, 311, 0.09)
    return finir(y, -12, 0.25, 3)


# ---------------------------------------------------------------- 4. halo

def voix_fm(n, f, t0, amp, attaque, tau, i_pic, i_fin, t_pic, t_rel, tau_rel, graine,
            desaccords=(-6.0, 0.0, 7.0), poids=(0.45, 1.0, 0.45)):
    """Voix FM 1:1 à trois copies désaccordées. L'indice s'ouvre (t_pic) puis se
    referme, l'amplitude décroît puis se relâche comme une touche qu'on lâche."""
    rng = np.random.default_rng(graine)
    out = np.zeros(n)
    i0 = n_de(t0)
    m = n - i0
    t = temps(m)
    env = lissee(t / attaque) * np.exp(-t / tau) * np.exp(-np.maximum(t - t_rel, 0) / tau_rel)
    idx = i_fin + (i_pic - i_fin) * lissee(t / t_pic) * np.exp(-np.maximum(t - t_pic, 0) / 0.09)
    y = np.zeros(m)
    for c, w in zip(desaccords, poids):
        fc = f * 2 ** (c / 1200)
        y += w * np.sin(2 * np.pi * fc * t + rng.uniform(0, 2 * np.pi)
                        + idx * np.sin(2 * np.pi * fc * t + rng.uniform(0, 2 * np.pi)))
    y = filtrer(y, sos_haut(0.6 * f, 4))   # la FM 1:1 replie une bande sur 0 Hz
    out[i0:] = amp * env * y / sum(poids)
    return out


def halo_debut():
    n = n_de(0.45)
    y = voix_fm(n, 440.00, 0.000, 0.90, 0.012, 0.20, 1.3, 0.45, 0.030, 0.28, 0.045, 401)
    y += voix_fm(n, 659.26, 0.022, 0.75, 0.012, 0.20, 1.3, 0.45, 0.030, 0.26, 0.045, 402)
    y += voix_fm(n, 987.77, 0.044, 0.50, 0.012, 0.20, 0.9, 0.35, 0.030, 0.24, 0.045, 403)
    y += bruit(n, 0.0, 0.020, 0.090, 600, 1800, 0.05, 404)
    return finir(y, -11, 0.32, 4)


def halo_fin():
    n = n_de(0.32)
    y = voix_fm(n, 880.00, 0.000, 0.45, 0.012, 0.14, 0.8, 0.30, 0.025, 0.15, 0.040, 411)
    y += voix_fm(n, 587.33, 0.020, 0.75, 0.012, 0.14, 0.9, 0.35, 0.025, 0.13, 0.040, 412)
    y += voix_fm(n, 392.00, 0.040, 0.70, 0.012, 0.14, 0.9, 0.35, 0.025, 0.11, 0.040, 413)
    y += bruit(n, 0.0, 0.020, 0.070, 600, 1600, 0.04, 414)
    return finir(y, -11, 0.32, 4)


PAIRES = [
    ("bronze", bronze_debut, bronze_fin),
    ("corde", corde_debut, corde_fin),
    ("declic", declic_debut, declic_fin),
    ("halo", halo_debut, halo_fin),
]


# ---------------------------------------------------------------- mesures

K_SOS = np.array([
    [1.53512485958697, -2.69169618940638, 1.19839281085285, 1.0, -1.69065929318241, 0.73248077421585],
    [1.0, -2.0, 1.0, 1.0, -1.99004745483398, 0.99007225036621],
])


def sonie(x):
    """Sonie momentanée maximale BS.1770 (fenêtre 400 ms, pondération K).
    Pour un son plus court qu'un bloc de 400 ms, c'est sa sonie intégrée."""
    pad = np.zeros(n_de(0.4))
    y = sg.sosfilt(K_SOS, np.concatenate([pad, x, pad]))
    w = n_de(0.4)
    c = np.concatenate([[0.0], np.cumsum(y ** 2)])
    ms = (c[w:] - c[:-w]) / w
    return -0.691 + 10 * np.log10(ms.max() + 1e-20)


def crete_vraie(x):
    return 20 * np.log10(np.max(np.abs(sg.resample_poly(x, 4, 1))) + 1e-20)


def tablette(x):
    """Petits haut-parleurs simulés : passe-haut 300 Hz du 4e ordre."""
    return filtrer(x, sos_haut(300, 4))


def spectre(x):
    N = 1 << 16
    P = np.abs(np.fft.rfft(x, N)) ** 2
    f = np.fft.rfftfreq(N, 1 / SR)
    return f, P


def parts(x):
    f, P = spectre(x)
    tot = P.sum()
    bandes = [(0, 300), (300, 400), (400, 2000), (2000, 5000), (5000, SR / 2), (1000, 2000)]
    return [100 * P[(f >= a) & (f < b)].sum() / tot for a, b in bandes]


def spectre_lisse(x, fg):
    """Spectre lissé au sixième d'octave, en dB, sur la grille fg."""
    f, P = spectre(x)
    c = np.concatenate([[0.0], np.cumsum(P)])
    lo = np.searchsorted(f, fg / 2 ** (1 / 12))
    hi = np.maximum(np.searchsorted(f, fg * 2 ** (1 / 12)), lo + 1)
    return 10 * np.log10((c[hi] - c[lo]) / (hi - lo) + 1e-30)


def enveloppe(x, pas=0.001, fen=0.002):
    w = n_de(fen)
    c = np.concatenate([[0.0], np.cumsum(np.concatenate([np.zeros(w), x ** 2]))])
    rms = np.sqrt(np.maximum((c[w:] - c[:-w]) / w, 0))[: len(x)]
    return rms[:: n_de(pas)]


def mesurer(x):
    m = {}
    m["duree_ms"] = 1000 * len(x) / SR
    m["lufs"] = sonie(x)
    m["lufs_tab"] = sonie(tablette(x))
    m["perte_tab_db"] = m["lufs"] - m["lufs_tab"]
    m["crete_dbtp"] = crete_vraie(x)
    p = parts(x)
    m["part_0_300"], m["part_300_400"], m["part_400_2k"], m["part_2k_5k"], m["part_5k"], m["part_1k_2k"] = p
    pk = parts(sg.sosfilt(K_SOS, x))
    m["part_2k_5k_K"] = pk[3]
    fg = np.geomspace(100, 12000, 400)
    s = spectre_lisse(x, fg)
    m["pic_2k_5k_rel_db"] = s[(fg >= 2000) & (fg <= 5000)].max() - s.max()
    m["f_pic_hz"] = fg[np.argmax(s)]
    f, P = spectre(tablette(x))
    m["centroide_tab_hz"] = float((f * P).sum() / P.sum())
    env = enveloppe(x)
    edb = 20 * np.log10(env + 1e-12)
    ip = int(np.argmax(env))
    m["t_pic_ms"] = ip
    i10 = int(np.argmax(env >= 0.1 * env[ip]))
    i90 = int(np.argmax(env >= 0.9 * env[ip]))
    m["attaque_ms"] = i90 - i10
    plateau = edb >= edb[ip] - 1.5
    m["plateau_ms"] = int(np.max(np.diff(np.flatnonzero(np.concatenate([[True], ~plateau, [True]]))) - 1))
    nf = int(0.045 * 1000)
    m["niveau_avant_fondu_db"] = float(edb[len(edb) - nf - 1] - edb[ip])
    hf = filtrer(x, sos_haut(8000, 4))
    m["eclat_8k_db"] = 20 * np.log10(enveloppe(hf, 0.0005, 0.0005).max() / (np.sqrt(np.mean(x ** 2)) + 1e-20) + 1e-20)
    m["debut_ech"] = abs(x[0])
    m["fin_rms_dbfs"] = 20 * np.log10(np.sqrt(np.mean(x[-n_de(0.002):] ** 2)) + 1e-20)
    return m


# ---------------------------------------------------------------- images

PALETTE = np.array([(0, 0, 4), (31, 12, 72), (85, 15, 109), (136, 34, 106), (186, 54, 85),
                    (227, 89, 51), (249, 140, 10), (249, 201, 50), (252, 255, 164)], float)


def couleurs(v):
    v = np.clip(v, 0, 1) * (len(PALETTE) - 1)
    i = np.minimum(np.floor(v).astype(int), len(PALETTE) - 2)
    fr = (v - i)[..., None]
    return (PALETTE[i] * (1 - fr) + PALETTE[i + 1] * fr).astype(np.uint8)


def tracer(img, ys, col):
    H = img.shape[0]
    ys = np.clip(np.round(ys).astype(int), 0, H - 1)
    for c in range(len(ys)):
        a, b = sorted((ys[c], ys[c - 1] if c else ys[c]))
        img[a:b + 1, c] = col


TMAX, FMIN, FMAX = 0.46, 80, 12000


def panneau_spectro(x, W=560, H=210, plage=(-105, -15)):
    nper, hop = 1536, 96
    xp = np.zeros(n_de(TMAX))
    xp[: min(len(x), len(xp))] = x[: len(xp)]
    f, t, Z = sg.stft(xp, fs=SR, window="blackmanharris", nperseg=nper, noverlap=nper - hop, nfft=4096)
    S = 20 * np.log10(2 * np.abs(Z) + 1e-12)
    ti = np.clip(np.searchsorted(t, np.linspace(0, TMAX, W)), 0, len(t) - 1)
    lignes = np.geomspace(FMAX, FMIN, H)
    fi = np.interp(lignes, f, np.arange(len(f)))
    lo = np.floor(fi).astype(int)
    fr = (fi - lo)[:, None]
    Sc = S[:, ti]
    img = Sc[lo] * (1 - fr) + Sc[np.minimum(lo + 1, len(f) - 1)] * fr
    rgb = couleurs((img - plage[0]) / (plage[1] - plage[0]))
    for fg, col in [(300, (0, 200, 255)), (2000, (120, 255, 120)), (5000, (120, 255, 120))]:
        r = int(np.argmin(np.abs(lignes - fg)))
        rgb[r, ::4] = col
    for tg in np.arange(0.1, TMAX, 0.1):
        rgb[::4, int(tg / TMAX * (W - 1))] = (110, 110, 110)
    return rgb


def panneau_env(x, W=560, H=80, plage=(-84.0, -4.0)):
    img = np.full((H, W, 3), 16, np.uint8)
    for g in (-20, -40, -60, -80):
        img[int((plage[1] - g) / (plage[1] - plage[0]) * (H - 1)), ::3] = 60
    for tg in np.arange(0.1, TMAX, 0.1):
        img[::3, int(tg / TMAX * (W - 1))] = 60
    for sig, col in [(tablette(x), (0, 200, 255)), (x, (240, 240, 240))]:
        env = enveloppe(sig)
        tt = np.linspace(0, TMAX * 1000 - 1, W).astype(int)
        e = np.where(tt < len(env), env[np.minimum(tt, len(env) - 1)], 1e-9)
        db = 20 * np.log10(e + 1e-9)
        tracer(img, (plage[1] - db) / (plage[1] - plage[0]) * (H - 1), col)
    return img


def panneau_spectre(x, W=560, H=100, plage=60.0):
    fg = np.geomspace(FMIN, FMAX, W)
    img = np.full((H, W, 3), 16, np.uint8)
    img[:, (fg >= 2000) & (fg <= 5000)] = (60, 18, 18)
    img[:, (fg >= 400) & (fg < 2000)] = (16, 44, 24)
    img[::3, int(np.argmin(np.abs(fg - 300)))] = (0, 200, 255)
    for g in range(10, int(plage), 10):
        img[int(g / plage * (H - 1)), ::3] = 70
    s = spectre_lisse(x, fg)
    ref = s.max()
    for sig, col in [(tablette(x), (0, 200, 255)), (x, (240, 240, 240))]:
        d = spectre_lisse(sig, fg) - ref
        tracer(img, -d / plage * (H - 1), col)
    return img


def planche(paire, debut, fin):
    cols = []
    for x in (debut, fin):
        cols.append(np.concatenate([panneau_spectro(x), np.full((6, 560, 3), 40, np.uint8),
                                    panneau_env(x), np.full((6, 560, 3), 40, np.uint8),
                                    panneau_spectre(x)], axis=0))
    h = cols[0].shape[0]
    return np.concatenate([cols[0], np.full((h, 12, 3), 40, np.uint8), cols[1]], axis=1)


def ecrire_png(chemin, rgb):
    h, w, _ = rgb.shape
    brut = b"".join(b"\x00" + rgb[r].tobytes() for r in range(h))

    def bloc(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(chemin, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                 + bloc(b"IDAT", zlib.compress(brut, 9)) + bloc(b"IEND", b""))


# ---------------------------------------------------------------- WAV

def ecrire_wav(chemin, x, titre):
    pcm = np.round(np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()

    def bloc(tag, data):
        taille = len(data)
        if taille % 2:
            data += b"\x00"
        return tag + struct.pack("<I", taille) + data

    def texte(s):
        return s.encode("utf-8") + b"\x00"

    info = (b"INFO" + bloc(b"INAM", texte(titre))
            + bloc(b"ICMT", texte(f"Sons d'écoute v{VERSION} du {DATE}, synthèse maison"))
            + bloc(b"ISFT", texte(f"fabriquer_sons.py {VERSION}")))
    fmt = struct.pack("<HHIIHH", 1, 1, SR, SR * 2, 2, 16)
    corps = b"WAVE" + bloc(b"fmt ", fmt) + bloc(b"data", pcm) + bloc(b"LIST", info)
    with open(chemin, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", len(corps)) + corps)


# ---------------------------------------------------------------- principal

def limiter(x, plafond_db=-3.6, anticipation=0.002, retour=0.030):
    """Limiteur à anticipation : le gain descend en douceur avant la crête
    (fenêtre de Hann de 4 ms) et remonte en 30 ms. Aucune saturation."""
    from scipy.ndimage import minimum_filter1d
    seuil = 10 ** (plafond_db / 20)
    g = np.minimum(1.0, seuil / (np.abs(x) + 1e-12))
    L = n_de(anticipation)
    g = minimum_filter1d(g, size=2 * L + 1)
    k = 1 - np.exp(-1 / (retour * SR))
    r = g.copy()
    for i in range(1, len(r)):
        r[i] = min(g[i], r[i - 1] + (1 - r[i - 1]) * k)
    w = np.hanning(2 * L + 3)[1:-1]
    r = np.convolve(r, w / w.sum(), mode="same")
    return x * r, 20 * np.log10(r.min())


def normaliser(x, cible):
    """Sonie visée, puis limiteur tant que la crête vraie dépasse -3,2 dBTP."""
    x = x * 10 ** ((cible - sonie(x)) / 20)
    reduction = 0.0
    for _ in range(8):
        if crete_vraie(x) <= -3.2:
            break
        x, red = limiter(x)
        reduction = min(reduction, red)
        x = x * 10 ** ((cible - sonie(x)) / 20)
    if reduction < 0:
        print(f"  limiteur : {reduction:.1f} dB au plus fort")
    return x


def main():
    if "--version" in sys.argv:
        print(f"fabriquer_sons.py {VERSION} ({DATE})")
        return
    os.makedirs(ANALYSE, exist_ok=True)
    sons = []
    lignes = [f"Mesures, fabriquer_sons.py v{VERSION} du {DATE}", ""]
    for i, (nom, f_debut, f_fin) in enumerate(PAIRES, start=1):
        debut = normaliser(f_debut(), CIBLE_DEBUT)
        fin = normaliser(f_fin(), CIBLE_FIN)
        sons.append((debut, fin))
        for role, x in (("debut", debut), ("fin", fin)):
            base = f"{i}-{nom}-{role}"
            ecrire_wav(os.path.join(ICI, base + ".wav"), x, base)
            ecrire_wav(os.path.join(ICI, base + "-nuit.wav"), x * 10 ** (NUIT_DB / 20), base + "-nuit")
            m = mesurer(x)
            lignes.append(base)
            lignes.append("  " + "  ".join(f"{k}={v:.1f}" if isinstance(v, float) else f"{k}={v}"
                                          for k, v in m.items()))
        ecart = sonie(debut) - sonie(fin)
        lignes.append(f"  ecart debut-fin = {ecart:.1f} dB, sur tablette = {sonie(tablette(debut)) - sonie(tablette(fin)):.1f} dB")
        lignes.append("")
        ecrire_png(os.path.join(ANALYSE, f"{i}-{nom}.png"), planche(nom, debut, fin))
    # écoute enchaînée : début, 2 s de silence, fin, puis 1,5 s avant la paire suivante
    morceaux = [np.zeros(n_de(0.5))]
    for debut, fin in sons:
        morceaux += [debut, np.zeros(n_de(2.0)), fin, np.zeros(n_de(1.5))]
    ecrire_wav(os.path.join(ICI, "ecoute-enchainee.wav"), np.concatenate(morceaux), "ecoute-enchainee")
    texte = "\n".join(lignes)
    with open(os.path.join(ANALYSE, "mesures.txt"), "w", encoding="utf-8") as fh:
        fh.write(texte + "\n")
    print(texte)


if __name__ == "__main__":
    main()
