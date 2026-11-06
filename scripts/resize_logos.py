"""Génère les petits logos (48 px) à partir des logos 128 px déjà versionnés.

Usage : py -m scripts.resize_logos

Aucun téléchargement : le script lit app/static/logos/<ABBR>.png et
logos/dark/<ABBR>.png, et écrit logos/48/<ABBR>.png et logos/48/dark/<ABBR>.png.
Les petits logos s'affichent à côté des abréviations (16 à 24 px) : 48 px
couvre les écrans haute densité (×2, voire ×3 à 16 px) pour un poids bien
moindre que les 128 px. Les grands logos de la page Match restent en 128 px.

Dépendance : Pillow, seulement pour ce script (ni l'app ni l'Action n'en ont
besoin, les fichiers générés sont versionnés) :
    py -m pip install pillow
À relancer après ``py -m scripts.fetch_logos``.
"""
from __future__ import annotations

import sys

from PIL import Image

from app.data.team_assets import COLOR_LOGO_IN_DARK, LOGO_DIR, SMALL_LOGO_PX


# Poids visuel comparable d'un logo à l'autre. « Encre » : part de la boîte
# couverte par le logo une fois ajusté (0,14 pour NYJ, très allongé, 0,79 pour
# TEN, un disque plein). Les logos plus massifs que la médiane (INK_TARGET)
# sont réduits jusqu'à l'atteindre, sans descendre sous MIN_SCALE de leur
# taille ; les logos fins gardent toute la place disponible (on ne peut pas
# les agrandir davantage). Écart ramené d'environ 5,6x à environ 3x.
INK_TARGET = 0.36
MIN_SCALE = 0.75
MARGIN_PX = 1  # marge transparente autour du logo, dans la boîte de 48 px


def resize(src, dst) -> tuple[int, int]:
    S = SMALL_LOGO_PX
    with Image.open(src) as im:
        im = im.convert("RGBA")
        # Recadrage sur la partie visible (les marges ESPN varient un peu).
        mask = im.getchannel("A").point(lambda v: 255 if v > 24 else 0)
        bbox = mask.getbbox() or (0, 0, im.width, im.height)
        im, mask = im.crop(bbox), mask.crop(bbox)
        w, h = im.size
        inner = S - 2 * MARGIN_PX
        fit = min(inner / w, inner / h)
        ink = mask.histogram()[255] / (w * h) * (w * fit) * (h * fit) / inner ** 2
        scale = fit * max(MIN_SCALE, min(1.0, (INK_TARGET / ink) ** 0.5)) if ink else fit
        im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        # Centré sur un carré transparent : toutes les images ont la même taille.
        out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        out.paste(im, ((S - im.width) // 2, (S - im.height) // 2))
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Palette de 256 couleurs (transparence comprise) : invisible à cette
        # taille, et environ deux fois plus léger qu'un PNG en couleurs vraies.
        out.quantize(256, method=Image.Quantize.FASTOCTREE).save(dst, optimize=True)
    return src.stat().st_size, dst.stat().st_size


def saturation(path) -> float:
    """Saturation moyenne des pixels visibles (0 : blanc, gris ou noir uni)."""
    with Image.open(path) as im:
        hsv = im.convert("RGBA")
        alpha = hsv.getchannel("A").point(lambda v: 255 if v > 128 else 0)
        s = hsv.convert("RGB").convert("HSV").getchannel("S")
        hist = s.histogram(mask=alpha)
    n = sum(hist)
    return sum(i * c for i, c in enumerate(hist)) / n / 255 if n else 0.0


def check_monochrome_dark() -> None:
    """Signale les variantes sombres sans couleur, alors que le logo clair en a :
    elles détonnent, à ajouter à COLOR_LOGO_IN_DARK (app/data/team_assets.py)."""
    for light in sorted(LOGO_DIR.glob("*.png")):
        dark = LOGO_DIR / "dark" / light.name
        if not dark.is_file() or light.stem in COLOR_LOGO_IN_DARK:
            continue
        if saturation(dark) < 0.08 and saturation(light) >= 0.15:
            print(f"  {light.stem} : variante sombre monochrome, à ajouter à COLOR_LOGO_IN_DARK")


def main() -> int:
    total_src = total_dst = n = 0
    for sub in ("", "dark"):
        src_dir = LOGO_DIR / sub if sub else LOGO_DIR
        dst_dir = LOGO_DIR / str(SMALL_LOGO_PX) / sub if sub else LOGO_DIR / str(SMALL_LOGO_PX)
        for src in sorted(src_dir.glob("*.png")):
            a, b = resize(src, dst_dir / src.name)
            total_src, total_dst, n = total_src + a, total_dst + b, n + 1
    if not n:
        print(f"Aucun logo dans {LOGO_DIR} : lance d'abord py -m scripts.fetch_logos")
        return 1
    check_monochrome_dark()
    print(f"{n} logos : {total_src / 1024:.0f} Ko en 128 px -> {total_dst / 1024:.0f} Ko en {SMALL_LOGO_PX} px "
          f"({100 * (1 - total_dst / total_src):.0f} % de moins, {total_dst / n / 1024:.1f} Ko par logo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
