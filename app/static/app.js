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
  { label: "1ers downs", get: (s) => s.first_downs, better: "high" },
  { label: "Turnovers", get: (s) => s.turnovers, better: "low" },
  { label: "Sacks subis", get: (s) => s.sacks_suffered, fmt: (s) => s.sacks_suffered == null ? "—" : `${s.sacks_suffered}${s.sack_yards_lost ? ` <span class="sub">−${s.sack_yards_lost}</span>` : ""}`, better: "low" },
  { label: "Pénalités", get: (s) => s.penalties, fmt: (s) => s.penalties == null ? "—" : `${s.penalties} <span class="sub">${dash(s.penalty_yards)} yds</span>`, better: "low" },
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

function roleStats(role, p) {
  if (role === "QB") {
    return statCells([
      ["C/A", p.completions == null ? "—" : `${p.completions}/${dash(p.attempts)}`],
      ["Yds", num(p.passing_yards)], ["TD", num(p.passing_tds)], ["INT", num(p.interceptions)],
      ["Sacks", num(p.sacks_suffered)], ["Course", p.carries ? `${p.carries}–${num(p.rushing_yards)}` : "—"],
    ]);
  }
  if (role === "RB1") {
    const avg = p.carries ? (p.rushing_yards ?? 0) / p.carries : null;
    return statCells([
      ["Courses", num(p.carries)], ["Yds", num(p.rushing_yards)], ["Moy.", num(avg)],
      ["TD", num(p.rushing_tds)], ["Réc.", num(p.receptions)],
    ]);
  }
  if (role.startsWith("EDGE")) {
    return statCells([
      ["Plaq.", num(p.tackles)], ["Sacks", num(p.sacks)], ["QB hits", num(p.qb_hits)], ["TFL", num(p.tackles_for_loss)],
    ]);
  }
  return statCells([
    ["Cibles", num(p.targets)], ["Réc.", num(p.receptions)], ["Yds", num(p.receiving_yards)], ["TD", num(p.receiving_tds)],
  ]);
}

function headshot(p) {
  if (!p.headshot_url) return `<span class="headshot is-empty" aria-hidden="true"></span>`;
  return `<img class="headshot" src="${esc(p.headshot_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'headshot is-empty'}))">`;
}

function playerCard(k) {
  const pos = k.depth_pos && k.depth_pos !== k.label ? `<span class="card-pos">${esc(k.depth_pos)}</span>` : "";
  const note = k.replaced_starter
    ? `<p class="card-note">Remplace ${esc(k.replaced_starter)} (${esc(k.replaced_reason || "absent")})</p>`
    : k.source === "fallback" ? `<p class="card-note">Choisi d'après la production du match</p>` : "";
  if (!k.player) {
    return `
      <article class="card">
        <h4 class="card-role">${esc(k.label)}${pos}</h4>
        <p class="card-name is-empty">—</p>${note}
      </article>`;
  }
  const p = k.player;
  return `
    <article class="card">
      <h4 class="card-role">${esc(k.label)}${pos}</h4>
      <div class="card-head">${headshot(p)}<p class="card-name">${playerLink(p)}</p></div>
      ${roleStats(k.role, p)}
      ${note}
    </article>`;
}

function bigPlays(list) {
  if (!list.length) return `<p class="state-msg">Aucun sack, interception ni fumble forcé.</p>`;
  const what = (p) => [
    p.def_interceptions ? `${num(p.def_interceptions)} INT` : "",
    p.fumbles_forced ? `${num(p.fumbles_forced)} FF` : "",
    p.sacks ? `${num(p.sacks)} sack${p.sacks > 1 ? "s" : ""}` : "",
  ].filter(Boolean).join(" · ");
  return `<ul class="big-plays">${list.map((p) => `
    <li><span class="bp-name">${playerLink(p)} <span class="bp-pos">${esc(p.position || "")}</span></span><span class="bp-what">${what(p)}</span></li>`).join("")}</ul>`;
}

function keyPlayersColumn(abbr, kp) {
  if (!kp) return "";
  const t = state.teams.get(abbr);
  const tl = kp.tackle_leader;
  const scheme = kp.scheme ? `<span class="scheme">· ${esc(kp.scheme)}</span>` : "";
  return `
    <div class="kp-col">
      <h3 class="kp-team"><span class="pill"${teamColorStyle(t)} aria-hidden="true"></span>${esc(teamName(abbr))}</h3>
      <h4 class="kp-sub">Attaque</h4>
      <div class="cards">${kp.offense.map(playerCard).join("")}</div>
      <h4 class="kp-sub">Défense ${scheme}</h4>
      <div class="cards">
        ${kp.edges.map(playerCard).join("")}
        <article class="card">
          <h4 class="card-role">Meilleur plaqueur</h4>
          ${tl ? `<div class="card-head">${headshot(tl)}<p class="card-name">${playerLink(tl)} <span class="bp-pos">${esc(tl.position || "")}</span></p></div>
            ${statCells([["Plaq.", num(tl.tackles)], ["Solo", num(tl.tackles_solo)], ["Ast.", num(tl.tackle_assists)], ["TFL", num(tl.tackles_for_loss)]])}`
            : `<p class="card-name is-empty">—</p>`}
        </article>
      </div>
      <h4 class="kp-sub">Sacks, interceptions, fumbles forcés</h4>
      ${bigPlays(kp.playmakers)}
    </div>`;
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
  const side = (abbr, score, cls, align) => `
    <div class="sb-team ${cls} ${align}">
      <span class="sb-abbr">${esc(abbr)}</span>
      <span class="sb-name">${esc(teamName(abbr))}</span>
    </div>
    ${final ? `<span class="sb-score ${cls}">${dash(score)}</span>` : ""}`;
  return `
    <p class="eyebrow">${esc(g.week_label)} · ${esc(when)}</p>
    <div class="scoreboard ${final ? "" : "is-scheduled"}">
      ${side(g.away_team, g.away_score, aw, "left")}
      <span class="sb-sep">${final ? "–" : "@"}</span>
      ${final ? `<span class="sb-score ${hw}">${dash(g.home_score)}</span>` : ""}
      <div class="sb-team ${hw} right">
        <span class="sb-abbr">${esc(g.home_team)}</span>
        <span class="sb-name">${esc(teamName(g.home_team))}</span>
      </div>
    </div>
    <p class="sb-status">${final ? (g.overtime ? "Final après prolongation" : "Final") : "Match à venir, heure de Paris"}</p>
    ${quarterTable(g)}
    ${conditions(g) ? `<p class="conditions">${conditions(g)}</p>` : ""}`;
}

async function renderGame(gameId) {
  setNav("week");
  setMessage("Chargement…");
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
       <section class="block">
         <h2 class="section-title">Joueurs clés</h2>
         <div class="kp-grid">${keyPlayersColumn(g.away_team, d.away_key)}${keyPlayersColumn(g.home_team, d.home_key)}</div>
       </section>`
    : "";
  view.innerHTML = `
    <a class="back" href="#/week/${g.week}">← ${esc(g.week_label)}</a>
    <header class="game-head">${scoreboard(g)}</header>
    ${body}`;
}

// --- Classement -------------------------------------------------------
const fmtPct = (v) => (v === null || v === undefined ? "—" : v.toFixed(3).replace(/^0(?=\.)/, ""));
const fmtDiff = (v) => (v > 0 ? `+${v}` : v < 0 ? `−${-v}` : "0");

function standingsTable(d) {
  const rows = d.rows.map((r, i) => {
    const t = state.teams.get(r.team);
    return `
      <tr${i === 0 ? ' class="is-leader"' : ""}>
        <th scope="row" class="st-team"><span class="st-team-inner">
          <span class="pill"${teamColorStyle(t)} aria-hidden="true"></span>
          <span class="st-abbr">${esc(r.team)}</span>
          <span class="st-name">${esc(r.name)}</span>
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
  document.title = "Classement — NFL Gameday";
  setMessage("Chargement…");
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
      ${divisions.filter((d) => d.conference === c).map(standingsTable).join("")}
    </section>`;
  view.innerHTML = `
    <div class="page-head"><h1 class="page-title">Classement</h1></div>
    <p class="page-sub">Saison régulière ${state.meta.season}, calculé à partir des résultats. Départage simplifié : confrontations directes, division, conférence, différence de points.</p>
    ${conf("AFC")}${conf("NFC")}`;
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
  setMessage("Chargement…");
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

  const cats = categoryOrder(p.position).filter((c) => CATEGORIES[c].has(p.totals));
  const logCats = cats.slice(0, 2); // le journal de matchs garde les deux catégories principales
  const teams = p.teams.map((t) => esc(teamName(t))).join(", ");

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
        <td class="gl-opp">${g.home ? "vs" : "@"} ${esc(g.opponent)}</td>
        <td class="gl-res is-${g.result || "none"}">${res}</td>
        ${cells}
      </tr>`;
  }).join("");

  view.innerHTML = `
    <button type="button" class="back link-plain" onclick="history.length > 1 ? history.back() : (location.hash = '#/')">← Retour</button>
    <header class="player-head">
      ${p.headshot_url ? `<img class="headshot headshot-lg" src="${esc(p.headshot_url)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
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
    </section>`;
}

// --- Routage ----------------------------------------------------------
async function route() {
  state.routeSeq += 1;
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [page, arg] = parts;
  if (page === "week" && /^\d+$/.test(arg || "")) return renderWeek(Number(arg));
  if (page === "game" && arg) return renderGame(decodeURIComponent(arg));
  if (page === "standings") return renderStandings();
  if (page === "player" && arg) return renderPlayer(decodeURIComponent(arg));
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
