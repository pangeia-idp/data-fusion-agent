
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

def load_document_pdf(path: str) -> Document:
    try: 
        loader = PyPDFLoader(path)
        document = loader.load()
    except Exception as e:
        print(f"Error loading PDF document: {e}")
    return document

def split_document_recursive(document: Document, chunk_size: int = 1000, chunk_overlap: int = 200) -> list[Document]:
    try:
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        chunks = text_splitter.split_documents(document)
    except Exception as e:
        print(f"Error splitting document: {e}")
    return chunks