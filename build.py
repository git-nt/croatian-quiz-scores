"""Build static HTML site from rank.xlsx data and Jinja2 templates."""

from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from data import (
    SERIES,
    SERIES_BY_CODE,
    aggregate_medals,
    blurb_for_key,
    load_ranking_data,
    medalists_by_event,
    series_code_from_key,
)

BASE = Path(__file__).resolve().parent
OUT = BASE / "_site"


def event_label(key: str, label: str) -> str:
    """Return display label for a tournament; WQC gets '(Croatia)' qualifier."""
    if series_code_from_key(key) == "wqc":
        m = re.search(r"(\d{4})", label)
        return f"WQC {m.group(1)} (Croatia)" if m else label
    return label


def player_slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "player"


def _build_timeline(data, p, tl_live, tl_hks, tl_defunct):
    event_map: dict[tuple[str, int], str] = {}
    all_years: set[int] = set()
    for t in data.tournaments:
        y = t.year
        if y is None:
            continue
        yr = int(y)
        sc = series_code_from_key(t.key)
        event_map[(sc, yr)] = t.key
        all_years.add(yr)

    years = sorted(all_years)

    def _make_cells(series_list):
        rows = []
        for code, label in series_list:
            cells = []
            for yr in years:
                tkey = event_map.get((code, yr))
                if tkey is None:
                    cells.append({"year": yr, "state": "no_event"})
                else:
                    ed = p.event_details.get(tkey)
                    if ed is None:
                        cells.append({"year": yr, "state": "absent", "key": tkey})
                    else:
                        if ed.rank == 1:
                            css = "tl-gold"
                        elif ed.rank == 2:
                            css = "tl-silver"
                        elif ed.rank == 3:
                            css = "tl-bronze"
                        elif ed.is_finalist:
                            css = "tl-final"
                        else:
                            css = "tl-played"
                        cells.append({
                            "year": yr,
                            "state": "played",
                            "rank": ed.rank,
                            "css": css,
                            "key": tkey,
                        })
            # Only include a series row if the player was at least absent once
            # (i.e. the event was held at least once in their year range)
            if any(c["state"] != "no_event" for c in cells):
                rows.append({"code": code, "label": label, "cells": cells})
        return rows

    return years, _make_cells(tl_live), _make_cells(tl_hks), _make_cells(tl_defunct)


def build(base_url: str = ""):
    base_url = base_url.rstrip("/")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    static_src = BASE / "static"
    if static_src.exists():
        shutil.copytree(static_src, OUT / "static")

    env = Environment(
        loader=FileSystemLoader(str(BASE / "templates")),
        autoescape=True,
    )
    def is_hks_event(key: str) -> bool:
        info = SERIES_BY_CODE.get(series_code_from_key(key))
        return info is not None and info.category == "hks"

    env.globals["player_slug"] = player_slug
    env.globals["event_label"] = event_label
    env.globals["is_hks_event"] = is_hks_event
    env.globals["series_code_from_key"] = series_code_from_key
    env.globals["base_url"] = base_url

    data = load_ranking_data()
    live_codes = {s.code for s in SERIES if s.category == "live"}
    hks_codes  = {s.code for s in SERIES if s.category == "hks"}
    medals_all  = aggregate_medals(data)
    medals_live = aggregate_medals(data, filter_codes=live_codes)
    medals_hks  = aggregate_medals(data, filter_codes=hks_codes)
    medals_by_series = {s.code: aggregate_medals(data, filter_codes={s.code}) for s in SERIES}
    events_medals = list(reversed(medalists_by_event(data)))
    pages = 0

    def write_page(path: str, template_name: str, context: dict):
        nonlocal pages
        tpl = env.get_template(template_name)
        html = tpl.render(**context)
        dest = OUT / path / "index.html" if path else OUT / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")
        pages += 1

    # ── Home (= players list) ──
    players_sorted = sorted(data.players, key=lambda p: p.name.lower())
    player_options = [
        {"name": pl.name, "slug": player_slug(pl.name)}
        for pl in players_sorted
    ]
    write_page("", "players.html", {
        "title": "All players",
        "players": players_sorted,
        "player_options": player_options,
    })

    # ── Medals ──
    write_page("medals", "medals.html", {
        "title": "Medalists",
        "medals_all": medals_all,
        "medals_live": medals_live,
        "medals_hks": medals_hks,
        "medals_by_series": medals_by_series,
        "series": SERIES,
        "events_medals": events_medals,
        "data": data,
        "blurb_for_key": blurb_for_key,
    })

    # ── Player detail pages ──
    tl_live_series   = [(s.code, s.name) for s in SERIES if s.category == "live" and not s.defunct]
    tl_hks_series    = [(s.code, s.name) for s in SERIES if s.category == "hks"]
    tl_defunct_series = [(s.code, s.name) for s in SERIES if s.defunct]

    for p in data.players:
        slug = player_slug(p.name)
        g, s, b = p.medal_counts()

        podium_hks: list[dict] = []
        podium_live: list[dict] = []
        history: list[dict] = []
        chart_labels: list[str] = []
        chart_ranks: list[int] = []
        for t in data.tournaments:
            ed = p.event_details.get(t.key)
            if ed is not None:
                history.append({"t": t, "ed": ed})
                chart_labels.append(t.label)
                chart_ranks.append(ed.rank)
                if ed.rank <= 3:
                    code = series_code_from_key(t.key)
                    s_info = SERIES_BY_CODE.get(code)
                    if s_info and s_info.category == "hks":
                        podium_hks.append({"t": t, "rank": ed.rank})
                    else:
                        podium_live.append({"t": t, "rank": ed.rank})
        podium_hks.sort(key=lambda m: m["rank"])
        podium_live.sort(key=lambda m: m["rank"])
        podium = podium_hks + podium_live
        chart_labels_js = Markup(json.dumps(chart_labels, ensure_ascii=False))
        chart_ranks_js = Markup(json.dumps(chart_ranks, ensure_ascii=False))
        chart_max = max(chart_ranks) if chart_ranks else 1

        tl_years, tl_live, tl_hks, tl_defunct = _build_timeline(
            data, p, tl_live_series, tl_hks_series, tl_defunct_series
        )

        write_page(f"players/{slug}", "player.html", {
            "title": p.name,
            "player": p,
            "current_slug": slug,
            "player_options": player_options,
            "podium": podium,
            "podium_hks": podium_hks,
            "podium_live": podium_live,
            "history": history,
            "g": g,
            "s": s,
            "b": b,
            "blurb_for_key": blurb_for_key,
            "chart_labels_js": chart_labels_js,
            "chart_ranks_js": chart_ranks_js,
            "chart_max": chart_max,
            "has_chart": len(chart_ranks) >= 2,
            "tl_years": tl_years,
            "series": SERIES,
            "tl_live": tl_live,
            "tl_hks": tl_hks,
            "tl_defunct": tl_defunct,
        })

    # ── Tournaments list ──
    # Group tournaments by series then by category, HKS first
    from collections import defaultdict
    tournaments_by_series: dict[str, list] = defaultdict(list)
    for t in data.tournaments:
        sc = series_code_from_key(t.key)
        tournaments_by_series[sc].append(t)

    def _series_group(cat):
        return [
            {
                "series": s,
                "tournaments": sorted(
                    tournaments_by_series.get(s.code, []),
                    key=lambda t: t.year or 0,
                ),
            }
            for s in SERIES
            if s.category == cat and tournaments_by_series.get(s.code)
        ]

    # Events page: Live Events (active) then Defunct Live Events
    _events_live_order = ["mmm", "sova", "oo"]
    _events_defunct_order = ["zimko", "ovako"]

    def _series_group_filtered(cat, defunct):
        order = _events_live_order if not defunct else _events_defunct_order
        groups = [
            g for g in _series_group(cat)
            if g["series"].defunct == defunct
        ]
        return sorted(
            groups,
            key=lambda g: order.index(g["series"].code)
            if g["series"].code in order else 99,
        )

    category_groups = [
        {"label": "HKS", "groups": _series_group("hks")},
        {"label": "Live Events", "groups": _series_group_filtered("live", False)},
        {"label": "Defunct Live Events", "groups": _series_group_filtered("live", True)},
    ]
    write_page("events", "tournaments.html", {
        "title": "Events",
        "category_groups": category_groups,
        "blurb_for_key": blurb_for_key,
    })

    # ── Tournament detail pages ──
    for t in data.tournaments:
        rows = data.standings_rows(t.key)
        has_sheet = t.key in data.sheet_by_key
        podium: list[tuple[str, int]] = []
        for p in data.players:
            r = p.ranks.get(t.key)
            if r is not None and 1 <= r <= 3:
                podium.append((p.name, r))
        podium.sort(key=lambda x: (x[1], x[0].lower()))
        finalist_count = sum(1 for row in rows if row.is_finalist)
        placement_only = bool(rows) and not any(
            row.total is not None or row.is_finalist for row in rows
        )
        sc = series_code_from_key(t.key)
        is_score_only = SERIES_BY_CODE.get(sc) is not None and SERIES_BY_CODE[sc].category == "hks"
        write_page(f"events/{t.key}", "tournament.html", {
            "title": t.label,
            "t": t,
            "rows": rows,
            "has_sheet": has_sheet,
            "podium": podium,
            "finalist_count": finalist_count,
            "placement_only": placement_only,
            "is_score_only": is_score_only,
            "blurb_for_key": blurb_for_key,
        })

    print(f"Built {pages} pages → {OUT.relative_to(BASE)}/")


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else ""
    build(base)
