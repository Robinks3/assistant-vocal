// Client web, Demander : une demande écrite, sa réponse, les actions faites et les étapes (S-W3).
// Le serveur décide de tout : le rôle, la personne et l'essai effectif viennent de la session et de ses réglages.
// Cette page n'envoie que le texte (ou un enregistrement) et le souhait d'essai, et n'affiche que ce qu'elle reçoit.
// La voix : getUserMedia, puis rééchantillonnage ici en 16 kHz mono 16 bits (le format que le serveur exige), 20 secondes
// au plus. Le son part en base64 dans un message WebSocket, il n'est ni gardé ici ni relu après l'envoi.
// Aucun HTML construit par concaténation : createElement et textContent seulement (Trusted Types).
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var C = window.Client;
  var TEXTE_MAX = 400;
  var TAUX = 16000;               // échantillons par seconde envoyés au serveur
  var DUREE_MAX_S = 20;
  var ECH_MAX = TAUX * DUREE_MAX_S;
  var ECH_MIN = TAUX / 5;         // moins de 0,2 s : rien à transcrire
  var BARRES = 13;
  var ETAPES = { entendu: "Entendu", compris: "Compris", fait: "Fait", repondu: "Répondu" };
  var ws = null;
  var essai = false;
  var occupe = false;
  var demande = null;      // { texte, heure } de la demande en cours ou de la dernière réponse
  var etapes = [];         // [{nom, t}] reçues pour la demande en cours
  var identifiant = null;  // identifiant de la demande dans le journal, connu à la réponse
  var reconnexion = 0;
  var delai = null;
  var ecoute = null;       // l'enregistrement en cours, voir demarrerEcoute

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
    $("bouton-micro").disabled = valeur || ecoute !== null;
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
    $("reponse-meta").textContent = (demande ? demande.heure : heureActuelle())
      + (m.saisie === "voix" ? ", dite sur cet appareil" : ", écrite sur cet appareil");
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
    if (m.type === "reponse" && (m.genre === "demande_texte" || m.genre === "demande_voix")) {
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

  // Rééchantillonnage en continu vers 16 kHz : chaque échantillon de sortie est la moyenne des échantillons d'entrée qui
  // tombent dans sa tranche, ce qui suffit pour la parole et évite le repliement le plus gênant.
  function reechantillonneur(tauxEntree) {
    var rapport = tauxEntree / TAUX;
    var somme = 0, nb = 0, vus = 0, sorties = 0;
    return function (entree) {
      var sortie = new Int16Array(Math.ceil(entree.length / rapport) + 1);
      var n = 0;
      for (var i = 0; i < entree.length; i++) {
        somme += entree[i];
        nb += 1;
        vus += 1;
        if (vus >= (sorties + 1) * rapport) {
          var v = Math.max(-1, Math.min(1, somme / nb));
          sortie[n++] = v < 0 ? v * 32768 : v * 32767;
          somme = 0;
          nb = 0;
          sorties += 1;
        }
      }
      return sortie.subarray(0, n);
    };
  }

  function enBase64(pcm) {
    var octets = new Uint8Array(pcm.length * 2);
    var vue = new DataView(octets.buffer);
    for (var i = 0; i < pcm.length; i++) { vue.setInt16(i * 2, pcm[i], true); }
    var texte = "";
    for (var j = 0; j < octets.length; j += 0x8000) {
      texte += String.fromCharCode.apply(null, octets.subarray(j, j + 0x8000));
    }
    return window.btoa(texte);
  }

  function afficherNiveau(niveaux) {
    var barres = $("niveau-micro").children;
    for (var i = 0; i < barres.length; i++) {
      var n = niveaux[niveaux.length - barres.length + i] || 0;
      barres[i].style.setProperty("--h", Math.round(8 + 92 * Math.min(1, n * 4)) + "%");
    }
    $("niveau-micro").classList.toggle("niveau-micro--repos", niveaux.length === 0);
  }

  function refusMicro(erreur) {
    var nom = erreur && erreur.name;
    if (nom === "NotAllowedError" || nom === "SecurityError") {
      return "Le micro est refusé pour ce site. Autorisez-le dans les réglages du navigateur, ou écrivez la demande.";
    }
    if (nom === "NotFoundError" || nom === "OverconstrainedError") {
      return "Aucun micro n'a été trouvé sur cet appareil. Écrivez la demande.";
    }
    return "Le micro ne peut pas démarrer. Écrivez la demande ou recommencez.";
  }

  // Libère le micro, le contexte audio et les écouteurs. Appelée à l'arrêt comme à l'annulation.
  function libererEcoute(e) {
    if (e.minuterie) { clearTimeout(e.minuterie); }
    if (e.noeud) { e.noeud.onaudioprocess = null; try { e.noeud.disconnect(); } catch (x) { /* déjà détaché */ } }
    if (e.source) { try { e.source.disconnect(); } catch (x) { /* déjà détaché */ } }
    if (e.flux) { e.flux.getTracks().forEach(function (p) { p.stop(); }); }
    if (e.contexte && e.contexte.close) { e.contexte.close().catch(function () { /* déjà fermé */ }); }
  }

  function montrerEcoute(visible) {
    $("carte-ecoute").hidden = !visible;
    $("bouton-envoyer").disabled = visible || occupe;   // la saisie écrite reste à portée, mais ne part pas pendant l'écoute
    $("demande-ecrite").readOnly = visible || occupe;
    if (visible) { afficherNiveau([]); }
    var orbe = $("onglet-micro");
    if (orbe) { orbe.setAttribute("aria-pressed", visible ? "true" : "false"); }
  }

  function arreterEcoute(envoyerLeSon) {
    var e = ecoute;
    if (!e) { return; }
    ecoute = null;
    libererEcoute(e);
    montrerEcoute(false);
    $("bouton-micro").disabled = occupe;
    if (!envoyerLeSon || e.annule) { return; }
    var total = Math.min(e.total, ECH_MAX);
    if (total < ECH_MIN) { message("erreur-demande", "L'enregistrement est trop court. Recommencez en parlant plus longtemps."); return; }
    var pcm = new Int16Array(total);
    var pos = 0;
    for (var i = 0; i < e.morceaux.length && pos < total; i++) {
      var m = e.morceaux[i].subarray(0, total - pos);
      pcm.set(m, pos);
      pos += m.length;
    }
    message("erreur-demande", "");
    effacerReponse();
    demande = { texte: "", heure: heureActuelle() };
    if (!envoyer({ type: "demande_voix", pcm: enBase64(pcm), essai: essai })) {
      message("erreur-demande", "La connexion avec l'assistant est coupée. Patientez un instant, puis recommencez.");
      return;
    }
    reglerOccupe(true);
  }

  function traiterBloc(e, bloc) {
    var somme = 0;
    for (var i = 0; i < bloc.length; i++) { somme += bloc[i] * bloc[i]; }
    e.niveaux.push(Math.sqrt(somme / bloc.length));
    if (e.niveaux.length > BARRES) { e.niveaux.shift(); }
    var sortie = e.reechant(bloc);
    e.morceaux.push(sortie);
    e.total += sortie.length;
    afficherNiveau(e.niveaux);
    $("duree-ecoute").textContent = Math.min(DUREE_MAX_S, Math.floor(e.total / TAUX)) + " s sur " + DUREE_MAX_S + " s";
    if (e.total >= ECH_MAX) { arreterEcoute(true); }
  }

  // auto : lancée par l'orbe d'une autre page, sans geste sur celle-ci. Si le navigateur garde le son bloqué faute de
  // geste, l'écoute est abandonnée sans bruit et la page invite à toucher le micro.
  function demarrerEcoute(auto) {
    if (occupe || ecoute) { return; }
    var md = navigator.mediaDevices;
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!md || !md.getUserMedia || !AC) {
      message("erreur-demande", "Ce navigateur ne peut pas enregistrer la voix. Écrivez la demande.");
      return;
    }
    message("erreur-demande", "");
    var e = { annule: false, total: 0, morceaux: [], niveaux: [], flux: null, contexte: null, source: null,
              noeud: null, minuterie: null, reechant: null };
    ecoute = e;
    $("bouton-micro").disabled = true;
    md.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false })
      .then(function (flux) {
        e.flux = flux;
        if (ecoute !== e) { libererEcoute(e); return; }   // annulée pendant la demande d'autorisation
        e.contexte = new AC();                            // taux natif : un contexte à 16 kHz échoue sous Firefox
        e.reechant = reechantillonneur(e.contexte.sampleRate);
        e.source = e.contexte.createMediaStreamSource(flux);
        e.noeud = e.contexte.createScriptProcessor(4096, 1, 1);
        e.noeud.onaudioprocess = function (ev) {
          if (ecoute === e) { traiterBloc(e, ev.inputBuffer.getChannelData(0)); }
        };
        e.source.connect(e.noeud);
        e.noeud.connect(e.contexte.destination);          // sortie muette : le bloc de sortie reste à zéro
        if (e.contexte.state === "suspended") { e.contexte.resume(); }
        if (auto === true) {
          setTimeout(function () {
            if (ecoute !== e || e.contexte.state !== "suspended") { return; }
            annulerEcoute();
            message("erreur-demande", "Touchez le micro pour parler.");
          }, 400);
        }
        e.minuterie = setTimeout(function () { if (ecoute === e) { arreterEcoute(true); } },
                                 (DUREE_MAX_S + 1) * 1000);
        $("duree-ecoute").textContent = "0 s sur " + DUREE_MAX_S + " s";
        montrerEcoute(true);
        $("orbe-ecoute").focus();
      })
      .catch(function (erreur) {
        if (ecoute === e) { ecoute = null; }
        libererEcoute(e);
        montrerEcoute(false);
        $("bouton-micro").disabled = occupe;
        message("erreur-demande", refusMicro(erreur));
      });
  }

  function annulerEcoute() {
    if (!ecoute) { return; }
    ecoute.annule = true;
    arreterEcoute(false);
    $("bouton-micro").focus();
  }

  function envoi(evenement) {
    evenement.preventDefault();
    if (occupe || ecoute) { return; }
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
  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia && (window.AudioContext || window.webkitAudioContext)) {
    $("bouton-micro").hidden = false;
  }
  $("bouton-micro").addEventListener("click", function () { demarrerEcoute(false); });
  // L'orbe de la barre du bas parle et se tait sans quitter la page.
  $("onglet-micro").addEventListener("click", function (ev) {
    ev.preventDefault();
    if (ecoute) { arreterEcoute(true); } else { demarrerEcoute(false); }
  });
  $("orbe-ecoute").addEventListener("click", function () { arreterEcoute(true); });
  $("annuler-ecoute").addEventListener("click", annulerEcoute);
  document.addEventListener("visibilitychange", function () { if (document.hidden) { annulerEcoute(); } });
  window.addEventListener("pagehide", function () {
    annulerEcoute();
    if (delai) { clearTimeout(delai); }
    if (ws && ws.readyState === 1) { envoyer({ type: "desabonner_journal" }); }
  });
  connecter();
  // /ecouter : arrivée par l'orbe d'une autre page, le micro s'ouvre aussitôt et l'adresse redevient /demander.
  if (window.location.pathname === "/ecouter") {
    window.history.replaceState(null, "", "/demander");
    if (!$("bouton-micro").hidden) { demarrerEcoute(true); }
  }
})();
