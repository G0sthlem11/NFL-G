"""Couleurs des points d'équipe (contraste avec le fond) et logos locaux."""
import pytest

from app.data import team_assets as ta
from app.data.team_assets import PAPER_DARK, PAPER_LIGHT, contrast, dot_color, logo_path


def test_contrast_bounds():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#123456", "#123456") == pytest.approx(1.0)
    assert contrast("pas une couleur", "#ffffff") is None


@pytest.mark.parametrize("team, c1, c2, light, dark", [
    ("PIT", "#000000", "#FFB612", "#000000", "#FFB612"),  # noir illisible sur fond sombre
    ("GB", "#203731", "#FFB612", "#203731", "#FFB612"),   # vert foncé idem
    ("NO", "#D3BC8D", "#000000", "#000000", "#D3BC8D"),   # or pâle illisible sur fond clair
    ("KC", "#E31837", "#FFB612", "#E31837", "#E31837"),   # rouge lisible partout
    ("NYJ", "#003F2D", "#000000", "#003F2D", "#003F2D"),  # secondaire pire : on garde la principale
])
def test_dot_color_by_theme(team, c1, c2, light, dark):
    assert dot_color(c1, c2, PAPER_LIGHT) == light
    assert dot_color(c1, c2, PAPER_DARK) == dark


def test_dot_color_missing_values():
    assert dot_color(None, None, PAPER_LIGHT) is None
    assert dot_color(None, "#FFB612", PAPER_DARK) == "#FFB612"
    assert dot_color("#000000", None, PAPER_DARK) == "#000000"


def test_paper_colors_match_stylesheet():
    css = (ta.LOGO_DIR.parent / "styles.css").read_text(encoding="utf-8").lower()
    assert f"--paper: {PAPER_LIGHT}" in css and f"--paper: {PAPER_DARK}" in css


def test_logo_path(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "LOGO_DIR", tmp_path)
    (tmp_path / "KC.png").write_bytes(b"\x89PNG")
    assert logo_path("KC") == "logos/KC.png"
    assert logo_path("XXX") is None
    assert logo_path("KC", dark=True) is None
    (tmp_path / "dark").mkdir()
    (tmp_path / "dark" / "KC.png").write_bytes(b"png")
    assert logo_path("KC", dark=True) == "logos/dark/KC.png"
    assert logo_path("KC", small=True) is None
    (tmp_path / "48" / "dark").mkdir(parents=True)
    (tmp_path / "48" / "KC.png").write_bytes(b"png")
    (tmp_path / "48" / "dark" / "KC.png").write_bytes(b"png")
    assert logo_path("KC", small=True) == "logos/48/KC.png"
    assert logo_path("KC", dark=True, small=True) == "logos/48/dark/KC.png"


def _png_size(path):
    """Largeur et hauteur d'un PNG, lues dans son en-tête IHDR (sans Pillow)."""
    head = path.read_bytes()[:24]
    assert head.startswith(b"\x89PNG"), path
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


@pytest.mark.parametrize("sub", ["", "dark"])
def test_small_logos_versioned_for_every_logo(sub):
    """Chaque logo 128 px a sa version 48 px (py -m scripts.resize_logos), carrée,
    et nettement plus légère."""
    big_dir = ta.LOGO_DIR / sub if sub else ta.LOGO_DIR
    small_dir = ta.LOGO_DIR / str(ta.SMALL_LOGO_PX) / sub if sub else ta.LOGO_DIR / str(ta.SMALL_LOGO_PX)
    big = sorted(p.name for p in big_dir.glob("*.png"))
    assert len(big) >= 32
    assert sorted(p.name for p in small_dir.glob("*.png")) == big
    for name in big:
        assert _png_size(small_dir / name) == (ta.SMALL_LOGO_PX, ta.SMALL_LOGO_PX), name
    total_big = sum((big_dir / n).stat().st_size for n in big)
    total_small = sum((small_dir / n).stat().st_size for n in big)
    assert total_small < total_big / 2
