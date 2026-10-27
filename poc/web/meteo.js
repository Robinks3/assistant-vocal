// Client web, Météo et mer : l'instant présent, la mer, les prochaines heures, les jours et les balises du lieu choisi (S-W5).
// Le serveur décide de ce que ce navigateur a le droit de voir et dit tout en mots. Cette page n'affiche que ce qu'elle reçoit.
// Aucun HTML construit par concaténation : createElement, createElementNS et textContent seulement (Trusted Types).
// Le vent s'affiche toujours en mots, la flèche n'est qu'un renfort. Une valeur absente est dite en mots.
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var C = window.Client;
  var NS = "http:" + "//www.w3.org/2000/svg";   // espace de noms SVG, requis par createElementNS
  var RAFRAICHIR_MS = 300000;                    // les sources sont en cache côté serveur, cinq minutes suffisent
  var ws = null;
  var reconnexion = 0;
  var point = null;                              // identifiant du lieu choisi, null : celui du serveur
  var dernier = null;
  var CAUSES = {
    droit: "Cet écran n'est pas ouvert à ce compte.",
    indisponible: "La météo n'est pas disponible pour le moment. Nouvel essai dans quelques minutes.",
    format: "La demande n'a pas été comprise.",
    entite: "Ce lieu n'existe plus. Choisissez-en un autre."
  };

  function envoyer(objet) {
    if (ws && ws.readyState === 1) { ws.send(JSON.stringify(objet)); return true; }
    return false;
  }

  function el(balise, classe, texte) {
    var e = document.createElement(balise);
    if (classe) { e.className = classe; }
    if (texte !== undefined && texte !== null) { e.textContent = texte; }
    return e;
  }

  function message(id, texte) {
    var e = $(id);
    e.textContent = texte || "";
    e.hidden = !texte;
  }

  // ------------------------------------------------------------------ icônes
  var CHEMINS = {
    soleil: ["M8 12a4 4 0 1 0 8 0 4 4 0 1 0-8 0", "M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"],
    nuage: ["M7 18h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7.1 9.2 4.4 4.4 0 0 0 7 18z"],
    pluie: ["M7 14h10a3.5 3.5 0 0 0 .5-6.96A5 5 0 0 0 7.5 6.5 4 4 0 0 0 7 14z", "M8 17v3M12 17v3M16 17v3"],
    orage: ["M7 14h10a3.5 3.5 0 0 0 .5-6.96A5 5 0 0 0 7.5 6.5 4 4 0 0 0 7 14z", "M12 14l-2 4h4l-2 4"],
    brouillard: ["M4 9h16M3 13h18M5 17h14"],
    neige: ["M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"],
    vague: ["M2 9c2.5 0 2.5 2 5 2s2.5-2 5-2 2.5 2 5 2 2.5-2 5-2M2 15c2.5 0 2.5 2 5 2s2.5-2 5-2 2.5 2 5 2 2.5-2 5-2"],
    thermometre: ["M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z"],
    fleche: ["M12 20V5M6 11l6-6 6 6"],
    vent: ["M3 9h11a3 3 0 1 0-3-3M3 14h15a3 3 0 1 1-3 3M3 19h6"],
    info: ["M3 12a9 9 0 1 0 18 0 9 9 0 1 0-18 0", "M12 11v5M12 8v.2"],
    chevron: ["m9 5 7 7-7 7"]
  };

  function icone(nom, degres) {
    var s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("class", "i");
    s.setAttribute("aria-hidden", "true");
    s.setAttribute("focusable", "false");
    var parent = s;
    if (typeof degres === "number") {            // rotation par attribut SVG, jamais par style
      parent = document.createElementNS(NS, "g");
      parent.setAttribute("transform", "rotate(" + Math.round(degres) + " 12 12)");
      s.appendChild(parent);
    }
    (CHEMINS[nom] || []).forEach(function (d) {
      var p = document.createElementNS(NS, "path");
      p.setAttribute("d", d);
      parent.appendChild(p);
    });
    return s;
  }

  // ------------------------------------------------------------------ mots
  function nb(v) { return String(v).replace(".", ","); }
  function aucune(v) { return v === null || v === undefined; }

  function heure(t) {                            // "15:00" devient "15 h", "14:20" devient "14 h 20"
    var m = /^(\d{1,2}):(\d{2})/.exec(t || "");
    if (!m) { return t || ""; }
    return Number(m[1]) + " h" + (m[2] === "00" ? "" : " " + m[2]);
  }

  function noeuds(v) { return nb(v) + (v >= 2 ? " nœuds" : " nœud"); }

  function etatMer(m) {                          // échelle de Douglas, en mots
    if (aucune(m)) { return null; }
    if (m < 0.1) { return "Mer calme"; }
    if (m < 0.5) { return "Mer belle"; }
    if (m < 1.25) { return "Mer peu agitée"; }
    if (m < 2.5) { return "Mer agitée"; }
    if (m < 4) { return "Mer forte"; }
    return "Mer très forte";
  }

  function pluie(mm) {
    if (aucune(mm)) { return null; }
    return mm > 0 ? "Pluie " + nb(mm) + " mm" : "Sans pluie";
  }

  function age(min) {
    if (min < 1) { return "à l'instant"; }
    if (min < 60) { return "il y a " + min + " min"; }
    if (min < 1440) { return "il y a " + Math.floor(min / 60) + " h"; }
    return "il y a " + Math.floor(min / 1440) + " j";
  }

  function symbole(s) {
    return s === "soleil" || s === "nuage" || s === "pluie" || s === "orage" || s === "brouillard" || s === "neige" ? s : "nuage";
  }
  function majuscule(t) { return t ? t.charAt(0).toUpperCase() + t.slice(1) : t; }

  // ------------------------------------------------------------------ éléments
  function carte(etiquette, classe) {
    var s = el("section", "carte " + (classe || ""));
    s.setAttribute("aria-label", etiquette);
    return s;
  }

  function puce(nom) {
    var p = el("span", "puce puce--meteo");
    p.appendChild(icone(nom));
    return p;
  }

  function rangee(avant, titre, details, valeur, unite, pastille) {
    var r = el("div", "rangee");
    r.appendChild(avant);
    var t = el("span", "texte");
    t.appendChild(el("b", "", titre));
    details.forEach(function (d) { if (d) { t.appendChild(el("span", "", d)); } });
    if (pastille) { t.appendChild(el("span", "pastille pastille--lumiere", pastille)); }
    r.appendChild(t);
    if (!aucune(valeur)) {
      var v = el("span", "valeur", String(valeur));
      if (unite) { v.appendChild(el("small", "", unite)); }
      r.appendChild(v);
    }
    return r;
  }

  function fleche(dirVers) {
    var f = el("span", "fleche-vent");
    f.appendChild(icone("fleche", dirVers));
    return f;
  }

  function titreSection(texte) { return el("h2", "titre-section", texte); }

  // ------------------------------------------------------------------ rendu
  function sectionMaintenant(m) {
    var s = carte("Maintenant", "maintenant");
    if (!m) {
      var vide = el("span", "texte");
      vide.appendChild(el("b", "", "Pas de prévision pour le moment"));
      s.appendChild(vide);
      return s;
    }
    s.appendChild(el("span", "temp-grand", aucune(m.air) ? "--" : Math.round(m.air) + "°"));
    var t = el("span", "texte");
    t.appendChild(el("b", "", m.ciel || "Ciel non précisé"));
    [pluie(m.pluie), etatMer(m.vagues)].forEach(function (x) { if (x) { t.appendChild(el("span", "", x)); } });
    s.appendChild(t);
    s.appendChild(puce(symbole(m.symbole)));
    return s;
  }

  function sectionEau(m, eau) {
    var s = carte("Sur l'eau", "carte--vide");
    var pas = "Pas de valeur pour le moment";
    if (m && !aucune(m.vent)) {
      var det = [m.rafales && m.rafales > m.vent ? "Rafales à " + noeuds(m.rafales) : null];
      s.appendChild(rangee(aucune(m.dir_vers) ? puce("vent") : fleche(m.dir_vers), m.vent_mot || "Vent", det,
        nb(m.vent), m.vent >= 2 ? "nœuds" : "nœud"));
    } else {
      s.appendChild(rangee(puce("vent"), "Vent", [pas], null));
    }
    if (m && !aucune(m.vagues)) {
      s.appendChild(rangee(puce("vague"), "Houle" + (m.vagues_secteur ? " " + m.vagues_secteur : ""),
        [m.periode ? "Période de " + nb(m.periode) + " secondes" : null], nb(m.vagues), m.vagues >= 2 ? "mètres" : "mètre"));
    } else {
      s.appendChild(rangee(puce("vague"), "Houle", [pas], null));
    }
    if (!aucune(eau)) {
      s.appendChild(rangee(puce("thermometre"), "Température de l'eau", [], Math.round(eau) + "°"));
    } else {
      s.appendChild(rangee(puce("thermometre"), "Température de l'eau", [pas], null));
    }
    return s;
  }

  function sectionHeures(heures) {
    var s = carte("Prochaines heures", "carte--vide");
    if (!heures.length) {
      s.appendChild(el("p", "secondaire carte-texte", "Pas de prévision pour les prochaines heures."));
      return s;
    }
    var ul = el("ul", "heures");
    ul.setAttribute("aria-label", "Prochaines heures");
    ul.tabIndex = 0;
    ul.setAttribute("data-defilement-horizontal-voulu", "");   // rail à défilement voulu, au clavier aussi
    heures.forEach(function (h) {
      var li = el("li", "heure-prev");
      li.appendChild(el("time", "", heure(h.heure)));
      li.appendChild(icone(symbole(h.symbole)));
      li.appendChild(el("b", "", aucune(h.air) ? "--" : Math.round(h.air) + "°"));
      li.appendChild(el("small", "", aucune(h.vent) ? "Vent inconnu" : noeuds(h.vent)));
      ul.appendChild(li);
    });
    s.appendChild(ul);
    return s;
  }

  function sectionJours(jours) {
    var s = carte("Prochains jours", "carte--vide");
    if (!jours.length) {
      s.appendChild(el("p", "secondaire carte-texte", "Pas de prévision pour les prochains jours."));
      return s;
    }
    jours.forEach(function (j) {
      var det = [];
      if (!aucune(j.vent_max)) { det.push("vent jusqu'à " + noeuds(j.vent_max)); }
      if (!aucune(j.vagues_max)) { det.push("houle jusqu'à " + nb(j.vagues_max) + " m"); }
      var ligne = det.length ? majuscule(det.join(", ")) : "Pas de valeur pour ce jour";
      s.appendChild(rangee(puce(symbole(j.symbole)), j.jour, [ligne, j.ciel],
        aucune(j.air_max) ? null : Math.round(j.air_max) + "°", aucune(j.air_min) ? "" : "min " + Math.round(j.air_min) + "°"));
    });
    return s;
  }

  function sectionBalises(balises) {
    var s = carte("Balises", "carte--vide");
    balises.forEach(function (b) {
      var det = aucune(b.vent) ? ["Pas de valeur pour le moment"]
        : [b.vent_mot, !aucune(b.rafale) && b.rafale > b.vent ? "Rafales à " + noeuds(b.rafale) : null];
      s.appendChild(rangee(aucune(b.dir_vers) ? puce("vent") : fleche(b.dir_vers), b.nom, det,
        aucune(b.vent) ? null : nb(b.vent), age(b.age_min), b.ancienne ? "Ancienne" : null));
    });
    return s;
  }

  function sectionSources(texte) {
    var s = carte("Sources et licences", "carte--vide");
    var b = el("button", "rangee");
    b.type = "button";
    b.setAttribute("aria-expanded", "false");
    b.setAttribute("aria-controls", "texte-sources");
    var p = el("span", "puce");
    p.appendChild(icone("info"));
    b.appendChild(p);
    var t = el("span", "texte");
    t.appendChild(el("b", "", "Sources et licences"));
    t.appendChild(el("span", "", "Données publiques, mentions de la configuration"));
    b.appendChild(t);
    var suite = el("span", "suite");
    suite.appendChild(icone("chevron"));
    b.appendChild(suite);
    var corps = el("p", "aide carte-texte", texte || "Aucune mention n'est renseignée dans la configuration.");
    corps.id = "texte-sources";
    corps.hidden = true;
    b.addEventListener("click", function () {
      var ouvert = b.getAttribute("aria-expanded") === "true";
      b.setAttribute("aria-expanded", ouvert ? "false" : "true");
      corps.hidden = ouvert;
    });
    s.appendChild(b);
    s.appendChild(corps);
    return s;
  }

  function rendrePoints(m) {
    var zone = $("points-meteo");
    zone.textContent = "";
    var liste = m.points || [];
    zone.hidden = liste.length < 2;
    if (liste.length < 2) { return; }
    liste.forEach(function (p) {
      var b = el("button", "filtre", p.nom);
      b.type = "button";
      b.setAttribute("aria-pressed", p.id === m.point.id ? "true" : "false");
      b.addEventListener("click", function () {
        if (p.id === point) { return; }
        point = p.id;
        demander();
      });
      zone.appendChild(b);
    });
  }

  function rendre(m) {
    dernier = m;
    point = m.point.id;
    message("erreur-meteo", "");
    $("sous-titre").textContent = m.point.nom + (m.lu_a ? ", mesures de " + heure(m.lu_a) : "");
    var pannes = $("pannes-meteo");
    pannes.textContent = "";
    (m.sources_en_panne || []).forEach(function (t) { pannes.appendChild(el("p", "", t)); });
    pannes.hidden = !(m.sources_en_panne || []).length;
    rendrePoints(m);
    var v = $("vue-meteo");
    v.textContent = "";
    v.appendChild(sectionMaintenant(m.maintenant));
    v.appendChild(titreSection("Sur l'eau"));
    v.appendChild(sectionEau(m.maintenant, m.eau));
    if (m.soleil && (m.soleil.lever || m.soleil.coucher)) {
      var phrase = [m.soleil.lever ? "Lever du soleil à " + heure(m.soleil.lever) : null,
        m.soleil.coucher ? "coucher à " + heure(m.soleil.coucher) : null].filter(Boolean).join(", ");
      v.appendChild(el("p", "secondaire soleil-ligne", phrase));
    }
    v.appendChild(titreSection("Prochaines heures"));
    v.appendChild(sectionHeures(m.heures || []));
    v.appendChild(titreSection("Prochains jours"));
    v.appendChild(sectionJours(m.jours || []));
    v.appendChild(titreSection("Balises"));
    if ((m.balises || []).length) {
      v.appendChild(sectionBalises(m.balises));
    } else {
      var vide = carte("Balises", "");
      vide.appendChild(el("p", "secondaire", "Aucune balise de mesure n'est rattachée à ce lieu."));
      v.appendChild(vide);
    }
    var sources = sectionSources(m.attribution);
    sources.classList.add("carte--espacee");
    v.appendChild(sources);
  }

  function recu(m) {
    if (m.type === "meteo") {
      rendre(m);
    } else if (m.type === "erreur" && m.genre === "meteo") {
      if (m.cause === "entite") { point = null; }
      $("sous-titre").textContent = "";
      message("erreur-meteo", CAUSES[m.cause] || C.texteErreur(m.cause));
    }
  }

  function demander() {
    var msg = { type: "meteo" };
    if (point) { msg.point = point; }
    envoyer(msg);
  }

  function connecter() {
    var s = C.ouvrirWs("/ws");
    ws = s;
    s.onopen = function () {
      reconnexion = 0;
      message("erreur-meteo", "");
      demander();
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
      message("erreur-meteo", "La connexion avec l'assistant est coupée. Nouvelle tentative.");
      reconnexion = Math.min(reconnexion + 1, 6);
      setTimeout(connecter, 1000 * reconnexion);
    };
  }

  var minuteur = setInterval(function () { if (!document.hidden) { demander(); } }, RAFRAICHIR_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden && dernier) { demander(); } });
  window.addEventListener("pagehide", function () { clearInterval(minuteur); });
  connecter();
})();
