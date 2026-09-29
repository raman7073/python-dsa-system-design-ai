from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

router = APIRouter(
    prefix="/query",
    tags=["query"]
)

# open ai client for generation
openai_client = OpenAI()

# Embedding the chunks using openAI embeddings
embedding_model = OpenAIEmbeddings(
    model="text-embedding-3-large"
)

# storing query
vector_db = QdrantVectorStore.from_existing_collection(
    embedding=embedding_model,
    url="http://localhost:6333",
    collection_name="sample"
)


@router.post("/")
async def query(question: str):
    search_results = vector_db.similarity_search(query=question)
    context = " ".join(
        [
            f"[Page {result.metadata.get('page','unknown')}]{result.page_content}"
            for result in search_results
        ]
    )

    SYSTEM_PROMPT = f"""
         You are a helpful assistant that answers questions based on the provided context.
         If the context does not contain the answer, respond with "I don't know."
         Also include the page number of the context in your answer if applicable.

         Context:
         {context}
      """
    response = openai_client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question}
        ]
    )
    return {"question": question, "answer": response.choices[0].message.content}
