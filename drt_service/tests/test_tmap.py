from __future__ import annotations

import asyncio
import json

import httpx

from app.clients.tmap_client import Coordinate, TmapClient
from app.geo import SearchKeywordType


def test_search_pois_no_content_returns_empty_list():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TmapClient("test-key", client=async_client)
        result = await client.search_pois(
            "검색결과없는장소", Coordinate(37.4849, 126.971), 3000, 5
        )
        await async_client.aclose()
        return result

    assert asyncio.run(run()) == []


def test_pedestrian_route_coordinate_order_and_cache():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        assert body["startX"] == 126.971
        assert body["startY"] == 37.4849
        assert body["endX"] == 126.9654
        assert body["endY"] == 37.4826
        return httpx.Response(200, json={
            "features": [{"properties": {"totalDistance": 640, "totalTime": 512}}]
        })

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TmapClient("test-key", client=async_client)
        origin = Coordinate(37.4849, 126.971)
        destination = Coordinate(37.4826, 126.9654)
        first = await client.pedestrian_route(origin, destination, "출발", "도착")
        second = await client.pedestrian_route(origin, destination, "출발", "도착")
        await async_client.aclose()
        return first, second

    first, second = asyncio.run(run())
    assert first == second
    assert first.distance_m == 640
    assert len(calls) == 1


def test_parse_pois_extracts_enriched_fields_and_prefers_pns_coord():
    body = {
        "searchPoiInfo": {"pois": {"poi": [{
            "id": "1", "name": "사당정형외과의원",
            "pnsLat": "37.4849", "pnsLon": "126.9711",
            "frontLat": "37.0", "frontLon": "127.0",
            "telNo": "02-1234-5678",
            "middleAddrName": "동작구", "lowerAddrName": "사당동",
            "lowerBizName": "병원", "detailBizName": "정형외과",
            "newAddressList": {"newAddress": {"fullAddressRoad": "서울 동작구 사당로 1"}},
        }]}}
    }
    results = TmapClient._parse_pois(body, Coordinate(37.4849, 126.9710), radius_m=1000, count=10)
    assert len(results) == 1
    poi = results[0]
    assert (poi.coord.lat, poi.coord.lon) == (37.4849, 126.9711)  # pnsLat/pnsLon 우선
    assert poi.phone == "02-1234-5678"
    assert poi.district == "동작구"
    assert poi.neighborhood == "사당동"
    assert poi.category == "병원"
    assert poi.detail_category == "정형외과"
    assert poi.address == "서울 동작구 사당로 1"


def test_parse_pois_falls_back_to_lot_address_without_road_address():
    body = {
        "searchPoiInfo": {"pois": {"poi": [{
            "id": "1", "name": "테스트장소", "frontLat": "37.48", "frontLon": "126.97",
            "upperAddrName": "서울특별시", "middleAddrName": "동작구", "lowerAddrName": "사당동",
            "firstNo": "100", "secondNo": "0",
        }]}}
    }
    results = TmapClient._parse_pois(body, Coordinate(37.48, 126.97), radius_m=1000, count=10)
    assert results[0].address == "서울특별시 동작구 사당동 100"


def test_search_pois_sends_exact_searchtypcd_for_exact_keyword_type():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["searchtypCd"] = request.url.params["searchtypCd"]
        return httpx.Response(204)

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TmapClient("test-key", client=async_client)
        await client.search_pois(
            "남현서울정형외과", Coordinate(37.4849, 126.971), 3000, 5,
            keyword_type=SearchKeywordType.EXACT,
        )
        await async_client.aclose()

    asyncio.run(run())
    assert captured["searchtypCd"] == "A"


def test_search_pois_defaults_to_category_searchtypcd():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["searchtypCd"] = request.url.params["searchtypCd"]
        return httpx.Response(204)

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TmapClient("test-key", client=async_client)
        await client.search_pois("정형외과", Coordinate(37.4849, 126.971), 3000, 5)
        await async_client.aclose()

    asyncio.run(run())
    assert captured["searchtypCd"] == "R"


def test_reverse_geocode_no_content():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TmapClient("test-key", client=async_client)
        result = await client.reverse_geocode(37.48, 126.97)
        await async_client.aclose()
        return result

    assert asyncio.run(run()) == {"ok": False, "status": "NO_CONTENT", "address": None}
