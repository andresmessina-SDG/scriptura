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
ROUTE = '#c5443c'        # journey red — the one saturated voice on the map
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
        'Kition':  (33.63, 34.92),
        'Amathus': (33.14, 34.71),
        'Kourion': (32.87, 34.66),
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
        'Nisyros S':        (27.170, 36.520),
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
        'Amphipolis':         (8, 17, 'start'),
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
                      'Berea': (-10, -7, 'end')},
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
            # NB: the fast [::2] halving is safe ONLY here — relief rings are
            # closed interior contours, never bbox-clipped, so halving can't
            # drop a corner vertex and fold the ring. On coastlines (which
            # ARE clipped) use thin_pts instead; do not copy this idiom there.
            if len(pts) > 24:
                pts = pts[::2]
                if len(pts) > 24:
                    pts = thin_pts(pts, 1.2)
            d_parts.append('M' + ' L'.join(f'{x:.0f},{y:.0f}'
                                           for x, y in pts) + ' Z')
        if d_parts:
            out.append(f'<path d="{" ".join(d_parts)}" fill="{color}" '
                       f'fill-rule="evenodd"/>')
    return out


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
    # Hypsometric relief — texture for the interior, and the Taurus story
    svg.extend(relief_paths(os.path.join(data_dir, 'terrarium'), BBOX, proj))
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

    def draw_land(p, q, bow, arrow, what, frac=0.5):
        c = bowed(p, q, bow) if bow else ((p[0]+q[0])/2, (p[1]+q[1])/2)
        if bow:
            d = (f'M{p[0]:.1f},{p[1]:.1f} Q{c[0]:.1f},{c[1]:.1f} '
                 f'{q[0]:.1f},{q[1]:.1f}')
        else:
            d = f'M{p[0]:.1f},{p[1]:.1f} L{q[0]:.1f},{q[1]:.1f}'
        svg.append(f'<path d="{d}" fill="none" stroke="{ROUTE}" '
                   f'stroke-width="{ROUTE_W}" stroke-linecap="round" '
                   f'opacity="0.9"/>')
        warn_if_wet(sample_quad(p, c, q), what)
        warn_if_sea(sample_quad(p, c, q), what)
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
        for pts in (offset_polyline(chain_pts, 3.4),
                    offset_polyline(chain_pts[::-1], 3.4)):
            svg.append(f'<path d="{path_d(pts)}" fill="none" '
                       f'stroke="{ROUTE}" stroke-width="{ROUTE_W}" '
                       f'stroke-linecap="round" stroke-linejoin="round" '
                       f'opacity="0.9"/>')
            dense = densify(pts)
            warn_if_wet(dense, 'chain')
            warn_if_sea(dense, 'chain')
            for fr in fracs:
                arrows.append(arrow_marker(dense, frac=fr))

    # group consecutive retraced land legs into chains
    pending_chain = []

    def flush_chain():
        if pending_chain and return_variant:
            draw_chain_pair(pending_chain.copy())
        elif pending_chain:
            for a, b in zip(pending_chain, pending_chain[1:]):
                draw_land(a, b, 0, False, 'retraced chain')
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
                draw_land(p, q, bow, arrow, f'{frm}->{to}')
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
                svg.append(f'<path d="{path_d(thin_pts(pts, 1.5))}" fill="none" '
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
                   f'stroke-width="3" '
                   f'stroke-linejoin="round">{display(name)}</text>')

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
        if modern and name in MODERN_LABEL_POS:
            dx, dy, anchor = MODERN_LABEL_POS[name]
        svg.append(f'<text x="{x+dx:.0f}" y="{y+dy:.0f}" text-anchor="{anchor}" '
                   f'fill="{LABEL}" font-size="17" font-weight="600" '
                   f'paint-order="stroke" stroke="{LABEL_HALO}" '
                   f'stroke-width="3.5" '
                   f'stroke-linejoin="round">{display(name)}</text>')

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
