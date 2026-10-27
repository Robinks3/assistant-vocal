// Client web, page d'accueil minimale (S-W1a). Aucun HTML construit par concaténation : textContent seulement,
// car la politique de contenu exige les Trusted Types (require-trusted-types-for 'script').
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var deux = function (n) { return (n < 10 ? '0' : '') + n; };

  function horloge() {
    var d = new Date();
    var h = deux(d.getHours()) + ':' + deux(d.getMinutes());
    $('heure').textContent = h;
    $('heure').setAttribute('datetime', h);
    $('date-jour').textContent = d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
    var soir = d.getHours() >= 20 || d.getHours() < 7;
    if (soir) { document.documentElement.setAttribute('data-ambiance', 'soir'); }
    else { document.documentElement.removeAttribute('data-ambiance'); }
  }

  function statut(texte, classe) {
    var s = $('statut');
    s.textContent = texte;
    s.className = 'pastille' + (classe ? ' pastille--' + classe : '');
  }

  function etat() {
    fetch('/api/etat', { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      var connecte = r.ok;
      $('carte-appairage').hidden = connecte;
      $('carte-connecte').hidden = !connecte;
      if (connecte) { statut('Connecté', 'ok'); }
      else { statut('Appareil non appairé', 'assistant'); }
    }).catch(function () {
      statut('Serveur injoignable', 'danger');
    });
  }

  horloge();
  setInterval(horloge, 15000);
  etat();
})();
