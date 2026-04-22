#!/usr/bin/env python3
"""Standalone static site generator for WQC stats. Output: wqc/site/

Usage:
  python build.py
  python build.py /your-github-pages-base   # e.g. /croatian-quiz-scores/wqc

Preview locally (serve the output folder ``wqc/site``, not the repo root):

  python -m http.server 8080 --directory wqc/site

With an empty base URL, CSS/JS use relative paths (e.g. ``../../static/wqc.css`` on
player pages) so they still resolve if the server root is not the project root.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

# Allow `python wqc/build.py` from repo root without installing the package.
WQC_ROOT = Path(__file__).resolve().parent
if str(WQC_ROOT) not in sys.path:
    sys.path.insert(0, str(WQC_ROOT))

from wqc_data import (
    DEFAULT_XLSX,
    GENRE_IDS,
    GENRE_LABEL,
    aggregate_medals,
    build_player_timeline,
    load_wqc_data,
    player_slug,
    player_wqc_podium_rows,
    podium_by_year_genre,
    podium_by_year_overall,
)

OUT = WQC_ROOT / "site"
TEMPLATES = WQC_ROOT / "templates"
STATIC_SRC = WQC_ROOT / "static"


def log(msg: str) -> None:
    print(msg, flush=True)


def write_page(env: Environment, rel: str, name: str, ctx: dict) -> None:
    ctx = {**ctx, "page_rel": rel}
    tpl = env.get_template(name)
    html = tpl.render(**ctx)
    dest = OUT / rel / "index.html" if rel else OUT / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else ""
    base_url = base_url.rstrip("/")

    log("WQC build: preparing output …")
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
        if OUT.exists():
            subprocess.run(["/bin/rm", "-rf", str(OUT)], check=False)
    OUT.mkdir(parents=True)
    if STATIC_SRC.exists():
        shutil.copytree(STATIC_SRC, OUT / "static")
        log(f"WQC build: copied static → {OUT / 'static'}")

    years, year_sheets, players, _genres_by_year = load_wqc_data()
    ys = year_sheets

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=True,
    )
    env.globals["base_url"] = base_url

    def asset_url(page_rel: str, filename: str) -> str:
        """Static files under ``site/static/``. When ``base_url`` is set (subpath deploy), use absolute URLs; otherwise paths relative to the HTML file so ``wqc/site`` can be opened without the server cwd being wrong."""
        if base_url:
            return f"{base_url}/static/{filename}"
        depth = 0 if not page_rel else page_rel.count("/") + 1
        return ("../" * depth) + f"static/{filename}"

    env.globals["asset_url"] = asset_url
    env.globals["player_slug"] = player_slug
    env.globals["GENRE_LABEL"] = GENRE_LABEL
    env.globals["GENRE_IDS"] = GENRE_IDS

    log("WQC build: aggregating medals …")
    medals_overall = aggregate_medals(ys, kind="overall")
    medals_by_genre = {gid: aggregate_medals(ys, kind=gid) for gid in GENRE_IDS}

    player_list = sorted(players.values(), key=lambda p: p.name.lower())
    player_options = [{"name": p.name, "slug": player_slug(p.name)} for p in player_list]

    podium_years = podium_by_year_overall(ys)
    podium_years_by_genre = {gid: podium_by_year_genre(ys, gid) for gid in GENRE_IDS}

    # ── Home ──
    write_page(env, "", "index.html", {
        "title": "Players",
        "player_options": player_options,
    })
    log("WQC build: wrote home (players search)")

    # ── Medals ──
    write_page(env, "medals", "medals.html", {
        "title": "Medals",
        "medals_overall": medals_overall,
        "medals_by_genre": medals_by_genre,
        "podium_years_overall": podium_years,
        "podium_years_by_genre": podium_years_by_genre,
    })
    log("WQC build: wrote medals")

    # ── Years index ──
    write_page(env, "years", "years.html", {
        "title": "Years",
        "years": list(reversed(years)),
    })
    log("WQC build: wrote years index")

    # ── Per year standings ──
    ny = len(years)
    for i, y in enumerate(years, start=1):
        ys_y = ys[y]
        write_page(env, f"years/{y}", "year.html", {
            "title": f"WQC {y}",
            "year": y,
            "rows": sorted(ys_y.rows, key=lambda r: r.rank),
            "genres_present": sorted(ys_y.genres_present, key=lambda g: GENRE_IDS.index(g) if g in GENRE_IDS else 99),
        })
        log(f"WQC build: year page [{i}/{ny}] WQC {y} ({len(ys_y.rows)} rows)")

    # ── Players ──
    npl = len(player_list)
    log(f"WQC build: writing {npl} player pages …")
    if npl > 2000:
        step = 500
    elif npl > 500:
        step = 250
    elif npl > 100:
        step = 50
    else:
        step = 10
    for pi, p in enumerate(player_list, start=1):
        slug = player_slug(p.name)
        tl_years, overall_row, genre_rows = build_player_timeline(p, years, ys)
        chart_labels = [f"WQC {y}" for y in years if y in p.by_year]
        chart_ranks = [p.by_year[y].rank for y in years if y in p.by_year]
        chart_labels_js = Markup(json.dumps(chart_labels, ensure_ascii=False))
        chart_ranks_js = Markup(json.dumps(chart_ranks, ensure_ascii=False))
        chart_max = max(chart_ranks) if chart_ranks else 1

        history_rows = []
        for y in years:
            if y not in p.by_year:
                continue
            r = p.by_year[y]
            history_rows.append({"year": y, "row": r})

        podium_overall_rows = player_wqc_podium_rows(p, None)
        podium_genre_rows = {gid: player_wqc_podium_rows(p, gid) for gid in GENRE_IDS}
        has_medal_block = bool(podium_overall_rows) or any(podium_genre_rows[gid] for gid in GENRE_IDS)

        write_page(env, f"players/{slug}", "player.html", {
            "title": p.name,
            "player": p,
            "current_slug": slug,
            "player_options": player_options,
            "overall_row": overall_row,
            "genre_rows": genre_rows,
            "tl_years": tl_years,
            "history_rows": history_rows,
            "chart_labels_js": chart_labels_js,
            "chart_ranks_js": chart_ranks_js,
            "chart_max": chart_max,
            "has_chart": len(chart_ranks) >= 2,
            "GENRE_IDS": GENRE_IDS,
            "podium_overall_rows": podium_overall_rows,
            "podium_genre_rows": podium_genre_rows,
            "has_medal_block": has_medal_block,
        })
        if pi == 1 or pi == npl or pi % step == 0:
            log(f"WQC build: player pages [{pi}/{npl}] …")

    log(f"WQC build: done → {OUT} (source {DEFAULT_XLSX.name})")


if __name__ == "__main__":
    main()
