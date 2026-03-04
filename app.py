import streamlit as st
import geopandas as gpd
import folium
from folium.plugins import LocateControl, Fullscreen
import json
from streamlit_folium import st_folium

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

# ---- SIDEBAR ----
st.sidebar.subheader("📍 Navigation")

names_list = sorted(gdf['name'].dropna().unique().tolist())
search_list = ["-- Select Building --"] + names_list

target = st.sidebar.selectbox("Find Building:", search_list)

layer_choice = st.sidebar.radio(
    "View Mode:",
    ["Condition", "Solar suitability", "Surface Temperature"]
)

def get_color(feature):
    p = feature['properties']
    if layer_choice == "Condition":
        c = int(p.get('Asset_Cond',1))
        return {1:"#1a9850", 2:"#66bd63", 3:"#fee08b", 4:"#f46d43", 5:"#d73027"}.get(c,"#ccc")
    elif layer_choice == "Solar suitability":
        s = str(p.get("Solar_Stat","")).lower()
        return "#f1c40f" if "high" in s else "#3498db" if "feas" in s else "#bdc3c7"
    else:
        t = float(p.get("Heat_mean",0))
        return "#d73027" if t>66 else "#fc8d59" if t>64 else "#fee08b"

# ---- MAP ----
m = folium.Map(location=[-1.0912, 37.0117], zoom_start=17, tiles="CartoDB Positron")

Fullscreen().add_to(m)
LocateControl(auto_start=False).add_to(m)

selected = None

if target != "-- Select Building --":
    selected = gdf[gdf["name"] == target]
    if not selected.empty:
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

st_folium(m, width="100%", height=600, key="jkuat_map")

# ---- METRICS ----
st.divider()
c1, c2, c3 = st.columns(3)

c1.metric("Avg Surface Temperature", f"{gdf['Heat_mean'].mean():.1f} °C")
c2.metric("Total Solar Potential", f"{gdf['Solar_Kwh'].sum():,} kWh")
c3.metric("Total Buildings", len(gdf))