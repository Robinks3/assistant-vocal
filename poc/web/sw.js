// Client web, service worker de la coquille (S-W9, client web 0.11.0). Servi à /sw.js par serveur_web.py, qui
// remplace le gabarit de version : le nom du cache suit donc la version du client sans être écrit deux fois.
// Listes blanches explicites : seuls les fichiers publics de COQUILLE passent par le cache, seules les pages de PAGES
// reçoivent la page hors ligne quand le réseau manque. Tout le reste (WebSocket, requêtes autres que GET, /api,
// /appairage et ses échanges, /oublier, scripts des pages protégées, vue 3D) n'est jamais touché : le navigateur le
// traite comme s'il n'y avait pas de service worker. Aucune donnée, aucune page protégée n'est mise en cache.
"use strict";

var VERSION = "{{version_client}}";
var CACHE = "coquille-" + VERSION;
var HORS_LIGNE = "/hors-ligne";

// Fichiers publics précachés à l'installation, servis réseau d'abord et cache en repli.
var COQUILLE = [
  "/app.css",
  "/app.js",
  "/client.js",
  "/hors-ligne",
  "/icones/icone-192.png",
  "/icones/icone-512.png",
  "/icones/icone-masquable-512.png",
  "/icones/apple-touch-icon.png",
  "/polices/instrument_sans_400.woff2",
  "/polices/instrument_sans_500.woff2",
  "/polices/big_shoulders_display_300.woff2"
];

// Pages HTML ouvertes par navigation : toujours demandées au réseau, jamais mises en cache. Sans réseau, la page hors
// ligne les remplace. Une redirection du serveur (session absente ou révoquée) est rendue telle quelle.
var PAGES = [
  "/",
  "/reglages",
  "/journal",
  "/vie-privee",
  "/demander",
  "/ecouter",
  "/maison",
  "/meteo",
  "/routines",
  "/associer"
];

function dansListe(liste, chemin) { return liste.indexOf(chemin) !== -1; }

self.addEventListener("install", function (ev) {
  ev.waitUntil(caches.open(CACHE).then(function (cache) {
    return cache.addAll(COQUILLE.map(function (chemin) { return new Request(chemin, { cache: "reload" }); }));
  }).then(function () { return self.skipWaiting(); }));
});

// Activation : tout autre cache de l'origine (version précédente du client) est supprimé.
self.addEventListener("activate", function (ev) {
  ev.waitUntil(caches.keys().then(function (noms) {
    return Promise.all(noms.filter(function (nom) { return nom !== CACHE; }).map(function (nom) {
      return caches.delete(nom);
    }));
  }).then(function () { return self.clients.claim(); }));
});

function depuisCache(chemin) {
  return caches.open(CACHE).then(function (cache) { return cache.match(chemin); }).then(function (r) {
    return r || Response.error();
  });
}

// La copie ne va que dans un cache encore présent : un cache vidé par « Oublier ce navigateur » n'est jamais recréé
// par la page qui reste contrôlée jusqu'à son départ.
function fichierCoquille(ev, chemin) {
  return fetch(ev.request).then(function (reponse) {
    if (reponse.status === 200 && reponse.type === "basic") {
      var copie = reponse.clone();
      ev.waitUntil(caches.has(CACHE).then(function (present) {
        if (!present) { return null; }
        return caches.open(CACHE).then(function (cache) { return cache.put(chemin, copie); });
      }));
    }
    return reponse;
  }).catch(function () { return depuisCache(chemin); });
}

function pageReseau(ev) {
  return fetch(ev.request).catch(function () { return depuisCache(HORS_LIGNE); });
}

self.addEventListener("fetch", function (ev) {
  var requete = ev.request;
  if (requete.method !== "GET") { return; }
  var url = new URL(requete.url);
  if (url.origin !== self.location.origin) { return; }
  if (!url.search && dansListe(COQUILLE, url.pathname)) {
    ev.respondWith(fichierCoquille(ev, url.pathname));
  } else if (requete.mode === "navigate" && dansListe(PAGES, url.pathname)) {
    ev.respondWith(pageReseau(ev));
  }
});
