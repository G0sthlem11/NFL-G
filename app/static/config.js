// Mode de données du front.
//   "api"    : servi par FastAPI (développement local), appels /api/...
//   "static" : export statique (dist/), lecture de /data/....json
// L'export (py -m app.export) remplace ce fichier par sa version "static".
window.GAMEDAY_CONFIG = { mode: "api" };
