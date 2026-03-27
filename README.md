# 🛰️ capella-cluster-map

Geospatial visualization and AI-powered temporal analysis of Capella Space SAR satellite imagery metadata, combining K-Means clustering, interactive maps, academic research context, and automated geographic intelligence via OpenStreetMap and Wikipedia.

---

## 📌 Overview

This project processes a dataset of 1,582 SAR (Synthetic Aperture Radar) satellite images from Capella Space across 61 unique locations worldwide. It clusters them using K-Means, visualizes their geographic distribution, and uses Claude (via Amazon Bedrock) to generate narrative analyses of temporal series — telling the "story" of each monitored location over time, enriched with scientific papers, geographic context, and Wikipedia data.

A classification module automatically assigns each location to a land-use category (port, mine, military base, volcano, etc.) using multi-source geospatial intelligence and visual analysis of SAR/satellite imagery.

---

## 🗂️ Project Structure

```
capella-cluster-map/
├── main.py                      # Interactive distribution map (Leaflet.js)
├── agent.py                     # AI agent for temporal series analysis
├── classification.py            # AI-powered location classification by land-use type
├── resultados_editado.xlsx      # Input dataset with SAR metadata and clusters
├── source/                      # PDF research papers for scientific context
│   └── *.pdf
└── output/
    ├── meu_globo_3d.html                # Interactive distribution map
    ├── historias.md                     # AI-generated temporal narratives
    ├── locais_classificados_v5.csv      # Classification results per location
    └── relatorio_classificado_v5.md     # Full classification report by category
```

---

## 🚀 Features

- **Interactive Map** — Visualizes all SAR images across global locations, with circle size proportional to the number of images (time series depth), color-coded by K-Means cluster, and toggle filters per group
- **K-Means Clustering** — Groups images by technical acquisition parameters (incidence angle, resolution, image size, platform)
- **AI Temporal Analysis** — Uses Claude via Amazon Bedrock to analyze metadata sequences and generate chronological narratives for each monitored location
- **AI Land-Use Classification** — Automatically classifies each location into categories (port, mine, military, volcano, etc.) using layered geospatial signals and visual image analysis
- **Multi-source Context** — Enriches analysis with:
  - 📄 Academic PDFs from `source/` folder
  - 🌍 Geographic context via OpenStreetMap (Nominatim)
  - 🏷️ Real OSM land-use tags via Overpass API (8km radius)
  - 📖 Encyclopedia context via Wikipedia Geosearch API (100km radius)
  - 🛰️ SAR preview images from Capella's open S3 bucket
  - 🗺️ Esri World Imagery satellite tiles as visual fallback
- **Technical Metadata Analysis** — Extracts statistics per location: capture frequency, average incidence angle, resolution, platforms used
- **Global Correlation** — Cross-analyzes all locations to identify global monitoring patterns, geopolitical connections, and strategic interests

---

## 🛠️ Requirements

```bash
pip install pandas openpyxl boto3 pypdf requests pillow numpy
```

AWS credentials configured:
```bash
aws configure
```

---

## ⚙️ Configuration

In `agent.py`:

```python
MAX_LOCAIS = 30      # Number of locations to analyze (max 30)
MIN_IMAGENS = 5      # Minimum images per location to be included
```

In `classification.py`:

```python
MAX_LOCAIS = 9999           # Analyze all locations (no limit)
AGRUPAMENTO_PRECISAO = 1    # Geographic grouping precision (~11km radius)
```

---

## 🗺️ Running the Map

```bash
python3 main.py
```

Opens `output/meu_globo_3d.html` in the browser — an interactive dark-theme map showing:
- Circle size = number of images (time series depth)
- Color = K-Means cluster
- Click any point to see platforms, clusters, and image count
- Toggle clusters on/off via the top buttons

---

## 🤖 Running the AI Agent

```bash
python3 agent.py
```

The agent will:
1. Load the Excel dataset and group images by geographic location
2. Load all PDFs from `source/` as scientific context (loaded once, reused for all locations)
3. For each location:
   - Fetch geographic name via OpenStreetMap
   - Fetch nearby Wikipedia articles (radius: 50km)
   - Compute technical statistics from metadata
   - Send everything to Claude via Amazon Bedrock
4. After all locations: generate a global correlation analysis
5. Save the full report at `output/historias.md`

**Estimated runtime:** ~20-30 minutes for 30 locations

---

## 🏷️ Running the Classification

```bash
python3 classification.py
```

Automatically classifies every monitored location into one of 9 land-use categories using a multi-layer AI pipeline:

### Classification Categories

| Class | Examples |
|-------|---------|
| Área de Mineração | Open-pit mines, quarries, tailings piles |
| Vulcão / Atividade Geológica | Active volcanoes, lava flows, calderas |
| Área Portuária | Container terminals, docks, harbours |
| Base Militar | Airfields, naval bases, restricted facilities |
| Usina de Energia | Power plants, solar farms, wind farms, dams |
| Zona Urbana | Dense urban areas (used only when no other class applies) |
| Agricultura / Desmatamento | Farmland, cropfields, deforestation patterns |
| Costa / Oceano | Coastlines without organised port infrastructure |
| Outro / Indeterminado | Fallback for ambiguous locations |

### Classification Pipeline

```
For each location:
    ├── Nominatim (OSM)     → textual address of the point
    ├── Overpass API        → real OSM land-use tags within 8km radius
    │                         (landuse=port, industrial=mine, military=airfield…)
    ├── Known port cities   → hardcoded list of ~60 major port cities worldwide
    ├── Wikipedia           → encyclopedic context within 100km radius
    ├── SAR preview image   → downloaded from Capella's open S3 bucket
    │   └── fallback        → Esri World Imagery satellite tile (no API key needed)
    └── Claude (Bedrock)    → classifies using all signals + visual image analysis
```

### Classification Priority Rules

1. **Overpass OSM tags** — if real tags indicate a specific class, use it
2. **Known port city** — if the location matches a known port city, classify as Área Portuária regardless of OSM address
3. **Visual image** — SAR or satellite image confirms land use
4. **Indirect signals** — climate zone, Australia regions, Mediterranean, revisit frequency

### Outputs

| File | Description |
|------|-------------|
| `output/locais_classificados_v5.csv` | Table with all locations, classes, confidence, links |
| `output/relatorio_classificado_v5.md` | Full markdown report grouped by category |

The report includes for each location:
- Classification with confidence level (🟢 Alta / 🟡 Média / 🔴 Baixa)
- Image source (🛰️ SAR Capella / 🗺️ Esri satellite / 📊 metadata only)
- OSM tags found by Overpass
- Direct link to SAR preview file
- Link to STAC Browser for full image and metadata

**Estimated runtime:** ~14-15 minutes for 43 locations

---

## 📊 Dataset

The input file `resultados_editado.xlsx` contains SAR metadata from Capella Space with the following key columns:

| Column | Description |
|--------|-------------|
| `stac_id` | Unique image identifier |
| `platform` | Satellite (capella-5 through capella-14) |
| `datetime` | Acquisition timestamp |
| `center_lat/lon` | Geographic coordinates |
| `instrument_mode` | Capture mode (spotlight) |
| `incidence_angle` | Radar look angle |
| `resolution_range` | Range resolution in meters |
| `KMeans_Cluster` | Assigned cluster (Grupo 0–2) |
| `DBSCAN_Cluster` | Secondary clustering result |

---

## 🔍 Cluster Interpretation

| Cluster | Incidence Angle | Image Size | Main Platform | Interpretation |
|---------|----------------|------------|---------------|----------------|
| **Grupo 0** | ~44° (high) | Wide (8600px) | capella-13 | Lateral panoramic — urban/coastal |
| **Grupo 1** | ~36° (low) | Large (7500px) | Older satellites | Wide-area coverage — agriculture/mining |
| **Grupo 2** | ~39° (medium) | Small/square (5200px) | Mixed | Focused target — ports, facilities |

---

## 🌍 Key Monitored Locations

| Location | Images | Coordinates |
|----------|--------|-------------|
| Hawaii (Big Island) | 376 | 19.42, -155.29 |
| Los Angeles, California | 214 | 34.83, -118.07 |
| Pilbara, Australia | 200 | -23.18, 118.77 |
| San Jose, California | 176 | 37.32, -121.87 |
| Newman, Australia | 124 | -21.75, 122.24 |

---

## 🤖 AI Pipeline

```
Excel (1,582 SAR metadata records)
    ↓
Group by location (43 unique sites, ~11km radius grouping)
    ↓
┌─────────────────────────────────────┐   ┌──────────────────────────────────────┐
│         agent.py                    │   │         classification.py             │
│                                     │   │                                      │
│  For each location:                 │   │  For each location:                  │
│  ├── OpenStreetMap → address        │   │  ├── OpenStreetMap → address         │
│  ├── Wikipedia → nearby articles    │   │  ├── Overpass API → OSM tags (8km)   │
│  ├── source/*.pdf → sci. context    │   │  ├── Wikipedia → articles (100km)    │
│  └── Technical stats               │   │  ├── Known port cities list          │
│      ↓                              │   │  ├── SAR preview (Capella S3)        │
│  Claude → narrative per location    │   │  │   └── fallback: Esri satellite    │
│      ↓                              │   │  └── Claude → class + confidence     │
│  Claude → global correlation        │   │      ↓                               │
│      ↓                              │   │  Group by class → consolidated       │
│  output/historias.md                │   │  analysis per category               │
└─────────────────────────────────────┘   │      ↓                               │
                                          │  output/relatorio_classificado_v5.md │
                                          └──────────────────────────────────────┘
```

---

## ☁️ AWS Setup

This project uses **Amazon Bedrock** with Claude Sonnet 4:

```python
modelId = "us.anthropic.claude-sonnet-4-20250514-v1:0"
```

Make sure your IAM user has `bedrock:InvokeModel` permissions for `us-east-1`.

---

## 📄 Adding Research Papers

Place any `.pdf` files in the `source/` folder before running the agent:

```bash
mv your_paper.pdf source/
python3 agent.py
```

The agent reads all PDFs automatically and uses them as scientific context for every location analysis.

---

## 📄 License

MIT