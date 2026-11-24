"""RAGFlow 站点配置 base64 编解码测试。"""
from app.hermes.rag_env import decode_sites, encode_sites


def test_encode_decode_roundtrip():
    sites = {"1": {"base_url": "http://a", "api_key": "secret-key"}}
    dataset_sites = {"d1": "1", "d2": "1"}
    s_b64, ds_b64 = encode_sites(sites, dataset_sites)
    assert decode_sites(s_b64, ds_b64) == (sites, dataset_sites)


def test_plaintext_key_not_in_encoded_value():
    sites = {"1": {"base_url": "http://a", "api_key": "SUPERSECRET123"}}
    s_b64, _ = encode_sites(sites, {})
    assert "SUPERSECRET123" not in s_b64


def test_decode_invalid_returns_empty():
    assert decode_sites("!!!not-base64!!!", "") == ({}, {})
