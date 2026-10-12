import { createMap, setStartMarker, drawRoute, clearRoute, showRewardStations } from "./map.js";
import { findRoutes } from "./router.js";
import { enrichStation } from "./rewards.js";
import { formatMinutes } from "./geo.js";

const form = document.getElementById("route-form");
const addressInput = document.getElementById("address");
const minutesInput = document.getElementById("minutes");
const minutesLabel = document.getElementById("minutes-label");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const metaEl = document.getElementById("data-meta");
const useLocationBtn = document.getElementById("use-location");

const mapCtx = createMap("map");
let stations = [];
let start = null;
let routes = [];
let selectedIndex = 0;

minutesInput.addEventListener("input", () => {
  minutesLabel.textContent = `${minutesInput.value} min`;
});

useLocationBtn.addEventListener("click", () => {
  if (!navigator.geolocation) {
    setStatus("Geolocation is not available in this browser.", "error");
    return;
  }
  setStatus("Getting your location…");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      start = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      addressInput.value = `${start.lat.toFixed(5)}, ${start.lon.toFixed(5)}`;
      setStartMarker(mapCtx, start.lat, start.lon);
      mapCtx.map.setView([start.lat, start.lon], 14);
      setStatus("Location set. Tap Find route.");
    },
    () => setStatus("Could not get location. Enter an address instead.", "error"),
    { enableHighAccuracy: true, timeout: 12000 }
  );
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  await runSearch();
});

async function init() {
  setStatus("Loading Bay Wheels stations…");
  try {
    const res = await fetch("./data/stations.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    stations = (payload.stations || []).map(enrichStation);
    showRewardStations(mapCtx, stations);
    const when = payload.local_time || payload.generated_at || "unknown";
    metaEl.textContent = `Predicted points · ${payload.rewarded_count ?? "?"} rewarded stations · updated ${formatStamp(when)}`;
    setStatus("Enter a San Francisco Bay Area address to plan a route.");
  } catch (err) {
    console.error(err);
    setStatus(
      "Could not load station data. Run scripts/refresh-web-data.py or wait for the GitHub Action refresh.",
      "error"
    );
  }
}

async function runSearch() {
  const query = addressInput.value.trim();
  if (!query) {
    setStatus("Enter an address or use your location.", "error");
    return;
  }

  setStatus("Geocoding address…");
  resultsEl.innerHTML = "";
  clearRoute(mapCtx);

  try {
    start = await geocode(query);
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Address not found.", "error");
    return;
  }

  setStartMarker(mapCtx, start.lat, start.lon);
  setStatus("Searching routes…");

  const budget = Number(minutesInput.value) || 45;
  const preferEbike = document.getElementById("allow-ebike").checked;

  // Yield to UI before beam search.
  await new Promise((r) => setTimeout(r, 20));
  routes = findRoutes(start, stations, {
    timeBudgetMin: budget,
    preferEbike,
    maxWalkMin: 12,
  });

  if (!routes.length) {
    setStatus(
      "No rewarding routes found in that time budget. Try a longer session or a more central address.",
      "error"
    );
    showRewardStations(mapCtx, stations);
    return;
  }

  selectedIndex = 0;
  renderResults();
  drawRoute(mapCtx, start, routes[0]);
  setStatus(
    `Found ${routes.length} route${routes.length === 1 ? "" : "s"} · points are predicted from station fill, not live Angels map values.`
  );
}

function renderResults() {
  resultsEl.innerHTML = "";
  routes.forEach((route, idx) => {
    const card = document.createElement("article");
    card.className = `route-card${idx === selectedIndex ? " is-selected" : ""}`;
    card.style.setProperty("--stagger", `${idx * 60}ms`);
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.innerHTML = `
      <header>
        <h2>Route ${idx + 1}</h2>
        <p class="route-totals">
          <span class="stat pts">+${route.points} pts</span>
          <span class="stat">≈ $${route.usdLow.toFixed(2)}–$${route.usdHigh.toFixed(2)}</span>
          <span class="stat">${formatMinutes(route.elapsedMin)}</span>
        </p>
        <p class="route-breakdown">Walk ${formatMinutes(route.walkMin)} · Ride ${formatMinutes(route.rideMin)}${route.preferEbike ? " · e-bike" : " · classic"}</p>
      </header>
      <ol class="leg-list">
        ${route.legs
          .map(
            (leg) => `
          <li>
            <div class="leg-head">
              <span class="leg-num">${leg.index}</span>
              <span class="leg-pts">+${leg.points} pts</span>
              <span class="leg-time">${formatMinutes(leg.walkMin)} walk · ${formatMinutes(leg.rideMin)} ride</span>
            </div>
            <div class="leg-stations">
              <div class="station pickup">
                <span class="tag">Pick up</span>
                <strong>${escapeHtml(leg.pickup.name)}</strong>
                <span>+${leg.pickup.points} · ${leg.pickup.bikes} bikes</span>
              </div>
              <div class="station dropoff">
                <span class="tag">Drop off</span>
                <strong>${escapeHtml(leg.dropoff.name)}</strong>
                <span>+${leg.dropoff.points} · ${leg.dropoff.docks} docks</span>
              </div>
            </div>
          </li>`
          )
          .join("")}
      </ol>
    `;
    const select = () => {
      selectedIndex = idx;
      renderResults();
      drawRoute(mapCtx, start, route);
    };
    card.addEventListener("click", select);
    card.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        select();
      }
    });
    resultsEl.appendChild(card);
  });
}

async function geocode(query) {
  // Accept raw "lat, lon"
  const coord = query.match(
    /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/
  );
  if (coord) {
    return { lat: Number(coord[1]), lon: Number(coord[2]), label: query };
  }

  const url = new URL("https://nominatim.openstreetmap.org/search");
  url.searchParams.set("q", query);
  url.searchParams.set("format", "json");
  url.searchParams.set("limit", "1");
  url.searchParams.set("countrycodes", "us");
  url.searchParams.set("viewbox", "-122.55,37.90,-121.75,37.25");
  url.searchParams.set("bounded", "1");

  const res = await fetch(url.toString(), {
    headers: {
      Accept: "application/json",
    },
  });
  if (!res.ok) throw new Error("Geocoding failed.");
  const data = await res.json();
  if (!data.length) {
    throw new Error("Address not found in the Bay Area. Try a clearer SF address.");
  }
  return {
    lat: Number(data[0].lat),
    lon: Number(data[0].lon),
    label: data[0].display_name,
  };
}

function setStatus(msg, kind = "info") {
  statusEl.textContent = msg;
  statusEl.dataset.kind = kind;
}

function formatStamp(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-US", {
      timeZone: "America/Los_Angeles",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

init();
