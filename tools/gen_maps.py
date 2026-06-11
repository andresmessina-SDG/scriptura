#!/usr/bin/env python3
"""Generate Scriptura's modern SVG Bible maps from open geodata.

PROTOTYPE: Paul's first missionary journey (Acts 13-14). The geometry is
computed, never drawn: coastlines/lakes/rivers come from Natural Earth 10m
(public domain), place coordinates from OpenBible.info (CC BY 4.0); an
equirectangular projection with a mid-latitude standard parallel turns them
into SVG paths. The aesthetic layer is the small parameter block below —
palette, strokes, type — iterated against the app's house style.

Data files (downloaded once, cached in --data-dir):
  ne_10m_land.geojson, ne_10m_lakes.geojson,
  ne_10m_rivers_lake_centerlines.geojson
    from https://github.com/nvkelso/natural-earth-vector (PD)
  ancient.jsonl
    from https://github.com/openbibleinfo/Bible-Geocoding-Data (CC BY 4.0)

Usage: gen_maps.py [--data-dir /tmp/mapdata] [--out maps/]
"""

import argparse
import json
import math
import os

# ── Style tokens (the entire aesthetic surface) ──────────────────────────────
SEA = '#dce8f0'          # quiet blue-gray wash
LAND = '#f7f4ed'         # warm paper
COAST = '#b7c6d0'        # coastline hairline
LAKE = '#cfe0ea'
RIVER = '#c2d6e2'
ROUTE = '#c5443c'        # journey red — the one saturated voice on the map
ROUTE_W = 3.0
DOT = '#3a3a3a'
DOT_R = 4.4
LABEL = '#33373b'
LABEL_HALO = '#ffffff'
SEA_LABEL = '#6e8da3'
REGION_LABEL = '#8f8875'
TITLE = '#33373b'
SUBTITLE = '#74797f'
FONT = 'Adwaita Sans, Inter, sans-serif'
FRAME = '#c9c4ba'

# ── The map definition (editorial content) ──────────────────────────────────
BBOX = (29.6, 33.9, 37.8, 39.3)   # lon_min, lat_min, lon_max, lat_max
WIDTH = 1400

PLACES = {                          # lon, lat (OpenBible.info, CC BY)
    'Antioch (Syria)':    (36.171743, 36.226691),
    'Seleucia':           (35.922000, 36.124000),
    'Salamis':            (33.901944, 35.184944),
    'Paphos':             (32.404167, 34.755667),
    'Perga':              (30.853686, 36.960353),
    'Attalia':            (30.703614, 36.881272),
    'Antioch in Pisidia': (31.189167, 38.306111),
    'Iconium':            (32.492331, 37.872202),
    'Lystra':             (32.338400, 37.601700),
    'Derbe':              (33.361453, 37.348569),
}

# Unlabeled route vertices (no dot, no label) for legs that need a shaping
# point. None currently: Paphos→Perga stays a *water* leg the whole way —
# Acts 13:13 says they "sailed to Perga"; the Cestrus was navigable and
# ships went upriver to the city, so dashes ending at inland Perga are the
# accurate reading (a coastal waypoint + road stub was tried and looked
# like a rendering error at zoom).
WAYPOINTS = {}

# Context cities — gray, no route: anchor the journey in the known NT
# world (reference-map study, 2026-06-12). Tarsus is Paul's hometown
# (Acts 9:11), Myra a later voyage stop (Acts 27:5).
CONTEXT_PLACES = {
    'Tarsus': (34.892056, 36.913028),
    'Myra':   (29.985278, 36.259167),
}
CONTEXT_LABEL_POS = {
    'Tarsus': (10, -6, 'start'),
    'Myra':   (10, -8, 'start'),
}

# The journey's origin gets a quiet ring around its dot (the reference
# maps mark it with a star; a ring is the house-calm version).
ORIGIN = 'Antioch (Syria)'

# Land legs the return retraced (Acts 14:21) — drawn as offset parallel
# pairs with per-direction arrows in the 'return' variant, single calm
# lines otherwise.
RETRACED = {('Perga', 'Antioch in Pisidia'),
            ('Antioch in Pisidia', 'Iconium'),
            ('Iconium', 'Lystra'), ('Lystra', 'Derbe')}

# Route legs: (from, to, kind, bow, arrow). Sea legs render dashed with a
# gentle bow (bow > 0 bends left of travel); arrow=True draws a direction
# arrowhead at the leg's midpoint. The return retraces the outbound roads
# (Acts 14:21), so retraced land legs are drawn once (no arrow — direction
# is both ways); the arrows on the sea legs carry the loop's story.
# Salamis→Paphos is LAND: Acts 13:6, "through the whole island".
LEGS = [
    ('Antioch (Syria)', 'Seleucia', 'land', 0, False),
    ('Seleucia', 'Salamis', 'sea', 0.18, True),
    ('Salamis', 'Paphos', 'land', 0.06, True),
    ('Paphos', 'Perga', 'sea', 0.08, True),
    ('Perga', 'Antioch in Pisidia', 'land', 0, False),
    ('Antioch in Pisidia', 'Iconium', 'land', 0, False),
    ('Iconium', 'Lystra', 'land', 0, False),
    ('Lystra', 'Derbe', 'land', 0, False),
    ('Perga', 'Attalia', 'land', 0, False),
    # Homebound sail ends at Seleucia, the port — the final hop to
    # Antioch reuses the already-drawn road (no doubled line).
    ('Attalia', 'Seleucia', 'sea', -0.34, True),
]

# Label placement: anchor + pixel nudge per place (the hand-tuned part).
LABEL_POS = {                       # (dx, dy, text-anchor)
    'Antioch (Syria)':    (10, 4, 'start'),
    'Seleucia':           (-6, -10, 'end'),
    'Salamis':            (8, -8, 'start'),
    'Paphos':             (-10, 4, 'end'),
    'Perga':              (11, -6, 'start'),
    'Attalia':            (-10, 14, 'end'),
    'Antioch in Pisidia': (10, -8, 'start'),
    'Iconium':            (12, -4, 'start'),
    'Lystra':             (-11, 8, 'end'),
    'Derbe':              (10, 14, 'start'),
}

SEA_LABELS = [('Mediterranean Sea', 33.0, 34.45, 0)]
# Region labels follow the passage's own geography: Acts 14:6 names
# Lycaonia (Lystra & Derbe); Pisidia is the lake district *south* of
# Pisidian Antioch (the first draft's position was in Phrygia). The
# rotation (degrees) lets a name follow its land's sweep, like the
# classic atlas charts (reference-map study).
REGION_LABELS = [('CYPRUS', 33.2, 35.05, -8), ('PISIDIA', 30.45, 37.72, 0),
                 ('LYCAONIA', 33.45, 37.95, 0),
                 ('PAMPHYLIA', 31.7, 36.8, -6), ('GALATIA', 33.0, 38.6, 0),
                 ('CILICIA', 34.9, 37.05, -10), ('SYRIA', 36.9, 35.7, 55)]

TITLE_TEXT = "PAUL'S FIRST MISSIONARY JOURNEY"
SUBTITLE_TEXT = 'Acts 13–14 · c. AD 46–48'


# ── Projection ───────────────────────────────────────────────────────────────

def make_projection(bbox, width):
    lon0, lat0, lon1, lat1 = bbox
    lat_mid = math.radians((lat0 + lat1) / 2)
    px_lon = width / (lon1 - lon0)
    px_lat = px_lon / math.cos(lat_mid)
    height = (lat1 - lat0) * px_lat

    def proj(lon, lat):
        return ((lon - lon0) * px_lon, (lat1 - lat) * px_lat)
    return proj, height


# ── Geometry: Sutherland–Hodgman polygon clip + line clip to bbox ────────────

def clip_polygon(ring, bbox):
    lon0, lat0, lon1, lat1 = bbox
    def clip_edge(pts, inside, intersect):
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            cin, pin = inside(cur), inside(prev)
            if cin:
                if not pin:
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif pin:
                out.append(intersect(prev, cur))
        return out
    def x_at(p, q, x):
        t = (x - p[0]) / (q[0] - p[0])
        return (x, p[1] + t * (q[1] - p[1]))
    def y_at(p, q, y):
        t = (y - p[1]) / (q[1] - p[1])
        return (p[0] + t * (q[0] - p[0]), y)
    pts = ring
    for inside, intersect in (
            (lambda p: p[0] >= lon0, lambda p, q: x_at(p, q, lon0)),
            (lambda p: p[0] <= lon1, lambda p, q: x_at(p, q, lon1)),
            (lambda p: p[1] >= lat0, lambda p, q: y_at(p, q, lat0)),
            (lambda p: p[1] <= lat1, lambda p, q: y_at(p, q, lat1))):
        pts = clip_edge(pts, inside, intersect)
        if not pts:
            return []
    return pts


def clip_line(points, bbox):
    """Split a line into runs of points inside the (slightly padded) bbox."""
    lon0, lat0, lon1, lat1 = bbox
    pad = 0.05
    runs, cur = [], []
    for p in points:
        if lon0 - pad <= p[0] <= lon1 + pad and lat0 - pad <= p[1] <= lat1 + pad:
            cur.append(p)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


# ── SVG emission ─────────────────────────────────────────────────────────────

def path_d(points, close=False):
    d = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in points)
    return d + (' Z' if close else '')


def geojson_rings(feature):
    g = feature['geometry']
    if g['type'] == 'Polygon':
        yield from g['coordinates']
    elif g['type'] == 'MultiPolygon':
        for poly in g['coordinates']:
            yield from poly


def geojson_lines(feature):
    g = feature['geometry']
    if g['type'] == 'LineString':
        yield g['coordinates']
    elif g['type'] == 'MultiLineString':
        yield from g['coordinates']


def bowed(p, q, bow):
    """Quadratic control point: perpendicular offset at the midpoint,
    `bow` as a fraction of the leg length. Positive bends left of travel."""
    mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    dx, dy = q[0] - p[0], q[1] - p[1]
    return (mx + dy * bow, my - dx * bow)


def sample_quad(p, c, q, n=240):
    """Sample the quadratic (p, c, q) as n+1 points."""
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append((u*u*p[0] + 2*u*t*c[0] + t*t*q[0],
                    u*u*p[1] + 2*u*t*c[1] + t*t*q[1]))
    return pts


def point_in_rings(pt, rings):
    """Ray-casting point-in-polygon across disjoint rings (projected px)."""
    x, y = pt
    inside = False
    for ring in rings:
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > y) != (yj > y) and \
                    x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


def arrow_marker(pts, size=9.0):
    """A direction arrowhead at the midpoint of a sampled run, aligned
    with travel."""
    m = len(pts) // 2
    x, y = pts[m]
    tx, ty = pts[m + 1][0] - pts[m - 1][0], pts[m + 1][1] - pts[m - 1][1]
    ang = math.degrees(math.atan2(ty, tx))
    return (f'<path d="M{size:.0f},0 L-{size*0.45:.1f},{size*0.55:.1f} '
            f'L-{size*0.45:.1f},-{size*0.55:.1f} Z" fill="{ROUTE}" '
            f'transform="translate({x:.1f},{y:.1f}) rotate({ang:.1f})"/>')


def build(data_dir, out_path, return_variant=False):
    proj, height = make_projection(BBOX, WIDTH)
    pad_top = 96          # title block
    H = int(height) + pad_top + 24

    def land_paths(name, fill, stroke, stroke_w):
        out = []
        rings = []
        with open(os.path.join(data_dir, name)) as f:
            data = json.load(f)
        for feat in data['features']:
            for ring in geojson_rings(feat):
                clipped = clip_polygon(ring, BBOX)
                if len(clipped) >= 3:
                    pts = [proj(*p) for p in clipped]
                    rings.append(pts)
                    out.append(f'<path d="{path_d(pts, close=True)}" '
                               f'fill="{fill}" stroke="{stroke}" '
                               f'stroke-width="{stroke_w}" '
                               f'stroke-linejoin="round"/>')
        return out, rings

    river_paths = []
    with open(os.path.join(data_dir, 'ne_10m_rivers_lake_centerlines.geojson')) as f:
        rivers = json.load(f)
    for feat in rivers['features']:
        for line in geojson_lines(feat):
            for run in clip_line(line, BBOX):
                if len(run) >= 2:
                    pts = [proj(*p) for p in run]
                    river_paths.append(
                        f'<path d="{path_d(pts)}" fill="none" '
                        f'stroke="{RIVER}" stroke-width="1.1" '
                        f'stroke-linecap="round"/>')

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" '
               f'width="{WIDTH}" height="{H}" '
               f'viewBox="0 0 {WIDTH} {H}" font-family="{FONT}">')
    svg.append(f'<rect width="{WIDTH}" height="{H}" fill="#ffffff"/>')
    # Title block
    svg.append(f'<text x="{WIDTH/2}" y="44" text-anchor="middle" '
               f'fill="{TITLE}" font-size="26" font-weight="700" '
               f'letter-spacing="3">{TITLE_TEXT}</text>')
    svg.append(f'<text x="{WIDTH/2}" y="72" text-anchor="middle" '
               f'fill="{SUBTITLE}" font-size="16" '
               f'letter-spacing="1">{SUBTITLE_TEXT}</text>')

    svg.append(f'<g transform="translate(0,{pad_top})">')
    svg.append(f'<clipPath id="frame"><rect x="0" y="0" width="{WIDTH}" '
               f'height="{height:.0f}" rx="10"/></clipPath>')
    svg.append('<g clip-path="url(#frame)">')
    svg.append(f'<rect width="{WIDTH}" height="{height:.0f}" fill="{SEA}"/>')
    land_svg, land_rings = land_paths('ne_10m_land.geojson', LAND, COAST, '1.4')
    svg.extend(land_svg)
    svg.extend(river_paths)
    lake_svg, _ = land_paths('ne_10m_lakes.geojson', LAKE, COAST, '1.0')
    svg.extend(lake_svg)

    # Whisper-faint 1° graticule — gives the empty interior a cartographic
    # texture without competing with anything (see the methodology doc's
    # "empty-interior problem"; hypsometric relief is the open follow-up).
    lon0, lat0, lon1, lat1 = BBOX
    for lon in range(math.ceil(lon0), math.floor(lon1) + 1):
        a, b = proj(lon, lat0), proj(lon, lat1)
        svg.append(f'<line x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" '
                   f'y2="{b[1]:.0f}" stroke="#8aa0b0" stroke-width="0.5" '
                   f'opacity="0.13"/>')
    for lat in range(math.ceil(lat0), math.floor(lat1) + 1):
        a, b = proj(lon0, lat), proj(lon1, lat)
        svg.append(f'<line x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" '
                   f'y2="{b[1]:.0f}" stroke="#8aa0b0" stroke-width="0.5" '
                   f'opacity="0.13"/>')

    # Region + sea labels (under the route); rotation follows the land
    for text, lon, lat, rot in REGION_LABELS:
        x, y = proj(lon, lat)
        xf = (f' transform="rotate({rot} {x:.0f} {y:.0f})"' if rot else '')
        svg.append(f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="middle" '
                   f'fill="{REGION_LABEL}" font-size="16" '
                   f'letter-spacing="4"{xf}>{text}</text>')
    for text, lon, lat, rot in SEA_LABELS:
        x, y = proj(lon, lat)
        svg.append(f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="middle" '
                   f'fill="{SEA_LABEL}" font-size="17" font-style="italic" '
                   f'letter-spacing="3" '
                   f'transform="rotate({rot} {x:.0f} {y:.0f})">{text}</text>')

    # ── Route — terrain-aware: sea legs are sampled and tested against the
    # very land polygons the map draws, so dashes are *only ever painted on
    # water*. A land run at the leg's start is the harbor departure (left
    # as a gap); a land run at the leg's end is an inland river/road
    # arrival (ships sailed up the Cestrus to Perga; travellers walked from
    # Seleucia's docks up to Antioch) and renders as a solid land leg from
    # the exact coast crossing. A land run in the middle means the bow
    # crosses an island/isthmus — a route bug, so it warns.
    coords = dict(PLACES)
    coords.update(WAYPOINTS)
    arrows = []

    def draw_land(p, q, bow, arrow):
        c = bowed(p, q, bow) if bow else ((p[0]+q[0])/2, (p[1]+q[1])/2)
        if bow:
            d = (f'M{p[0]:.1f},{p[1]:.1f} Q{c[0]:.1f},{c[1]:.1f} '
                 f'{q[0]:.1f},{q[1]:.1f}')
        else:
            d = f'M{p[0]:.1f},{p[1]:.1f} L{q[0]:.1f},{q[1]:.1f}'
        svg.append(f'<path d="{d}" fill="none" stroke="{ROUTE}" '
                   f'stroke-width="{ROUTE_W}" stroke-linecap="round" '
                   f'opacity="0.9"/>')
        if arrow:
            arrows.append(arrow_marker(sample_quad(p, c, q)))

    def offset_pts(p, q, d):
        dx, dy = q[0] - p[0], q[1] - p[1]
        ln = math.hypot(dx, dy) or 1.0
        ox, oy = -dy / ln * d, dx / ln * d
        return (p[0] + ox, p[1] + oy), (q[0] + ox, q[1] + oy)

    for frm, to, kind, bow, arrow in LEGS:
        p, q = proj(*coords[frm]), proj(*coords[to])
        c = bowed(p, q, bow) if bow else ((p[0]+q[0])/2, (p[1]+q[1])/2)
        if kind == 'land':
            if return_variant and (frm, to) in RETRACED:
                # the retraced road as an offset pair, each direction
                # with its own arrowhead (reference-map treatment)
                po, qo = offset_pts(p, q, 3.4)
                pr, qr = offset_pts(q, p, 3.4)
                draw_land(po, qo, 0, True)
                draw_land(pr, qr, 0, True)
            else:
                draw_land(p, q, bow, arrow)
            continue
        # sea leg: split the sampled curve into water/land runs
        samples = sample_quad(p, c, q)
        runs = []          # [is_water, [pts]]
        for pt in samples:
            water = not point_in_rings(pt, land_rings)
            if runs and runs[-1][0] == water:
                runs[-1][1].append(pt)
            else:
                runs.append([water, [pt]])
        water_runs = [pts for w, pts in runs if w]
        for i, (water, pts) in enumerate(runs):
            if len(pts) < 2:
                continue
            if water:
                svg.append(f'<path d="{path_d(pts)}" fill="none" '
                           f'stroke="{ROUTE}" stroke-width="{ROUTE_W}" '
                           f'stroke-linecap="round" '
                           f'stroke-dasharray="2 9" opacity="0.9"/>')
            elif i == 0:
                pass        # harbor departure — leave the land bit as a gap
            elif i == len(runs) - 1:
                # micro arrival runs at coastal ports are just the dot's
                # own shoreline — drawing them leaves a stray fleck
                span = math.hypot(pts[-1][0] - pts[0][0],
                                  pts[-1][1] - pts[0][1])
                if span >= 6:
                    svg.append(f'<path d="{path_d(pts)}" fill="none" '
                               f'stroke="{ROUTE}" stroke-width="{ROUTE_W}" '
                               f'stroke-linecap="round" opacity="0.9"/>')
            else:
                print(f'  ! sea leg {frm}->{to} crosses land mid-route '
                      f'({len(pts)} samples) — adjust the bow')
        if arrow and water_runs:
            arrows.append(arrow_marker(max(water_runs, key=len)))
    svg.extend(arrows)   # arrowheads above all route lines

    # Context cities — muted, no route: orientation anchors only
    for name, (lon, lat) in CONTEXT_PLACES.items():
        x, y = proj(lon, lat)
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.0" '
                   f'fill="#8a8f8d" stroke="#ffffff" stroke-width="1.3"/>')
        dx, dy, anchor = CONTEXT_LABEL_POS.get(name, (8, -8, 'start'))
        svg.append(f'<text x="{x+dx:.0f}" y="{y+dy:.0f}" text-anchor="{anchor}" '
                   f'fill="#6b7075" font-size="15" '
                   f'paint-order="stroke" stroke="{LABEL_HALO}" '
                   f'stroke-width="3" stroke-linejoin="round">{name}</text>')

    # Places: dot + haloed label; the journey's origin gets a quiet ring
    for name, (lon, lat) in PLACES.items():
        x, y = proj(lon, lat)
        if name == ORIGIN:
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8.5" '
                       f'fill="none" stroke="{DOT}" stroke-width="1.3" '
                       f'opacity="0.7"/>')
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{DOT_R}" '
                   f'fill="{DOT}" stroke="#ffffff" stroke-width="1.6"/>')
        dx, dy, anchor = LABEL_POS.get(name, (8, -8, 'start'))
        svg.append(f'<text x="{x+dx:.0f}" y="{y+dy:.0f}" text-anchor="{anchor}" '
                   f'fill="{LABEL}" font-size="17" font-weight="600" '
                   f'paint-order="stroke" stroke="{LABEL_HALO}" '
                   f'stroke-width="3.5" stroke-linejoin="round">{name}</text>')

    # Scale bar — bottom-left; 100 km at the standard parallel
    lat_mid = math.radians((BBOX[1] + BBOX[3]) / 2)
    px_per_km = (WIDTH / (BBOX[2] - BBOX[0])) / (111.32 * math.cos(lat_mid))
    bar = 100 * px_per_km
    bx, by = 26, height - 26
    svg.append(f'<g stroke="#74797f" stroke-width="1.4">'
               f'<line x1="{bx}" y1="{by}" x2="{bx+bar:.0f}" y2="{by}"/>'
               f'<line x1="{bx}" y1="{by-4}" x2="{bx}" y2="{by+4}"/>'
               f'<line x1="{bx+bar:.0f}" y1="{by-4}" x2="{bx+bar:.0f}" '
               f'y2="{by+4}"/></g>')
    svg.append(f'<text x="{bx+bar/2:.0f}" y="{by-8}" text-anchor="middle" '
               f'fill="#74797f" font-size="12.5" paint-order="stroke" '
               f'stroke="#ffffff" stroke-width="3" '
               f'stroke-linejoin="round">100 km · 62 mi</text>')

    svg.append('</g>')   # clip
    svg.append(f'<rect x="0.5" y="0.5" width="{WIDTH-1}" '
               f'height="{height:.0f}" rx="10" fill="none" '
               f'stroke="{FRAME}" stroke-width="1"/>')
    svg.append('</g></svg>')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(svg))
    print(f'wrote {out_path} ({os.path.getsize(out_path)//1024} KB)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default='/tmp/mapdata')
    ap.add_argument('--out', default='/tmp/paul-journey-1.svg')
    ap.add_argument('--return-variant', action='store_true',
                    help='draw retraced roads as offset pairs with '
                         'per-direction arrows')
    args = ap.parse_args()
    build(args.data_dir, args.out, return_variant=args.return_variant)


if __name__ == '__main__':
    main()
