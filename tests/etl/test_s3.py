"""Tests de radia.etl.s3 contra un S3 simulado con moto. Nunca tocan el bucket real."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from radia.etl import s3

BUCKET = "test-bucket"
OBJECTS = {
    "data/customers.csv": b"customer_id\nC1\n",
    "data/products.csv": b"product_id\nP1\n",
    "data/products_v2.csv": b"otra tabla\n",
    "data/transactions/year=2026/month=06/day=16/part-0.csv": b"t1\n",
    "data/transactions/year=2026/month=06/day=17/part-0.csv": b"t2\n",
    "data/digital_events/year=2026/month=06/day=17/part-0.csv": b"no se baja\n",
}


@pytest.fixture
def tmpdir_path():
    """tempfile en vez de tmp_path: el tmp_path de pytest es lento en Windows."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def client():
    with mock_aws():
        c = boto3.client("s3", region_name="us-east-1")
        c.create_bucket(Bucket=BUCKET)
        for key, body in OBJECTS.items():
            c.put_object(Bucket=BUCKET, Key=key, Body=body)
        yield c


def test_manifest_solo_trae_las_tablas_pedidas(client):
    m = s3.build_manifest(
        client, BUCKET, "data/", ("customers", "products", "transactions")
    )
    keys = {e.key for e in m.entries}
    assert "data/digital_events/year=2026/month=06/day=17/part-0.csv" not in keys
    assert "data/products_v2.csv" not in keys
    assert m.summary()["transactions"]["objects"] == 2
    assert m.total_bytes == sum(len(OBJECTS[k]) for k in keys)


def test_table_of():
    tables = ("customers", "transactions")
    assert s3._table_of("data/customers.csv", "data/", tables) == "customers"
    assert (
        s3._table_of("data/transactions/year=2026/x.csv", "data/", tables)
        == "transactions"
    )
    assert s3._table_of("data/customers_old.csv", "data/", tables) is None


def test_manifest_ida_y_vuelta(client, tmpdir_path):
    directory = tmpdir_path
    m = s3.build_manifest(client, BUCKET, "data/", ("customers",))
    assert s3.load_manifest(s3.save_manifest(m, directory)) == m


def test_download_una_sola_vez_y_retoma_cambios(client, tmpdir_path):
    raw = tmpdir_path
    m = s3.build_manifest(client, BUCKET, "data/", ("customers", "transactions"))
    assert len(s3.download(client, m, raw, max_concurrency=2)) == 3
    assert (raw / "data/customers.csv").read_bytes() == OBJECTS["data/customers.csv"]
    # Segunda corrida: nada pendiente, ningún GET.
    assert s3.download(client, m, raw, max_concurrency=2) == []
    # Dato tardío: cambia un objeto y aparece otro. Solo esos se bajan.
    client.put_object(
        Bucket=BUCKET, Key="data/customers.csv", Body=b"customer_id\nC1\nC2\n"
    )
    client.put_object(
        Bucket=BUCKET,
        Key="data/transactions/year=2026/month=06/day=18/part-0.csv",
        Body=b"t3\n",
    )
    m2 = s3.build_manifest(client, BUCKET, "data/", ("customers", "transactions"))
    got = {e.key for e in s3.download(client, m2, raw, max_concurrency=2)}
    assert got == {
        "data/customers.csv",
        "data/transactions/year=2026/month=06/day=18/part-0.csv",
    }


def test_manifest_created_at_con_zona():
    m = s3.Manifest(
        bucket="b", prefix="data/", created_at=datetime.now(UTC), entries=[]
    )
    assert m.total_bytes == 0
    assert m.summary() == {}
