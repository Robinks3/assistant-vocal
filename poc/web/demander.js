// Client web, Demander : une demande écrite, sa réponse, les actions faites et les étapes (S-W3).
// Le serveur décide de tout : le rôle, la personne et l'essai effectif viennent de la session et de ses réglages.
// Cette page n'envoie que le texte et le souhait d'essai, et n'affiche que ce qu'elle reçoit.
// Aucun HTML construit par concaténation : createElement et textContent seulement (Trusted Types).
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var C = window.Client;
  var TEXTE_MAX = 400;
  var ETAPES = { entendu: "Entendu", compris: "Compris", fait: "Fait", repondu: "Répondu" };
  var ws = null;
  var essai = false;
  var occupe = false;
  var demande = null;      // { texte, heure } de la demande en cours ou de la dernière réponse
  var etapes = [];         // [{nom, t}] reçues pour la demande en cours
  var identifiant = null;  // identifiant de la demande dans le journal, connu à la réponse
  var reconnexion = 0;
  var delai = null;

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

  function vider(e) { while (e.firstChild) { e.removeChild(e.firstChild); } }

  function message(id, texte) {
    var e = $(id);
    e.textContent = texte || "";
    e.hidden = !texte;
  }

  function deux(n) { return (n < 10 ? "0" : "") + n; }

  function heureActuelle() {
    var d = new Date();
    return deux(d.getHours()) + ":" + deux(d.getMinutes());
  }

  // Refus propres aux demandes. « droit » a ici un autre sens que dans Réglages, d'où une table à part.
  var REFUS = {
    droit: "Ce navigateur n'a pas le droit de faire cette demande.",
    quota: "Vous avez atteint la limite de demandes de ce navigateur.",
    texte: "Écrivez une demande de 400 caractères au plus.",
    audio: "L'enregistrement n'est pas utilisable. Recommencez.",
    occupe: "Une demande est déjà en cours. Attendez sa réponse.",
    indisponible: "L'assistant ne peut pas répondre pour le moment.",
    transcription: "La voix n'a pas pu être transcrite. Écrivez la demande ou recommencez."
  };

  function texteRefus(m) {
    var t = REFUS[m.cause] || C.texteErreur(m.cause);
    if (m.cause === "quota" && typeof m.attente_s === "number" && m.attente_s > 0) {
      t += " Vous pourrez demander de nouveau dans " + C.duree(m.attente_s) + ".";
    }
    return t;
  }

  function reglerOccupe(valeur) {
    occupe = valeur;
    $("bouton-envoyer").disabled = valeur;
    $("demande-ecrite").readOnly = valeur;
    $("bascule-essai").disabled = valeur;
    var statut = $("statut-demande");
    statut.textContent = valeur ? "La demande est en cours de traitement." : "";
    statut.hidden = !valeur;
  }

  function reglerEssai(valeur) {
    essai = valeur;
    $("bascule-essai").setAttribute("aria-checked", valeur ? "true" : "false");
    $("essai-etat").textContent = valeur ? "Oui" : "Non";
    $("bandeau-essai").hidden = !valeur;
  }

  function afficherEtapes() {
    var liste = $("etapes-demande");
    vider(liste);
    etapes.forEach(function (x) {
      var li = el("li", "etape");
      li.appendChild(el("span", "fort", ETAPES[x.nom] || String(x.nom)));
      li.appendChild(el("span", "secondaire chiffres", String(x.t || "")));
      liste.appendChild(li);
    });
    $("carte-etapes").hidden = etapes.length === 0;
  }

  function effacerReponse() {
    ["carte-reponse", "carte-actions", "liens-reponse"].forEach(function (id) { $(id).hidden = true; });
    $("reponse-essai").hidden = true;
    vider($("liste-actions"));
    etapes = [];
    identifiant = null;
    afficherEtapes();
  }

  function afficherReponse(m) {
    $("reponse-demande").textContent = "« " + (m.texte || (demande && demande.texte) || "") + " »";
    $("reponse-meta").textContent = (demande ? demande.heure : heureActuelle()) + ", écrite sur cet appareil";
    $("reponse-texte").textContent = m.reponse || "";
    $("reponse-essai").hidden = !m.essai;
    var liste = $("liste-actions");
    vider(liste);
    var actions = Array.isArray(m.actions) ? m.actions : [];
    actions.forEach(function (a) { liste.appendChild(el("li", "", String(a))); });
    $("carte-actions").hidden = actions.length === 0;
    $("carte-reponse").hidden = false;
    $("liens-reponse").hidden = false;
    identifiant = m.id || null;
    if (m.erreur) { message("erreur-demande", "L'assistant a rencontré une erreur en traitant cette demande."); }
    afficherEtapes();
  }

  // Étapes poussées au journal : le serveur ne les envoie qu'à l'auteur de la demande.
  function etape(m) {
    if (!occupe) { return; }
    etapes.push({ nom: m.nom, t: m.t });
    afficherEtapes();
  }

  // Quand l'entrée du journal arrive, ses étapes complètes remplacent celles reçues en direct.
  function ajoutJournal(m) {
    var e = m.entree;
    if (!e || typeof e !== "object" || !identifiant || e.id !== identifiant) { return; }
    if (e.mien && Array.isArray(e.etapes) && e.etapes.length) {
      etapes = e.etapes.map(function (x) { return { nom: x.nom, t: x.t }; });
      afficherEtapes();
    }
  }

  function recu(m) {
    if (m.type === "reponse" && m.genre === "demande_texte") {
      reglerOccupe(false);
      message("erreur-demande", "");
      afficherReponse(m);
      $("demande-ecrite").value = "";
    } else if (m.type === "erreur") {
      if (typeof m.genre === "string" && m.genre.indexOf("demande_") === 0) {
        reglerOccupe(false);
        message("erreur-demande", texteRefus(m));
      }
    } else if (m.type === "journal_etape") {
      etape(m);
    } else if (m.type === "journal_ajout") {
      ajoutJournal(m);
    }
  }

  function envoi(evenement) {
    evenement.preventDefault();
    if (occupe) { return; }
    var champ = $("demande-ecrite");
    var texte = champ.value.trim();
    if (!texte || texte.length > TEXTE_MAX) {
      message("erreur-demande", REFUS.texte);
      champ.focus();
      return;
    }
    message("erreur-demande", "");
    effacerReponse();
    demande = { texte: texte, heure: heureActuelle() };
    if (!envoyer({ type: "demande_texte", texte: texte, essai: essai })) {
      message("erreur-demande", "La connexion avec l'assistant est coupée. Patientez un instant, puis recommencez.");
      return;
    }
    reglerOccupe(true);
  }

  function connecter() {
    var s = C.ouvrirWs("/ws");
    ws = s;
    s.onopen = function () {
      reconnexion = 0;
      message("erreur-demande", "");
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
      if (occupe) { reglerOccupe(false); }
      message("erreur-demande", "La connexion avec l'assistant est coupée. Nouvelle tentative.");
      reconnexion = Math.min(reconnexion + 1, 6);
      delai = setTimeout(connecter, 1000 * reconnexion);
    };
  }

  $("formulaire-demande").addEventListener("submit", envoi);
  $("bascule-essai").addEventListener("click", function () { reglerEssai(!essai); });
  window.addEventListener("pagehide", function () {
    if (delai) { clearTimeout(delai); }
    if (ws && ws.readyState === 1) { envoyer({ type: "desabonner_journal" }); }
  });
  connecter();
})();
