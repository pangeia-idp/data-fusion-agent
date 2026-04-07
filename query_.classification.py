import pandas as pd
import json
import boto3
import requests
import base64
import io
import math
from pathlib import Path

EXCEL_PATH = "resultados_editado.xlsx"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_LOCAIS = 9999
AGRUPAMENTO_PRECISAO = 1

CLASSES_POSSIVEIS = [
    "Área de Mineração",
    "Vulcão / Atividade Geológica",
    "Área Portuária",
    "Base Militar",
    "Usina de Energia",
    "Zona Urbana",
    "Agricultura / Desmatamento",
    "Costa / Oceano",
    "Outro / Indeterminado",
]

CAPELLA_S3_BASE = "https://capella-open-data.s3.amazonaws.com/stac/capella-open-data-by-datetime"

CIDADES_PORTUARIAS = [
    "new york", "newark", "los angeles", "long beach", "seattle", "tacoma",
    "houston", "new orleans", "miami", "baltimore", "savannah", "charleston",
    "vancouver", "montreal", "halifax",
    "rotterdam", "antwerp", "antwerpen", "hamburg", "bremen", "barcelona",
    "valencia", "algeciras", "marseille", "genova", "genoa", "piraeus",
    "amsterdam", "felixstowe", "southampton", "le havre",
    "alicante", "alacant", "gdansk", "lisbon", "lisboa",
    "shanghai", "shenzhen", "guangzhou", "tianjin", "qingdao", "ningbo",
    "singapore", "busan", "tokyo", "yokohama", "osaka",
    "hong kong", "kaohsiung", "colombo", "mumbai", "chennai",
    "sydney", "melbourne", "brisbane", "fremantle", "adelaide",
    "dubai", "jebel ali", "abu dhabi", "jeddah", "dammam",
    "durban", "cape town", "mombasa", "lagos", "dakar",
    "santos", "paranagua", "rio de janeiro", "itajai", "buenos aires",
    "valparaiso", "callao", "guayaquil", "cartagena", "colon",
]

def _e_cidade_portuaria(address: dict) -> tuple[bool, str]:
    cidade = (address.get("city") or address.get("town") or address.get("village") or "").lower()
    estado = address.get("state", "").lower()
    pais = address.get("country", "").lower()
    texto = f"{cidade} {estado} {pais}"
    for cp in CIDADES_PORTUARIAS:
        if cp in texto:
            return True, cp.title()
    return False, ""


# ── OVERPASS: tags OSM reais num raio ──────────────────────────────────────
OSM_TAG_CLASSES = {
    "Área Portuária":           ["harbour", "port", "dock", "ferry_terminal", "container_terminal"],
    "Área de Mineração":        ["quarry", "mine", "mining"],
    "Base Militar":             ["military", "airfield", "naval_base", "barracks"],
    "Usina de Energia":         ["power_station", "power_plant", "nuclear", "solar_farm", "wind_farm", "dam"],
    "Agricultura / Desmatamento": ["farmland", "farmyard", "orchard", "vineyard", "greenhouse"],
    "Vulcão / Atividade Geológica": ["volcano"],
}

def buscar_tags_osm(lat: float, lon: float, raio_m: int = 8000) -> dict:
    tags_por_classe = {}
    try:
        filtros = []
        for classe, tags in OSM_TAG_CLASSES.items():
            for tag in tags:
                filtros.append(f'node(around:{raio_m},{lat},{lon})["{tag}"];')
                filtros.append(f'way(around:{raio_m},{lat},{lon})["{tag}"];')
                filtros.append(f'node(around:{raio_m},{lat},{lon})["landuse"="{tag}"];')
                filtros.append(f'way(around:{raio_m},{lat},{lon})["landuse"="{tag}"];')
                filtros.append(f'node(around:{raio_m},{lat},{lon})["industrial"="{tag}"];')
                filtros.append(f'way(around:{raio_m},{lat},{lon})["industrial"="{tag}"];')

        query = f"""
[out:json][timeout:8];
(
{''.join(filtros)}
);
out tags 50;
"""
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            timeout=10
        )
        if r.status_code != 200:
            return {}

        elements = r.json().get("elements", [])
        encontrados = set()
        for el in elements:
            tags = el.get("tags", {})
            for key in ["landuse", "industrial", "harbour", "military",
                        "power", "natural", "amenity"]:
                if key in tags:
                    encontrados.add(f"{key}={tags[key]}")

        for classe, keywords in OSM_TAG_CLASSES.items():
            matches = [t for t in encontrados if any(k in t for k in keywords)]
            if matches:
                tags_por_classe[classe] = matches

    except Exception:
        pass

    return tags_por_classe


# ── IMAGEM FALLBACK: OSM tile stitching ────────────────────────────────────
def _latlon_para_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y

def baixar_mapa_satelite_b64(lat: float, lon: float, zoom: int = 14) -> str | None:
    try:
        from PIL import Image

        x, y = _latlon_para_tile(lat, lon, zoom)

        tiles = []
        for dy in [-1, 0, 1]:
            row = []
            for dx in [-1, 0, 1]:
                tx, ty = x + dx, y + dy
                url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{ty}/{tx}"
                r = requests.get(url, timeout=8, headers={"User-Agent": "capella-sar-classifier"})
                if r.status_code == 200:
                    tile_img = Image.open(io.BytesIO(r.content)).convert("RGB")
                    row.append(tile_img)
                else:
                    return None
            tiles.append(row)

        tw, th = tiles[0][0].size
        combined = Image.new("RGB", (tw * 3, th * 3))
        for row_i, row in enumerate(tiles):
            for col_i, tile in enumerate(row):
                combined.paste(tile, (col_i * tw, row_i * th))

        combined.thumbnail((512, 512), Image.LANCZOS)
        buf = io.BytesIO()
        combined.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return None


# ── PREVIEW SAR ────────────────────────────────────────────────────────────
def stac_id_para_urls(stac_id: str) -> dict:
    try:
        partes = stac_id.split("_")
        data_str = partes[5]
        ano, mes, dia = data_str[0:4], data_str[4:6], data_str[6:8]
        pasta = (
            f"{CAPELLA_S3_BASE}/capella-open-data-{ano}"
            f"/capella-open-data-{ano}-{mes}"
            f"/capella-open-data-{ano}-{mes}-{dia}/{stac_id}"
        )
        return {
            "preview_candidates": [
                f"{pasta}/{stac_id}_PREVIEW.tif",
                f"{pasta}/{stac_id}_OVERVIEW.tif",
                f"{pasta}/preview.tif",
                f"{pasta}/overview.tif",
                f"{pasta}/thumbnail.png",
            ],
            "stac_json": f"{pasta}/{stac_id}.json",
            "stac_browser": (
                "https://radiantearth.github.io/stac-browser/#/external/"
                f"capella-open-data.s3.amazonaws.com/stac/capella-open-data-by-datetime"
                f"/capella-open-data-{ano}/capella-open-data-{ano}-{mes}"
                f"/capella-open-data-{ano}-{mes}-{dia}/{stac_id}/{stac_id}.json"
            ),
        }
    except Exception:
        return {"preview_candidates": [], "stac_json": None, "stac_browser": None}


def _converter_para_png_b64(content: bytes, media_type: str) -> str | None:
    try:
        from PIL import Image
        import numpy as np
        img = Image.open(io.BytesIO(content))
        if img.mode not in ("RGB", "RGBA", "L"):
            arr = np.array(img, dtype=float)
            p2, p98 = np.percentile(arr[arr > 0], [2, 98]) if arr.max() > 0 else (0, 1)
            arr = np.clip((arr - p2) / max(p98 - p2, 1e-6) * 255, 0, 255).astype("uint8")
            img = Image.fromarray(arr, mode="L")
        img.thumbnail((512, 512), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        if content[:8].startswith(b"\x89PNG"):
            return base64.b64encode(content).decode("utf-8")
        return None


def baixar_preview_sar_b64(stac_id: str) -> tuple[str | None, str | None]:
    MAX_BYTES = 5 * 1024 * 1024
    urls_info = stac_id_para_urls(stac_id)
    try:
        r = requests.get(urls_info["stac_json"], timeout=5)
        if r.status_code == 200:
            assets = r.json().get("assets", {})
            for asset in assets.values():
                if any(role in asset.get("roles", []) for role in ["overview", "thumbnail", "visual"]):
                    href = asset.get("href", "")
                    img_r = requests.get(href, timeout=8, stream=True)
                    if img_r.status_code == 200:
                        content = b""
                        for chunk in img_r.iter_content(65536):
                            content += chunk
                            if len(content) > MAX_BYTES:
                                break
                        img_r.close()
                        b64 = _converter_para_png_b64(content, asset.get("type", "image/tiff"))
                        if b64:
                            return b64, href
    except Exception:
        pass

    for url in urls_info.get("preview_candidates", []):
        try:
            r = requests.get(url, timeout=8, stream=True)
            if r.status_code == 200:
                content = b""
                for chunk in r.iter_content(65536):
                    content += chunk
                    if len(content) > MAX_BYTES:
                        break
                r.close()
                b64 = _converter_para_png_b64(content, "image/tiff" if url.endswith(".tif") else "image/png")
                if b64:
                    return b64, url
        except Exception:
            continue
    return None, None


def escolher_thumbnail_representativa(grupo: pd.DataFrame) -> tuple[str, str]:
    for tipo in ["GEO", "SLC", "GEC"]:
        sub = grupo[grupo['stac_id'].str.contains(f"_{tipo}_")]
        if not sub.empty:
            melhor = sub.loc[sub['resolution_range'].idxmin()]
            return melhor['stac_id'], stac_id_para_urls(melhor['stac_id'])["stac_browser"]
    melhor = grupo.loc[grupo['resolution_range'].idxmin()]
    return melhor['stac_id'], stac_id_para_urls(melhor['stac_id'])["stac_browser"]


# ── GEO ────────────────────────────────────────────────────────────────────
def buscar_contexto_geo(lat: float, lon: float) -> dict:
    try:
        r = requests.get(
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=14&addressdetails=1",
            headers={"User-Agent": "capella-sar-classifier"}, timeout=8
        )
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def buscar_wikipedia(lat: float, lon: float, raio_km: int = 100) -> str:
    try:
        r = requests.get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "list": "geosearch",
            "gscoord": f"{lat}|{lon}", "gsradius": raio_km * 1000,
            "gslimit": 5, "format": "json"
        }, timeout=8)
        if r.status_code != 200:
            return ""
        results = r.json().get("query", {}).get("geosearch", [])
        textos = []
        for item in results[:3]:
            pr = requests.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "pageids": item["pageid"],
                "prop": "extracts", "exintro": True, "explaintext": True, "format": "json"
            }, timeout=8)
            if pr.status_code == 200:
                for page in pr.json().get("query", {}).get("pages", {}).values():
                    extract = page.get("extract", "")[:700]
                    if extract:
                        textos.append(f"### {item['title']} (~{item.get('dist',0)/1000:.0f}km)\n{extract}")
        return "\n\n".join(textos)
    except Exception:
        return ""


def analisar_metadados_tecnicos(grupo: pd.DataFrame) -> dict:
    return {
        "total_imagens": len(grupo),
        "periodo_dias": (grupo['datetime'].max() - grupo['datetime'].min()).days,
        "frequencia_media_dias": (grupo['datetime'].max() - grupo['datetime'].min()).days / max(len(grupo) - 1, 1),
        "angulo_medio": round(grupo['incidence_angle'].mean(), 2),
        "plataformas": list(grupo['platform'].unique()),
        "clusters": list(grupo['KMeans_Cluster'].unique()),
        "resolucao_media": round(grupo['resolution_range'].mean(), 3),
        "imagens_por_mes": round(len(grupo) / max((grupo['datetime'].max() - grupo['datetime'].min()).days / 30, 1), 1),
    }


def sinais_indiretos(lat: float, lon: float, grupo: pd.DataFrame) -> dict:
    periodo = (grupo['datetime'].max() - grupo['datetime'].min()).days
    freq = periodo / max(len(grupo) - 1, 1)
    return {
        "zona_climatica": (
            "Polar/Subpolar" if abs(lat) > 60 else
            "Temperada" if abs(lat) > 35 else
            "Subtropical" if abs(lat) > 23 else "Tropical"
        ),
        "hemisferio": "Norte" if lat > 0 else "Sul",
        "proximo_equador": abs(lat) < 23,
        "costa_oeste_australia": -45 < lat < -10 and 110 < lon < 130,
        "costa_leste_australia": -45 < lat < -10 and 140 < lon < 155,
        "mediterraneo": 30 < lat < 47 and -6 < lon < 36,
        "frequencia_revisita_dias": round(freq, 1),
        "monitoramento_intensivo": freq < 3,
        "resolucao_media": round(grupo['resolution_range'].mean(), 3),
        "alta_resolucao": grupo['resolution_range'].mean() < 0.4,
        "multiplas_plataformas": len(grupo['platform'].unique()) > 1,
    }


# ── CLASSIFICAÇÃO ──────────────────────────────────────────────────────────
def classificar_local(grupo: pd.DataFrame, lat: float, lon: float) -> dict:
    bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

    geo_data = buscar_contexto_geo(lat, lon)
    endereco = geo_data.get("display_name", "Não disponível")
    address = geo_data.get("address", {})
    osm_type = geo_data.get("type", "")
    osm_class = geo_data.get("class", "")

    contexto_wiki = buscar_wikipedia(lat, lon, raio_km=100)
    tags_osm = buscar_tags_osm(lat, lon, raio_m=8000)
    tecnico = analisar_metadados_tecnicos(grupo)
    sinais = sinais_indiretos(lat, lon, grupo)
    e_porto, nome_porto = _e_cidade_portuaria(address)

    localizacao = ", ".join(filter(None, [
        address.get("city") or address.get("town") or address.get("village"),
        address.get("state"), address.get("country")
    ])) or f"{lat:.2f}, {lon:.2f}"

    stac_repr, stac_browser_url = escolher_thumbnail_representativa(grupo)
    thumb_b64, thumb_url_usada = baixar_preview_sar_b64(stac_repr)
    fonte_imagem = "SAR (Capella)"

    if not thumb_b64:
        thumb_b64 = baixar_mapa_satelite_b64(lat, lon, zoom=14)
        thumb_url_usada = f"Esri Satellite tile ({lat:.2f},{lon:.2f})"
        fonte_imagem = "Satélite Esri (fallback)"

    tem_imagem = thumb_b64 is not None

    tags_str = ""
    if tags_osm:
        for cls, tags in tags_osm.items():
            tags_str += f"\n  → {cls}: {', '.join(tags)}"
    else:
        tags_str = "\n  Nenhuma tag específica encontrada."

    classes_str = "\n".join(f"- {c}" for c in CLASSES_POSSIVEIS)

    img_desc = "não disponível"
    if tem_imagem:
        img_desc = f"INCLUÍDA ({fonte_imagem}) — analise o conteúdo visual"

    texto = f"""Você é um analista sênior de inteligência geoespacial com expertise em imagens SAR.
Classifique este local monitorado pela Capella Space usando TODOS os sinais abaixo.

════════════════════════════════════════
DADOS GEOGRÁFICOS (OpenStreetMap)
════════════════════════════════════════
Coordenadas: ({lat:.4f}, {lon:.4f})
Endereço: {endereco}
Tipo OSM: {osm_class} / {osm_type}
País: {address.get('country','N/D')} | Estado: {address.get('state','N/D')}

════════════════════════════════════════
TAGS OSM REAIS (Overpass API, raio 8km)
════════════════════════════════════════{tags_str}

════════════════════════════════════════
SINAIS INDIRETOS
════════════════════════════════════════
Zona climática: {sinais['zona_climatica']} (hemisfério {sinais['hemisferio']})
Tropical (potencial agrícola): {'SIM' if sinais['proximo_equador'] else 'NÃO'}
Costa oeste Austrália (Pilbara/mineração): {'SIM' if sinais['costa_oeste_australia'] else 'NÃO'}
Costa leste Austrália (portos/urbano): {'SIM' if sinais['costa_leste_australia'] else 'NÃO'}
Região mediterrânea: {'SIM' if sinais['mediterraneo'] else 'NÃO'}
Cidade portuária conhecida: {'⚠️ SIM — ' + nome_porto if e_porto else 'NÃO'}

════════════════════════════════════════
PADRÃO DE MONITORAMENTO SAR
════════════════════════════════════════
Total de imagens: {tecnico['total_imagens']}
Período: {tecnico['periodo_dias']} dias | Frequência: 1 imagem a cada {sinais['frequencia_revisita_dias']} dias
Monitoramento intensivo (<3 dias): {'SIM ⚠️' if sinais['monitoramento_intensivo'] else 'NÃO'}
Resolução média: {tecnico['resolucao_media']}m {'(ALTA RESOLUÇÃO)' if sinais['alta_resolucao'] else ''}
Múltiplas plataformas: {'SIM' if sinais['multiplas_plataformas'] else 'NÃO'} ({', '.join(tecnico['plataformas'])})

════════════════════════════════════════
CONTEXTO WIKIPEDIA (raio 100km)
════════════════════════════════════════
{contexto_wiki if contexto_wiki else 'Nenhum artigo encontrado.'}

════════════════════════════════════════
IMAGEM: {img_desc}
════════════════════════════════════════

REGRAS DE CLASSIFICAÇÃO (em ordem de prioridade):
1. Se tags OSM indicam uma classe específica → use essa classe
2. Se "Cidade portuária conhecida" = SIM → Área Portuária (mesmo que OSM mostre rua residencial)
3. Se a imagem mostrar estrutura clara → use o que a imagem revela
4. Use os sinais indiretos para desempatar

GUIA VISUAL:
• Área Portuária → cais, guindastes, navios, terminal de contêineres
• Agricultura / Desmatamento → talhões, campos cultivados, desmatamento em padrão geométrico
• Área de Mineração → cratera aberta, pilhas de rejeito, estradas de acesso radiais
• Base Militar → hangares, pistas, instalações isoladas com perímetro definido
• Vulcão → cratera, fluxo de lava, cone vulcânico
• Costa / Oceano → interface água/terra sem porto organizado
• Usina de Energia → estrutura de usina, painéis solares em grade, torres eólicas, barragem
• Zona Urbana → malha urbana — use APENAS quando nenhuma outra se aplica

Classes disponíveis:
{classes_str}

Responda SOMENTE com JSON válido, sem texto adicional:
{{
  "classe": "<classe escolhida>",
  "confianca": "<Alta | Média | Baixa>",
  "justificativa": "<2-3 frases descrevendo os sinais decisivos>"
}}"""

    content = []
    if tem_imagem:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": thumb_b64}
        })
    content.append({"type": "text", "text": texto})

    response = bedrock.invoke_model(
        modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 400,
            "messages": [{"role": "user", "content": content}]
        })
    )
    raw = json.loads(response["body"].read())["content"][0]["text"].strip()

    try:
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        resultado = json.loads(raw)
        if resultado.get("classe") not in CLASSES_POSSIVEIS:
            resultado["classe"] = "Outro / Indeterminado"
    except Exception:
        resultado = {"classe": "Outro / Indeterminado", "confianca": "Baixa",
                     "justificativa": "Erro ao interpretar resposta."}

    resultado["localizacao"] = localizacao
    resultado["thumbnail_url"] = thumb_url_usada or ""
    resultado["fonte_imagem"] = fonte_imagem if tem_imagem else "nenhuma"
    resultado["stac_browser_url"] = stac_browser_url or ""
    resultado["stac_id_repr"] = stac_repr
    resultado["thumbnail_carregada"] = tem_imagem
    resultado["tags_osm"] = "; ".join(f"{k}: {','.join(v)}" for k, v in tags_osm.items())
    return resultado


# ── ANÁLISE POR CLASSE ─────────────────────────────────────────────────────
def analisar_classe(classe: str, locais: list) -> str:
    bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
    resumo = ""
    for loc in locais:
        resumo += (
            f"\n- {loc['localizacao']} ({loc['lat']:.2f}, {loc['lon']:.2f})"
            f" | {loc['n_imagens']} imagens | {loc['data_inicio']} → {loc['data_fim']}"
            f"\n  {loc['justificativa']}\n"
        )
    response = bedrock.invoke_model(
        modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": f"""Especialista em inteligência geoespacial SAR.
A Capella Space monitorou {len(locais)} locais classificados como **{classe}**:
{resumo}

Análise consolidada:
1. **Distribuição Global** — Onde estão? Padrão regional?
2. **Intensidade** — Quais recebem mais atenção e por quê?
3. **Relevância Estratégica** — Por que a Capella monitora esses locais?
4. **Padrões em Comum** — O que une esses locais?
5. **Insight Principal** — Descoberta mais importante do grupo."""}]
        })
    )
    return json.loads(response["body"].read())["content"][0]["text"]


# ── PIPELINE ───────────────────────────────────────────────────────────────
print("📂 Carregando dados...")
df = pd.read_excel(EXCEL_PATH, sheet_name="Dados_Completos")
df['datetime'] = pd.to_datetime(df['datetime'])
df['lat_r'] = df['center_lat'].round(AGRUPAMENTO_PRECISAO)
df['lon_r'] = df['center_lon'].round(AGRUPAMENTO_PRECISAO)

all_locations = sorted(
    [(key, group.sort_values('datetime')) for key, group in df.groupby(['lat_r', 'lon_r'])],
    key=lambda x: -len(x[1])
)
print(f"✅ {len(all_locations)} locais únicos (agrupamento ±{10**(-AGRUPAMENTO_PRECISAO)*111:.0f}km)")

# ── NOVIDADE: carrega locais já classificados para não repetir ──────────────
csv_path = OUTPUT_DIR / "locais_classificados_v5.csv"
locais_classificados = []
ja_classificados = set()

if csv_path.exists():
    df_existente = pd.read_csv(csv_path)
    locais_classificados = df_existente.to_dict("records")
    ja_classificados = set(
        zip(df_existente['lat'].round(AGRUPAMENTO_PRECISAO),
            df_existente['lon'].round(AGRUPAMENTO_PRECISAO))
    )
    print(f"♻️  {len(ja_classificados)} locais já classificados — serão pulados\n")
else:
    print("🆕 Nenhum CSV anterior encontrado — classificando tudo do zero\n")
# ───────────────────────────────────────────────────────────────────────────

pendentes = [(key, grupo) for key, grupo in all_locations if key not in ja_classificados]
total = min(MAX_LOCAIS, len(pendentes))
print(f"🏷️  Classificando {total} locais novos...\n")

for i, ((lat, lon), grupo) in enumerate(pendentes[:MAX_LOCAIS]):
    n = len(grupo)
    print(f"📍 [{i+1}/{total}] ({lat:.1f}, {lon:.1f}) — {n} imagens", end="", flush=True)

    resultado = classificar_local(grupo, lat, lon)

    icons = {"SAR (Capella)": "🛰️", "Satélite Esri (fallback)": "🗺️", "nenhuma": "📊"}
    flag = icons.get(resultado["fonte_imagem"], "📊")
    print(f" {flag} → {resultado['classe']} [{resultado['confianca']}]")

    locais_classificados.append({
        "lat": lat, "lon": lon,
        "localizacao": resultado["localizacao"],
        "classe": resultado["classe"],
        "confianca": resultado["confianca"],
        "justificativa": resultado["justificativa"],
        "n_imagens": n,
        "data_inicio": str(grupo['datetime'].min().date()),
        "data_fim": str(grupo['datetime'].max().date()),
        "plataformas": ', '.join(grupo['platform'].unique()),
        "thumbnail_url": resultado["thumbnail_url"],
        "fonte_imagem": resultado["fonte_imagem"],
        "stac_browser_url": resultado["stac_browser_url"],
        "stac_id_repr": resultado["stac_id_repr"],
        "thumbnail_carregada": resultado["thumbnail_carregada"],
        "tags_osm": resultado["tags_osm"],
    })

    # ── NOVIDADE: salva o CSV a cada local para não perder progresso ────────
    pd.DataFrame(locais_classificados).to_csv(csv_path, index=False, encoding='utf-8')
    # ────────────────────────────────────────────────────────────────────────

print(f"\n💾 CSV: {csv_path}")

print("\n📊 Analisando por classe...\n")
grupos_por_classe = {}
for loc in locais_classificados:
    grupos_por_classe.setdefault(loc["classe"], []).append(loc)

analises_por_classe = {}
for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    print(f"🗂️  {classe}: {len(locais)} locais", end="", flush=True)
    analises_por_classe[classe] = analisar_classe(classe, locais)
    print(" ✅")

md = "# 🛰️ Classificação de Locais — Capella SAR (v5)\n\n"
md += f"_{len(locais_classificados)} locais · {len(grupos_por_classe)} categorias_\n\n"

md += "## 📋 Resumo por Classe\n\n"
md += "| Classe | Locais | Imagens | Fonte Imagem | Alta Confiança |\n"
md += "|--------|--------|---------|--------------|----------------|\n"
for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    total_imgs = sum(l['n_imagens'] for l in locais)
    sar = sum(1 for l in locais if l['fonte_imagem'] == 'SAR (Capella)')
    esri = sum(1 for l in locais if l['fonte_imagem'] == 'Satélite Esri (fallback)')
    alta = sum(1 for l in locais if l['confianca'] == 'Alta')
    md += f"| {classe} | {len(locais)} | {total_imgs} | 🛰️{sar} 🗺️{esri} | {alta}/{len(locais)} |\n"
md += "\n"

for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    md += "---\n\n"
    md += f"## 🏷️ {classe}\n\n"
    for loc in sorted(locais, key=lambda x: -x['n_imagens']):
        emoji_conf = {"Alta": "🟢", "Média": "🟡", "Baixa": "🔴"}.get(loc['confianca'], "⚪")
        emoji_img = {"SAR (Capella)": "🛰️", "Satélite Esri (fallback)": "🗺️"}.get(loc['fonte_imagem'], "📊")
        md += f"### 📍 {loc['localizacao']}\n\n"
        md += f"> `{loc['lat']:.2f}, {loc['lon']:.2f}`\n\n"
        md += f"- **Imagens:** {loc['n_imagens']} | **Período:** {loc['data_inicio']} → {loc['data_fim']}\n"
        md += f"- **Plataformas:** {loc['plataformas']}\n"
        md += f"- **Confiança:** {emoji_conf} {loc['confianca']} {emoji_img}\n"
        md += f"- **Justificativa:** {loc['justificativa']}\n"
        if loc['tags_osm']:
            md += f"- **Tags OSM:** `{loc['tags_osm']}`\n"
        if loc['thumbnail_url']:
            md += f"- **Preview:** [{loc['stac_id_repr']}]({loc['thumbnail_url']})\n"
        if loc['stac_browser_url']:
            md += f"- **STAC Browser:** [Ver imagem completa]({loc['stac_browser_url']})\n"
        md += "\n"
    md += f"### 🔍 Análise Consolidada\n\n{analises_por_classe.get(classe, '')}\n\n"

output_path = OUTPUT_DIR / "relatorio_classificado_v5.md"
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(md)

sar_count = sum(1 for l in locais_classificados if l['fonte_imagem'] == 'SAR (Capella)')
esri_count = sum(1 for l in locais_classificados if l['fonte_imagem'] == 'Satélite Esri (fallback)')
print(f"\n🚀 SUCESSO!")
print(f"   📄 {output_path}")
print(f"   💾 {csv_path}")
print(f"   🛰️  {sar_count} com preview SAR | 🗺️ {esri_count} com satélite Esri")
print(f"\n📊 Distribuição:")
for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    print(f"   {classe:<35} {len(locais):>3} locais")