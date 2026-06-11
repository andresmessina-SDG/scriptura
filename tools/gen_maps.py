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
# Hypsometric relief: elevation bands as successively deeper paper tones
# (subtle — texture, not topo-map). Thresholds in metres; the Anatolian
# plateau (~1000 m) and the Taurus range carry the story of the hard
# climb inland from Perga.
RELIEF_BANDS = [(400, '#f2ece0'), (1000, '#ece4d3'), (1800, '#e4dac6')]

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
# Road-corridor waypoints (unlabeled). The Via Sebaste (the Roman highway
# of 6 BC that Acts scholarship puts Paul on) climbed from Perga through
# the Taurus and threaded the Pisidian lake corridor — between Lake Burdur
# and Lake Eğirdir — to Pisidian Antioch (via Comama and Apollonia). On
# Cyprus, "through the whole island" (Acts 13:6) followed the south-coast
# Roman road: Kition, Amathus, Kourion.
WAYPOINTS = {
    'Via Sebaste S': (30.48, 37.34),   # near Comama
    'Via Sebaste N': (30.46, 38.07),   # near Apollonia
    # The road rounded the NORTH shore of Lake Eğirdir's Hoyran arm —
    # placed from the drawn lake's own north tip (30.86, 38.28), so the
    # route can never clip the water it skirts.
    'Hoyran N': (30.87, 38.34),
    'Kition':  (33.63, 34.92),
    'Amathus': (33.14, 34.71),
    'Kourion': (32.87, 34.66),
}

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
RETRACED = {('Perga', 'Via Sebaste S'), ('Via Sebaste S', 'Via Sebaste N'),
            ('Via Sebaste N', 'Hoyran N'), ('Hoyran N', 'Antioch in Pisidia'),
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
    # Cyprus south-coast road; one arrow mid-island
    ('Salamis', 'Kition', 'land', 0, False),
    ('Kition', 'Amathus', 'land', 0, True),
    ('Amathus', 'Kourion', 'land', 0, False),
    ('Kourion', 'Paphos', 'land', 0, False),
    ('Paphos', 'Perga', 'sea', 0.08, True),
    # Via Sebaste climb through the lake corridor; arrows on the long
    # first segment only (the pair logic uses each row's own flag)
    ('Perga', 'Via Sebaste S', 'land', 0, True),
    ('Via Sebaste S', 'Via Sebaste N', 'land', 0, False),
    ('Via Sebaste N', 'Hoyran N', 'land', 0, False),
    ('Hoyran N', 'Antioch in Pisidia', 'land', 0, False),
    ('Antioch in Pisidia', 'Iconium', 'land', 0, True),
    ('Iconium', 'Lystra', 'land', 0, True),
    ('Lystra', 'Derbe', 'land', 0, True),
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


# ── Hypsometric relief (Mapzen terrarium DEM → marching squares) ─────────────
# Elevation from the public-domain terrarium tiles on AWS
# (s3.amazonaws.com/elevation-tiles-prod), decoded with PIL, resampled to a
# regular lon/lat grid over the bbox, then contoured per RELIEF_BANDS with
# marching squares (interpolated edges, segments chained into closed rings).
# Grid borders are forced below every threshold so rings always close.

def load_elevation_grid(tile_dir, bbox, nx=420, ny=320, z=7):
    from PIL import Image
    lon0, lat0, lon1, lat1 = bbox

    def txf(lon):
        return (lon + 180) / 360 * (1 << z)

    def tyf(lat):
        r = math.radians(lat)
        return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) \
            / 2 * (1 << z)

    tiles = {}

    def elev(lon, lat):
        fx, fy = txf(lon), tyf(lat)
        tx, ty = int(fx), int(fy)
        if (tx, ty) not in tiles:
            path = os.path.join(tile_dir, f'{z}_{tx}_{ty}.png')
            tiles[(tx, ty)] = (Image.open(path).convert('RGB').load()
                               if os.path.exists(path) else None)
        px = tiles[(tx, ty)]
        if px is None:
            return -1000.0
        r, g, b = px[min(255, int((fx - tx) * 256)),
                     min(255, int((fy - ty) * 256))]
        return (r * 256 + g + b / 256) - 32768

    grid = []
    for j in range(ny):
        lat = lat1 - (lat1 - lat0) * j / (ny - 1)
        row = [elev(lon0 + (lon1 - lon0) * i / (nx - 1), lat)
               for i in range(nx)]
        grid.append(row)
    # Smooth before contouring: raw 1-km cells contour into speckled
    # camo patches; two 3x3 box-blur passes yield coherent ranges
    # (relief here is texture, not survey data).
    for _ in range(2):
        prev = [row[:] for row in grid]
        for j in range(1, ny - 1):
            for i in range(1, nx - 1):
                grid[j][i] = (
                    prev[j-1][i-1] + prev[j-1][i] + prev[j-1][i+1] +
                    prev[j][i-1] + prev[j][i] + prev[j][i+1] +
                    prev[j+1][i-1] + prev[j+1][i] + prev[j+1][i+1]) / 9.0
    # closed-ring guarantee: borders below any threshold
    for i in range(nx):
        grid[0][i] = grid[ny - 1][i] = -10000.0
    for j in range(ny):
        grid[j][0] = grid[j][nx - 1] = -10000.0
    return grid


def marching_squares(grid, threshold):
    """Closed contour rings (grid coordinates) for grid >= threshold."""
    ny, nx = len(grid), len(grid[0])
    segs = {}   # start -> (end) with rounded keys

    def interp(va, vb, a, b):
        t = (threshold - va) / (vb - va)
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def key(p):
        return (round(p[0], 3), round(p[1], 3))

    for j in range(ny - 1):
        for i in range(nx - 1):
            tl, tr = grid[j][i], grid[j][i + 1]
            bl, br = grid[j + 1][i], grid[j + 1][i + 1]
            case = ((tl >= threshold) | (tr >= threshold) << 1 |
                    (br >= threshold) << 2 | (bl >= threshold) << 3)
            if case in (0, 15):
                continue
            # edge midpoints (interpolated): top/right/bottom/left
            T = interp(tl, tr, (i, j), (i + 1, j)) if (tl >= threshold) != (tr >= threshold) else None
            R = interp(tr, br, (i + 1, j), (i + 1, j + 1)) if (tr >= threshold) != (br >= threshold) else None
            B = interp(bl, br, (i, j + 1), (i + 1, j + 1)) if (bl >= threshold) != (br >= threshold) else None
            L = interp(tl, bl, (i, j), (i, j + 1)) if (tl >= threshold) != (bl >= threshold) else None
            # segments oriented with the >=threshold side on the LEFT
            table = {
                1: [(L, T)], 2: [(T, R)], 3: [(L, R)], 4: [(R, B)],
                5: [(L, T), (R, B)], 6: [(T, B)], 7: [(L, B)],
                8: [(B, L)], 9: [(B, T)], 10: [(T, L), (B, R)],
                11: [(B, R)], 12: [(R, L)], 13: [(R, T)], 14: [(T, L)],
            }
            for a, b in table[case]:
                if a and b:
                    segs[key(a)] = (a, b)

    rings = []
    while segs:
        start_key, (a, b) = next(iter(segs.items()))
        del segs[start_key]
        ring = [a, b]
        while True:
            nxt = segs.pop(key(ring[-1]), None)
            if nxt is None:
                break
            ring.append(nxt[1])
            if key(nxt[1]) == start_key:
                break
        if len(ring) > 3:
            rings.append(ring)
    return rings


def relief_paths(tile_dir, bbox, proj):
    out = []
    grid = load_elevation_grid(tile_dir, bbox)
    ny, nx = len(grid), len(grid[0])
    lon0, lat0, lon1, lat1 = bbox

    def to_lonlat(p):
        return (lon0 + (lon1 - lon0) * p[0] / (nx - 1),
                lat1 - (lat1 - lat0) * p[1] / (ny - 1))

    for threshold, color in RELIEF_BANDS:
        d_parts = []
        for ring in marching_squares(grid, threshold):
            pts = [proj(*to_lonlat(p)) for p in ring]
            # drop speckle rings and thin the rest — relief is texture,
            # not survey data; halves the SVG without visible change
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            if (max(xs) - min(xs)) * (max(ys) - min(ys)) < 300:
                continue
            pts = pts[::2] if len(pts) > 24 else pts
            d_parts.append('M' + ' L'.join(f'{x:.0f},{y:.0f}'
                                           for x, y in pts) + ' Z')
        if d_parts:
            out.append(f'<path d="{" ".join(d_parts)}" fill="{color}" '
                       f'fill-rule="evenodd"/>')
    return out


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


def arrow_marker(pts, size=9.0, frac=0.5):
    """A direction arrowhead along a sampled run (frac of its length),
    aligned with travel."""
    m = max(1, min(len(pts) - 2, int(len(pts) * frac)))
    x, y = pts[m]
    tx, ty = pts[m + 1][0] - pts[m - 1][0], pts[m + 1][1] - pts[m - 1][1]
    ang = math.degrees(math.atan2(ty, tx))
    return (f'<path d="M{size:.0f},0 L-{size*0.45:.1f},{size*0.55:.1f} '
            f'L-{size*0.45:.1f},-{size*0.55:.1f} Z" fill="{ROUTE}" '
            f'transform="translate({x:.1f},{y:.1f}) rotate({ang:.1f})"/>')


def build(data_dir, out_path, return_variant=True):
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
    # Hypsometric relief — texture for the interior, and the Taurus story
    svg.extend(relief_paths(os.path.join(data_dir, 'terrarium'), BBOX, proj))
    svg.extend(river_paths)
    lake_svg, lake_rings = land_paths('ne_10m_lakes.geojson', LAKE, COAST,
                                      '1.0')
    svg.extend(lake_svg)

    def warn_if_wet(pts, what):
        wet = sum(1 for pt in pts if point_in_rings(pt, lake_rings))
        if wet > 1:
            print(f'  ! land route {what} crosses a lake '
                  f'({wet} samples) — add a shore waypoint')

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

    def draw_land(p, q, bow, arrow, frac=0.5):
        c = bowed(p, q, bow) if bow else ((p[0]+q[0])/2, (p[1]+q[1])/2)
        if bow:
            d = (f'M{p[0]:.1f},{p[1]:.1f} Q{c[0]:.1f},{c[1]:.1f} '
                 f'{q[0]:.1f},{q[1]:.1f}')
        else:
            d = f'M{p[0]:.1f},{p[1]:.1f} L{q[0]:.1f},{q[1]:.1f}'
        svg.append(f'<path d="{d}" fill="none" stroke="{ROUTE}" '
                   f'stroke-width="{ROUTE_W}" stroke-linecap="round" '
                   f'opacity="0.9"/>')
        warn_if_wet(sample_quad(p, c, q), 'leg')
        if arrow:
            arrows.append(arrow_marker(sample_quad(p, c, q), frac=frac))

    def offset_polyline(pts, d):
        """Offset a polyline by d (left of travel) with mitered joints —
        per-segment offsetting notches at every bend; the miter keeps the
        two parallels continuous through corners."""
        out = []
        n = len(pts)
        for i in range(n):
            if i == 0:
                dirs = [(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])]
            elif i == n - 1:
                dirs = [(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])]
            else:
                dirs = [(pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1]),
                        (pts[i+1][0] - pts[i][0], pts[i+1][1] - pts[i][1])]
            normals = []
            for dx, dy in dirs:
                ln = math.hypot(dx, dy) or 1.0
                normals.append((-dy / ln, dx / ln))
            mx = sum(nv[0] for nv in normals) / len(normals)
            my = sum(nv[1] for nv in normals) / len(normals)
            ln = math.hypot(mx, my) or 1.0
            # miter scale = 1/cos(half-angle); cap for near-hairpins
            scale = min(1.0 / max(ln, 0.25), 3.0)
            out.append((pts[i][0] + mx / ln * d * ln * scale,
                        pts[i][1] + my / ln * d * ln * scale))
        return out

    def densify(pts, step=4.0):
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            ln = math.hypot(b[0] - a[0], b[1] - a[1])
            for k in range(1, max(2, int(ln / step)) + 1):
                t = k / max(2, int(ln / step))
                out.append((a[0] + (b[0] - a[0]) * t,
                            a[1] + (b[1] - a[1]) * t))
        return out

    def draw_chain_pair(chain_pts):
        """A retraced road as one continuous mitered parallel pair, with
        two staggered arrowheads per direction along the whole chain."""
        # fracs interleave when mapped onto the shared road: forward at
        # 20%/60%, reverse at 20%/60% of ITS direction = 80%/40% forward —
        # four arrowheads evenly spaced, never face to face
        for pts, fracs in ((offset_polyline(chain_pts, 3.4), (0.20, 0.60)),
                           (offset_polyline(chain_pts[::-1], 3.4),
                            (0.20, 0.60))):
            svg.append(f'<path d="{path_d(pts)}" fill="none" '
                       f'stroke="{ROUTE}" stroke-width="{ROUTE_W}" '
                       f'stroke-linecap="round" stroke-linejoin="round" '
                       f'opacity="0.9"/>')
            dense = densify(pts)
            warn_if_wet(dense, 'chain')
            for fr in fracs:
                arrows.append(arrow_marker(dense, frac=fr))

    # group consecutive retraced land legs into chains
    pending_chain = []

    def flush_chain():
        if pending_chain and return_variant:
            draw_chain_pair(pending_chain.copy())
        elif pending_chain:
            for a, b in zip(pending_chain, pending_chain[1:]):
                draw_land(a, b, 0, False)
        pending_chain.clear()

    for frm, to, kind, bow, arrow in LEGS:
        p, q = proj(*coords[frm]), proj(*coords[to])
        c = bowed(p, q, bow) if bow else ((p[0]+q[0])/2, (p[1]+q[1])/2)
        if kind == 'land':
            if (frm, to) in RETRACED:
                if pending_chain and pending_chain[-1] != p:
                    flush_chain()
                if not pending_chain:
                    pending_chain.append(p)
                pending_chain.append(q)
            else:
                flush_chain()
                draw_land(p, q, bow, arrow)
            continue
        flush_chain()
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
    flush_chain()
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
    ap.add_argument('--single-retrace', action='store_true',
                    help='draw retraced roads as single calm lines instead '
                         'of the default offset out/return pair')
    args = ap.parse_args()
    build(args.data_dir, args.out,
          return_variant=not args.single_retrace)


if __name__ == '__main__':
    main()
