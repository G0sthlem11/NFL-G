// Protection par mot de passe du site déployé sur Vercel (Routing Middleware).
//
// Laisse passer sans authentification UNIQUEMENT : le manifeste, les icônes,
// le favicon et la page de connexion (nécessaire pour que Chrome/Google puissent
// créer l'application installable). Tout le reste, /data/*.json compris, exige
// un cookie de session signé.
//
// Variables d'environnement Vercel (jamais dans le code) :
//   APP_PASSWORD    mot de passe d'accès (12 caractères minimum)
//   SESSION_SECRET  clé de signature des cookies (32 caractères minimum ;
//                   la changer déconnecte tous les appareils)
// S'il en manque une, le site refuse tout (503) au lieu de s'ouvrir.
//
// Ce fichier ne sert qu'en ligne : le mode local (FastAPI) n'est pas concerné.
//
// Uniquement des API Web standard (Web Crypto, TextEncoder, btoa/atob) : pas de
// `node:*` ni de `Buffer`, absents du runtime Edge sur lequel Vercel compile ce
// middleware. Le même code tourne sous Node 22 pour les tests.

export const COOKIE_NAME = "gd_session";
export const SESSION_SECONDS = 365 * 24 * 3600; // 1 an : pas de reconnexion dans l'app installée
export const PUBLIC_PATHS = new Set([
  "/manifest.webmanifest",
  "/favicon.svg",
  "/apple-touch-icon.png",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-maskable-512.png",
]);
const LOGIN_PATH = "/login";
const LOGOUT_PATH = "/logout";

// Limite basique contre les essais en boucle : 5 échecs par IP sur 15 min, puis
// refus (429) jusqu'à la fin de la fenêtre, et un délai après chaque échec.
// Le compteur vit dans la mémoire de l'instance : il n'est pas partagé entre
// instances. Le vrai rempart reste un mot de passe long et aléatoire.
export const MAX_FAILURES = 5;
const WINDOW_MS = 15 * 60 * 1000;
const failures = new Map(); // ip -> { count, first }

export function _resetForTests() {
  failures.clear();
}

// --- Signature du cookie (Web Crypto) --------------------------------------
const encoder = new TextEncoder();
const keys = new Map(); // secret -> Promise<CryptoKey>, importée une fois par instance

function hmacKey(secret) {
  if (!keys.has(secret)) {
    keys.set(secret, crypto.subtle.importKey(
      "raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"],
    ));
  }
  return keys.get(secret);
}

function b64urlEncode(bytes) {
  let bin = "";
  for (const b of new Uint8Array(bytes)) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(text) {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(text)) return null;
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4);
  try {
    return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  } catch {
    return null;
  }
}

export async function signSession(secret, nowSeconds = Math.floor(Date.now() / 1000)) {
  const payload = `v1.${nowSeconds + SESSION_SECONDS}`;
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(secret), encoder.encode(payload));
  return `${payload}.${b64urlEncode(sig)}`;
}

export async function verifySession(token, secret, nowSeconds = Math.floor(Date.now() / 1000)) {
  if (typeof token !== "string") return false;
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "v1" || !/^\d{1,12}$/.test(parts[1])) return false;
  if (Number(parts[1]) <= nowSeconds) return false; // expiré
  const sig = b64urlDecode(parts[2]);
  if (!sig) return false;
  // crypto.subtle.verify compare la signature à durée constante.
  return crypto.subtle.verify("HMAC", await hmacKey(secret), sig, encoder.encode(`${parts[0]}.${parts[1]}`));
}

async function samePassword(input, expected) {
  // Empreintes SHA-256 de même longueur, comparées à durée constante.
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(String(input))),
    crypto.subtle.digest("SHA-256", encoder.encode(String(expected))),
  ]);
  const x = new Uint8Array(a), y = new Uint8Array(b);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

// --- Petits utilitaires -----------------------------------------------------
function readCookie(header, name) {
  for (const part of (header || "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return null;
}

// Destination après connexion : chemin local uniquement (pas de redirection ouverte).
export function safeNext(next) {
  if (typeof next !== "string" || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/";
  if (next.startsWith(LOGIN_PATH) || next.startsWith(LOGOUT_PATH)) return "/";
  return next.length > 512 ? "/" : next;
}

// Fragment de l'app (#/game/...) conservé après connexion, s'il est sain.
export function safeHash(hash) {
  return typeof hash === "string" && /^#\/[\w\-/]{0,200}$/.test(hash) ? hash : "";
}

function clientIp(request) {
  const h = request.headers;
  return h.get("x-real-ip") || (h.get("x-forwarded-for") || "").split(",")[0].trim() || "inconnue";
}

function isBlocked(ip, now) {
  const f = failures.get(ip);
  if (!f) return false;
  if (now - f.first > WINDOW_MS) {
    failures.delete(ip);
    return false;
  }
  return f.count >= MAX_FAILURES;
}

function recordFailure(ip, now) {
  const f = failures.get(ip);
  if (!f || now - f.first > WINDOW_MS) failures.set(ip, { count: 1, first: now });
  else f.count += 1;
  if (failures.size > 5000) failures.clear(); // garde-fou mémoire
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failDelayMs = () => Number(process.env.LOGIN_FAIL_DELAY_MS ?? 1500);

const NO_STORE = { "Cache-Control": "no-store" };

function redirect(location, status = 302, extra = {}) {
  return new Response(null, { status, headers: { Location: location, ...NO_STORE, ...extra } });
}

// --- Page de connexion ------------------------------------------------------
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export function loginPage({ next = "/", error = "", status = 200 } = {}) {
  const html = `<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connexion — Gameday</title>
<meta name="robots" content="noindex">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#F5F1E8">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="manifest" href="/manifest.webmanifest?v=2" crossorigin="use-credentials">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png?v=2">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400..600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<style>
:root{--paper:#f7f3ea;--ink:#1d1b17;--ink-2:#4a463f;--muted:#776f62;--rule:#ddd5c6;--accent:#9c3d22}
@media (prefers-color-scheme:dark){:root{--paper:#15140f;--ink:#ece6d9;--ink-2:#bdb6a7;--muted:#8f887a;--rule:#34302a;--accent:#e08a64}}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Source Serif 4",Georgia,serif;font-size:17px;line-height:1.5;display:flex;align-items:center;justify-content:center;padding:24px 16px}
main{width:100%;max-width:340px}
.brand{display:flex;align-items:center;gap:10px;padding-bottom:14px;border-bottom:1px solid var(--ink);margin-bottom:28px}
.brand svg{width:40px;height:40px;margin-left:-6px}
.brand span{font-family:Fraunces,Georgia,serif;font-weight:600;font-size:26px;letter-spacing:-.01em}
h1{font-family:Fraunces,Georgia,serif;font-weight:400;font-size:30px;line-height:1.1;margin:0 0 6px}
p.sub{margin:0 0 24px;color:var(--muted);font-size:15px}
label{display:block;font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
input[type=password]{width:100%;padding:10px 0;border:0;border-bottom:1px solid var(--ink-2);background:transparent;color:var(--ink);font:inherit;font-size:20px;outline:none}
input[type=password]:focus{border-bottom-color:var(--accent)}
button{margin-top:22px;width:100%;padding:11px 16px;border:1px solid var(--ink);background:var(--ink);color:var(--paper);font:inherit;font-weight:600;cursor:pointer}
button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.error{margin:16px 0 0;color:var(--accent);font-size:15px}
</style>
</head>
<body>
<main>
  <div class="brand">
    <svg viewBox="0 0 100 100" aria-hidden="true"><g fill="currentColor"><rect x="20" y="10" width="6" height="48"/><rect x="74" y="10" width="6" height="48"/><rect x="20" y="52" width="60" height="6"/><rect x="47" y="58" width="6" height="34"/></g><circle cx="50" cy="30" r="7" fill="#B4532A"/></svg>
    <span>Gameday</span>
  </div>
  <h1>Accès privé</h1>
  <p class="sub">Saisis le mot de passe pour continuer.</p>
  <form method="post" action="${LOGIN_PATH}">
    <label for="password">Mot de passe</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
    <input type="hidden" name="next" value="${esc(safeNext(next))}">
    <input type="hidden" name="hash" id="hash" value="">
    <button type="submit">Entrer</button>
    ${error ? `<p class="error" role="alert">${esc(error)}</p>` : ""}
  </form>
</main>
<script>document.getElementById("hash").value = location.hash;</script>
</body>
</html>`;
  return new Response(html, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8", ...NO_STORE, "X-Robots-Tag": "noindex" },
  });
}

function configErrorPage() {
  return new Response(
    "Configuration incomplète : définir APP_PASSWORD (12 caractères min.) et SESSION_SECRET (32 caractères min.) dans Vercel, puis redéployer.",
    { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8", ...NO_STORE } },
  );
}

// --- Point d'entrée -----------------------------------------------------------
export default async function middleware(request) {
  const url = new URL(request.url);
  const path = url.pathname;

  // Fichiers publics : on laisse Vercel les servir (ne rien renvoyer = continuer).
  if (PUBLIC_PATHS.has(path)) return undefined;

  const password = process.env.APP_PASSWORD || "";
  const secret = process.env.SESSION_SECRET || "";
  if (password.length < 12 || secret.length < 32) return configErrorPage();

  const authenticated = await verifySession(readCookie(request.headers.get("cookie"), COOKIE_NAME), secret);

  if (path === LOGOUT_PATH) {
    return redirect(LOGIN_PATH, 303, {
      "Set-Cookie": `${COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax`,
    });
  }

  if (path === LOGIN_PATH) {
    if (request.method === "POST") return handleLogin(request, password, secret);
    const next = url.searchParams.get("next") || "/";
    if (authenticated) return redirect(safeNext(next));
    return loginPage({ next });
  }

  if (authenticated) return undefined; // session valide : on continue

  // Données : 401 (le front redirige vers la connexion) plutôt qu'une page HTML.
  if (path.startsWith("/data/")) {
    return new Response(JSON.stringify({ detail: "Connexion requise" }), {
      status: 401,
      headers: { "Content-Type": "application/json; charset=utf-8", ...NO_STORE },
    });
  }
  return redirect(`${LOGIN_PATH}?next=${encodeURIComponent(path + url.search)}`);
}

async function handleLogin(request, password, secret) {
  const ip = clientIp(request);
  const now = Date.now();
  let form;
  try {
    form = await request.formData();
  } catch {
    return loginPage({ error: "Requête invalide.", status: 400 });
  }
  const next = form.get("next") || "/";

  if (isBlocked(ip, now)) {
    return loginPage({ next, error: "Trop d'essais. Réessaie dans quelques minutes.", status: 429 });
  }

  if (!(await samePassword(form.get("password") || "", password))) {
    recordFailure(ip, now);
    await sleep(failDelayMs());
    return loginPage({ next, error: "Mot de passe incorrect.", status: 401 });
  }

  failures.delete(ip);
  const cookie = `${COOKIE_NAME}=${await signSession(secret)}; Path=/; Max-Age=${SESSION_SECONDS}; HttpOnly; Secure; SameSite=Lax`;
  return redirect(safeNext(next) + safeHash(form.get("hash")), 303, { "Set-Cookie": cookie });
}
