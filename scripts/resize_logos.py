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

from app.data.team_assets import LOGO_DIR, SMALL_LOGO_PX


def resize(src, dst) -> tuple[int, int]:
    with Image.open(src) as im:
        im = im.convert("RGBA")
        im.thumbnail((SMALL_LOGO_PX, SMALL_LOGO_PX), Image.LANCZOS)
        # Centré sur un carré transparent : toutes les images ont la même taille.
        out = Image.new("RGBA", (SMALL_LOGO_PX, SMALL_LOGO_PX), (0, 0, 0, 0))
        out.paste(im, ((SMALL_LOGO_PX - im.width) // 2, (SMALL_LOGO_PX - im.height) // 2))
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Palette de 256 couleurs (transparence comprise) : invisible à cette
        # taille, et environ deux fois plus léger qu'un PNG en couleurs vraies.
        out.quantize(256, method=Image.Quantize.FASTOCTREE).save(dst, optimize=True)
    return src.stat().st_size, dst.stat().st_size


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
    print(f"{n} logos : {total_src / 1024:.0f} Ko en 128 px -> {total_dst / 1024:.0f} Ko en {SMALL_LOGO_PX} px "
          f"({100 * (1 - total_dst / total_src):.0f} % de moins, {total_dst / n / 1024:.1f} Ko par logo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
