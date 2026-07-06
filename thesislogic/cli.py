"""ThesisLogic command-line interface.

    thesislogic serve                          run the gateway + UI
    thesislogic pack list                      show installed jurisdiction packs
    thesislogic pack scaffold <id> --name --jurisdiction
    thesislogic pack build <id> [--source authorities.ndjson] [--limit N]
    thesislogic pack embed <id>                add semantic vectors (needs embedding provider)
    thesislogic user add <user_id>             create a user (prompts for password)
    thesislogic doctor                         check providers, packs, OCR tooling
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from .config import get_settings


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    settings = get_settings()
    uvicorn.run("thesislogic.server:app", host=args.host or settings.host,
                port=args.port or settings.port, log_level="info")
    return 0


def cmd_pack_list(_: argparse.Namespace) -> int:
    from .packs import list_packs
    settings = get_settings()
    packs = list_packs(settings.packs_dir)
    if not packs:
        print(f"no packs found in {settings.packs_dir}")
        return 1
    for pack in packs:
        print(json.dumps(pack))
    return 0


def cmd_pack_scaffold(args: argparse.Namespace) -> int:
    from .packs import scaffold_pack
    settings = get_settings()
    path = scaffold_pack(settings.packs_dir, args.pack_id, args.name or args.pack_id,
                         args.jurisdiction or args.pack_id)
    print(f"created pack scaffold at {path}")
    print("next: replace authorities.sample.ndjson with authorities.ndjson, then run:")
    print(f"  thesislogic pack build {args.pack_id}")
    return 0


def cmd_pack_build(args: argparse.Namespace) -> int:
    from .packs import build_index, load_pack
    settings = get_settings()
    pack = load_pack(settings.packs_dir, args.pack_id)
    source = Path(args.source) if args.source else None
    stats = build_index(pack, source=source, limit=args.limit)
    print(json.dumps(stats, indent=2))
    return 0


def cmd_pack_embed(args: argparse.Namespace) -> int:
    from .packs import load_pack
    from .providers import build_embedding_provider
    settings = get_settings()
    embedder = build_embedding_provider(settings)
    if embedder is None:
        print("no embedding provider configured (THESISLOGIC_EMBEDDING_PROVIDER)")
        return 1
    pack = load_pack(settings.packs_dir, args.pack_id)
    db = pack.db()
    rows = db.execute(
        "SELECT a.authority_id, a.citation, a.title, a.text_excerpt FROM authorities a "
        "LEFT JOIN embeddings e ON e.authority_id = a.authority_id "
        "WHERE e.authority_id IS NULL").fetchall()
    print(f"embedding {len(rows)} authorities...")
    batch: list = []
    done = 0
    for row in rows:
        batch.append(row)
        if len(batch) >= 16:
            done += _embed_batch(db, embedder, batch, settings.embedding_model)
            batch = []
            if done % 320 == 0:
                print(f"  {done} embedded")
    if batch:
        done += _embed_batch(db, embedder, batch, settings.embedding_model)
    db.commit()
    print(f"done: {done} vectors stored")
    return 0


def _embed_batch(db, embedder, rows, model_id: str) -> int:
    import math
    texts = [f"{r['citation']} {r['title']} {r['text_excerpt'][:600]}" for r in rows]
    vectors = embedder.embed(texts)
    if not vectors:
        return 0
    for row, vector in zip(rows, vectors):
        norm = math.sqrt(sum(x * x for x in vector))
        db.execute("INSERT OR REPLACE INTO embeddings (authority_id, model_id, vector_json, norm) "
                   "VALUES (?,?,?,?)",
                   (row["authority_id"], model_id or "default", json.dumps(vector), norm))
    db.commit()
    return len(rows)


def cmd_user_add(args: argparse.Namespace) -> int:
    from .auth import AuthError, register_user
    from .db import app_db
    settings = get_settings()
    settings.ensure_dirs()
    password = args.password or getpass.getpass("password (min 10 chars): ")
    try:
        user = register_user(app_db(settings.data_dir), args.user_id, password,
                             args.display_name or args.user_id, args.role)
    except AuthError as exc:
        print(f"error: {exc}")
        return 1
    print(json.dumps(user))
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    from .ingestion import ocr_readiness
    from .packs import list_packs
    from .providers import build_embedding_provider, build_generation_provider
    settings = get_settings()
    settings.ensure_dirs()
    report = {
        "data_dir": str(settings.data_dir),
        "packs_dir": str(settings.packs_dir),
        "active_pack": settings.active_pack or "(first available)",
        "packs": list_packs(settings.packs_dir),
        "generation": build_generation_provider(settings).health(),
        "ocr": ocr_readiness(),
        "prefer_live_output": settings.prefer_live_output,
    }
    embedder = build_embedding_provider(settings)
    report["embedding"] = embedder.health() if embedder else {"provider": "none",
                                                              "detail": "lexical-only retrieval"}
    print(json.dumps(report, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thesislogic", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the gateway and workspace UI")
    p_serve.add_argument("--host", default="")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.set_defaults(func=cmd_serve)

    p_pack = sub.add_parser("pack", help="manage jurisdiction packs")
    pack_sub = p_pack.add_subparsers(dest="pack_command", required=True)

    p_list = pack_sub.add_parser("list")
    p_list.set_defaults(func=cmd_pack_list)

    p_scaffold = pack_sub.add_parser("scaffold")
    p_scaffold.add_argument("pack_id")
    p_scaffold.add_argument("--name", default="")
    p_scaffold.add_argument("--jurisdiction", default="")
    p_scaffold.set_defaults(func=cmd_pack_scaffold)

    p_build = pack_sub.add_parser("build")
    p_build.add_argument("pack_id")
    p_build.add_argument("--source", default="")
    p_build.add_argument("--limit", type=int, default=None)
    p_build.set_defaults(func=cmd_pack_build)

    p_embed = pack_sub.add_parser("embed")
    p_embed.add_argument("pack_id")
    p_embed.set_defaults(func=cmd_pack_embed)

    p_user = sub.add_parser("user", help="manage users")
    user_sub = p_user.add_subparsers(dest="user_command", required=True)
    p_add = user_sub.add_parser("add")
    p_add.add_argument("user_id")
    p_add.add_argument("--display-name", default="")
    p_add.add_argument("--role", default="attorney", choices=["attorney", "admin"])
    p_add.add_argument("--password", default="")
    p_add.set_defaults(func=cmd_user_add)

    p_doctor = sub.add_parser("doctor", help="environment and provider checks")
    p_doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
