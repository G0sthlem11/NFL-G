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

async function api(path, options) {
  const res = await fetch(path, options);
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

function setMessage(text, isError = false) {
  view.innerHTML = `<p class="state-msg${isError ? " is-error" : ""}">${esc(text)}</p>`;
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
  if (m?.fetched_at) {
    const d = new Date(m.fetched_at);
    updated.textContent = `Données mises à jour ${relativeTime(d)}`;
    updated.title = fmtUpdated.format(d);
  } else {
    updated.textContent = "";
  }
}

async function loadMeta() {
  const [meta, teams] = await Promise.all([api("/api/meta"), api("/api/teams")]);
  state.meta = meta;
  state.teams = new Map(teams.map((t) => [t.abbr, t]));
  renderMasthead();
}

document.getElementById("refresh").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "Actualisation…";
  try {
    await api("/api/refresh", { method: "POST" });
    await loadMeta();
    await route();
    btn.textContent = "Actualiser";
  } catch (err) {
    btn.textContent = "Échec — réessayer";
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

// Luminance relative (WCAG) d'une couleur #rrggbb.
function luminance(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return null;
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(m[1].slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

// Pastille d'équipe : couleur principale ; en mode sombre, la secondaire si
// la principale est trop foncée pour se voir sur le fond (PIT, LV, DAL…).
function teamColorStyle(t) {
  if (!t?.color) return "";
  let dark = t.color;
  const l1 = luminance(t.color), l2 = luminance(t.color2);
  if (l1 !== null && l1 < 0.05 && l2 !== null && l2 > l1) dark = t.color2;
  return ` style="--team:${esc(t.color)};--team-dark:${esc(dark)}"`;
}

function teamLine(abbr, score, outcome) {
  const t = state.teams.get(abbr);
  const color = teamColorStyle(t);
  const name = t ? `<span class="full">${esc(t.name)}</span><span class="nick">${esc(t.nick || t.name)}</span>` : "";
  return `
    <div class="team-line ${outcome}">
      <span class="pill"${color} aria-hidden="true"></span>
      <span class="abbr">${esc(abbr)}</span>
      <span class="team-name">${name}</span>
      <span class="score">${score === null || score === undefined ? "" : esc(score)}</span>
    </div>`;
}

function gameRow(g) {
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
        ${teamLine(g.away_team, g.away_score, awayCls)}
        ${teamLine(g.home_team, g.home_score, homeCls)}
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

async function renderWeek(week) {
  setNav("week");
  const weeks = state.meta.weeks.map((w) => w.week);
  const idx = weeks.indexOf(week);
  const prev = idx > 0 ? weeks[idx - 1] : null;
  const next = idx >= 0 && idx < weeks.length - 1 ? weeks[idx + 1] : null;
  const info = state.meta.weeks.find((w) => w.week === week);
  document.title = `${weekLabel(week)} — NFL Gameday`;

  const head = `
    <div class="page-head">
      <h1 class="page-title">${esc(weekLabel(week))}</h1>
      <div class="pager">
        ${prev !== null ? `<a href="#/week/${prev}">← ${esc(weekLabel(prev))}</a>` : `<span class="is-disabled">←</span>`}
        ${next !== null ? `<a href="#/week/${next}">${esc(weekLabel(next))} →</a>` : `<span class="is-disabled">→</span>`}
      </div>
    </div>
    ${info ? `<p class="page-sub">${weekSummary(info)}</p>` : ""}
    ${weekStrip(week)}`;

  if (!info) {
    view.innerHTML = head + `<p class="state-msg">Cette semaine n'est pas encore au calendrier.</p>`;
    return;
  }

  view.innerHTML = head + `<p class="state-msg">Chargement…</p>`;
  scrollStripToCurrent();
  const seq = state.routeSeq;
  let games;
  try {
    games = await api(`/api/weeks/${week}`);
  } catch (err) {
    if (seq !== state.routeSeq) return;
    view.innerHTML = head + `<p class="state-msg is-error">Impossible de charger la semaine : ${esc(err.message)}</p>`;
    return;
  }
  if (seq !== state.routeSeq) return; // l'utilisateur a changé de page entre-temps

  const playing = new Set(games.flatMap((g) => [g.away_team, g.home_team]));
  const byes = [...state.teams.keys()].filter((t) => !playing.has(t)).sort();
  const days = groupByDay(games).map((d) => `
    <section class="day">
      <h2 class="day-label">${esc(d.label)}</h2>
      <div class="games">${d.games.map(gameRow).join("")}</div>
    </section>`).join("");
  const byesHtml = week <= 18 && byes.length
    ? `<p class="byes">Exemptes : ${byes.map(esc).join(", ")}</p>` : "";

  view.innerHTML = head + days + byesHtml;
  scrollStripToCurrent();
}

function scrollStripToCurrent() {
  const strip = view.querySelector(".week-strip");
  const cur = strip?.querySelector('[aria-current="page"]');
  if (strip && cur) strip.scrollLeft = cur.offsetLeft - strip.clientWidth / 2 + cur.clientWidth / 2;
}

// --- Page match (provisoire, complétée au jalon 4) -----------------------
async function renderGame(gameId) {
  setNav("week");
  setMessage("Chargement…");
  try {
    const d = await api(`/api/games/${encodeURIComponent(gameId)}`);
    const g = d.game;
    document.title = `${g.away_team} – ${g.home_team} — NFL Gameday`;
    view.innerHTML = `
      <a class="back" href="#/week/${g.week}">← ${esc(g.week_label)}</a>
      <h1 class="page-title" style="margin-top:16px">${esc(g.away_team)} ${dash(g.away_score)} – ${dash(g.home_score)} ${esc(g.home_team)}</h1>
      <p class="page-sub">La fiche complète du match arrive au prochain jalon.</p>`;
  } catch (err) {
    setMessage(err.status === 404 ? "Match introuvable." : `Erreur : ${err.message}`, true);
  }
}

// --- Routage ----------------------------------------------------------
async function route() {
  state.routeSeq += 1;
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [page, arg] = parts;
  if (page === "week" && /^\d+$/.test(arg || "")) return renderWeek(Number(arg));
  if (page === "game" && arg) return renderGame(decodeURIComponent(arg));
  return renderWeek(state.meta.current_week ?? 1);
}

window.addEventListener("hashchange", () => {
  route();
  window.scrollTo(0, 0);
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
