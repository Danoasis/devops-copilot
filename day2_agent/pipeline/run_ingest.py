"""CLI entrypoint: copilot-ingest [--rebuild] [--fake]"""
from __future__ import annotations

import argparse

from common.config import settings
from day2_agent.pipeline.embedding import get_embedder
from day2_agent.pipeline.index import VectorIndex
from day2_agent.pipeline.ingest import run_ingest


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest the KB into the vector index.")
    parser.add_argument("--rebuild", action="store_true",
                        help="Drop the index and re-embed everything (required after "
                             "changing the embedding model).")
    parser.add_argument("--fake", action="store_true",
                        help="Use the deterministic FakeEmbedder (tests/CI, no Ollama needed).")
    args = parser.parse_args()

    if args.rebuild and settings.db_path.exists():
        settings.db_path.unlink()
        print(f"removed {settings.db_path}")

    index = VectorIndex(settings.db_path, get_embedder(fake=args.fake))
    report = run_ingest(settings.kb_dir, index, rebuild=args.rebuild)
    print(f"[ingest] {report}")
    print(f"[index]  {index.stats()}")
    index.close()


if __name__ == "__main__":
    main()
