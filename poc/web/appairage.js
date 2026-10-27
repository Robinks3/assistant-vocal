// Client web, association d'un nouveau navigateur (S-W1b).
// Le code à 6 chiffres part vers /ws/appairage, la clé d'accès est créée par le navigateur, le propriétaire confirme
// de son côté, puis un ticket à usage unique s'échange contre le cookie de session (/appairage/fin).
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var C = window.Client;
  var ws = null;
  var etape = "code";
  var echeance = 0;
  var minuteur = null;

  function montrer(nom) {
    etape = nom;
    ["code", "attente", "interrompu", "fait"].forEach(function (n) { $("etape-" + n).hidden = n !== nom; });
    var titre = { code: "titre-code", attente: "titre-attente", interrompu: "titre-interrompu", fait: "titre-fait" }[nom];
    $(titre).setAttribute("tabindex", "-1");
    $(titre).focus();
  }

  function erreurCode(texte) {
    var e = $("erreur-code");
    e.textContent = texte || "";
    e.hidden = !texte;
  }

  function arreterMinuteur() {
    if (minuteur) { clearInterval(minuteur); minuteur = null; }
    $("reste-attente").textContent = "";
  }

  function compteARebours(secondes) {
    arreterMinuteur();
    echeance = Date.now() + secondes * 1000;
    function maj() {
      var reste = (echeance - Date.now()) / 1000;
      $("reste-attente").textContent = reste > 0 ? "Encore " + C.duree(reste) : "";
    }
    maj();
    minuteur = setInterval(maj, 1000);
  }

  function fermer() {
    arreterMinuteur();
    if (ws) {
      var s = ws;
      ws = null;
      s.onclose = null;
      try { s.close(); } catch (e) { /* déjà fermé */ }
    }
  }

  function interrompu(texte) {
    fermer();
    $("texte-interrompu").textContent = texte;
    montrer("interrompu");
  }

  function terminer(ticket) {
    fermer();
    montrer("fait");
    fetch("/appairage/fin", { credentials: "same-origin", cache: "no-store", headers: { "X-Ticket": ticket } })
      .then(function (r) {
        if (!r.ok) { throw new Error("ticket"); }
        window.location.replace("/reglages");
      })
      .catch(function () {
        interrompu("L'association a échoué au dernier moment. Demandez un nouveau code au propriétaire.");
      });
  }

  function creation(options) {
    $("texte-attente").textContent = "Le code est bon. Validez la création de la clé d'accès sur cet appareil.";
    $("etat-attente").textContent = "Création de la clé";
    montrer("attente");
    C.creerCle(options).then(function (reponse) {
      if (!ws) { return; }
      $("texte-attente").textContent = "Le code est bon. Le propriétaire doit encore confirmer avec sa clé d'accès. Gardez cette page ouverte.";
      $("etat-attente").textContent = "Confirmation en cours";
      reponse.type = "creation";
      ws.send(JSON.stringify(reponse));
    }).catch(function (e) {
      interrompu(C.erreurNavigateur(e) + " Demandez un nouveau code au propriétaire.");
    });
  }

  function recu(evenement) {
    var m;
    try { m = JSON.parse(evenement.data); } catch (e) { return; }
    if (!m || typeof m !== "object") { return; }
    if (m.etat === "code_refuse") {
      var n = m.restant;
      erreurCode("Ce code n'est pas le bon. Il vous reste " + n + (n > 1 ? " essais" : " essai") + ". Vérifiez les chiffres affichés chez le propriétaire.");
      $("bouton-code").disabled = false;
      $("champ-code").focus();
    } else if (m.etat === "creation") {
      creation(m.options);
    } else if (m.etat === "attente") {
      compteARebours(Math.max(1, m.expire - Date.now() / 1000));
    } else if (m.etat === "fait" && m.ticket) {
      terminer(m.ticket);
    } else if (m.etat === "limite") {
      interrompu("Trop d'essais. Patientez une dizaine de minutes avant de recommencer.");
    } else if (m.etat === "interrompu") {
      interrompu("Un deuxième navigateur a essayé un code, le délai est dépassé ou la clé a été refusée. Par précaution, le code est détruit. Demandez un nouveau code au propriétaire.");
    } else if (m.etat === "erreur") {
      interrompu("Cette étape n'est pas possible. Demandez un nouveau code au propriétaire.");
    }
  }

  function envoyerCode(code) {
    fermer();
    var s = C.ouvrirWs("/ws/appairage");
    ws = s;
    s.onmessage = recu;
    s.onopen = function () { s.send(JSON.stringify({ type: "code", code: code })); };
    s.onclose = function () {
      if (ws !== s) { return; }
      ws = null;
      if (etape === "code") {
        erreurCode("La connexion avec l'assistant a été coupée. Réessayez.");
        $("bouton-code").disabled = false;
      } else if (etape === "attente") {
        interrompu("La connexion avec l'assistant a été coupée. Demandez un nouveau code au propriétaire.");
      }
    };
  }

  function envoi(e) {
    e.preventDefault();
    var code = $("champ-code").value.replace(/\s+/g, "");
    erreurCode("");
    if (!/^[0-9]{6}$/.test(code)) {
      erreurCode("Saisissez les 6 chiffres du code.");
      $("champ-code").focus();
      return;
    }
    if (!C.disponible()) {
      erreurCode("Ce navigateur ne sait pas créer de clé d'accès, ou la page n'est pas ouverte en connexion sécurisée.");
      return;
    }
    $("bouton-code").disabled = true;
    envoyerCode(code);
  }

  function annuler() {
    fermer();
    $("champ-code").value = "";
    erreurCode("");
    $("bouton-code").disabled = false;
    montrer("code");
  }

  function reprendre() {
    $("champ-code").value = "";
    erreurCode("");
    $("bouton-code").disabled = false;
    montrer("code");
  }

  // Un code passé dans l'adresse (QR code) préremplit le champ, puis l'adresse est nettoyée.
  var depart = /^#code=([0-9]{6})$/.exec(window.location.hash);
  if (depart) {
    $("champ-code").value = depart[1];
    window.history.replaceState(null, "", window.location.pathname);
  }
  $("formulaire-code").addEventListener("submit", envoi);
  $("bouton-annuler").addEventListener("click", annuler);
  $("bouton-reprendre").addEventListener("click", reprendre);
  window.addEventListener("pagehide", fermer);
})();
