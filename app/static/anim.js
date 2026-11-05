// NFL Gameday — animations (Motion, https://motion.dev, vendor/motion.js).
//
// Style voulu : discret. Fondus courts (200 à 400 ms), léger glissement,
// aucun rebond. Tout est optionnel : si Motion n'est pas chargé, ou si
// l'utilisateur a demandé moins d'animations (prefers-reduced-motion),
// chaque fonction se contente de ne rien faire et le contenu s'affiche tel quel.
//
// API exposée à app.js (window.GamedayAnim) :
//   leave(view)   avant un changement de page : fondu sortant de la vue
//   enter(view)   après le rendu final d'une page : fondu entrant, cascade
//                 des cartes, compteurs sur les scores et les stats, survol
"use strict";

(function () {
  const M = window.Motion;
  const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const reduced = () => !M || !!mq?.matches;

  // Motion lui-même : animations coupées si l'utilisateur le demande,
  // y compris quand le réglage change pendant que la page est ouverte.
  const syncGlobal = () => { if (M?.MotionGlobalConfig) M.MotionGlobalConfig.skipAnimations = !!mq?.matches; };
  syncGlobal();
  mq?.addEventListener?.("change", syncGlobal);

  const EASE = [0.25, 0.1, 0.25, 1]; // ease-out doux, sans dépassement
  const T = { out: 0.15, in: 0.25, card: 0.32, count: 0.4, hover: 0.2 };
  const STEP = 0.04;     // décalage entre deux cartes de la cascade
  const MAX_DELAY = 0.3; // une longue liste ne fait pas attendre

  // Sélecteurs : cartes révélées en cascade, valeurs comptées.
  const CARDS = ".game, .card, .totals-group";
  const COUNTED = ".score, .sb-score, .quarters td, .team-stats td, .stat-cells dd";

  // Nettoyage des observateurs et gestes de la page précédente.
  let cleanups = [];
  function reset() {
    cleanups.forEach((stop) => { try { stop(); } catch { /* déjà arrêté */ } });
    cleanups = [];
  }

  // --- Compteurs ------------------------------------------------------
  // Largeurs finales mesurées en une seule passe (lectures groupées avant
  // toute écriture, pour ne pas recalculer la mise en page à chaque carte).
  let widths = new Map();
  function measure(view) {
    widths = new Map([...view.querySelectorAll(COUNTED)].map((el) => [el, el.getBoundingClientRect().width]));
  }

  // Nombres au format français, tels que les produit app.js : 27, 4,5,
  // 1 234 (espace fine insécable). « 23/35 » donne deux nombres.
  const NUM_RE = /\d{1,3}(?:[   ]\d{3})+(?:,\d+)?|\d+(?:,\d+)?/g;

  function parseNum(s) {
    const decimals = s.includes(",") ? s.split(",")[1].length : 0;
    return {
      value: Number(s.replace(/[   ]/g, "").replace(",", ".")),
      fmt: new Intl.NumberFormat("fr-FR", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
        useGrouping: /[   ]/.test(s),
      }),
    };
  }

  // Prépare les valeurs comptées d'un bloc : chaque nœud texte contenant des
  // nombres est découpé en morceaux, puis affiché à zéro. Renvoie une
  // fonction qui anime de 0 à la valeur finale, ou null s'il n'y a rien.
  function prepareCount(root) {
    const els = [...root.querySelectorAll(COUNTED)];
    if (root.matches?.(COUNTED)) els.unshift(root);
    const nodes = [];
    for (const el of els) {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const found = [];
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const text = n.nodeValue;
        const parts = [];
        let last = 0;
        for (const m of text.matchAll(NUM_RE)) {
          parts.push(text.slice(last, m.index), parseNum(m[0]));
          last = m.index + m[0].length;
        }
        if (parts.length) { parts.push(text.slice(last)); found.push({ node: n, parts, final: text }); }
      }
      if (!found.length) continue;
      // Largeur figée pendant le comptage : « 0 » puis « 27 » ne doit pas
      // faire bouger les colonnes ni le tableau de score.
      const w = widths.get(el);
      if (w) el.style.minWidth = `${w}px`;
      nodes.push({ el, found });
    }
    if (!nodes.length) return null;

    const paint = (p) => {
      for (const { found } of nodes) {
        for (const f of found) {
          f.node.nodeValue = f.parts.map((x) => (typeof x === "string" ? x : x.fmt.format(x.value * p))).join("");
        }
      }
    };
    const finish = () => {
      for (const { el, found } of nodes) {
        for (const f of found) f.node.nodeValue = f.final;
        el.style.minWidth = "";
      }
    };
    paint(0);
    return (delay = 0) => {
      const a = M.animate(0, 1, { duration: T.count, delay, ease: EASE, onUpdate: paint });
      a.then(finish, finish);
      cleanups.push(finish); // page quittée en plein comptage : valeurs finales
    };
  }

  // --- Cascade des cartes ---------------------------------------------
  // Chaque carte apparaît quand elle entre à l'écran. Les cartes qui entrent
  // ensemble (celles visibles au chargement, ou une rangée au défilement)
  // sont décalées les unes des autres.
  let batch = 0, batchFrame = 0;
  function nextDelay() {
    if (!batchFrame) batchFrame = requestAnimationFrame(() => { batch = 0; batchFrame = 0; });
    return Math.min(batch++ * STEP, MAX_DELAY);
  }

  function revealCard(el) {
    el.style.opacity = "0";
    el.style.transform = "translateY(8px)";
    const stop = M.inView(el, () => {
      // Mise à zéro seulement maintenant : une carte encore hors écran garde
      // ses vraies valeurs (recherche dans la page, impression).
      const count = prepareCount(el);
      const delay = nextDelay();
      M.animate(el, { opacity: [0, 1], transform: ["translateY(8px)", "translateY(0px)"] },
        { duration: T.card, delay, ease: EASE })
        .then(() => { el.style.transform = ""; });
      count?.(delay + 0.05);
      stop?.();
    }, { amount: 0.15 });
    cleanups.push(() => { stop?.(); el.style.opacity = ""; el.style.transform = ""; });
  }

  // --- Survol -----------------------------------------------------------
  // Cartes de match : les pastilles grossissent à peine, les équipes glissent
  // de 3 px. Motion ignore les survols émulés par le tactile.
  function hoverGames(view) {
    const games = view.querySelectorAll(".game");
    if (!games.length) return;
    const stop = M.hover(games, (el) => {
      const pills = el.querySelectorAll(".pill");
      const teams = el.querySelector(".game-teams");
      M.animate(pills, { scale: 1.25 }, { duration: T.hover, ease: EASE });
      if (teams) M.animate(teams, { x: 3 }, { duration: T.hover, ease: EASE });
      return () => {
        M.animate(pills, { scale: 1 }, { duration: T.hover, ease: EASE });
        if (teams) M.animate(teams, { x: 0 }, { duration: T.hover, ease: EASE });
      };
    });
    cleanups.push(stop);
  }

  // --- Transitions entre les vues ---------------------------------------
  let fallback = 0;

  async function leave(view) {
    reset();
    clearTimeout(fallback);
    if (reduced() || !view.childElementCount) return;
    // Les contrôles Motion ont un then() mais pas de catch() : await suffit.
    try { await M.animate(view, { opacity: 0 }, { duration: T.out, ease: EASE }); } catch { /* annulé */ }
    // Chargement plus long que prévu : on réaffiche la vue (et son
    // « Chargement… ») au lieu de laisser une page vide.
    clearTimeout(fallback);
    fallback = setTimeout(() => M.animate(view, { opacity: 1 }, { duration: T.in, ease: EASE }), 300);
  }

  function enter(view) {
    clearTimeout(fallback);
    if (reduced()) { view.style.opacity = ""; return; }
    reset();
    measure(view);
    M.animate(view, { opacity: [0, 1] }, { duration: T.in, ease: EASE });
    // Valeurs hors cartes (tableau de score, stats d'équipe) : comptées dès
    // qu'elles sont visibles.
    view.querySelectorAll(".game-head, .team-stats").forEach((block) => {
      const stop = M.inView(block, () => { prepareCount(block)?.(0.05); stop?.(); }, { amount: 0.2 });
      cleanups.push(() => stop?.());
    });
    view.querySelectorAll(CARDS).forEach(revealCard);
    hoverGames(view);
  }

  window.GamedayAnim = { leave, enter };
})();
