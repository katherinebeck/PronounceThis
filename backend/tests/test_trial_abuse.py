"""Trial anti-abuse: alias collapse, disposable domains, per-device counters."""
import asyncio
import os

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import auth


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    d = client["test_trial_abuse"]
    _run(d.users.delete_many({}))
    _run(d.trial_devices.delete_many({}))
    yield d
    client.drop_database("test_trial_abuse")


def test_canonical_email_gmail_aliases():
    for alias in ["Jane.Doe@gmail.com", "janedoe+trial2@gmail.com", "j.a.n.e.doe@googlemail.com", "JANEDOE@GMAIL.COM"]:
        assert auth.canonical_email(alias) == "janedoe@gmail.com"


def test_canonical_email_other_domains_keep_dots_strip_plus():
    assert auth.canonical_email("jane.doe+x@icloud.com") == "jane.doe@icloud.com"
    assert auth.canonical_email("Jane.Doe@Yahoo.com") == "jane.doe@yahoo.com"


def test_disposable_detection():
    assert auth.is_disposable_email("x@mailinator.com")
    assert auth.is_disposable_email("x@sub.mailinator.com")
    assert not auth.is_disposable_email("x@gmail.com")
    assert not auth.is_disposable_email("x@katherinebeck.com")
    assert len(auth.DISPOSABLE_DOMAINS) > 3000


def test_resolve_prefers_legacy_exact_then_alias(db):
    _run(db.users.insert_one({"email": "jane.doe@gmail.com", "email_key": "janedoe@gmail.com", "created_at": "2026-01-01"}))
    assert _run(auth.resolve_account_email(db, "Jane.Doe@gmail.com")) == "jane.doe@gmail.com"
    assert _run(auth.resolve_account_email(db, "janedoe+again@gmail.com")) == "jane.doe@gmail.com"
    assert _run(auth.resolve_account_email(db, "someone.new@gmail.com")) == "someonenew@gmail.com"


def test_backfill_email_keys(db):
    _run(db.users.insert_one({"email": "a.b@gmail.com"}))
    _run(auth.backfill_email_keys(db))
    assert _run(db.users.find_one({"email": "a.b@gmail.com"}))["email_key"] == "ab@gmail.com"


def test_effective_trial_used_takes_device_max(db):
    _run(db.trial_devices.insert_one({"device_id": "dev1", "trial_word_used": 5, "trial_scene_used": 0}))
    fresh_user = {"email": "new@x.com", "trial_word_used": 0, "trial_scene_used": 1}
    used = _run(auth.effective_trial_used(db, fresh_user, "dev1"))
    assert used == {"word": 5, "scene": 1}
    assert _run(auth.effective_trial_used(db, fresh_user, None)) == {"word": 0, "scene": 1}


def test_consume_trial_increments_user_and_device(db):
    _run(db.users.insert_one({"email": "u@x.com", "trial_word_used": 0, "trial_scene_used": 0}))
    actor = auth.Actor(email="u@x.com", is_subscriber=False, allowed=True,
                       consumed_trial_kind="word", device_id="devZ")
    _run(auth.consume_trial(db, actor))
    _run(auth.consume_trial(db, actor))
    assert _run(db.users.find_one({"email": "u@x.com"}))["trial_word_used"] == 2
    dev = _run(db.trial_devices.find_one({"device_id": "devZ"}))
    assert dev["trial_word_used"] == 2 and dev["emails"] == ["u@x.com"]
