"""Knowledge-base ingestion pipeline (LlamaIndex -> ChromaDB).

Chunking strategy (as specified for this project):
  1. File-structure chunking — llama-index MarkdownNodeParser splits each
     document at its heading structure, so every chunk is one coherent
     section and carries its header path in metadata.
  2. Sentence-window suffix — for every chunk, a context window of up to W
     sentences from the neighbouring chunks (trailing sentences of the
     previous chunk, leading sentences of the next chunk) is parsed and
     appended at the END of the chunk as a "[Surrounding context]" block.

Meta-labelling: every chunk carries {"type", "source", "title", "headers",
"chunk_index", "total_chunks"}; "type" comes from the document frontmatter
(policy / membership / refund / product) and matches the metadata filter the
agent's get_document_by_hybrid_search tool applies.

Insertion: chunks are embedded and upserted into ChromaDB with deterministic
ids (sha1 of source+chunk_index), so re-running the pipeline is idempotent.

Why direct chromadb upsert instead of llama-index ChromaVectorStore: the
llama-index chroma integration is unmaintained (0.2.1, pins chromadb<0.6)
and conflicts with this project's chromadb 1.5.9; chunking/metadata still
uses llama-index-core, and the write path goes through the same chromadb
client the agent reads through.

Modes:
  --embedding mock      deterministic hash embeddings (default; no network)
  --embedding litellm   LiteLLMEmbeddings through the litellm gateway
  --chroma ephemeral    chromadb.EphemeralClient (default; no server needed)
  --chroma http         chromadb.HttpClient at --host/--port
  --dry-run             parse + chunk + report, write nothing

Run:
    python scripts/ingest_knowledge_base.py --dry-run
    python scripts/ingest_knowledge_base.py --chroma http --host localhost --port 8001
"""

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Fallback when a document has no frontmatter: filename stem -> type.
FILENAME_TYPE_MAP = {
    "store_policy": "policy",
    "membership_criteria": "membership",
    "refund_policy": "refund",
    "product_catalog": "product",
}


# --------------------------------------------------------------------------- #
# Document loading + frontmatter meta-labelling
# --------------------------------------------------------------------------- #

def parse_frontmatter(text: str):
    """Split '---\nkey: value\n---' frontmatter from the markdown body."""
    match = FRONTMATTER_RE.match(text)
    meta = {}
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
        text = text[match.end():]
    return meta, text


def load_documents(source_dir: Path):
    """Load every .md file in source_dir as a llama-index Document."""
    docs = []
    for path in sorted(source_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(raw)
        doc_type = frontmatter.get("type") or FILENAME_TYPE_MAP.get(path.stem, "policy")
        title = frontmatter.get("title") or path.stem.replace("_", " ").title()
        docs.append(Document(text=body, metadata={
            "type": doc_type,
            "source": path.name,
            "title": title,
        }))
    return docs


# --------------------------------------------------------------------------- #
# Sentence-window suffix
# --------------------------------------------------------------------------- #

def split_sentences(text: str):
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def build_context_window(sentences: list, start: int, end: int, window: int):
    """Sentences [start, end) belong to this chunk; the window pulls up to
    `window` sentences from before `start` and after `end` in the document's
    global sentence list."""
    before = [s for s in sentences[max(0, start - window):start]]
    after = [s for s in sentences[end:end + window]]
    return before, after


def locate_sentence_span(node_sentences: list, sentences: list, cursor: int):
    """Advance a cursor over the document's global sentence list to consume
    this chunk's sentences (in order). Returns (start, end). Falls back to
    the chunk's own sentence count when the match drifts."""
    start = cursor
    for offset, sentence in enumerate(node_sentences):
        probe = start + offset
        if probe < len(sentences) and sentences[probe] == sentence:
            continue
        # Drift (parser normalised whitespace): resync by scanning forward.
        try:
            resync = sentences.index(sentence, start)
            start = resync - offset
        except ValueError:
            return start, start + len(node_sentences)
    end = start + len(node_sentences)
    return start, min(end, len(sentences))


def enrich_chunks_with_windows(doc, nodes, window: int):
    """Append the sentence-window context block to the END of each chunk."""
    doc_sentences = split_sentences(doc.get_content())
    cursor = 0
    enriched = []
    for chunk_index, node in enumerate(nodes):
        node_text = node.get_content()
        node_sentences = split_sentences(node_text)
        start, end = locate_sentence_span(node_sentences, doc_sentences, cursor)
        cursor = end
        before, after = build_context_window(doc_sentences, start, end, window)

        lines = [node_text.rstrip()]
        if before or after:
            lines.append("")
            lines.append("<!--context_window-->")
            lines.append("[Surrounding context]")
            if before:
                lines.append("Before this section: " + " ".join(before))
            if after:
                lines.append("After this section: " + " ".join(after))
        enriched_text = "\n".join(lines)

        metadata = dict(node.metadata or {})
        metadata.update(doc.metadata or {})
        metadata["chunk_index"] = chunk_index
        metadata["total_chunks"] = len(nodes)
        metadata["headers"] = str(metadata.pop("header_path", "") or "")
        enriched.append((enriched_text, metadata))
    return enriched


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #

MOCK_EMBED_DIM = 1024


class MockEmbedder:
    """Deterministic token-hash bag-of-words embedding (no network)."""

    def __init__(self, dim: int = MOCK_EMBED_DIM):
        self.dim = dim

    def embed_documents(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * self.dim
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
                h = int(digest, 16)
                idx = h % self.dim
                vector[idx] += ((h >> 8) % 9 + 1) / 10.0
            norm = sum(v * v for v in vector) ** 0.5 or 1.0
            vectors.append([v / norm for v in vector])
        return vectors


def get_embedder(mode: str):
    if mode == "mock":
        return MockEmbedder()
    if mode == "litellm":
        from langchain_litellm.embeddings import LiteLLMEmbeddings
        return LiteLLMEmbeddings(
            model=os.getenv("EMBEDDING_LLM", "multilingual-e5-large"),
            api_base=os.getenv("LITELLM_API_BASE", "http://litellm:4000"),
            api_key=os.environ["LITELLM_API_KEY"],
        )
    raise ValueError(f"unknown embedding mode: {mode}")


# --------------------------------------------------------------------------- #
# Chroma insertion
# --------------------------------------------------------------------------- #

def get_collection(mode: str, host: str, port: int, name: str):
    import chromadb
    if mode == "ephemeral":
        client = chromadb.EphemeralClient()
    elif mode == "http":
        client = chromadb.HttpClient(host=host, port=port, ssl=False)
    else:
        raise ValueError(f"unknown chroma mode: {mode}")
    return client.get_or_create_collection(name=name)


def chunk_id(source: str, chunk_index: int) -> str:
    return hashlib.sha1(f"{source}|{chunk_index}".encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="knowledge_base",
                        help="Directory of markdown documents (default: knowledge_base)")
    parser.add_argument("--embedding", choices=["mock", "litellm"], default="mock")
    parser.add_argument("--chroma", choices=["ephemeral", "http"], default="ephemeral")
    parser.add_argument("--host", default=os.getenv("CHROMA_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CHROMA_PORT", "8001")))
    parser.add_argument("--collection",
                        default=os.getenv("CHROMA_COLLECTION", "table_schema_definition"))
    parser.add_argument("--window", type=int, default=2,
                        help="Sentence window size on each side (default: 2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse, chunk and report without writing to Chroma")
    args = parser.parse_args()

    source_dir = Path(args.source)
    if not source_dir.is_dir():
        print(f"ERROR: source directory not found: {source_dir}", file=sys.stderr)
        sys.exit(2)

    # 1. Load + meta-label
    docs = load_documents(source_dir)
    if not docs:
        print(f"ERROR: no .md documents found in {source_dir}", file=sys.stderr)
        sys.exit(2)
    print(f"Loaded {len(docs)} documents: "
          + ", ".join(f"{d.metadata['source']} (type={d.metadata['type']})" for d in docs))

    # 2. File-structure chunking (markdown headings)
    parser_md = MarkdownNodeParser()
    all_chunks = []  # (enriched_text, metadata)
    for doc in docs:
        nodes = parser_md.get_nodes_from_documents([doc])
        enriched = enrich_chunks_with_windows(doc, nodes, args.window)
        all_chunks.extend(enriched)
        print(f"  {doc.metadata['source']}: {len(nodes)} structural chunks")

    if not all_chunks:
        print("ERROR: chunking produced no chunks", file=sys.stderr)
        sys.exit(2)

    # 3. Report
    sizes = [len(t) for t, _ in all_chunks]
    print(f"\nTotal chunks: {len(all_chunks)}  "
          f"(size min/avg/max = {min(sizes)}/{sum(sizes)//len(sizes)}/{max(sizes)} chars)")
    types = {}
    for _, meta in all_chunks:
        types[meta.get("type", "?")] = types.get(meta.get("type", "?"), 0) + 1
    print(f"Type distribution: {types}")
    with_windows = sum(1 for t, _ in all_chunks if "<!--context_window-->" in t)
    print(f"Chunks with sentence-window suffix: {with_windows}/{len(all_chunks)}")

    sample_text, sample_meta = all_chunks[0]
    print("\nFirst chunk sample (first 400 chars):")
    print(sample_text[:400])
    print(f"... sample metadata: { {k: v for k, v in sample_meta.items()} }")

    if args.dry_run:
        print("\n[dry-run] no writes performed.")
        return

    # 4. Embed + upsert
    embedder = get_embedder(args.embedding)
    texts = [t for t, _ in all_chunks]
    print(f"\nEmbedding {len(texts)} chunks with mode={args.embedding} ...")
    vectors = embedder.embed_documents(texts)

    ids = [chunk_id(meta.get("source", "doc"), meta.get("chunk_index", i))
           for i, meta in enumerate(m for _, m in all_chunks)]

    collection = get_collection(args.chroma, args.host, args.port, args.collection)
    collection.upsert(
        ids=ids,
        documents=texts,
        metadatas=[{k: v for k, v in meta.items()} for _, meta in all_chunks],
        embeddings=vectors,
    )

    # 5. Read-back verification
    count = collection.count()
    print(f"Upserted {len(ids)} chunks; collection '{args.collection}' now holds {count} records.")
    if count < len(ids):
        print("ERROR: collection count below expectation", file=sys.stderr)
        sys.exit(1)
    one = collection.get(ids=[ids[0]], include=["metadatas", "documents"])
    got_meta = (one.get("metadatas") or [{}])[0]
    got_doc = (one.get("documents") or [""])[0]
    assert got_meta.get("type") == all_chunks[0][1]["type"], "read-back metadata mismatch"
    assert got_doc == texts[0], "read-back document mismatch"
    print(f"Read-back verification OK (id={ids[0][:12]}..., type={got_meta.get('type')}).")


if __name__ == "__main__":
    main()
