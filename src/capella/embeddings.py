from typing import List

from langchain.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings

def load_embeddings_model(model_name: str, **model_kwargs) -> OllamaEmbeddings:
    try:
        model = OllamaEmbeddings(model=model_name, **model_kwargs)
    except Exception as e:
        print(f"Error loading embeddings model: {e}")
    return model

def generate_document_embeddings(model: Embeddings, documents: List[str]) -> List[List[float]]:
    try:
        embeddings = model.embed_documents(documents)
    except Exception as e:
        print(f"Error generating document embeddings: {e}")
    return embeddings

def generate_embeddings(model: Embeddings, query: str) -> List[float]:
    try:
        embedding = model.embed_query(query)
    except Exception as e:
        print(f"Error generating query embedding: {e}")
    return embedding
