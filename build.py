"""Build static HTML site from rank.xlsx data and Jinja2 templates."""

from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
from types import SimpleNamespace
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

    def team_event_label(series_code: str, year: int) -> str:
        if series_code == "edp":
            return f"EDP {year}"
        s = SERIES_BY_CODE.get(series_code)
        return f"{s.name} {year}" if s else f"{series_code.upper()} {year}"
    env.globals["team_event_label"] = team_event_label
    env.globals["series_info"] = lambda code: SERIES_BY_CODE.get(code)

    # ── Event dates ──
    _event_dates: dict[str, dict] = {}
    _dates_file = BASE / "event_dates.json"
    if _dates_file.exists():
        with open(_dates_file, encoding="utf-8") as _f:
            _event_dates = json.load(_f)

    def event_date_for(key: str) -> dict | None:
        return _event_dates.get(key)

    env.globals["event_date_for"] = event_date_for

    data = load_ranking_data()
    live_codes = {s.code for s in SERIES if s.category == "live"}
    hks_codes  = {s.code for s in SERIES if s.category == "hks"}
    medals_all  = aggregate_medals(data)
    medals_live = aggregate_medals(data, filter_codes=live_codes)
    medals_hks  = aggregate_medals(data, filter_codes=hks_codes)
    medals_by_series = {s.code: aggregate_medals(data, filter_codes={s.code}) for s in SERIES}
    events_medals = list(reversed(medalists_by_event(data)))

    # ── Team championship data (all files in team_results/) ──
    from data import player_match_key as _pmk

    # Load every JSON file; filename stem = series code ("edp", "ovako", "sova", …)
    _all_team_raw: dict[str, list] = {}
    for _tf in sorted((BASE / "team_results").glob("*.json")):
        with open(_tf, encoding="utf-8") as _f:
            _all_team_raw[_tf.stem] = json.load(_f)

    # EDP specifically (for events page accordion + EDP year pages)
    edp_raw    = _all_team_raw.get("edp", [])
    edp_by_year = sorted(edp_raw, key=lambda e: e["year"], reverse=True)

    # Categorise series: "edp" → hks_team; everything else → live_team
    _live_team_codes = [c for c in _all_team_raw if c != "edp"]

    # Per-player team medal lookup: match_key → [{series, year, rank, team}]
    _team_player_medals: dict[str, list] = {}
    for _series_code, _entries in _all_team_raw.items():
        for entry in _entries:
            for slot in entry["podium"]:
                for member in slot["members"]:
                    mk = _pmk(member)
                    _team_player_medals.setdefault(mk, []).append({
                        "series": _series_code,
                        "year":   entry["year"],
                        "label":  entry.get("label"),
                        "rank":   slot["rank"],
                        "team":   slot["team"],
                        "members": slot["members"],
                    })
    for _ml in _team_player_medals.values():
        _ml.sort(key=lambda m: (m["rank"], m["year"]))

    def _team_medal_table(entries_iter):
        """(name, g, s, b, total) sorted by G desc from an iterable of {year,rank,…} dicts."""
        _counts: dict[str, list] = {}
        for e in entries_iter:
            for slot in e["podium"]:
                for member in slot["members"]:
                    _counts.setdefault(member, [0, 0, 0])[slot["rank"] - 1] += 1
        return sorted(
            [(n, g, s, b, g+s+b) for n, (g, s, b) in _counts.items()],
            key=lambda x: (-x[1], -x[2], -x[3], x[0].lower()),
        )

    # All team medals combined
    team_medals_all = _team_medal_table(
        e for entries in _all_team_raw.values() for e in entries
    )
    # EDP only
    team_medals_edp = _team_medal_table(edp_raw)
    # Per live-series team medals
    team_medals_by_series = {
        code: _team_medal_table(_all_team_raw[code])
        for code in _live_team_codes
    }
    # Live Opens combined (all non-EDP)
    team_medals_live = _team_medal_table(
        e for code in _live_team_codes for e in _all_team_raw[code]
    )
    # Live team series sorted by SERIES order for consistent display
    live_team_series = [s for s in SERIES if s.code in _live_team_codes]

    # ── Pair championship data (all files in pair_results/) ──
    _all_pair_raw: dict[str, list] = {}
    for _pf in sorted((BASE / "pair_results").glob("*.json")):
        with open(_pf, encoding="utf-8") as _f:
            _all_pair_raw[_pf.stem] = json.load(_f)

    def _hr_key(name: str) -> str:
        """Croatian-alphabet sort key by surname (Č<D, Š<T<U<V, Ž after Z)."""
        s = name.split()[-1].lower()
        out, i = [], 0
        while i < len(s):
            c = s[i]
            nxt = s[i+1] if i+1 < len(s) else ""
            if c == "č":   out.append("cz1")
            elif c == "ć": out.append("cz2")
            elif c == "đ": out.append("dz")
            elif c == "š": out.append("sz")   # s < š < t
            elif c == "ž": out.append("zz")   # z < ž
            elif c == "l" and nxt == "j": out.append("lz"); i += 1
            elif c == "n" and nxt == "j": out.append("nz"); i += 1
            else: out.append(c)
            i += 1
        return "".join(out)

    # Normalize live pair order: sort each pair alphabetically by surname (Croatian)
    for _sc, _entries in _all_pair_raw.items():
        if _sc == "php":
            continue
        for _e in _entries:
            for _slot in _e["podium"]:
                _slot["players"] = sorted(_slot["players"], key=_hr_key)

    # Normalize team member order: sort alphabetically by surname (Croatian, all series)
    for _sc, _entries in _all_team_raw.items():
        for _e in _entries:
            for _slot in _e["podium"]:
                _slot["members"] = sorted(_slot["members"], key=_hr_key)

    # PHP specifically (for events page + PHP year pages)
    php_raw = _all_pair_raw.get("php", [])
    php_by_year = sorted(php_raw, key=lambda e: e["year"], reverse=True)

    # Categorise: "php" → hks_pair; everything else → live_pair
    _live_pair_codes = [c for c in _all_pair_raw if c != "php"]

    # Per-player pair medal lookup: match_key → [{series, year, rank, players}]
    _pair_player_medals: dict[str, list] = {}
    for _series_code, _entries in _all_pair_raw.items():
        for entry in _entries:
            for slot in entry["podium"]:
                for player in slot["players"]:
                    mk = _pmk(player)
                    _pair_player_medals.setdefault(mk, []).append({
                        "series":  _series_code,
                        "year":    entry["year"],
                        "label":   entry.get("label"),
                        "rank":    slot["rank"],
                        "players": slot["players"],
                    })
    for _ml in _pair_player_medals.values():
        _ml.sort(key=lambda m: (m["rank"], m["year"]))

    def _pair_medal_table(entries_iter):
        """(name, g, s, b, total) sorted by G desc from pair entries."""
        _counts: dict[str, list] = {}
        for e in entries_iter:
            for slot in e["podium"]:
                for player in slot["players"]:
                    _counts.setdefault(player, [0, 0, 0])[slot["rank"] - 1] += 1
        return sorted(
            [(n, g, s, b, g+s+b) for n, (g, s, b) in _counts.items()],
            key=lambda x: (-x[1], -x[2], -x[3], x[0].lower()),
        )

    pair_medals_all  = _pair_medal_table(e for entries in _all_pair_raw.values() for e in entries)

    # Combined medal table across individual + pairs + teams
    def _combined_medal_table():
        counts: dict[str, list] = {}
        # Individual
        for name, g, s, b, _ in medals_all:
            counts.setdefault(name, [0, 0, 0])
            counts[name][0] += g; counts[name][1] += s; counts[name][2] += b
        # Teams
        for e in (e for entries in _all_team_raw.values() for e in entries):
            for slot in e["podium"]:
                for m in slot["members"]:
                    counts.setdefault(m, [0, 0, 0])[slot["rank"] - 1] += 1
        # Pairs
        for e in (e for entries in _all_pair_raw.values() for e in entries):
            for slot in e["podium"]:
                for p in slot["players"]:
                    counts.setdefault(p, [0, 0, 0])[slot["rank"] - 1] += 1
        return sorted(
            [(n, g, s, b, g+s+b) for n, (g, s, b) in counts.items()],
            key=lambda x: (-x[1], -x[2], -x[3], x[0].lower()),
        )
    medals_combined = _combined_medal_table()
    pair_medals_php  = _pair_medal_table(php_raw)
    pair_medals_live = _pair_medal_table(
        e for code in _live_pair_codes for e in _all_pair_raw[code]
    )
    pair_medals_by_series = {
        code: _pair_medal_table(_all_pair_raw[code]) for code in _live_pair_codes
    }
    live_pair_series = [s for s in SERIES if s.code in _live_pair_codes]

    def pair_event_label(series_code: str, year: int) -> str:
        if series_code == "php":
            return f"PHP {year}"
        s = SERIES_BY_CODE.get(series_code)
        return f"{s.name} {year}" if s else f"{series_code.upper()} {year}"
    env.globals["pair_event_label"] = pair_event_label

    # Set of known player slugs for linking
    known_slugs = {player_slug(p.name) for p in data.players}
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

    # Collect extra names (team/pair-only, no individual data)
    _all_team_pair_names_pre: set[str] = set()
    for _entries in _all_team_raw.values():
        for _e in _entries:
            for _slot in _e["podium"]:
                for _m in _slot["members"]:
                    _all_team_pair_names_pre.add(_m)
    for _entries in _all_pair_raw.values():
        for _e in _entries:
            for _slot in _e["podium"]:
                for _p in _slot["players"]:
                    _all_team_pair_names_pre.add(_p)
    _indiv_slugs = {player_slug(p.name) for p in data.players}
    _extra_names = sorted(
        {n for n in _all_team_pair_names_pre if player_slug(n) not in _indiv_slugs},
        key=lambda n: n.lower()
    )

    player_options = [
        {"name": pl.name, "slug": player_slug(pl.name)}
        for pl in players_sorted
    ] + [
        {"name": n, "slug": player_slug(n)} for n in _extra_names
    ]
    player_options.sort(key=lambda o: o["name"].lower())
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
        "edp_by_year": edp_by_year,
        "team_medals_all": team_medals_all,
        "team_medals_edp": team_medals_edp,
        "team_medals_live": team_medals_live,
        "team_medals_by_series": team_medals_by_series,
        "live_team_series": live_team_series,
        "all_team_raw": _all_team_raw,
        "live_team_codes": _live_team_codes,
        "medals_combined": medals_combined,
        "php_by_year": php_by_year,
        "pair_medals_all": pair_medals_all,
        "pair_medals_php": pair_medals_php,
        "pair_medals_live": pair_medals_live,
        "pair_medals_by_series": pair_medals_by_series,
        "live_pair_series": live_pair_series,
        "all_pair_raw": _all_pair_raw,
        "live_pair_codes": _live_pair_codes,
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
        edp_medals  = _team_player_medals.get(_pmk(p.name), [])
        pair_medals = _pair_player_medals.get(_pmk(p.name), [])
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
            "edp_medals": edp_medals,
            "pair_medals": pair_medals,
            "known_slugs": known_slugs,
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

    # ── Team/pair-only player pages ──
    _seen_extra: set[str] = set()
    for _name in _extra_names:
        _slug = player_slug(_name)
        if _slug in _indiv_slugs or _slug in _seen_extra:
            continue
        _seen_extra.add(_slug)
        _mk = _pmk(_name)
        _tm = _team_player_medals.get(_mk, [])
        _pm = _pair_player_medals.get(_mk, [])
        write_page(f"players/{_slug}", "player.html", {
            "title": _name,
            "player": SimpleNamespace(name=_name),
            "current_slug": _slug,
            "player_options": player_options,
            "podium": [],
            "podium_hks": [],
            "podium_live": [],
            "edp_medals": _tm,
            "pair_medals": _pm,
            "known_slugs": known_slugs | _seen_extra,
            "history": [],
            "g": 0, "s": 0, "b": 0,
            "blurb_for_key": blurb_for_key,
            "chart_labels_js": Markup("[]"),
            "chart_ranks_js": Markup("[]"),
            "chart_max": 1,
            "has_chart": False,
            "tl_years": [],
            "series": SERIES,
            "tl_live": {},
            "tl_hks": {},
            "tl_defunct": {},
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
    # Team-only event years per series (not in individual data), for events page links
    _team_only_by_series: dict[str, list[dict]] = {}
    for _sc, _entries in _all_team_raw.items():
        if _sc == "edp":
            continue
        _keys = {t.key for t in data.tournaments}
        _extra = [e for e in _entries if f"{_sc}{e['year']}" not in _keys]
        if _extra:
            _team_only_by_series[_sc] = sorted(_extra, key=lambda e: e["year"], reverse=True)

    write_page("events", "tournaments.html", {
        "title": "Events",
        "category_groups": category_groups,
        "edp_by_year": edp_by_year,
        "php_by_year": php_by_year,
        "team_only_by_series": _team_only_by_series,
        "blurb_for_key": blurb_for_key,
    })

    # ── EDP year detail pages ──
    for entry in edp_raw:
        write_page(f"events/edp{entry['year']}", "edp_event.html", {
            "title": f"EDP {entry['year']}",
            "year": entry["year"],
            "podium": entry["podium"],
        })

    # ── PHP year detail pages ──
    for entry in php_raw:
        write_page(f"events/php{entry['year']}", "php_event.html", {
            "title": f"PHP {entry['year']}",
            "year": entry["year"],
            "podium": entry["podium"],
        })

    # Build lookup: (series_code, year) → team/pair podium entry
    _team_by_event: dict[tuple[str, int], dict] = {}
    for _sc, _entries in _all_team_raw.items():
        if _sc == "edp":
            continue
        for _e in _entries:
            _team_by_event[(_sc, _e["year"])] = _e

    _pair_by_event: dict[tuple[str, int], dict] = {}
    for _sc, _entries in _all_pair_raw.items():
        if _sc == "php":
            continue
        for _e in _entries:
            _pair_by_event[(_sc, _e["year"])] = _e

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
        series_obj = SERIES_BY_CODE.get(sc)
        is_score_only = series_obj is not None and series_obj.category == "hks"
        is_live_event = series_obj is not None and series_obj.category == "live"
        # Team results for this specific event year (if available)
        _year_match = re.search(r"(\d{4})", t.key)
        _event_year = int(_year_match.group(1)) if _year_match else None
        team_entry = _team_by_event.get((sc, _event_year)) if _event_year else None
        pair_entry = _pair_by_event.get((sc, _event_year)) if _event_year else None
        write_page(f"events/{t.key}", "tournament.html", {
            "title": t.label,
            "t": t,
            "rows": rows,
            "has_sheet": has_sheet,
            "podium": podium,
            "finalist_count": finalist_count,
            "placement_only": placement_only,
            "is_score_only": is_score_only,
            "is_live_event": is_live_event,
            "blurb_for_key": blurb_for_key,
            "team_entry": team_entry,
            "pair_entry": pair_entry,
            "team_only": False,
        })

    # ── Team-only event pages (no individual data) ──
    _tournament_keys = {t.key for t in data.tournaments}
    for _sc, _entries in _all_team_raw.items():
        if _sc == "edp":
            continue
        _series_obj = SERIES_BY_CODE.get(_sc)
        if not _series_obj:
            continue
        for _entry in _entries:
            _ekey = f"{_sc}{_entry['year']}"
            if _ekey in _tournament_keys:
                continue
            _label = _entry.get("label") or f"{_series_obj.name} {_entry['year']}"
            _t = SimpleNamespace(label=_label, key=_ekey)
            write_page(f"events/{_ekey}", "tournament.html", {
                "title": _label,
                "t": _t,
                "rows": [],
                "has_sheet": False,
                "podium": [],
                "finalist_count": 0,
                "placement_only": False,
                "is_score_only": False,
                "is_live_event": True,
                "blurb_for_key": blurb_for_key,
                "team_entry": _entry,
                "pair_entry": None,
                "team_only": True,
            })

    print(f"Built {pages} pages → {OUT.relative_to(BASE)}/")


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else ""
    build(base)
