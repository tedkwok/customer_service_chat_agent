import os
from functools import lru_cache

from langchain_litellm.embeddings import LiteLLMEmbeddings
# langchain 1.x moved the classic retrievers out of langchain.retrievers:
# Ensemble/MultiQuery live in langchain_classic, BM25 in langchain_community.
from langchain_classic.retrievers import EnsembleRetriever
from langchain_classic.retrievers.multi_query import MultiQueryRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain.tools import tool
import chromadb
from app.agent.agent.llm_provider import llm


# Embeddings are served through the same litellm gateway as the chat models
# (model "multilingual-e5-large" -> vllm-embedding container).
embeddings = LiteLLMEmbeddings(
        model = os.getenv("EMBEDDING_LLM", "multilingual-e5-large"),
        api_base = os.getenv("LITELLM_API_BASE", "http://litellm:4000"),
        api_key = os.environ["LITELLM_API_KEY"]
)


# chromadb.HttpClient connects eagerly, so build the client + collection
# lazily on first tool call: importing this module (unit tests, host-run
# scripts, cold start before chroma is healthy) must not require a live
# Chroma server.
@lru_cache(maxsize=1)
def get_chroma_store() -> Chroma:
    client = chromadb.HttpClient(
                        host=os.getenv("CHROMA_HOST", "chroma"),
                        port=int(os.getenv("CHROMA_PORT", "8000")),
                        ssl=False
                    )


    return Chroma(
           collection_name = os.getenv("CHROMA_COLLECTION", "table_schema_definition"),
           embedding_function=embeddings,
           client=client
       )


@tool("get_document_by_hybrid_search")
def get_document_by_hybrid_search(enquiry:str, type:str):
    """Get the store policy or document in a precision-recall balanced way

      This tool is to search the document of store policy such as membership criteria, refund criteria with a precision-recall balanced method

      Args:
        enquiry: query to submit to the vector database for vector search
        type: type of the document which is used as meta filter to perform meta data search and then BM25 retriever using enquiry. Value of type includes membership, product, refund and policy

      Return
          status: status of execution of the tools, Success implies the successful call. Fail imples exception in the call.
          Exception_content: content of the exception thrown from the tools call if thrown
          Retrieved_result: result of the retrieved document using hybrid search
    """

    try:

        chroma_store = get_chroma_store()

        # Both halves of the ensemble must honour the type filter, otherwise
        # the vector half leaks chunks of other document types.
        vector_retriever = chroma_store.as_retriever(search_kwargs = {"k":5, "filter": {"type": type}})

        meta_filter_result = chroma_store.get(where={"type": type})
        meta_filter_docs = [
            Document(page_content=doc, metadata=meta or {})
            for doc, meta in zip(meta_filter_result.get("documents") or [],
                                 meta_filter_result.get("metadatas") or [])
        ]

        if meta_filter_docs:
            bm25_retriever = BM25Retriever.from_documents(meta_filter_docs)
            bm25_retriever.k = 5

            hybrid_retriever = EnsembleRetriever(
                retrievers=[bm25_retriever, vector_retriever],
                weights=[0.5, 0.5]
            )
        else:
            # BM25Retriever cannot be built from an empty corpus; fall back to
            # the vector half alone.
            hybrid_retriever = vector_retriever

        retrieved_result = hybrid_retriever.invoke(enquiry)

        # LangChain tools must return JSON-serialisable values; raw Document
        # objects do not survive the tool-call boundary reliably.
        serialised_result = [
            {"content": doc.page_content, "metadata": dict(doc.metadata or {})}
            for doc in retrieved_result
        ]

        print("[Agent]------Successfully retrieve the relevant document from vector database with hybrid search", flush= True)
        return ["Success", "", serialised_result]

    except Exception as e:

        error_message = f"Exception in chroma_search_by_vector:{str(e)}"
        print(error_message, flush=True)
        return ["Fail", error_message, ""]


@tool("get_document_by_query_expansion")
def get_document_by_query_expansion(enquiry:str):
    """Get the store policy or document in a high recall way

       This tool is to search the document of store policy such as membership criteria, refund criteria with a precision-recall balanced method

        Args:
          enquiry: query to submit to the vector database for vector search

        Return
          status: status of execution of the tools, Success implies the successful call. Fail imples exception in the call.
          Exception_content: content of the exception thrown from the tools call if thrown
          Retrieved_result: result of the retrieved document using hybrid search

    """

    try:
        base_retriever = get_chroma_store().as_retriever(search_kwargs={"k": 5})
        multi_query_retriever = MultiQueryRetriever.from_llm(
            retriever = base_retriever,
            llm=llm
        )
        retrieved_result = multi_query_retriever.invoke(enquiry)

        serialised_result = [
            {"content": doc.page_content, "metadata": dict(doc.metadata or {})}
            for doc in retrieved_result
        ]

        print("[Agent]------Successfully retrieve the relevant document from vector database with hybrid search", flush= True)
        return ["Success", "", serialised_result ]

    except Exception as e:

        error_message = f"Exception in chroma_search_by_vector:{str(e)}"
        print(error_message, flush=True)
        return ["Fail", error_message, ""]
