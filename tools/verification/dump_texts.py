"""Dump every article's stored text as the ingest stores it, one JSONL per law, for the verification pass.

The text is what `legal_search.ingest.prepare` returns (the corpus parser with content/corpus/corrections.json
applied), taken from `recall-plan`'s services/legal-search, the copy that runs live. This file imports legal_search
and holds no parser code of its own. Each line: law_slug, number, suffix, text, text_sha256 (sha256 of the text's
UTF-8 bytes, exactly; the records' binding key), shard, folder.

    uv run --project <recall-plan checkout>/services/legal-search \
        python tools/verification/dump_texts.py --root . --out <dir> [--law <slug> ...]

or, with an environment that already has legal_search's dependencies:

    python tools/verification/dump_texts.py --legal-search-src <recall-plan checkout>/services/legal-search/src \
        --root . --out <dir>

--root is this repository's checkout (it reads content/corpus/laws.json, content/corpus/corrections.json and
jordanian-law/references/القوانين-الأردنية). prepare checks every law, so the whole registry is parsed even when
--law names one.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

CORPUS = Path('jordanian-law/references/القوانين-الأردنية')


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, required=True, help='this repository checkout (the content tree)')
    parser.add_argument('--out', type=Path, required=True, help='folder for <law-slug>.jsonl')
    parser.add_argument('--law', action='append', default=[], help='dump only this law slug (repeatable)')
    parser.add_argument('--legal-search-src', type=Path, help="recall-plan's services/legal-search/src, if legal_search is not installed")
    args = parser.parse_args(argv)
    if args.legal_search_src:
        sys.path.insert(0, str(args.legal_search_src.resolve()))

    import legal_search
    from legal_search.corrections import load_corrections
    from legal_search.ingest import prepare
    from legal_search.registry import load_registry

    print(f'legal_search from {Path(legal_search.__file__).parent}', file=sys.stderr)
    root = args.root
    laws = load_registry(root / 'content/corpus/laws.json')
    unknown = sorted(set(args.law) - {law.slug for law in laws})
    if unknown:
        raise SystemExit(f'not in the registry: {", ".join(unknown)}')
    prepared = prepare(laws, load_corrections(root / 'content/corpus/corrections.json'), root / CORPUS)
    args.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for law in prepared.laws:
        if args.law and law.slug not in args.law:
            continue
        rows = prepared.articles[law.slug]
        with open(args.out / f'{law.slug}.jsonl', 'w', encoding='utf-8', newline='\n') as handle:
            for article in rows:
                handle.write(json.dumps({
                    'law_slug': article.law_slug, 'number': article.number, 'suffix': article.suffix,
                    'text': article.text, 'text_sha256': hashlib.sha256(article.text.encode('utf-8')).hexdigest(),
                    'shard': article.shard, 'folder': law.folder,
                }, ensure_ascii=False) + '\n')
        total += len(rows)
        print(law.slug, len(rows))
    print('total', total)


if __name__ == '__main__':
    main()
