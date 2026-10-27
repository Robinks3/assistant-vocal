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

  window.Client = {
    deB64u: deB64u, versB64u: versB64u, heure: heure, duree: duree, ouvrirWs: ouvrirWs, disponible: disponible,
    creerCle: creerCle, signer: signer, texteErreur: texteErreur, erreurNavigateur: erreurNavigateur,
    modeDeveloppeur: modeDeveloppeur, reglerDeveloppeur: reglerDeveloppeur, surModeDeveloppeur: surModeDeveloppeur
  };
})();
