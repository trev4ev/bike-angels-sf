/** Leaflet map helpers for route visualization. */

const SF_CENTER = [37.7749, -122.4194];

export function createMap(containerId) {
  const map = L.map(containerId, {
    zoomControl: false,
    attributionControl: true,
  }).setView(SF_CENTER, 13);

  L.control.zoom({ position: "bottomright" }).addTo(map);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

  return {
    map,
    layers: {
      start: null,
      stations: L.layerGroup().addTo(map),
      route: L.layerGroup().addTo(map),
    },
  };
}

function markerIcon(kind, label) {
  const cls =
    kind === "pickup"
      ? "pin-pickup"
      : kind === "dropoff"
        ? "pin-dropoff"
        : kind === "start"
          ? "pin-start"
          : "pin-neutral";
  return L.divIcon({
    className: "route-pin",
    html: `<div class="pin ${cls}"><span>${label}</span></div>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

export function setStartMarker(ctx, lat, lon, label = "You") {
  if (ctx.layers.start) ctx.map.removeLayer(ctx.layers.start);
  ctx.layers.start = L.marker([lat, lon], {
    icon: markerIcon("start", label),
  }).addTo(ctx.map);
  ctx.layers.start.bindPopup("Start");
}

export function clearRoute(ctx) {
  ctx.layers.route.clearLayers();
  ctx.layers.stations.clearLayers();
}

export function drawRoute(ctx, start, route) {
  clearRoute(ctx);
  const latlngs = [[start.lat, start.lon]];
  const bounds = L.latLngBounds(latlngs);

  route.legs.forEach((leg, i) => {
    const pickupLL = [leg.pickup.lat, leg.pickup.lon];
    const dropoffLL = [leg.dropoff.lat, leg.dropoff.lon];

    L.marker(pickupLL, {
      icon: markerIcon("pickup", String(i * 2 + 1)),
    })
      .bindPopup(
        `<strong>${leg.pickup.name}</strong><br>Pickup +${leg.pickup.points} pts · ${leg.pickup.bikes} bikes`
      )
      .addTo(ctx.layers.route);

    L.marker(dropoffLL, {
      icon: markerIcon("dropoff", String(i * 2 + 2)),
    })
      .bindPopup(
        `<strong>${leg.dropoff.name}</strong><br>Dropoff +${leg.dropoff.points} pts · ${leg.dropoff.docks} docks`
      )
      .addTo(ctx.layers.route);

    // Walk dashed
    L.polyline([latlngs[latlngs.length - 1], pickupLL], {
      color: "#5b6d7a",
      weight: 3,
      dashArray: "6 8",
      opacity: 0.85,
      className: "route-walk",
    }).addTo(ctx.layers.route);

    // Ride solid
    L.polyline([pickupLL, dropoffLL], {
      color: "#0f766e",
      weight: 5,
      opacity: 0.92,
      className: "route-ride",
    }).addTo(ctx.layers.route);

    latlngs.push(pickupLL, dropoffLL);
    bounds.extend(pickupLL);
    bounds.extend(dropoffLL);
  });

  if (ctx.layers.start) bounds.extend(ctx.layers.start.getLatLng());
  ctx.map.fitBounds(bounds.pad(0.18), { animate: true, duration: 0.6 });
}

export function showRewardStations(ctx, stations, limit = 80) {
  ctx.layers.stations.clearLayers();
  const rewarded = stations
    .filter((s) => s.pickup_points > 0 || s.dropoff_points > 0)
    .slice(0, limit);

  for (const s of rewarded) {
    const kind = s.pickup_points > 0 ? "pickup" : "dropoff";
    const pts = s.pickup_points || s.dropoff_points;
    L.circleMarker([s.lat, s.lon], {
      radius: 5 + Math.min(pts, 4),
      color: kind === "pickup" ? "#c2410c" : "#0369a1",
      fillColor: kind === "pickup" ? "#ea580c" : "#0ea5e9",
      fillOpacity: 0.35,
      weight: 1.5,
      opacity: 0.7,
    })
      .bindPopup(
        `<strong>${s.name}</strong><br>${kind} +${pts} (predicted)<br>${s.bikes_available} bikes · ${s.docks_available} docks`
      )
      .addTo(ctx.layers.stations);
  }
}
