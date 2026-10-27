"""Contrôle de mise en page de pages HTML statiques (maquettes du client web, écrans codés).

Ouvre chaque page avec Chrome sans fenêtre (protocole DevTools, aucune dépendance à installer), à plusieurs
largeurs (360, 390 et 430 par défaut, hauteur 844) et dans les deux thèmes (clair et sombre, par
`prefers-color-scheme`), puis signale :
  - superposition : deux éléments porteurs de texte, d'icône ou de commande dont les rectangles se
    chevauchent sans lien d'ancêtre (un contrôle contient son propre contenu). Les fonds, les calques
    décoratifs `aria-hidden` et les superpositions voulues (feuille modale, voile, pastille posée sur une
    icône) sont ignorés quand l'élément porte l'attribut `data-superposition-voulue` : aucune liste
    d'exceptions dans l'outil ;
  - texte-coupe : texte, icône ou commande rognés par un conteneur à `overflow` caché, ou texte qui sort de
    son bloc, sans points de suspension ni `line-clamp` voulus ;
  - defilement-horizontal : la page, ou un conteneur défilant, est plus large que sa zone visible. Un rail
    à défilement voulu porte l'attribut `data-defilement-horizontal-voulu` ;
  - barre-recouvre : une barre fixe (position fixed, ou absolute collée au bord du conteneur) recouvre du
    contenu au bout du défilement faute de réserve de place ;
  - cible-tactile : une commande de moins de 44 x 44 px (hors lien en ligne dans un texte).

Usage : python poc/outils/verifier_mise_en_page.py [pages ou dossiers] [--largeurs 360,390,430]
        [--themes clair,sombre] [--captures [DOSSIER]] [--json] [--cibles SELECTEUR]
Sans argument, contrôle docs/maquettes/client-web/*.html.
Code de sortie : 0 aucun défaut, 1 au moins un défaut, 2 Chrome introuvable ou erreur d'exécution.
Copies temporaires et captures : dans un dossier temporaire du système, jamais dans le dépôt. Profils Chrome :
quelques profils fixes réutilisés dans %LOCALAPPDATA%\\verifier-mise-en-page, jamais un profil neuf par lancement
(voir prendre_profil)."""
import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse

RACINE = Path(__file__).resolve().parents[2]
DOSSIER_PAGES = RACINE / "docs" / "maquettes" / "client-web"
CHROME_DEFAUT = "C:/Program Files/Google/Chrome/Application/chrome.exe"
HAUTEUR = 844
LARGEURS = (360, 390, 430)
THEMES = ("clair", "sombre")
CIBLES_PAR_DEFAUT = ".telephone"
NB_PROFILS = 4

# Mesure exécutée dans la page. ARGS est injecté par l'appelant (portée des cibles tactiles).
SCRIPT_MESURE = r"""
(async () => {
const SEUIL = 1.0, TOL = 1.5, CIBLE = 43.5;
const de = document.documentElement;
const CW = de.clientWidth;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const img = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
await img();
try { await Promise.race([document.fonts.ready, sleep(3000)]); } catch (e) {}
try { document.getAnimations().forEach(a => { try { a.finish(); } catch (e) {} }); } catch (e) {}
await img();

const r1 = v => Math.round(v * 10) / 10;
const rectDe = r => [r1(r.left), r1(r.top), r1(r.width), r1(r.height)];
const csc = new Map();
const cs = e => { let c = csc.get(e); if (!c) { c = getComputedStyle(e); csc.set(e, c); } return c; };
const inter = (a, b) => {
  const l = Math.max(a.left, b.left), t = Math.max(a.top, b.top);
  const r = Math.min(a.right, b.right), bt = Math.min(a.bottom, b.bottom);
  return (r > l && bt > t) ? { left: l, top: t, right: r, bottom: bt, width: r - l, height: bt - t } : null;
};
const defauts = [];

function selecteur(el) {
  const parts = [];
  for (let e = el; e && e.nodeType === 1 && e !== document.body && e !== de; e = e.parentElement) {
    let p = e.tagName.toLowerCase();
    if (e.id) { parts.unshift(p + '#' + e.id); break; }
    const cl = [...e.classList].slice(0, 2);
    if (cl.length) p += '.' + cl.join('.');
    const par = e.parentElement;
    if (par) {
      const memes = [...par.children].filter(c => c.tagName === e.tagName);
      if (memes.length > 1) p += ':nth-of-type(' + (memes.indexOf(e) + 1) + ')';
    }
    parts.unshift(p);
  }
  const fig = el.closest && el.closest('figure');
  let pre = '';
  if (fig) pre = 'vue ' + ([...document.querySelectorAll('figure')].indexOf(fig) + 1) + ' : ';
  return pre + (parts.length > 4 ? '... > ' : '') + parts.slice(-4).join(' > ');
}
function decrire(it) {
  return { sel: selecteur(it.el), rect: rectDe(it.r), texte: it.texte || '', genre: it.kind };
}
function visible(el) {
  if (cs(el).visibility !== 'visible') return false;
  for (let e = el; e && e !== de; e = e.parentElement) {
    const c = cs(e);
    if (c.display === 'none' || parseFloat(c.opacity) === 0) return false;
  }
  return true;
}
function clipsDe(el, soiMeme) {
  const res = [];
  for (let e = soiMeme ? el : el.parentElement; e && e !== de && e !== document.body; e = e.parentElement) {
    const c = cs(e);
    if (c.overflowX !== 'visible' || c.overflowY !== 'visible') {
      res.push({
        el: e, r: e.getBoundingClientRect(),
        defX: c.overflowX === 'auto' || c.overflowX === 'scroll',
        defY: c.overflowY === 'auto' || c.overflowY === 'scroll',
      });
    }
  }
  return res;
}

const SEL_CMD = 'button, a[href], summary, select, textarea, input:not([type="hidden"]), [role="button"], [role="switch"], [role="tab"], [role="slider"], [role="link"], [role="checkbox"], [role="radio"], [role="menuitem"], [tabindex]:not([tabindex="-1"]), label';
let barresEls = [];

function collecter() {
  const items = [];
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = tw.nextNode())) {
    if (!n.nodeValue.trim()) continue;
    const el = n.parentElement;
    if (!el) continue;
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE', 'TEMPLATE', 'OPTION'].includes(el.tagName)) continue;
    if (el.closest('svg')) continue;
    if (!visible(el)) continue;
    if (el.closest('[aria-hidden="true"]')) continue;
    const rg = document.createRange();
    rg.selectNodeContents(n);
    for (const rc of rg.getClientRects()) {
      if (rc.width < 1 || rc.height < 1) continue;
      items.push({ kind: 'texte', el, r: rc, texte: n.nodeValue.trim().slice(0, 32) });
    }
  }
  for (const s of document.querySelectorAll('svg, img, canvas, video')) {
    if (s.parentElement && s.parentElement.closest('svg')) continue;
    if (!visible(s)) continue;
    const rc = s.getBoundingClientRect();
    if (rc.width < 1 || rc.height < 1) continue;
    const grand = rc.width > 64 || rc.height > 64;
    const cache = s.getAttribute('aria-hidden') === 'true';
    if (grand && (cache || (s.tagName.toLowerCase() === 'svg' && s.getAttribute('role') !== 'img'))) continue;
    items.push({ kind: 'icone', el: s, r: rc, texte: s.getAttribute('aria-label') || s.tagName.toLowerCase() });
  }
  for (const c of document.querySelectorAll(SEL_CMD)) {
    if (c.tagName === 'LABEL' && !c.querySelector('input, select, textarea')) continue;
    if (!visible(c)) continue;
    const rc = c.getBoundingClientRect();
    if (rc.width < 1 || rc.height < 1) continue;
    items.push({ kind: 'commande', el: c, r: rc, texte: (c.getAttribute('aria-label') || c.textContent || '').trim().slice(0, 32) });
  }
  const keep = [];
  for (const it of items) {
    it.clips = clipsDe(it.el, it.kind === 'texte');
    // rect pour les recouvrements : le texte est rogné de 12 % en haut et en bas (encre des lettres)
    if (it.kind === 'texte') {
      const h = it.r.height * 0.12;
      it.rp = { left: it.r.left, right: it.r.right, top: it.r.top + h, bottom: it.r.bottom - h };
    } else it.rp = it.r;
    // un item entièrement masqué par un conteneur qui ne défile pas n'existe pas à l'écran
    let v = it.r;
    for (const c of it.clips) { if (!c.defX && !c.defY) { v = inter(v, c.r); if (!v) break; } }
    if (!v) continue;
    it.marque = it.el.closest('[data-superposition-voulue]');
    it.barre = barresEls.find(b => b.contains(it.el)) || null;
    keep.push(it);
  }
  return keep;
}

function detecterBarres() {
  const res = [];
  for (const e of document.querySelectorAll('body *')) {
    const c = cs(e);
    if (c.position !== 'fixed' && c.position !== 'absolute') continue;
    if (e.closest('svg') || e.closest('[data-superposition-voulue]')) continue;
    if (!visible(e)) continue;
    const rc = e.getBoundingClientRect();
    if (rc.width < 1 || rc.height < 1) continue;
    let cont;
    if (c.position === 'fixed') cont = { left: 0, top: 0, right: CW, bottom: window.innerHeight, width: CW, height: window.innerHeight, el: null };
    else {
      const op = e.offsetParent;
      if (op && op !== document.body) { const b = op.getBoundingClientRect(); cont = { left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height, el: op }; }
      else cont = { left: 0, top: 0, right: CW, bottom: window.innerHeight, width: CW, height: window.innerHeight, el: null };
    }
    if (rc.width < 0.9 * cont.width || rc.height > 0.5 * cont.height) continue;
    const haut = Math.abs(rc.top - cont.top) <= 1, bas = Math.abs(rc.bottom - cont.bottom) <= 1;
    if (!haut && !bas) continue;
    if (res.some(b => b.el.contains(e))) continue;
    res.push({ el: e, bas, cont, fixe: c.position === 'fixed' });
  }
  return res;
}

barresEls = [];
const barres = detecterBarres();
barresEls = barres.map(b => b.el);

// ---- défilement horizontal de la page
{
  const sw = Math.max(de.scrollWidth, document.body.scrollWidth);
  if (sw > CW + 1) {
    const coupables = [];
    for (const e of document.querySelectorAll('body *')) {
      if (!visible(e)) continue;
      const rc = e.getBoundingClientRect();
      if (rc.width < 1 || (rc.right <= CW + TOL && rc.left >= -TOL)) continue;
      const par = e.parentElement;
      if (par && par !== document.body) {
        const pr = par.getBoundingClientRect();
        if (pr.right > CW + TOL || pr.left < -TOL) continue;
      }
      if (clipsDe(e, false).length) continue;
      coupables.push({ el: e, r: rc });
    }
    coupables.sort((a, b) => b.r.right - a.r.right);
    const cibles = coupables.slice(0, 4);
    if (!cibles.length) defauts.push({ type: 'defilement-horizontal', a: { sel: 'page', rect: [0, 0, sw, 0], texte: '', genre: 'page' }, b: null, detail: 'la page défile en largeur (' + sw + ' px pour ' + CW + ' px visibles)' });
    for (const c of cibles) {
      defauts.push({ type: 'defilement-horizontal', a: { sel: selecteur(c.el), rect: rectDe(c.r), texte: (c.el.textContent || '').trim().slice(0, 32), genre: 'element' }, b: null, detail: 'la page défile en largeur (' + sw + ' px pour ' + CW + ' px visibles), cet élément sort de ' + r1(c.r.right - CW) + ' px à droite' });
    }
  }
}

let items = collecter();
const estMarque = el => !!el.closest('[data-defilement-horizontal-voulu]');

// ---- superpositions
{
  const memo = new Map();
  for (let i = 0; i < items.length; i++) {
    for (let j = i + 1; j < items.length; j++) {
      const a = items[i], b = items[j];
      if (a.el === b.el) continue;
      if (a.rp.right <= b.rp.left + SEUIL || b.rp.right <= a.rp.left + SEUIL) continue;
      if (a.rp.bottom <= b.rp.top + SEUIL || b.rp.bottom <= a.rp.top + SEUIL) continue;
      if (a.kind === 'commande' && a.el.contains(b.el)) continue;
      if (b.kind === 'commande' && b.el.contains(a.el)) continue;
      if (a.marque !== b.marque) continue;
      if (a.barre !== b.barre) continue;
      let ra = a.rp, rb = b.rp;
      for (const c of a.clips) { if (!c.el.contains(b.el)) { ra = inter(ra, c.r); if (!ra) break; } }
      if (!ra) continue;
      for (const c of b.clips) { if (!c.el.contains(a.el)) { rb = inter(rb, c.r); if (!rb) break; } }
      if (!rb) continue;
      const z = inter(ra, rb);
      if (!z || z.width <= SEUIL || z.height <= SEUIL) continue;
      const cle = selecteur(a.el) + '|' + selecteur(b.el);
      const aire = z.width * z.height;
      const prev = memo.get(cle);
      if (!prev || prev.aire < aire) memo.set(cle, { aire, a, b, z });
    }
  }
  for (const { a, b, z } of memo.values()) {
    defauts.push({ type: 'superposition', a: decrire(a), b: decrire(b), detail: 'zone commune ' + r1(z.width) + ' x ' + r1(z.height) + ' px en ' + rectDe(z).slice(0, 2).join(', ') });
  }
}

// ---- texte, icône ou commande coupé, texte hors de son bloc
{
  const vus = new Set();
  const vouluSuspension = (it, jusquA) => {
    for (let e = it.el; e; e = e.parentElement) {
      const c = cs(e);
      if (c.textOverflow === 'ellipsis' || (c.webkitLineClamp && c.webkitLineClamp !== 'none')) return true;
      if (e === jusquA) break;
    }
    return false;
  };
  for (const it of items) {
    if (it.marque && it.marque !== it.el.closest('[data-superposition-voulue]')) continue;
    let arretX = false, arretY = false;
    for (const c of it.clips) {
      if (c.defX || c.defY) { if (c.defX) arretX = true; if (c.defY) arretY = true; continue; }
      const dx = !arretX && (it.r.right > c.r.right + TOL || it.r.left < c.r.left - TOL);
      const dy = !arretY && (it.r.bottom > c.r.bottom + TOL || it.r.top < c.r.top - TOL);
      if (!dx && !dy) continue;
      if (estMarque(it.el)) continue;
      if (it.kind === 'texte' && vouluSuspension(it, c.el)) continue;
      const cle = selecteur(it.el) + '|' + selecteur(c.el);
      if (vus.has(cle)) continue;
      vus.add(cle);
      const qui = dx ? 'en largeur' : 'en hauteur';
      defauts.push({ type: 'texte-coupe', a: decrire(it), b: { sel: selecteur(c.el), rect: rectDe(c.r), texte: '', genre: 'conteneur' }, detail: it.kind + ' rogné ' + qui + ' par son conteneur' });
    }
    if (it.kind === 'texte') {
      let bloc = it.el;
      while (bloc && ['inline', 'contents'].includes(cs(bloc).display)) bloc = bloc.parentElement;
      if (!bloc || bloc === document.body) continue;
      if (estMarque(bloc)) continue;
      const cb = cs(bloc);
      if (cb.textOverflow === 'ellipsis' || (cb.webkitLineClamp && cb.webkitLineClamp !== 'none')) continue;
      const br = bloc.getBoundingClientRect();
      const g = br.left + parseFloat(cb.borderLeftWidth) + parseFloat(cb.paddingLeft);
      const d = br.right - parseFloat(cb.borderRightWidth) - parseFloat(cb.paddingRight);
      if (it.r.right > d + TOL || it.r.left < g - TOL) {
        const cle = 'bloc|' + selecteur(it.el);
        if (vus.has(cle)) continue;
        vus.add(cle);
        defauts.push({ type: 'texte-coupe', a: decrire(it), b: { sel: selecteur(bloc), rect: rectDe(br), texte: '', genre: 'bloc' }, detail: 'texte hors de la zone de contenu de son bloc (' + r1(Math.max(it.r.right - d, g - it.r.left)) + ' px)' });
      }
    }
  }
}

// ---- conteneurs défilants plus larges que leur zone visible
{
  for (const e of document.querySelectorAll('body *')) {
    const c = cs(e);
    if (c.overflowX !== 'auto' && c.overflowX !== 'scroll') continue;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.tagName)) continue;
    if (!visible(e)) continue;
    if (e.scrollWidth <= e.clientWidth + 1) continue;
    if (estMarque(e)) continue;
    const er = e.getBoundingClientRect();
    const coupables = items.filter(it => e.contains(it.el) && (it.r.right > er.right + TOL || it.r.left < er.left - TOL));
    if (!coupables.length) continue;
    const pire = coupables.reduce((m, it) => (it.r.right > m.r.right ? it : m), coupables[0]);
    defauts.push({ type: 'defilement-horizontal', a: decrire(pire), b: { sel: selecteur(e), rect: rectDe(er), texte: '', genre: 'conteneur' }, detail: 'le conteneur défile en largeur (' + e.scrollWidth + ' px pour ' + e.clientWidth + ' px visibles)' });
  }
}

// ---- cibles tactiles
{
  const portee = ARGS.cibles;
  const cmds = items.filter(it => it.kind === 'commande');
  const vus = new Set();
  for (const it of cmds) {
    if (portee && !it.el.closest(portee)) continue;
    if (it.el.closest('[aria-hidden="true"]')) continue;
    if (it.el.tagName === 'A' && cs(it.el).display === 'inline') continue;
    const grand = x => x.r.width >= CIBLE && x.r.height >= CIBLE;
    if (cmds.some(o => o !== it && o.el !== it.el && o.el.contains(it.el) && grand(o))) continue;
    if (grand(it)) continue;
    const cle = selecteur(it.el);
    if (vus.has(cle)) continue;
    vus.add(cle);
    defauts.push({ type: 'cible-tactile', a: decrire(it), b: null, detail: 'cible de ' + r1(it.r.width) + ' x ' + r1(it.r.height) + ' px (44 x 44 minimum)' });
  }
}

// ---- barres fixes : réserve de place au bout du défilement
for (const bar of barres) {
  const cont = bar.cont.el;
  const racine = cont || document.documentElement;
  const defilants = [];
  if (bar.fixe) defilants.push(document.scrollingElement);
  for (const s of racine.querySelectorAll('*')) {
    if (bar.el.contains(s)) continue;
    const c = cs(s);
    if (c.overflowY === 'auto' || c.overflowY === 'scroll') defilants.push(s);
  }
  const sauve = defilants.map(s => s.scrollTop);
  defilants.forEach(s => { s.scrollTop = bar.bas ? s.scrollHeight : 0; });
  let zone = bar.el.getBoundingClientRect();
  let u = { left: zone.left, top: zone.top, right: zone.right, bottom: zone.bottom };
  for (const d of bar.el.querySelectorAll('*')) {
    if (!visible(d)) continue;
    const r = d.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    u = { left: Math.min(u.left, r.left), top: Math.min(u.top, r.top), right: Math.max(u.right, r.right), bottom: Math.max(u.bottom, r.bottom) };
  }
  const apres = collecter();
  const vus = new Set();
  for (const it of apres) {
    if (bar.el.contains(it.el)) continue;
    if (it.marque) continue;
    if (cont && !cont.contains(it.el)) continue;
    let v = it.r;
    for (const c of it.clips) { v = inter(v, c.r); if (!v) break; }
    if (!v) continue;
    const z = inter(v, u);
    if (!z || z.width <= SEUIL || z.height <= SEUIL) continue;
    const cle = selecteur(it.el);
    if (vus.has(cle)) continue;
    vus.add(cle);
    defauts.push({ type: 'barre-recouvre', a: decrire(it), b: { sel: selecteur(bar.el), rect: rectDe(zone), texte: '', genre: 'barre' }, detail: 'au bout du défilement (' + (bar.bas ? 'bas' : 'haut') + '), ' + r1(z.height) + ' px du contenu sont sous la barre' });
  }
  defilants.forEach((s, i) => { s.scrollTop = sauve[i]; });
}

return JSON.stringify({ defauts, largeur: CW, barres: barres.length, items: items.length });
})()
"""


# ---------------------------------------------------------------- client WebSocket minimal (stdlib)
class Ws:
    def __init__(self, url, delai=60):
        u = urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=delai)
        cle = base64.b64encode(os.urandom(16)).decode()
        requete = (f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {cle}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.s.sendall(requete.encode())
        tete = b""
        while b"\r\n\r\n" not in tete:
            morceau = self.s.recv(4096)
            if not morceau:
                raise RuntimeError("poignée de main WebSocket refusée")
            tete += morceau
        if b" 101 " not in tete.split(b"\r\n")[0] + b" ":
            raise RuntimeError("poignée de main WebSocket refusée : " + tete.split(b"\r\n")[0].decode(errors="replace"))
        self.reste = tete.split(b"\r\n\r\n", 1)[1]

    def _lire(self, n):
        while len(self.reste) < n:
            morceau = self.s.recv(65536)
            if not morceau:
                raise RuntimeError("connexion DevTools fermée")
            self.reste += morceau
        donnees, self.reste = self.reste[:n], self.reste[n:]
        return donnees

    def envoyer(self, texte):
        charge = texte.encode("utf-8")
        tete = bytearray([0x81])
        n = len(charge)
        if n < 126:
            tete.append(0x80 | n)
        elif n < 65536:
            tete.append(0x80 | 126)
            tete += struct.pack(">H", n)
        else:
            tete.append(0x80 | 127)
            tete += struct.pack(">Q", n)
        masque = os.urandom(4)
        tete += masque
        corps = bytes(b ^ masque[i % 4] for i, b in enumerate(charge))
        self.s.sendall(bytes(tete) + corps)

    def recevoir(self):
        message = b""
        while True:
            b0, b1 = self._lire(2)
            fin, code = b0 & 0x80, b0 & 0x0F
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._lire(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._lire(8))[0]
            charge = self._lire(n)
            if code == 0x8:
                raise RuntimeError("connexion DevTools fermée par Chrome")
            if code == 0x9:
                continue
            if code in (0x0, 0x1, 0x2):
                message += charge
                if fin:
                    return message.decode("utf-8")

    def fermer(self):
        try:
            self.s.close()
        except OSError:
            pass


class Chrome:
    """Un Chrome sans fenêtre, une seule page pilotée par le protocole DevTools."""

    def __init__(self, chemin, dossier_profil):
        self.proc = subprocess.Popen(
            [chemin, "--headless=new", "--remote-debugging-port=0", "--remote-allow-origins=*",
             f"--user-data-dir={dossier_profil}", "--no-first-run", "--no-default-browser-check",
             "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1", "--disable-extensions",
             "--disable-renderer-backgrounding", "--disable-background-timer-throttling",
             "--allow-file-access-from-files", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        fichier = Path(dossier_profil) / "DevToolsActivePort"
        fin = time.time() + 30
        port = None
        while port is None:
            try:
                contenu = fichier.read_text().split()
                if contenu:
                    port = int(contenu[0])
                    break
            except (OSError, ValueError):
                pass  # fichier absent ou en cours d'écriture par Chrome
            if self.proc.poll() is not None or time.time() > fin:
                raise RuntimeError("Chrome ne démarre pas")
            time.sleep(0.1)
        cible = None
        while cible is None:
            if time.time() > fin:
                raise RuntimeError("aucune page DevTools disponible")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as rep:
                    for c in json.loads(rep.read()):
                        if c.get("type") == "page":
                            cible = c
                            break
            except OSError:
                pass
            if cible is None:
                time.sleep(0.1)
        self.ws = Ws(cible["webSocketDebuggerUrl"])
        self.n = 0
        self.evenements = []
        self.appeler("Page.enable")

    def appeler(self, methode, params=None, delai=60):
        self.n += 1
        ident = self.n
        self.ws.envoyer(json.dumps({"id": ident, "method": methode, "params": params or {}}))
        fin = time.time() + delai
        while True:
            if time.time() > fin:
                raise RuntimeError(f"délai dépassé : {methode}")
            msg = json.loads(self.ws.recevoir())
            if msg.get("id") == ident:
                if "error" in msg:
                    raise RuntimeError(f"{methode} : {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.evenements.append(msg["method"])

    def attendre_evenement(self, nom, delai=30):
        fin = time.time() + delai
        while nom not in self.evenements:
            if time.time() > fin:
                raise RuntimeError(f"délai dépassé : {nom}")
            msg = json.loads(self.ws.recevoir())
            if "method" in msg:
                self.evenements.append(msg["method"])
        self.evenements.remove(nom)

    def ouvrir(self, url):
        self.evenements.clear()
        self.appeler("Page.navigate", {"url": url})
        self.attendre_evenement("Page.loadEventFired")

    def evaluer(self, expression):
        res = self.appeler("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                                "returnByValue": True}, delai=90)
        if "exceptionDetails" in res:
            raise RuntimeError("erreur dans la page : " + json.dumps(res["exceptionDetails"], ensure_ascii=False)[:600])
        return res["result"].get("value")

    def configurer(self, largeur, theme):
        self.appeler("Emulation.setDeviceMetricsOverride", {
            "width": largeur, "height": HAUTEUR, "deviceScaleFactor": 1, "mobile": False})
        self.appeler("Emulation.setEmulatedMedia", {"media": "", "features": [
            {"name": "prefers-color-scheme", "value": "dark" if theme == "sombre" else "light"},
            {"name": "prefers-reduced-motion", "value": "reduce"}]})

    def capture(self, chemin):
        mesures = self.appeler("Page.getLayoutMetrics")
        taille = mesures.get("cssContentSize") or mesures.get("contentSize")
        clip = {"x": 0, "y": 0, "width": float(taille["width"]), "height": float(taille["height"]), "scale": 1}
        res = self.appeler("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True, "clip": clip})
        Path(chemin).write_bytes(base64.b64decode(res["data"]))

    def fermer(self):
        self.ws.fermer()
        if self.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self.proc.kill()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass


def trouver_chrome(indice=None):
    """Chemin de Chrome, ou None s'il est introuvable."""
    candidats = [indice, os.environ.get("CHROME"), CHROME_DEFAUT,
                 "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
                 shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chrome")]
    for c in candidats:
        if c and Path(c).is_file():
            return str(c)
    return None


def lister_pages(entrees):
    pages = []
    for e in entrees or [str(DOSSIER_PAGES)]:
        p = Path(e)
        if p.is_dir():
            pages += sorted(p.glob("*.html"))
        elif p.is_file():
            pages.append(p)
        else:
            raise FileNotFoundError(f"page introuvable : {e}")
    return pages


def dossier_profils():
    """Profils Chrome gardés d'une exécution à l'autre, hors du dépôt et hors du dossier temporaire."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".cache")
    return Path(base) / "verifier-mise-en-page"


def prendre_profil():
    """Réserve l'un des NB_PROFILS profils fixes et rend (dossier, fichier de verrou ouvert).

    Au premier démarrage d'un profil, Chrome teste sous Windows si le compte a un mot de passe vide, ce qui
    compte un échec de connexion. Un profil neuf par lancement finissait par verrouiller le compte Windows
    (seuil de 10 échecs). Les profils sont donc fixes et réutilisés, un verrou par profil pour les exécutions
    en parallèle (Chrome refuse deux instances sur le même profil). Le verrou tombe avec le processus."""
    base = dossier_profils()
    base.mkdir(parents=True, exist_ok=True)
    fin = time.time() + 300
    while True:
        for n in range(NB_PROFILS):
            fichier = open(base / f"profil-{n}.verrou", "a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fichier.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fichier.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fichier.close()
                continue
            profil = base / f"profil-{n}"
            profil.mkdir(exist_ok=True)
            try:
                (profil / "DevToolsActivePort").unlink()  # port d'un lancement précédent
            except FileNotFoundError:
                pass
            return profil, fichier
        if time.time() > fin:
            raise RuntimeError(f"aucun des {NB_PROFILS} profils Chrome n'est libre")
        time.sleep(1)


def verifier(pages, largeurs=LARGEURS, themes=THEMES, chrome=None, captures=None, cibles=CIBLES_PAR_DEFAUT):
    """Retourne la liste des défauts (dictionnaires). Lève RuntimeError si Chrome est introuvable."""
    exe = trouver_chrome(chrome)
    if not exe:
        raise RuntimeError("Chrome introuvable (option --chrome ou variable CHROME)")
    expression = SCRIPT_MESURE.replace("ARGS.cibles", json.dumps(cibles))
    profil, verrou = prendre_profil()
    defauts = []
    try:
        navigateur = Chrome(exe, profil)
    except BaseException:
        verrou.close()
        raise
    try:
        for page in pages:
            url = Path(page).resolve().as_uri()
            for largeur in largeurs:
                for theme in themes:
                    navigateur.configurer(largeur, theme)
                    navigateur.ouvrir(url)
                    brut = navigateur.evaluer(expression)
                    resultat = json.loads(brut)
                    if captures is not None:
                        navigateur.capture(Path(captures) / f"{Path(page).stem}-{largeur}-{theme}.png")
                    for d in resultat["defauts"]:
                        d.update(page=Path(page).name, largeur=largeur, theme=theme)
                        defauts.append(d)
    finally:
        navigateur.fermer()
        verrou.close()
    return defauts


def regrouper(defauts):
    """Un défaut qui se répète à plusieurs largeurs ou dans les deux thèmes n'est listé qu'une fois."""
    groupes = OrderedDict()
    for d in defauts:
        cle = (d["page"], d["type"], d["a"]["sel"], d["b"]["sel"] if d.get("b") else "")
        g = groupes.setdefault(cle, {"d": d, "combos": []})
        g["combos"].append(f"{d['largeur']} {d['theme']}")
    return list(groupes.values())


def formater(defauts):
    groupes = regrouper(defauts)
    lignes = []
    page = None
    for g in groupes:
        d = g["d"]
        if d["page"] != page:
            page = d["page"]
            lignes.append(page)
        lignes.append(f"  [{d['type']}] {d['detail']}")
        lignes.append(f"      en : {', '.join(g['combos'])}")
        a = d["a"]
        lignes.append(f"      A ({a['genre']}) {a['sel']}  {a['rect']}" + (f"  \"{a['texte']}\"" if a["texte"] else ""))
        if d.get("b"):
            b = d["b"]
            lignes.append(f"      B ({b['genre']}) {b['sel']}  {b['rect']}" + (f"  \"{b['texte']}\"" if b["texte"] else ""))
    return "\n".join(lignes)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Contrôle de mise en page de pages HTML statiques")
    ap.add_argument("pages", nargs="*", help="pages ou dossiers (défaut : docs/maquettes/client-web)")
    ap.add_argument("--largeurs", default=",".join(map(str, LARGEURS)))
    ap.add_argument("--themes", default=",".join(THEMES))
    ap.add_argument("--chrome", default=None)
    ap.add_argument("--cibles", default=CIBLES_PAR_DEFAUT,
                    help="portée du contrôle des cibles tactiles (sélecteur CSS, vide pour toute la page)")
    ap.add_argument("--captures", nargs="?", const="", default=None,
                    help="enregistre une capture par page, largeur et thème (dossier temporaire si omis)")
    ap.add_argument("--json", action="store_true", help="sortie JSON")
    args = ap.parse_args(argv)
    if not trouver_chrome(args.chrome):
        print("Chrome introuvable (option --chrome ou variable CHROME)", file=sys.stderr)
        return 2
    try:
        pages = lister_pages(args.pages)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2
    largeurs = [int(x) for x in args.largeurs.split(",") if x]
    themes = [x for x in args.themes.split(",") if x]
    dossier_captures = None
    if args.captures is not None:
        dossier_captures = Path(args.captures) if args.captures else Path(tempfile.mkdtemp(prefix="verifier-mise-en-page-captures-"))
        dossier_captures.mkdir(parents=True, exist_ok=True)
    debut = time.time()
    try:
        defauts = verifier(pages, largeurs, themes, args.chrome, dossier_captures, args.cibles)
    except RuntimeError as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(defauts, ensure_ascii=False, indent=1))
    else:
        if defauts:
            print(formater(defauts))
        total = len(regrouper(defauts))
        print(f"\n{len(pages)} pages, {len(largeurs)} largeurs, {len(themes)} thèmes, "
              f"{time.time() - debut:.0f} s : {total} défaut(s) distinct(s), {len(defauts)} occurrence(s).")
        if dossier_captures:
            print(f"captures : {dossier_captures}")
    return 1 if defauts else 0


if __name__ == "__main__":
    sys.exit(main())
