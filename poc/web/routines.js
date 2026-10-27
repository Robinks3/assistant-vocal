// Client web, Routines : la liste, le détail d'une routine et sa suppression confirmée (S-W6).
// Le serveur décide de ce que ce navigateur voit et de ce qu'il peut faire : chaque routine arrive avec son bloc
// « droits ». Cette page n'invente aucun droit, elle montre ou cache les commandes selon ce bloc.
// Aucun HTML construit par concaténation : createElement, createElementNS et textContent seulement (Trusted Types).
// On ne crée pas de routine ici : la création et la modification se font à la voix.
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var C = window.Client;
  var NS = "http:" + "//www.w3.org/2000/svg";   // espace de noms SVG, requis par createElementNS
  var IDENT = /^[a-z0-9_-]{1,80}$/;
  var ws = null;
  var reconnexion = 0;
  var routines = null;                           // dernière liste reçue, null : pas encore lue
  var courant = null;                            // identifiant de la routine ouverte, null : la liste
  var poussee = false;                           // le détail a été ouvert par cette page (history.back possible)
  var supprimee = null;                          // nom de la routine dont la suppression est en cours
  var focusAvant = null;
  var CAUSES = {
    droit: "Ce compte n'a pas le droit de faire cela.",
    format: "La demande n'a pas été comprise.",
    indisponible: "Les routines ne sont pas disponibles pour le moment. Nouvel essai dans quelques minutes.",
    inconnue: "Cette routine n'existe plus."
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
    chevron: ["m9 5 7 7-7 7"],
    routines: ["M4 7h10M4 12h16M4 17h8", "M15 7a2 2 0 1 0 4 0 2 2 0 1 0-4 0", "M13 17a2 2 0 1 0 4 0 2 2 0 1 0-4 0"],
    pause: ["M8 5v14M16 5v14"],
    lecture: ["M8 5l11 7-11 7V5Z"],
    ok: ["M3 12a9 9 0 1 0 18 0 9 9 0 1 0-18 0", "m8 12.5 3 3 5-6"]
  };

  function icone(nom) {
    var s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("class", "i");
    s.setAttribute("aria-hidden", "true");
    s.setAttribute("focusable", "false");
    (CHEMINS[nom] || []).forEach(function (d) {
      var p = document.createElementNS(NS, "path");
      p.setAttribute("d", d);
      s.appendChild(p);
    });
    return s;
  }

  // ------------------------------------------------------------------ mots
  function nEtapes(n) { return n + (n > 1 ? " étapes" : " étape"); }
  function etat(r) { return (r.actif ? "Active, " : "En pause, ") + nEtapes(r.etapes || 0); }
  function guillemets(t) { return "\"" + t + "\""; }
  function majuscule(t) { return t ? t.charAt(0).toUpperCase() + t.slice(1) : t; }
  function droits(r) { return r.droits || {}; }

  function parId(id) {
    var liste = routines || [];
    for (var i = 0; i < liste.length; i++) { if (liste[i].id === id) { return liste[i]; } }
    return null;
  }

  // ------------------------------------------------------------------ liste
  function commutateur(r) {
    var b = el("button", "commutateur");
    b.type = "button";
    b.setAttribute("role", "switch");
    b.setAttribute("aria-checked", r.actif ? "true" : "false");
    b.setAttribute("aria-label", r.nom + (r.actif ? ", active" : ", en pause"));
    b.appendChild(el("span", "interrupteur"));
    b.addEventListener("click", function () {
      // Pas de confirmation : une pause se défait d'un geste.
      if (envoyer({ type: "routine_activer", id: r.id, actif: !r.actif })) {
        r.actif = !r.actif;
        b.setAttribute("aria-checked", r.actif ? "true" : "false");
        b.setAttribute("aria-label", r.nom + (r.actif ? ", active" : ", en pause"));
        var etatTexte = b.parentNode.querySelector(".etat-routine");
        if (etatTexte) { etatTexte.textContent = etat(r); }
      }
    });
    return b;
  }

  function carteRoutine(r) {
    var c = el("div", "carte carte--vide routine");
    c.setAttribute("data-id", r.id);
    var b = el("button", "rangee");
    b.type = "button";
    var p = el("span", "puce puce--assistant");
    p.appendChild(icone("routines"));
    b.appendChild(p);
    var t = el("span", "texte");
    t.appendChild(el("b", "", r.nom));
    if ((r.phrases || []).length) { t.appendChild(el("span", "", "Déclencheur : " + guillemets(r.phrases[0]))); }
    t.appendChild(el("small", "etat-routine", etat(r)));
    b.appendChild(t);
    var suite = el("span", "suite");
    suite.appendChild(icone("chevron"));
    b.appendChild(suite);
    b.addEventListener("click", function () { ouvrir(r.id, true); });
    c.appendChild(b);
    if (droits(r).couper) { c.appendChild(commutateur(r)); }
    return c;
  }

  function rendreListe() {
    var zone = $("liste-routines");
    zone.textContent = "";
    var liste = routines || [];
    $("vide-routines").hidden = liste.length > 0;
    liste.forEach(function (r) { zone.appendChild(carteRoutine(r)); });
    $("sous-titre").textContent = liste.length ? (liste.length + (liste.length > 1 ? " routines" : " routine")) : "";
    $("sous-titre").hidden = !liste.length;
  }

  // ------------------------------------------------------------------ détail
  function entete(r) {
    var e = $("entete-routine");
    e.textContent = "";
    e.appendChild(el("span", r.actif ? "pastille pastille--ok" : "pastille", r.actif ? "Active" : "En pause"));
    e.appendChild(el("span", "discret", nEtapes(r.etapes || 0)));
    if (r.a_revoir) { e.appendChild(el("span", "pastille pastille--lumiere", "À revoir")); }
  }

  function declencheurs(r) {
    var ul = $("declencheurs-routine");
    ul.textContent = "";
    (r.phrases || []).forEach(function (ph) {
      var li = el("li", "");
      li.appendChild(el("b", "", guillemets(ph)));
      ul.appendChild(li);
    });
    if ((r.variantes || []).length) {
      var li = el("li", "variantes");
      li.textContent = "Aussi : " + r.variantes.map(guillemets).join(", ");
      ul.appendChild(li);
    }
    if (!ul.children.length) { ul.appendChild(el("li", "secondaire", "Aucune phrase de déclenchement.")); }
  }

  function etapes(r) {
    var ol = $("etapes-routine");
    ol.textContent = "";
    (r.etapes_mots || []).forEach(function (e) {
      var li = el("li", "");
      var t = el("span", "texte");
      t.appendChild(el("b", "", e.texte));
      // L'identifiant technique n'arrive que pour le propriétaire, et ne s'affiche qu'en mode développeur.
      if (e.technique) { t.appendChild(el("span", "technique dev-seulement", e.technique)); }
      li.appendChild(t);
      ol.appendChild(li);
    });
    if (!ol.children.length) { ol.appendChild(el("li", "secondaire", "Aucune étape.")); }
  }

  function ligneFiche(dl, terme, valeur, detail) {
    dl.appendChild(el("dt", "", terme));
    var dd = el("dd", "", valeur);
    if (detail) { dd.appendChild(el("small", "", detail)); }
    dl.appendChild(dd);
  }

  function fiche(r) {
    var dl = $("fiche-routine");
    dl.textContent = "";
    var d = r.derniere_execution;
    if (d) {
      ligneFiche(dl, "Dernière fois", majuscule(d.quand || "date inconnue"));
      var echecs = (d.echecs || []).length ? "En échec : " + d.echecs.join(", ") : null;
      ligneFiche(dl, "Résultat", d.resultat, echecs);
    } else {
      ligneFiche(dl, "Dernière fois", "Jamais lancée");
    }
    var n = r.executions || 0;
    ligneFiche(dl, "Lancée", n === 0 ? "Jamais" : n + " fois");
    if (r.creee) { ligneFiche(dl, "Créée", majuscule(r.creee) + (r.auteur_nom ? ", par " + r.auteur_nom : "")); }
    ligneFiche(dl, "Peut la lancer", majuscule(r.lanceurs || ""));
    ligneFiche(dl, "Peut la gérer", majuscule(r.gerants || ""));
  }

  function actions(r) {
    var d = droits(r);
    var lancer = $("bouton-lancer");
    lancer.hidden = !d.lancer;
    lancer.disabled = !r.actif;
    $("bouton-pause").hidden = !d.couper;
    $("texte-pause").textContent = r.actif ? "Mettre en pause" : "Réactiver";
    var chemin = $("bouton-pause").querySelector("path");
    chemin.setAttribute("d", r.actif ? CHEMINS.pause[0] : CHEMINS.lecture[0]);
    $("bouton-modifier").hidden = !d.couper;
    $("bouton-supprimer").hidden = !d.supprimer;
    $("bouton-modifier").parentNode.hidden = !d.couper && !d.supprimer;
    if (!d.couper) {
      $("aide-modifier").hidden = true;
      $("bouton-modifier").setAttribute("aria-expanded", "false");
    }
    var aide = [];
    if (d.lancer && !r.actif) { aide.push("Elle est en pause : réactive-la pour la lancer."); }
    if (!d.lancer) { aide.push("Seul " + (r.lanceurs || "son auteur").replace(/ seulement$/, "") + " peut la lancer."); }
    if (!d.couper) { aide.push("Pour la mettre en pause, la modifier ou la supprimer, demande à " + (r.gerants || "son auteur") + "."); }
    message("aide-droits", aide.join(" "));
    $("actions-routine").hidden = !d.lancer && !d.couper && !d.supprimer;
  }

  function rendreDetail(r) {
    $("titre-routines").textContent = r.nom;
    entete(r);
    declencheurs(r);
    etapes(r);
    fiche(r);
    actions(r);
  }

  // ------------------------------------------------------------------ navigation
  function montrerListe(focaliser) {
    var avant = courant;
    courant = null;
    fermerFeuille(false);
    $("titre-routines").textContent = "Routines";
    $("vue-detail").hidden = true;
    $("vue-liste").hidden = false;
    message("lancement-routine", "");
    if (routines) { rendreListe(); }
    if (focaliser && avant) {
      var cible = $("liste-routines").querySelector("[data-id='" + avant + "'] .rangee");
      (cible || $("titre-routines")).focus({ preventScroll: true });
    }
  }

  function ouvrir(id, pousser) {
    var r = parId(id);
    if (!r) { return; }
    if (courant !== id) { message("lancement-routine", ""); }
    courant = id;
    message("bandeau-routines", "");
    message("erreur-routines", "");
    $("sous-titre").hidden = true;
    $("vue-liste").hidden = true;
    $("vue-detail").hidden = false;
    $("aide-modifier").hidden = true;
    $("bouton-modifier").setAttribute("aria-expanded", "false");
    rendreDetail(r);
    if (pousser) {
      try { history.pushState({ routine: id }, "", "#" + id); poussee = true; } catch (e) { poussee = false; }
      window.scrollTo(0, 0);
      $("titre-routines").focus({ preventScroll: true });
    }
  }

  function revenir() {
    if (courant && poussee) { history.back(); return; }
    if (courant) {
      try { history.replaceState(null, "", window.location.pathname); } catch (e) { /* adresse inchangée */ }
      montrerListe(true);
      return;
    }
    window.location.href = "/";
  }

  window.addEventListener("popstate", function () {
    var h = (window.location.hash || "").slice(1);
    if (IDENT.test(h) && parId(h)) { ouvrir(h, false); }
    else { poussee = false; montrerListe(true); }
  });

  // ------------------------------------------------------------------ suppression
  function feuilleOuverte() { return !$("feuille-supprimer").hidden; }

  function ouvrirFeuille() {
    var r = parId(courant);
    if (!r || !droits(r).supprimer) { return; }
    focusAvant = document.activeElement;
    $("supp-titre").textContent = "Supprimer la routine " + r.nom + " ?";
    message("erreur-supprimer", "");
    $("confirmer-supprimer").disabled = false;
    $("voile-supprimer").hidden = false;
    $("feuille-supprimer").hidden = false;
    ["contenu-routines", "onglets"].forEach(function (id) {
      var e = $(id);
      if (e) { e.setAttribute("inert", ""); e.setAttribute("aria-hidden", "true"); }
    });
    $("garder-routine").focus({ preventScroll: true });   // le choix sûr reçoit le focus
  }

  function fermerFeuille(rendreFocus) {
    if (!feuilleOuverte()) { return; }
    $("voile-supprimer").hidden = true;
    $("feuille-supprimer").hidden = true;
    ["contenu-routines", "onglets"].forEach(function (id) {
      var e = $(id);
      if (e) { e.removeAttribute("inert"); e.removeAttribute("aria-hidden"); }
    });
    supprimee = null;
    if (rendreFocus && focusAvant && focusAvant.focus) { focusAvant.focus({ preventScroll: true }); }
    focusAvant = null;
  }

  function clavierFeuille(ev) {
    if (ev.key === "Escape") { ev.preventDefault(); fermerFeuille(true); return; }
    if (ev.key !== "Tab") { return; }
    var tous = $("feuille-supprimer").querySelectorAll("button");
    var visibles = [];
    for (var i = 0; i < tous.length; i++) { if (tous[i].offsetParent !== null && !tous[i].disabled) { visibles.push(tous[i]); } }
    if (!visibles.length) { return; }
    var premier = visibles[0], dernier = visibles[visibles.length - 1];
    if (ev.shiftKey && document.activeElement === premier) { ev.preventDefault(); dernier.focus(); }
    else if (!ev.shiftKey && document.activeElement === dernier) { ev.preventDefault(); premier.focus(); }
  }

  function confirmerSuppression() {
    var r = parId(courant);
    if (!r) { fermerFeuille(true); return; }
    if (!envoyer({ type: "routine_supprimer", id: r.id })) {
      message("erreur-supprimer", "La connexion avec l'assistant est coupée. Réessaie dans un instant.");
      return;
    }
    supprimee = r.nom;
    $("confirmer-supprimer").disabled = true;
  }

  function bandeauSuppression(nom) {
    var b = $("bandeau-routines");
    b.textContent = "";
    b.appendChild(icone("ok"));
    var d = el("div", "");
    d.appendChild(el("b", "", "Routine " + nom + " supprimée."));
    d.appendChild(document.createTextNode("Une copie reste dans le journal des routines."));
    b.appendChild(d);
    b.hidden = false;
  }

  // ------------------------------------------------------------------ messages du serveur
  function recu(m) {
    if (m.type === "routines") {
      routines = Array.isArray(m.routines) ? m.routines : [];
      message("erreur-routines", "");
      if (courant) {
        var r = parId(courant);
        if (r) { rendreDetail(r); } else if (!feuilleOuverte()) { revenirApresDisparition(); }
      } else {
        rendreListe();
        var h = (window.location.hash || "").slice(1);
        if (IDENT.test(h) && parId(h)) { ouvrir(h, false); }
      }
    } else if (m.type === "routines_maj") {
      envoyer({ type: "routines" });
    } else if (m.type === "routine_lancee") {
      var texte = m.parole || (m.ok ? "La routine est lancée." : "La routine n'a pas pu aller au bout.");
      if ((m.echecs || []).length) { texte += " En échec : " + m.echecs.join(", ") + "."; }
      message("lancement-routine", texte);
      $("bouton-lancer").disabled = !(parId(courant) || {}).actif;
      envoyer({ type: "routines" });
    } else if (m.type === "routine_ok") {
      if (m.genre === "routine_supprimer") {
        var nom = supprimee || "";
        if (routines) { routines = routines.filter(function (x) { return x.id !== m.id; }); }
        fermerFeuille(false);
        if (poussee) {
          try { history.replaceState(null, "", window.location.pathname); } catch (e) { /* adresse inchangée */ }
          poussee = false;
        }
        montrerListe(false);
        bandeauSuppression(nom);
        $("titre-routines").focus({ preventScroll: true });
      }
      envoyer({ type: "routines" });
    } else if (m.type === "erreur" && typeof m.genre === "string" && m.genre.indexOf("routine") === 0) {
      var t = CAUSES[m.cause] || C.texteErreur(m.cause);
      if (m.genre === "routine_supprimer" && feuilleOuverte()) {
        message("erreur-supprimer", t);
        $("confirmer-supprimer").disabled = false;
        supprimee = null;
        return;
      }
      message("erreur-routines", t);
      if (m.genre === "routines") { $("sous-titre").hidden = true; return; }
      if (m.genre === "routine_lancer") { message("lancement-routine", ""); }
      $("bouton-lancer").disabled = !(parId(courant) || {}).actif;
      envoyer({ type: "routines" });   // l'état affiché a pu changer d'avance (pause), la liste du serveur fait foi
    }
  }

  function revenirApresDisparition() {
    if (poussee) {
      try { history.replaceState(null, "", window.location.pathname); } catch (e) { /* adresse inchangée */ }
      poussee = false;
    }
    montrerListe(false);
    message("erreur-routines", "Cette routine n'existe plus.");
  }

  function connecter() {
    var s = C.ouvrirWs("/ws");
    ws = s;
    s.onopen = function () {
      reconnexion = 0;
      message("erreur-routines", "");
      envoyer({ type: "routines" });
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
      message("erreur-routines", "La connexion avec l'assistant est coupée. Nouvelle tentative.");
      reconnexion = Math.min(reconnexion + 1, 6);
      setTimeout(connecter, 1000 * reconnexion);
    };
  }

  // ------------------------------------------------------------------ commandes
  $("retour").addEventListener("click", revenir);
  $("bouton-lancer").addEventListener("click", function () {
    var r = parId(courant);
    if (!r || !droits(r).lancer || !r.actif) { return; }
    if (envoyer({ type: "routine_lancer", id: r.id })) {
      $("bouton-lancer").disabled = true;
      message("lancement-routine", "Lancement de la routine " + r.nom + ".");
    }
  });
  $("bouton-pause").addEventListener("click", function () {
    var r = parId(courant);
    if (!r || !droits(r).couper) { return; }
    if (envoyer({ type: "routine_activer", id: r.id, actif: !r.actif })) {
      r.actif = !r.actif;
      rendreDetail(r);
    }
  });
  $("bouton-modifier").addEventListener("click", function () {
    var b = $("bouton-modifier");
    var ouvert = b.getAttribute("aria-expanded") === "true";
    b.setAttribute("aria-expanded", ouvert ? "false" : "true");
    $("aide-modifier").hidden = ouvert;
  });
  $("bouton-supprimer").addEventListener("click", ouvrirFeuille);
  $("garder-routine").addEventListener("click", function () { fermerFeuille(true); });
  $("confirmer-supprimer").addEventListener("click", confirmerSuppression);
  $("voile-supprimer").addEventListener("click", function () { fermerFeuille(true); });
  $("feuille-supprimer").addEventListener("keydown", clavierFeuille);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && feuilleOuverte() && !$("feuille-supprimer").contains(document.activeElement)) { fermerFeuille(true); }
  });
  document.addEventListener("visibilitychange", function () { if (!document.hidden && routines) { envoyer({ type: "routines" }); } });
  connecter();
})();
