from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
pdf_path = Path(__file__).parent/"data"/"sample.pdf"

# pdf loader
loader = PyPDFLoader(str(pdf_path))
docs = loader.load()

# split the documents into chunk
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=400
)
chunks = text_splitter.split_documents(documents=docs)

# Embedding the chunks using openAI embeddings
embedding_model = OpenAIEmbeddings(
    model="text-embedding-3-large"
)

# storing
vector_store = QdrantVectorStore.from_documents(
    documents=chunks,
    embedding=embedding_model,
    url="http://localhost:6333",
    collection_name="sample"
)

print("vector store created and document embedded successfully.")
