"use strict";

const POLL_INTERVAL_MS = 1000;

// 이 화면은 mock_drt_server가 같은 오리진(/static/tracking)에서 직접 서빙한다.
// 배포된 Render 주소를 고정해 두면 로컬(run_stack.py 등)에서 포트를 바꿀 때마다
// 깨지므로, 지금 이 페이지가 열린 곳을 그대로 API 주소로 쓴다.
const MOCK_DRT_API_BASE_URL = window.location.origin;
const STATUS_ORDER = [
  "DISPATCHED",
  "APPROACHING",
  "ARRIVED",
  "IN_SERVICE",
  "COMPLETED",
];
const STATUS_META = {
  DISPATCHED: {
    label: "차량 배정 완료",
    icon: "✓",
    etaCaption: "승차 장소까지",
  },
  APPROACHING: {
    label: "차량 접근 중",
    icon: "🚐",
    etaCaption: "승차 장소까지",
  },
  ARRIVED: {
    label: "차량 도착",
    icon: "📍",
    etaCaption: "승차 준비",
  },
  IN_SERVICE: {
    label: "목적지 이동 중",
    icon: "🚐",
    etaCaption: "목적지까지",
  },
  COMPLETED: {
    label: "운행 완료",
    icon: "✓",
    etaCaption: "이용 완료",
  },
};

const elements = {
  loadingView: document.querySelector("#loadingView"),
  errorView: document.querySelector("#errorView"),
  dashboardView: document.querySelector("#dashboardView"),
  errorTitle: document.querySelector("#errorTitle"),
  errorMessage: document.querySelector("#errorMessage"),
  retryButton: document.querySelector("#retryButton"),
  statusIcon: document.querySelector("#statusIcon"),
  statusLabel: document.querySelector("#statusLabel"),
  statusMessage: document.querySelector("#statusMessage"),
  etaCaption: document.querySelector("#etaCaption"),
  etaValue: document.querySelector("#etaValue"),
  vehicleName: document.querySelector("#vehicleName"),
  departureName: document.querySelector("#departureName"),
  arrivalName: document.querySelector("#arrivalName"),
  timeline: document.querySelector("#statusTimeline"),
  routePath: document.querySelector("#routePath"),
  routeSource: document.querySelector("#routeSource"),
  vehicleMarker: document.querySelector("#vehicleMarker"),
  stopMarkers: document.querySelector("#stopMarkers"),
  departureMarker: document.querySelector("#departureMarker"),
  arrivalMarker: document.querySelector("#arrivalMarker"),
};

const queryParams = new URLSearchParams(window.location.search);
const token = queryParams.get("token")?.trim() || "";
let pollTimer = null;
let hasLoaded = false;
let leafletMap = null;
let leafletVehicleMarker = null;
let leafletDepartureMarker = null;
let leafletArrivalMarker = null;
let leafletRouteLine = null;
let leafletStopMarkers = [];

elements.retryButton.addEventListener("click", () => {
  showLoading();
  loadTracking();
});

function showLoading() {
  elements.loadingView.hidden = false;
  elements.errorView.hidden = true;
  elements.dashboardView.hidden = true;
}

function showDashboard() {
  elements.loadingView.hidden = true;
  elements.errorView.hidden = true;
  elements.dashboardView.hidden = false;
}

function showError(title, message, canRetry = true) {
  elements.loadingView.hidden = true;
  elements.dashboardView.hidden = true;
  elements.errorView.hidden = false;
  elements.errorTitle.textContent = title;
  elements.errorMessage.textContent = message;
  elements.retryButton.hidden = !canRetry;
}

async function loadTracking() {
  clearTimeout(pollTimer);
  if (!token) {
    showError("잘못된 링크입니다", "전달받은 메시지의 링크를 다시 확인해 주세요.", false);
    return;
  }

  try {
    const response = await fetch(
      `${MOCK_DRT_API_BASE_URL}/tracking/${encodeURIComponent(token)}/status`,
      {
        cache: "no-store",
        headers: { Accept: "application/json" },
      },
    );

    if (response.status === 404) {
      showError("운행 정보를 찾을 수 없습니다", "링크가 올바른지 다시 확인해 주세요.", false);
      return;
    }
    if (response.status === 410) {
      showError("사용 기간이 종료된 링크입니다", "운행이 종료되었거나 링크가 만료되었습니다.", false);
      return;
    }
    if (!response.ok) {
      throw new Error(`tracking request failed: ${response.status}`);
    }

    const tracking = await response.json();
    showDashboard();
    renderTracking(tracking);
    hasLoaded = true;
    if (tracking.status !== "COMPLETED") {
      pollTimer = setTimeout(loadTracking, POLL_INTERVAL_MS);
    }
  } catch (error) {
    console.error("운행 정보 조회 실패:", error);
    if (!hasLoaded) {
      showError("연결이 원활하지 않습니다", "네트워크 상태를 확인한 후 다시 시도해 주세요.");
    } else {
      pollTimer = setTimeout(loadTracking, POLL_INTERVAL_MS);
    }
  }
}

function renderTracking(tracking) {
  const meta = STATUS_META[tracking.status] || STATUS_META.DISPATCHED;
  elements.statusIcon.textContent = meta.icon;
  elements.statusLabel.textContent = meta.label;
  elements.statusMessage.textContent = tracking.status_message;
  elements.etaCaption.textContent = meta.etaCaption;
  elements.etaValue.textContent = formatRemainingTime(
    tracking.estimated_arrival_seconds,
    tracking.status,
  );
  elements.vehicleName.textContent = tracking.vehicle.display_name;
  elements.departureName.textContent = tracking.departure_stop.name;
  elements.arrivalName.textContent = tracking.arrival_stop.name;
  updateTimeline(tracking.status);
  updateMap(tracking);
}

function formatRemainingTime(seconds, status) {
  if (status === "ARRIVED") return "도착 완료";
  if (status === "COMPLETED") return "운행 완료";
  const safeSeconds = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = Math.floor(safeSeconds % 60);
  if (minutes === 0) return `${remainder}초`;
  return `${minutes}분 ${String(remainder).padStart(2, "0")}초`;
}

function updateTimeline(status) {
  const activeIndex = STATUS_ORDER.indexOf(status);
  elements.timeline.querySelectorAll("li").forEach((item, index) => {
    item.classList.toggle("complete", index < activeIndex || status === "COMPLETED");
    item.classList.toggle("active", index === activeIndex && status !== "COMPLETED");
  });
}

function updateMap(tracking) {
  if (typeof window.L !== "undefined") {
    try {
      updateLeafletMap(tracking);
      return;
    } catch (error) {
      console.error("Leaflet 지도 렌더링에 실패했습니다.", error);
    }
  }
  showFallbackMap();
  updateFallbackMap(tracking);
}

function updateLeafletMap(tracking) {
  const mapElement = document.querySelector("#trackingMap");
  const fallbackElement = document.querySelector("#trackingFallback");
  mapElement.style.display = "block";
  fallbackElement.style.display = "none";
  const routeCoordinates = routeLatLngs(tracking);
  const vehiclePosition = [tracking.vehicle.latitude, tracking.vehicle.longitude];
  const departurePosition = [tracking.departure_stop.latitude, tracking.departure_stop.longitude];
  const arrivalPosition = [tracking.arrival_stop.latitude, tracking.arrival_stop.longitude];
  if (!leafletMap) {
    leafletMap = L.map("trackingMap");
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(leafletMap);
    leafletVehicleMarker = L.marker(vehiclePosition, {
      title: tracking.vehicle.display_name,
      icon: leafletIcon("🚐", "tmap-marker"),
      zIndexOffset: 1100,
    }).addTo(leafletMap);
    leafletDepartureMarker = L.marker(departurePosition, {
      title: tracking.departure_stop.name,
      icon: leafletIcon("승", "tmap-marker"),
      zIndexOffset: 1000,
    }).addTo(leafletMap);
    leafletArrivalMarker = L.marker(arrivalPosition, {
      title: tracking.arrival_stop.name,
      icon: leafletIcon("하", "tmap-marker"),
      zIndexOffset: 1000,
    }).addTo(leafletMap);
  } else {
    leafletVehicleMarker.setLatLng(vehiclePosition);
    leafletDepartureMarker.setLatLng(departurePosition);
    leafletArrivalMarker.setLatLng(arrivalPosition);
  }
  leafletStopMarkers.forEach((marker) => marker.remove());
  leafletStopMarkers = allStops(tracking).map((stop) =>
    L.marker([stop.latitude, stop.longitude], {
      title: stop.name,
      icon: leafletIcon("", "tmap-marker stop-marker"),
    }).addTo(leafletMap),
  );
  if (leafletRouteLine) leafletRouteLine.remove();
  leafletRouteLine = L.polyline(routeCoordinates, { color: routeColor(tracking.status), weight: 6 }).addTo(leafletMap);
  leafletMap.fitBounds(L.latLngBounds([...routeCoordinates, vehiclePosition, departurePosition, arrivalPosition]), { padding: [24, 24] });

  elements.routeSource.textContent =
    tracking.route?.source === "tmap" ? "TMAP 도로 경로 · OpenStreetMap 표시" : "직선 경로 (TMAP 폴백)";
}

function leafletIcon(label, className) {
  const isStop = className.includes("stop-marker");
  const size = isStop ? 18 : 40;
  return L.divIcon({
    className: "leaflet-custom-icon",
    html: `<span class="${className}">${label}</span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function showFallbackMap() {
  document.querySelector("#trackingMap").style.display = "none";
  document.querySelector("#trackingFallback").style.display = "block";
}

function updateFallbackMap(tracking) {
  const routeCoordinates = routeLatLngs(tracking);
  const stops = allStops(tracking);
  const coordinates = [
    ...routeCoordinates,
    ...stops.map((stop) => [stop.latitude, stop.longitude]),
    [tracking.vehicle.latitude, tracking.vehicle.longitude],
    [tracking.departure_stop.latitude, tracking.departure_stop.longitude],
    [tracking.arrival_stop.latitude, tracking.arrival_stop.longitude],
  ];
  const project = createProjector(coordinates);
  const routePoints = routeCoordinates.map(project);
  const vehiclePoint = project([
    tracking.vehicle.latitude,
    tracking.vehicle.longitude,
  ]);
  const departurePoint = project([
    tracking.departure_stop.latitude,
    tracking.departure_stop.longitude,
  ]);
  const arrivalPoint = project([
    tracking.arrival_stop.latitude,
    tracking.arrival_stop.longitude,
  ]);

  renderFallbackStops(stops, project);

  elements.routePath.setAttribute(
    "d",
    routePoints.map(([x, y], index) => `${index === 0 ? "M" : "L"} ${x} ${y}`).join(" "),
  );
  elements.routePath.style.stroke = routeColor(tracking.status);
  setMarkerPosition(elements.vehicleMarker, vehiclePoint);
  setMarkerPosition(elements.departureMarker, departurePoint);
  setMarkerPosition(elements.arrivalMarker, arrivalPoint);
  elements.routeSource.textContent =
    tracking.route?.source === "tmap" ? "TMAP 도로 경로" : "직선 경로 (TMAP 폴백)";
}

function allStops(tracking) {
  if (Array.isArray(tracking.stops) && tracking.stops.length) {
    return tracking.stops;
  }
  return [tracking.departure_stop, tracking.arrival_stop];
}

function renderFallbackStops(stops, project) {
  elements.stopMarkers.replaceChildren();
  stops.forEach((stop) => {
    const [x, y] = project([stop.latitude, stop.longitude]);
    const marker = document.createElementNS("http://www.w3.org/2000/svg", "g");
    marker.setAttribute("class", "all-stop-marker");
    marker.setAttribute("transform", `translate(${x} ${y})`);
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("r", "8");
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = stop.name;
    marker.append(circle, title);
    elements.stopMarkers.append(marker);
  });
}

function routeLatLngs(tracking) {
  const coordinates = tracking.route?.coordinates;
  if (Array.isArray(coordinates) && coordinates.length >= 2) {
    return coordinates;
  }
  return [
    [tracking.departure_stop.latitude, tracking.departure_stop.longitude],
    [tracking.arrival_stop.latitude, tracking.arrival_stop.longitude],
  ];
}

function createProjector(coordinates) {
  const latitudes = coordinates.map(([latitude]) => latitude);
  const longitudes = coordinates.map(([, longitude]) => longitude);
  const centerLatitude = (Math.min(...latitudes) + Math.max(...latitudes)) / 2;
  const longitudeFactor = Math.cos((centerLatitude * Math.PI) / 180);
  const normalized = coordinates.map(([latitude, longitude]) => [
    longitude * longitudeFactor,
    latitude,
  ]);
  const xValues = normalized.map(([x]) => x);
  const yValues = normalized.map(([, y]) => y);
  const minimumX = Math.min(...xValues);
  const maximumX = Math.max(...xValues);
  const minimumY = Math.min(...yValues);
  const maximumY = Math.max(...yValues);
  const xRange = Math.max(maximumX - minimumX, 0.0001);
  const yRange = Math.max(maximumY - minimumY, 0.0001);
  const padding = 48;
  const width = 1000 - padding * 2;
  const height = 460 - padding * 2;
  const scale = Math.min(width / xRange, height / yRange);
  const contentWidth = xRange * scale;
  const contentHeight = yRange * scale;
  const offsetX = (1000 - contentWidth) / 2;
  const offsetY = (460 - contentHeight) / 2;

  return ([latitude, longitude]) => {
    const x = longitude * longitudeFactor;
    return [
      Math.round((offsetX + (x - minimumX) * scale) * 10) / 10,
      Math.round((offsetY + (maximumY - latitude) * scale) * 10) / 10,
    ];
  };
}

function setMarkerPosition(marker, [x, y]) {
  marker.setAttribute("transform", `translate(${x} ${y})`);
}

function routeColor(status) {
  return ["DISPATCHED", "APPROACHING", "ARRIVED"].includes(status)
    ? "#155eef"
    : "#7a5af8";
}

showLoading();
loadTracking();
