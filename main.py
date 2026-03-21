import pandas as pd
import pydeck as pdk
import json
import os

file_path = "resultados_editado.xlsx"

if not os.path.exists(file_path):
    print(f"❌ Arquivo '{file_path}' não encontrado!")
    exit()

print("🔍 Analisando as abas do Excel para encontrar os dados geográficos...")

excel_file = pd.ExcelFile(file_path)
df = None
aba_encontrada = ""

for sheet in excel_file.sheet_names:
    temp_df = pd.read_excel(file_path, sheet_name=sheet)
    temp_df.columns = temp_df.columns.astype(str).str.strip()
    if 'center_lat' in temp_df.columns and 'center_lon' in temp_df.columns:
        df = temp_df
        aba_encontrada = sheet
        break

if df is None:
    print("❌ ERRO: Não encontrei as colunas 'center_lat' e 'center_lon'.")
    exit()

print(f"✅ Dados encontrados na aba: '{aba_encontrada}'")

color_map = {
    'Grupo 0': [255, 87,  34,  200],
    'Grupo 1': [33,  150, 243, 200],
    'Grupo 2': [76,  175, 80,  200],
    'Grupo 3': [156, 39,  176, 200],
}


data = []
for _, row in df.iterrows():
    data.append({
        "center_lon":    float(row["center_lon"]),
        "center_lat":    float(row["center_lat"]),
        "color":         color_map.get(str(row["KMeans_Cluster"]).strip(), [128, 128, 128, 200]),
        "stac_id":       str(row["stac_id"]),
        "platform":      str(row["platform"]),
        "KMeans_Cluster": str(row["KMeans_Cluster"]),
    })


df['lat_r'] = df['center_lat'].round(2)
df['lon_r'] = df['center_lon'].round(2)

grupos_loc = df.groupby(['lat_r','lon_r']).agg(
    count=('stac_id','count'),
    cluster=('KMeans_Cluster', lambda x: x.mode()[0]),
    lat=('center_lat','mean'),
    lon=('center_lon','mean'),
    platforms=('platform', lambda x: ', '.join(sorted(x.unique()))),
    clusters=('KMeans_Cluster', lambda x: ', '.join(sorted(x.unique()))),
).reset_index()

color_map_hex = {
    'Grupo 0': '#FF5722',
    'Grupo 1': '#2196F3',
    'Grupo 2': '#4CAF50',
    'Grupo 3': '#9C27B0',
}

records = []
for _, row in grupos_loc.iterrows():
    records.append({
        'lat': float(row['lat']),
        'lon': float(row['lon']),
        'count': int(row['count']),
        'cluster': str(row['cluster']),
        'color': color_map_hex.get(str(row['cluster']), '#888888'),
        'platform': str(row['platforms']),
        'clusters': str(row['clusters']),
    })

max_count = max(r['count'] for r in records)
data_json = json.dumps(records)
total_locais = len(records)
total_imagens = df.shape[0]

html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Distribuição Espacial — Capella SAR</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:#0d1117; font-family:'Segoe UI',sans-serif; color:#eee; }}
    #header {{
      padding:10px 20px; background:#161b22;
      border-bottom:1px solid #30363d;
      display:flex; align-items:center; gap:16px; flex-wrap:wrap;
    }}
    #header h1 {{ font-size:16px; font-weight:600; color:#fff; }}
    .badge {{
      display:inline-flex; align-items:center; gap:5px;
      padding:3px 10px; border-radius:20px; font-size:12px;
      font-weight:500; cursor:pointer; transition:opacity .2s;
      border:2px solid transparent;
    }}
    .badge.off {{ opacity:0.3; }}
    .dot {{ width:9px; height:9px; border-radius:50%; }}
    #map {{ height:calc(100vh - 48px); }}
    #legend {{
      position:absolute; bottom:20px; right:10px; z-index:999;
      background:rgba(13,17,23,0.92); border:1px solid #30363d;
      border-radius:10px; padding:14px 18px; font-size:12px;
      backdrop-filter:blur(6px); min-width:200px;
    }}
    #legend h3 {{ font-size:11px; color:#8b949e; margin-bottom:10px; text-transform:uppercase; letter-spacing:1px; }}
    .leg-row {{ display:flex; align-items:center; gap:8px; margin:6px 0; }}
    .leg-dot {{ border-radius:50%; flex-shrink:0; }}
    .leg-label {{ color:#ccc; }}
    .leg-count {{ color:#8b949e; margin-left:auto; padding-left:8px; }}
    #size-legend {{
      position:absolute; bottom:20px; left:10px; z-index:999;
      background:rgba(13,17,23,0.92); border:1px solid #30363d;
      border-radius:10px; padding:14px 18px; font-size:12px;
      backdrop-filter:blur(6px);
    }}
    #size-legend h3 {{ font-size:11px; color:#8b949e; margin-bottom:10px; text-transform:uppercase; letter-spacing:1px; }}
    .size-row {{ display:flex; align-items:center; gap:10px; margin:6px 0; }}
    .size-circle {{ border-radius:50%; background:#aaa; flex-shrink:0; }}
    .leaflet-popup-content-wrapper {{
      background:#161b22; color:#ddd; border:1px solid #30363d;
      border-radius:8px; box-shadow:0 4px 20px rgba(0,0,0,0.6);
    }}
    .leaflet-popup-tip {{ background:#161b22; }}
    .popup-title {{ font-weight:700; font-size:14px; color:#58a6ff; margin-bottom:8px; }}
    .popup-row {{ font-size:12px; margin:4px 0; }}
    .popup-row span {{ color:#8b949e; }}
    .popup-series {{
      display:inline-block; background:#238636; color:#fff;
      border-radius:12px; padding:2px 10px; font-size:13px;
      font-weight:700; margin:6px 0;
    }}
  </style>
</head>
<body>
<div id="header">
  <h1>🛰️ Distribuição Espacial — Capella SAR</h1>
  <div id="toggles"></div>
</div>
<div id="map"></div>
<div id="size-legend">
  <h3>Séries Temporais</h3>
  <div class="size-row"><div class="size-circle" style="width:8px;height:8px"></div><span>1 imagem</span></div>
  <div class="size-row"><div class="size-circle" style="width:16px;height:16px"></div><span>~50 imagens</span></div>
  <div class="size-row"><div class="size-circle" style="width:28px;height:28px"></div><span>~150 imagens</span></div>
  <div class="size-row"><div class="size-circle" style="width:40px;height:40px"></div><span>300+ imagens</span></div>
</div>
<div id="legend">
  <h3>Clusters K-Means</h3>
  <div class="leg-row"><div class="leg-dot" style="width:12px;height:12px;background:#FF5722"></div><span class="leg-label">Grupo 0</span><span class="leg-count">Ângulo alto, largo</span></div>
  <div class="leg-row"><div class="leg-dot" style="width:12px;height:12px;background:#2196F3"></div><span class="leg-label">Grupo 1</span><span class="leg-count">Ângulo baixo, grande</span></div>
  <div class="leg-row"><div class="leg-dot" style="width:12px;height:12px;background:#4CAF50"></div><span class="leg-label">Grupo 2</span><span class="leg-count">Ângulo médio, focado</span></div>
  <div class="leg-row"><div class="leg-dot" style="width:12px;height:12px;background:#9C27B0"></div><span class="leg-label">Grupo 3</span><span class="leg-count">—</span></div>
  <hr style="border-color:#30363d;margin:10px 0"/>
  <div style="color:#8b949e;font-size:11px">{total_locais} locais · {total_imagens} imagens</div>
</div>
<script>
const DATA = {data_json};
const MAX = {max_count};
const colorMap = {json.dumps(color_map_hex)};
const map = L.map('map', {{center:[20,0], zoom:2, preferCanvas:true}});
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution:'&copy; OpenStreetMap &copy; CARTO', subdomains:'abcd', maxZoom:19
}}).addTo(map);
const layers = {{}};
const active = {{}};
const groups = [...new Set(DATA.map(d => d.cluster))].sort();
groups.forEach(g => {{ layers[g] = L.layerGroup().addTo(map); active[g] = true; }});
function getRadius(count) {{ return 6 + (count / MAX) * 34; }}
DATA.forEach(d => {{
  const circle = L.circleMarker([d.lat, d.lon], {{
    radius: getRadius(d.count),
    fillColor: d.color, color:'#fff',
    weight: d.count > 50 ? 1.5 : 0.8,
    opacity: 0.9, fillOpacity: d.count > 50 ? 0.85 : 0.6,
  }});
  circle.bindPopup(`
    <div class="popup-title">📍 ${{d.lat.toFixed(4)}}, ${{d.lon.toFixed(4)}}</div>
    <div><span class="popup-series">${{d.count}} imagens</span></div>
    <div class="popup-row"><span>Cluster:</span> ${{d.clusters}}</div>
    <div class="popup-row"><span>Plataformas:</span> ${{d.platform}}</div>
  `, {{maxWidth:300}});
  layers[d.cluster].addLayer(circle);
}});
const toggleDiv = document.getElementById('toggles');
groups.forEach(g => {{
  const badge = document.createElement('div');
  badge.className = 'badge';
  badge.style.background = colorMap[g] + '22';
  badge.style.borderColor = colorMap[g];
  badge.innerHTML = `<div class="dot" style="background:${{colorMap[g]}}"></div>${{g}}`;
  badge.onclick = () => {{
    active[g] = !active[g];
    badge.classList.toggle('off', !active[g]);
    active[g] ? map.addLayer(layers[g]) : map.removeLayer(layers[g]);
  }};
  toggleDiv.appendChild(badge);
}});
</script>
</body>
</html>"""

with open('meu_globo_3d.html', 'w', encoding='utf-8') as f:
    f.write(html)

import webbrowser, os
webbrowser.open('file://' + os.path.abspath('meu_globo_3d.html'))
print(f"🚀 SUCESSO! Arquivo criado com {total_locais} locais e {total_imagens} imagens.")