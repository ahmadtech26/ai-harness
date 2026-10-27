import os

import pytest
from psycopg import AsyncConnection

from legal_search import db
from legal_search.corpus import Article
from legal_search.search_config import SearchConfig
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        yield connection


async def test_length_normalisation_ranks_a_short_match_above_a_longer_one(conn):
    # Article 1 says «العربون» twice in 45 words; article 2 once in 2 words.
    long_text = 'يرد العربون عند ' + ' '.join(['الشرط'] * 40) + ' ويستحق العربون.'
    await db.upsert_articles(conn, [
        Article('civil-code', 'x', 1, '', long_text, 's', 'a.md'),
        Article('civil-code', 'x', 2, '', 'العربون يرد.', 's', 'a.md'),
    ])

    # Explicit settings: an adopted default must not change what this test pins.
    plain = await db.search(conn, 'العربون', 2, config=SearchConfig(rank_normalization=0))
    normalised = await db.search(conn, 'العربون', 2, config=SearchConfig(rank_normalization=2))

    assert [a.number for a in plain] == [1, 2]
    assert [a.number for a in normalised] == [2, 1]
