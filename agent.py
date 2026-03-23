import pandas as pd
import json
import boto3
import pypdf
import requests
from pathlib import Path

EXCEL_PATH = "resultados_editado.xlsx"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
PDFS_DIR = Path("source")

MAX_LOCAIS = 30
MIN_IMAGENS = 5

print("📂 Carregando dados...")
df = pd.read_excel(EXCEL_PATH, sheet_name="Dados_Completos")
df['datetime'] = pd.to_datetime(df['datetime'])
df['lat_r'] = df['center_lat'].round(2)
df['lon_r'] = df['center_lon'].round(2)

series = df.groupby(['lat_r', 'lon_r'])
big_locations = [
    (key, group.sort_values('datetime'))
    for key, group in series
    if len(group) >= MIN_IMAGENS
]
big_locations.sort(key=lambda x: -len(x[1]))
print(f"✅ {len(big_locations)} locais com {MIN_IMAGENS}+ imagens encontrados")

# ================================
# LER TODOS OS PDFs DA PASTA SOURCE
# ================================
def carregar_todos_pdfs() -> str:
    if not PDFS_DIR.exists():
        print("  ⚠️ Pasta 'source' não encontrada")
        return ""
    pdfs = list(PDFS_DIR.glob("*.pdf"))
    if not pdfs:
        print("  ⚠️ Nenhum PDF encontrado em 'source/'")
        return ""
    texto_total = ""
    for pdf in pdfs:
        print(f"  📄 Lendo: {pdf.name}")
        try:
            reader = pypdf.PdfReader(str(pdf))
            texto = ""
            for page in reader.pages:
                texto += page.extract_text() or ""
                if len(texto) >= 5000:
                    break
            if texto:
                texto_total += f"\n\n=== {pdf.stem} ===\n{texto[:5000]}"
        except Exception as e:
            print(f"  ⚠️ Erro ao ler {pdf.name}: {e}")
    print(f"  ✅ {len(pdfs)} PDFs carregados")
    return texto_total[:20000]

# ================================
# CONTEXTO GEOGRÁFICO (OpenStreetMap)
# ================================
def buscar_contexto_geo(lat: float, lon: float) -> str:
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        r = requests.get(url, headers={"User-Agent": "capella-cluster-map"}, timeout=10)
        if r.status_code != 200:
            return ""
        data = r.json()
        address = data.get("address", {})
        partes = []
        for campo in ["city", "town", "village", "county", "state", "country"]:
            if campo in address:
                partes.append(address[campo])
        return f"Localização: {', '.join(partes)}\nEndereço: {data.get('display_name', '')}"
    except Exception:
        return ""

# ================================
# CONTEXTO WIKIPEDIA
# ================================
def buscar_wikipedia(lat: float, lon: float) -> str:
    try:
        params = {
            "action": "query", "list": "geosearch",
            "gscoord": f"{lat}|{lon}", "gsradius": 50000,
            "gslimit": 3, "format": "json"
        }
        r = requests.get("https://en.wikipedia.org/w/api.php", params=params, timeout=10)
        if r.status_code != 200:
            return ""
        results = r.json().get("query", {}).get("geosearch", [])
        if not results:
            return ""
        textos = []
        for item in results:
            page_r = requests.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "pageids": item["pageid"],
                "prop": "extracts", "exintro": True,
                "explaintext": True, "format": "json"
            }, timeout=10)
            if page_r.status_code == 200:
                pages = page_r.json().get("query", {}).get("pages", {})
                for page in pages.values():
                    extract = page.get("extract", "")[:800]
                    if extract:
                        textos.append(f"### {item['title']}\n{extract}")
        return "\n\n".join(textos)
    except Exception:
        return ""

# ================================
# ANÁLISE TÉCNICA DOS METADADOS
# ================================
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
        "modos": list(grupo['instrument_mode'].unique()),
        "resolucao_media": round(grupo['resolution_range'].mean(), 3),
        "imagens_por_mes": round(len(grupo) / max((grupo['datetime'].max() - grupo['datetime'].min()).days / 30, 1), 1),
    }

# ================================
# ANÁLISE PRINCIPAL COM BEDROCK
# ================================
def analisar_com_bedrock(grupo: pd.DataFrame, lat: float, lon: float, contexto_pdfs: str) -> str:
    bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

    print(f"  🌍 Buscando contexto geográfico...")
    contexto_geo = buscar_contexto_geo(lat, lon)

    print(f"  📖 Buscando Wikipedia...")
    contexto_wiki = buscar_wikipedia(lat, lon)

    tecnico = analisar_metadados_tecnicos(grupo)

    metadados_str = ""
    for _, row in grupo.iterrows():
        metadados_str += f"- {row['datetime'].strftime('%Y-%m-%d')} | {row['platform']} | {row['KMeans_Cluster']} | ângulo: {row['incidence_angle']}° | resolução: {row['resolution_range']}m\n"

    content = []
    
    content.append({
        "type": "text",
        "text": f"""Você é um especialista em inteligência geoespacial e imagens de satélite SAR (Synthetic Aperture Radar).

=== CONTEXTO GEOGRÁFICO (OpenStreetMap) ===
{contexto_geo}

=== CONTEXTO ENCICLOPÉDICO (Wikipedia) ===
{contexto_wiki if contexto_wiki else 'Não encontrado'}

=== CONTEXTO CIENTÍFICO (Pesquisas Acadêmicas) ===
{contexto_pdfs if contexto_pdfs else 'Não disponível'}"""
    })

    content.append({
        "type": "text",
        "text": f"""=== ANÁLISE TÉCNICA DOS METADADOS ===
Local: ({lat:.4f}, {lon:.4f})
Total de imagens: {tecnico['total_imagens']}
Período monitorado: {tecnico['periodo_dias']} dias
Frequência média: 1 imagem a cada {tecnico['frequencia_media_dias']:.1f} dias
Imagens por mês: {tecnico['imagens_por_mes']}
Ângulo de incidência: {tecnico['angulo_medio']}° (min: {tecnico['angulo_min']}°, max: {tecnico['angulo_max']}°)
Plataformas usadas: {', '.join(tecnico['plataformas'])}
Clusters K-Means: {', '.join(tecnico['clusters'])}
Resolução média: {tecnico['resolucao_media']}m

Sequência completa de capturas:
{metadados_str}

=== PERGUNTA ===
Com base em TODOS os contextos acima (geográfico, enciclopédico, científico e técnico), analise:

1. **Identificação do Local** — O que é esse lugar? Por que é estratégico?
2. **Análise Técnica** — O que os metadados revelam sobre como e quando foi monitorado?
3. **Correlação com Pesquisas** — Como os PDFs científicos explicam o interesse nesse local?
4. **História Temporal** — Conte a narrativa cronológica do monitoramento
5. **Classificação** — Tipo: PONTUAL / CONTÍNUO / SAZONAL / INTENSIVO
6. **Hipótese** — Por que a Capella Space monitora esse local com essa intensidade?"""
    })

    response = bedrock.invoke_model(
        modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": content}]
        })
    )
    return json.loads(response["body"].read())["content"][0]["text"]

# ================================
# CORRELAÇÃO GLOBAL
# ================================
def correlacionar_regioes(historias: list) -> str:
    bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

    resumos = ""
    for h in historias:
        resumos += f"\n### ({h['lat']:.2f}, {h['lon']:.2f}) — {h['localizacao']}\n"
        resumos += f"- {h['n_imagens']} imagens | {h['data_inicio']} → {h['data_fim']}\n"
        resumos += f"- {h['analise'][:400]}...\n"

    response = bedrock.invoke_model(
        modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 3000,
            "messages": [{
                "role": "user",
                "content": f"""Você é um especialista em inteligência geoespacial global.

Abaixo estão análises de {len(historias)} regiões monitoradas pela Capella Space com imagens SAR:

{resumos}

Faça uma análise de correlação global respondendo:
1. **Padrões Globais** — Quais padrões em comum existem entre essas regiões?
2. **Estratégia de Observação** — O que a seleção dessas regiões revela sobre os objetivos da Capella?
3. **Conexões Geopolíticas** — Existe relação geopolítica, econômica ou ambiental entre os locais?
4. **Setores de Interesse** — Mineração? Portos? Infraestrutura militar? Mudanças climáticas?
5. **Região Mais Crítica** — Qual local apresenta o monitoramento mais intenso e por quê?
6. **Narrativa Global** — Conte a história completa do que esses dados revelam sobre o mundo"""
            }]
        })
    )
    return json.loads(response["body"].read())["content"][0]["text"]

# ================================
# CARREGAR PDFs UMA VEZ SÓ
# ================================
print("\n📚 Carregando PDFs da pasta source/...")
contexto_pdfs = carregar_todos_pdfs()

# ================================
# PROCESSAR TODOS OS LOCAIS
# ================================
historias = []

for i, ((lat, lon), grupo) in enumerate(big_locations[:MAX_LOCAIS]):
    print(f"\n{'='*50}")
    print(f"📍 Local {i+1}/{min(MAX_LOCAIS, len(big_locations))}: ({lat:.2f}, {lon:.2f})")
    print(f"   {len(grupo)} imagens | {grupo['datetime'].min().date()} → {grupo['datetime'].max().date()}")

    localizacao = buscar_contexto_geo(lat, lon).split('\n')[0].replace('Localização: ', '')

    print(f"  🤖 Analisando com Claude via Bedrock...")
    analise = analisar_com_bedrock(grupo, lat, lon, contexto_pdfs)

    historias.append({
        'lat': lat, 'lon': lon,
        'localizacao': localizacao,
        'n_imagens': len(grupo),
        'data_inicio': str(grupo['datetime'].min().date()),
        'data_fim': str(grupo['datetime'].max().date()),
        'plataformas': ', '.join(grupo['platform'].unique()),
        'analise': analise,
    })
    print("  ✅ Análise concluída!")

print("\n🔗 Correlacionando todas as regiões...")
correlacao = correlacionar_regioes(historias)
print("✅ Correlação concluída!")

# ================================
# GERAR RELATÓRIO MARKDOWN
# ================================
print(f"\n📄 Gerando relatório com {len(historias)} histórias...")

output_path = OUTPUT_DIR / "historias.md"

md = "# 🛰️ Histórias das Séries Temporais — Capella SAR\n\n"
md += f"_{len(historias)} locais analisados_\n\n"

for h in historias:
    md += "---\n\n"
    md += f"## 📍 {h['localizacao']}\n\n"
    md += f"> Coordenadas: {h['lat']:.4f}, {h['lon']:.4f}\n\n"
    md += f"- **Imagens:** {h['n_imagens']}\n"
    md += f"- **Período:** {h['data_inicio']} → {h['data_fim']}\n"
    md += f"- **Plataformas:** {h['plataformas']}\n\n"
    md += f"### Análise\n\n"
    md += f"{h['analise']}\n\n"

md += "---\n\n"
md += "## 🔗 Correlação Global entre Regiões\n\n"
md += f"{correlacao}\n\n"

with open(output_path, 'w', encoding='utf-8') as f:
    f.write(md)

print(f"🚀 SUCESSO! Relatório salvo em '{output_path}'")