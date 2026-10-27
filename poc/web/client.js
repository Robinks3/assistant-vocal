// Client web, aides partagées par les pages d'appairage et de réglages (S-W1b).
// Aucun HTML construit par concaténation : textContent seulement (Trusted Types exigés par la politique de contenu).
(function () {
  "use strict";

  function deB64u(texte) {
    var b = texte.replace(/-/g, "+").replace(/_/g, "/");
    while (b.length % 4) { b += "="; }
    var brut = atob(b);
    var octets = new Uint8Array(brut.length);
    for (var i = 0; i < brut.length; i++) { octets[i] = brut.charCodeAt(i); }
    return octets.buffer;
  }

  function versB64u(tampon) {
    var octets = new Uint8Array(tampon);
    var s = "";
    for (var i = 0; i < octets.length; i++) { s += String.fromCharCode(octets[i]); }
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function deux(n) { return (n < 10 ? "0" : "") + n; }

  function heure(secondes) {
    var d = new Date(secondes * 1000);
    return deux(d.getHours()) + ":" + deux(d.getMinutes());
  }

  function duree(secondes) {
    var s = Math.max(0, Math.ceil(secondes));
    var m = Math.floor(s / 60);
    return m > 0 ? m + " min " + deux(s % 60) + " s" : s + " s";
  }

  function ouvrirWs(chemin) {
    var protocole = location.protocol === "https:" ? "wss://" : "ws://";
    return new WebSocket(protocole + location.host + chemin);
  }

  function disponible() {
    return !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.create);
  }

  // Options reçues du serveur (champs binaires en base64url) vers les options attendues par le navigateur.
  function optionsCreation(o) {
    return {
      publicKey: {
        challenge: deB64u(o.challenge),
        rp: o.rp,
        user: { id: deB64u(o.user.id), name: o.user.name, displayName: o.user.displayName },
        pubKeyCredParams: o.pubKeyCredParams,
        authenticatorSelection: o.authenticatorSelection,
        attestation: o.attestation,
        timeout: o.timeout,
        excludeCredentials: (o.excludeCredentials || []).map(function (c) {
          return { type: c.type, id: deB64u(c.id) };
        })
      }
    };
  }

  function optionsAssertion(o) {
    return {
      publicKey: {
        challenge: deB64u(o.challenge),
        rpId: o.rpId,
        userVerification: o.userVerification,
        timeout: o.timeout,
        allowCredentials: (o.allowCredentials || []).map(function (c) {
          return { type: c.type, id: deB64u(c.id) };
        })
      }
    };
  }

  function creerCle(options) {
    return navigator.credentials.create(optionsCreation(options)).then(function (c) {
      return {
        id: versB64u(c.rawId),
        clientDataJSON: versB64u(c.response.clientDataJSON),
        attestationObject: versB64u(c.response.attestationObject)
      };
    });
  }

  function signer(options) {
    return navigator.credentials.get(optionsAssertion(options)).then(function (c) {
      return {
        id: versB64u(c.rawId),
        clientDataJSON: versB64u(c.response.clientDataJSON),
        authenticatorData: versB64u(c.response.authenticatorData),
        signature: versB64u(c.response.signature)
      };
    });
  }

  // Texte lisible pour une cause d'erreur du serveur ou du navigateur.
  var CAUSES = {
    role: "Ce rôle n'est pas possible.",
    nom: "Ce nom n'est pas valide. Utilisez des lettres et des chiffres, 40 caractères au plus.",
    droit: "Seul un propriétaire peut faire cette action.",
    limite: "Trop de demandes. Patientez quelques minutes.",
    etat: "L'association n'est plus à cette étape. Recommencez.",
    cible: "Cet appareil n'existe plus.",
    action: "Cette action n'est pas possible.",
    defi: "La demande a expiré. Recommencez.",
    preuve: "La clé d'accès n'a pas été acceptée. Recommencez.",
    inconnu: "Une erreur est survenue. Recommencez."
  };

  function texteErreur(cause) { return CAUSES[cause] || CAUSES.inconnu; }

  function erreurNavigateur(e) {
    if (e && e.name === "NotAllowedError") { return "La clé d'accès a été refusée ou le délai est dépassé."; }
    if (e && e.name === "InvalidStateError") { return "Ce navigateur est déjà associé."; }
    return "La clé d'accès n'a pas pu être utilisée sur ce navigateur.";
  }

  // Mode développeur (client web 0.8.0). Actif par défaut. Coupé, il masque sur toutes les pages ce qui sert à déboguer
  // (numéros de version, durées des étapes, identifiants, compteurs techniques) par l'attribut data-dev="non" de
  // <html> et la classe .dev-seulement. Jamais une information de sécurité ni un message d'erreur utile.
  // Seul usage du stockage local du client web, pour ce réglage, avec repli en mémoire si le navigateur le refuse.
  var CLE_DEV = "modeDeveloppeur";
  var devMemoire = true;
  var ecouteursDev = [];

  function modeDeveloppeur() {
    try {
      var v = window.localStorage.getItem(CLE_DEV);
      if (v === "non") { return false; }
      if (v === "oui") { return true; }
    } catch (e) { return devMemoire; }
    return true;
  }

  function appliquerDev() {
    var actif = modeDeveloppeur();
    document.documentElement.setAttribute("data-dev", actif ? "oui" : "non");
    ecouteursDev.forEach(function (f) { try { f(actif); } catch (e) { /* un écouteur fautif n'arrête pas les autres */ } });
    return actif;
  }

  function reglerDeveloppeur(actif) {
    devMemoire = !!actif;
    try { window.localStorage.setItem(CLE_DEV, actif ? "oui" : "non"); } catch (e) { /* repli en mémoire */ }
    return appliquerDev();
  }

  // [f] est appelée tout de suite, puis à chaque changement (aussi venu d'un autre onglet).
  function surModeDeveloppeur(f) {
    ecouteursDev.push(f);
    try { f(modeDeveloppeur()); } catch (e) { /* idem */ }
  }

  appliquerDev();
  window.addEventListener("storage", function (ev) { if (ev.key === CLE_DEV || ev.key === null) { appliquerDev(); } });

  // Client installable (S-W9, client web 0.11.0). Le service worker /sw.js ne garde que la coquille publique (styles,
  // scripts partagés, icônes, polices, page hors ligne) : aucune page protégée, aucune donnée. Il est inscrit depuis les
  // pages d'une session, et retiré avec tout le cache de l'origine quand le navigateur est oublié ou retiré.
  function serviceWorkerPossible() {
    return !!(window.isSecureContext && navigator.serviceWorker);
  }

  // La politique de contenu exige des Trusted Types pour toute URL de script, celle du service worker comprise. Cette
  // politique n'accepte qu'une seule adresse, /sw.js, et refuse tout le reste.
  var URL_SW = "/sw.js";
  var politiqueSw = null;

  function adresseSw() {
    if (!window.trustedTypes || !window.trustedTypes.createPolicy) { return URL_SW; }
    if (!politiqueSw) {
      politiqueSw = window.trustedTypes.createPolicy("service-worker", {
        createScriptURL: function (u) {
          if (u !== URL_SW) { throw new TypeError("adresse de service worker refusée"); }
          return u;
        }
      });
    }
    return politiqueSw.createScriptURL(URL_SW);
  }

  function installerHorsLigne() {
    if (!serviceWorkerPossible()) { return; }
    try {
      navigator.serviceWorker.register(adresseSw(), { scope: "/" }).catch(function () { /* le client marche sans */ });
    } catch (e) { /* idem */ }
  }

  // Vide le cache et désinscrit le service worker. Ne bloque jamais plus de 1,5 s la suite (changement de page).
  function purgerHorsLigne() {
    var travail = Promise.resolve().then(function () {
      var attente = [];
      var magasin = window.caches;
      if (magasin) {
        attente.push(magasin.keys().then(function (noms) {
          return Promise.all(noms.map(function (nom) { return magasin.delete(nom); }));
        }));
      }
      if (serviceWorkerPossible() && navigator.serviceWorker.getRegistrations) {
        attente.push(navigator.serviceWorker.getRegistrations().then(function (inscriptions) {
          return Promise.all(inscriptions.map(function (i) { return i.unregister(); }));
        }));
      }
      return Promise.all(attente);
    });
    var delai = new Promise(function (fin) { setTimeout(fin, 1500); });
    return Promise.race([travail, delai]).catch(function () { /* rien à purger ou purge refusée */ });
  }

  // Proposition d'installation du navigateur (Chrome, Samsung Internet) : elle peut arriver avant les scripts des
  // pages, elle est donc gardée ici. iPhone n'en envoie jamais.
  var propositionInstallation = null;
  var ecouteursInstallation = [];

  function prevenirInstallation() {
    ecouteursInstallation.forEach(function (f) { try { f(); } catch (e) { /* les autres écouteurs passent */ } });
  }

  window.addEventListener("beforeinstallprompt", function (ev) {
    ev.preventDefault();
    propositionInstallation = ev;
    prevenirInstallation();
  });
  window.addEventListener("appinstalled", function () {
    propositionInstallation = null;
    prevenirInstallation();
  });

  function dejaInstallee() {
    if (navigator.standalone === true) { return true; }
    try { return window.matchMedia("(display-mode: standalone)").matches; } catch (e) { return false; }
  }

  function propositionDisponible() { return propositionInstallation !== null; }

  // Ouvre la proposition du navigateur. Résout vrai si l'installation est acceptée.
  function proposerInstallation() {
    var p = propositionInstallation;
    if (!p) { return Promise.resolve(false); }
    propositionInstallation = null;
    return Promise.resolve(p.prompt()).then(function () { return p.userChoice; }).then(function (choix) {
      return !!(choix && choix.outcome === "accepted");
    }).catch(function () { return false; }).then(function (accepte) {
      prevenirInstallation();
      return accepte;
    });
  }

  // [f] est appelée à chaque changement de la proposition (reçue, utilisée, application installée).
  function surInstallation(f) { ecouteursInstallation.push(f); }

  // L'écran d'association n'est ouvert que par un navigateur sans accès : rien ne doit y rester. L'accueil inscrit le
  // service worker lui-même, une fois la session vérifiée (app.js).
  var chemin = (window.location && window.location.pathname) || "";
  if (chemin === "/appairage") {
    purgerHorsLigne();
  } else if (chemin && chemin !== "/" && chemin !== "/hors-ligne") {
    installerHorsLigne();
  }

  window.Client = {
    deB64u: deB64u, versB64u: versB64u, heure: heure, duree: duree, ouvrirWs: ouvrirWs, disponible: disponible,
    creerCle: creerCle, signer: signer, texteErreur: texteErreur, erreurNavigateur: erreurNavigateur,
    modeDeveloppeur: modeDeveloppeur, reglerDeveloppeur: reglerDeveloppeur, surModeDeveloppeur: surModeDeveloppeur,
    installerHorsLigne: installerHorsLigne, purgerHorsLigne: purgerHorsLigne, dejaInstallee: dejaInstallee,
    propositionDisponible: propositionDisponible, proposerInstallation: proposerInstallation, surInstallation: surInstallation
  };
})();
