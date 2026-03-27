import pandas as pd
import json
import boto3
import requests
from pathlib import Path

EXCEL_PATH = "resultados_editado.xlsx"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_LOCAIS = 30
MIN_IMAGENS = 5

CLASSES_POSSIVEIS = [
    "Área de Mineração",
    "Vulcão / Atividade Geológica",
    "Área Portuária",
    "Base Militar",
    "Usina de Energia",
    "Zona Urbana",
    "Agricultura / Desmatamento",
    "Costa / Oceano",
    "Outro / Indeterminado",  # fallback automático
]

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
        for item in results[:2]:  # limita a 2 artigos
            page_r = requests.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "pageids": item["pageid"],
                "prop": "extracts", "exintro": True,
                "explaintext": True, "format": "json"
            }, timeout=10)
            if page_r.status_code == 200:
                pages = page_r.json().get("query", {}).get("pages", {})
                for page in pages.values():
                    extract = page.get("extract", "")[:600]
                    if extract:
                        textos.append(f"### {item['title']}\n{extract}")
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

def classificar_local(grupo: pd.DataFrame, lat: float, lon: float) -> dict:
    """
    Retorna: {
        "classe": "Área Portuária",
        "confianca": "Alta",
        "justificativa": "...",
        "localizacao": "Santos, Brasil"
    }
    """
    bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

    contexto_geo = buscar_contexto_geo(lat, lon)
    contexto_wiki = buscar_wikipedia(lat, lon)
    tecnico = analisar_metadados_tecnicos(grupo)

    localizacao = contexto_geo.split('\n')[0].replace('Localização: ', '') if contexto_geo else f"{lat:.2f}, {lon:.2f}"

    classes_str = "\n".join(f"- {c}" for c in CLASSES_POSSIVEIS)

    prompt = f"""Você é um especialista em inteligência geoespacial e imagens de satélite SAR.

=== CONTEXTO GEOGRÁFICO (OpenStreetMap) ===
{contexto_geo if contexto_geo else 'Não disponível'}

=== CONTEXTO ENCICLOPÉDICO (Wikipedia) ===
{contexto_wiki if contexto_wiki else 'Não encontrado'}

=== METADADOS TÉCNICOS SAR ===
Coordenadas: ({lat:.4f}, {lon:.4f})
Total de imagens: {tecnico['total_imagens']}
Período monitorado: {tecnico['periodo_dias']} dias
Frequência: 1 imagem a cada {tecnico['frequencia_media_dias']:.1f} dias
Imagens/mês: {tecnico['imagens_por_mes']}
Ângulo médio de incidência: {tecnico['angulo_medio']}°
Plataformas: {', '.join(tecnico['plataformas'])}
Resolução média: {tecnico['resolucao_media']}m

=== TAREFA ===
Com base em TODOS os contextos acima, classifique este local em UMA das seguintes classes:

{classes_str}

Responda SOMENTE com um JSON válido, sem texto adicional, neste formato exato:
{{
  "classe": "<classe escolhida>",
  "confianca": "<Alta | Média | Baixa>",
  "justificativa": "<1-2 frases explicando a escolha>"
}}"""

    response = bedrock.invoke_model(
        modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}]
        })
    )
    raw = json.loads(response["body"].read())["content"][0]["text"].strip()

    # Parse seguro do JSON retornado
    try:
        # Remove possíveis blocos de código markdown
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        resultado = json.loads(raw)
        # Garante que a classe é válida
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
    """Gera análise consolidada de todos os locais de uma mesma classe."""
    bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

    resumo_locais = ""
    for loc in locais:
        resumo_locais += (
            f"\n- {loc['localizacao']} ({loc['lat']:.2f}, {loc['lon']:.2f})"
            f" | {loc['n_imagens']} imagens | {loc['data_inicio']} → {loc['data_fim']}"
            f" | Confiança: {loc['confianca']}"
            f"\n  Justificativa: {loc['justificativa']}\n"
        )

    prompt = f"""Você é um especialista em inteligência geoespacial e monitoramento por satélite SAR.

A Capella Space monitorou {len(locais)} locais classificados como: **{classe}**

Locais identificados:
{resumo_locais}

Faça uma análise consolidada respondendo:

1. **Distribuição Global** — Onde estão concentrados esses locais? Há padrão regional?
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

print(f"\n🏷️  Iniciando classificação de {min(MAX_LOCAIS, len(big_locations))} locais...\n")

locais_classificados = []

for i, ((lat, lon), grupo) in enumerate(big_locations[:MAX_LOCAIS]):
    print(f"📍 [{i+1}/{min(MAX_LOCAIS, len(big_locations))}] ({lat:.2f}, {lon:.2f}) — {len(grupo)} imagens")

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

    print(f"   ✅ Classe: {classificacao['classe']} [{classificacao['confianca']}]")

df_resultado = pd.DataFrame(locais_classificados)
csv_path = OUTPUT_DIR / "locais_classificados.csv"
df_resultado.to_csv(csv_path, index=False, encoding='utf-8')
print(f"\n💾 CSV salvo: {csv_path}")

print("\n📊 Agrupando por classe e analisando cada grupo...\n")

grupos_por_classe = {}
for loc in locais_classificados:
    cls = loc["classe"]
    grupos_por_classe.setdefault(cls, []).append(loc)

analises_por_classe = {}
for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    print(f"\n🗂️  Classe: {classe} ({len(locais)} locais)")
    analise = analisar_classe(classe, locais)
    analises_por_classe[classe] = analise
    print(f"   ✅ Análise concluída")

print("\n📄 Gerando relatório...")

md = "# 🛰️ Classificação de Locais — Capella SAR\n\n"
md += f"_{len(locais_classificados)} locais classificados em {len(grupos_por_classe)} categorias_\n\n"

# Tabela resumo
md += "## 📋 Resumo por Classe\n\n"
md += "| Classe | Nº de Locais | Total de Imagens |\n"
md += "|--------|-------------|------------------|\n"
for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    total_imgs = sum(l['n_imagens'] for l in locais)
    md += f"| {classe} | {len(locais)} | {total_imgs} |\n"
md += "\n"

# Detalhe por classe
for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    md += "---\n\n"
    md += f"## 🏷️ {classe}\n\n"
    md += f"**{len(locais)} locais identificados:**\n\n"

    for loc in sorted(locais, key=lambda x: -x['n_imagens']):
        confianca_emoji = {"Alta": "🟢", "Média": "🟡", "Baixa": "🔴"}.get(loc['confianca'], "⚪")
        md += f"### 📍 {loc['localizacao']}\n\n"
        md += f"> Coordenadas: `{loc['lat']:.4f}, {loc['lon']:.4f}`\n\n"
        md += f"- **Imagens:** {loc['n_imagens']} | **Período:** {loc['data_inicio']} → {loc['data_fim']}\n"
        md += f"- **Plataformas:** {loc['plataformas']}\n"
        md += f"- **Confiança da classificação:** {confianca_emoji} {loc['confianca']}\n"
        md += f"- **Justificativa:** {loc['justificativa']}\n\n"

    md += f"### 🔍 Análise Consolidada do Grupo\n\n"
    md += f"{analises_por_classe.get(classe, '')}\n\n"

output_path = OUTPUT_DIR / "relatorio_classificado.md"
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(md)

print(f"\n🚀 SUCESSO!")
print(f"   📄 Relatório: {output_path}")
print(f"   💾 CSV:       {csv_path}")
print(f"\n📊 Distribuição final:")
for classe, locais in sorted(grupos_por_classe.items(), key=lambda x: -len(x[1])):
    print(f"   {classe}: {len(locais)} locais")