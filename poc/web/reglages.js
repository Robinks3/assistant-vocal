// Client web, Réglages : appareils associés, révocation, oubli de ce navigateur (S-W1b).
// Aucun HTML construit par concaténation : createElement et textContent seulement (Trusted Types).
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var C = window.Client;
  var ROLES = { invite: "Invité", habitant: "Habitant", administrateur: "Propriétaire" };
  var MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  var ws = null;
  var moi = null;
  var appareils = [];
  var cible = null;       // appareil en cours de révocation
  var attendu = "";       // réponse attendue après un envoi : defi, preuve
  var reconnexion = 0;

  function envoyer(objet) {
    if (ws && ws.readyState === 1) { ws.send(JSON.stringify(objet)); return true; }
    return false;
  }

  function message(id, texte) {
    var e = $(id);
    e.textContent = texte || "";
    e.hidden = !texte;
  }

  function jour(secondes) {
    var d = new Date(secondes * 1000);
    var auj = new Date();
    var h = C.heure(secondes);
    if (d.toDateString() === auj.toDateString()) { return "aujourd'hui à " + h; }
    return d.getDate() + " " + MOIS[d.getMonth()] + " à " + h;
  }

  function ligne(texte, classe) {
    var p = document.createElement("span");
    p.className = classe;
    p.textContent = texte;
    return p;
  }

  function creerLigne(a) {
    var li = document.createElement("li");
    li.className = "appareil";
    var infos = document.createElement("div");
    infos.className = "appareil-infos";
    infos.appendChild(ligne(a.nom, "fort appareil-nom"));
    infos.appendChild(ligne(ROLES[a.role] || a.role, "secondaire"));
    if (a.courant) {
      var p = ligne("Ce navigateur", "pastille pastille--assistant");
      infos.appendChild(p);
    }
    var etat = a.en_ligne ? "Connecté maintenant" : "Dernière connexion " + jour(a.dernier);
    infos.appendChild(ligne(etat, "secondaire"));
    if (a.expire) { infos.appendChild(ligne("Accès jusqu'au " + jour(a.expire), "secondaire")); }
    infos.appendChild(ligne("Identifiant " + a.id, "aide-id dev-seulement"));
    li.appendChild(infos);
    if (moi && moi.proprietaire && !a.courant) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "bouton bouton--danger bouton--appareil";
      b.textContent = "Révoquer";
      b.setAttribute("aria-label", "Révoquer " + a.nom);
      b.addEventListener("click", function () { ouvrirRevocation(a); });
      li.appendChild(b);
    }
    return li;
  }

  function afficherListe() {
    var ul = $("liste-appareils");
    while (ul.firstChild) { ul.removeChild(ul.firstChild); }
    appareils.forEach(function (a) { ul.appendChild(creerLigne(a)); });
    var n = appareils.length;
    $("compte-appareils").textContent = n + (n > 1 ? " appareils" : " appareil");
  }

  function actualiser() {
    if (moi && moi.proprietaire) {
      envoyer({ type: "appareils" });
    } else if (moi) {
      appareils = [Object.assign({ courant: true, en_ligne: true }, moi.appareil)];
      afficherListe();
    }
  }

  // Dialogues : showModal met le reste de la page hors d'atteinte, Échap ferme, le focus part sur Annuler.
  function ouvrir(dialogue, focus) {
    if (typeof dialogue.showModal === "function") { dialogue.showModal(); } else { dialogue.setAttribute("open", ""); }
    $(focus).focus();
  }

  function fermer(dialogue) {
    if (typeof dialogue.close === "function") { dialogue.close(); } else { dialogue.removeAttribute("open"); }
  }

  function ouvrirRevocation(a) {
    cible = a;
    attendu = "";
    $("nom-revoquer").textContent = a.nom;
    message("erreur-revoquer", "");
    $("bouton-revoquer-confirmer").disabled = false;
    ouvrir($("dialogue-revoquer"), "bouton-revoquer-annuler");
  }

  function confirmerRevocation() {
    if (!cible) { return; }
    message("erreur-revoquer", "");
    if (!C.disponible()) {
      message("erreur-revoquer", "Ce navigateur ne sait pas utiliser de clé d'accès.");
      return;
    }
    $("bouton-revoquer-confirmer").disabled = true;
    attendu = "defi";
    if (!envoyer({ type: "defi", action: "revoquer", cible: cible.id })) {
      attendu = "";
      $("bouton-revoquer-confirmer").disabled = false;
      message("erreur-revoquer", "La connexion avec l'assistant est coupée. Rechargez la page.");
    }
  }

  function echecRevocation(texte) {
    attendu = "";
    message("erreur-revoquer", texte);
    $("bouton-revoquer-confirmer").disabled = false;
  }

  function recu(m) {
    if (m.type === "evenement") { actualiser(); return; }
    if (m.type === "moi") {
      moi = m;
      $("version-client").textContent = m.serveur.client;
      $("version-serveur").textContent = m.serveur.version;
      $("date-serveur").textContent = m.serveur.date;
      $("bloc-associer").hidden = !m.proprietaire;
      actualiser();
    } else if (m.type === "appareils") {
      appareils = m.appareils;
      afficherListe();
    } else if (m.type === "defi") {
      C.signer(m.options).then(function (r) {
        attendu = "preuve";
        envoyer({ type: "preuve", reponse: r });
      }).catch(function (e) { echecRevocation(C.erreurNavigateur(e)); });
    } else if (m.type === "revoque") {
      attendu = "";
      cible = null;
      fermer($("dialogue-revoquer"));
      actualiser();
    } else if (m.type === "erreur") {
      if (attendu) { echecRevocation(C.texteErreur(m.cause)); }
      else { message("erreur-liste", C.texteErreur(m.cause)); }
    }
  }

  function connecter() {
    var s = C.ouvrirWs("/ws");
    ws = s;
    s.onopen = function () {
      reconnexion = 0;
      message("erreur-liste", "");
      envoyer({ type: "moi" });
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
      message("erreur-liste", "La connexion avec l'assistant est coupée. Nouvelle tentative.");
      reconnexion = Math.min(reconnexion + 1, 6);
      setTimeout(connecter, 1000 * reconnexion);
    };
  }

  function oublier() {
    message("erreur-oublier", "");
    $("bouton-oublier-confirmer").disabled = true;
    fetch("/oublier", { credentials: "same-origin", cache: "no-store", headers: { "X-Confirme": "oui" } })
      .then(function (r) {
        if (!r.ok) { throw new Error("oubli"); }
        if (ws) { var s = ws; ws = null; s.onclose = null; try { s.close(); } catch (e) { /* déjà fermé */ } }
        window.location.replace("/appairage");
      })
      .catch(function () {
        message("erreur-oublier", "L'oubli a échoué. Rechargez la page et recommencez.");
        $("bouton-oublier-confirmer").disabled = false;
      });
  }

  function afficherDev(actif) {
    $("bascule-dev").setAttribute("aria-checked", actif ? "true" : "false");
    $("dev-etat").textContent = actif ? "Oui" : "Non";
  }

  $("bascule-dev").addEventListener("click", function () { C.reglerDeveloppeur(!C.modeDeveloppeur()); });
  C.surModeDeveloppeur(afficherDev);
  $("bouton-revoquer-annuler").addEventListener("click", function () { cible = null; attendu = ""; fermer($("dialogue-revoquer")); });
  $("bouton-revoquer-confirmer").addEventListener("click", confirmerRevocation);
  $("bouton-oublier").addEventListener("click", function () {
    message("erreur-oublier", "");
    $("avertissement-dernier").hidden = !(moi && moi.dernier_proprietaire);
    $("bouton-oublier-confirmer").disabled = false;
    ouvrir($("dialogue-oublier"), "bouton-oublier-annuler");
  });
  $("bouton-oublier-annuler").addEventListener("click", function () { fermer($("dialogue-oublier")); });
  $("bouton-oublier-confirmer").addEventListener("click", oublier);
  connecter();
})();
