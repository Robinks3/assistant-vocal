// Client web, Journal : liste filtrée, demande en cours, feuille de détail (S-W2).
// Le serveur décide de ce que ce navigateur a le droit de voir. Cette page n'affiche que ce qu'elle reçoit.
// Aucun HTML construit par concaténation : createElement et textContent seulement (Trusted Types).
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var C = window.Client;
  var MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  var NIVEAUX = { tout: "Tout", action: "Action seulement", discret: "Discret" };
  var STATUTS = {
    ok: "Fait", refus: "Refusé", erreur: "Erreur", "non compris": "Non compris", "non confirmé": "Non confirmé"
  };
  var ETAPES = { entendu: "Entendu", compris: "Compris", fait: "Fait", repondu: "Répondu" };
  var ws = null;
  var entrees = [];        // les entrées reçues, la plus récente d'abord
  var plus = null;         // jour par lequel reprendre pour la page suivante
  var filtre = "tout";
  var encours = null;      // { id, etapes: [{nom, t}] }
  var minuteur = null;
  var reconnexion = 0;
  var chargement = false;

  function envoyer(objet) {
    if (ws && ws.readyState === 1) { ws.send(JSON.stringify(objet)); return true; }
    return false;
  }

  function message(id, texte) {
    var e = $(id);
    e.textContent = texte || "";
    e.hidden = !texte;
  }

  function el(balise, classe, texte) {
    var e = document.createElement(balise);
    if (classe) { e.className = classe; }
    if (texte !== undefined && texte !== null) { e.textContent = texte; }
    return e;
  }

  // « 2026-10-27T10:15:03 » vers { jour: "2026-10-27", heure: "10:15" }
  function decouper(horodatage) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(horodatage || "");
    if (!m) { return { jour: "", heure: "--:--", libelle: "Date inconnue" }; }
    return { jour: m[1] + "-" + m[2] + "-" + m[3], heure: m[4] + ":" + m[5], an: +m[1], mois: +m[2], j: +m[3] };
  }

  function jourCle(d) {
    return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2);
  }

  function libelleJour(cle, d) {
    if (!cle) { return d.libelle; }
    var auj = new Date();
    var hier = new Date(auj.getTime() - 86400000);
    if (cle === jourCle(auj)) { return "Aujourd'hui"; }
    if (cle === jourCle(hier)) { return "Hier"; }
    return d.j + " " + MOIS[d.mois - 1];
  }

  function titre(e) {
    if (e.detail === "aucun") { return "Une demande"; }
    if (e.phrase) { return e.phrase; }
    if (e.actions && e.actions.length) { return e.actions[0]; }
    return "Une demande";
  }

  function sousTitre(e) {
    if (e.detail === "aucun") { return "Détail non partagé"; }
    var parts = [];
    if (e.appareil) { parts.push(e.appareil); }
    if (e.detail === "action" && e.actions && e.actions.length > 1) { parts.push(e.actions.length + " actions"); }
    if (e.detail === "complet" && e.actions && e.actions.length) { parts.push(e.actions.join(", ")); }
    return parts.join(", ");
  }

  function pastilleStatut(statut) {
    var classe = "pastille";
    if (statut === "ok") { classe += " pastille--ok"; }
    else if (statut === "refus" || statut === "erreur") { classe += " pastille--danger"; }
    return el("span", classe, STATUTS[statut] || statut);
  }

  function visible(e) {
    if (filtre === "miennes") { return e.mien; }
    if (filtre === "autres") { return !e.mien; }
    if (filtre === "refus") { return e.statut === "refus"; }
    return true;
  }

  function creerEntree(e) {
    var d = decouper(e.horodatage);
    var b = el("button", "entree");
    b.type = "button";
    b.setAttribute("aria-label", d.heure + ", " + (e.mien ? "vous, " : "") + titre(e));
    b.appendChild(el("span", "entree-heure chiffres", d.heure));
    var corps = el("span", "entree-corps");
    corps.appendChild(el("span", "fort entree-titre", titre(e)));
    var sous = sousTitre(e);
    if (sous) { corps.appendChild(el("span", "secondaire entree-sous", sous)); }
    var marques = el("span", "entree-marques");
    if (e.mien) { marques.appendChild(el("span", "pastille pastille--assistant", "Vous")); }
    if (e.statut && e.detail !== "aucun") { marques.appendChild(pastilleStatut(e.statut)); }
    if (marques.firstChild) { corps.appendChild(marques); }
    b.appendChild(corps);
    b.addEventListener("click", function () { ouvrirDetail(e); });
    return b;
  }

  function afficher() {
    var conteneur = $("liste-journal");
    while (conteneur.firstChild) { conteneur.removeChild(conteneur.firstChild); }
    var courant = null;
    var n = 0;
    entrees.forEach(function (e) {
      if (!visible(e)) { return; }
      var d = decouper(e.horodatage);
      if (d.jour !== courant) {
        courant = d.jour;
        conteneur.appendChild(el("h3", "jour", libelleJour(d.jour, d)));
      }
      conteneur.appendChild(creerEntree(e));
      n += 1;
    });
    var vide = $("vide-journal");
    vide.hidden = n > 0 || chargement;
    vide.textContent = entrees.length ? "Aucune demande ne correspond à ce filtre." : "Aucune demande dans le journal.";
    $("bouton-plus").hidden = !plus;
  }

  function afficherEncours() {
    var carte = $("carte-encours");
    var liste = $("etapes-encours");
    while (liste.firstChild) { liste.removeChild(liste.firstChild); }
    if (!encours) { carte.hidden = true; return; }
    encours.etapes.forEach(function (x) {
      var li = el("li", "etape");
      li.appendChild(el("span", "fort", ETAPES[x.nom] || x.nom));
      li.appendChild(el("span", "secondaire chiffres", x.t));
      liste.appendChild(li);
    });
    carte.hidden = false;
  }

  function finEncours() {
    encours = null;
    if (minuteur) { clearTimeout(minuteur); minuteur = null; }
    afficherEncours();
  }

  function etape(m) {
    if (!encours || encours.id !== m.id) { encours = { id: m.id, etapes: [] }; }
    encours.etapes.push({ nom: m.nom, t: m.t });
    afficherEncours();
    if (minuteur) { clearTimeout(minuteur); }
    minuteur = setTimeout(finEncours, 60000);   // une demande qui ne se termine pas ne reste pas affichée
  }

  function ajout(e) {
    if (!e || typeof e !== "object") { return; }
    entrees = entrees.filter(function (x) { return x.id !== e.id; });
    entrees.unshift(e);
    if (encours && encours.id === e.id) { finEncours(); }
    afficher();
  }

  function retrait(ids) {
    if (!Array.isArray(ids)) { return; }
    entrees = entrees.filter(function (x) { return ids.indexOf(x.id) < 0; });
    afficher();
  }

  function ligneDetail(liste, nom, valeur) {
    if (!valeur) { return; }
    var bloc = el("div");
    bloc.appendChild(el("dt", "", nom));
    bloc.appendChild(el("dd", "", valeur));
    liste.appendChild(bloc);
  }

  function ouvrirDetail(e) {
    var d = decouper(e.horodatage);
    $("titre-detail").textContent = e.detail === "aucun" ? "Une demande" : titre(e);
    var p = $("detail-pastille");
    while (p.firstChild) { p.removeChild(p.firstChild); }
    if (e.mien) { p.appendChild(el("span", "pastille pastille--assistant", "Vous")); }
    if (e.statut && e.detail !== "aucun") { p.appendChild(pastilleStatut(e.statut)); }
    var l = $("detail-liste");
    while (l.firstChild) { l.removeChild(l.firstChild); }
    ligneDetail(l, "Jour", libelleJour(d.jour, d));
    ligneDetail(l, "Heure", d.heure);
    if (e.detail !== "aucun") {
      if (e.detail === "complet") { ligneDetail(l, "Phrase", e.phrase); }
      ligneDetail(l, "Actions", e.actions && e.actions.length ? e.actions.join(", ") : "");
      ligneDetail(l, "Motif", e.motif);
      if (e.detail === "complet") {
        ligneDetail(l, "Réponse", e.reponse);
        ligneDetail(l, "Appareil", e.appareil);
        ligneDetail(l, "Chemin", e.voie);
        ligneDetail(l, "Durée", e.duree_s ? e.duree_s + " s" : "");
      }
      if (e.mien && e.niveau) { ligneDetail(l, "Vie privée alors", NIVEAUX[e.niveau] || e.niveau); }
    }
    var et = $("detail-etapes");
    while (et.firstChild) { et.removeChild(et.firstChild); }
    var aEtapes = e.mien && Array.isArray(e.etapes) && e.etapes.length > 0;
    aEtapes ? e.etapes.forEach(function (x) {
      var li = el("li", "etape");
      li.appendChild(el("span", "fort", ETAPES[x.nom] || x.nom));
      li.appendChild(el("span", "secondaire chiffres", x.t));
      et.appendChild(li);
    }) : null;
    et.hidden = !aEtapes;
    var note = $("detail-note");
    if (e.detail === "aucun") {
      note.textContent = "Cette personne a choisi de ne pas partager le détail de ses demandes.";
    } else if (e.detail === "action") {
      note.textContent = "Cette personne partage ce qui a été fait, sans sa phrase ni la réponse.";
    } else if (e.mien) {
      note.textContent = "Seul cet appareil voit les étapes de ses propres demandes.";
    } else {
      note.textContent = "Cette personne partage ses demandes en entier.";
    }
    note.hidden = false;
    var dialogue = $("dialogue-detail");
    if (typeof dialogue.showModal === "function") { dialogue.showModal(); } else { dialogue.setAttribute("open", ""); }
    $("bouton-detail-fermer").focus();
  }

  function fermerDetail() {
    var dialogue = $("dialogue-detail");
    if (typeof dialogue.close === "function") { dialogue.close(); } else { dialogue.removeAttribute("open"); }
  }

  function niveau(n, jours) {
    $("niveau-courant").textContent = NIVEAUX[n] || "Discret";
    if (jours) { $("conserve-jours").textContent = String(jours); }
  }

  function recu(m) {
    if (m.type === "journal") {
      entrees = Array.isArray(m.entrees) ? m.entrees : [];
      plus = m.plus || null;
      chargement = false;
      niveau(m.niveau, m.conserve_jours);
      message("erreur-journal", "");
      afficher();
    } else if (m.type === "journal_page") {
      var suite = Array.isArray(m.entrees) ? m.entrees : [];
      var connus = {};
      entrees.forEach(function (x) { connus[x.id] = true; });
      suite.forEach(function (x) { if (!connus[x.id]) { entrees.push(x); } });
      plus = m.plus || null;
      chargement = false;
      $("bouton-plus").disabled = false;
      afficher();
    } else if (m.type === "journal_ajout") {
      ajout(m.entree);
    } else if (m.type === "journal_etape") {
      etape(m);
    } else if (m.type === "journal_retrait") {
      retrait(m.ids);
    } else if (m.type === "erreur") {
      chargement = false;
      $("bouton-plus").disabled = false;
      message("erreur-journal", C.texteErreur(m.cause));
    }
  }

  function connecter() {
    var s = C.ouvrirWs("/ws");
    ws = s;
    chargement = true;
    s.onopen = function () {
      reconnexion = 0;
      envoyer({ type: "abonner_journal" });
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
      message("erreur-journal", "La connexion avec l'assistant est coupée. Nouvelle tentative.");
      reconnexion = Math.min(reconnexion + 1, 6);
      setTimeout(connecter, 1000 * reconnexion);
    };
  }

  function choisirFiltre(nom) {
    filtre = nom;
    var boutons = document.querySelectorAll("#filtres .filtre");
    Array.prototype.forEach.call(boutons, function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-filtre") === nom ? "true" : "false");
    });
    afficher();
  }

  Array.prototype.forEach.call(document.querySelectorAll("#filtres .filtre"), function (b) {
    b.addEventListener("click", function () { choisirFiltre(b.getAttribute("data-filtre")); });
  });
  $("bouton-plus").addEventListener("click", function () {
    if (!plus) { return; }
    $("bouton-plus").disabled = true;
    if (!envoyer({ type: "journal_page", reprise: plus })) { $("bouton-plus").disabled = false; }
  });
  $("bouton-detail-fermer").addEventListener("click", fermerDetail);
  window.addEventListener("pagehide", function () {
    if (ws && ws.readyState === 1) { envoyer({ type: "desabonner_journal" }); }
  });
  connecter();
})();
