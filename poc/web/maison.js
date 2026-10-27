// Client web, Maison : une carte par pièce, les lampes, la télé, les mesures d'air et le volet de réglage (S-W4a).
// Le serveur décide de tout : les pièces visibles, les mesures, les mots (« chaud », « médiocre ») viennent de lui.
// Cette page n'envoie que des demandes de réglage {entite, action, valeur}. Le service Home Assistant est reconstruit
// et contrôlé par le serveur, jamais ici.
// Cadence : un réglage par entité et par famille toutes les 500 ms au plus, et 24 messages par 10 secondes au plus,
// sous la limite du serveur (30 par 10 secondes, au-delà il ferme la connexion).
// Aucun HTML construit par concaténation : createElement et textContent seulement (Trusted Types).
// Points d'accroche de S-W4b : voir « S-W4b » plus bas (vue 3D, sources et lecture de la télé, historique de l'air).
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var C = window.Client;
  var NS = "http:" + "//www.w3.org/2000/svg";   // espace de noms SVG, requis par createElementNS

  var INTERVALLE_REGLAGE_MS = 500;   // entre deux envois d'une même famille de réglage d'une même entité
  var FENETRE_MS = 10000;            // fenêtre du limiteur du serveur
  var MAX_FENETRE = 24;              // messages permis dans la fenêtre (le serveur en accepte 30)
  var SUIVI_RAPIDE_MS = 2000;        // relevé des états tant qu'un réglage attend sa lampe
  var SUIVI_LENT_MS = 15000;         // relevé des états au repos
  var ALERTE_DANGER = "#D6503A";     // couleur d'air « mauvais » envoyée par le serveur

  // Blancs nommés, filtrés sur les bornes de l'ampoule. Les couleurs de l'échantillon sont indicatives.
  var BLANCS = [
    { nom: "Bougie", k: 2200, hex: [255, 180, 94] },
    { nom: "Chaud", k: 2700, hex: [255, 207, 143] },
    { nom: "Neutre", k: 4000, hex: [247, 242, 230] },
    { nom: "Froid", k: 6000, hex: [201, 220, 255] }
  ];
  // Couleurs nommées : le nom en minuscules part au serveur, qui connaît la même table.
  var COULEURS = [
    { nom: "Rouge", h: 0 }, { nom: "Orange", h: 30 }, { nom: "Jaune", h: 55 }, { nom: "Vert", h: 120 },
    { nom: "Cyan", h: 180 }, { nom: "Bleu", h: 220 }, { nom: "Violet", h: 275 }, { nom: "Rose", h: 330 }
  ];
  var TOLERANCE_KELVIN = 100;        // pour marquer un blanc comme choisi
  var TOLERANCE_TEINTE = 8;

  var ws = null;
  var reconnexion = 0;
  var delai = null;
  var etats = null;                  // dernier message « etats » reçu
  var brouillons = {};               // entité -> ce que l'utilisateur vient de demander, affiché en attendant le vrai état
  var derniere = {};                 // entité -> {action, valeur, libelle} du dernier réglage demandé (Réessayer)
  var file = {};                     // clé -> {entite, action, valeur} en attente d'envoi (la dernière valeur gagne)
  var dernierEnvoi = {};             // clé -> instant du dernier envoi
  var attente = [];                  // entités des réglages envoyés dont la réponse n'est pas revenue (ordre d'envoi)
  var emissions = [];                // instants des derniers messages envoyés (limiteur)
  var minuteriePompe = null;
  var minuterieEtats = null;
  var dernierEtats = 0;
  var glisse = 0;                    // nombre de glisseurs en cours de glissement
  var erreurReglage = null;          // {entite, texte} du dernier refus
  var signatureListe = "";
  var signaturePied = "";
  var volet = null;                  // le volet ouvert, voir ouvrirVolet
  var compteur = 0;

  // ------------------------------------------------------------------ petits outils
  function el(balise, classe, texte) {
    var e = document.createElement(balise);
    if (classe) { e.className = classe; }
    if (texte !== undefined && texte !== null) { e.textContent = texte; }
    return e;
  }

  function vider(e) { while (e.firstChild) { e.removeChild(e.firstChild); } }

  function message(id, texte) {
    var e = $(id);
    e.textContent = texte || "";
    e.hidden = !texte;
  }

  function capitaliser(t) { return t ? t.charAt(0).toUpperCase() + t.slice(1) : t; }

  function arrondi(x) { return Math.floor(x + 0.5); }

  function borne(v, a, b) { return Math.max(a, Math.min(b, v)); }

  function envoyer(objet) {
    if (ws && ws.readyState === 1) { ws.send(JSON.stringify(objet)); return true; }
    return false;
  }

  function peutEmettre() {
    var t = Date.now();
    while (emissions.length && t - emissions[0] > FENETRE_MS) { emissions.shift(); }
    return emissions.length < MAX_FENETRE;
  }

  function emettre(objet) {
    if (!peutEmettre()) { return false; }
    if (!envoyer(objet)) { return false; }
    emissions.push(Date.now());
    return true;
  }

  function icone(nom) {
    var s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("class", "i");
    s.setAttribute("aria-hidden", "true");
    s.setAttribute("focusable", "false");
    function chemin(d) { var p = document.createElementNS(NS, "path"); p.setAttribute("d", d); s.appendChild(p); }
    if (nom === "alerte") { chemin("M12 4 2.8 20h18.4z"); chemin("M12 10v5M12 17.8v.2"); }
    else if (nom === "chevron") { chemin("m9 5 7 7-7 7"); }
    else if (nom === "fermer") { chemin("M6 6l12 12M18 6 6 18"); }
    else if (nom === "coche") { chemin("m5 12.5 4.5 4.5L19 7.5"); }
    else if (nom === "bouclier") { chemin("M12 3 4.5 6v5.5c0 4.5 3 8 7.5 9.5 4.5-1.5 7.5-5 7.5-9.5V6z"); }
    else if (nom === "tele") {
      var r = document.createElementNS(NS, "rect");
      r.setAttribute("x", "3"); r.setAttribute("y", "5"); r.setAttribute("width", "18"); r.setAttribute("height", "12");
      r.setAttribute("rx", "2");
      s.appendChild(r);
      chemin("M9 21h6M12 17v4");
    }
    return s;
  }

  // ------------------------------------------------------------------ couleurs et mots
  function ecartTeinte(a, b) {
    var d = Math.abs(a - b) % 360;
    return Math.min(d, 360 - d);
  }

  function nomTeinte(h) {
    var meilleur = COULEURS[0];
    COULEURS.forEach(function (c) { if (ecartTeinte(c.h, h) < ecartTeinte(meilleur.h, h)) { meilleur = c; } });
    return meilleur.nom.toLowerCase();
  }

  function motChaleur(k) {
    if (k < 2450) { return "bougie"; }
    if (k < 3300) { return "chaud"; }
    if (k < 4800) { return "neutre"; }
    return "froid";
  }

  // Couleur indicative d'un blanc, par interpolation entre les blancs nommés.
  function couleurKelvin(k) {
    var x = BLANCS[0], y = BLANCS[BLANCS.length - 1];
    if (k <= x.k) { return x.hex; }
    if (k >= y.k) { return y.hex; }
    for (var i = 0; i < BLANCS.length - 1; i++) {
      if (k >= BLANCS[i].k && k <= BLANCS[i + 1].k) { x = BLANCS[i]; y = BLANCS[i + 1]; break; }
    }
    var f = (k - x.k) / (y.k - x.k);
    return [0, 1, 2].map(function (j) { return Math.round(x.hex[j] + (y.hex[j] - x.hex[j]) * f); });
  }

  function rgb(c, facteur) {
    var f = facteur || 1;
    return "rgb(" + Math.round(c[0] * f) + "," + Math.round(c[1] * f) + "," + Math.round(c[2] * f) + ")";
  }

  function texteLampe(v) {
    if (!v.allumee) { return "Éteinte"; }
    var parties = [v.intensite !== null && v.intensite !== undefined ? v.intensite + " %" : "Allumée"];
    if (v.mode === "blanc" && v.kelvin) { parties.push(v.kelvin + " K", motChaleur(v.kelvin)); }
    else if (v.mode === "couleur" && v.teinte !== null && v.teinte !== undefined) { parties.push(nomTeinte(v.teinte)); }
    return parties.join(", ");
  }

  function texteTele(v) {
    if (!v.allumee) { return "Éteinte"; }
    return v.volume !== null && v.volume !== undefined ? "Allumée, volume " + v.volume + " %" : "Allumée";
  }

  // ------------------------------------------------------------------ états, brouillons
  function chercher(entite) {
    if (!etats) { return null; }
    for (var i = 0; i < etats.pieces.length; i++) {
      var p = etats.pieces[i];
      for (var j = 0; j < p.lumieres.length; j++) {
        if (p.lumieres[j].entite === entite) { return { type: "lampe", objet: p.lumieres[j], piece: p }; }
      }
      if (p.tele && p.tele.entite === entite) { return { type: "tele", objet: p.tele, piece: p }; }
    }
    return null;
  }

  // La vue affichée : l'état du serveur, recouvert par ce que l'utilisateur vient de demander tant que la lampe n'a pas suivi.
  function fusion(objet, type) {
    var b = brouillons[objet.entite];
    if (!b || objet.statut !== "ok") { return objet; }
    var v = {};
    Object.keys(objet).forEach(function (k) { v[k] = objet[k]; });
    v.allumee = b.allumee;
    if (type === "lampe") {
      if (b.intensite !== null && b.intensite !== undefined) { v.intensite = b.intensite; }
      if (b.mode) { v.mode = b.mode; v.kelvin = b.kelvin; v.teinte = b.teinte; }
      v.texte = texteLampe(v);
    } else {
      if (b.volume !== null && b.volume !== undefined) { v.volume = b.volume; }
      v.texte = texteTele(v);
    }
    return v;
  }

  function brouillonDe(trouve) {
    var o = trouve.objet;
    var b = brouillons[o.entite];
    if (!b) {
      b = { allumee: o.allumee, intensite: o.intensite, kelvin: o.kelvin, teinte: o.teinte, mode: o.mode,
            volume: o.volume, pendants: 0 };
      brouillons[o.entite] = b;
    }
    return b;
  }

  function dansFile(entite) {
    return Object.keys(file).some(function (c) { return file[c].entite === entite; });
  }

  function aEnAttente() {
    return !!etats && etats.pieces.some(function (p) {
      return p.lumieres.some(function (l) { return l.reglage === "en_attente"; });
    });
  }

  function famille(action) {
    if (action === "allumer" || action === "eteindre") { return "onoff"; }
    if (action === "blanc" || action === "couleur") { return "mode"; }
    return action;
  }

  function libelleAction(action, valeur) {
    if (action === "allumer") { return "Allumer"; }
    if (action === "eteindre") { return "Éteindre"; }
    if (action === "intensite") { return "Intensité " + valeur + " %"; }
    if (action === "volume") { return "Volume " + valeur + " %"; }
    if (action === "blanc") { return "Blanc " + valeur + " K, " + motChaleur(valeur); }
    if (action === "couleur") { return "Couleur " + (typeof valeur === "string" ? valeur : nomTeinte(valeur)); }
    return action;
  }

  function nomDe(entite) {
    var t = chercher(entite);
    return t ? t.objet.nom : "Cet appareil";
  }

  // ------------------------------------------------------------------ envoi des réglages
  function demander(entite, action, valeur) {
    var t = chercher(entite);
    if (!t) { return; }
    if (t.objet.statut !== "ok") { message("erreur-maison", nomDe(entite) + " ne répond pas."); return; }
    if (!ws || ws.readyState !== 1) {
      message("erreur-maison", "La connexion avec la maison est coupée. Nouvelle tentative.");
      return;
    }
    message("erreur-maison", "");
    erreurReglage = null;
    var b = brouillonDe(t);
    if (action === "allumer") { b.allumee = true; }
    else if (action === "eteindre") { b.allumee = false; }
    else if (action === "intensite") { b.allumee = true; b.intensite = valeur; }
    else if (action === "volume") { b.allumee = true; b.volume = valeur; }
    else if (action === "blanc") { b.allumee = true; b.mode = "blanc"; b.kelvin = valeur; b.teinte = null; }
    else if (action === "couleur") {
      var h = typeof valeur === "number" ? valeur : (COULEURS.filter(function (c) { return c.nom.toLowerCase() === valeur; })[0] || { h: 0 }).h;
      b.allumee = true; b.mode = "couleur"; b.teinte = h; b.kelvin = null;
    }
    derniere[entite] = { action: action, valeur: valeur, libelle: libelleAction(action, valeur) };
    var fam = famille(action);
    // Le dernier souhait l'emporte : un interrupteur annule les réglages en attente, un réglage annule un allumage ou
    // une extinction en attente (régler l'intensité allume de toute façon).
    Object.keys(file).forEach(function (c) {
      if (file[c].entite !== entite) { return; }
      if (fam === "onoff" || file[c].fam === "onoff") { delete file[c]; }
    });
    file[entite + "|" + fam] = { entite: entite, action: action, valeur: valeur, fam: fam };
    planifierPompe();
    afficher();
  }

  function planifierPompe() {
    if (minuteriePompe) { clearTimeout(minuteriePompe); }
    minuteriePompe = setTimeout(pomper, 0);
  }

  function pomper() {
    minuteriePompe = null;
    var maintenant = Date.now();
    var prochain = null;
    Object.keys(file).forEach(function (cle) {
      var r = file[cle];
      var reste = (dernierEnvoi[cle] || 0) + INTERVALLE_REGLAGE_MS - maintenant;
      if (reste <= 0 && peutEmettre()) {
        var m = { type: "regler", entite: r.entite, action: r.action, essai: false };
        if (r.valeur !== undefined && r.valeur !== null) { m.valeur = r.valeur; }
        delete file[cle];
        dernierEnvoi[cle] = maintenant;
        if (emettre(m)) {
          attente.push(r.entite);
          if (brouillons[r.entite]) { brouillons[r.entite].pendants += 1; }
        }
      } else {
        var a = reste > 0 ? reste : 250;
        prochain = prochain === null ? a : Math.min(prochain, a);
      }
    });
    if (prochain !== null) { minuteriePompe = setTimeout(pomper, prochain); }
  }

  // ------------------------------------------------------------------ relevé des états
  function demanderEtats() {
    if (!ws || ws.readyState !== 1) { return; }
    if (Date.now() - dernierEtats < 700) { planifierEtats(700); return; }
    if (emettre({ type: "etats" })) { dernierEtats = Date.now(); }
    else { planifierEtats(1000); }
  }

  function planifierEtats(duree) {
    if (minuterieEtats) { clearTimeout(minuterieEtats); }
    minuterieEtats = setTimeout(function () {
      minuterieEtats = null;
      if (document.hidden) { planifierEtats(SUIVI_LENT_MS); return; }
      if (glisse > 0) { planifierEtats(1000); return; }
      demanderEtats();
      // Si la réponse se perd, le relevé reprend quand même. La réponse reprogramme une échéance plus juste.
      if (!minuterieEtats) { planifierEtats(SUIVI_LENT_MS); }
    }, duree);
  }

  function appliquerEtats(m) {
    if (!Array.isArray(m.pieces)) { return; }
    etats = m;
    Object.keys(brouillons).forEach(function (entite) {
      var b = brouillons[entite];
      var t = chercher(entite);
      if (!t) { delete brouillons[entite]; return; }
      var attend = t.objet.reglage === "en_attente";
      if (b.pendants <= 0 && !dansFile(entite) && glisse === 0 && !attend) { delete brouillons[entite]; }
    });
    $("bandeau-essai").hidden = !m.essai;
    $("statut-maison").hidden = true;
    planifierEtats(aEnAttente() ? SUIVI_RAPIDE_MS : SUIVI_LENT_MS);
    afficher();
  }

  // ------------------------------------------------------------------ refus
  // « droit » et d'autres causes ont ici un autre sens que dans Réglages, d'où une table à part.
  var REFUS = {
    droit: "Ce navigateur n'a pas le droit de régler la maison.",
    format: "Le réglage n'est pas compris. Rechargez la page.",
    entite: "Cet appareil n'est plus réglable depuis ici.",
    action: "Ce réglage n'existe pas pour cet appareil.",
    valeur: "Cette valeur n'est pas permise pour cet appareil.",
    protegee: "Pièce protégée : aucun réglage n'est possible ici.",
    securite: "Ce réglage est refusé par les règles de sécurité de la maison.",
    indisponible: "La maison ne répond pas pour le moment."
  };

  function texteRefus(cause, entite) {
    if (cause === "injoignable") { return nomDe(entite) + " ne répond pas."; }
    return REFUS[cause] || C.texteErreur(cause);
  }

  function finReglage(entite) {
    var b = brouillons[entite];
    if (!b) { return; }
    b.pendants = Math.max(0, b.pendants - 1);
  }

  function recu(m) {
    if (m.type === "etats") {
      if (!erreurReglage) { message("erreur-maison", ""); }
      appliquerEtats(m);
    } else if (m.type === "regle") {
      var e = attente.shift() || m.entite;
      finReglage(e);
      if (m.statut === "essai" && brouillons[e] && brouillons[e].pendants <= 0 && !dansFile(e)) { delete brouillons[e]; }
      erreurReglage = null;
      planifierEtats(300);
      afficher();
    } else if (m.type === "erreur") {
      if (m.genre === "regler") {
        var x = attente.shift() || m.entite;
        finReglage(x);
        var b = brouillons[x];
        if (b && b.pendants <= 0 && !dansFile(x)) { delete brouillons[x]; }
        var texte = texteRefus(m.cause, x);
        erreurReglage = { entite: x, texte: texte };
        message("erreur-maison", texte);
        planifierEtats(300);
        afficher();
      } else if (m.genre === "etats") {
        message("erreur-maison", texteRefus(m.cause, ""));
      }
    }
  }

  // ------------------------------------------------------------------ liste des pièces
  function sphere(v) {
    var s = el("span", "sphere");
    s.setAttribute("aria-hidden", "true");
    habillerSphere(s, v);
    return s;
  }

  function habillerSphere(s, v) {
    ["--t", "--t2", "--lumiere-vif", "--lumiere-profond"].forEach(function (p) { s.style.removeProperty(p); });
    var c = "sphere";
    if (!v.allumee) { c += " sphere--eteinte"; }
    else if (v.mode === "couleur" && v.teinte !== null && v.teinte !== undefined) {
      c += " sphere--teinte";
      s.style.setProperty("--t", "hsl(" + v.teinte + ",75%,58%)");
      s.style.setProperty("--t2", "hsl(" + v.teinte + ",70%,38%)");
    } else if (v.mode === "blanc" && v.kelvin) {
      var k = couleurKelvin(v.kelvin);
      s.style.setProperty("--lumiere-vif", rgb(k, 1));
      s.style.setProperty("--lumiere-profond", rgb(k, 0.74));
    }
    s.className = c;
  }

  function commutateur(objet, cle) {
    var b = el("button", "commutateur");
    b.type = "button";
    b.setAttribute("role", "switch");
    b.setAttribute("aria-checked", objet.allumee ? "true" : "false");
    b.dataset.cle = cle;
    var injoignable = objet.statut !== "ok";
    b.setAttribute("aria-label", objet.nom + (injoignable ? ", injoignable" : ""));
    if (injoignable) { b.setAttribute("aria-disabled", "true"); }
    b.appendChild(el("span", "interrupteur"));
    b.addEventListener("click", function () {
      if (injoignable) { message("erreur-maison", objet.nom + " ne répond pas."); return; }
      demander(objet.entite, objet.allumee ? "eteindre" : "allumer");
    });
    return b;
  }

  function chevron(objet, type) {
    var b = el("button", "lampe-ouvrir");
    b.type = "button";
    b.dataset.cle = "ouvrir:" + objet.entite;
    b.setAttribute("aria-label", "Régler " + objet.nom);
    b.setAttribute("aria-haspopup", "dialog");
    b.setAttribute("aria-expanded", volet && volet.entite === objet.entite ? "true" : "false");
    b.appendChild(icone("chevron"));
    b.addEventListener("click", function () { ouvrirVolet(objet.entite, type, b.dataset.cle); });
    return b;
  }

  function ligneLampe(l) {
    var ouverte = !!volet && volet.entite === l.entite;
    var r = el("div", "lampe" + (ouverte ? " lampe--ouverte" : ""));
    r.appendChild(sphere(l));
    var t = el("div", "texte");
    t.appendChild(el("b", null, l.nom));
    var s = el("span");
    if (l.statut !== "ok") { s.appendChild(icone("alerte")); s.appendChild(document.createTextNode("Injoignable")); }
    else if (l.reglage === "non_applique") { s.appendChild(icone("alerte")); s.appendChild(document.createTextNode("Réglage non appliqué")); }
    else if (l.reglage === "en_attente") { s.appendChild(document.createTextNode("En attente de la lampe")); }
    else { s.appendChild(document.createTextNode(l.texte)); }
    t.appendChild(s);
    r.appendChild(t);
    r.appendChild(commutateur(l, "commut:" + l.entite));
    if (l.statut === "ok" && l.reglable) { r.appendChild(chevron(l, "lampe")); }
    return r;
  }

  function ligneTele(tv) {
    var r = el("div", "rangee");
    var puce = el("span", "puce puce--assistant");
    puce.appendChild(icone("tele"));
    r.appendChild(puce);
    var t = el("div", "texte");
    t.appendChild(el("b", null, tv.nom));
    var s = el("span");
    if (tv.statut !== "ok") { s.appendChild(icone("alerte")); s.appendChild(document.createTextNode("Injoignable")); }
    else { s.appendChild(document.createTextNode(tv.texte)); }
    t.appendChild(s);
    r.appendChild(t);
    r.appendChild(commutateur(tv, "commut:" + tv.entite));
    if (tv.statut === "ok") { r.appendChild(chevron(tv, "tele")); }
    return r;
  }

  function mesure(classe, avant, gras, apres) {
    var li = el("li", "mesure" + (classe ? " mesure--" + classe : ""));
    if (avant) { li.appendChild(document.createTextNode(avant)); }
    if (gras) { li.appendChild(el("b", null, gras)); }
    if (apres) { li.appendChild(document.createTextNode(apres)); }
    return li;
  }

  var CLASSE_AIR = { "bon": "bon", "correct": "correct", "médiocre": "mediocre", "mauvais": "mauvais" };
  var CLASSE_TEMP = { "frais": "frais", "agréable": "agreable", "chaud": "chaud" };

  // Mesures en lecture seule, toujours avec un mot. Une mesure absente ou un capteur absent le disent en toutes lettres.
  function mesuresDe(m) {
    var ul = el("ul", "mesures");
    ul.setAttribute("aria-label", "Mesures de la pièce");
    var wrapper = m.statut === "aucun" || (m.statut === "absente" && !("temperature" in m));
    if (wrapper) {
      ul.appendChild(mesure(m.statut === "aucun" ? "aucune" : "absente", capitaliser(m.texte || "Mesures indisponibles"), null, null));
      return ul;
    }
    var t = m.temperature;
    if (t && typeof t.valeur === "number") {
      ul.appendChild(mesure(CLASSE_TEMP[t.mot] || "", "Température ", arrondi(t.valeur) + "°", t.mot ? ", " + t.mot : ""));
    } else if (t) {
      ul.appendChild(mesure("absente", "Température absente" + (t.depuis ? " depuis " + t.depuis : ""), null, null));
    } else {
      ul.appendChild(mesure("aucune", "Pas de thermomètre", null, null));
    }
    var h = m.humidite;
    if (h && typeof h.valeur === "number") {
      ul.appendChild(mesure("", "Humidité ", arrondi(h.valeur) + " %", null));
    } else if (h) {
      ul.appendChild(mesure("absente", "Humidité absente" + (h.depuis ? " depuis " + h.depuis : ""), null, null));
    }
    var airVu = false;
    [["co2", "CO2", "ppm"], ["pm25", "PM2,5", "µg/m3"]].forEach(function (g) {
      var x = m[g[0]];
      if (!x) { return; }
      airVu = true;
      if (typeof x.valeur === "number") {
        ul.appendChild(mesure(CLASSE_AIR[x.mot] || "", g[1] + " ", arrondi(x.valeur) + " " + g[2], x.mot ? ", " + x.mot : ""));
      } else {
        ul.appendChild(mesure("absente", g[1] + " absent" + (x.depuis ? " depuis " + x.depuis : ""), null, null));
      }
    });
    if (!airVu) { ul.appendChild(mesure("aucune", "Pas de capteur d'air", null, null)); }
    return ul;
  }

  function carte(p, indice) {
    var s = el("section", "carte carte--vide piece");
    s.setAttribute("aria-label", p.nom);
    if (p.protegee) {
      var pr = el("div", "piece-protegee");
      var puce = el("span", "puce");
      puce.appendChild(icone("bouclier"));
      pr.appendChild(puce);
      var tp = el("div", "texte");
      tp.appendChild(el("b", null, p.nom));
      tp.appendChild(el("span", null, "Pièce protégée"));
      pr.appendChild(tp);
      s.appendChild(pr);
      return s;
    }
    var tete = el("div", "piece-tete");
    var h = el("h2", null, p.nom);
    tete.appendChild(h);
    var lampes = p.lumieres.map(function (l) { return fusion(l, "lampe"); });
    var allumees = lampes.filter(function (l) { return l.allumee; }).length;
    if (lampes.length) {
      tete.appendChild(el("span", "secondaire", allumees === 0 ? "Tout éteint" : allumees + (allumees > 1 ? " allumées" : " allumée")));
    }
    s.appendChild(tete);
    if (p.mesures) { s.appendChild(mesuresDe(p.mesures)); }
    if (p.tele) { s.appendChild(ligneTele(fusion(p.tele, "tele"))); }
    lampes.forEach(function (l) { s.appendChild(ligneLampe(l)); });
    if (!lampes.length && !p.tele && !p.mesures) {
      var rien = el("div", "piece-protegee");
      var tr = el("div", "texte");
      tr.appendChild(el("span", null, "Rien à régler ici depuis ce navigateur."));
      rien.appendChild(tr);
      s.appendChild(rien);
    }
    return s;
  }

  function alerteIcone(classe, texte, role, gras) {
    var a = el("div", "alerte alerte--icone " + classe);
    a.setAttribute("role", role);
    a.appendChild(icone("alerte"));
    var d = el("div");
    if (gras) { d.appendChild(el("b", null, texte)); }
    else { d.appendChild(document.createTextNode(texte)); }
    a.appendChild(d);
    return a;
  }

  function afficherListe() {
    if (!etats) { return; }
    var pieces = etats.pieces.map(function (p) {
      return { p: p, l: p.lumieres.map(function (l) { return fusion(l, "lampe"); }), t: p.tele ? fusion(p.tele, "tele") : null };
    });
    var signature = JSON.stringify([pieces, etats.alertes, etats.configure, etats.lu_a, etats.mesures_visibles,
      volet ? volet.entite : null]);
    if (signature === signatureListe) { return; }
    signatureListe = signature;
    var focus = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.cle : null;

    var alertes = $("alertes-air");
    vider(alertes);
    (etats.alertes || []).forEach(function (a) {
      var danger = a.couleur === ALERTE_DANGER;
      alertes.appendChild(alerteIcone(danger ? "alerte--danger" : "alerte--air", String(a.texte || ""), danger ? "alert" : "status", true));
    });
    alertes.hidden = !alertes.firstChild;

    var liste = $("liste-pieces");
    vider(liste);
    etats.pieces.forEach(function (p, i) { liste.appendChild(carte(p, i)); });

    var vide = !etats.configure || etats.pieces.length === 0;
    $("carte-vide").hidden = !vide;
    if (vide) {
      $("texte-vide").textContent = !etats.configure
        ? "Aucune pièce n'est configurée pour cette maison."
        : "Ce navigateur n'a accès à aucune pièce.";
    }
    var lu = $("lu-a");
    var heure = typeof etats.lu_a === "string" && etats.lu_a.length >= 16 ? etats.lu_a.slice(11, 16) : "";
    lu.textContent = etats.mesures_visibles && heure ? "Mesures lues à " + heure + "." : "";
    lu.hidden = !lu.textContent;

    if (focus) {
      var cibles = liste.querySelectorAll("[data-cle]");
      for (var i = 0; i < cibles.length; i++) {
        if (cibles[i].dataset.cle === focus) { cibles[i].focus({ preventScroll: true }); break; }
      }
    }
  }

  function afficher() {
    afficherListe();
    majVolet();
  }

  // ------------------------------------------------------------------ glisseur
  // Un curseur à pointeur et clavier. onChange(v, final) est appelé pendant le glissement (final faux) puis au relâchement.
  function creerGlisseur(o) {
    compteur += 1;
    var id = "gl" + compteur;
    var racine = el("div", "reglage");
    var tete = el("div", "reglage-tete");
    var lib = el("span", "etiquette", o.etiquette);
    lib.id = id + "-lib";
    var val = el("span", "valeur-reglage");
    tete.appendChild(lib);
    tete.appendChild(val);
    racine.appendChild(tete);
    var g = el("div", "glisseur" + (o.classe ? " " + o.classe : ""));
    g.setAttribute("role", "slider");
    g.tabIndex = 0;
    g.setAttribute("aria-labelledby", id + "-lib");
    g.setAttribute("aria-valuemin", String(o.min));
    g.setAttribute("aria-valuemax", String(o.max));
    var pouce = el("span", "pouce");
    if (o.rempli) { g.appendChild(el("span", "rempli")); }
    g.appendChild(pouce);
    racine.appendChild(g);
    if (o.bornes) {
      var b = el("div", "bornes");
      o.bornes.forEach(function (t) { b.appendChild(el("span", null, t)); });
      racine.appendChild(b);
    }
    var pas = o.pas || 1;
    var pasClavier = Math.max(pas, Math.round((o.max - o.min) * 0.05 / pas) * pas);
    var s = { racine: racine, valeur: null, glisse: false, inactif: false };

    function caler(v) { return borne(Math.round((v - o.min) / pas) * pas + o.min, o.min, o.max); }
    function poser(v) {
      var vide = v === null || v === undefined;
      var x = vide ? o.min : caler(v);
      s.valeur = x;
      g.style.setProperty("--p", ((x - o.min) / (o.max - o.min) * 100) + "%");
      g.setAttribute("aria-valuenow", String(x));
      var t = o.texte(vide ? null : x);
      g.setAttribute("aria-valuetext", o.parole ? o.parole(vide ? null : x) : t);
      val.textContent = t;
    }
    s.maj = function (v) { if (!s.glisse) { poser(v); } };
    s.desactiver = function (oui) {
      s.inactif = oui;
      if (oui) { g.setAttribute("aria-disabled", "true"); } else { g.removeAttribute("aria-disabled"); }
    };
    function depuis(ev, final) {
      var r = g.getBoundingClientRect();
      var f = r.width > 0 ? borne((ev.clientX - r.left) / r.width, 0, 1) : 0;
      var v = caler(o.min + f * (o.max - o.min));
      var change = v !== s.valeur;
      poser(v);
      if (change || final) { o.onChange(v, final); }
    }
    function fin(ev) {
      if (!s.glisse) { return; }
      s.glisse = false;
      glisse = Math.max(0, glisse - 1);
      depuis(ev, true);
      planifierEtats(300);
    }
    g.addEventListener("pointerdown", function (ev) {
      if (s.inactif || (ev.pointerType === "mouse" && ev.button !== 0)) { return; }
      ev.preventDefault();
      try { g.setPointerCapture(ev.pointerId); } catch (x) { /* capture refusée : le glissement reste possible sur le curseur */ }
      g.focus({ preventScroll: true });
      s.glisse = true;
      glisse += 1;
      depuis(ev, false);
    });
    g.addEventListener("pointermove", function (ev) { if (s.glisse) { depuis(ev, false); } });
    g.addEventListener("pointerup", fin);
    g.addEventListener("pointercancel", fin);
    g.addEventListener("keydown", function (ev) {
      if (s.inactif) { return; }
      var v = s.valeur;
      var k = ev.key;
      if (k === "ArrowRight" || k === "ArrowUp") { v += pasClavier; }
      else if (k === "ArrowLeft" || k === "ArrowDown") { v -= pasClavier; }
      else if (k === "PageUp") { v += pasClavier * 2; }
      else if (k === "PageDown") { v -= pasClavier * 2; }
      else if (k === "Home") { v = o.min; }
      else if (k === "End") { v = o.max; }
      else { return; }
      ev.preventDefault();
      v = caler(v);
      if (v === s.valeur) { return; }
      poser(v);
      o.onChange(v, true);
    });
    poser(o.valeur);
    return s;
  }

  // ------------------------------------------------------------------ volet de réglage
  // S-W4b : la vue 3D (iframe isolée), les sources et la lecture de la télé et l'historique de l'air se brancheront ici,
  // dans le corps du volet (volet.corps) et dans la carte de la pièce. Rien de cela n'est présent en S-W4a.
  function ouvrirVolet(entite, type, cle) {
    if (volet) { fermerVolet(false); }
    var t = chercher(entite);
    if (!t) { return; }
    var o = t.objet;
    var voile = el("div", "voile");
    voile.setAttribute("data-superposition-voulue", "voile de la feuille");
    var feuille = el("div", "feuille");
    feuille.setAttribute("role", "dialog");
    feuille.setAttribute("aria-modal", "true");
    feuille.setAttribute("data-superposition-voulue", "feuille modale");
    compteur += 1;
    var idTitre = "volet-titre-" + compteur;
    feuille.setAttribute("aria-labelledby", idTitre);
    feuille.appendChild(el("div", "poignee"));

    var tete = el("div", "volet-tete");
    var marque;
    if (type === "lampe") { marque = sphere(o); }
    else { marque = el("span", "puce puce--assistant"); marque.appendChild(icone("tele")); }
    tete.appendChild(marque);
    var texte = el("div", "texte");
    var titre = el("h2", null, o.nom);
    titre.id = idTitre;
    var sous = el("p");
    texte.appendChild(titre);
    texte.appendChild(sous);
    tete.appendChild(texte);
    var fermer = el("button", "fermer");
    fermer.type = "button";
    fermer.setAttribute("aria-label", "Fermer");
    fermer.appendChild(icone("fermer"));
    tete.appendChild(fermer);
    feuille.appendChild(tete);

    var corps = el("div", "volet-corps");
    feuille.appendChild(corps);
    var pied = el("div", "volet-pied");
    feuille.appendChild(pied);

    volet = { entite: entite, type: type, cle: cle, voile: voile, feuille: feuille, corps: corps, pied: pied, marque: marque,
              sous: sous, titre: titre, glisseurs: {}, choix: [], onglets: null, panneaux: {}, onglet: null };
    if (type === "lampe") { construireLampe(o); } else { construireTele(); }

    $("volet-maison").appendChild(voile);
    $("volet-maison").appendChild(feuille);
    $("contenu-maison").setAttribute("inert", "");
    $("contenu-maison").setAttribute("aria-hidden", "true");
    voile.addEventListener("click", function () { fermerVolet(true); });
    fermer.addEventListener("click", function () { fermerVolet(true); });
    feuille.addEventListener("keydown", clavierVolet);
    signaturePied = "";
    signatureListe = "";
    afficher();
    fermer.focus({ preventScroll: true });
  }

  function fermerVolet(rendreFocus) {
    if (!volet) { return; }
    var cle = volet.cle;
    vider($("volet-maison"));
    $("contenu-maison").removeAttribute("inert");
    $("contenu-maison").removeAttribute("aria-hidden");
    volet = null;
    signatureListe = "";
    afficher();
    if (rendreFocus && cle) {
      var cibles = $("liste-pieces").querySelectorAll("[data-cle]");
      for (var i = 0; i < cibles.length; i++) {
        if (cibles[i].dataset.cle === cle) { cibles[i].focus({ preventScroll: true }); break; }
      }
    }
  }

  function clavierVolet(ev) {
    if (ev.key === "Escape") { ev.preventDefault(); fermerVolet(true); return; }
    if (ev.key !== "Tab" || !volet) { return; }
    var tous = volet.feuille.querySelectorAll("button, [tabindex='0']");
    var visibles = [];
    for (var i = 0; i < tous.length; i++) { if (tous[i].offsetParent !== null) { visibles.push(tous[i]); } }
    if (!visibles.length) { return; }
    var premier = visibles[0], dernier = visibles[visibles.length - 1];
    if (ev.shiftKey && document.activeElement === premier) { ev.preventDefault(); dernier.focus(); }
    else if (!ev.shiftKey && document.activeElement === dernier) { ev.preventDefault(); premier.focus(); }
  }

  function choisir(onglet) {
    if (!volet || !volet.onglets) { return; }
    volet.onglet = onglet;
    Object.keys(volet.panneaux).forEach(function (n) { volet.panneaux[n].hidden = n !== onglet; });
    Object.keys(volet.onglets).forEach(function (n) {
      volet.onglets[n].setAttribute("aria-selected", n === onglet ? "true" : "false");
      volet.onglets[n].tabIndex = n === onglet ? 0 : -1;
    });
  }

  function construireLampe(o) {
    var peutBlanc = !!o.blanc, peutCouleur = !!o.couleur;
    var entite = o.entite;
    var kmin = o.kmin || 2700, kmax = o.kmax || 6500;

    function intensite() {
      var gl = creerGlisseur({
        etiquette: "Intensité", min: 1, max: 100, pas: 1, rempli: true,
        texte: function (v) { return v === null ? "Éteinte" : v + " %"; },
        parole: function (v) { return v === null ? "Éteinte" : v + " pour cent"; },
        valeur: 100,
        onChange: function (v) { demander(entite, "intensite", v); }
      });
      volet.glisseurs["intensite" + Object.keys(volet.glisseurs).length] = gl;
      return gl;
    }

    function blancs() {
      var bloc = el("div", "reglage");
      bloc.appendChild(el("span", "etiquette", "Blancs"));
      var grille = el("div", "choix-grille");
      BLANCS.filter(function (b) { return b.k >= kmin && b.k <= kmax; }).forEach(function (b) {
        var bt = el("button", "choix-volet");
        bt.type = "button";
        var e = el("span", "echantillon");
        e.style.setProperty("--t", rgb(b.hex, 1));
        bt.appendChild(e);
        bt.appendChild(el("b", null, b.nom));
        bt.appendChild(el("small", null, b.k + " K"));
        bt.setAttribute("aria-pressed", "false");
        bt.addEventListener("click", function () { demander(entite, "blanc", b.k); });
        grille.appendChild(bt);
        volet.choix.push({ bouton: bt, test: function (v) { return v.mode === "blanc" && v.kelvin && Math.abs(v.kelvin - b.k) <= TOLERANCE_KELVIN; } });
      });
      bloc.appendChild(grille);
      return bloc;
    }

    function chaleur() {
      var gl = creerGlisseur({
        etiquette: "Chaleur du blanc", min: kmin, max: kmax, pas: 50, classe: "glisseur--chaleur",
        texte: function (v) { return v === null ? "Pas en blanc" : v + " K, " + motChaleur(v); },
        valeur: null,
        bornes: [kmin + " K", "Bornes de cette ampoule", kmax + " K"],
        onChange: function (v) { demander(entite, "blanc", v); }
      });
      volet.glisseurs.chaleur = gl;
      return gl;
    }

    function couleurs() {
      var bloc = el("div", "reglage");
      bloc.appendChild(el("span", "etiquette", "Couleurs"));
      var grille = el("div", "choix-grille");
      COULEURS.forEach(function (c) {
        var bt = el("button", "choix-volet");
        bt.type = "button";
        var e = el("span", "echantillon");
        e.style.setProperty("--t", "hsl(" + c.h + ",75%,58%)");
        bt.appendChild(e);
        bt.appendChild(el("b", null, c.nom));
        bt.setAttribute("aria-pressed", "false");
        bt.addEventListener("click", function () { demander(entite, "couleur", c.nom.toLowerCase()); });
        grille.appendChild(bt);
        volet.choix.push({ bouton: bt, test: function (v) { return v.mode === "couleur" && v.teinte !== null && v.teinte !== undefined && ecartTeinte(v.teinte, c.h) <= TOLERANCE_TEINTE; } });
      });
      bloc.appendChild(grille);
      return bloc;
    }

    function bande() {
      var gl = creerGlisseur({
        etiquette: "Teinte", min: 0, max: 360, pas: 1, classe: "glisseur--teinte",
        texte: function (v) { return v === null ? "Pas en couleur" : nomTeinte(v); },
        valeur: null,
        onChange: function (v) { demander(entite, "couleur", v === 360 ? 0 : v); }
      });
      volet.glisseurs.teinte = gl;
      return gl;
    }

    var corps = volet.corps;
    if (peutBlanc && peutCouleur) {
      var barre = el("div", "segments");
      barre.setAttribute("role", "tablist");
      barre.setAttribute("aria-label", "Type de réglage");
      volet.onglets = {};
      [["blanc", "Blanc"], ["couleur", "Couleur"]].forEach(function (d) {
        var bt = el("button", "segment", d[1]);
        bt.type = "button";
        bt.setAttribute("role", "tab");
        bt.id = "onglet-" + d[0];
        bt.setAttribute("aria-controls", "panneau-" + d[0]);
        bt.addEventListener("click", function () { choisir(d[0]); });
        bt.addEventListener("keydown", function (ev) {
          if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
            ev.preventDefault();
            var autre = d[0] === "blanc" ? "couleur" : "blanc";
            choisir(autre);
            volet.onglets[autre].focus();
          }
        });
        barre.appendChild(bt);
        volet.onglets[d[0]] = bt;
      });
      corps.appendChild(barre);
    }
    function panneau(nom) {
      var p = el("div", "panneau");
      p.id = "panneau-" + nom;
      if (volet.onglets) { p.setAttribute("role", "tabpanel"); p.setAttribute("aria-labelledby", "onglet-" + nom); }
      volet.panneaux[nom] = p;
      corps.appendChild(p);
      return p;
    }
    if (peutBlanc) {
      var pb = panneau("blanc");
      pb.appendChild(intensite().racine);
      pb.appendChild(blancs());
      pb.appendChild(chaleur().racine);
    }
    if (peutCouleur) {
      var pc = panneau("couleur");
      pc.appendChild(intensite().racine);
      pc.appendChild(couleurs());
      pc.appendChild(bande().racine);
    }
    if (!peutBlanc && !peutCouleur) {
      panneau("intensite").appendChild(intensite().racine);
    }
    if (volet.onglets) { choisir(o.mode === "couleur" ? "couleur" : "blanc"); }
  }

  // S-W4b : sources et lecture de la télé. En S-W4a, seul le volume se règle, l'allumage et l'extinction sont sur la ligne.
  function construireTele() {
    var entite = volet.entite;
    var gl = creerGlisseur({
      etiquette: "Volume", min: 0, max: 100, pas: 1, rempli: true,
      texte: function (v) { return v === null ? "Inconnu" : v + " %"; },
      parole: function (v) { return v === null ? "Inconnu" : v + " pour cent"; },
      valeur: null,
      onChange: function (v) { demander(entite, "volume", v); }
    });
    volet.glisseurs.volume = gl;
    volet.corps.appendChild(gl.racine);
    var eteinte = el("p", "secondaire", "Allumez la télé pour régler le volume.");
    volet.corps.appendChild(eteinte);
    volet.eteinte = eteinte;
  }

  function pied(v, type) {
    var noeuds = [];
    if (erreurReglage && erreurReglage.entite === v.entite) {
      noeuds.push(alerteIcone("alerte--danger", erreurReglage.texte, "alert", false));
    }
    if (v.statut !== "ok") {
      noeuds.push(alerteIcone("alerte--danger", v.nom + " ne répond pas. Les réglages reprendront quand "
        + (type === "lampe" ? "la lampe" : "la télé") + " sera de nouveau joignable.", "alert", false));
    } else if (v.reglage === "en_attente") {
      var a = el("div", "alerte alerte--info");
      a.setAttribute("role", "status");
      var d = derniere[v.entite];
      var attendu = etats && typeof etats.attente_s === "number" ? etats.attente_s : 5;
      a.appendChild(document.createTextNode((d ? "Demandé : " + d.libelle + ". " : "") + v.nom
        + " n'a pas encore répondu. Sans réponse dans " + attendu + " s, le réglage sera signalé comme non appliqué."));
      noeuds.push(a);
    } else if (v.reglage === "non_applique") {
      var d2 = derniere[v.entite];
      var al = alerteIcone("alerte--danger", v.nom + " n'a pas appliqué le réglage. " + (d2 ? "Demandé : " + d2.libelle + ". " : "")
        + "La lampe affiche : " + v.texte + ".", "alert", false);
      if (d2) {
        var re = el("button", "bouton", "Réessayer");
        re.type = "button";
        re.addEventListener("click", function () { demander(v.entite, d2.action, d2.valeur); });
        al.lastChild.appendChild(re);
      }
      noeuds.push(al);
    }
    return noeuds;
  }

  function majVolet() {
    if (!volet) { return; }
    var t = chercher(volet.entite);
    if (!t) { fermerVolet(false); return; }
    var v = fusion(t.objet, t.type);
    volet.titre.textContent = v.nom;
    volet.sous.textContent = v.statut !== "ok" ? "Injoignable" : v.texte;
    var actif = v.statut === "ok";
    if (t.type === "lampe") {
      habillerSphere(volet.marque, v);
      if (volet.glisseurs) {
        Object.keys(volet.glisseurs).forEach(function (n) {
          var g = volet.glisseurs[n];
          g.desactiver(!actif);
          if (n.indexOf("intensite") === 0) { g.maj(v.allumee && v.intensite ? v.intensite : (v.intensite || 100)); }
          else if (n === "chaleur") { g.maj(v.mode === "blanc" && v.kelvin ? v.kelvin : null); }
          else if (n === "teinte") { g.maj(v.mode === "couleur" && v.teinte !== null && v.teinte !== undefined ? v.teinte : null); }
        });
      }
      volet.choix.forEach(function (c) {
        var oui = !!c.test(v);
        c.bouton.setAttribute("aria-pressed", oui ? "true" : "false");
        c.bouton.setAttribute("aria-disabled", actif ? "false" : "true");
        var coche = c.bouton.querySelector(".coche");
        if (oui && !coche) {
          var cc = el("span", "coche");
          cc.setAttribute("aria-hidden", "true");
          cc.appendChild(icone("coche"));
          c.bouton.appendChild(cc);
        } else if (!oui && coche) {
          c.bouton.removeChild(coche);
        }
      });
    } else {
      var g = volet.glisseurs.volume;
      g.desactiver(!actif || !v.allumee);
      g.racine.hidden = !v.allumee;
      volet.eteinte.hidden = !!v.allumee;
      g.maj(v.allumee && typeof v.volume === "number" ? v.volume : null);
    }
    var noeuds = pied(v, t.type);
    var signature = JSON.stringify([v.statut, v.reglage, v.texte, erreurReglage, derniere[v.entite] || null]);
    if (signature !== signaturePied) {
      signaturePied = signature;
      vider(volet.pied);
      noeuds.forEach(function (n) { volet.pied.appendChild(n); });
    }
  }

  // ------------------------------------------------------------------ connexion
  function connecter() {
    var s = C.ouvrirWs("/ws");
    ws = s;
    s.onopen = function () {
      reconnexion = 0;
      message("erreur-maison", "");
      demanderEtats();
    };
    s.onmessage = function (ev) {
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m && typeof m === "object") { recu(m); }
    };
    s.onclose = function (ev) {
      if (ws !== s) { return; }
      ws = null;
      if (ev.code === 4001 || ev.code === 1008) { window.location.replace("/appairage"); return; }
      file = {};
      attente = [];
      brouillons = {};
      if (minuterieEtats) { clearTimeout(minuterieEtats); minuterieEtats = null; }
      var st = $("statut-maison");
      st.textContent = "La connexion avec la maison est coupée. Nouvelle tentative.";
      st.hidden = false;
      reconnexion = Math.min(reconnexion + 1, 6);
      delai = setTimeout(connecter, 1000 * reconnexion);
      afficher();
    };
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && volet && !volet.feuille.contains(document.activeElement)) { fermerVolet(true); }
  });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { demanderEtats(); } });
  window.addEventListener("pagehide", function () {
    if (delai) { clearTimeout(delai); }
    if (minuterieEtats) { clearTimeout(minuterieEtats); }
    if (minuteriePompe) { clearTimeout(minuteriePompe); }
  });
  connecter();
})();
