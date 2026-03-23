# 🛰️ capella-cluster-map

Geospatial visualization and AI-powered temporal analysis of Capella Space SAR satellite imagery metadata, combining K-Means clustering, interactive maps, academic research context, and automated geographic intelligence via OpenStreetMap and Wikipedia.

---

## 📌 Overview

This project processes a dataset of 1,582 SAR (Synthetic Aperture Radar) satellite images from Capella Space across 61 unique locations worldwide. It clusters them using K-Means, visualizes their geographic distribution, and uses Claude (via Amazon Bedrock) to generate narrative analyses of temporal series — telling the "story" of each monitored location over time, enriched with scientific papers, geographic context, and Wikipedia data.

---

## 🗂️ Project Structure

```
capella-cluster-map/
├── main.py                  # Interactive distribution map (Leaflet.js)
├── agent.py                 # AI agent for temporal series analysis
├── resultados_editado.xlsx  # Input dataset with SAR metadata and clusters
├── source/                  # PDF research papers for scientific context
│   └── *.pdf
└── output/
    ├── meu_globo_3d.html    # Interactive distribution map
    └── historias.md         # AI-generated temporal narratives + global correlation
```

---

## 🚀 Features

- **Interactive Map** — Visualizes all SAR images across global locations, with circle size proportional to the number of images (time series depth), color-coded by K-Means cluster, and toggle filters per group
- **K-Means Clustering** — Groups images by technical acquisition parameters (incidence angle, resolution, image size, platform)
- **AI Temporal Analysis** — Uses Claude via Amazon Bedrock to analyze metadata sequences and generate chronological narratives for each monitored location
- **Multi-source Context** — Enriches analysis with:
  - 📄 Academic PDFs from `source/` folder
  - 🌍 Geographic context via OpenStreetMap (Nominatim)
  - 📖 Encyclopedia context via Wikipedia Geosearch API
- **Technical Metadata Analysis** — Extracts statistics per location: capture frequency, average incidence angle, resolution, platforms used
- **Global Correlation** — Cross-analyzes all 30 locations to identify global monitoring patterns, geopolitical connections, and strategic interests

---

## 🛠️ Requirements

```bash
pip install pandas openpyxl boto3 pypdf requests
```

AWS credentials configured:
```bash
aws configure
```

---

## ⚙️ Configuration

In `agent.py`, adjust these variables:

```python
MAX_LOCAIS = 30      # Number of locations to analyze (max 30)
MIN_IMAGENS = 5      # Minimum images per location to be included
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
Group by location (61 unique sites)
    ↓
For each location:
    ├── OpenStreetMap → country, city, region name
    ├── Wikipedia → nearby articles (50km radius)
    ├── source/*.pdf → scientific context
    └── Technical stats → frequency, angle, resolution
    ↓
Claude (Amazon Bedrock) → narrative analysis per location
    ↓
Global correlation → patterns, geopolitics, strategic interests
    ↓
output/historias.md
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