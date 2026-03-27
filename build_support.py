"""
build_support.py
Lê locais_classificados_v5.csv, baixa as thumbnails SAR da Capella via S3
e organiza no formato do autolabeler:

    support/
    ├── mineracao/
    │   └── CAPELLA_xxx.png
    ├── porto/
    └── ...
"""

import os
import requests
import pandas as pd
from pathlib import Path

CSV_PATH   = Path("output/locais_classificados_v5.csv")
OUTPUT_DIR = Path("output/support")

CLASS_MAP = {
    "Área de Mineração":             "mineracao",
    "Zona Urbana":                   "urbano",
    "Agricultura / Desmatamento":    "agricultura",
    "Base Militar":                  "militar",
    "Costa / Oceano":                "costa",
    "Vulcão / Atividade Geológica":  "vulcao",
    "Área Portuária":                "porto",
    "Outro / Indeterminado":         "outro",
}

def stac_json_url(stac_browser_url: str) -> str:
    """Converte URL do STAC Browser para URL direta do S3."""
    return "https://" + stac_browser_url.split("#/external/")[1]

def get_thumbnail_url(stac_json_url: str) -> str | None:
    """Busca o asset 'thumbnail' no JSON do STAC."""
    r = requests.get(stac_json_url, timeout=15)
    r.raise_for_status()
    assets = r.json().get("assets", {})
    if "thumbnail" in assets:
        return assets["thumbnail"]["href"]
    # fallback: qualquer asset com role thumbnail
    for asset in assets.values():
        if "thumbnail" in asset.get("roles", []):
            return asset["href"]
    return None

def download_image(url: str, dest: Path) -> bool:
    """Baixa imagem e salva em dest. Retorna True se ok."""
    r = requests.get(url, timeout=30)
    if r.status_code == 200 and len(r.content) > 0:
        dest.write_bytes(r.content)
        return True
    return False

def main():
    df = pd.read_csv(CSV_PATH)

    ok, fail = 0, 0

    for _, row in df.iterrows():
        classe_raw  = row["classe"]
        stac_id     = row["stac_id_repr"]
        browser_url = row["stac_browser_url"]

        classe_folder = CLASS_MAP.get(classe_raw)
        if classe_folder is None:
            print(f"[SKIP] Classe desconhecida: {classe_raw}")
            continue

        dest_dir = OUTPUT_DIR / classe_folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"{stac_id}.png"

        if dest_file.exists():
            print(f"[SKIP] Já existe: {dest_file}")
            ok += 1
            continue

        try:
            json_url  = stac_json_url(browser_url)
            thumb_url = get_thumbnail_url(json_url)

            if thumb_url is None:
                print(f"[FAIL] Sem thumbnail no STAC: {stac_id}")
                fail += 1
                continue

            if download_image(thumb_url, dest_file):
                print(f"[OK]   {classe_folder}/{stac_id}.png")
                ok += 1
            else:
                print(f"[FAIL] Download falhou: {thumb_url}")
                fail += 1

        except Exception as e:
            print(f"[ERRO] {stac_id}: {e}")
            fail += 1

    print(f"\nConcluído: {ok} ok | {fail} falhas")
    print(f"\nEstrutura gerada em: {OUTPUT_DIR.resolve()}")
    for d in sorted(OUTPUT_DIR.iterdir()):
        imgs = list(d.glob("*.png"))
        print(f"  {d.name}/  ({len(imgs)} imagens)")

if __name__ == "__main__":
    main()
