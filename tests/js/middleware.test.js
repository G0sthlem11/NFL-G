// Tests du middleware de protection (node --test tests/js/). Aucune dépendance.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

import middleware, {
  COOKIE_NAME, MAX_FAILURES, PUBLIC_PATHS, SESSION_SECONDS,
  _resetForTests, safeHash, safeNext, signSession, verifySession,
} from "../../middleware.js";

const PASSWORD = "mot-de-passe-de-test-assez-long";
const SECRET = "secret-de-test-0123456789abcdef0123456789";
const BASE = "https://nfl-g.vercel.app";

beforeEach(() => {
  process.env.APP_PASSWORD = PASSWORD;
  process.env.SESSION_SECRET = SECRET;
  process.env.LOGIN_FAIL_DELAY_MS = "0";
  _resetForTests();
});

const get = (path, cookie) =>
  middleware(new Request(BASE + path, { headers: cookie ? { cookie: `${COOKIE_NAME}=${cookie}` } : {} }));

const login = (fields, ip = "203.0.113.7") =>
  middleware(new Request(BASE + "/login", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", "x-real-ip": ip },
    body: new URLSearchParams(fields).toString(),
  }));

test("manifeste, icônes et favicon passent sans cookie", async () => {
  for (const path of PUBLIC_PATHS) assert.equal(await get(path), undefined, path);
  assert.equal(await get("/manifest.webmanifest?v=2"), undefined);
});

test("liste publique limitée au strict nécessaire", () => {
  assert.deepEqual([...PUBLIC_PATHS].sort(), [
    "/apple-touch-icon.png", "/favicon.svg", "/icon-192.png", "/icon-512.png",
    "/icon-maskable-512.png", "/manifest.webmanifest",
  ]);
});

test("pages sans cookie : redirection vers la connexion", async () => {
  for (const path of ["/", "/index.html", "/app.js", "/styles.css", "/config.js", "/inconnu"]) {
    const r = await get(path);
    assert.equal(r.status, 302, path);
    assert.equal(r.headers.get("location"), `/login?next=${encodeURIComponent(path)}`);
    assert.equal(r.headers.get("cache-control"), "no-store");
  }
});

test("données sans cookie : 401 JSON, jamais le contenu", async () => {
  const r = await get("/data/meta.json");
  assert.equal(r.status, 401);
  assert.match(r.headers.get("content-type"), /application\/json/);
  assert.equal((await r.json()).detail, "Connexion requise");
});

test("cookie valide : la requête continue", async () => {
  const token = signSession(SECRET);
  assert.equal(await get("/", token), undefined);
  assert.equal(await get("/data/games/2026_08_CAR_GB.json", token), undefined);
});

test("cookie falsifié, mal formé, expiré ou signé avec un autre secret : refusé", async () => {
  const now = Math.floor(Date.now() / 1000);
  const good = signSession(SECRET);
  const [v, exp, sig] = good.split(".");
  const bad = [
    `${v}.${Number(exp) + 999}.${sig}`,                  // expiration modifiée
    `${v}.${exp}.${sig.slice(0, -2)}AA`,                 // signature modifiée
    signSession("un-autre-secret-0123456789abcdefghij"), // autre secret
    signSession(SECRET, now - SESSION_SECONDS - 10),     // expiré
    "n'importe-quoi", "", "v1.123", "v2.9999999999.abc",
  ];
  for (const token of bad) {
    assert.equal(verifySession(token, SECRET), false, token);
    const r = await get("/data/meta.json", token);
    assert.equal(r.status, 401, token);
  }
});

test("connexion réussie : cookie signé HttpOnly Secure SameSite=Lax d'un an", async () => {
  const r = await login({ password: PASSWORD, next: "/", hash: "#/game/2026_08_CAR_GB" });
  assert.equal(r.status, 303);
  assert.equal(r.headers.get("location"), "/#/game/2026_08_CAR_GB");
  const cookie = r.headers.get("set-cookie");
  for (const attr of ["HttpOnly", "Secure", "SameSite=Lax", "Path=/", `Max-Age=${SESSION_SECONDS}`]) {
    assert.ok(cookie.includes(attr), attr);
  }
  const token = cookie.split(";")[0].split("=").slice(1).join("=");
  assert.ok(verifySession(token, SECRET));
  assert.equal(await get("/", token), undefined);
});

test("mauvais mot de passe : 401, pas de cookie", async () => {
  const r = await login({ password: "faux", next: "/" });
  assert.equal(r.status, 401);
  assert.equal(r.headers.get("set-cookie"), null);
  assert.match(await r.text(), /Mot de passe incorrect/);
});

test("trop d'essais depuis la même IP : 429, même avec le bon mot de passe", async () => {
  for (let i = 0; i < MAX_FAILURES; i++) assert.equal((await login({ password: "faux" })).status, 401);
  assert.equal((await login({ password: PASSWORD })).status, 429);
  assert.equal((await login({ password: PASSWORD }, "198.51.100.9")).status, 303); // autre IP
});

test("page de connexion servie sans cookie, et déjà connecté -> redirection", async () => {
  const r = await get("/login?next=%2F");
  assert.equal(r.status, 200);
  const html = await r.text();
  assert.match(html, /type="password"/);
  assert.match(html, /Fraunces/);
  assert.ok(!html.includes(PASSWORD));
  const again = await get("/login?next=%2F", signSession(SECRET));
  assert.equal(again.status, 302);
  assert.equal(again.headers.get("location"), "/");
});

test("pas de redirection ouverte après connexion", () => {
  for (const evil of ["https://evil.example", "//evil.example", "/\\evil", "javascript:alert(1)", "/login", "/logout"]) {
    assert.equal(safeNext(evil), "/", evil);
  }
  assert.equal(safeNext("/?x=1"), "/?x=1");
  assert.equal(safeHash("#/player/00-0036264"), "#/player/00-0036264");
  assert.equal(safeHash("#<script>"), "");
});

test("déconnexion : cookie effacé", async () => {
  const r = await get("/logout", signSession(SECRET));
  assert.equal(r.status, 303);
  assert.match(r.headers.get("set-cookie"), /Max-Age=0/);
});

test("variables absentes ou trop courtes : tout est refusé (503), sauf les icônes", async () => {
  for (const [pw, sec] of [["", SECRET], [PASSWORD, ""], ["court", SECRET], [PASSWORD, "court"]]) {
    process.env.APP_PASSWORD = pw;
    process.env.SESSION_SECRET = sec;
    assert.equal((await get("/")).status, 503);
    assert.equal((await get("/data/meta.json")).status, 503);
    assert.equal((await get("/login")).status, 503);
    assert.equal(await get("/icon-512.png"), undefined);
  }
});
