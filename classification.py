import pandas as pd
import json
import boto3
import requests
import math
from pathlib import Path

EXCEL_PATH = "resultados_editado.xlsx"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# Sem mínimo de imagens — analisa TODOS os locais
MIN_IMAGENS = 1
MAX_LOCAIS = 9999  # sem limite prático

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

print("📂 Carregando dados...")
df = pd.read_excel(EXCEL_PATH, sheet_name="Dados_Completos")
df['datetime'] = pd.to_datetime(df['datetime'])
df['lat_r'] = df['center_lat'].round(2)
df['lon_r'] = df['center_lon'].round(2)

series = df.groupby(['lat_r', 'lon_r'])
all_locations = [
    (key, group.sort_values('datetime'))
    for key, group in series
    if len(group) >= MIN_IMAGENS
]
all_locations.sort(key=lambda x: -len(x[1]))
print(f"✅ {len(all_locations)} locais encontrados (todos os grupos)")

def buscar_contexto_geo(lat: float, lon: float) -> dict:
    """Retorna endereço + tags OSM do ponto."""
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=14&addressdetails=1"
        r = requests.get(url, headers={"User-Agent": "capella-sar-classifier"}, timeout=10)
        if r.status_code != 200:
            return {}
        return r.json()
    except Exception:
        return {}


def distancia_ao_litoral_km(lat: float, lon: float) -> float:
    """
    Estimativa simples: busca o ponto de costa mais próximo via Nominatim
    pesquisando 'coastline' ou 'sea' nos arredores. Alternativa leve sem API extra.
    Usa heurística: se o Nominatim retornar 'sea', 'bay', 'harbour' etc. no endereço
    a distância é ~0. Caso contrário, tenta estimar pelo tipo de área.
    """
    try:
        # Busca em raios crescentes por corpo d'água
        for radius in [2000, 10000, 30000]:
            url = (
                f"https://nominatim.openstreetmap.org/reverse"
                f"?lat={lat}&lon={lon}&format=json&zoom=10"
            )
            r = requests.get(url, headers={"User-Agent": "capella-sar-classifier"}, timeout=8)
            if r.status_code != 200:
                break
            data = r.json()
            tipo = data.get("type", "") + " " + data.get("class", "")
            nome = data.get("display_name", "").lower()
            if any(w in nome for w in ["sea", "ocean", "bay", "harbor", "harbour",
                                        "port", "strait", "gulf", "coast", "marina"]):
                return radius / 1000.0
        return 999.0
    except Exception:
        return 999.0


def buscar_wikipedia(lat: float, lon: float, raio_km: int = 100) -> str:
    try:
        params = {
            "action": "query", "list": "geosearch",
            "gscoord": f"{lat}|{lon}",
            "gsradius": raio_km * 1000,
            "gslimit": 5, "format": "json"
        }
        r = requests.get("https://en.wikipedia.org/w/api.php", params=params, timeout=10)
        if r.status_code != 200:
            return ""
        results = r.json().get("query", {}).get("geosearch", [])
        if not results:
            return ""
        textos = []
        for item in results[:3]:
            page_r = requests.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "pageids": item["pageid"],
                "prop": "extracts", "exintro": True,
                "explaintext": True, "format": "json"
            }, timeout=10)
            if page_r.status_code == 200:
                pages = page_r.json().get("query", {}).get("pages", {})
                for page in pages.values():
                    extract = page.get("extract", "")[:700]
                    if extract:
                        dist = item.get("dist", 0)
                        textos.append(f"### {item['title']} (~{dist/1000:.0f}km)\n{extract}")
        return "\n\n".join(textos)
    except Exception:
        return ""


def sinais_indiretos(lat: float, lon: float, grupo: pd.DataFrame) -> dict:
    """
    Extrai sinais geoespaciais indiretos que ajudam na classificação:
    - Hemisfério / zona climática
    - Proximidade ao equador (trópicos → agricultura)
    - Latitude absoluta alta → polar/subpolar
    - Padrão de revisita (muito frequente → monitoramento ativo)
    - Resolução (altíssima resolução → alvo estratégico pontual)
    - Variação de ângulo (variação alta → múltiplos satélites = interesse crítico)
    """
    periodo = (grupo['datetime'].max() - grupo['datetime'].min()).days
    n = len(grupo)
    freq = periodo / max(n - 1, 1)
    angulo_var = grupo['incidence_angle'].std() if n > 1 else 0

    sinais = {
        "lat_abs": abs(lat),
        "hemisferio": "Norte" if lat > 0 else "Sul",
        "zona_climatica": (
            "Polar/Subpolar" if abs(lat) > 60 else
            "Temperada" if abs(lat) > 35 else
            "Subtropical" if abs(lat) > 23 else
            "Tropical"
        ),
        "proximo_equador": abs(lat) < 23,
        "costa_leste_australia": -45 < lat < -10 and 140 < lon < 155,
        "costa_oeste_australia": -45 < lat < -10 and 110 < lon < 130,
        "mediterraneo": 30 < lat < 47 and -6 < lon < 36,
        "pacifico_norte": lat > 30 and lon < -100,
        "interior_continente": abs(lon) < 60 or (80 < abs(lon) < 140),
        "frequencia_revisita_dias": round(freq, 1),
        "monitoramento_intensivo": freq < 3,       # menos de 3 dias entre imagens
        "monitoramento_esporadico": freq > 30,
        "resolucao_media": round(grupo['resolution_range'].mean(), 3),
        "alta_resolucao": grupo['resolution_range'].mean() < 0.4,
        "variacao_angulo": round(angulo_var, 2),
        "multiplas_plataformas": len(grupo['platform'].unique()) > 1,
        "n_imagens": n,
        "periodo_dias": periodo,
    }
    return sinais


def analisar_metadados_tecnicos(grupo: pd.DataFrame) -> dict:
    return {
        "total_imagens": len(grupo),
        "periodo_dias": (grupo['datetime'].max() - grupo['datetime'].min()).days,
        "frequencia_media_dias": (grupo['datetime'].max() - grupo['datetime'].min()).days / max(len(grupo) - 1, 1),
        "angulo_medio": round(grupo['incidence_angle'].mean(), 2),
        "angulo_min": round(grupo['incidence_angle'].min(), 2),
        "angulo_max": round(grupo['incidence_angle'].max(), 2),
        "plataformas": list(grupo['platform'].unique()),
        "clusters": list(grupo['KMeans_Cluster'].unique()),
        "resolucao_media": round(grupo['resolution_range'].mean(), 3),
        "imagens_por_mes": round(len(grupo) / max((grupo['datetime'].max() - grupo['datetime'].min()).days / 30, 1), 1),
    }



def classificar_local(grupo: pd.DataFrame, lat: float, lon: float) -> dict:
    bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

    geo_data = buscar_contexto_geo(lat, lon)
    endereco = geo_data.get("display_name", "Não disponível")
    osm_type = geo_data.get("type", "")
    osm_class = geo_data.get("class", "")
    address = geo_data.get("address", {})

    contexto_wiki = buscar_wikipedia(lat, lon, raio_km=100)
    tecnico = analisar_metadados_tecnicos(grupo)
    sinais = sinais_indiretos(lat, lon, grupo)

    localizacao = ", ".join(filter(None, [
        address.get("city") or address.get("town") or address.get("village"),
        address.get("state"),
        address.get("country")
    ])) or f"{lat:.2f}, {lon:.2f}"

    classes_str = "\n".join(f"- {c}" for c in CLASSES_POSSIVEIS)

    prompt = f"""Você é um analista sênior de inteligência geoespacial com expertise em imagens SAR e uso do solo.

Sua tarefa é classificar um local monitorado pela Capella Space. Use TODOS os sinais disponíveis,
especialmente os sinais indiretos — eles são tão importantes quanto o endereço textual.

════════════════════════════════════════
DADOS GEOGRÁFICOS (OpenStreetMap)
════════════════════════════════════════
Coordenadas: ({lat:.4f}, {lon:.4f})
Endereço: {endereco}
Tipo OSM: {osm_class} / {osm_type}
País/Região: {address.get('country', 'N/D')} | Estado: {address.get('state', 'N/D')}

════════════════════════════════════════
SINAIS INDIRETOS (ANÁLISE GEOESPACIAL)
════════════════════════════════════════
Zona climática: {sinais['zona_climatica']} (lat {sinais['lat_abs']:.1f}°, hemisfério {sinais['hemisferio']})
Região tropical (potencial agrícola): {'SIM' if sinais['proximo_equador'] else 'NÃO'}
Costa leste da Austrália: {'SIM' if sinais['costa_leste_australia'] else 'NÃO'}
Costa oeste da Austrália (Pilbara/mineração): {'SIM' if sinais['costa_oeste_australia'] else 'NÃO'}
Região mediterrânea (Portugal/Espanha/Norte África): {'SIM' if sinais['mediterraneo'] else 'NÃO'}
Pacífico Norte (EUA/Japão/bases): {'SIM' if sinais['pacifico_norte'] else 'NÃO'}

════════════════════════════════════════
PADRÃO DE MONITORAMENTO SAR
════════════════════════════════════════
Total de imagens: {tecnico['total_imagens']}
Período monitorado: {tecnico['periodo_dias']} dias
Frequência média: 1 imagem a cada {sinais['frequencia_revisita_dias']} dias
Imagens/mês: {tecnico['imagens_por_mes']}
Monitoramento intensivo (<3 dias entre imagens): {'SIM ⚠️' if sinais['monitoramento_intensivo'] else 'NÃO'}
Monitoramento esporádico (>30 dias): {'SIM' if sinais['monitoramento_esporadico'] else 'NÃO'}
Resolução média: {tecnico['resolucao_media']}m {'(ALTA RESOLUÇÃO ⚠️)' if sinais['alta_resolucao'] else ''}
Variação do ângulo de incidência: {sinais['variacao_angulo']}° {'(alta variação = múltiplos satélites)' if sinais['variacao_angulo'] > 5 else ''}
Múltiplas plataformas: {'SIM' if sinais['multiplas_plataformas'] else 'NÃO'} ({', '.join(tecnico['plataformas'])})
Clusters K-Means: {', '.join(tecnico['clusters'])}

════════════════════════════════════════
CONTEXTO ENCICLOPÉDICO (Wikipedia, raio 100km)
════════════════════════════════════════
{contexto_wiki if contexto_wiki else 'Nenhum artigo encontrado no raio de 100km.'}

════════════════════════════════════════
GUIA DE CLASSIFICAÇÃO — SINAIS CHAVE
════════════════════════════════════════
Use estas pistas para decidir:

• Área Portuária → endereço menciona "port", "harbour", "dock", "terminal", "pier", "cais",
  OU coordenadas estão em cidade costeira + osm_type contém "harbour/port/industrial",
  OU Wikipedia menciona porto/terminal marítimo no raio de 100km

• Agricultura / Desmatamento → zona tropical ou subtropical, interior continental,
  endereço menciona "farm", "rural", "fazenda", "agricultura", "campo",
  OU Wikipedia menciona produção agrícola, agronegócio, desmatamento

• Área de Mineração → endereço menciona "mine", "mina", "quarry", "pedreira", "mineral",
  OU região conhecida por mineração (Pilbara AU, Minas Gerais BR, etc.),
  OU Wikipedia menciona operação de mineração no raio

• Base Militar → endereço menciona "base", "air force", "naval", "military", "fort",
  OU monitoramento muito intensivo em área aparentemente não-urbana

• Vulcão → coordenadas em área vulcânica conhecida, Wikipedia menciona vulcão/lava/erupção

• Costa / Oceano → coordenadas na beira do mar mas SEM evidência de porto organizado;
  pode ser praia, estuário, mangue, costa aberta

• Usina de Energia → endereço ou Wikipedia menciona "power plant", "usina", "dam", "barragem",
  "nuclear", "solar farm", "wind farm"

• Zona Urbana → apenas quando NÃO há evidência de nenhuma das categorias acima

════════════════════════════════════════
TAREFA
════════════════════════════════════════
Classifique este local em UMA das seguintes classes:
{classes_str}

IMPORTANTE:
- Prefira classes específicas (Mineração, Porto, Agrícola, Militar) a "Zona Urbana" ou "Outro"
- Use os sinais indiretos quando o endereço for ambíguo
- Se a cidade é costeira E o OSM type indica área industrial/portuária, prefira "Área Portuária"
- Se a região é tropical/subtropical com interior continental, considere "Agricultura / Desmatamento"

Responda SOMENTE com JSON válido, sem texto adicional:
{{
  "classe": "<classe escolhida>",
  "confianca": "<Alta | Média | Baixa>",
  "justificativa": "<2-3 frases explicando os sinais que levaram à decisão>"
}}"""

    response = bedrock.invoke_model(
        modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}]
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
        resultado = {
            "classe": "Outro / Indeterminado",
            "confianca": "Baixa",
            "justificativa": "Erro ao interpretar resposta do modelo."
        }

    resultado["localizacao"] = localizacao
    return resultado



def analisar_classe(classe: str, locais: list) -> str:
    bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

    resumo_locais = ""
    for loc in locais:
        resumo_locais += (
            f"\n- {loc['localizacao']} ({loc['lat']:.2f}, {loc['lon']:.2f})"
            f" | {loc['n_imagens']} imagens | {loc['data_inicio']} → {loc['data_fim']}"
            f" | Confiança: {loc['confianca']}"
            f"\n  {loc['justificativa']}\n"
        )

    prompt = f"""Você é um especialista em inteligência geoespacial e monitoramento por satélite SAR.

A Capella Space monitorou {len(locais)} locais classificados como: **{classe}**

Locais identificados:
{resumo_locais}

Faça uma análise consolidada respondendo:
1. **Distribuição Global** — Onde estão concentrados? Há padrão regional?
2. **Intensidade de Monitoramento** — Quais locais recebem mais atenção e por quê?
3. **Relevância Estratégica** — Por que a Capella monitora locais desse tipo?
4. **Padrões em Comum** — O que une esses locais além da classe?
5. **Insight Principal** — Qual é a descoberta mais importante deste grupo?"""

    response = bedrock.invoke_model(
        modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}]
        })
    )
    return json.loads(response["body"].read())["content"][0]["text"]



total = min(MAX_LOCAIS, len(all_locations))
print(f"\n🏷️  Classificando {total} locais (sem filtro mínimo de imagens)...\n")

locais_classificados = []

for i, ((lat, lon), grupo) in enumerate(all_locations[:MAX_LOCAIS]):
    print(f"📍 [{i+1}/{total}] ({lat:.2f}, {lon:.2f}) — {len(grupo)} imagens", end="")

    classificacao = classificar_local(grupo, lat, lon)

    locais_classificados.append({
        "lat": lat,
        "lon": lon,
        "localizacao": classificacao["localizacao"],
        "classe": classificacao["classe"],
        "confianca": classificacao["confianca"],
        "justificativa": classificacao["justificativa"],
        "n_imagens": len(grupo),
        "data_inicio": str(grupo['datetime'].min().date()),
        "data_fim": str(grupo['datetime'].max().date()),
        "plataformas": ', '.join(grupo['platform'].unique()),
    })

    print(f" → {classificacao['classe']} [{classificacao['confianca']}]")


df_resultado = pd.DataFrame(locais_classificados)
csv_path = OUTPUT_DIR / "locais_classificados_v2.csv"
df_resultado.to_csv(csv_path, index=False, encoding='utf-8')
print(f"\n💾 CSV salvo: {csv_path}")


print("\n📊 Agrupando e analisando por classe...\n")

grupos_por_classe = {}
for loc in locais_classificados:
    grupos_por_classe.setdefault(loc["classe"], []).append(loc)

analises_por_classe = {}
for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    print(f"🗂️  {classe}: {len(locais)} locais", end="")
    analise = analisar_classe(classe, locais)
    analises_por_classe[classe] = analise
    print(" ✅")
md = "# 🛰️ Classificação de Locais — Capella SAR (v2)\n\n"
md += f"_{len(locais_classificados)} locais classificados em {len(grupos_por_classe)} categorias_\n\n"

md += "## 📋 Resumo por Classe\n\n"
md += "| Classe | Nº Locais | Total Imagens | Confiança Alta |\n"
md += "|--------|-----------|---------------|----------------|\n"
for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    total_imgs = sum(l['n_imagens'] for l in locais)
    alta = sum(1 for l in locais if l['confianca'] == 'Alta')
    md += f"| {classe} | {len(locais)} | {total_imgs} | {alta}/{len(locais)} |\n"
md += "\n"

for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    md += "---\n\n"
    md += f"## 🏷️ {classe}\n\n"

    for loc in sorted(locais, key=lambda x: -x['n_imagens']):
        emoji = {"Alta": "🟢", "Média": "🟡", "Baixa": "🔴"}.get(loc['confianca'], "⚪")
        md += f"### 📍 {loc['localizacao']}\n\n"
        md += f"> `{loc['lat']:.4f}, {loc['lon']:.4f}`\n\n"
        md += f"- **Imagens:** {loc['n_imagens']} | **Período:** {loc['data_inicio']} → {loc['data_fim']}\n"
        md += f"- **Plataformas:** {loc['plataformas']}\n"
        md += f"- **Confiança:** {emoji} {loc['confianca']}\n"
        md += f"- **Justificativa:** {loc['justificativa']}\n\n"

    md += f"### 🔍 Análise Consolidada\n\n{analises_por_classe.get(classe, '')}\n\n"

output_path = OUTPUT_DIR / "relatorio_classificado_v2.md"
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(md)

print(f"\n🚀 SUCESSO!")
print(f"   📄 Relatório: {output_path}")
print(f"   💾 CSV:       {csv_path}")
print(f"\n📊 Distribuição final:")
for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    total_imgs = sum(l['n_imagens'] for l in locais)
    print(f"   {classe:<35} {len(locais):>3} locais | {total_imgs:>5} imagens")