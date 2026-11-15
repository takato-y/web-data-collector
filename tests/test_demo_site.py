"""デモショップ自体のテスト（収集の前提となるページ構成を確かめる）。"""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from demo_site.app import create_app

DATA = Path(__file__).resolve().parents[1] / "demo_site" / "data"


@pytest.fixture
def client():
    return create_app(DATA / "day1.json").test_client()


def test_robots_txt_disallows_admin(client):
    res = client.get("/robots.txt")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "Disallow: /admin/" in body
    assert "Crawl-delay: 1" in body


def test_list_is_paginated(client):
    soup = BeautifulSoup(client.get("/products").get_data(as_text=True), "html.parser")
    assert len(soup.select("li.product-card")) == 5
    assert soup.select_one("a.next")["href"] == "/products?page=2"
    last = BeautifulSoup(client.get("/products?page=3").get_data(as_text=True), "html.parser")
    assert len(last.select("li.product-card")) == 2
    assert last.select_one("a.next") is None
    assert client.get("/products?page=4").status_code == 404


def test_detail_has_stock_and_category(client):
    soup = BeautifulSoup(client.get("/products/A-1008").get_data(as_text=True), "html.parser")
    assert soup.select_one(".stock").get_text() == "在庫切れ"
    assert soup.select_one(".category").get_text() == "事務用品"
    assert client.get("/products/NOPE").status_code == 404


def test_new_arrivals_html_has_no_items_until_js_runs(client):
    soup = BeautifulSoup(client.get("/new-arrivals").get_data(as_text=True), "html.parser")
    assert soup.select("li.product-card") == []
    assert len(client.get("/api/new-arrivals").get_json()) == 2


def test_fail_first_returns_503_then_recovers():
    c = create_app(DATA / "day1.json", fail_first=2).test_client()
    assert c.get("/robots.txt").status_code == 200  # robots.txt は失敗させない
    assert c.get("/products").status_code == 503
    assert c.get("/products").headers["Retry-After"] == "1"
    assert c.get("/products").status_code == 200


def test_names_are_html_escaped():
    c = create_app(DATA / "day2.json").test_client()
    html = c.get("/products/A-1014").get_data(as_text=True)
    assert "&#34;" in html or "&quot;" in html
