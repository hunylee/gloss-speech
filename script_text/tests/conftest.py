import os

import psycopg
import pytest

from app import db

# 테스트 전용 DB. 없으면 만든다.
TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://speech:speech@localhost:5432/script_text_test")


@pytest.fixture()
def conn():
    admin_url = TEST_URL.rsplit("/", 1)[0] + "/postgres"
    name = TEST_URL.rsplit("/", 1)[1]
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'drop database if exists "{name}"')
        admin.execute(f'create database "{name}"')
    os.environ["DATABASE_URL"] = TEST_URL
    with db.connect(TEST_URL) as c:
        db.migrate(c)
        c.commit()
        yield c
