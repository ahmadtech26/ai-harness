import os
from pathlib import Path

import pytest

from legal_search.corpus import parse_law, parse_shard

SHARD = """---
title: القانون المدني الأردني (المواد 1-3)
parent_law: القانون المدني الأردني
source: example.test
---

# القانون المدني الأردني — المواد 1-3

### المادة 1 — يسمى هذا القانون (القانون المدني لسنة 1976).

---

### المادة 2

الفقرة الأولى.

الفقرة الثانية.

---

### المادة 2 مكرر — نص مكرر.

---

### المادة ٣

"""


def test_parses_inline_multiparagraph_and_repeated_articles(tmp_path: Path):
    shard = tmp_path / '00-المواد-1-3.md'
    shard.write_text(SHARD, encoding='utf-8')

    articles = parse_shard(shard, 'civil-code')

    assert [(a.number, a.suffix) for a in articles] == [(1, ''), (2, ''), (2, 'مكرر')]
    assert articles[0].text == 'يسمى هذا القانون (القانون المدني لسنة 1976).'
    assert articles[1].text == 'الفقرة الأولى.\n\nالفقرة الثانية.'
    assert articles[2].label == 'المادة 2 مكرر'
    assert {a.law_title for a in articles} == {'القانون المدني الأردني'}
    assert {a.source for a in articles} == {'example.test'}


def test_skips_headings_without_text(tmp_path: Path):
    shard = tmp_path / 'x.md'
    shard.write_text('### المادة 9\n\n---\n', encoding='utf-8')

    assert parse_shard(shard, 'civil-code') == []


@pytest.mark.skipif(not os.environ.get('CIVIL_CODE_DIR'), reason='real corpus not mounted')
def test_real_civil_code_parses_every_article_once():
    articles = parse_law(Path(os.environ['CIVIL_CODE_DIR']), 'civil-code')

    keys = [(a.number, a.suffix) for a in articles]
    assert len(keys) == len(set(keys))
    assert len(articles) >= 1440
    assert any(a.number == 107 for a in articles)


@pytest.mark.skipif(not os.environ.get('COURT_FEES_DIR'), reason='real corpus not mounted')
def test_real_court_fees_schedule_parses_every_article_once():
    articles = parse_law(Path(os.environ['COURT_FEES_DIR']), 'court-fees')

    assert [a.number for a in articles] == list(range(1, 53))
    assert articles[0].text.startswith('عن الدعوى أو الدعوى المتقابلة')
    assert {a.law_title for a in articles} == {'جدول رسوم المحاكم'}
