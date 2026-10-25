"use strict";
// Page d'administration. Tout texte venu du serveur passe par textContent, jamais par du balisage.
// Adresses relatives seulement : sous Ingress, la page vit sous un préfixe imprévisible.
(function () {
  var ROLES = { administrateur: "Administrateur", habitant: "Habitant", partage: "Partage", invite: "Invité" };
  var CHANGEABLES = ["habitant", "partage", "invite"];
  var CAUSES = { jeton: "Jeton inconnu", reseau: "Réseau non autorisé", origine: "Origine refusée", limite: "Trop d'essais" };
  var ws = null, essai = 0, retard = null, invitation = null, fin = 0, minuteur = null, confirmation = null;
  var $ = function (id) { return document.getElementById(id); };

  function el(nom, classe, texte) {
    var e = document.createElement(nom);
    if (classe) e.className = classe;
    if (texte !== undefined) e.textContent = texte;
    return e;
  }
  function bouton(texte, classe, action) {
    var b = el("button", classe, texte);
    b.type = "button";
    b.addEventListener("click", action);
    return b;
  }
  function envoyer(msg) {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg));
  }
  function bandeau(texte, erreur) {
    var b = $("bandeau");
    b.textContent = texte || "";
    b.hidden = !texte;
    b.className = erreur ? "bandeau erreur" : "bandeau";
    b.setAttribute("role", erreur ? "alert" : "status");
  }
  function chiffres(code) { return "Code " + String(code).split("").join(" "); }
  function date(iso) {
    if (!iso) return "jamais connecté";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
  }
  function dateCreation(iso) {
    var d = new Date(iso);
    return isNaN(d.getTime()) ? "" : d.toLocaleDateString("fr-FR", { dateStyle: "medium" });
  }
  function duree(s) {
    s = Math.max(0, Math.floor(s));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  function demandes(liste) {
    var ul = $("demandes");
    ul.replaceChildren();
    $("bloc-demandes").hidden = !liste.length;
    liste.forEach(function (d) {
      var li = el("li");
      var tete = el("div", "carte-tete");
      tete.appendChild(el("span", "nom", d.nom || "Appareil sans nom"));
      var codeDemande = el("span", "code-demande", d.code || "");
      if (d.code) codeDemande.setAttribute("aria-label", chiffres(d.code));
      tete.appendChild(codeDemande);
      li.appendChild(tete);
      li.appendChild(el("p", "discret", "Adresse : " + (d.ip || "inconnue")));
      var actions = el("div", "actions");
      var sel = roleSelect("habitant");
      sel.setAttribute("aria-label", "Rôle de " + (d.nom || "l'appareil"));
      actions.appendChild(sel);
      var accepter = bouton("Accepter", "principal", function () {
        envoyer({ type: "appairer", id: d.id, role: sel.value });
      });
      accepter.setAttribute("aria-label", "Accepter " + (d.nom || "l'appareil"));
      actions.appendChild(accepter);
      var refuser = bouton("Refuser", "danger", function () {
        envoyer({ type: "refuser_appareil", id: d.id });
      });
      refuser.setAttribute("aria-label", "Refuser " + (d.nom || "l'appareil"));
      actions.appendChild(refuser);
      li.appendChild(actions);
      ul.appendChild(li);
    });
  }

  function roleSelect(courant) {
    var s = el("select");
    CHANGEABLES.forEach(function (r) {
      var o = el("option", "", ROLES[r]);
      o.value = r;
      s.appendChild(o);
    });
    s.value = CHANGEABLES.indexOf(courant) >= 0 ? courant : "habitant";
    return s;
  }

  function appareils(liste, focus) {
    var ul = $("appareils");
    var cle = focus || (document.activeElement && document.activeElement.dataset && document.activeElement.dataset.k);
    ul.replaceChildren();
    ul.hidden = !liste.length;
    setTimeout(function () {
      var cible = cle && ul.querySelector('[data-k="' + cle + '"]');
      if (cible) cible.focus();
    }, 0);
    $("aucun-appareil").hidden = liste.length > 0;
    liste.forEach(function (a) {
      var li = el("li");
      var tete = el("div", "carte-tete");
      tete.appendChild(el("span", "nom", a.nom || "Appareil sans nom"));
      li.appendChild(tete);
      li.appendChild(el("p", "discret", "Créé le " + dateCreation(a.cree) + ". Dernière connexion : " + date(a.dernier) + "."));
      var actions = el("div", "actions");
      if (a.role === "administrateur") {
        actions.appendChild(el("span", "", "Rôle : " + ROLES.administrateur));
      } else {
        var sel = roleSelect(a.role);
        sel.setAttribute("aria-label", "Rôle de " + (a.nom || "l'appareil"));
        sel.addEventListener("change", function () {
          envoyer({ type: "changer_role", id: a.id, role: sel.value });
        });
        actions.appendChild(sel);
      }
      var nom = a.nom || "cet appareil";
      if (confirmation === a.id) {
        var question = el("span", "", a.role === "administrateur"
          ? "Révoquer " + nom + " ? Tu perdras l'accès à cette page."
          : "Révoquer " + nom + " ?");
        question.setAttribute("role", "alert");
        actions.appendChild(question);
        var oui = bouton("Oui, révoquer", "danger plein", function () {
          confirmation = null;
          envoyer({ type: "revoquer", id: a.id });
        });
        oui.setAttribute("aria-label", "Oui, révoquer " + nom);
        actions.appendChild(oui);
        var garder = bouton("Garder", "", function () {
          confirmation = null; appareils(liste, "rev-" + a.id);
        });
        garder.setAttribute("aria-label", "Garder " + nom);
        garder.dataset.k = "garder-" + a.id;
        actions.appendChild(garder);
      } else {
        var rev = bouton("Révoquer", "danger", function () {
          confirmation = a.id; appareils(liste, "garder-" + a.id);
        });
        rev.setAttribute("aria-label", "Révoquer " + nom);
        rev.dataset.k = "rev-" + a.id;
        actions.appendChild(rev);
      }
      li.appendChild(actions);
      ul.appendChild(li);
    });
  }

  function simples(idListe, idVide, textes) {
    var ul = $(idListe);
    ul.replaceChildren();
    $(idVide).hidden = textes.length > 0;
    textes.forEach(function (t) { ul.appendChild(el("li", "", t)); });
  }

  function vue(m) {
    demandes(m.attente || []);
    appareils(m.appareils || []);
    simples("jetons", "aucun-jeton", (m.jetons_fixes || []).map(String));
    simples("refus", "aucun-refus", (m.refus || []).slice().reverse().map(function (r) {
      return (r.heure ? date(r.heure) + " : " : "") + (CAUSES[r.cause] || r.cause || "refus") + " depuis " + (r.ip || "adresse inconnue");
    }));
    if (m.invitation) {
      if (!invitation) afficherInvitation({ role: m.invitation.role, code: null, expire: m.invitation.restant });
    } else if (invitation) {
      masquerInvitation();
    }
  }

  function afficherInvitation(m) {
    invitation = m;
    fin = Date.now() + m.expire * 1000;
    $("formulaire-ajout").hidden = true;
    $("invitation").hidden = false;
    var codeInv = $("code-invitation");
    codeInv.textContent = m.code ? m.code.replace(/(\d{3})(\d{3})/, "$1 $2") : "Un code est déjà ouvert sur un autre écran. Annule-le pour en créer un nouveau.";
    if (m.code) codeInv.setAttribute("aria-label", chiffres(m.code)); else codeInv.removeAttribute("aria-label");
    if (m.code) {
      bandeau("Code créé, valable " + Math.round(m.expire / 60) + " minutes.");
      codeInv.tabIndex = -1;
      codeInv.focus();
    }
    var qr = $("qr");
    if (m.qr && m.qr.indexOf("data:image/") === 0) {
      qr.src = m.qr;
      qr.hidden = false;
      $("explication-qr").hidden = true;
    } else {
      qr.removeAttribute("src");
      qr.hidden = true;
      $("explication-qr").hidden = false;
    }
    clearInterval(minuteur);
    minuteur = setInterval(tic, 1000);
    tic();
  }
  function tic() {
    var reste = (fin - Date.now()) / 1000;
    if (reste <= 0) { masquerInvitation(); bandeau("Le code a expiré. Crée-en un nouveau."); return; }
    $("compte-a-rebours").textContent = "Expire dans " + duree(reste);
  }
  function masquerInvitation() {
    invitation = null;
    clearInterval(minuteur);
    $("invitation").hidden = true;
    $("formulaire-ajout").hidden = false;
    $("code-invitation").textContent = "";
    $("qr").removeAttribute("src");
  }

  function recu(m) {
    if (m.etat === "session") {
      $("titre").textContent = (m.assistant || "Assistant") + " : administration";
      $("sous-titre").textContent = "Connecté en tant que " + (m.utilisateur || "administrateur");
      $("infos").textContent = "Serveur " + (m.version || "");
      document.title = "Administration de " + (m.assistant || "l'assistant");
      bandeau("");
    } else if (m.etat === "appareils") {
      vue(m);
    } else if (m.etat === "invitation") {
      afficherInvitation(m);
    } else if (m.etat === "refuse") {
      bandeau(m.message || "Action refusée.", true);
    }
  }

  function connecter() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var base = location.pathname.replace(/[^\/]*$/, "");
    ws = new WebSocket(proto + "//" + location.host + base + "ws");
    ws.onopen = function () { essai = 0; };
    ws.onmessage = function (e) {
      try { recu(JSON.parse(e.data)); } catch (x) { /* message illisible ignoré */ }
    };
    ws.onclose = function (e) {
      $("sous-titre").textContent = "Déconnecté";
      if (e.code === 4003) { bandeau("Accès refusé. Recharge la page depuis Home Assistant.", true); return; }
      essai += 1;
      bandeau("Connexion perdue, nouvel essai...");
      clearTimeout(retard);
      retard = setTimeout(connecter, Math.min(10000, 1000 * essai));
    };
  }

  $("creer-code").addEventListener("click", function () {
    envoyer({ type: "inviter", role: $("role-invitation").value });
  });
  $("annuler-code").addEventListener("click", function () {
    envoyer({ type: "annuler_invitation" });
    masquerInvitation();
    $("creer-code").focus();
  });
  connecter();
})();
