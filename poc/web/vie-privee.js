// Client web, Vie privée : niveau de partage du journal et effacement des entrées (S-W2).
// Chaque changement passe par la clé d'accès : defi, signature, preuve. Le serveur ne l'accepte pas autrement.
// Aucun HTML construit par concaténation : createElement et textContent seulement (Trusted Types).
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var C = window.Client;
  var MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  var NOMS = { tout: "Tout", action: "Action seulement", discret: "Discret" };
  // Exemples fictifs de ce que voit un autre habitant, jamais une vraie demande.
  var APERCUS = {
    tout: { titre: "Allume la lampe du salon", sous: "Lampe du salon allumée. Réponse : c'est fait." },
    action: { titre: "Une demande", sous: "Lampe du salon allumée" },
    discret: { titre: "Une demande", sous: "Détail non partagé" }
  };
  var ALERTES = {
    tout: "Les autres habitants verront vos phrases et les réponses de l'assistant, avec l'heure et l'appareil.",
    action: "Les actions seules en disent déjà long : une lumière éteinte ou une porte fermée à telle heure révèle vos habitudes, par exemple l'heure du coucher ou votre présence.",
    discret: ""
  };
  var ws = null;
  var courant = "";        // niveau enregistré sur le serveur
  var choisi = "";         // niveau coché
  var attendu = "";        // "niveau" ou "effacer" pendant le parcours de la clé d'accès
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

  function depuis(horodatage) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(horodatage || "");
    if (!m) { return ""; }
    return " depuis le " + (+m[3]) + " " + MOIS[+m[2] - 1] + " à " + m[4] + ":" + m[5];
  }

  function radios() {
    return document.querySelectorAll("#groupe-niveau input[name=niveau]");
  }

  function afficherApercu() {
    var a = APERCUS[choisi];
    $("apercu").hidden = !a;
    if (!a) { return; }
    $("apercu-titre").textContent = a.titre;
    $("apercu-sous").textContent = a.sous;
    message("alerte-niveau", ALERTES[choisi] || "");
    $("bouton-enregistrer").disabled = !choisi || choisi === courant || attendu !== "";
  }

  function cocher(niveau) {
    Array.prototype.forEach.call(radios(), function (r) { r.checked = r.value === niveau; });
    choisi = niveau;
    afficherApercu();
  }

  function recuNiveau(m) {
    courant = m.niveau;
    if (m.conserve_jours) { $("conserve-jours").textContent = String(m.conserve_jours); }
    $("actuel").textContent = "Niveau actuel : " + (NOMS[courant] || courant) + depuis(m.depuis) + ".";
    if (attendu === "niveau") {
      attendu = "";
      message("succes-niveau", "Niveau enregistré : " + (NOMS[courant] || courant) + ".");
    }
    cocher(courant);
  }

  function echec(id, texte) {
    attendu = "";
    message(id, texte);
    $("bouton-enregistrer").disabled = !choisi || choisi === courant;
    $("bouton-effacer-confirmer").disabled = false;
  }

  function lancer(action, cible, idErreur) {
    if (!C.disponible()) {
      message(idErreur, "Ce navigateur ne sait pas utiliser de clé d'accès.");
      return false;
    }
    var msg = { type: "defi", action: action };
    if (cible) { msg.cible = cible; }
    if (!envoyer(msg)) {
      message(idErreur, "La connexion avec l'assistant est coupée. Rechargez la page.");
      return false;
    }
    return true;
  }

  function enregistrer() {
    message("erreur-niveau", "");
    message("succes-niveau", "");
    if (!choisi || choisi === courant) { return; }
    attendu = "niveau";
    $("bouton-enregistrer").disabled = true;
    if (!lancer("vie_privee", choisi, "erreur-niveau")) {
      attendu = "";
      $("bouton-enregistrer").disabled = false;
    }
  }

  function ouvrir(dialogue, focus) {
    if (typeof dialogue.showModal === "function") { dialogue.showModal(); } else { dialogue.setAttribute("open", ""); }
    $(focus).focus();
  }

  function fermer(dialogue) {
    if (typeof dialogue.close === "function") { dialogue.close(); } else { dialogue.removeAttribute("open"); }
  }

  function confirmerEffacement() {
    message("erreur-dialogue-effacer", "");
    attendu = "effacer";
    $("bouton-effacer-confirmer").disabled = true;
    if (!lancer("journal_effacer", null, "erreur-dialogue-effacer")) {
      attendu = "";
      $("bouton-effacer-confirmer").disabled = false;
    }
  }

  function recu(m) {
    if (m.type === "moi") {
      envoyer({ type: "vie_privee" });
    } else if (m.type === "vie_privee") {
      recuNiveau(m);
    } else if (m.type === "defi") {
      C.signer(m.options).then(function (r) {
        envoyer({ type: "preuve", reponse: r });
      }).catch(function (e) {
        echec(attendu === "effacer" ? "erreur-dialogue-effacer" : "erreur-niveau", C.erreurNavigateur(e));
      });
    } else if (m.type === "journal_efface") {
      attendu = "";
      fermer($("dialogue-effacer"));
      $("bouton-effacer-confirmer").disabled = false;
      var n = +m.n || 0;
      message("succes-effacer", n === 0 ? "Aucune entrée à effacer." : n === 1 ? "1 entrée effacée." : n + " entrées effacées.");
    } else if (m.type === "erreur") {
      if (attendu === "effacer") { echec("erreur-dialogue-effacer", C.texteErreur(m.cause)); }
      else if (attendu === "niveau") { echec("erreur-niveau", C.texteErreur(m.cause)); }
      else { message("erreur-niveau", C.texteErreur(m.cause)); }
    }
  }

  function connecter() {
    var s = C.ouvrirWs("/ws");
    ws = s;
    s.onopen = function () {
      reconnexion = 0;
      message("erreur-niveau", "");
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
      message("erreur-niveau", "La connexion avec l'assistant est coupée. Nouvelle tentative.");
      reconnexion = Math.min(reconnexion + 1, 6);
      setTimeout(connecter, 1000 * reconnexion);
    };
  }

  Array.prototype.forEach.call(radios(), function (r) {
    r.addEventListener("change", function () {
      if (r.checked) {
        choisi = r.value;
        message("succes-niveau", "");
        message("erreur-niveau", "");
        afficherApercu();
      }
    });
  });
  $("bouton-enregistrer").addEventListener("click", enregistrer);
  $("bouton-effacer").addEventListener("click", function () {
    message("succes-effacer", "");
    message("erreur-dialogue-effacer", "");
    $("bouton-effacer-confirmer").disabled = false;
    ouvrir($("dialogue-effacer"), "bouton-effacer-annuler");
  });
  $("bouton-effacer-annuler").addEventListener("click", function () { attendu = ""; fermer($("dialogue-effacer")); });
  $("bouton-effacer-confirmer").addEventListener("click", confirmerEffacement);
  $("apercu").hidden = true;
  connecter();
})();
