// Client web, côté propriétaire : ouvrir une association, montrer le code, confirmer avec sa clé d'accès (S-W1b).
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var C = window.Client;
  var ROLES = { invite: "Invité", habitant: "Habitant", administrateur: "Propriétaire" };
  var ETAPES = ["1", "2", "3", "fait", "interrompu"];
  var ws = null;
  var etape = "1";
  var fin = 0;
  var duree = 120;
  var minuteur = null;
  var attendu = "";   // quelle réponse du serveur est attendue : ouvrir, defi ou preuve
  var courante = null;

  function montrer(nom) {
    etape = nom;
    ETAPES.forEach(function (n) { $("etape-" + n).hidden = n !== nom; });
    var titre = $("titre-" + nom);
    titre.setAttribute("tabindex", "-1");
    titre.focus();
    if (nom !== "2") { arreterMinuteur(); }
  }

  function message(id, texte) {
    var e = $(id);
    e.textContent = texte || "";
    e.hidden = !texte;
  }

  function arreterMinuteur() {
    if (minuteur) { clearInterval(minuteur); minuteur = null; }
  }

  function envoyer(objet) {
    if (ws && ws.readyState === 1) { ws.send(JSON.stringify(objet)); return true; }
    return false;
  }

  function compteARebours() {
    arreterMinuteur();
    var barre = $("barre-code");
    barre.max = duree;
    function maj() {
      var reste = (fin - Date.now()) / 1000;
      if (reste <= 0) {
        arreterMinuteur();
        envoyer({ type: "appareils" });
        $("reste-code").textContent = "Le code a expiré";
        barre.value = 0;
        return;
      }
      $("reste-code").textContent = "Valable encore " + C.duree(reste);
      barre.value = reste;
    }
    maj();
    minuteur = setInterval(maj, 1000);
  }

  function afficherCode(m) {
    var code = String(m.code);
    $("nom-code").textContent = m.nom;
    $("code-a").textContent = code.slice(0, 3);
    $("code-b").textContent = code.slice(3);
    duree = m.duree || 120;
    fin = Date.now() + duree * 1000;
    message("statut-code", "");
    var zone = $("zone-qr");
    if (m.qr) {
      $("image-qr").src = m.qr;
      zone.hidden = false;
    } else {
      $("image-qr").removeAttribute("src");
      zone.hidden = true;
    }
    courante = { nom: m.nom, role: m.role };
    montrer("2");
    compteARebours();
  }

  function afficherConfirmation(nom, role, heure) {
    courante = { nom: nom, role: role };
    $("nom-confirmer").textContent = nom;
    $("resume-nom").textContent = nom;
    $("resume-role").textContent = ROLES[role] || role;
    $("resume-heure").textContent = heure ? C.heure(heure) : "";
    message("erreur-confirmer", "");
    $("bouton-confirmer").disabled = false;
    montrer("3");
    $("bouton-confirmer").focus();
  }

  function afficherFait(appareil) {
    var a = appareil || courante || {};
    $("fait-nom").textContent = a.nom || "Le navigateur";
    var role = ROLES[a.role] || "";
    $("fait-detail").textContent = "Rôle " + role + ". " + (a.role === "invite"
      ? "L'accès s'arrête seul au bout de 7 jours."
      : "L'accès s'arrête seul après 30 jours sans connexion.");
    montrer("fait");
  }

  function afficherInterrompu(texte, heure) {
    $("texte-interrompu").textContent = texte;
    var h = $("heure-interrompu");
    h.textContent = heure ? "Tentative à " + C.heure(heure) + ". Un navigateur inconnu, 1 essai." : "";
    h.hidden = !heure;
    montrer("interrompu");
  }

  var RAISONS = {
    concurrent: "Un deuxième navigateur a essayé un code pendant que le premier attendait. Par précaution, le code est détruit.",
    essais: "Trois mauvais codes ont été saisis. Par précaution, le code est détruit.",
    expiree: "Le code a expiré avant la fin de l'association.",
    deconnecte: "Le nouveau navigateur s'est déconnecté avant la fin de l'association.",
    creation_refusee: "La clé d'accès créée par le nouveau navigateur n'a pas été acceptée.",
    remplacee: "Une autre association a été ouverte, celle-ci est remplacée."
  };

  function evenement(m) {
    var e = m.evenement;
    if (e === "appairage_code_saisi" && etape === "2") {
      message("statut-code", "Quelqu'un a saisi le bon code. Le navigateur crée sa clé d'accès.");
    } else if (e === "appairage_attente" && (etape === "2" || etape === "3")) {
      afficherConfirmation(m.nom, m.role, m.heure);
    } else if (e === "appairage_fait" && (etape === "2" || etape === "3")) {
      afficherFait({ nom: m.nom, role: m.role });
    } else if (e === "appairage_ferme" && (etape === "2" || etape === "3")) {
      if (m.raison === "annulee" || m.raison === "refusee") { retourDebut(); return; }
      afficherInterrompu(RAISONS[m.raison] || "L'association a été interrompue.", m.raison === "concurrent" ? m.tentative : null);
    }
  }

  function reponse(m) {
    if (m.type === "evenement") { evenement(m); return; }
    var a = attendu;
    attendu = "";
    if (m.type === "erreur") {
      var texte = C.texteErreur(m.cause);
      if (a === "ouvrir") {
        message("erreur-ouvrir", texte);
        $("bouton-ouvrir").disabled = false;
      } else {
        message("erreur-confirmer", texte);
        $("bouton-confirmer").disabled = false;
      }
    } else if (m.type === "ouverture") {
      $("bouton-ouvrir").disabled = false;
      afficherCode(m);
    } else if (m.type === "defi") {
      C.signer(m.options).then(function (r) {
        attendu = "preuve";
        envoyer({ type: "preuve", reponse: r });
      }).catch(function (e) {
        message("erreur-confirmer", C.erreurNavigateur(e));
        $("bouton-confirmer").disabled = false;
      });
    } else if (m.type === "confirme") {
      afficherFait(m.appareil);
    } else if (m.type === "appareils") {
      var o = m.ouverture || {};
      if (etape === "2" && !o.ouverte) {
        afficherInterrompu("Le code a expiré avant la fin de l'association.", null);
      } else if (etape === "1" && o.ouverte && o.etat === "attente") {
        afficherConfirmation(o.nom, o.role, null);
      }
    }
  }

  function connecter() {
    var s = C.ouvrirWs("/ws");
    ws = s;
    s.onopen = function () { envoyer({ type: "appareils" }); };
    s.onmessage = function (ev) {
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m && typeof m === "object") { reponse(m); }
    };
    s.onclose = function (ev) {
      if (ws !== s) { return; }
      ws = null;
      if (ev.code === 4001) { window.location.replace("/appairage"); return; }
      arreterMinuteur();
      if (etape !== "fait") {
        afficherInterrompu("La connexion avec l'assistant a été coupée. Recommencez avec un nouveau code.", null);
      }
    };
  }

  function retourDebut() {
    message("erreur-ouvrir", "");
    $("bouton-ouvrir").disabled = false;
    montrer("1");
  }

  function ouvrir(ev) {
    ev.preventDefault();
    message("erreur-ouvrir", "");
    var nom = $("champ-nom").value.trim();
    if (!nom) {
      message("erreur-ouvrir", "Donnez un nom à cet appareil.");
      $("champ-nom").focus();
      return;
    }
    var role = document.querySelector("input[name=role]:checked").value;
    $("bouton-ouvrir").disabled = true;
    attendu = "ouvrir";
    if (!envoyer({ type: "ouvrir", nom: nom, role: role })) {
      attendu = "";
      $("bouton-ouvrir").disabled = false;
      message("erreur-ouvrir", "La connexion avec l'assistant est coupée. Rechargez la page.");
    }
  }

  function annuler() {
    envoyer({ type: "annuler" });
    retourDebut();
  }

  function confirmer() {
    message("erreur-confirmer", "");
    $("bouton-confirmer").disabled = true;
    if (!C.disponible()) {
      message("erreur-confirmer", "Ce navigateur ne sait pas utiliser de clé d'accès.");
      $("bouton-confirmer").disabled = false;
      return;
    }
    attendu = "defi";
    if (!envoyer({ type: "defi", action: "confirmer" })) {
      attendu = "";
      message("erreur-confirmer", "La connexion avec l'assistant est coupée. Rechargez la page.");
    }
  }

  function changerRole() {
    var role = document.querySelector("input[name=role]:checked").value;
    $("avertissement-proprietaire").hidden = role !== "administrateur";
  }

  Array.prototype.forEach.call(document.querySelectorAll("input[name=role]"), function (r) {
    r.addEventListener("change", changerRole);
  });
  $("formulaire-ouvrir").addEventListener("submit", ouvrir);
  $("bouton-annuler").addEventListener("click", annuler);
  $("bouton-refuser").addEventListener("click", annuler);
  $("bouton-confirmer").addEventListener("click", confirmer);
  $("bouton-autre").addEventListener("click", function () { $("champ-nom").value = ""; retourDebut(); });
  $("bouton-recommencer").addEventListener("click", retourDebut);
  connecter();
})();
