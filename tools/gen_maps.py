#!/usr/bin/env python3
"""Generate Scriptura's modern SVG Bible maps from open geodata.

Each map is one entry in the MAPS dict (Paul's journeys 1 and 2 so far).
The geometry is computed, never drawn: coastlines/lakes/rivers come from
Natural Earth 10m (public domain), place coordinates from OpenBible.info
(CC BY 4.0), hypsometric relief from Mapzen terrarium tiles (PD); an
equirectangular projection with a mid-latitude standard parallel turns them
into SVG paths. The aesthetic layer is the small style-token block below.

Routes are guaranteed against the terrain at build time — sea legs are
clipped so dashes fall only on water, land legs warned if they cross sea or
a lake, and every dot checked to clear the drawn coastline by its radius;
see CARTOGRAPHY_METHODOLOGY.md for the principles.

Data files (downloaded once, cached in --data-dir, default /tmp/mapdata):
  ne_10m_land.geojson, ne_10m_lakes.geojson,
  ne_10m_rivers_lake_centerlines.geojson,
  ne_10m_admin_0_boundary_lines_land.geojson  (--era modern only)
    from https://github.com/nvkelso/natural-earth-vector (PD)
  terrarium/{z}_{x}_{y}.png  elevation tiles
    from s3.amazonaws.com/elevation-tiles-prod/terrarium (PD)
  ancient.jsonl
    from https://github.com/openbibleinfo/Bible-Geocoding-Data (CC BY 4.0)

Usage: gen_maps.py [--map paul_journey_1] [--era ancient|modern]
                   [--no-title] [--single-retrace]
                   [--data-dir DIR] [--out FILE]
"""

import argparse
import json
import math
import os

# ── Style tokens (the entire aesthetic surface) ──────────────────────────────
SEA = '#b7d0e2'          # quiet blue-gray wash (deepened for land/sea contrast)
LAND = '#f7f4ed'         # warm paper
COAST = '#8fa8bd'        # coastline hairline (darkened to reinforce the edge)
LAKE = '#bcd4e4'         # inland water — sits in the sea's family, a hair lighter
RIVER = '#c2d6e2'
# Two route voices: the outbound stays the journey red (long the map's one
# saturated voice); the homeward leg takes a warm amber/ochre that reads on
# BOTH the paper land and the blue sea (the return is largely the voyage
# home). Drawing out and back in distinct hues deliberately reverses the old
# draw-once retrace (methodology lessons 3 & 5) — the two now run as an
# offset parallel pair, direction carried by hue as well as arrowheads.
ROUTE_OUT = '#c5443c'    # outbound — journey red
# Homeward — amber/ochre. Lightened from the first #c8862a so it carries a
# clear LIGHTNESS delta from the red (CIE L* 47 vs 68, ΔL*≈21), which is what
# keeps the two lanes separable under red-green colour-vision deficiency
# (deuteranopia/protanopia) — verified in simulation. Direction is also
# redundantly encoded (arrowheads + the offset pair), never colour-only.
ROUTE_RETURN = '#d99a2b'
ROUTE = ROUTE_OUT        # legacy alias (default colour for helpers)
ROUTE_SMOOTH = 0.16      # Catmull-Rom handle fraction for rounded land bends
ROUTE_W = 3.0
DOT = '#3a3a3a'
DOT_R = 4.4
LABEL = '#33373b'
LABEL_HALO = '#ffffff'
SEA_LABEL = '#557790'    # re-darkened to hold ~3:1 on the deeper sea (lesson 12)
REGION_LABEL = '#8f8875'
TITLE = '#33373b'
SUBTITLE = '#74797f'
FONT = 'Adwaita Sans, Inter, sans-serif'
# Water names take the house *serif italic* — the app's dual-voice type
# system (sans = structure, serif = the read/lyrical voice) mapped onto
# cartography's own convention of italic water labels.
SEA_FONT = "'Source Serif 4', Georgia, serif" 
FRAME = '#c9c4ba'
# Hypsometric relief: elevation bands as successively deeper paper tones
# (subtle — texture, not topo-map). Thresholds in metres; the Anatolian
# plateau (~1000 m) and the Taurus range carry the story of the hard
# climb inland from Perga.
RELIEF_BANDS = [(400, '#f2ece0'), (1000, '#ece4d3'), (1800, '#e4dac6')]
# Faint shaded relief from the same DEM (Imhof: tints carry altitude, the
# hillshade carries 3-D form). Classed slope shading, NW illumination: slopes
# turned away from the light get progressively darker grey overlays at low
# opacity. Texture, never a topo map — drawn UNDER the route so figure-ground
# holds. (shade-threshold, opacity); z_factor exaggerates the gentle slopes
# that survive at 10m/this grid so ranges actually read.
HILLSHADE = '#5e6253'         # desaturated warm-grey shadow (sits with paper)
HILLSHADE_BANDS = [(0.05, 0.05), (0.11, 0.05), (0.20, 0.06)]
HILLSHADE_ZF = 6.0

# ── Map definitions (editorial content) ─────────────────────────────────────
# Each map is one dict; build() consumes it. Geometry/coordinate sources:
# OpenBible.info (CC BY) for biblical places, Pleiades for road stations.
MAPS = {}

MAPS['paul_journey_1'] = dict(
    bbox=(29.6, 33.9, 37.8, 39.3),   # lon_min, lat_min, lon_max, lat_max
    width=1400,
    places={                          # lon, lat (OpenBible.info, CC BY)
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
    },
    # Unlabeled route vertices. Paphos->Perga stays a *water* leg the whole
    # way — Acts 13:13 "sailed to Perga"; the Cestrus was navigable.
    # Road corridors: the Via Sebaste (the Roman highway of 6 BC) climbed
    # from Perga through the Taurus and threaded the Pisidian lake corridor
    # — between Lake Burdur and Lake Egirdir — via Comama and Apollonia;
    # it rounded the NORTH shore of Lake Egirdir's Hoyran arm (waypoint
    # placed from the drawn lake's own north tip, 30.86/38.28). On Cyprus,
    # "through the whole island" (Acts 13:6) follows the south-coast road:
    # Kition, Amathus, Kourion.
    waypoints={
        'Via Sebaste S': (30.48, 37.34),   # near Comama
        'Via Sebaste N': (30.46, 38.07),   # near Apollonia
        'Hoyran N': (30.87, 38.34),
        # Nudged a few km inland of the actual coastal sites so the rounded
        # (smoothed) road holds the land instead of bulging past the convex
        # south cape into the sea — the methodology's shore-waypoint fix.
        'Kition':  (33.63, 34.95),
        'Amathus': (33.14, 34.77),
        'Kourion': (32.87, 34.73),
    },
    # Context cities — gray, no route: anchor the journey in the known NT
    # world. Tarsus is Paul's hometown (Acts 9:11), Myra a later voyage
    # stop (Acts 27:5).
    context_places={
        'Tarsus': (34.892056, 36.913028),
        'Myra':   (29.985278, 36.259167),
    },
    context_label_pos={
        'Tarsus': (10, -6, 'start'),
        'Myra':   (10, -8, 'start'),
    },
    origin='Antioch (Syria)',
    # Land legs the return retraced (Acts 14:21) — drawn as one offset
    # mitered parallel pair with per-direction arrows.
    retraced={('Perga', 'Via Sebaste S'), ('Via Sebaste S', 'Via Sebaste N'),
              ('Via Sebaste N', 'Hoyran N'),
              ('Hoyran N', 'Antioch in Pisidia'),
              ('Antioch in Pisidia', 'Iconium'),
              ('Iconium', 'Lystra'), ('Lystra', 'Derbe')},
    # Homeward from here: Perga down to Attalia and the sail back to Seleucia
    # (Acts 14:25-26) — drawn in the return hue.
    return_from=('Perga', 'Attalia'),
    # (from, to, kind, bow, arrow). Sea legs render dashed with a gentle
    # bow (bow > 0 bends left of travel). Salamis->Paphos is LAND:
    # Acts 13:6, "through the whole island".
    legs=[
        ('Antioch (Syria)', 'Seleucia', 'land', 0, False),
        ('Seleucia', 'Salamis', 'sea', 0.18, True),
        ('Salamis', 'Kition', 'land', 0, False),
        ('Kition', 'Amathus', 'land', 0, True),
        ('Amathus', 'Kourion', 'land', 0, False),
        ('Kourion', 'Paphos', 'land', 0, False),
        ('Paphos', 'Perga', 'sea', 0.08, True),
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
    ],
    label_pos={                       # (dx, dy, text-anchor)
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
    },
    sea_labels=[('Mediterranean Sea', 33.0, 34.45, 0)],
    # Region labels follow the passage's own geography (Acts 14:6 names
    # Lycaonia); rotation follows the land's sweep.
    region_labels=[('CYPRUS', 33.2, 35.05, -8), ('PISIDIA', 30.45, 37.72, 0),
                   ('LYCAONIA', 33.45, 37.95, 0),
                   ('PAMPHYLIA', 31.7, 36.8, -6), ('GALATIA', 33.0, 38.6, 0),
                   ('CILICIA', 34.9, 37.05, -10), ('SYRIA', 36.9, 35.7, 55)],
    title="PAUL'S FIRST MISSIONARY JOURNEY",
    subtitle='Acts 13\u201314 \u00b7 c. AD 46\u201348',
    # Present-day era: living successor cities take modern names; pure
    # ruins keep the ancient name + "(ruins)".
    modern_names={
        'Antioch (Syria)':    'Antakya',          # Hatay, Turkiye
        'Seleucia':           'Samanda\u011f',
        'Salamis':            'Salamis (ruins)',
        'Paphos':             'Paphos',
        'Perga':              'Perge (ruins)',
        'Attalia':            'Antalya',
        'Antioch in Pisidia': 'Yalva\u00e7',
        'Iconium':            'Konya',
        'Lystra':             'Lystra (ruins)',
        'Derbe':              'Derbe (ruins)',
    },
    modern_context_names={'Tarsus': 'Tarsus', 'Myra': 'Demre'},
    modern_label_pos={'Salamis': (9, 20, 'start')},
    modern_region_labels=[('CYPRUS', 33.2, 35.05, -8),
                          ('T\u00dcRK\u0130YE', 32.6, 38.5, 0),
                          ('SYRIA', 36.9, 35.7, 55),
                          ('LEBANON', 36.35, 34.25, 40)],
    modern_subtitle='Acts 13\u201314 \u00b7 present-day place names',
    border_countries={'Turkey', 'Syria', 'Lebanon'},
)

# Paul's second missionary journey (Acts 15:36-18:22). Route scholarship:
# Antioch->Tarsus crosses the Amanus at the Syrian Gates (Belen Pass) and
# the Taurus at the Cilician Gates (15:41-16:1, "through Syria and
# Cilicia"); on through Derbe/Lystra/Iconium to Pisidian Antioch, then
# "through Phrygia and Galatia, forbidden in Asia" (16:6) — traditional
# corridor north via Prymnessus to Cotiaeum, then "passing by Mysia, down
# to Troas" (16:7-8) via Hadrianutherae. Sea to Samothrace + Neapolis in
# two days (16:11), then the VIA EGNATIA: Neapolis-Philippi-Amphipolis-
# Apollonia-Thessalonica (17:1 names the stations). Berea (17:10); to the
# coast at Methone, then SEA to Athens (17:14 "sent him off to the sea")
# — southbound = downwind with the Etesians (lesson 12), threading east
# of Euboea to Sounion. Athens->Corinth by the Megara coast road. Home:
# Cenchreae (18:18, Corinth's east port, unlabeled waypoint: 10 px from
# Corinth's dot) -> Ephesus (eastbound open sea) -> Caesarea (long
# downwind run passing south of Cyprus, the Acts 21:1-3 pattern), "up"
# to Jerusalem (18:22, retraced to Caesarea), then home BY SEA up the
# Levant coast to Seleucia (Antioch's port) and the short road inland —
# 18:22 names no land stops, and coasting the Phoenician shore is exactly
# the Acts 21:1-7 pattern. Tyre/Sidon/Ptolemais ride along as context
# dots (they are journey-3 ports).
MAPS['paul_journey_2'] = dict(
    bbox=(21.4, 31.4, 37.2, 41.6),
    width=1400,
    places={
        'Antioch (Syria)':    (36.171743, 36.226691),
        'Tarsus':             (34.892056, 36.913028),
        'Derbe':              (33.361453, 37.348569),
        'Lystra':             (32.338400, 37.601700),
        'Iconium':            (32.492331, 37.872202),
        'Antioch in Pisidia': (31.189167, 38.306111),
        'Troas':              (26.158611, 39.751944),
        'Samothrace':         (25.583333, 40.450000),
        'Neapolis':           (24.415000, 40.935000),
        'Philippi':           (24.284576, 41.012072),
        'Amphipolis':         (23.847209, 40.820159),
        'Apollonia':          (23.469685, 40.623703),
        'Thessalonica':       (22.945767, 40.637771),
        'Berea':              (22.200000, 40.518333),
        'Athens':             (23.726738, 37.971851),
        'Corinth':            (22.878741, 37.905785),
        'Ephesus':            (27.340700, 37.939125),
        'Caesarea':           (34.891667, 32.500000),
        'Jerusalem':          (35.234167, 31.776667),
    },
    waypoints={
        'Syrian Gates':     (36.204, 36.494),   # Belen Pass, Amanus
        'Iskenderun':       (36.300, 36.610),   # E shore of the gulf
        'Cilician Plain':   (36.150, 36.980),   # round the gulf's NE head
        'Cilician Gates':   (34.770, 37.280),   # Gulek Pass, Taurus
        'Cybistra':         (34.050, 37.510),   # Eregli, Tyana road
        'Prymnessus':       (30.550, 38.720),   # near Afyon
        'Cotiaeum':         (29.980, 39.420),   # Kutahya
        'Hadrianutherae':   (27.890, 39.650),   # Balikesir ("passing by Mysia")
        'Methone':          (22.620, 40.410),   # Pierian port for Berea
        # Aegean sea-lane vertices, placed from the DRAWN islands' own
        # extents (the Hoyran rule): the lanes are the ancient ones —
        # round Tenedos, the Lemnos-Imbros gap, down the Magnesian coast
        # through the Trikeri channel, outside Euboea, the Doro passage
        # (Euboea-Andros), round Sounion; eastbound via the Kea-Kythnos
        # passage, Delos (the entrepot lane), south of Ikaria and Samos.
        'Tenedos S':        (25.950, 39.740),
        'Imbros W':         (25.550, 40.060),
        'Thasos N':         (24.730, 40.830),
        'Thermaic Mid':     (22.900, 40.220),
        'Thermaic S':       (22.950, 39.800),
        'Magnesia E':       (23.620, 39.400),
        'Skiathos E':       (23.545, 39.060),
        'Euboea E':         (24.450, 38.620),
        'Kafireas S':       (24.660, 38.010),
        'Kea Channel':      (24.210, 37.600),
        'Saronic':          (23.620, 37.780),
        'Saronic N':        (23.500, 37.830),
        'Sounion S':        (24.050, 37.560),
        'Cyclades W':       (24.430, 37.500),
        'Syros S':          (24.920, 37.320),
        'Delos':            (25.270, 37.370),
        'Ikaria S':         (26.300, 37.440),
        'Samos S':          (26.850, 37.550),
        'Mycale':           (27.100, 37.660),
        'Patmos E':         (26.660, 37.330),
        'Kos W':            (26.750, 36.700),
        'Nisyros S':        (27.020, 36.560),
        'Symi S':           (27.850, 36.480),
        'Rhodes N':         (28.260, 36.490),
        'Rhodes E':         (28.400, 36.320),
        'Pella':            (22.550, 40.780),   # round the Thermaic head
        'Eleusis N':        (23.460, 38.135),   # N of the bay/Salamis
        'Isthmus':          (23.000, 37.950),   # the Corinth isthmus road
        'Megara':           (23.340, 37.995),
        'Cenchreae':        (22.996816, 37.884335),
        'Seleucia':         (35.922, 36.124),   # Antioch's port (sea landfall)
    },
    context_places={
        'Byzantium': (28.760, 41.060),   # the modern era's Istanbul anchor (W of the strait)
        'Rhodes':    (28.220, 36.440),   # journey-3 stop (Acts 21:1)
        'Patmos':    (26.545, 37.309),   # John's exile (Rev 1:9)
        'Tyre':      (35.196, 33.272),   # Acts 21:3-7
        'Sidon':     (35.371, 33.563),   # Acts 27:3
        'Ptolemais': (35.070, 32.920),   # Acts 21:7
    },
    context_label_pos={
        'Byzantium': (8, -8, 'start'),
        'Rhodes':    (-23, 29, 'middle'),   # centred over the island body
        'Patmos':    (9, 4, 'start'),
        'Tyre':      (9, 1, 'start'),
        'Sidon':     (9, 2, 'start'),
        'Ptolemais': (-9, 4, 'end'),
    },
    # Cities that legitimately sit AT the shore (ports + island cities), so
    # the dot-placement guarantee expects them on the coast, not clearing
    # it. Sea-leg endpoints are auto-detected; these are the coastal cities
    # reached only by land legs (Thessalonica/Corinth/Amphipolis are
    # port-cities) or named as context (the islands + Phoenician ports).
    coastal={'Thessalonica', 'Corinth', 'Amphipolis', 'Rhodes', 'Patmos',
             'Tyre', 'Sidon', 'Ptolemais'},
    origin='Antioch (Syria)',
    retraced={('Caesarea', 'Jerusalem')},   # 18:22 "up... and down"
    # Corinth is the turn: from the departure for Cenchreae onward the route
    # is the voyage home (Ephesus, Caesarea, Jerusalem, Antioch) — return hue.
    return_from=('Corinth', 'Cenchreae'),
    legs=[
        ('Antioch (Syria)', 'Syrian Gates', 'land', 0, False),
        ('Syrian Gates', 'Iskenderun', 'land', 0, False),
        ('Iskenderun', 'Cilician Plain', 'land', 0, False),
        ('Cilician Plain', 'Tarsus', 'land', 0, True),
        ('Tarsus', 'Cilician Gates', 'land', 0, False),
        ('Cilician Gates', 'Cybistra', 'land', 0, False),
        ('Cybistra', 'Derbe', 'land', 0, False),
        ('Derbe', 'Lystra', 'land', 0, True),
        ('Lystra', 'Iconium', 'land', 0, False),
        ('Iconium', 'Antioch in Pisidia', 'land', 0, True),
        ('Antioch in Pisidia', 'Prymnessus', 'land', 0, False),
        ('Prymnessus', 'Cotiaeum', 'land', 0, True),
        ('Cotiaeum', 'Hadrianutherae', 'land', 0, False),
        ('Hadrianutherae', 'Troas', 'land', 0, True),
        ('Troas', 'Tenedos S', 'sea', 0.04, False),
        ('Tenedos S', 'Imbros W', 'sea', 0.04, False),
        ('Imbros W', 'Samothrace', 'sea', 0.04, True),
        ('Samothrace', 'Thasos N', 'sea', 0, False),
        ('Thasos N', 'Neapolis', 'sea', 0.05, False),
        ('Neapolis', 'Philippi', 'land', 0, False),
        ('Philippi', 'Amphipolis', 'land', 0, False),
        ('Amphipolis', 'Apollonia', 'land', 0, False),
        ('Apollonia', 'Thessalonica', 'land', 0, True),
        ('Thessalonica', 'Pella', 'land', 0, False),
        ('Pella', 'Berea', 'land', 0, False),
        ('Berea', 'Methone', 'land', 0, False),
        ('Methone', 'Thermaic Mid', 'sea', 0.02, False),
        ('Thermaic Mid', 'Thermaic S', 'sea', 0.02, False),
        ('Thermaic S', 'Magnesia E', 'sea', 0.05, False),
        ('Magnesia E', 'Skiathos E', 'sea', 0.02, False),
        ('Skiathos E', 'Euboea E', 'sea', 0.04, True),
        ('Euboea E', 'Kafireas S', 'sea', 0.03, False),
        ('Kafireas S', 'Kea Channel', 'sea', 0.03, False),
        ('Kea Channel', 'Sounion S', 'sea', 0.02, False),
        ('Sounion S', 'Saronic', 'sea', 0.02, False),
        ('Saronic', 'Athens', 'sea', 0.02, False),
        ('Athens', 'Eleusis N', 'land', 0, False),
        ('Eleusis N', 'Megara', 'land', 0, False),
        ('Megara', 'Isthmus', 'land', 0, False),
        ('Isthmus', 'Corinth', 'land', 0, False),
        ('Corinth', 'Cenchreae', 'land', 0, False),
        ('Cenchreae', 'Saronic N', 'sea', 0.02, False),
        ('Saronic N', 'Sounion S', 'sea', 0.02, False),
        ('Sounion S', 'Cyclades W', 'sea', 0.02, False),
        ('Cyclades W', 'Syros S', 'sea', 0.02, False),
        ('Syros S', 'Delos', 'sea', 0.02, False),
        ('Delos', 'Ikaria S', 'sea', 0.02, True),
        ('Ikaria S', 'Samos S', 'sea', 0.02, False),
        ('Samos S', 'Mycale', 'sea', 0.02, False),
        ('Mycale', 'Ephesus', 'sea', 0.02, False),
        # Homebound, ships left Ephesus back down the Samos strait — the
        # same water the arrival lane just drew, so (like retraced roads,
        # lesson 3) it is drawn once: the outbound resumes at Samos S and
        # takes the west-of-Dodecanese lane past Leros, Kos, Nisyros and
        # Symi to the Rhodes channel, then the long open downwind run
        # south of Cyprus (Acts 21:1-3 pattern; lesson 12).
        ('Samos S', 'Patmos E', 'sea', -0.08, False),
        ('Patmos E', 'Kos W', 'sea', 0, False),
        ('Kos W', 'Nisyros S', 'sea', 0.02, False),
        ('Nisyros S', 'Symi S', 'sea', 0.02, False),
        ('Symi S', 'Rhodes N', 'sea', 0, False),
        ('Rhodes N', 'Rhodes E', 'sea', 0, False),
        ('Rhodes E', 'Caesarea', 'sea', -0.10, True),
        ('Caesarea', 'Jerusalem', 'land', 0, False),
        ('Caesarea', 'Seleucia', 'sea', 0.10, True),
        ('Seleucia', 'Antioch (Syria)', 'land', 0, False),
    ],
    label_pos={
        'Antioch (Syria)':    (-12, -10, 'end'),
        'Tarsus':             (6, 19, 'start'),
        'Derbe':              (10, 14, 'start'),
        'Lystra':             (-11, 8, 'end'),
        'Iconium':            (12, -4, 'start'),
        'Antioch in Pisidia': (10, -8, 'start'),
        'Troas':              (-10, -6, 'end'),
        'Samothrace':         (10, 12, 'start'),
        'Neapolis':           (10, 12, 'start'),
        'Philippi':           (8, -10, 'start'),
        'Amphipolis':         (6, -9, 'end'),
        'Apollonia':          (-8, 19, 'end'),
        'Thessalonica':       (-11, -9, 'end'),
        'Berea':              (-10, 12, 'end'),
        'Athens':             (12, 10, 'start'),
        'Corinth':            (-11, -6, 'end'),
        'Ephesus':            (10, -8, 'start'),
        'Caesarea':           (10, 4, 'start'),
        'Jerusalem':          (12, 6, 'start'),
    },
    sea_labels=[('Aegean Sea', 25.05, 38.65, -70),
                ('Mediterranean Sea', 30.0, 33.6, 0)],
    # Acts 15:36-18:22 names them all: Syria & Cilicia (15:41), Phrygia &
    # Galatia (16:6), Asia (16:6), Mysia & Bithynia (16:7), Macedonia
    # (16:9), Achaia (18:12).
    region_labels=[('SYRIA', 36.8, 35.3, 50), ('CILICIA', 34.6, 37.02, -8),
                   ('PHRYGIA', 29.55, 38.72, 0), ('GALATIA', 32.6, 39.3, 0),
                   ('ASIA', 28.6, 38.45, 0), ('MYSIA', 27.25, 39.35, 0),
                   ('BITHYNIA', 30.6, 40.55, 0),
                   ('MACEDONIA', 23.45, 41.3, 0), ('ACHAIA', 22.4, 38.4, 0)],
    title="PAUL'S SECOND MISSIONARY JOURNEY",
    subtitle='Acts 15:36\u201318:22 \u00b7 c. AD 49\u201352',
    modern_names={
        'Antioch (Syria)':    'Antakya',
        'Tarsus':             'Tarsus',
        'Derbe':              'Derbe (ruins)',
        'Lystra':             'Lystra (ruins)',
        'Iconium':            'Konya',
        'Antioch in Pisidia': 'Yalva\u00e7',
        'Troas':              'Troas (ruins)',
        'Samothrace':         'Samothraki',
        'Neapolis':           'Kavala',
        'Philippi':           'Philippi (ruins)',
        'Amphipolis':         'Amphipolis (ruins)',
        'Apollonia':          'Apollonia (ruins)',
        'Thessalonica':       'Thessaloniki',
        'Berea':              'Veria',
        'Athens':             'Athens',
        'Corinth':            'Corinth',
        'Ephesus':            'Ephesus (ruins)',
        'Caesarea':           'Caesarea',
        'Jerusalem':          'Jerusalem',
    },
    modern_context_names={'Byzantium': 'Istanbul', 'Rhodes': 'Rhodes',
                          'Patmos': 'Patmos', 'Tyre': 'Tyre',
                          'Sidon': 'Sidon', 'Ptolemais': 'Akko'},
    # "(ruins)" names run longer — Veria/Apollonia collide on the shared
    # nudges
    modern_label_pos={'Apollonia': (3, 19, 'start'),
                      'Berea': (-9, 15, 'end'),
                      'Amphipolis': (6, -9, 'end')},
    # West Bank lines excluded like Cyprus' in journey 1 — major
    # international boundaries only; the calm rendering.
    modern_region_labels=[('GREECE', 22.6, 39.4, 0),
                          ('T\u00dcRK\u0130YE', 31.5, 39.6, 0),
                          ('SYRIA', 36.8, 35.3, 50),
                          ('CYPRUS', 33.2, 35.05, -8),
                          ('LEBANON', 35.85, 34.15, 40),
                          ('ISRAEL', 34.72, 32.2, 60),
                          ('JORDAN', 36.25, 31.78, 0)],
    modern_subtitle='Acts 15:36\u201318:22 \u00b7 present-day place names',
    border_countries={'Turkey', 'Greece', 'Bulgaria', 'North Macedonia',
                      'Albania', 'Syria', 'Lebanon', 'Israel', 'Jordan'},
)

# Paul's third missionary journey (Acts 18:23-21:16). Same Greece->Jerusalem
# frame as journey 2. Outbound overland through "Galatia and Phrygia"
# strengthening the churches (18:23) - the journey-2 corridor as far as
# Pisidian Antioch - then WEST by the "upper country" road (19:1, ta
# anoterika mere: the interior highway via Apamea down the Lycus/Maeander to
# Ephesus, NOT the coast). Three years at Ephesus (19), then to Macedonia and
# Greece (20:1-2). The signature is the verse-by-verse return voyage
# (20:13-21:16): Troas -> Assos (Paul ALONE on foot, 20:13) -> Mitylene ->
# past Chios -> Samos -> Miletus (the Ephesian-elders farewell) -> Cos ->
# Rhodes -> Patara, then the open run "leaving Cyprus on the left" (21:3) to
# Tyre, down the coast to Ptolemais and Caesarea, and up to Jerusalem.
# The Macedonia excursion is traversed both ways. The Greek LAND corridor
# (Neapolis down to Corinth and back) is now drawn as an offset out/return
# PAIR — red out, amber back — so the homeward Macedonia/Achaia leg is
# visible (a deliberate reversal of the old draw-once, lessons 3 & 5; the two
# hues keep the doubled corridor legible rather than burying the map). The
# shared Neapolis<->Troas sea crossing stays drawn once (the islands leave no
# clean parallel lane); the amber return resumes at the Troas farewell.
MAPS['paul_journey_3'] = dict(
    bbox=(21.4, 31.4, 37.2, 41.6),
    width=1400,
    places={
        'Antioch (Syria)':    (36.171743, 36.226691),
        'Tarsus':             (34.892056, 36.913028),
        'Derbe':              (33.361453, 37.348569),
        'Lystra':             (32.338400, 37.601700),
        'Iconium':            (32.492331, 37.872202),
        'Antioch in Pisidia': (31.189167, 38.306111),
        'Ephesus':            (27.340700, 37.939125),
        'Troas':              (26.158611, 39.751944),
        'Neapolis':           (24.415000, 40.935000),
        'Philippi':           (24.284576, 41.012072),
        'Thessalonica':       (22.945767, 40.637771),
        'Berea':              (22.200000, 40.518333),
        'Corinth':            (22.878741, 37.905785),
        'Assos':              (26.336700, 39.490600),
        'Mitylene':           (26.547000, 39.110500),
        'Samos':              (26.833300, 37.750000),
        'Miletus':            (27.275600, 37.531100),
        'Cos':                (27.110300, 36.815300),
        'Rhodes':             (28.220000, 36.440000),
        'Patara':             (29.314200, 36.260300),
        'Tyre':               (35.196100, 33.270800),
        'Ptolemais':          (35.069200, 32.921400),
        'Caesarea':           (34.891667, 32.500000),
        'Jerusalem':          (35.234167, 31.776667),
    },
    waypoints={
        # Anatolian gates (journey-2 routing round the Gulf of Iskenderun)
        'Syrian Gates':     (36.204, 36.494),
        'Iskenderun':       (36.300, 36.610),
        'Cilician Plain':   (36.150, 36.980),
        'Cilician Gates':   (34.770, 37.280),
        'Cybistra':         (34.050, 37.510),
        # "upper country" road (19:1): Apamea then down the Lycus valley
        'Apamea':           (30.170, 38.070),
        'Lycus':            (29.110, 37.840),   # Laodicea/Colossae corridor
        'Maeander':         (27.900, 37.870),   # over to the Cayster/Ephesus
        # Karaburun (the big mainland headland) blocks the inside channel,
        # so BOTH directions pass west of it: the outbound sweeps the open
        # Aegean west of Chios/Lesbos, the return threads back nearer the
        # islands - a clean loop, arrows carrying direction.
        'Aegean SW':        (25.700, 37.950),
        'Aegean W':         (25.600, 38.850),
        'Mytilene Str':     (26.720, 39.330),
        'Lesbos E S':       (26.700, 39.000),
        'Lesbos SW':        (25.950, 38.850),
        # Carian coast / Dodecanese (the island-hop south)
        'Mycale S':         (27.020, 37.600),
        'Bodrum W':         (26.820, 37.020),
        'Kos N':            (26.780, 36.820),
        'Nisyros S':        (27.020, 36.560),
        'Symi S':           (27.850, 36.480),
        'Rhodes N':         (28.180, 36.500),
        # North Aegean (Troas<->Neapolis): the islands (Thasos sits right off
        # Neapolis) force a single threaded lane — no clean parallel exists on
        # either side — so the shared crossing is drawn ONCE (outbound) and the
        # homeward leg resumes in amber at Troas (lessons 3 & 5).
        'Tenedos S':        (25.950, 39.740),
        'Imbros W':         (25.520, 40.120),
        'Samothrace N':     (25.300, 40.560),
        'Thasos S':         (24.720, 40.630),
        # Levant coastal sail (offshore of the convex coast)
        'Pella':            (22.550, 40.780),   # round the Thermaic head
        # the historic road south to Corinth: down Thessaly, the Maliac
        # gulf at Thermopylae, Boeotia/Thebes, then round the Gulf of
        # Corinth's east end and over the isthmus (the only land bridge)
        'Tempe':            (22.420, 39.850),
        'Lamia':            (22.430, 38.950),
        'Thermopylae':      (22.400, 38.720),
        'Thebes':           (23.320, 38.330),
        # Nudged a touch inland (NW) of the Saronic shore so the smoothed
        # out/return pair turns the corner on land, not over the bay.
        'Megara':           (23.300, 38.045),
        'Isthmus':          (23.000, 37.955),
        'Egirdir S':        (30.980, 37.720),   # skirt the lakes to Apamea
        'Burdur S':         (30.300, 37.560),
    },
    context_places={
        'Chios':     (26.1375, 38.3725),   # "came opposite Chios" (20:15)
        'Patmos':    (26.545, 37.309),     # Rev 1:9 - on the island return lane
        'Cnidus':    (27.375, 36.686),     # journey-to-Rome stop (27:7)
    },
    context_label_pos={
        'Chios':  (-9, 4, 'end'),
        'Patmos': (-9, 13, 'end'),
        'Cnidus': (9, 6, 'start'),
    },
    coastal={'Corinth', 'Thessalonica', 'Chios', 'Patmos', 'Cnidus'},
    origin='Antioch (Syria)',
    # The Greek land corridor (Neapolis down to Corinth) is traversed both
    # ways — drawn as an offset out/return pair. The Neapolis<->Troas sea
    # crossing and the island voyage home are coloured by return_from below.
    retraced={('Neapolis', 'Philippi'), ('Philippi', 'Thessalonica'),
              ('Thessalonica', 'Pella'), ('Pella', 'Berea'),
              ('Berea', 'Tempe'), ('Tempe', 'Lamia'),
              ('Lamia', 'Thermopylae'), ('Thermopylae', 'Thebes'),
              ('Thebes', 'Megara'), ('Megara', 'Isthmus'),
              ('Isthmus', 'Corinth')},
    # Corinth is the turn; from the Troas farewell on, the whole island
    # voyage down to Jerusalem is drawn in the return hue.
    return_from=('Troas', 'Assos'),
    legs=[
        # ── outbound: Galatia & Phrygia, strengthening the churches (18:23)
        ('Antioch (Syria)', 'Syrian Gates', 'land', 0, False),
        ('Syrian Gates', 'Iskenderun', 'land', 0, False),
        ('Iskenderun', 'Cilician Plain', 'land', 0, False),
        ('Cilician Plain', 'Tarsus', 'land', 0, True),
        ('Tarsus', 'Cilician Gates', 'land', 0, False),
        ('Cilician Gates', 'Cybistra', 'land', 0, False),
        ('Cybistra', 'Derbe', 'land', 0, False),
        ('Derbe', 'Lystra', 'land', 0, False),
        ('Lystra', 'Iconium', 'land', 0, True),
        ('Iconium', 'Antioch in Pisidia', 'land', 0, False),
        # ── upper country to Ephesus (19:1)
        ('Antioch in Pisidia', 'Egirdir S', 'land', 0, True),
        ('Egirdir S', 'Burdur S', 'land', 0, False),
        ('Burdur S', 'Apamea', 'land', 0, False),
        ('Apamea', 'Lycus', 'land', 0, False),
        ('Lycus', 'Maeander', 'land', 0, False),
        ('Maeander', 'Ephesus', 'land', 0, False),
        # ── Ephesus -> Macedonia -> Greece (20:1-2); drawn once.
        # Up the Ionian straits (east of Chios and Lesbos) to Troas.
        ('Ephesus', 'Aegean SW', 'sea', 0.04, True),
        ('Aegean SW', 'Aegean W', 'sea', 0, False),
        ('Aegean W', 'Troas', 'sea', 0.03, False),
        # North Aegean crossing to Macedonia
        ('Troas', 'Tenedos S', 'sea', 0.03, False),
        ('Tenedos S', 'Imbros W', 'sea', 0.03, False),
        ('Imbros W', 'Samothrace N', 'sea', 0.03, False),
        ('Samothrace N', 'Thasos S', 'sea', 0.02, False),
        ('Thasos S', 'Neapolis', 'sea', 0.04, False),
        ('Neapolis', 'Philippi', 'land', 0, False),
        ('Philippi', 'Thessalonica', 'land', 0, False),
        ('Thessalonica', 'Pella', 'land', 0, False),
        ('Pella', 'Berea', 'land', 0, False),
        ('Berea', 'Tempe', 'land', 0, True),
        ('Tempe', 'Lamia', 'land', 0, False),
        ('Lamia', 'Thermopylae', 'land', 0, False),
        ('Thermopylae', 'Thebes', 'land', 0, False),
        ('Thebes', 'Megara', 'land', 0, False),
        ('Megara', 'Isthmus', 'land', 0, False),
        ('Isthmus', 'Corinth', 'land', 0, False),
        # ── homeward (20:3-6): back through Macedonia (the corridor above is
        # the return lane of the pair) to Philippi/Neapolis, then the shared
        # Neapolis->Troas sea crossing (drawn once, outbound). The return
        # voyage (20:13-21:16) resumes in amber at Troas: walk to Assos, then
        # the island-hop south to the Levant.
        ('Troas', 'Assos', 'land', 0, True),
        ('Assos', 'Mytilene Str', 'sea', 0.03, False),
        ('Mytilene Str', 'Mitylene', 'sea', 0.02, False),
        # back down the shared channel to Samos (bypassing Ephesus, 20:16)
        ('Mitylene', 'Lesbos E S', 'sea', 0, True),
        ('Lesbos E S', 'Lesbos SW', 'sea', 0, False),
        ('Lesbos SW', 'Aegean W', 'sea', 0, False),
        ('Aegean W', 'Aegean SW', 'sea', 0, False),
        ('Aegean SW', 'Samos', 'sea', 0, False),
        ('Samos', 'Mycale S', 'sea', 0.02, False),
        ('Mycale S', 'Miletus', 'sea', 0.02, False),
        # offshore round the Bodrum peninsula to Cos
        ('Miletus', 'Bodrum W', 'sea', 0.03, False),
        ('Bodrum W', 'Kos N', 'sea', 0.02, False),
        ('Kos N', 'Cos', 'sea', 0.02, False),
        # south of the Datca/Cnidus peninsula to Rhodes
        ('Cos', 'Nisyros S', 'sea', 0.03, False),
        ('Nisyros S', 'Symi S', 'sea', 0.02, False),
        ('Symi S', 'Rhodes N', 'sea', 0.02, False),
        ('Rhodes N', 'Rhodes', 'sea', 0.02, True),
        ('Rhodes', 'Patara', 'sea', 0.04, True),
        # open run "leaving Cyprus on the left" (21:3)
        ('Patara', 'Tyre', 'sea', -0.10, True),
        # coastal sail down to Ptolemais and Caesarea (offshore of the
        # convex Phoenician coast, then landing at each named port)
        ('Tyre', 'Ptolemais', 'sea', -0.55, False),
        ('Ptolemais', 'Caesarea', 'sea', -0.40, True),
        ('Caesarea', 'Jerusalem', 'land', 0, True),
    ],
    label_pos={
        'Antioch (Syria)':    (-12, -10, 'end'),
        'Tarsus':             (6, 19, 'start'),
        'Derbe':              (10, 14, 'start'),
        'Lystra':             (-11, 8, 'end'),
        'Iconium':            (10, -8, 'start'),
        'Antioch in Pisidia': (10, -8, 'start'),
        'Ephesus':            (9, -7, 'start'),
        'Troas':              (-10, -6, 'end'),
        'Neapolis':           (10, 12, 'start'),
        'Philippi':           (8, -10, 'start'),
        'Thessalonica':       (-11, -9, 'end'),
        'Berea':              (-10, 4, 'end'),
        'Corinth':            (-11, -6, 'end'),
        'Assos':              (-10, -6, 'end'),
        'Mitylene':           (10, 3, 'start'),
        'Samos':              (-10, 1, 'end'),
        'Miletus':            (9, 16, 'start'),   # below-right, clear of Patmos
        'Cos':                (0, -9, 'middle'),  # above, clear of Cnidus
        'Rhodes':             (-23, 29, 'middle'),
        'Patara':             (8, 16, 'start'),
        'Tyre':               (10, 2, 'start'),
        'Ptolemais':          (-9, 4, 'end'),
        'Caesarea':           (10, 4, 'start'),
        'Jerusalem':          (12, 6, 'start'),
    },
    sea_labels=[('Aegean Sea', 25.05, 38.55, -70),
                ('Mediterranean Sea', 30.5, 33.3, 0)],
    region_labels=[('SYRIA', 36.8, 35.3, 50), ('CILICIA', 34.6, 37.02, -8),
                   ('PHRYGIA', 30.0, 38.6, 0), ('GALATIA', 32.6, 39.3, 0),
                   ('ASIA', 28.4, 38.7, 0), ('LYDIA', 28.0, 38.25, 0),
                   ('MACEDONIA', 23.45, 41.3, 0), ('ACHAIA', 22.5, 38.5, 0),
                   ('LYCIA', 29.6, 36.6, 0)],
    title="PAUL'S THIRD MISSIONARY JOURNEY",
    subtitle='Acts 18:23\u201321:16 \u00b7 c. AD 53\u201357',
    modern_names={
        'Antioch (Syria)':    'Antakya',
        'Tarsus':             'Tarsus',
        'Derbe':              'Derbe (ruins)',
        'Lystra':             'Lystra (ruins)',
        'Iconium':            'Konya',
        'Antioch in Pisidia': 'Yalva\u00e7',
        'Ephesus':            'Ephesus (ruins)',
        'Troas':              'Troas (ruins)',
        'Neapolis':           'Kavala',
        'Philippi':           'Philippi (ruins)',
        'Thessalonica':       'Thessaloniki',
        'Berea':              'Veria',
        'Corinth':            'Corinth',
        'Assos':              'Behramkale',
        'Mitylene':           'Mytilene',
        'Samos':              'Samos',
        'Miletus':            'Miletus (ruins)',
        'Cos':                'Kos',
        'Rhodes':             'Rhodes',
        'Patara':             'Patara (ruins)',
        'Tyre':               'Tyre',
        'Ptolemais':          'Akko',
        'Caesarea':           'Caesarea',
        'Jerusalem':          'Jerusalem',
    },
    modern_context_names={'Chios': 'Chios', 'Patmos': 'Patmos',
                          'Cnidus': 'Cnidus (ruins)'},
    modern_label_pos={},
    modern_region_labels=[('GREECE', 22.6, 39.4, 0),
                          ('T\u00dcRK\u0130YE', 31.5, 39.6, 0),
                          ('SYRIA', 36.8, 35.3, 50),
                          ('CYPRUS', 33.2, 35.05, -8),
                          ('LEBANON', 35.85, 34.15, 40),
                          ('ISRAEL', 34.72, 32.2, 60),
                          ('JORDAN', 36.25, 31.78, 0)],
    modern_subtitle='Acts 18:23\u201321:16 \u00b7 present-day place names',
    border_countries={'Turkey', 'Greece', 'Bulgaria', 'North Macedonia',
                      'Albania', 'Syria', 'Lebanon', 'Israel', 'Jordan'},
)

# Paul's voyage to Rome (Acts 27:1-28:16). A prisoner transport, one way -
# so the whole route is outbound (no return hue). From Caesarea up the coast
# to Sidon (27:3), then "under the lee of Cyprus, the winds being contrary"
# (27:4) = up the sheltered E/N side of the island, across the open sea off
# Cilicia and Pamphylia to Myra in Lycia (27:5), where they changed to an
# Alexandrian grain ship. Slow westing to Cnidus (27:7), then forced SW
# "under the lee of Crete off Salmone" (the NE cape), coasting the south
# shore to Fair Havens by Lasea (27:8). Leaving for Phoenix they were caught
# by the Euraquilo and run under the lee of Cauda (27:14-16), then driven
# fourteen days across "the Adria" (27:27) - fearing the Syrtis shoals
# (27:17) - to shipwreck on Malta (28:1). After three months: Syracuse,
# Rhegium, Puteoli (28:12-13), then the Via Appia by LAND through the Forum
# of Appius and Three Taverns to Rome (28:15-16). All coords OpenBible.info.
MAPS['paul_journey_4'] = dict(
    # Left edge carries extra Tyrrhenian sea so the tight Via Appia cluster
    # (Rome/Three Taverns/Forum of Appius) can label onto open water instead
    # of burying the ITALIA region label.
    bbox=(10.0, 31.6, 36.4, 42.4),
    width=1800,
    places={
        'Caesarea':         (34.891667, 32.500000),
        'Sidon':            (35.371944, 33.560985),
        'Myra':             (29.985278, 36.259167),
        'Cnidus':           (27.375000, 36.685830),
        'Salmone':          (26.311041, 35.313628),
        'Fair Havens':      (24.800306, 34.929694),
        'Cauda':            (24.121511, 34.801558),
        'Malta':            (14.401000, 35.953000),   # St Paul's Bay landfall
        'Syracuse':         (15.293060, 37.063890),
        'Rhegium':          (15.644120, 38.108800),
        'Puteoli':          (14.120556, 40.826111),
        'Forum of Appius':  (12.997500, 41.466390),
        'Three Taverns':    (12.873890, 41.561940),
        'Rome':             (12.485200, 41.892200),
    },
    # Sea-lane vertices charted from the drawn coast: round Cyprus' E/N
    # shore (the "lee"), offshore of the Lycian capes, round Crete's SE cape
    # and along its south coast, and up the Tyrrhenian offshore of Calabria.
    waypoints={
        'Phoenicia W':   (34.92, 33.10),   # offshore W of Tyre/Ptolemais
        'Cyprus E':      (34.20, 34.75),   # off the SE corner (Cape Greco)
        'Cyprus NE':     (34.80, 35.75),   # off the Karpas NE tip
        'Cyprus N':      (33.00, 35.70),   # north coast, offshore
        'Lycia S':       (29.50, 35.80),   # open water S of the Lycian coast
        'Rhodes S':      (27.85, 35.72),   # S of Rhodes (charted clear lane)
        'Rhodes W':      (27.20, 36.40),   # W of Rhodes & the Tilos islets
        'Crete E':       (26.45, 35.05),   # off Crete's east coast
        'Crete SE':      (26.05, 34.68),   # S of the SE cape
        'Crete S':       (25.30, 34.72),   # south coast, offshore
        'Sicily SE':     (15.45, 36.62),   # off Cape Passero
        'Syracuse E':    (15.45, 36.95),   # E of the Plemmirio cape (arrival)
        'Syracuse N':    (15.52, 37.02),   # due E out of the harbour (departure)
        'Strait N':      (15.72, 38.55),   # through the strait, Calabrian side
        'Tyrrhenian S':  (15.10, 39.30),   # offshore W of Calabria
        'Tyrrhenian N':  (14.20, 40.55),   # W of Capri, into the bay
        'Capua':         (14.25, 41.08),   # Via Appia inland (land leg)
    },
    # The harbor they made for but never reached (27:12) - an off-route
    # context dot, not a stop.
    context_places={
        'Phoenix':       (24.078580, 35.200010),
    },
    context_label_pos={
        'Phoenix':       (-9, -6, 'end'),
    },
    coastal={'Phoenix'},
    origin='Caesarea',
    retraced=set(),
    legs=[
        ('Caesarea', 'Phoenicia W', 'sea', 0.0, False),
        ('Phoenicia W', 'Sidon', 'sea', 0.04, False),
        ('Sidon', 'Cyprus E', 'sea', 0.0, False),
        ('Cyprus E', 'Cyprus NE', 'sea', -0.05, False),  # bow E off the Karpas
        ('Cyprus NE', 'Cyprus N', 'sea', 0.04, False),
        ('Cyprus N', 'Myra', 'sea', 0.05, True),
        ('Myra', 'Lycia S', 'sea', 0.0, False),
        ('Lycia S', 'Rhodes S', 'sea', 0.0, False),
        ('Rhodes S', 'Rhodes W', 'sea', 0.0, False),
        ('Rhodes W', 'Cnidus', 'sea', 0.0, False),
        ('Cnidus', 'Salmone', 'sea', 0.08, True),
        ('Salmone', 'Crete E', 'sea', 0.0, False),
        ('Crete E', 'Crete SE', 'sea', 0.0, False),
        ('Crete SE', 'Crete S', 'sea', 0.0, False),
        ('Crete S', 'Fair Havens', 'sea', 0.0, False),
        ('Fair Havens', 'Cauda', 'sea', -0.08, True),
        ('Cauda', 'Malta', 'sea', 0.10, True),
        ('Malta', 'Sicily SE', 'sea', 0.0, True),        # round Cape Passero
        ('Sicily SE', 'Syracuse E', 'sea', 0.0, False),
        ('Syracuse E', 'Syracuse', 'sea', 0.0, False),   # into the harbour from E
        ('Syracuse', 'Syracuse N', 'sea', 0.0, False),   # back out, NE
        ('Syracuse N', 'Rhegium', 'sea', 0.04, True),    # NE across the Ionian
        ('Rhegium', 'Strait N', 'sea', 0.0, False),      # N through the strait
        ('Strait N', 'Tyrrhenian S', 'sea', 0.0, False),
        ('Tyrrhenian S', 'Tyrrhenian N', 'sea', 0.04, False),
        ('Tyrrhenian N', 'Puteoli', 'sea', 0.0, True),
        ('Puteoli', 'Capua', 'land', 0, False),
        ('Capua', 'Forum of Appius', 'land', 0, False),
        ('Forum of Appius', 'Three Taverns', 'land', 0, False),
        ('Three Taverns', 'Rome', 'land', 0, True),
    ],
    label_pos={
        'Caesarea':         (-9, 13, 'end'),
        'Sidon':            (9, 2, 'start'),
        'Myra':             (6, -9, 'start'),
        'Cnidus':           (10, 6, 'start'),   # E onto its peninsula, off islets
        'Salmone':          (11, 6, 'start'),   # level w/ dot, over open sea
        'Fair Havens':      (11, 19, 'start'),  # below-right onto the sea
        'Cauda':            (-10, 19, 'end'),   # below-left onto the sea
        'Malta':            (9, 8, 'start'),
        'Syracuse':         (-9, 8, 'end'),
        'Rhegium':          (9, 4, 'start'),
        'Puteoli':          (-9, -3, 'end'),
        # The three Via Appia stations cluster tight; the route runs inland
        # (right), so labels go LEFT onto the open Tyrrhenian — Rome above,
        # the two stations cascading down the sea — leaving ITALIA clear.
        'Forum of Appius':  (-12, 21, 'end'),
        'Three Taverns':    (-12, 3, 'end'),
        'Rome':             (0, -12, 'middle'),
    },
    sea_labels=[('Mediterranean Sea', 20.0, 33.6, 0),
                ('The Adria', 18.3, 36.0, 0),
                ('Tyrrhenian Sea', 12.6, 39.7, 0),
                ('Aegean Sea', 25.2, 38.4, -70)],
    region_labels=[('ITALIA', 14.6, 41.95, 0), ('SICILIA', 14.2, 37.5, 0),
                   ('CRETE', 24.9, 35.18, 0), ('CYPRUS', 33.2, 35.0, 0),
                   ('LYCIA', 29.7, 36.7, 0), ('ACHAIA', 21.8, 37.9, 0),
                   ('SYRTIS', 19.2, 32.2, 0), ('AFRICA', 15.5, 32.2, 0)],
    title="PAUL'S VOYAGE TO ROME",
    subtitle='Acts 27–28 · c. AD 59–60',
    modern_names={
        'Caesarea':         'Caesarea',
        'Sidon':            'Sidon',
        'Myra':             'Demre',
        'Cnidus':           'Cnidus (ruins)',
        'Salmone':          'Cape Sideros',
        'Fair Havens':      'Kaloi Limenes',
        'Cauda':            'Gavdos',
        'Malta':            "St Paul's Bay",
        'Syracuse':         'Siracusa',
        'Rhegium':          'Reggio Calabria',
        'Puteoli':          'Pozzuoli',
        'Forum of Appius':  'Forum Appii (ruins)',
        'Three Taverns':    'Tres Tabernae (ruins)',
        'Rome':             'Rome',
    },
    modern_context_names={'Phoenix': 'Loutro'},
    modern_label_pos={},
    modern_region_labels=[('ITALY', 14.6, 41.95, 0), ('SICILY', 14.2, 37.5, 0),
                          ('CRETE', 24.9, 35.18, 0), ('CYPRUS', 33.2, 35.0, 0),
                          ('GREECE', 21.8, 37.9, 0),
                          ('TÜRKİYE', 30.2, 37.4, 0),
                          ('LIBYA', 17.0, 32.1, 0), ('TUNISIA', 11.9, 34.2, 0)],
    modern_subtitle='Acts 27–28 · present-day place names',
    border_countries={'Italy', 'Greece', 'Turkey', 'Cyprus', 'Malta',
                      'Libya', 'Tunisia', 'Lebanon', 'Israel', 'Syria',
                      'Egypt'},
)

BORDER = '#8d9298'       # quiet dashed hairline — context, never content


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


def _grid_to_lonlat(bbox, nx, ny):
    lon0, lat0, lon1, lat1 = bbox
    return lambda p: (lon0 + (lon1 - lon0) * p[0] / (nx - 1),
                      lat1 - (lat1 - lat0) * p[1] / (ny - 1))


def _contour_overlay(grid, thresholds_colors, bbox, proj, opacity=None,
                     min_area=300, thin_tol=1.2):
    """Marching-squares contour bands shared by relief + hillshade: drop
    speckle rings, thin the rest, emit one evenodd path per threshold."""
    ny, nx = len(grid), len(grid[0])
    to_lonlat = _grid_to_lonlat(bbox, nx, ny)
    out = []
    for k, (threshold, color) in enumerate(thresholds_colors):
        d_parts = []
        for ring in marching_squares(grid, threshold):
            pts = [proj(*to_lonlat(p)) for p in ring]
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            if (max(xs) - min(xs)) * (max(ys) - min(ys)) < min_area:
                continue
            if len(pts) > 24:
                pts = pts[::2]
                if len(pts) > 24:
                    pts = thin_pts(pts, 1.2)
            d_parts.append('M' + ' L'.join(f'{x:.0f},{y:.0f}'
                                           for x, y in pts) + ' Z')
        if d_parts:
            op = f' opacity="{opacity[k]}"' if opacity else ''
            out.append(f'<path d="{" ".join(d_parts)}" fill="{color}" '
                       f'fill-rule="evenodd"{op}/>')
    return out


def hillshade_paths(grid, bbox, proj):
    """Faint classed slope-shading from the elevation grid (NW light)."""
    ny, nx = len(grid), len(grid[0])
    lon0, lat0, lon1, lat1 = bbox
    lat_mid = math.radians((lat0 + lat1) / 2)
    cell_x = (lon1 - lon0) * 111320 * math.cos(lat_mid) / (nx - 1)
    cell_y = (lat1 - lat0) * 111320 / (ny - 1)
    Lx, Ly, Lz = -0.5, -0.5, 0.70711   # NW azimuth, 45° altitude (i, j, up)
    shadow = [[0.0] * nx for _ in range(ny)]
    for j in range(1, ny - 1):
        for i in range(1, nx - 1):
            dzdi = (grid[j][i+1] - grid[j][i-1]) / (2 * cell_x)
            dzdj = (grid[j+1][i] - grid[j-1][i]) / (2 * cell_y)
            nxv, nyv = -HILLSHADE_ZF * dzdi, -HILLSHADE_ZF * dzdj
            nlen = math.sqrt(nxv*nxv + nyv*nyv + 1.0)
            illum = (nxv*Lx + nyv*Ly + Lz) / nlen
            shadow[j][i] = max(0.0, Lz - illum)    # 0 on flat/lit ground
    # Smooth the shadow field before contouring — the gradient amplifies
    # grid noise into a speckle of tiny rings; one box-blur merges them into
    # coherent shadowed flanks and roughly halves the path count.
    for _ in range(2):
        prev = [row[:] for row in shadow]
        for j in range(1, ny - 1):
            for i in range(1, nx - 1):
                shadow[j][i] = (
                    prev[j-1][i-1] + prev[j-1][i] + prev[j-1][i+1] +
                    prev[j][i-1] + prev[j][i] + prev[j][i+1] +
                    prev[j+1][i-1] + prev[j+1][i] + prev[j+1][i+1]) / 9.0
    # Contour at half resolution — the shadow field is soft texture, so a
    # 2x-downsampled grid quarters the ring data with no visible loss.
    shadow = [row[::2] for row in shadow[::2]]
    bands = [(t, HILLSHADE) for t, _ in HILLSHADE_BANDS]
    return _contour_overlay(shadow, bands, bbox, proj,
                            opacity=[o for _, o in HILLSHADE_BANDS],
                            min_area=650, thin_tol=2.6)


def relief_paths(grid, bbox, proj):
    # Hypsometric tint bands — texture, not survey data. (The [::2] halving
    # inside _contour_overlay is safe here: these rings are closed interior
    # contours, never bbox-clipped, so halving can't fold a clipped corner.)
    return _contour_overlay(grid, RELIEF_BANDS, bbox, proj)


# ── SVG emission ─────────────────────────────────────────────────────────────

def thin_pts(pts, tol=0.7):
    """Radial-distance simplification: drop points closer than tol px to
    the last kept one. Error is bounded by tol (sub-pixel), so corners
    survive — naive [::n] slicing can drop bbox-corner vertices and fold
    a clipped ring across the map."""
    out = [pts[0]]
    for p in pts[1:-1]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= tol:
            out.append(p)
    out.append(pts[-1])
    return out


def path_d(points, close=False, dec=1):
    d = 'M' + ' L'.join(f'{x:.{dec}f},{y:.{dec}f}' for x, y in points)
    return d + (' Z' if close else '')


def catmull_rom_beziers(pts, s=ROUTE_SMOOTH, clamp=0.22):
    """Cubic segments (p0, c1, c2, p1) of a Catmull-Rom spline THROUGH every
    point — the curve passes exactly through each city/waypoint, only the
    tangents are smoothed, so bends round without the route leaving its
    coordinates. Ends are duplicated, giving a straight run into terminals
    (no overshoot past the first/last dot).

    Each control handle is capped at `clamp`x the local chord length so a
    sharp corner can't overshoot the curve off the road into water — the
    bound that keeps rounding honest (it was ~12 px of sea-bulge uncapped)."""
    if len(pts) < 3:
        return [(pts[0], pts[0], pts[-1], pts[-1])] if len(pts) == 2 else []

    def handle(anchor, vec, chord):
        ln = math.hypot(vec[0], vec[1])
        cap = clamp * chord
        if ln > cap > 0:
            vec = (vec[0] * cap / ln, vec[1] * cap / ln)
        return (anchor[0] + vec[0], anchor[1] + vec[1])

    P = [pts[0]] + list(pts) + [pts[-1]]
    segs = []
    for i in range(1, len(P) - 2):
        pm, p0, p1, pp = P[i - 1], P[i], P[i + 1], P[i + 2]
        chord = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        c1 = handle(p0, ((p1[0] - pm[0]) * s, (p1[1] - pm[1]) * s), chord)
        c2 = handle(p1, (-(pp[0] - p0[0]) * s, -(pp[1] - p0[1]) * s), chord)
        segs.append((p0, c1, c2, p1))
    return segs


def smooth_path_d(pts):
    """SVG path string of the rounded route through pts."""
    segs = catmull_rom_beziers(pts)
    if not segs:
        return path_d(pts)
    d = f'M{segs[0][0][0]:.1f},{segs[0][0][1]:.1f}'
    for _, c1, c2, p1 in segs:
        d += (f' C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} '
              f'{p1[0]:.1f},{p1[1]:.1f}')
    return d


def smooth_points(pts, n=12):
    """Sample the rounded route as points — for the terrain warnings, which
    must test the curve actually drawn, not the straight chords."""
    segs = catmull_rom_beziers(pts)
    if not segs:
        return list(pts)
    out = [segs[0][0]]
    for p0, c1, c2, p1 in segs:
        for k in range(1, n + 1):
            t = k / n
            u = 1 - t
            out.append((u*u*u*p0[0] + 3*u*u*t*c1[0] + 3*u*t*t*c2[0] + t*t*t*p1[0],
                        u*u*u*p0[1] + 3*u*u*t*c1[1] + 3*u*t*t*c2[1] + t*t*t*p1[1]))
    return out


def label_aabb(x, y, fs, anchor, text, ls=0.0, rot=0.0, bold=False):
    """Approximate axis-aligned bbox of a rendered text label (avg glyph
    advance + letter-spacing; rotated about its anchor). Rough but enough to
    catch labels colliding — the build-time enforcement of "no label covers
    another label or dot"."""
    cw = (0.57 if bold else 0.52) * fs
    w = len(text) * cw + max(0, len(text) - 1) * ls
    x0 = x if anchor == 'start' else (x - w if anchor == 'end' else x - w / 2)
    y0 = y - 0.74 * fs
    corners = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + fs), (x0, y0 + fs)]
    if rot:
        a = math.radians(rot); ca, sa = math.cos(a), math.sin(a)
        corners = [((cx - x) * ca - (cy - y) * sa + x,
                    (cx - x) * sa + (cy - y) * ca + y) for cx, cy in corners]
    xs = [c[0] for c in corners]; ys = [c[1] for c in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def boxes_overlap(a, b, pad=1.0):
    return not (a[2] < b[0] - pad or b[2] < a[0] - pad or
                a[3] < b[1] - pad or b[3] < a[1] - pad)


def bezier_point_angle(seg, t=0.5):
    """Position and travel angle (deg) on one cubic at parameter t — so an
    arrowhead sits ON the drawn curve and points along its tangent, not on
    the straight chord beside it."""
    p0, c1, c2, p1 = seg
    u = 1 - t
    x = u*u*u*p0[0] + 3*u*u*t*c1[0] + 3*u*t*t*c2[0] + t*t*t*p1[0]
    y = u*u*u*p0[1] + 3*u*u*t*c1[1] + 3*u*t*t*c2[1] + t*t*t*p1[1]
    dx = 3*u*u*(c1[0]-p0[0]) + 6*u*t*(c2[0]-c1[0]) + 3*t*t*(p1[0]-c2[0])
    dy = 3*u*u*(c1[1]-p0[1]) + 6*u*t*(c2[1]-c1[1]) + 3*t*t*(p1[1]-c2[1])
    return x, y, math.degrees(math.atan2(dy, dx))


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


_ring_bbox = {}      # id(ring) -> (x0, x1, y0, y1); rings live for one build


def _bbox(ring):
    b = _ring_bbox.get(id(ring))
    if b is None:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        b = (min(xs), max(xs), min(ys), max(ys))
        _ring_bbox[id(ring)] = b
    return b


def point_in_rings(pt, rings):
    """Ray-casting point-in-polygon across disjoint rings (projected px).

    The ray is cast to the RIGHT (+x), so a ring can be skipped iff it does
    not span the point's y, OR lies entirely to its left (x1 < x) — neither
    can contribute a rightward crossing. This bbox pre-filter is exact (same
    result, no ring that matters is skipped) and is the hot path's main
    speedup: a point near Greece never scans Anatolia's vertices."""
    x, y = pt
    inside = False
    for ring in rings:
        x0, x1, y0, y1 = _bbox(ring)
        if y < y0 or y > y1 or x1 < x:
            continue
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > y) != (yj > y) and \
                    x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


def arrow_at(x, y, ang, color=ROUTE, size=9.0):
    """A direction arrowhead at (x, y), rotated to ang (degrees)."""
    return (f'<path d="M{size:.0f},0 L-{size*0.45:.1f},{size*0.55:.1f} '
            f'L-{size*0.45:.1f},-{size*0.55:.1f} Z" fill="{color}" '
            f'transform="translate({x:.1f},{y:.1f}) rotate({ang:.1f})"/>')


def arrow_marker(pts, size=9.0, frac=0.5, color=ROUTE):
    """A direction arrowhead along a sampled run (frac of its length),
    aligned with travel."""
    m = max(1, min(len(pts) - 2, int(len(pts) * frac)))
    x, y = pts[m]
    tx, ty = pts[m + 1][0] - pts[m - 1][0], pts[m + 1][1] - pts[m - 1][1]
    ang = math.degrees(math.atan2(ty, tx))
    return arrow_at(x, y, ang, color, size)


def build(data_dir, out_path, mapdef=None, return_variant=True,
          no_title=False, era='ancient'):
    m = mapdef or MAPS['paul_journey_1']
    # Required (ancient) fields — a missing one should error loudly.
    BBOX = m['bbox']
    WIDTH = m['width']
    PLACES = m['places']
    WAYPOINTS = m['waypoints']
    CONTEXT_PLACES = m['context_places']
    CONTEXT_LABEL_POS = m['context_label_pos']
    ORIGIN = m['origin']
    RETRACED = m['retraced']
    # The leg (frm, to) at which the homeward half begins; from here on every
    # single-direction leg is drawn in the return hue. None => all outbound
    # (retraced corridors still split out/return by lane, see draw_chain_pair).
    RETURN_FROM = m.get('return_from')
    LEGS = m['legs']
    LABEL_POS = m['label_pos']
    SEA_LABELS = m['sea_labels']
    REGION_LABELS = m['region_labels']
    TITLE_TEXT = m['title']
    SUBTITLE_TEXT = m['subtitle']
    COASTAL = m.get('coastal', frozenset())   # places meant to sit at the shore
    # Present-day layer — optional; an ancient-only map omits it and the
    # modern build degrades gracefully (ancient names, no borders).
    MODERN_NAMES = m.get('modern_names', {})
    MODERN_CONTEXT_NAMES = m.get('modern_context_names', {})
    MODERN_LABEL_POS = m.get('modern_label_pos', {})
    MODERN_REGION_LABELS = m.get('modern_region_labels', REGION_LABELS)
    MODERN_SUBTITLE = m.get('modern_subtitle', SUBTITLE_TEXT)
    BORDER_COUNTRIES = m.get('border_countries', frozenset())
    modern = era == 'modern'

    def display(name):
        if modern:
            return MODERN_NAMES.get(name, MODERN_CONTEXT_NAMES.get(name, name))
        return name

    proj, height = make_projection(BBOX, WIDTH)
    # In-app, the imagery card already titles the map in house type — the
    # no-title build is pure content: no margins and a transparent
    # background, so nothing peeks past the rounded frame in dark mode.
    pad_top = 0 if no_title else 96
    H = int(height) if no_title else int(height) + pad_top + 24

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
                    if len(pts) > 150:
                        pts = thin_pts(pts, 1.0)
                    rings.append(pts)
                    out.append(f'<path d="{path_d(pts, close=True, dec=0)}" '
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
                    if len(pts) > 60:
                        pts = thin_pts(pts)
                    river_paths.append(
                        f'<path d="{path_d(pts, dec=0)}" fill="none" '
                        f'stroke="{RIVER}" stroke-width="1.1" '
                        f'stroke-linecap="round"/>')

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" '
               f'width="{WIDTH}" height="{H}" '
               f'viewBox="0 0 {WIDTH} {H}" font-family="{FONT}">')
    if not no_title:
        svg.append(f'<rect width="{WIDTH}" height="{H}" fill="#ffffff"/>')
        svg.append(f'<text x="{WIDTH/2}" y="44" text-anchor="middle" '
                   f'fill="{TITLE}" font-size="26" font-weight="700" '
                   f'letter-spacing="3">{TITLE_TEXT}</text>')
        svg.append(f'<text x="{WIDTH/2}" y="72" text-anchor="middle" '
                   f'fill="{SUBTITLE}" font-size="16" letter-spacing="1">'
                   f'{MODERN_SUBTITLE if modern else SUBTITLE_TEXT}</text>')

    svg.append(f'<g transform="translate(0,{pad_top})">')
    svg.append(f'<clipPath id="frame"><rect x="0" y="0" width="{WIDTH}" '
               f'height="{height:.0f}" rx="10"/></clipPath>')
    svg.append('<g clip-path="url(#frame)">')
    svg.append(f'<rect width="{WIDTH}" height="{height:.0f}" fill="{SEA}"/>')
    land_svg, land_rings = land_paths('ne_10m_land.geojson', LAND, COAST, '1.4')
    svg.extend(land_svg)
    # Relief from the terrarium DEM (loaded once): hypsometric tints for
    # altitude + a faint NW hillshade for 3-D form (Imhof). Both texture,
    # both under the route.
    elev = load_elevation_grid(os.path.join(data_dir, 'terrarium'), BBOX)
    svg.extend(relief_paths(elev, BBOX, proj))
    svg.extend(hillshade_paths(elev, BBOX, proj))
    svg.extend(river_paths)
    lake_svg, lake_rings = land_paths('ne_10m_lakes.geojson', LAKE, COAST,
                                      '1.0')
    svg.extend(lake_svg)

    # Present-day country borders — a quiet dashed hairline under the
    # labels and route (borders are context, never content)
    if modern:
        with open(os.path.join(
                data_dir, 'ne_10m_admin_0_boundary_lines_land.geojson')) as f:
            borders = json.load(f)
        for feat in borders['features']:
            p = feat['properties']
            if not {p.get('ADM0_LEFT'), p.get('ADM0_RIGHT')} <= BORDER_COUNTRIES:
                continue
            for line in geojson_lines(feat):
                for run in clip_line(line, BBOX):
                    if len(run) >= 2:
                        pts = [proj(*c) for c in run]
                        svg.append(f'<path d="{path_d(pts)}" fill="none" '
                                   f'stroke="{BORDER}" stroke-width="1.2" '
                                   f'stroke-dasharray="7 4" opacity="0.6" '
                                   f'stroke-linecap="round"/>')

    def warn_if_wet(pts, what):
        wet = sum(1 for pt in pts if point_in_rings(pt, lake_rings))
        if wet > 1:
            print(f'  ! land route {what} crosses a lake '
                  f'({wet} samples) — add a shore waypoint')

    def warn_if_sea(pts, what):
        # A land leg that dips into the SEA mid-route (e.g. a straight chord
        # cutting across a gulf head) — the terrain guarantee only clipped
        # *sea* legs against land, so this class slipped through (the
        # Antioch->Tarsus gulf crossing, found 2026-06-13). Endpoint water
        # is ignored (coastal city dots sit at the shoreline). The test is
        # the wet run's PIXEL SPAN, not sample count: a straight road
        # shaving a convex coast by a pixel or two at 10m thinned
        # resolution is invisible, not a crossing — only a visible run
        # (> ~5 px) is a real route-through-water.
        runs = []          # [is_wet, [pts]]
        for pt in pts:
            wet = not point_in_rings(pt, land_rings)
            if runs and runs[-1][0] == wet:
                runs[-1][1].append(pt)
            else:
                runs.append([wet, [pt]])
        for i, (wet, run) in enumerate(runs):
            if wet and 0 < i < len(runs) - 1:
                span = math.hypot(run[-1][0] - run[0][0],
                                  run[-1][1] - run[0][1])
                if span > 5:
                    print(f'  ! land route {what} crosses the sea '
                          f'(~{span:.0f} px) — route it round the shore')
                    return

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

    # Label-collision guard collects only the FOREGROUND haloed labels
    # (place + context) and dots: (rawname, display, bbox) and (rawname,
    # bbox). Region/sea names are a faint background layer drawn first, with
    # everything haloed on top, so they're exempt by design (standard
    # cartographic underlay) — the rule is no FOREGROUND label covers another
    # foreground label or another place's dot.
    text_boxes = []
    dot_boxes = []

    # Region + sea labels (under the route); rotation follows the land
    for text, lon, lat, rot in (MODERN_REGION_LABELS if modern
                                else REGION_LABELS):
        x, y = proj(lon, lat)
        xf = (f' transform="rotate({rot} {x:.0f} {y:.0f})"' if rot else '')
        svg.append(f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="middle" '
                   f'fill="{REGION_LABEL}" font-size="16" '
                   f'letter-spacing="4"{xf}>{text}</text>')
    for text, lon, lat, rot in SEA_LABELS:
        x, y = proj(lon, lat)
        svg.append(f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="middle" '
                   f'fill="{SEA_LABEL}" font-size="17" font-style="italic" '
                   f'font-family="{SEA_FONT}" letter-spacing="2" '
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

    # ── Dot-placement guarantee (the point-analogue of the route clip) ──────
    # A dot is render-correct iff its SIGNED clearance to the drawn coastline
    # has the right sign AND exceeds its own radius — so the whole 4.4 px
    # footprint sits on the intended side of the shore, not just the centre
    # (the Byzantium-on-the-strait class). Clearance is measured against the
    # exact thinned rings the SVG draws, so this is render-correct by
    # construction, not a coordinate check. Ports (sea-leg endpoints + the
    # `coastal` set) legitimately sit AT the waterline and only fail if a dot
    # lands well out to sea; every other land dot must clear the coast.
    def _seg_dist(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx*dx + dy*dy
        if L2 == 0:
            return math.hypot(p[0]-a[0], p[1]-a[1])
        t = max(0.0, min(1.0, ((p[0]-a[0])*dx + (p[1]-a[1])*dy) / L2))
        return math.hypot(p[0]-(a[0]+t*dx), p[1]-(a[1]+t*dy))

    def coast_clearance(pt):
        d = min(_seg_dist(pt, ring[i], ring[(i+1) % len(ring)])
                for ring in land_rings for i in range(len(ring)))
        return d if point_in_rings(pt, land_rings) else -d

    ports = {n for f, t, k, *_ in LEGS if k == 'sea' for n in (f, t)} | set(COASTAL)
    for name, (lon, lat) in {**PLACES, **CONTEXT_PLACES}.items():
        c = coast_clearance(proj(lon, lat))
        if name in ports:
            if c < -DOT_R:
                print(f'  ! port {name} sits {-c:.1f} px out to sea — '
                      f'nudge to the drawn shore')
        elif c < DOT_R:
            print(f'  ! land dot {name} clears the drawn coast by {c:.1f} px '
                  f'(< {DOT_R} px dot radius) — its footprint bleeds into '
                  f'water; nudge inland or use finer coastline data')

    def draw_land(p, q, bow, arrow, what, frac=0.5, color=ROUTE_OUT):
        c = bowed(p, q, bow) if bow else ((p[0]+q[0])/2, (p[1]+q[1])/2)
        if bow:
            d = (f'M{p[0]:.1f},{p[1]:.1f} Q{c[0]:.1f},{c[1]:.1f} '
                 f'{q[0]:.1f},{q[1]:.1f}')
        else:
            d = f'M{p[0]:.1f},{p[1]:.1f} L{q[0]:.1f},{q[1]:.1f}'
        svg.append(f'<path d="{d}" fill="none" stroke="{color}" '
                   f'stroke-width="{ROUTE_W}" stroke-linecap="round" '
                   f'opacity="0.9"/>')
        warn_if_wet(sample_quad(p, c, q), what)
        warn_if_sea(sample_quad(p, c, q), what)
        if arrow:
            arrows.append(arrow_marker(sample_quad(p, c, q), frac=frac,
                                       color=color))

    def draw_land_chain(pts, arrowed, color, what='land chain'):
        """Consecutive non-retraced land legs as ONE rounded path through
        every point (cities/waypoints are passed through exactly, only the
        bends are smoothed). `arrowed` is the set of segment indices whose
        leg asked for a direction arrowhead — placed on the curve, mid-leg."""
        svg.append(f'<path d="{smooth_path_d(pts)}" fill="none" '
                   f'stroke="{color}" stroke-width="{ROUTE_W}" '
                   f'stroke-linecap="round" stroke-linejoin="round" '
                   f'opacity="0.9"/>')
        sampled = smooth_points(pts)
        warn_if_wet(sampled, what)
        warn_if_sea(sampled, what)
        segs = catmull_rom_beziers(pts)
        for si in arrowed:
            if 0 <= si < len(segs):
                x, y, ang = bezier_point_angle(segs[si])
                arrows.append(arrow_at(x, y, ang, color))

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

    def draw_chain_pair(chain_pts):
        """A retraced road as one continuous mitered parallel pair, with
        staggered arrowheads per direction along the whole chain."""
        # Arrow count scales with the drawn chain length: two per direction
        # on a long loop (Galatia) spread out and read clearly; on a short
        # retrace (Caesarea<->Jerusalem) four 9px heads pile up on the two
        # near-touching lanes, so one per direction — at 0.66 of each
        # direction (= 0.66 and 0.34 forward), which drops the two arrows
        # into opposite halves of the leg so the out-and-back reads at a
        # glance instead of clustering mid-line.
        chain_px = sum(math.hypot(b[0] - a[0], b[1] - a[1])
                       for a, b in zip(chain_pts, chain_pts[1:]))
        fracs = (0.20, 0.60) if chain_px > 260 else (0.66,)
        # The two lanes carry the two directions: the forward offset is the
        # outbound (red), the reversed offset the homeward leg (amber).
        for pts, color in ((offset_polyline(chain_pts, 3.4), ROUTE_OUT),
                           (offset_polyline(chain_pts[::-1], 3.4),
                            ROUTE_RETURN)):
            svg.append(f'<path d="{smooth_path_d(pts)}" fill="none" '
                       f'stroke="{color}" stroke-width="{ROUTE_W}" '
                       f'stroke-linecap="round" stroke-linejoin="round" '
                       f'opacity="0.9"/>')
            # warn + arrows ride the SMOOTH curve actually drawn (sampling the
            # straight offset polyline would float the heads off the bends)
            curve = smooth_points(pts)
            warn_if_wet(curve, 'chain')
            warn_if_sea(curve, 'chain')
            for fr in fracs:
                arrows.append(arrow_marker(curve, frac=fr, color=color))

    # group consecutive retraced land legs into chains (offset out/return
    # pairs); separately, group consecutive non-retraced land legs into one
    # rounded chain so the city-to-city road bends smoothly instead of
    # snapping at every vertex.
    pending_chain = []          # retraced corridor points
    land_chain = []             # non-retraced consecutive land points
    land_arrows = []            # segment indices of arrowed legs in land_chain
    land_color = [ROUTE_OUT]    # hue of the current land_chain (mutable box)

    def flush_chain():
        if pending_chain and return_variant:
            draw_chain_pair(pending_chain.copy())
        elif pending_chain:
            for a, b in zip(pending_chain, pending_chain[1:]):
                draw_land(a, b, 0, False, 'retraced chain')
        pending_chain.clear()

    def flush_land():
        if len(land_chain) >= 2:
            draw_land_chain(land_chain.copy(), land_arrows.copy(),
                            land_color[0])
        land_chain.clear()
        land_arrows.clear()

    is_return = False
    for frm, to, kind, bow, arrow in LEGS:
        if RETURN_FROM and (frm, to) == RETURN_FROM:
            is_return = True
        color = ROUTE_RETURN if is_return else ROUTE_OUT
        p, q = proj(*coords[frm]), proj(*coords[to])
        c = bowed(p, q, bow) if bow else ((p[0]+q[0])/2, (p[1]+q[1])/2)
        if kind == 'land':
            if (frm, to) in RETRACED:
                flush_land()
                if pending_chain and pending_chain[-1] != p:
                    flush_chain()
                if not pending_chain:
                    pending_chain.append(p)
                pending_chain.append(q)
            else:
                flush_chain()
                # break the rounded chain at a gap or a hue change so out and
                # return never blend into one curve
                if land_chain and (land_chain[-1] != p
                                   or land_color[0] != color):
                    flush_land()
                if not land_chain:
                    land_chain.append(p)
                    land_color[0] = color
                land_chain.append(q)
                if arrow:   # segment just appended: pts[-2] -> pts[-1]
                    land_arrows.append(len(land_chain) - 2)
            continue
        flush_land()
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
                svg.append(f'<path d="{path_d(thin_pts(pts, 1.5))}" fill="none" '
                           f'stroke="{color}" stroke-width="{ROUTE_W}" '
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
                               f'stroke="{color}" stroke-width="{ROUTE_W}" '
                               f'stroke-linecap="round" opacity="0.9"/>')
            else:
                print(f'  ! sea leg {frm}->{to} crosses land mid-route '
                      f'({len(pts)} samples) — adjust the bow')
        if arrow and water_runs:
            arrows.append(arrow_marker(max(water_runs, key=len), color=color))
    flush_land()
    flush_chain()
    svg.extend(arrows)   # arrowheads above all route lines

    # Context cities — muted, no route: orientation anchors only
    for name, (lon, lat) in CONTEXT_PLACES.items():
        x, y = proj(lon, lat)
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.0" '
                   f'fill="#8a8f8d" stroke="#ffffff" stroke-width="1.3"/>')
        dot_boxes.append((name, (x-3, y-3, x+3, y+3)))
        dx, dy, anchor = CONTEXT_LABEL_POS.get(name, (8, -8, 'start'))
        svg.append(f'<text x="{x+dx:.0f}" y="{y+dy:.0f}" text-anchor="{anchor}" '
                   f'fill="#6b7075" font-size="15" '
                   f'paint-order="stroke" stroke="{LABEL_HALO}" '
                   f'stroke-width="3" '
                   f'stroke-linejoin="round">{display(name)}</text>')
        text_boxes.append((name, display(name),
                           label_aabb(x+dx, y+dy, 15, anchor, display(name))))

    # Places: dot + haloed label; the journey's origin gets a quiet ring
    for name, (lon, lat) in PLACES.items():
        x, y = proj(lon, lat)
        if name == ORIGIN:
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8.5" '
                       f'fill="none" stroke="{DOT}" stroke-width="1.3" '
                       f'opacity="0.7"/>')
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{DOT_R}" '
                   f'fill="{DOT}" stroke="#ffffff" stroke-width="1.6"/>')
        dot_boxes.append((name, (x-DOT_R, y-DOT_R, x+DOT_R, y+DOT_R)))
        dx, dy, anchor = LABEL_POS.get(name, (8, -8, 'start'))
        if modern and name in MODERN_LABEL_POS:
            dx, dy, anchor = MODERN_LABEL_POS[name]
        svg.append(f'<text x="{x+dx:.0f}" y="{y+dy:.0f}" text-anchor="{anchor}" '
                   f'fill="{LABEL}" font-size="17" font-weight="600" '
                   f'paint-order="stroke" stroke="{LABEL_HALO}" '
                   f'stroke-width="3.5" '
                   f'stroke-linejoin="round">{display(name)}</text>')
        text_boxes.append((name, display(name),
                           label_aabb(x+dx, y+dy, 17, anchor, display(name),
                                      bold=True)))

    # ── Label-collision guard ── no label may cover another label or another
    # place's dot; reposition via label_pos onto free sea/land space.
    for i in range(len(text_boxes)):
        ri, di_, bi = text_boxes[i]
        for j in range(i + 1, len(text_boxes)):
            rj, dj_, bj = text_boxes[j]
            if boxes_overlap(bi, bj):
                print(f'  ! label "{di_}" overlaps label "{dj_}" — '
                      f'reposition onto free space')
        for dn, db in dot_boxes:
            if dn != ri and boxes_overlap(bi, db):
                print(f'  ! label "{di_}" covers the {dn} dot — reposition')

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

    # Route legend — keyed to what THIS map actually shows: the outbound/
    # return colour key only when the journey has a return leg; the context
    # key only when there are context dots. Stacked above the scale bar in the
    # open-sea corner; haloed like the other chrome, no panel (house calm).
    has_return = bool(RETURN_FROM) or bool(RETRACED)
    rows = []
    if has_return:
        rows.append([(ROUTE_OUT, False, 'outbound'),
                     (ROUTE_RETURN, False, 'return')])
    rows.append([('#6f7479', False, 'by land'), ('#6f7479', True, 'by sea')])
    if CONTEXT_PLACES:
        rows.append([('dot', None, 'nearby town')])
    n = len(rows)
    for i, row in enumerate(rows):
        ly = by - 30 - (n - 1 - i) * 17
        cx = bx
        for color, dashed, text in row:
            if color == 'dot':
                svg.append(f'<circle cx="{cx+7}" cy="{ly-4}" r="3.4" '
                           f'fill="#8a8f8d" stroke="#ffffff" '
                           f'stroke-width="1.2"/>')
            else:
                dash = ' stroke-dasharray="2 4"' if dashed else ''
                svg.append(f'<line x1="{cx}" y1="{ly-4}" x2="{cx+22}" '
                           f'y2="{ly-4}" stroke="{color}" stroke-width="3" '
                           f'stroke-linecap="round"{dash}/>')
            svg.append(f'<text x="{cx+28}" y="{ly}" fill="#5a5f63" '
                       f'font-size="12.5" paint-order="stroke" stroke="#ffffff" '
                       f'stroke-width="3" stroke-linejoin="round">{text}</text>')
            cx += 112

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
    ap.add_argument('--map', choices=sorted(MAPS), default='paul_journey_1')
    ap.add_argument('--out', default=None,
                    help='output path (default /tmp/<map>.svg)')
    ap.add_argument('--single-retrace', action='store_true',
                    help='draw retraced roads as single calm lines instead '
                         'of the default offset out/return pair')
    ap.add_argument('--no-title', action='store_true',
                    help='omit the title block (in-app builds — the card '
                         'supplies the header)')
    ap.add_argument('--era', choices=['ancient', 'modern'], default='ancient',
                    help='label era: ancient (Bible-time, default) or '
                         'modern (present-day names + country borders)')
    args = ap.parse_args()
    out = args.out or f'/tmp/{args.map}.svg'
    build(args.data_dir, out, mapdef=MAPS[args.map],
          return_variant=not args.single_retrace,
          no_title=args.no_title, era=args.era)


if __name__ == '__main__':
    main()
