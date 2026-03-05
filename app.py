import streamlit as st
import geopandas as gpd
import folium
from folium.plugins import LocateControl, Fullscreen
from folium import Element
import json
import requests
from streamlit_folium import st_folium
import streamlit.components.v1 as components

st.set_page_config(page_title="JKUAT Smart Campus", layout="wide")
st.title("🏛️ JKUAT Smart-Spatial Campus Dashboard")
st.markdown("### Engineering Decision Support | World Engineering Day 2026")

@st.cache_data
def get_clean_data():
    gdf = gpd.read_file("jkuat_digital_twin.geojson").to_crs(epsg=4326)

    required = ['name','Heat_mean','Solar_Kwh','Asset_Dept','Asset_Cond','Solar_Stat','geometry']
    gdf = gdf[[c for c in required if c in gdf.columns]].copy()

    gdf['name'] = gdf['name'].fillna("Unnamed Building").astype(str)
    gdf['Heat_mean'] = gdf['Heat_mean'].fillna(0).astype(float)
    gdf['Solar_Kwh'] = gdf['Solar_Kwh'].fillna(0).astype(int)
    gdf['Asset_Cond'] = gdf['Asset_Cond'].fillna(1).astype(int)

    for col in ['Asset_Dept','Solar_Stat']:
        gdf[col] = gdf[col].fillna("N/A").astype(str)

    gdf["Condition_Text"] = gdf["Asset_Cond"].map({
        1:"Very Good",
        2:"Good",
        3:"Fairly Good",
        4:"Repair",
        5:"Urgent Repair"
    })

    clean_dict = json.loads(gdf.to_json())
    return gdf, clean_dict

gdf, map_dict = get_clean_data()

# ---- SESSION STATE INIT ----
if "route_geojson"    not in st.session_state: st.session_state.route_geojson    = None
if "route_distance_m" not in st.session_state: st.session_state.route_distance_m = None
if "route_for"        not in st.session_state: st.session_state.route_for        = None
if "route_user_lat"   not in st.session_state: st.session_state.route_user_lat   = None
if "route_user_lon"   not in st.session_state: st.session_state.route_user_lon   = None
if "gps_lat"          not in st.session_state: st.session_state.gps_lat          = None
if "gps_lon"          not in st.session_state: st.session_state.gps_lon          = None

# ---- GPS CAPTURE COMPONENT ----
# A tiny hidden HTML component that requests the browser GPS and writes
# the result into Streamlit's query params, then triggers a rerun.
# This sits OUTSIDE the Folium iframe so it has direct access to
# window.location and can reliably communicate back to Streamlit.
gps_bridge_html = """
<style>
  #gps-btn {
    background: #0d6efd; color: white; border: none; border-radius: 8px;
    padding: 10px 18px; font-size: 14px; font-weight: bold; cursor: pointer;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25); width: 100%;
  }
  #gps-btn:hover { background: #0b5ed7; }
  #gps-status {
    margin-top: 8px; padding: 8px 12px; border-radius: 6px;
    font-size: 13px; display: none;
  }
</style>
<button id="gps-btn" onclick="captureGPS()">📍 Capture My Current Location</button>
<div id="gps-status"></div>
<script>
function captureGPS() {
    var btn    = document.getElementById('gps-btn');
    var status = document.getElementById('gps-status');

    if (!navigator.geolocation) {
        status.style.display      = 'block';
        status.style.background   = '#f8d7da';
        status.style.color        = '#842029';
        status.innerText          = '❌ Geolocation not supported in this browser.';
        return;
    }

    btn.innerText             = '⏳ Acquiring GPS...';
    btn.disabled              = true;
    status.style.display      = 'none';

    navigator.geolocation.getCurrentPosition(
        function(pos) {
            var lat = pos.coords.latitude.toFixed(7);
            var lon = pos.coords.longitude.toFixed(7);

            // Write coords into parent window URL query params
            var url = new URL(window.parent.location.href);
            url.searchParams.set('gps_lat', lat);
            url.searchParams.set('gps_lon', lon);
            // replaceState updates the URL without a full page reload
            window.parent.history.replaceState(null, '', url.toString());

            status.style.display    = 'block';
            status.style.background = '#d1e7dd';
            status.style.color      = '#0f5132';
            status.innerText        = '✅ Location captured! (' + lat + ', ' + lon + '). Now tap Get Shortest Route.';
            btn.innerText           = '📍 Capture My Current Location';
            btn.disabled            = false;

            // Tell Streamlit to rerun by sending a postMessage
            window.parent.postMessage({type: 'streamlit:rerun'}, '*');
        },
        function(err) {
            status.style.display    = 'block';
            status.style.background = '#f8d7da';
            status.style.color      = '#842029';
            status.innerText        = '❌ GPS error: ' + err.message;
            btn.innerText           = '📍 Capture My Current Location';
            btn.disabled            = false;
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
}
</script>
"""

# ---- READ GPS FROM QUERY PARAMS (set by the bridge component above) ----
qp = st.query_params
if "gps_lat" in qp and "gps_lon" in qp:
    try:
        captured_lat = float(qp["gps_lat"])
        captured_lon = float(qp["gps_lon"])
        # Only update if different from what we already have
        if (st.session_state.gps_lat != captured_lat or
                st.session_state.gps_lon != captured_lon):
            st.session_state.gps_lat = captured_lat
            st.session_state.gps_lon = captured_lon
    except ValueError:
        pass

# ---- SIDEBAR ----
st.sidebar.subheader("📍 Navigation")

names_list = sorted(gdf['name'].dropna().unique().tolist())
search_list = ["-- Select Building --"] + names_list

target = st.sidebar.selectbox("Find Building:", search_list)

# Clear stored route when the user picks a different building
if target != st.session_state.route_for:
    st.session_state.route_geojson    = None
    st.session_state.route_distance_m = None
    st.session_state.route_for        = None
    st.session_state.route_user_lat   = None
    st.session_state.route_user_lon   = None

layer_choice = st.sidebar.radio(
    "View Mode:",
    ["Condition", "Solar suitability", "Surface Temperature"]
)

# ---- LEGEND ----
st.sidebar.divider()
st.sidebar.subheader("🗺️ Legend")

if layer_choice == "Solar suitability":
    st.sidebar.markdown(
        """
        <div style="line-height:2">
            <span style="display:inline-block;width:14px;height:14px;background:#f1c40f;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Yellow</b> — High Priority<br>
            <span style="display:inline-block;width:14px;height:14px;background:#3498db;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Blue</b> — Feasible<br>
            <span style="display:inline-block;width:14px;height:14px;background:#bdc3c7;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Grey</b> — Not Recommended
        </div>
        """,
        unsafe_allow_html=True
    )
elif layer_choice == "Condition":
    st.sidebar.markdown(
        """
        <div style="line-height:2">
            <span style="display:inline-block;width:14px;height:14px;background:#1a9850;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Dark Green</b> — Very Good<br>
            <span style="display:inline-block;width:14px;height:14px;background:#66bd63;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Light Green</b> — Good<br>
            <span style="display:inline-block;width:14px;height:14px;background:#fee08b;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Yellow</b> — Fairly Good<br>
            <span style="display:inline-block;width:14px;height:14px;background:#f46d43;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Orange</b> — Repair Needed<br>
            <span style="display:inline-block;width:14px;height:14px;background:#d73027;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Red</b> — Urgent Repair
        </div>
        """,
        unsafe_allow_html=True
    )
elif layer_choice == "Surface Temperature":
    st.sidebar.markdown(
        """
        <div style="line-height:2">
            <span style="display:inline-block;width:14px;height:14px;background:#d73027;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Red</b> — High (&gt;66 °C)<br>
            <span style="display:inline-block;width:14px;height:14px;background:#fc8d59;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Orange</b> — Medium (64–66 °C)<br>
            <span style="display:inline-block;width:14px;height:14px;background:#fee08b;border-radius:3px;margin-right:6px;vertical-align:middle;"></span><b>Yellow</b> — Low (≤64 °C)
        </div>
        """,
        unsafe_allow_html=True
    )

# ---- SHORTEST ROUTE ----
st.sidebar.divider()
st.sidebar.subheader("🚶 Shortest Route")

# GPS capture button rendered in sidebar (outside Folium iframe — reliable)
with st.sidebar:
    components.html(gps_bridge_html, height=90)

# GPS status
if st.session_state.gps_lat is not None:
    st.sidebar.success(
        f"📡 GPS ready: {st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}"
    )
else:
    st.sidebar.warning("Capture your location above before routing.")

if target != "-- Select Building --":
    if st.sidebar.button("Get Shortest Route"):
        if st.session_state.gps_lat is None:
            st.sidebar.error("⚠️ Capture your location first using the button above.")
        else:
            sel_row = gdf[gdf["name"] == target]
            if not sel_row.empty:
                centroid = sel_row.geometry.centroid.iloc[0]
                dest_lat = centroid.y
                dest_lon = centroid.x
                user_lat = st.session_state.gps_lat
                user_lon = st.session_state.gps_lon

                osrm_url = (
                    f"http://router.project-osrm.org/route/v1/foot/"
                    f"{user_lon},{user_lat};{dest_lon},{dest_lat}"
                    f"?overview=full&geometries=geojson"
                )
                try:
                    resp = requests.get(osrm_url, timeout=10)
                    data = resp.json()
                    if data.get("code") == "Ok":
                        route = data["routes"][0]
                        st.session_state.route_geojson    = route["geometry"]
                        st.session_state.route_distance_m = route["distance"]
                        st.session_state.route_for        = target
                        st.session_state.route_user_lat   = user_lat
                        st.session_state.route_user_lon   = user_lon
                    else:
                        st.sidebar.error("Route not found.")
                except Exception as e:
                    st.sidebar.error(f"Routing error: {e}")
else:
    st.sidebar.info("Select a building above to enable routing.")

# Show persisted distance badge on every rerun
if st.session_state.route_distance_m is not None:
    st.sidebar.success(f"📏 Distance: **{st.session_state.route_distance_m:.0f} m**")

# Read route from session_state
route_geojson    = st.session_state.route_geojson
route_distance_m = st.session_state.route_distance_m
route_user_lat   = st.session_state.route_user_lat
route_user_lon   = st.session_state.route_user_lon

def get_color(feature):
    p = feature['properties']
    if layer_choice == "Condition":
        c = int(p.get('Asset_Cond', 1))
        return {1:"#1a9850", 2:"#66bd63", 3:"#fee08b", 4:"#f46d43", 5:"#d73027"}.get(c, "#ccc")
    elif layer_choice == "Solar suitability":
        s = str(p.get("Solar_Stat", "")).lower()
        return "#f1c40f" if "high" in s else "#3498db" if "feas" in s else "#bdc3c7"
    else:
        t = float(p.get("Heat_mean", 0))
        return "#d73027" if t > 66 else "#fc8d59" if t > 64 else "#fee08b"

# ---- MAP ----
m = folium.Map(location=[-1.0912, 37.0117], zoom_start=17, tiles="CartoDB Positron")

Fullscreen().add_to(m)
LocateControl(auto_start=False).add_to(m)

selected = None

if target != "-- Select Building --":
    selected = gdf[gdf["name"] == target]
    if not selected.empty:
        if route_geojson is None:
            bounds = selected.total_bounds
            m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

folium.GeoJson(
    map_dict,
    style_function=lambda f: {
        "fillColor": get_color(f),
        "color": "white",
        "weight": 1,
        "fillOpacity": 0.7
    },
    popup=folium.GeoJsonPopup(
        fields=["name","Asset_Dept","Condition_Text","Solar_Stat","Solar_Kwh","Heat_mean"],
        aliases=[
            "Building:",
            "Department:",
            "Condition:",
            "Solar Status:",
            "Solar Potential (kWh/yr):",
            "Surface Temp (°C):"
        ],
        localize=True
    )
).add_to(m)

# Highlight selected building
if selected is not None and not selected.empty:
    folium.GeoJson(
        selected.__geo_interface__,
        style_function=lambda x: {
            "color": "#00ffff",
            "weight": 4,
            "fillOpacity": 0.1
        }
    ).add_to(m)

# Draw route if available
if route_geojson is not None:
    folium.GeoJson(
        route_geojson,
        name="Shortest Route",
        style_function=lambda x: {
            "color": "#e74c3c",
            "weight": 4,
            "opacity": 0.85,
            "dashArray": "6,4"
        }
    ).add_to(m)

    folium.Marker(
        location=[route_user_lat, route_user_lon],
        popup="📍 Your Location",
        icon=folium.Icon(color="blue", icon="user", prefix="fa")
    ).add_to(m)

    if selected is not None and not selected.empty:
        centroid = selected.geometry.centroid.iloc[0]
        folium.Marker(
            location=[centroid.y, centroid.x],
            popup=f"🏛️ {target}\n{route_distance_m:.0f} m away",
            icon=folium.Icon(color="red", icon="building", prefix="fa")
        ).add_to(m)

    coords = route_geojson["coordinates"]
    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])

# ---- Live GPS tracking: pulsing dot + real-time progress along drawn route ----
# Bake the route coordinates into the JS so it can compute progress client-side.
# Python logic is completely unchanged — only this JS block is extended.
_route_coords_js = "null"
if route_geojson is not None:
    # Pass the route as a JS array of [lat, lon] pairs
    _route_coords_js = json.dumps(
        [[c[1], c[0]] for c in route_geojson["coordinates"]]
    )

live_gps_js = """
<style>
@keyframes livepin {
  0%,100% { box-shadow: 0 0 0 0 rgba(0,229,255,0.6); }
  50%      { box-shadow: 0 0 0 10px rgba(0,229,255,0); }
}
#nav-hud {
    position: absolute;
    bottom: 36px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 9999;
    background: rgba(10, 18, 35, 0.88);
    border: 1.5px solid #00e5ff;
    border-radius: 12px;
    padding: 10px 22px;
    font-family: monospace;
    color: #e0f7fa;
    text-align: center;
    pointer-events: none;
    min-width: 220px;
    box-shadow: 0 4px 18px rgba(0,229,255,0.15);
}
#nav-hud .hud-dist  { font-size: 22px; font-weight: bold; color: #00e5ff; }
#nav-hud .hud-label { font-size: 11px; color: #80deea; margin-bottom: 2px; }
#nav-hud .hud-eta   { font-size: 12px; color: #b2ebf2; margin-top: 4px; }
#nav-hud .hud-arr   { font-size: 14px; font-weight: bold; color: #69f0ae; }
</style>
<script>
(function () {
    /* Route coords baked in by Python — array of [lat,lon] or null */
    var ROUTE_LATLONS = """ + _route_coords_js + """;

    /* ── Haversine distance between two [lat,lon] points (metres) ── */
    function haversine(a, b) {
        var R = 6371000;
        var dLat = (b[0] - a[0]) * Math.PI / 180;
        var dLon = (b[1] - a[1]) * Math.PI / 180;
        var s = Math.sin(dLat/2) * Math.sin(dLat/2) +
                Math.cos(a[0]*Math.PI/180) * Math.cos(b[0]*Math.PI/180) *
                Math.sin(dLon/2) * Math.sin(dLon/2);
        return R * 2 * Math.atan2(Math.sqrt(s), Math.sqrt(1-s));
    }

    /* ── Find the index of the route point closest to a given [lat,lon] ── */
    function closestIdx(latlng) {
        var best = 0, bestD = Infinity;
        for (var i = 0; i < ROUTE_LATLONS.length; i++) {
            var d = haversine(latlng, ROUTE_LATLONS[i]);
            if (d < bestD) { bestD = d; best = i; }
        }
        return best;
    }

    /* ── Remaining route distance from index idx to end ── */
    function remainingDist(idx) {
        var d = 0;
        for (var i = idx; i < ROUTE_LATLONS.length - 1; i++) {
            d += haversine(ROUTE_LATLONS[i], ROUTE_LATLONS[i+1]);
        }
        return d;
    }

    /* ── Poll until Leaflet map is ready ── */
    var _tries = 0;
    var _poll = setInterval(function () {
        _tries++;
        var mapDiv = document.querySelector('.folium-map') ||
                     document.querySelector('[id^="map_"]');
        if (!mapDiv && _tries < 60) return;
        clearInterval(_poll);
        if (!mapDiv) return;
        var _map = mapDiv._leaflet_map;
        if (!_map) {
            var inner = setInterval(function () {
                _map = mapDiv._leaflet_map;
                if (_map) { clearInterval(inner); init(_map, mapDiv); }
            }, 300);
        } else {
            init(_map, mapDiv);
        }
    }, 300);

    function init(map, mapDiv) {
        if (!navigator.geolocation) return;

        /* ── Pulsing user dot ── */
        var userMarker = null;
        var liveIcon = L.divIcon({
            className: '',
            html: '<div style="width:14px;height:14px;background:#00e5ff;' +
                  'border:2px solid #fff;border-radius:50%;' +
                  'animation:livepin 1.4s ease-in-out infinite;"></div>',
            iconSize: [14,14], iconAnchor: [7,7]
        });

        /* ── Progress polylines (only created when route exists) ── */
        var walkedLine    = null;   // grey — already travelled
        var remainingLine = null;   // red dashed — still to go
        var arrived       = false;

        /* ── HUD panel ── */
        var hud = null;
        if (ROUTE_LATLONS) {
            hud = document.createElement('div');
            hud.id = 'nav-hud';
            hud.innerHTML =
                '<div class="hud-label">📍 DISTANCE REMAINING</div>' +
                '<div class="hud-dist" id="hud-dist">-- m</div>' +
                '<div class="hud-eta"  id="hud-eta">ETA: --</div>';
            mapDiv.style.position = 'relative';
            mapDiv.appendChild(hud);
        }

        navigator.geolocation.watchPosition(
            function (pos) {
                var lat = pos.coords.latitude;
                var lon = pos.coords.longitude;
                var userLL = [lat, lon];

                /* Move / create user dot */
                if (!userMarker) {
                    userMarker = L.marker(userLL, {
                        icon: liveIcon, zIndexOffset: 9999, title: 'You are here'
                    }).addTo(map);
                } else {
                    userMarker.setLatLng(userLL);
                }

                /* Keep dot in view */
                if (!map.getBounds().contains(userLL)) {
                    map.panTo(userLL);
                }

                /* ── Progress tracking (only when route is available) ── */
                if (!ROUTE_LATLONS || arrived) return;

                var idx      = closestIdx(userLL);
                var remDist  = remainingDist(idx);

                /* Arrived check — within 15 m of destination */
                var destLL   = ROUTE_LATLONS[ROUTE_LATLONS.length - 1];
                var distToDest = haversine(userLL, destLL);
                if (distToDest < 15) {
                    arrived = true;
                    if (hud) {
                        hud.innerHTML =
                            '<div class="hud-arr">✅ You have arrived!</div>';
                    }
                    /* Paint full route green on arrival */
                    if (walkedLine)    map.removeLayer(walkedLine);
                    if (remainingLine) map.removeLayer(remainingLine);
                    L.polyline(ROUTE_LATLONS, {
                        color: '#69f0ae', weight: 5, opacity: 0.9
                    }).addTo(map);
                    return;
                }

                /* Update HUD */
                if (hud) {
                    var distText = remDist < 1000
                        ? Math.round(remDist) + ' m'
                        : (remDist / 1000).toFixed(2) + ' km';
                    var etaSecs  = remDist / 1.4;   /* 1.4 m/s walking speed */
                    var etaText  = etaSecs < 60
                        ? Math.round(etaSecs) + 's walk'
                        : Math.round(etaSecs / 60) + ' min walk';
                    document.getElementById('hud-dist').innerText = distText;
                    document.getElementById('hud-eta').innerText  = 'ETA: ' + etaText;
                }

                /* Split route into walked (grey) and remaining (red dashed) */
                var walkedPart    = ROUTE_LATLONS.slice(0, idx + 1);
                var remainingPart = ROUTE_LATLONS.slice(idx);

                /* Include user's exact current position at the split point */
                walkedPart[walkedPart.length - 1]  = userLL;
                remainingPart[0]                   = userLL;

                if (walkedLine)    map.removeLayer(walkedLine);
                if (remainingLine) map.removeLayer(remainingLine);

                walkedLine = L.polyline(walkedPart, {
                    color: '#888', weight: 4, opacity: 0.5, dashArray: '4,4'
                }).addTo(map);

                remainingLine = L.polyline(remainingPart, {
                    color: '#e74c3c', weight: 4, opacity: 0.85, dashArray: '6,4'
                }).addTo(map);
            },
            function () { /* silently ignore GPS errors */ },
            { enableHighAccuracy: true, maximumAge: 2000, timeout: 10000 }
        );
    }
})();
</script>
"""

m.get_root().html.add_child(Element(live_gps_js))

st_folium(m, width="100%", height=600, key="jkuat_map")

# ---- METRICS ----
st.divider()
c1, c2, c3 = st.columns(3)

c1.metric("Avg Surface Temperature", f"{gdf['Heat_mean'].mean():.1f} °C")
c2.metric("Total Solar Potential",   f"{gdf['Solar_Kwh'].sum():,} kWh")
c3.metric("Total Buildings",         len(gdf))
