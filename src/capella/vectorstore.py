from typing import List

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

def create_vectorstore(embedding_model: Embeddings) -> InMemoryVectorStore:
    """
    Creates an in-memory vector store using the provided embeddings model.

    Args:
        embedding_model: Embeddings model used to encode documents and queries.
    """
    try:
        vector_store = InMemoryVectorStore(
            embedding=embedding_model
        )
    except Exception as e:
        print(f"Error creating vector store: {e}")
    return vector_store


def add_documents(vectorstore: InMemoryVectorStore, documents: List[Document]) -> List[str]:
    """
    Embeds and adds a list of Documents to the vector store.

    Args:
        vectorstore: Target vector store.
        documents: Documents to store.

    Returns:
        List of document IDs assigned by the store.
    """
    ids = []
    try:
        ids = vectorstore.add_documents(documents)
    except Exception as e:
        print(f"Error adding documents: {e}")
    return ids
