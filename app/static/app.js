// NFL Gameday — front vanilla, routage par hash.
//   #/            -> semaine courante
//   #/week/8      -> page semaine
//   #/game/<id>   -> page match (jalon 4)
"use strict";

const TZ = "Europe/Paris";
const PLAYOFFS = [
  { week: 19, short: "WC", label: "Wild Card" },
  { week: 20, short: "DIV", label: "Divisional" },
  { week: 21, short: "CONF", label: "Conférence" },
  { week: 22, short: "SB", label: "Super Bowl" },
];

const fmtDay = new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, weekday: "long", day: "numeric", month: "long" });
const fmtTime = new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const fmtDayKey = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
const fmtUpdated = new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const rtf = new Intl.RelativeTimeFormat("fr", { numeric: "auto" });

const state = { meta: null, teams: new Map(), routeSeq: 0 };
const view = document.getElementById("view");

// --- Utilitaires ------------------------------------------------------
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const dash = (v) => (v === null || v === undefined || v === "" ? "—" : esc(v));
const capitalize = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// Mode de données, fixé par config.js : "api" (FastAPI, en local) ou
// "static" (export dist/, déployé sur Vercel). Rien à régler à la main.
const MODE = window.GAMEDAY_CONFIG?.mode === "static" ? "static" : "api";

// Seul point d'accès réseau du front. En statique, /api/weeks/8 devient
// /data/weeks/8.json (arborescence miroir produite par py -m app.export).
function dataUrl(path) {
  if (MODE === "api") return path;
  return `/data/${path.replace(/^\/api\//, "")}.json`;
}

async function api(path, options) {
  if (MODE === "static" && options?.method && options.method !== "GET") {
    throw new Error("Action indisponible dans la version statique");
  }
  const res = await fetch(dataUrl(path), options);
  if (res.status === 401 && MODE === "static") {
    // Session absente ou expirée (protection du site en ligne) : page de
    // connexion, en gardant la page demandée (#/game/...) pour y revenir après.
    location.replace(`/login?next=${encodeURIComponent(location.pathname + location.search)}${location.hash}`);
    return new Promise(() => {}); // la page va changer : on n'affiche pas d'erreur
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* corps non JSON */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

function relativeTime(date) {
  const minutes = Math.round((date - Date.now()) / 60000);
  if (Math.abs(minutes) < 60) return rtf.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return rtf.format(hours, "hour");
  return fmtUpdated.format(date);
}

function weekLabel(week) {
  const w = state.meta?.weeks.find((x) => x.week === week);
  if (w) return w.label;
  const p = PLAYOFFS.find((x) => x.week === week);
  return p ? p.label : `Week ${week}`;
}

// Animations (anim.js, avec Motion) : facultatives, l'app marche sans.
const anim = window.GamedayAnim || { leave: async () => {}, enter: () => {}, show: () => {} };

// « Chargement… » différé. L'ancien contenu (masqué par le fondu de sortie)
// garde sa place tant que les données arrivent vite. Le remplacer tout de suite
// par une ligne de texte faisait s'effondrer la hauteur de la page le temps
// d'une image : la barre de défilement disparaissait et l'en-tête sautait.
let loadingTimer = 0;
function loadingLater(target = view) {
  clearTimeout(loadingTimer);
  const seq = state.routeSeq;
  loadingTimer = setTimeout(() => {
    if (seq !== state.routeSeq) return;
    target.innerHTML = `<p class="state-msg">Chargement…</p>`;
    anim.show(target);
  }, 300);
}

// Rendu final d'une page (ou d'une erreur) dans target (la vue entière, ou
// seulement la liste des matchs d'une semaine) : contenu puis animation d'entrée.
function paint(html, target = view) {
  clearTimeout(loadingTimer);
  target.innerHTML = html;
  anim.enter(target);
}

function setMessage(text, isError = false) {
  const html = `<p class="state-msg${isError ? " is-error" : ""}">${esc(text)}</p>`;
  if (isError) paint(html);
  else view.innerHTML = html;
}

function setNav(name) {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

// --- En-tête ----------------------------------------------------------
function renderMasthead() {
  const m = state.meta;
  document.getElementById("season").textContent = m ? `Saison ${m.season}` : "";
  const updated = document.getElementById("updated");
  if (MODE === "static") {
    // Version statique : pas d'actualisation à la demande, on date les données.
    const stamp = m?.fetched_at || m?.generated_at;
    updated.textContent = stamp ? `Données du ${fmtDataDate.format(new Date(stamp))}` : "";
    updated.title = m?.generated_at ? `Site généré le ${fmtDataDate.format(new Date(m.generated_at))}` : "";
    return;
  }
  if (m?.fetched_at) {
    const d = new Date(m.fetched_at);
    updated.textContent = `Mis à jour ${relativeTime(d)}`;
    updated.title = fmtUpdated.format(d);
  } else {
    updated.textContent = "";
  }
}

const fmtDataDate = new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
if (MODE === "static") {
  document.getElementById("refresh").remove();
  // Version en ligne (protégée par mot de passe) : lien discret de déconnexion.
  const out = document.createElement("a");
  out.href = "/logout";
  out.className = "logout";
  out.textContent = "Se déconnecter";
  document.querySelector(".colophon p")?.append(" ", out);
}

async function loadMeta() {
  const [meta, teams] = await Promise.all([api("/api/meta"), api("/api/teams")]);
  state.meta = meta;
  state.teams = new Map(teams.map((t) => [t.abbr, t]));
  renderMasthead();
}

document.getElementById("refresh")?.addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "Actualisation…";
  try {
    await api("/api/refresh", { method: "POST" });
    await loadMeta();
    await route();
    btn.textContent = "Actualiser";
    btn.title = "Retélécharger les données nflverse";
  } catch (err) {
    btn.textContent = "Échec — réessayer";
    btn.title = err.message;
    console.error(err);
  } finally {
    btn.disabled = false;
  }
});

// --- Page semaine -----------------------------------------------------
function weekStrip(current) {
  const weeks = state.meta.weeks;
  const known = new Set(weeks.map((w) => w.week));
  const item = (w, short, title, cls) =>
    known.has(w)
      ? `<a href="#/week/${w}" class="${cls}" title="${esc(title)}"${w === current ? ' aria-current="page"' : ""}>${esc(short)}</a>`
      : `<span class="is-empty" title="${esc(title)} — pas encore au calendrier">${esc(short)}</span>`;

  const regular = weeks.filter((w) => w.week <= 18)
    .map((w) => item(w.week, String(w.week), w.label, w.finals === 0 ? "is-future" : ""));
  const playoffs = PLAYOFFS.map((p) => {
    const w = weeks.find((x) => x.week === p.week);
    return item(p.week, p.short, p.label, w && w.finals === 0 ? "is-future" : "");
  });
  return `<nav class="week-strip" aria-label="Semaines">${regular.join("")}<span class="strip-sep" aria-hidden="true">|</span>${playoffs.join("")}</nav>`;
}

// Pastille d'équipe : couleur choisie au build pour chaque thème selon son
// contraste avec le fond (app/data/team_assets.py). Ex. : PIT passe au jaune
// en thème sombre, NO au noir en thème clair.
function teamColorStyle(t) {
  const light = t?.dot_light || t?.color, dark = t?.dot_dark || light;
  if (!light) return "";
  return ` style="--team:${esc(light)};--team-dark:${esc(dark)}"`;
}

// --- Logos d'équipe -----------------------------------------------------
// Un seul composant pour toute l'app. Petits logos (48 px, logos/48/…) à côté
// des abréviations, grands logos (128 px) pour l'en-tête d'un match. La
// variante pour fond sombre (…/dark/…) est choisie par <picture> selon
// prefers-color-scheme. width/height fixes : pas de saut de mise en page.
// alt vide : le texte d'à côté nomme déjà l'équipe, il n'est lu qu'une fois.
// Image introuvable : elle disparaît, le texte reste.
function logoPicture(abbr, px, { lazy = true, cls = "team-logo" } = {}) {
  const t = state.teams.get(abbr);
  const small = px <= 48;
  const src = (small && t?.logo_sm) || t?.logo;
  if (!src) return "";
  const darkSrc = (small && t.logo_sm_dark) || t.logo_dark;
  const dark = darkSrc ? `<source media="(prefers-color-scheme: dark)" srcset="${esc(darkSrc)}">` : "";
  return `<picture class="${cls}-wrap">${dark}<img class="${cls}" src="${esc(src)}" alt="" width="${px}" height="${px}"${lazy ? ' loading="lazy"' : ""} decoding="async" onerror="this.closest('picture').remove()"></picture>`;
}

// Logo + abréviation, partout dans l'app (sauf l'en-tête d'un match, qui a
// ses grands logos). Pas de nom en toutes lettres : il apparaît au survol.
// size : 22 px dans les listes, 18 px dans les tableaux, 24 px dans les titres.
// lazy : false pour ce qui est visible dès l'ouverture de la page.
function teamBadge(abbr, { size = 22, lazy = true, cls = "", textCls = "" } = {}) {
  const name = state.teams.get(abbr)?.name;
  return `<span class="team-badge${cls ? ` ${cls}` : ""}"${name ? ` title="${esc(name)}"` : ""}>${logoPicture(abbr, size, { lazy })}<span class="tb-text${textCls ? ` ${textCls}` : ""}">${esc(abbr)}</span></span>`;
}

function teamLine(abbr, score, outcome, eager = false) {
  return `
    <div class="team-line ${outcome}">
      ${teamBadge(abbr, { size: 22, lazy: !eager, textCls: "abbr" })}
      <span class="score">${score === null || score === undefined ? "" : esc(score)}</span>
    </div>`;
}

function gameRow(g, eager = false) {
  const kickoff = g.kickoff_paris ? new Date(g.kickoff_paris) : null;
  const time = kickoff ? fmtTime.format(kickoff) : "—";
  const final = g.status === "final";
  let awayCls = "", homeCls = "";
  if (final && g.away_score !== g.home_score) {
    const awayWins = g.away_score > g.home_score;
    awayCls = awayWins ? "is-winner" : "is-loser";
    homeCls = awayWins ? "is-loser" : "is-winner";
  }
  const status = final
    ? `<span>Final</span>${g.overtime ? "<span>Prol.</span>" : ""}`
    : "<span>À venir</span>";
  const label = final
    ? `${g.away_team} ${g.away_score}, ${g.home_team} ${g.home_score}`
    : `${g.away_team} chez ${g.home_team}, ${time}`;
  return `
    <a class="game ${final ? "is-final" : "is-scheduled"}" href="#/game/${esc(g.game_id)}" aria-label="${esc(label)}">
      <div class="game-status"><span class="time">${esc(time)}</span>${status}</div>
      <div class="game-teams">
        ${teamLine(g.away_team, g.away_score, awayCls, eager)}
        ${teamLine(g.home_team, g.home_score, homeCls, eager)}
      </div>
    </a>`;
}

function groupByDay(games) {
  const groups = new Map();
  for (const g of games) {
    const d = g.kickoff_paris ? new Date(g.kickoff_paris) : null;
    const key = d ? fmtDayKey.format(d) : "zz";
    if (!groups.has(key)) groups.set(key, { label: d ? capitalize(fmtDay.format(d)) : "Date à confirmer", games: [] });
    groups.get(key).games.push(g);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, v]) => v);
}

function weekSummary({ games, finals }) {
  const n = `${games} match${games > 1 ? "s" : ""}`;
  if (finals === 0) return `${n} · à venir`;
  if (finals === games) return `${n} · tous terminés`;
  return `${n} · ${finals} terminé${finals > 1 ? "s" : ""}`;
}

// Titre, flèches et sélecteur de semaine. D'une semaine à l'autre, ils restent
// en place (mêmes éléments, mis à jour sans animation) : seule la liste des
// matchs (.week-body) fait le fondu.
function weekHead(week, info) {
  const weeks = state.meta.weeks.map((w) => w.week);
  const idx = weeks.indexOf(week);
  const prev = idx > 0 ? weeks[idx - 1] : null;
  const next = idx >= 0 && idx < weeks.length - 1 ? weeks[idx + 1] : null;
  return `
    <div class="page-head">
      <h1 class="page-title">${esc(weekLabel(week))}</h1>
      <div class="pager">
        ${prev !== null ? `<a href="#/week/${prev}">← ${esc(weekLabel(prev))}</a>` : `<span class="is-disabled">←</span>`}
        ${next !== null ? `<a href="#/week/${next}">${esc(weekLabel(next))} →</a>` : `<span class="is-disabled">→</span>`}
      </div>
    </div>
    <p class="page-sub">${info ? weekSummary(info) : "&nbsp;"}</p>`;
}

const metaStamp = () => state.meta?.fetched_at || state.meta?.generated_at || "";

function updateWeekShell(shell, week, info) {
  shell.querySelector(".week-head").innerHTML = weekHead(week, info);
  shell.querySelectorAll(".week-strip a").forEach((a) => {
    if (a.getAttribute("href") === `#/week/${week}`) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  scrollStripToCurrent(false);
}

async function renderWeek(week) {
  setNav("week");
  const info = state.meta.weeks.find((w) => w.week === week);
  document.title = `${weekLabel(week)} — NFL Gameday`;

  // Coquille déjà affichée (on vient d'une autre semaine) : mise à jour sur
  // place. Sinon (autre page, ou données rafraîchies) : rendu complet.
  let shell = view.querySelector(".week-shell");
  if (shell && shell.dataset.stamp !== metaStamp()) shell = null;
  if (shell) updateWeekShell(shell, week, info);
  const body = shell?.querySelector(".week-body");
  const render = (html) => {
    if (body) { paint(html, body); return; }
    paint(`
      <div class="week-shell" data-stamp="${esc(metaStamp())}">
        <div class="week-head">${weekHead(week, info)}</div>
        ${weekStrip(week)}
        <div class="week-body">${html}</div>
      </div>`);
    scrollStripToCurrent(true);
  };

  if (!info) {
    render(`<p class="state-msg">Cette semaine n'est pas encore au calendrier.</p>`);
    return;
  }

  loadingLater(body || view);
  const seq = state.routeSeq;
  let games;
  try {
    games = await api(`/api/weeks/${week}`);
  } catch (err) {
    if (seq !== state.routeSeq) return;
    render(`<p class="state-msg is-error">Impossible de charger la semaine : ${esc(err.message)}</p>`);
    return;
  }
  if (seq !== state.routeSeq) return; // l'utilisateur a changé de page entre-temps

  const playing = new Set(games.flatMap((g) => [g.away_team, g.home_team]));
  const byes = [...state.teams.keys()].filter((t) => !playing.has(t)).sort();
  let shown = 0; // les premiers matchs, visibles à l'ouverture, chargent leurs logos tout de suite
  const days = groupByDay(games).map((d) => `
    <section class="day">
      <h2 class="day-label">${esc(d.label)}</h2>
      <div class="games">${d.games.map((g) => gameRow(g, shown++ < 5)).join("")}</div>
    </section>`).join("");
  const byesHtml = week <= 18 && byes.length
    ? `<p class="byes"><span class="byes-label">Au repos</span>${byes.map((t) => teamBadge(t, { size: 18, cls: "bye-team" })).join("")}</p>` : "";

  render(days + byesHtml);
}

// Semaine courante visible dans le sélecteur (utile sur mobile, où il défile).
// Premier affichage : centrage immédiat. Ensuite : seulement si elle sort du
// cadre, en douceur.
function scrollStripToCurrent(initial) {
  const strip = view.querySelector(".week-strip");
  const cur = strip?.querySelector('[aria-current="page"]');
  if (!strip || !cur) return;
  const left = cur.offsetLeft - strip.clientWidth / 2 + cur.clientWidth / 2;
  if (initial) { strip.scrollLeft = left; return; }
  const outside = cur.offsetLeft < strip.scrollLeft || cur.offsetLeft + cur.clientWidth > strip.scrollLeft + strip.clientWidth;
  if (!outside) return;
  const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  strip.scrollTo({ left, behavior: smooth ? "smooth" : "auto" });
}

// --- Page match ---------------------------------------------------------
const nf1 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const num = (v) => (v === null || v === undefined ? "—" : nf1.format(v));
const ROOF = { outdoors: "En extérieur", dome: "Sous dôme", closed: "Toit fermé", open: "Toit ouvert" };

function playerLink(p) {
  return `<a class="player-link" href="#/player/${encodeURIComponent(p.player_id)}">${esc(p.name)}</a>`;
}

function teamName(abbr) {
  return state.teams.get(abbr)?.name || abbr;
}

function conditions(g) {
  const parts = [];
  if (g.stadium) parts.push(esc(g.stadium));
  if (g.roof) parts.push(esc(ROOF[g.roof] || g.roof));
  if (g.temp_f !== null && g.temp_f !== undefined) parts.push(`${Math.round((g.temp_f - 32) * 5 / 9)} °C`);
  if (g.wind_mph !== null && g.wind_mph !== undefined) parts.push(`vent ${Math.round(g.wind_mph * 1.609)} km/h`);
  return parts.join(" · ");
}

function quarterTable(g) {
  if (!g.quarters.length) return "";
  const head = g.quarters.map((q) => `<th scope="col">${esc(q.period)}</th>`).join("");
  const row = (abbr, side, total) => `
    <tr><th scope="row">${esc(abbr)}</th>${g.quarters.map((q) => `<td>${dash(q[side])}</td>`).join("")}<td class="total">${dash(total)}</td></tr>`;
  return `
    <table class="quarters" aria-label="Score par quart-temps">
      <thead><tr><th></th>${head}<th scope="col">T</th></tr></thead>
      <tbody>${row(g.away_team, "away", g.away_score)}${row(g.home_team, "home", g.home_score)}</tbody>
    </table>`;
}

// better : "high" (plus grand = mieux), "low", ou null (pas de comparaison)
const TEAM_ROWS = [
  { label: "Yards totaux", get: (s) => s.total_yards, better: "high" },
  { label: "Yards à la passe (nets)", get: (s) => s.net_passing_yards, better: "high" },
  { label: "Yards à la course", get: (s) => s.rushing_yards, better: "high" },
  { label: "Passes complétées", get: (s) => s.completions, fmt: (s) => s.completions == null ? "—" : `${s.completions}/${dash(s.attempts)}`, better: null },
  { label: "Courses", get: (s) => s.carries, better: null },
  { label: "Sacks subis", get: (s) => s.sacks_suffered, better: "low" },
  { label: "Pénalités", get: (s) => s.penalties, better: "low" },
];

function teamStatsTable(g, a, h) {
  if (!a || !h) return "";
  const rows = TEAM_ROWS.map((r) => {
    const va = r.get(a), vh = r.get(h);
    let ca = "", ch = "";
    if (r.better && va != null && vh != null && va !== vh) {
      const aBetter = r.better === "high" ? va > vh : va < vh;
      ca = aBetter ? "is-better" : ""; ch = aBetter ? "" : "is-better";
    }
    const f = r.fmt || ((s) => dash(r.get(s)));
    return `<tr><th scope="row">${r.label}</th><td class="${ca}">${f(a)}</td><td class="${ch}">${f(h)}</td></tr>`;
  }).join("");
  return `
    <section class="block">
      <h2 class="section-title">Statistiques d'équipe</h2>
      <table class="team-stats">
        <thead><tr><th></th><th scope="col">${esc(g.away_team)}</th><th scope="col">${esc(g.home_team)}</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </section>`;
}

function statCells(cells) {
  return `<dl class="stat-cells">${cells.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>`;
}

// --- Portraits -----------------------------------------------------------
// nflverse donne l'original du CDN de la NFL : un PNG de 3400 × 2450 px
// (4 à 6 Mo) au format paysage. Réduit d'un coup à 36 px, il crénelait, et le
// visage n'occupait qu'une petite partie du cercle. On demande au même CDN,
// pour la même image, un carré recadré sur le visage (c_thumb,g_face) à 4 fois
// la taille affichée, en qualité maximale (q_auto:best).
const HEADSHOT_RE = /^(https:\/\/static\.www\.nfl\.com\/image\/(?:upload|private))\/[^/]+\/(league\/[^?#]+)$/;
const HEADSHOT_SIZES = { sm: 36, lg: 84 };

function headshotUrl(url, px) {
  const m = HEADSHOT_RE.exec(url || "");
  return m ? `${m[1]}/c_thumb,g_face,w_${px},h_${px},f_auto,q_auto:best/${m[2]}` : url;
}

// Repli : silhouette neutre, à la même taille que le portrait.
function silhouette(cls) {
  return `<span class="${cls} is-empty" aria-hidden="true"><svg viewBox="0 0 36 36" focusable="false"><circle cx="18" cy="14" r="6.5"/><path d="M5 36c1-8 6.5-12 13-12s12 4 13 12z"/></svg></span>`;
}

function headshotFallback(img) {
  img.outerHTML = silhouette(img.className);
}

function headshot(p, size = "sm") {
  const cls = size === "lg" ? "headshot headshot-lg" : "headshot";
  const dim = HEADSHOT_SIZES[size];
  if (!p?.headshot_url) return silhouette(cls);
  return `<img class="${cls}" src="${esc(headshotUrl(p.headshot_url, dim * 4))}" width="${dim}" height="${dim}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="headshotFallback(this)">`;
}

// --- Joueurs clés (app/data/key_players.py) ------------------------------
const fmtW = (v) => nf1.format(v);
const made = (m, a) => (a ? `${m ?? 0}/${a}` : "—");

function qbStats(p) {
  return statCells([
    ["C/A", made(p.completions, p.attempts)], ["Yds", num(p.passing_yards)], ["TD", num(p.passing_tds)],
    ["INT", num(p.interceptions)], ["Sacks", num(p.sacks_suffered)],
    ["Course", p.carries ? `${p.carries}–${num(p.rushing_yards)}` : "—"],
  ]);
}

// Seules les stats qui comptent pour ce joueur : course s'il a couru,
// réception s'il a été ciblé, et ses TD.
function offenseStats(p) {
  const cells = [];
  if (p.carries) cells.push(["Courses", num(p.carries)], ["Yds course", num(p.rushing_yards)]);
  if (p.targets || p.receptions) cells.push(["Réc.", made(p.receptions, p.targets)], ["Yds réc.", num(p.receiving_yards)]);
  cells.push(["TD", num((p.rushing_tds || 0) + (p.receiving_tds || 0))]);
  return statCells(cells);
}

function defenseStats(p, withPressures) {
  return statCells([
    ["Plaq.", num(p.tackles)], ["Sacks", num(p.sacks)], ["INT", num(p.def_interceptions)],
    ["PD", num(p.passes_defended)], ["QB hits", num(p.qb_hits)],
    ...(withPressures ? [["Press.", num(p.pressures)]] : []),
  ]);
}

function kickerStats(p) {
  return statCells([["FG", made(p.fg_made, p.fg_att)], ["Long", p.fg_att ? num(p.fg_long) : "—"], ["XP", made(p.pat_made, p.pat_att)]]);
}

// Carte joueur : rôle, poste, portrait et stats. L'équipe est donnée par la
// colonne (une par équipe), inutile de la répéter sur chaque carte.
// MVP : badge « MVP » et fin liseré à la couleur de son équipe.
function keyCard(p, role, stats, extra = "", mvp = false) {
  const pos = p.position && p.position !== role ? esc(p.position) : "";
  const meta = [pos, extra].filter(Boolean).join(" · ");
  const badge = mvp ? `<span class="mvp-badge">MVP</span>` : "";
  return `
    <article class="card${mvp ? " is-mvp" : ""}"${mvp ? teamColorStyle(state.teams.get(p.team)) : ""}>
      <h4 class="card-role">${esc(role)}${meta ? `<span class="card-pos">${meta}</span>` : ""}${badge}</h4>
      <div class="card-head">${headshot(p)}<p class="card-name">${playerLink(p)}</p></div>
      ${stats}
    </article>`;
}

// Joueurs clés : une rangée par catégorie (QB, offensive, défense, kicker),
// l'équipe à l'extérieur à gauche, celle à domicile à droite, comme dans le
// tableau de score. Les deux cellules d'une rangée partagent la même ligne de
// grille : chaque catégorie commence à la même hauteur pour les deux équipes,
// et la rangée prend la hauteur de la cellule la plus remplie.
// Sur mobile, une seule colonne dans le même ordre (catégorie par catégorie,
// extérieur puis domicile) ; chaque cellule rappelle alors son équipe.
function teamLabel(abbr, cls) {
  return `<span class="${cls}">${teamBadge(abbr, { size: 24 })}</span>`;
}

function keyCell(team, cards, empty) {
  return `
    <div class="kp-cell">
      ${teamLabel(team, "kp-cell-team")}
      ${cards.length ? cards.join("") : `<p class="kp-empty">${empty}</p>`}
    </div>`;
}

function keyPlayers(k) {
  if (!k) return "";
  const wo = k.weights?.offense || {}, wd = k.weights?.defense || {};
  const pts = (r) => `${fmtW(r.score)} pts`;
  const { away, home } = k;
  const plural = (n, one, many) => (n > 1 ? many : one);
  // Le MVP garde sa place dans sa catégorie ; seule sa carte est marquée.
  const isMvp = (p, category) => k.mvp?.category === category && k.mvp.player.player_id === p.player_id;
  const rows = [
    {
      title: plural(Math.max(away.quarterbacks.length, home.quarterbacks.length), "Quarterback", "Quarterbacks"),
      cards: (s) => s.quarterbacks.map((p) => keyCard(p, "QB", qbStats(p), "", isMvp(p, "qb"))),
      empty: "Aucune passe tentée.",
    },
    {
      title: `Top ${wo.top ?? 5} offensif`,
      cards: (s) => s.offense.map((r) => keyCard(r.player, `N° ${r.rank}`, offenseStats(r.player), pts(r), isMvp(r.player, "offense"))),
      empty: "Aucun joueur offensif avec des stats.",
    },
    {
      title: `Top ${wd.top ?? 3} défensif`,
      cards: (s) => s.defense.map((r) => keyCard(r.player, `N° ${r.rank}`, defenseStats(r.player, k.pressures_available), pts(r), isMvp(r.player, "defense"))),
      empty: "Aucun joueur défensif avec des stats.",
    },
    {
      title: plural(Math.max(away.kickers.length, home.kickers.length), "Kicker", "Kickers"),
      cards: (s) => s.kickers.map((p) => keyCard(p, "K", kickerStats(p), "", isMvp(p, "kicker"))),
      empty: "Aucun coup de pied tenté.",
    },
  ];
  return `
    <section class="block key-players">
      <h2 class="section-title">Joueurs clés</h2>
      <div class="kp-grid">
        <h3 class="kp-team">${teamLabel(away.team, "kp-team-inner")}</h3>
        <h3 class="kp-team">${teamLabel(home.team, "kp-team-inner")}</h3>
        ${rows.map((r) => `
          <h4 class="kp-sub kp-row-title">${r.title}</h4>
          ${keyCell(away.team, r.cards(away), r.empty)}
          ${keyCell(home.team, r.cards(home), r.empty)}`).join("")}
      </div>
    </section>`;
}

function scoreboard(g) {
  const final = g.status === "final";
  const kickoff = g.kickoff_paris ? new Date(g.kickoff_paris) : null;
  const when = kickoff ? `${capitalize(fmtDay.format(kickoff))} · ${fmtTime.format(kickoff)}` : "Date à confirmer";
  let aw = "", hw = "";
  if (final && g.away_score !== g.home_score) {
    aw = g.away_score > g.home_score ? "is-winner" : "is-loser";
    hw = g.away_score > g.home_score ? "is-loser" : "is-winner";
  }
  // Équipe gagnante : sa couleur sert de fin liseré sous son abréviation.
  const team = (abbr, cls, align) => `
    <div class="sb-team ${cls} ${align}"${cls === "is-winner" ? teamColorStyle(state.teams.get(abbr)) : ""}>
      ${logoPicture(abbr, 88, { lazy: false, cls: "sb-logo" })}
      <div class="sb-text">
        <span class="sb-abbr">${esc(abbr)}</span>
        <span class="sb-name">${esc(teamName(abbr))}</span>
      </div>
    </div>`;
  return `
    <p class="eyebrow">${esc(g.week_label)} · ${esc(when)}</p>
    <div class="scoreboard ${final ? "" : "is-scheduled"}">
      ${team(g.away_team, aw, "left")}
      ${final ? `<span class="sb-score ${aw}">${dash(g.away_score)}</span>` : ""}
      <span class="sb-sep">${final ? "–" : "@"}</span>
      ${final ? `<span class="sb-score ${hw}">${dash(g.home_score)}</span>` : ""}
      ${team(g.home_team, hw, "right")}
    </div>
    <p class="sb-status">${final ? (g.overtime ? "Final après prolongation" : "Final") : "Match à venir, heure de Paris"}</p>
    ${quarterTable(g)}
    ${conditions(g) ? `<p class="conditions">${conditions(g)}</p>` : ""}`;
}

async function renderGame(gameId) {
  setNav("week");
  loadingLater();
  const seq = state.routeSeq;
  let d;
  try {
    d = await api(`/api/games/${encodeURIComponent(gameId)}`);
  } catch (err) {
    if (seq === state.routeSeq) setMessage(err.status === 404 ? "Match introuvable." : `Erreur : ${err.message}`, true);
    return;
  }
  if (seq !== state.routeSeq) return;
  const g = d.game;
  document.title = `${g.away_team} – ${g.home_team}, ${g.week_label} — NFL Gameday`;
  const body = g.status === "final"
    ? `${teamStatsTable(g, d.away_stats, d.home_stats)}
       ${keyPlayers(d.key_players)}`
    : "";
  paint(`
    <a class="back" href="#/week/${g.week}">← ${esc(g.week_label)}</a>
    <header class="game-head">${scoreboard(g)}</header>
    ${body}`);
}

// --- Classement -------------------------------------------------------
const fmtPct = (v) => (v === null || v === undefined ? "—" : v.toFixed(3).replace(/^0(?=\.)/, ""));
const fmtDiff = (v) => (v > 0 ? `+${v}` : v < 0 ? `−${-v}` : "0");

// eager : tableaux visibles à l'ouverture (les deux premières divisions AFC).
function standingsTable(d, eager = false) {
  const rows = d.rows.map((r, i) => {
    return `
      <tr${i === 0 ? ' class="is-leader"' : ""}>
        <th scope="row" class="st-team"><span class="st-team-inner">
          ${teamBadge(r.team, { size: 20, lazy: !eager, textCls: "st-abbr" })}
        </span></th>
        <td>${r.wins}</td><td>${r.losses}</td><td>${r.ties}</td>
        <td class="st-pct">${fmtPct(r.pct)}</td>
        <td class="opt">${r.points_for}</td><td class="opt">${r.points_against}</td>
        <td>${fmtDiff(r.diff)}</td>
        <td class="opt">${esc(r.div_record)}</td><td class="opt">${esc(r.conf_record)}</td>
        <td class="opt">${esc(r.home_record)}</td><td class="opt">${esc(r.away_record)}</td>
        <td class="st-streak">${dash(r.streak)}</td>
      </tr>`;
  }).join("");
  return `
    <table class="standings">
      <caption>${esc(d.name)}</caption>
      <thead><tr>
        <th scope="col" class="st-team"><span class="visually-hidden">Équipe</span></th>
        <th scope="col" title="Victoires">V</th><th scope="col" title="Défaites">D</th><th scope="col" title="Nuls">N</th>
        <th scope="col" title="Pourcentage de victoires">%</th>
        <th scope="col" class="opt" title="Points marqués">PM</th><th scope="col" class="opt" title="Points encaissés">PE</th>
        <th scope="col" title="Différence de points">Diff.</th>
        <th scope="col" class="opt" title="Bilan en division">Div.</th><th scope="col" class="opt" title="Bilan en conférence">Conf.</th>
        <th scope="col" class="opt" title="À domicile">Dom.</th><th scope="col" class="opt" title="À l'extérieur">Ext.</th>
        <th scope="col" title="Série en cours">Série</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function renderStandings() {
  setNav("standings");
  document.title = "Classement des équipes — NFL Gameday";
  loadingLater();
  const seq = state.routeSeq;
  let divisions;
  try {
    divisions = await api("/api/standings");
  } catch (err) {
    if (seq === state.routeSeq) setMessage(`Impossible de charger le classement : ${err.message}`, true);
    return;
  }
  if (seq !== state.routeSeq) return;
  const conf = (c) => `
    <section class="block conference">
      <h2 class="section-title">${c}</h2>
      ${divisions.filter((d) => d.conference === c).map((d, i) => standingsTable(d, c === "AFC" && i < 2)).join("")}
    </section>`;
  paint(`
    <div class="page-head"><h1 class="page-title">Équipes</h1></div>
    <p class="page-sub">Saison régulière ${state.meta.season}, calculé à partir des résultats. Départage simplifié : confrontations directes, division, conférence, différence de points.</p>
    ${conf("AFC")}${conf("NFC")}`);
}

// --- Stats par poste (fiches joueurs et classements) ---------------------
// Les mêmes colonnes servent au résumé de saison, au tableau match par match
// et à l'onglet Classements. Types : "count" (somme, ou moyenne par match),
// "pct" (ratio, jamais divisé), "made" (réussis/tentés), "max" (plus long FG).
const OFF_POSITIONS = new Set(["RB", "HB", "FB", "WR", "TE"]);
const DEF_POSITIONS = new Set(["DE", "DT", "NT", "DL", "DI", "ED", "EDGE", "LB", "ILB", "MLB", "OLB",
  "CB", "DB", "S", "FS", "SS", "SAF"]);
const col = (k, title, f, type = "count") => ({ k, title, f, type });
const STAT_GROUPS = {
  qb: [
    { label: "Passe", cols: [
      col("Yds", "Yards à la passe", (l) => l.passing_yards),
      col("TD", "TD à la passe", (l) => l.passing_tds),
      col("INT", "Interceptions", (l) => l.interceptions),
      col("Comp.", "Pourcentage de passes complétées", (l) => (l.attempts ? (100 * (l.completions || 0)) / l.attempts : null), "pct"),
    ] },
    { label: "Course", cols: [
      col("Yds", "Yards à la course", (l) => l.rushing_yards),
      col("TD", "TD à la course", (l) => l.rushing_tds),
    ] },
  ],
  offense: [
    { label: "Réception", cols: [
      col("Yds", "Yards en réception", (l) => l.receiving_yards),
      col("TD", "TD en réception", (l) => l.receiving_tds),
    ] },
    { label: "Course", cols: [
      col("Yds", "Yards à la course", (l) => l.rushing_yards),
      col("TD", "TD à la course", (l) => l.rushing_tds),
    ] },
  ],
  defense: [
    { label: "Défense", cols: [
      col("Plaq.", "Plaquages (solo + assistés)", (l) => l.tackles),
      col("Sacks", "Sacks", (l) => l.sacks),
      col("QB hits", "QB hits", (l) => l.qb_hits),
      col("INT", "Interceptions", (l) => l.def_interceptions),
      col("PD", "Passes déviées", (l) => l.passes_defended),
    ] },
  ],
  kicker: [
    { label: "Coups de pied", cols: [
      col("FG", "Field goals réussis / tentés", (l) => [l.fg_made, l.fg_att], "made"),
      col("Long", "Plus long field goal réussi", (l) => l.fg_long, "max"),
      col("XP", "Extra points réussis / tentés", (l) => [l.pat_made, l.pat_att], "made"),
    ] },
  ],
};

// Fiche joueur : type de résumé selon le poste (null : fiche d'origine,
// pour les kickers, punters, joueurs de ligne…).
function statKind(position) {
  if (position === "QB") return "qb";
  if (OFF_POSITIONS.has(position)) return "offense";
  if (DEF_POSITIONS.has(position)) return "defense";
  return null;
}

const nfAvg = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

// Valeur affichée. games : diviseur en mode « moyenne par match » (sinon null).
function statText(c, l, games = null) {
  const v = c.f(l);
  const fmt = (x) => (games ? nfAvg.format(x / games) : nf1.format(x));
  if (c.type === "pct") return v === null || v === undefined ? "—" : `${nfAvg.format(v)} %`;
  if (c.type === "made") return v[1] ? `${fmt(v[0] || 0)}/${fmt(v[1])}` : "—";
  if (c.type === "max") return num(v);
  return v === null || v === undefined ? "—" : fmt(v);
}

function statSortValue(c, l, games = null) {
  let v = c.f(l);
  if (c.type === "made") v = v[0];
  if (v === null || v === undefined) return -Infinity;
  return games && (c.type === "count" || c.type === "made") ? v / games : v;
}


// En-têtes à deux niveaux : groupes (« Passe », « Course ») puis colonnes.
// Un seul groupe : pas de ligne de groupe. lead : colonnes avant les stats.
function groupedHead(groups, lead, colTh) {
  const multi = groups.length > 1;
  const grp = multi
    ? `<tr class="grp-row"><th colspan="${lead}"></th>${groups.map((g) => `<th scope="colgroup" colspan="${g.cols.length}" class="grp-start">${esc(g.label)}</th>`).join("")}<th></th></tr>`
    : "";
  const cols = groups.flatMap((g, gi) => g.cols.map((c, i) => colTh(c, i === 0 && (multi || gi > 0), `${gi}.${i}`))).join("");
  return { grp, cols };
}

// --- Page joueur --------------------------------------------------------
const CATEGORIES = {
  pass: {
    label: "Passe",
    has: (t) => (t.attempts || 0) > 0,
    cols: [
      ["C/A", (l) => (l.completions == null ? "—" : `${l.completions}/${dash(l.attempts)}`)],
      ["Yds", (l) => num(l.passing_yards)], ["TD", (l) => num(l.passing_tds)],
      ["INT", (l) => num(l.interceptions)], ["Sacks", (l) => num(l.sacks_suffered)],
    ],
  },
  rush: {
    label: "Course",
    has: (t) => (t.carries || 0) > 0,
    cols: [
      ["Courses", (l) => num(l.carries)], ["Yds", (l) => num(l.rushing_yards)],
      ["Moy.", (l) => (l.carries ? num((l.rushing_yards || 0) / l.carries) : "—")], ["TD", (l) => num(l.rushing_tds)],
    ],
  },
  rec: {
    label: "Réception",
    has: (t) => (t.targets || 0) > 0 || (t.receptions || 0) > 0,
    cols: [
      ["Cibles", (l) => num(l.targets)], ["Réc.", (l) => num(l.receptions)],
      ["Yds", (l) => num(l.receiving_yards)], ["TD", (l) => num(l.receiving_tds)],
    ],
  },
  def: {
    label: "Défense",
    has: (t) => (t.tackles || 0) > 0 || (t.sacks || 0) > 0 || (t.def_interceptions || 0) > 0 || (t.passes_defended || 0) > 0,
    cols: [
      ["Plaq.", (l) => num(l.tackles)], ["Sacks", (l) => num(l.sacks)], ["TFL", (l) => num(l.tackles_for_loss)],
      ["QB hits", (l) => num(l.qb_hits)], ["INT", (l) => num(l.def_interceptions)],
      ["PD", (l) => num(l.passes_defended)], ["FF", (l) => num(l.fumbles_forced)],
    ],
  },
};

// Catégories pertinentes selon le poste : un QB qui plaque après une
// interception n'a pas besoin d'une section « Défense », et inversement.
function categoryOrder(position) {
  if (position === "QB") return ["pass", "rush", "rec"];
  if (position === "RB" || position === "FB") return ["rush", "rec", "pass"];
  if (position === "WR" || position === "TE") return ["rec", "rush", "pass"];
  if (!position) return ["pass", "rush", "rec", "def"];
  return ["def"];
}

async function renderPlayer(playerId) {
  setNav(null);
  loadingLater();
  const seq = state.routeSeq;
  let p;
  try {
    p = await api(`/api/players/${encodeURIComponent(playerId)}`);
  } catch (err) {
    if (seq === state.routeSeq) setMessage(err.status === 404 ? "Joueur introuvable." : `Erreur : ${err.message}`, true);
    return;
  }
  if (seq !== state.routeSeq) return;
  document.title = `${p.name} — NFL Gameday`;
  const kind = statKind(p.position);
  if (kind) { paint(playerPage(p, kind)); return; }

  const cats = categoryOrder(p.position).filter((c) => CATEGORIES[c].has(p.totals));
  const logCats = cats.slice(0, 2); // le journal de matchs garde les deux catégories principales
  const teams = playerTeams(p);

  const totals = cats.map((c) => `
    <div class="totals-group">
      <h3 class="kp-sub">${CATEGORIES[c].label}</h3>
      ${statCells(CATEGORIES[c].cols.map(([k, f]) => [k, f(p.totals)]))}
    </div>`).join("");

  const groupHead = logCats.map((c) => `<th scope="colgroup" colspan="${CATEGORIES[c].cols.length}">${CATEGORIES[c].label}</th>`).join("");
  const colHead = logCats.flatMap((c) => CATEGORIES[c].cols.map(([k], i) => `<th scope="col"${i === 0 ? ' class="grp-start"' : ""}>${k}</th>`)).join("");
  const rows = p.games.map((g) => {
    const res = g.result ? `${g.result} ${dash(g.team_score)}-${dash(g.opponent_score)}` : "—";
    const cells = logCats.flatMap((c) => CATEGORIES[c].cols.map(([, f], i) => `<td${i === 0 ? ' class="grp-start"' : ""}>${f(g.line)}</td>`)).join("");
    return `
      <tr>
        <th scope="row"><a href="#/game/${esc(g.game_id)}">${esc(g.week_label.replace("Week ", "S"))}</a></th>
        <td class="gl-opp"><span class="gl-ha" title="${g.home ? "À domicile" : "À l'extérieur"}">${g.home ? "vs" : "@"}</span>${teamBadge(g.opponent, { size: 18 })}</td>
        <td class="gl-res is-${g.result || "none"}">${res}</td>
        ${cells}
      </tr>`;
  }).join("");

  paint(`
    <button type="button" class="back link-plain" onclick="history.length > 1 ? history.back() : (location.hash = '#/')">← Retour</button>
    <header class="player-head">
      ${headshot(p, "lg")}
      <div>
        <h1 class="page-title player-name">${esc(p.name)}</h1>
        <p class="page-sub">${[esc(p.position || ""), teams, `${p.games_played} match${p.games_played > 1 ? "s" : ""}`].filter(Boolean).join(" · ")}</p>
      </div>
    </header>
    <section class="block">
      <h2 class="section-title">Saison ${state.meta.season}</h2>
      ${totals || `<p class="state-msg">Aucune stat enregistrée.</p>`}
    </section>
    <section class="block">
      <h2 class="section-title">Match par match</h2>
      <div class="table-scroll">
        <table class="game-log">
          <thead>
            <tr class="grp-row"><th colspan="3"></th>${groupHead}</tr>
            <tr><th scope="col">Sem.</th><th scope="col">Adv.</th><th scope="col">Rés.</th>${colHead}</tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>`);
}

// Équipes du joueur (plusieurs s'il a été échangé) : logo et abréviation.
function playerTeams(p) {
  return p.teams.map((t) => teamBadge(t, { size: 20, lazy: false })).join(", ");
}

function playerHeader(p) {
  const teams = playerTeams(p);
  return `
    <button type="button" class="back link-plain" onclick="history.length > 1 ? history.back() : (location.hash = '#/')">← Retour</button>
    <header class="player-head">
      ${headshot(p, "lg")}
      <div>
        <h1 class="page-title player-name">${esc(p.name)}</h1>
        <p class="page-sub">${[esc(p.position || ""), teams, `${p.games_played} match${p.games_played > 1 ? "s" : ""}`].filter(Boolean).join(" · ")}</p>
      </div>
    </header>`;
}

// Fiche QB, offensif ou défensif : seulement les stats clés du poste, dans
// le résumé comme dans le tableau match par match.
function playerPage(p, kind) {
  const groups = STAT_GROUPS[kind];
  const multi = groups.length > 1;
  const totals = groups.map((g) => `
    <div class="totals-group">
      ${multi ? `<h3 class="kp-sub">${esc(g.label)}</h3>` : ""}
      ${statCells(g.cols.map((c) => [`<span title="${esc(c.title)}">${c.k === "Yds" ? "Yards" : esc(c.k)}</span>`, statText(c, p.totals)]))}
    </div>`).join("");

  const { grp, cols } = groupedHead(groups, 3, (c, start) =>
    `<th scope="col" title="${esc(c.title)}"${start ? ' class="grp-start"' : ""}>${esc(c.k)}</th>`);
  const rows = p.games.map((g) => {
    const res = g.result ? `${g.result} ${dash(g.team_score)}-${dash(g.opponent_score)}` : "—";
    const label = { V: "Victoire", D: "Défaite", N: "Match nul" }[g.result] || "";
    const cells = groups.flatMap((gr, gi) => gr.cols.map((c, i) =>
      `<td${i === 0 && (multi || gi > 0) ? ' class="grp-start"' : ""}>${statText(c, g.line)}</td>`)).join("");
    return `
      <tr>
        <th scope="row"><a href="#/game/${esc(g.game_id)}">${esc(g.week_label.replace("Week ", "S"))}</a></th>
        <td class="gl-opp"><span class="gl-ha" title="${g.home ? "À domicile" : "À l'extérieur"}">${g.home ? "vs" : "@"}</span>${teamBadge(g.opponent, { size: 18 })}</td>
        <td class="gl-res is-${g.result || "none"}"${label ? ` title="${label}"` : ""}>${res}</td>
        ${cells}
      </tr>`;
  }).join("");

  return `
    ${playerHeader(p)}
    <section class="block">
      <h2 class="section-title">Saison ${state.meta.season}</h2>
      <div class="totals-row">${totals}</div>
    </section>
    <section class="block">
      <h2 class="section-title">Match par match</h2>
      <div class="table-scroll">
        <table class="game-log game-log-key">
          <thead>
            ${grp.replace("<th></th></tr>", "</tr>")}
            <tr><th scope="col">Sem.</th><th scope="col">Adv.</th><th scope="col">Rés.</th>${cols}</tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>`;
}

// --- Classements par poste (app/data/rankings.py) -------------------------
const RK_TITLES = {
  QB: "Quarterbacks", RB: "Running backs", WR: "Wide receivers", TE: "Tight ends",
  EDGE: "Edge rushers", DT: "Defensive tackles", LB: "Linebackers", CB: "Cornerbacks",
  S: "Safeties", K: "Kickers",
};
// mode : "avg" (moyenne par match, critère du classement) ou "total".
// sort : colonne triée ("rank", "name", "team", "games", "score" ou "g.i").
state.rk = { data: null, stamp: null, mode: "avg", sort: { key: "rank", desc: false } };

async function loadRankings() {
  if (state.rk.data && state.rk.stamp === metaStamp()) return state.rk.data;
  const d = await api("/api/rankings");
  state.rk.data = d;
  state.rk.stamp = metaStamp();
  return d;
}

const rkScore = (r) => (state.rk.mode === "avg" ? r.score_avg : r.score_total);

// Rang selon le mode : score décroissant, joueurs sous le minimum de matchs
// à la fin ; puis tri d'affichage choisi (ils restent à la fin).
function rkRanked(pos) {
  const other = (r) => (state.rk.mode === "avg" ? r.score_total : r.score_avg);
  const ranked = [...pos.rows].sort((a, b) => (b.eligible - a.eligible) || rkScore(b) - rkScore(a)
    || other(b) - other(a) || a.name.localeCompare(b.name, "fr"));
  ranked.forEach((r, i) => { r.rk = i + 1; });
  const { key, desc } = state.rk.sort;
  if (key === "rank") return desc ? [...ranked].reverse().sort((a, b) => b.eligible - a.eligible) : ranked;
  const groups = STAT_GROUPS[pos.score];
  const games = (r) => (state.rk.mode === "avg" ? r.games : null);
  let val;
  if (key === "name") val = (r) => r.name;
  else if (key === "team") val = (r) => r.team;
  else if (key === "games") val = (r) => r.games;
  else if (key === "score") val = rkScore;
  else {
    const [gi, i] = key.split(".").map(Number);
    const c = groups[gi].cols[i];
    val = (r) => statSortValue(c, r.totals, games(r));
  }
  const cmp = (a, b) => {
    const x = val(a), y = val(b);
    const d = typeof x === "string" ? x.localeCompare(y, "fr") : x - y;
    return desc ? -d : d;
  };
  return ranked.sort((a, b) => (b.eligible - a.eligible) || cmp(a, b) || a.rk - b.rk);
}

function rkTable(pos, minGames) {
  const groups = STAT_GROUPS[pos.score];
  const { key, desc } = state.rk.sort;
  const avg = state.rk.mode === "avg";
  const th = (k, label, title, cls = "") => {
    const sorted = key === k;
    const aria = sorted ? ` aria-sort="${desc ? "descending" : "ascending"}"` : "";
    return `<th scope="col"${cls ? ` class="${cls}"` : ""}${aria}><button type="button" class="rk-sort" data-sort="${k}" title="${esc(title)}">${label}</button></th>`;
  };
  const { grp, cols } = groupedHead(groups, 5, (c, start, k) => th(k, esc(c.k), c.title, start ? "grp-start" : ""));
  const rows = rkRanked(pos).map((r, i) => {
    const g = avg ? r.games : null;
    const cells = groups.flatMap((gr, gi) => gr.cols.map((c, i) =>
      `<td${i === 0 && (groups.length > 1 || gi > 0) ? ' class="grp-start"' : ""}>${statText(c, r.totals, g)}</td>`)).join("");
    const low = r.eligible ? "" : ` class="is-low" title="Moins de ${minGames} matchs joués"`;
    return `
      <tr data-href="#/player/${encodeURIComponent(r.player_id)}"${low}>
        <td class="rk-rank">${r.rk}</td>
        <td class="rk-photo">${headshot(r)}</td>
        <th scope="row" class="rk-name"><a class="player-link" href="#/player/${encodeURIComponent(r.player_id)}">${esc(r.name)}</a></th>
        <td class="rk-team">${teamBadge(r.team, { size: 18, lazy: i >= 12 })}</td>
        <td>${r.games}</td>
        ${cells}
        <td class="rk-score">${nfAvg.format(rkScore(r))}</td>
      </tr>`;
  }).join("");
  return `
    <div class="table-scroll">
      <table class="rankings">
        <thead>
          ${grp}
          <tr>
            ${th("rank", "#", "Rang")}
            <th scope="col" class="rk-photo"><span class="visually-hidden">Portrait</span></th>
            ${th("name", "Joueur", "Nom", "rk-name")}
            ${th("team", "Équipe", "Équipe", "rk-team")}
            ${th("games", "MJ", "Matchs joués")}
            ${cols}
            ${th("score", "Score", avg ? "Score moyen par match" : "Score total de la saison", "rk-score")}
          </tr>
        </thead>
        <tbody>${rows || `<tr><td colspan="${6 + groups.reduce((n, gr) => n + gr.cols.length, 0)}" class="state-msg">Aucun joueur.</td></tr>`}</tbody>
      </table>
    </div>`;
}

function rkStrip(data, current) {
  return `
    <nav class="week-strip rk-strip" aria-label="Poste">
      ${data.positions.map((p) => `<a href="#/rankings/${esc(p.key)}" title="${esc(RK_TITLES[p.key] || p.key)}"${p.key === current ? ' aria-current="page"' : ""}>${esc(p.key)}</a>`).join("")}
    </nav>`;
}

function rkTools() {
  const b = (mode, label) => `<button type="button" class="link-plain" data-mode="${mode}" aria-pressed="${state.rk.mode === mode}">${label}</button>`;
  return `<div class="rk-toggle" role="group" aria-label="Valeurs affichées">${b("total", "Total saison")}<span aria-hidden="true">/</span>${b("avg", "Moyenne par match")}</div>`;
}

function rkSub(pos, data) {
  const what = pos.score === "kicker" ? "le plus de matchs joués" : "le plus de snaps sur la saison";
  return `${esc(RK_TITLES[pos.key] || pos.key)} · le titulaire de chaque équipe (${what}), classé sur le score du poste. Moins de ${data.min_games} matchs joués : en fin de classement.`;
}

async function renderRankings(key) {
  setNav("rankings");
  let shell = view.querySelector(".rk-shell");
  if (shell && shell.dataset.stamp !== metaStamp()) shell = null;
  const body = shell?.querySelector(".rk-body");
  loadingLater(body || view);
  const seq = state.routeSeq;
  let data;
  try {
    data = await loadRankings();
  } catch (err) {
    if (seq === state.routeSeq) setMessage(`Impossible de charger les classements : ${err.message}`, true);
    return;
  }
  if (seq !== state.routeSeq) return;
  const pos = data.positions.find((p) => p.key === key) || data.positions[0];
  if (!pos) { setMessage("Classements indisponibles.", true); return; }
  if (state.rk.pos !== pos.key) state.rk.sort = { key: "rank", desc: false };
  state.rk.pos = pos.key;
  document.title = `Classement des joueurs · ${pos.key} — NFL Gameday`;

  if (body) {
    // Changement de poste : titre, sélecteur et interrupteur restent en place,
    // seul le tableau fait le fondu.
    shell.querySelectorAll(".rk-strip a").forEach((a) => {
      if (a.getAttribute("href") === `#/rankings/${pos.key}`) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    shell.querySelector(".rk-sub").innerHTML = rkSub(pos, data);
    paint(rkTable(pos, data.min_games), body);
    return;
  }
  paint(`
    <div class="rk-shell" data-stamp="${esc(metaStamp())}">
      <div class="page-head"><h1 class="page-title">Joueurs</h1></div>
      <p class="page-sub rk-sub">${rkSub(pos, data)}</p>
      ${rkStrip(data, pos.key)}
      <div class="rk-tools">${rkTools()}</div>
      <div class="rk-body">${rkTable(pos, data.min_games)}</div>
    </div>`);
}

// Tri, interrupteur et clic sur une ligne : le tableau est redessiné sur
// place, sans animation (ni l'en-tête ni le sélecteur ne bougent).
function redrawRankings() {
  const body = view.querySelector(".rk-shell .rk-body");
  const pos = state.rk.data?.positions.find((p) => p.key === state.rk.pos);
  if (!body || !pos) return;
  const scroll = body.querySelector(".table-scroll")?.scrollLeft || 0;
  body.innerHTML = rkTable(pos, state.rk.data.min_games);
  const ts = body.querySelector(".table-scroll");
  if (ts) ts.scrollLeft = scroll;
}

view.addEventListener("click", (e) => {
  const shell = e.target.closest(".rk-shell");
  if (!shell) return;
  const sort = e.target.closest(".rk-sort");
  if (sort) {
    const k = sort.dataset.sort;
    const cur = state.rk.sort;
    // Premier clic : croissant pour le rang, le nom et l'équipe ; décroissant sinon.
    state.rk.sort = cur.key === k ? { key: k, desc: !cur.desc } : { key: k, desc: !["rank", "name", "team"].includes(k) };
    redrawRankings();
    view.querySelector(`.rk-sort[data-sort="${k}"]`)?.focus();
    return;
  }
  const mode = e.target.closest("[data-mode]");
  if (mode) {
    state.rk.mode = mode.dataset.mode;
    shell.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === state.rk.mode)));
    redrawRankings();
    return;
  }
  const row = e.target.closest("tr[data-href]");
  if (row && !e.target.closest("a")) location.hash = row.dataset.href;
});

// --- Routage ----------------------------------------------------------
async function route() {
  state.routeSeq += 1;
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [page, arg] = parts;
  if (page === "week" && /^\d+$/.test(arg || "")) return renderWeek(Number(arg));
  if (page === "game" && arg) return renderGame(decodeURIComponent(arg));
  if (page === "standings") return renderStandings();
  if (page === "rankings") return renderRankings(arg ? decodeURIComponent(arg).toUpperCase() : null);
  if (page === "player" && arg) return renderPlayer(decodeURIComponent(arg));
  return renderWeek(state.meta.current_week ?? 1);
}

// Flèches gauche/droite : semaine précédente/suivante (page semaine uniquement).
document.addEventListener("keydown", (e) => {
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  if (e.target.closest("input, textarea, select, [contenteditable]")) return;
  const weeks = state.meta?.weeks.map((w) => w.week) || [];
  const m = /^#\/week\/(\d+)$/.exec(location.hash) || (/^#?\/?$/.test(location.hash) ? [null, String(state.meta?.current_week)] : null);
  if (!m) return;
  const i = weeks.indexOf(Number(m[1]));
  const j = e.key === "ArrowLeft" ? i - 1 : i + 1;
  if (i >= 0 && j >= 0 && j < weeks.length) location.hash = `#/week/${weeks[j]}`;
});

// Pages semaine : #/week/8, ou #/ (semaine courante).
const isWeekHash = (h) => /^#\/week\/\d+$/.test(h) || /^#?\/?$/.test(h);

// Classements : #/rankings ou #/rankings/WR.
const isRankingsHash = (h) => /^#\/rankings(\/[\w]+)?$/.test(h);

window.addEventListener("hashchange", async () => {
  const body = isWeekHash(location.hash) ? view.querySelector(".week-shell .week-body") : null;
  const rkBody = isRankingsHash(location.hash) ? view.querySelector(".rk-shell .rk-body") : null;
  if (rkBody) {
    // Poste -> poste : seul le tableau s'anime.
    await anim.leave(rkBody);
    route();
    return;
  }
  if (body) {
    // Semaine -> semaine : seul le contenu sous le sélecteur s'anime. On ne
    // remonte que si le sélecteur est sorti de l'écran (flèches du clavier).
    await anim.leave(body);
    if (view.querySelector(".week-strip").getBoundingClientRect().bottom < 0) window.scrollTo(0, 0);
  } else {
    await anim.leave(view); // fondu sortant bref, puis nouvelle page
    window.scrollTo(0, 0);
  }
  route();
});

(async function init() {
  setMessage("Chargement des données…");
  try {
    await loadMeta();
  } catch (err) {
    setMessage(`Impossible de charger les données : ${err.message}`, true);
    return;
  }
  route();
  setInterval(renderMasthead, 60000);
})();
