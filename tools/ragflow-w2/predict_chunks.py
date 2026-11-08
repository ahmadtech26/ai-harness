#!/usr/bin/env python3
"""predict_chunks.py: the chunks RAGFlow v0.27.3's own code makes from each upload file under the canvas.

Runs INSIDE the running server container, with the image's own Python and RAGFlow's code on sys.path:
  docker exec ragbench-rf-server /ragflow/.venv/bin/python -B /w2/predict_chunks.py \
      --canvas /canvas/indexing-pipeline.json --in-dir /in > "$RUN/out/<engine>/predicted-chunks.jsonl"
Not `docker run`: the image's ENTRYPOINT is ./entrypoint.sh (Dockerfile:321), which refuses unknown
arguments (docker/entrypoint.sh:164-166). Not `python -I`: that drops the image's PYTHONPATH=/ragflow/
(Dockerfile:282); this script also puts /ragflow first on sys.path itself and removes its own folder.

What it runs, per file, is RAGFlow's code, not a copy of it:
  1. Parser._markdown (rag/flow/parser/parser.py:1067-1127) with the canvas's Parser params, applied
     by ParserParam.update and checked by ParserParam.check, as Graph.validate_component_parameters does
     (agent/canvas.py:113-124). It calls rag.app.naive.Markdown (naive.py:1067-1104).
  2. The TitleChunker method the canvas names, GroupTitleChunker or HierarchyTitleChunker
     (rag/flow/chunker/title_chunker/title_chunker.py:24-40), with TitleChunkerParam from the canvas, fed
     what the pipeline feeds it: the Parser's outputs and the file name (rag/flow/base.py:41-45;
     rag/flow/pipeline.py:175-177). Its token counts come from common.token_utils (cl100k_base,
     token_utils.py:144-153), as in the server.
  The stand-in for the pipeline object holds no tenant: the Parser's vision step returns at once without
  one (rag/flow/parser/utils.py:169-170), and our files hold no image (make_w2_corpus.py refuses them).
  The Tokenizer step is not run: it adds tokens and vectors but never changes a chunk's text
  (rag/flow/tokenizer/tokenizer.py:127-195), and the stored content is that text
  (rag/svr/task_executor.py:946-948).

Output, on stdout (ASCII JSON lines, so a shell redirect cannot change a byte):
  first line {"w2_predict": 1, "canvas_sha256", "files": {name: sha256}, "ragflow_version", "method", ...}
  then one line per chunk {"file", "i", "tokens", "articles", "text"} in each file's chunk order.
A summary per file goes to stderr: chunks, chunks holding two or more «### المادة» headings, chunks
holding none, the largest token count, and repeated texts. A repeated text is not simply stored once:
its copies share one chunk id (task_executor.py:926-927) but each is added to chunk_count
(task_executor.py:972), so the runbook stops at E4 when any file repeats a text (README).
The canvas is read as data. Nothing is written, nothing is sent.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

RAGFLOW_ROOT = '/ragflow'
CHAIN = ('File', 'Parser', 'TitleChunker', 'Tokenizer')
ARTICLE_HEAD = '### المادة'


class Refused(Exception):
    pass


class Stage:
    """Stands in for the pipeline component: holds the param, records outputs, ignores progress."""

    class _Canvas:
        _tenant_id = None
        _language = None
        _doc_id = None
        _kb_id = None

    def __init__(self, param):
        self._param = param
        self._canvas = self._Canvas()
        self.outputs = {}

    def set_output(self, key, value):
        self.outputs[key] = value

    def callback(self, *args, **kwargs):
        pass


def components_of(dsl) -> dict:
    components = dsl.get('components') if isinstance(dsl, dict) else None
    if not isinstance(components, dict):
        raise Refused('the canvas has no components object')
    found = {}
    for comp in components.values():
        name = (comp.get('obj') or {}).get('component_name') if isinstance(comp, dict) else None
        if name not in CHAIN or name in found:
            raise Refused(f'the canvas holds a component other than one each of {", ".join(CHAIN)}: {name!r}')
        found[name] = comp['obj'].get('params') or {}
    if set(found) != set(CHAIN):
        raise Refused(f'the canvas lacks {sorted(set(CHAIN) - set(found))}')
    return found


def main(argv=None) -> int:
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # anything RAGFlow prints while importing or parsing stays off the data stream
    ap = argparse.ArgumentParser(description='Predict the W2 chunks with RAGFlow\'s own chunker.')
    ap.add_argument('--canvas', required=True, type=Path)
    ap.add_argument('--in-dir', required=True, type=Path)
    ap.add_argument('--expect', type=int, default=22, help='number of .md files required (default: %(default)s)')
    args = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or '.') != here]
    sys.path.insert(0, RAGFLOW_ROOT)
    try:
        raw = args.canvas.read_bytes()
        params = components_of(json.loads(raw.decode('utf-8')))
        files = sorted(p for p in args.in_dir.iterdir() if p.name.endswith('.md'))
        if len(files) != args.expect:
            raise Refused(f'{args.in_dir} holds {len(files)} .md files, not {args.expect}')
    except (OSError, ValueError, Refused) as error:
        print(f'refused: {error}', file=sys.stderr)
        return 2

    from common.token_utils import num_tokens_from_string
    from rag.flow.chunker.title_chunker.common import TitleChunkerParam
    from rag.flow.chunker.title_chunker.group_chunker import GroupTitleChunker
    from rag.flow.chunker.title_chunker.hierarchy_chunker import HierarchyTitleChunker
    from rag.flow.chunker.title_chunker.schema import TitleChunkerFromUpstream
    from rag.flow.parser.parser import Parser, ParserParam

    parser_param = ParserParam()
    parser_param.update(params['Parser'])
    parser_param.check()
    chunker_param = TitleChunkerParam()
    chunker_param.update(params['TitleChunker'])
    chunker_param.check()
    chunkers = {'group': GroupTitleChunker, 'hierarchy': HierarchyTitleChunker}
    if chunker_param.method not in chunkers:
        print(f'refused: TitleChunker method {chunker_param.method!r} is not group or hierarchy', file=sys.stderr)
        return 2
    try:
        version = Path(RAGFLOW_ROOT, 'VERSION').read_text(encoding='utf-8').strip()
    except OSError:
        version = None

    header = {'w2_predict': 1, 'canvas_sha256': hashlib.sha256(raw).hexdigest(),
              'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
              'ragflow_version': version, 'method': chunker_param.method, 'hierarchy': chunker_param.hierarchy,
              'chunk_token_cap': chunker_param.chunk_token_cap, 'python': sys.version.split()[0]}
    lines = [json.dumps(header, ensure_ascii=True)]
    total = 0
    for path in files:
        blob = path.read_bytes()
        parsing = Stage(parser_param)
        Parser._markdown(parsing, path.name, blob)
        if parsing.outputs.get('_ERROR'):
            print(f'{path.name}: the Parser failed: {parsing.outputs["_ERROR"]}', file=sys.stderr)
            return 1
        upstream = {k: parsing.outputs[k] for k in ('output_format', 'json', 'markdown', 'text', 'html')
                    if k in parsing.outputs}
        from_upstream = TitleChunkerFromUpstream.model_validate({'name': path.name, **upstream})
        chunking = Stage(chunker_param)
        asyncio.run(chunkers[chunker_param.method](chunking, from_upstream).invoke())
        chunks = chunking.outputs.get('chunks')
        if not isinstance(chunks, list):
            print(f'{path.name}: the chunker gave no chunk list', file=sys.stderr)
            return 1
        texts = [c.get('text') or '' for c in chunks]
        heads = [sum(1 for x in t.split('\n') if x.startswith(ARTICLE_HEAD)) for t in texts]
        tokens = [num_tokens_from_string(t) for t in texts]
        for i, (text, n_heads, n_tokens) in enumerate(zip(texts, heads, tokens)):
            lines.append(json.dumps({'file': path.name, 'i': i, 'tokens': n_tokens, 'articles': n_heads, 'text': text},
                                    ensure_ascii=True))
        repeats = sum(n - 1 for n in Counter(texts).values() if n > 1)
        print(f'{path.name:28s} chunks {len(texts):5d}  two+ articles {sum(h > 1 for h in heads):4d}  '
              f'no article {sum(h == 0 for h in heads):3d}  max tokens {max(tokens, default=0):5d}  '
              f'repeated texts {repeats}', file=sys.stderr)
        total += len(texts)
    print(f'TOTAL {len(files)} files, {total} predicted chunks (RAGFlow {version}, method {chunker_param.method})',
          file=sys.stderr)
    real_stdout.write('\n'.join(lines) + '\n')
    real_stdout.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
