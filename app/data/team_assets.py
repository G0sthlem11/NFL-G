"""Couleurs et logos des équipes, préparés pour le front.

Couleurs : nflverse donne une couleur principale (team_color) et une
secondaire (team_color2). Le point de couleur affiché à côté de chaque
équipe doit rester visible sur le fond de la page. Pour chacun des deux
thèmes, on garde la principale si son contraste avec le fond atteint
MIN_CONTRAST, sinon la secondaire si elle fait mieux. Exemples : PIT (noir)
passe au jaune en thème sombre, NO (or pâle) au noir en thème clair.

Logos : copies locales des logos ESPN (team_logo_espn), dans
app/static/logos/<ABBR>.png (thème clair) et logos/dark/<ABBR>.png (variante
ESPN pour fond sombre), téléchargées une fois par
``py -m scripts.fetch_logos`` et versionnées. Aucun appel à ESPN au runtime.
Versions réduites en 48 px dans logos/48/ (et logos/48/dark/), pour les
petits logos à côté des abréviations.
"""
from __future__ import annotations

from pathlib import Path

# Fonds de page, à garder alignés sur --paper dans app/static/styles.css.
PAPER_LIGHT = "#f7f3ea"
PAPER_DARK = "#15140f"

# Seuil de contraste (rapport WCAG) en dessous duquel un point de couleur se
# confond avec le fond. 2:1 suffit pour un repère décoratif cerclé d'un filet.
MIN_CONTRAST = 2.0

LOGO_DIR = Path(__file__).resolve().parents[1] / "static" / "logos"

# Petits logos (à côté des abréviations, 16 à 24 px affichés) : logos/48/…,
# générés depuis les 128 px par ``py -m scripts.resize_logos``.
SMALL_LOGO_PX = 48

# Équipes dont la variante ESPN « 500-dark » est une silhouette blanche, sans
# couleur, qui détonne à côté des autres logos : on garde le logo couleur en
# thème sombre aussi. scripts.resize_logos signale toute nouvelle équipe dans
# ce cas. LAR et STL : anciennes abréviations des Rams (même logo que LA).
COLOR_LOGO_IN_DARK = frozenset({"LA", "LAR", "STL", "NYJ"})


def _luminance(hex_color: str) -> float | None:
    """Luminance relative WCAG d'une couleur #rrggbb, ou None si illisible."""
    h = (hex_color or "").strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        return None
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float | None:
    """Rapport de contraste WCAG entre deux couleurs (1 à 21)."""
    la, lb = _luminance(a), _luminance(b)
    if la is None or lb is None:
        return None
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def dot_color(primary: str | None, secondary: str | None, background: str) -> str | None:
    """Couleur du point d'équipe sur ce fond : la principale, sauf si elle est
    trop proche du fond et que la secondaire contraste mieux."""
    cp = contrast(primary, background) if primary else None
    if cp is None:
        return secondary if secondary and contrast(secondary, background) is not None else None
    if cp >= MIN_CONTRAST or not secondary:
        return primary
    cs = contrast(secondary, background)
    return secondary if cs is not None and cs > cp else primary


def logo_path(abbr: str, dark: bool = False, small: bool = False) -> str | None:
    """Chemin du logo relatif à la racine du site, s'il existe.
    ``dark`` : variante pour fond sombre (logos/dark/<ABBR>.png).
    ``small`` : version réduite (logos/48/…), générée par scripts.resize_logos.
    Pas de variante sombre pour COLOR_LOGO_IN_DARK : le front garde alors le
    logo couleur dans les deux thèmes."""
    if dark and abbr in COLOR_LOGO_IN_DARK:
        return None
    rel = f"dark/{abbr}.png" if dark else f"{abbr}.png"
    if small:
        rel = f"{SMALL_LOGO_PX}/{rel}"
    return f"logos/{rel}" if (LOGO_DIR / rel).is_file() else None
