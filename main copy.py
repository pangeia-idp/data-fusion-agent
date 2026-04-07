import os
import sys
import json
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.cluster import DBSCAN

load_dotenv()

from langchain.tools import tool
from langchain_core.messages import HumanMessage

from src.capella.chat import load_chat_model, load_agent
from src.capella.embeddings import load_embeddings_model
from src.capella.utils.clustering import identify_sequences, spatial_clustering, summarize_sequences
from src.capella.utils.geocoding import get_geocoding_context
from src.capella.vectorstore import create_vectorstore, add_documents
from src.capella.utils.utils import load_document_pdf, split_document_recursive
from src.capella.utils.tools import download_capella_assets, search_wikipedia


CSV_PATH = "data/dataset/raw/20260403_capella_ieee_datacontest_2026_v01.csv"
MODEL_ID = "claude-haiku-4-5-20251001"
EMBEDDINGS_MODEL = "nomic-embed-text"

PDF_PATHS = [
    "data/context/Data Fusion Contest - Espanha e Estados Unidos.pdf",
    "data/context/Pesquisa Vulcânica Havaí_ Dados SAR.pdf",
    "data/context/Pesquisa Austrália_ Mineração e Infraestrutura.pdf",
]

SYSTEM_PROMPT = """You are an expert in SAR (Synthetic Aperture Radar) remote sensing and geospatial analysis.
You have been given metadata for multiple temporal acquisition sequences from a Capella Space SAR dataset,
organized by geographic region (state/province/territory).

Your task is to produce a comprehensive Markdown report structured by region. The report must follow this hierarchy:

# Regional Report

For each region (state/province/territory):

## [Region Name], [Country]
- Brief geographic and thematic overview of the region
- Why this region is relevant for SAR monitoring (call `search_vectorstore` for domain context)
- Call `search_wikipedia` for encyclopedic context about the region

### [Location Name 1]
- Sequence IDs covering this location
- Temporal coverage: date range, number of acquisitions, average revisit interval
- Imaging parameters: orbital plane, orbit state, observation direction, incidence angle stats
- Platforms used
- Call `download_capella_assets` for two representative STAC IDs
- Potential applications (change detection, disaster monitoring, infrastructure mapping, etc.)

### [Location Name 2]
...repeat for each location in the region...

## [Next Region], [Country]
...repeat...

# Cross-Regional Summary
- Total sequences analyzed, total acquisitions, overall temporal span
- Common imaging configurations across regions
- Comparative analysis: which regions have the densest temporal coverage
- Recommended priorities for further analysis

Guidelines:
- Group sequences that share the same location name into a single subsection.
- Use `search_vectorstore` at the region level to find relevant domain knowledge.
- Use `search_wikipedia` once per region for geographic context.
- Use `download_capella_assets` for a few representative STAC IDs per location, not every acquisition.
- Keep individual location analyses concise; focus depth at the regional level.
- Structure the final output as clean, well-formatted Markdown.
"""

def main():
    # Load metadata and identify sequences
    df = pd.read_csv(CSV_PATH)

    # Parse datetime
    df["datetime_parsed"] = pd.to_datetime(df["datetime"], utc=True)

    # Drop duplicate collect_id
    df = df.drop_duplicates(subset=["collect_id"], keep="first")

    # Apply spatial clustering
    eps_km = 5.0
    min_samples = 1
    coords_rad = np.radians(df[["center_lat", "center_lon"]].values)
    df["spatial_cluster"] = spatial_clustering(coords_rad, eps_km=eps_km, min_samples=min_samples)

    # Identify sequences
    df_seq = identify_sequences(df)

    # Summarize sequences
    df_seq_summary = summarize_sequences(df_seq)
    
    # Get geocoding context for each sequence
    for idx, row in df_seq_summary.iterrows():
        coords = (row["center_lat_mean"], row["center_lon_mean"])
        geocoding_info = get_geocoding_context(coords)

        for key, value in geocoding_info.items():
            df_seq_summary.at[idx, key] = value

        print(f"Processed sequence {row['sequence_id']} ({idx + 1}/{len(df_seq_summary)})")
        print(f"  Location: {geocoding_info.get('name', 'Unknown')}, {geocoding_info.get('country', '')}")
    
    # Transform the enriched summary into a string for potential use in prompts or reports
    drop_cols = ["incidence_angle_std", "n_platforms"] # Drop less relevant columns for the report
    df_seq_summary_str = df_seq_summary.drop(columns=drop_cols, errors="ignore").to_string()
    print(df_seq_summary_str)

    # Instantiate chat model
    model = load_chat_model(model=MODEL_ID, max_tokens=16384)

    # Instantiate embeddings model
    embeddings = load_embeddings_model(model_name=EMBEDDINGS_MODEL)

    # Instantiate vectorstore and populate with PDF context documents
    vectorstore = create_vectorstore(embedding_model=embeddings)
    for path in PDF_PATHS:
        document = load_document_pdf(path)
        chunks = split_document_recursive(document)
        add_documents(vectorstore, chunks)

    # Vectorstore retrieval tool
    @tool
    def search_vectorstore(query: str, k: int = 3) -> str:
        """
        Searches the reference document vectorstore for relevant context.
        Use this to find domain knowledge about locations, SAR imaging techniques,
        or any topic related to the dataset.

        Args:
            query: Natural language search query
            k: Number of document chunks to retrieve (default: 3)
        """
        docs = vectorstore.similarity_search(query, k=k)
        results = [
            {"content": doc.page_content, "source": doc.metadata.get("source", "unknown")}
            for doc in docs
        ]
        return json.dumps(results, ensure_ascii=False, indent=2)

    tools = [download_capella_assets, search_wikipedia, search_vectorstore]

    # Instantiate agent
    agent = load_agent(model=model, tools=tools, system_prompt=SYSTEM_PROMPT)

    # User prompt for making a report over the summarized sequence information
    user_message = f"""Here is the enriched sequence summary for the entire Capella SAR dataset:
    {df_seq_summary_str}

    Please generate a regional report grouped by state/region. For each region:
    1. Provide a brief geographic overview using `search_wikipedia`
    2. Search the vectorstore for relevant domain context with `search_vectorstore`
    3. Analyze each location within that region (temporal coverage, imaging parameters, potential applications)
    5. End with a cross-regional summary comparing coverage density and recommending priorities for further analysis.
    """

    # Run agent
    result = agent.invoke({"messages": [HumanMessage(content=user_message)]})

    # Extract the final assistant message
    final_message = result["messages"][-1].content

    # Save Report
    os.makedirs("reports", exist_ok=True)
    report_path = "reports/capella_regional_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(final_message)

    print(f"Report saved to {report_path}")
    
if __name__ == "__main__":
    main()