# NFL Gameday — consignes pour Claude Code

@README.md

Le README ci-dessus est la référence du projet : fonctionnement, architecture, données, joueurs clés, déploiement et protection. Garde-le à jour, en français, à chaque changement. Ce fichier ne contient que ce qui n'a pas sa place dans le README. En début de session, lis `git log --oneline -20` pour voir où on en est.

## Environnement
- **Windows 11, PowerShell.** Toutes les commandes doivent fonctionner sous PowerShell.
- Python se lance avec **`py`**. La commande `python` n'est pas dans le PATH. Le venv s'active avec `.venv\Scripts\Activate.ps1`.
- Réponds-moi **en français**.

## Façon de travailler
- Avance par jalons. Montre-moi le résultat de chacun avant de passer au suivant.
- Quand une action est de mon côté (interface Vercel, GitHub, téléphone), donne-moi des étapes précises, puis arrête-toi et attends ma confirmation. L'interface Vercel change souvent : si un menu n'existe plus, indique le chemin le plus probable et le champ « Find » comme solution de secours.
- Avant chaque push, lance `py -m pytest` et `node --test "tests/js/*.test.js"`.
- Fais des commits réguliers avec des messages clairs.

## Sécurité
- **Ne me demande jamais un secret et ne le manipule jamais en clair** : token Vercel, `APP_PASSWORD`, `SESSION_SECRET`. C'est moi qui les saisis, dans les secrets GitHub ou les variables Vercel. Ils ne doivent jamais apparaître dans le code, les logs ou nos échanges.
- Tout changement qui touche à la protection d'accès ou à `middleware.js` ne doit **jamais ouvrir le site**, même temporairement. On déploie d'abord, on bascule ensuite, et on vérifie avec les commandes curl du README.
- Le middleware doit toujours **refuser par défaut** : si une variable manque ou qu'un cas n'est pas prévu, l'accès est bloqué.
- Seuls doivent rester publics le manifeste, les icônes, `favicon.svg` et `/login`.

## Design (à respecter pour toute nouvelle page)
- Minimaliste, beaucoup d'espace blanc, ni dégradés, ni ombres lourdes, ni emojis.
- **Fraunces** pour les titres et les scores, **Source Serif 4** pour le texte, et chiffres tabulaires dans les tableaux.
- Encre `#1C1B19` sur papier crème `#F5F1E8`, inversé en mode sombre. Un seul accent : orange brûlé `#B4532A`.
- Animations discrètes uniquement, via `anim.js`, et coupées si `prefers-reduced-motion`.
- **Logo** : des poteaux de foot US vus de face, avec un point orange entre les montants. Il est inline en `currentColor` dans l'en-tête, et décliné en favicon et en icônes d'app (180, 192, 512 et maskable 512). Ne le modifie pas sans me demander.
