import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import os
import numpy as np
import requests
from dotenv import load_dotenv

# --- Configuration ---
st.set_page_config(page_title="PortuVan", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600&display=swap');

html, body, [class*="css"], .stMarkdown, .stTextInput, .stSelectbox,
.stRadio, .stButton, .stMetric, .stDataFrame, .stTab, .stExpander,
button, input, label, div, p, span, h1, h2, h3, h4 {
    font-family: 'Space Grotesk', sans-serif !important;
}

/* Tighten header */
h1 { font-weight: 500 !important; letter-spacing: -0.5px; }
h2, h3 { font-weight: 400 !important; }

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #111111 !important;
    border-right: 1px solid #222 !important;
}

/* Metric cards */
[data-testid="stMetric"] {
    background-color: #161616;
    border: 1px solid #222;
    border-radius: 6px;
    padding: 12px 16px;
}

/* Remove default Streamlit top padding */
.block-container { padding-top: 1.5rem !important; }

/* Tab styling */
[data-testid="stTab"] { font-size: 0.9rem; letter-spacing: 0.3px; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #111; }
::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

# Load API Key
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY and hasattr(st, "secrets") and "GOOGLE_API_KEY" in st.secrets:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]

if not GOOGLE_API_KEY:
    st.warning("Google API Key not found. Photos will not load.")

CSV_PATH = os.path.join(os.path.dirname(__file__), 'trip_data.csv')
LISBON_COORDS = (38.7223, -9.1393)
PORTO_COORDS = (41.1579, -8.6291)

CATEGORY_COLORS = {
    "Beach":     {"folium": "orange",  "hex": "#f59e0b"},
    "Campsite":  {"folium": "green",   "hex": "#22c55e"},
    "Viewpoint": {"folium": "purple",  "hex": "#a855f7"},
    "Hiking":    {"folium": "red",     "hex": "#ef4444"},
    "Hostel":    {"folium": "blue",    "hex": "#3b82f6"},
}

# --- Data ---
@st.cache_data
def load_data():
    if not os.path.exists(CSV_PATH):
        st.error("Data file not found. Run data_builder.py first.")
        return pd.DataFrame()
    df = pd.read_csv(CSV_PATH)
    df['rating'] = pd.to_numeric(df['rating'], errors='coerce').fillna(0)
    df['user_ratings_total'] = pd.to_numeric(df['user_ratings_total'], errors='coerce').fillna(0)
    df['amenity_score'] = pd.to_numeric(df['amenity_score'], errors='coerce').fillna(0)
    df['weighted_score'] = df.apply(
        lambda x: x['rating'] * np.log10(x['user_ratings_total'] + 1) + (x['amenity_score'] / 25),
        axis=1
    )
    return df


def get_route_segment(start, end):
    locs = [f"{start[1]},{start[0]}", f"{end[1]},{end[0]}"]
    url = f"http://router.project-osrm.org/route/v1/driving/{';'.join(locs)}?overview=full&geometries=geojson"
    try:
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            data = r.json()
            route = data['routes'][0]
            return route['geometry'], route['distance'], route['duration']
    except:
        pass
    return None, 0, 0


def generate_random_trip(df, preference="Balanced"):
    trip_stops = []
    trip_stops.append({"name": "Lisbon", "lat": LISBON_COORDS[0], "lon": LISBON_COORDS[1], "type": "Start", "rating": 5.0})

    if preference == "Wild & Nature":
        candidates = df[df['amenity_score'] > 70]
    elif preference == "Popular & Social":
        candidates = df[df['user_ratings_total'] > 500]
    else:
        candidates = df

    alentejo = candidates[(candidates['lat'] < 38.6) & (candidates['lat'] > 37.3)]
    if not alentejo.empty:
        trip_stops.append(alentejo.sample(1).iloc[0].to_dict())

    algarve = candidates[candidates['lat'] < 37.2]
    if not algarve.empty:
        trip_stops.append(algarve.sort_values('weighted_score', ascending=False).head(5).sample(1).iloc[0].to_dict())

    center = candidates[(candidates['lat'] > 39.0) & (candidates['lat'] < 40.8)]
    if not center.empty:
        trip_stops.append(center.sample(1).iloc[0].to_dict())

    trip_stops.append({"name": "Porto", "lat": PORTO_COORDS[0], "lon": PORTO_COORDS[1], "type": "End", "rating": 5.0})
    return trip_stops


# --- App ---
st.title("PortuVan")

df = load_data()
if df.empty:
    st.stop()

# Sidebar
with st.sidebar:
    st.markdown("### Filters")
    selected_types = st.multiselect("Categories", df['type'].unique(), default=df['type'].unique())
    min_rating = st.slider("Min Rating", 0.0, 5.0, 4.0, step=0.1)

filtered_df = df[df['type'].isin(selected_types) & (df['rating'] >= min_rating)]

tab1, tab2, tab3 = st.tabs(["Top Picks", "Trip Generator", "Territory"])

# ── Tab 1: Top Picks ──────────────────────────────────────────────────────────
with tab1:
    st.subheader("Best Rated Spots by Category")

    m_overview = folium.Map(location=[39.5, -8.0], zoom_start=7, tiles='CartoDB dark_matter')
    categories = ['Beach', 'Campsite', 'Viewpoint']

    for cat in categories:
        picks = df[df['type'] == cat].sort_values('weighted_score', ascending=False).head(5)
        c = CATEGORY_COLORS.get(cat, {"folium": "blue", "hex": "#3b82f6"})
        for _, row in picks.iterrows():
            folium.Marker(
                [row['lat'], row['lon']],
                popup=f"<b>{row['name']}</b><br>Rating: {row['rating']}",
                icon=folium.Icon(color=c["folium"], prefix='fa', icon='circle')
            ).add_to(m_overview)

    st_folium(m_overview, width="100%", height=480)

    cols = st.columns(3)
    for i, cat in enumerate(categories):
        with cols[i]:
            st.markdown(f"**{cat}s**")
            top_picks = df[df['type'] == cat].sort_values('weighted_score', ascending=False).head(5)
            for _, row in top_picks.iterrows():
                gmaps_url = f"https://www.google.com/maps/search/?api=1&query={row['lat']},{row['lon']}"
                if GOOGLE_API_KEY and pd.notna(row.get('photo_reference')) and row['photo_reference']:
                    photo_url = f"https://places.googleapis.com/v1/{row['photo_reference']}/media?key={GOOGLE_API_KEY}&maxHeightPx=400&maxWidthPx=400"
                    st.image(photo_url, use_container_width=True)
                st.markdown(f"""[**{row['name']}**]({gmaps_url})
{row['rating']} &nbsp;·&nbsp; {int(row['user_ratings_total'])} reviews
Wild score: {int(row['amenity_score'])}

---""")

# ── Tab 2: Trip Generator ──────────────────────────────────────────────────────
with tab2:
    col1, col2 = st.columns([1, 3])

    with col1:
        st.subheader("Plan a Route")
        with st.expander("Trip Settings", expanded=True):
            preference = st.radio("Style", ["Balanced", "Wild & Nature", "Popular & Social"])
            if st.button("Generate Route", type="primary", use_container_width=True):
                st.session_state['trip'] = generate_random_trip(df, preference)

    with col2:
        m = folium.Map(location=[39.5, -8.0], zoom_start=7, tiles='CartoDB dark_matter')
        colors = ["#e0633a", "#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ec4899"]

        if 'trip' in st.session_state:
            trip = st.session_state['trip']
            total_dist = 0
            total_duration = 0
            trip[0]['drive_time'] = "Start"

            for i in range(len(trip) - 1):
                start = (trip[i]['lat'], trip[i]['lon'])
                end = (trip[i+1]['lat'], trip[i+1]['lon'])
                geo, dist, dur = get_route_segment(start, end)
                total_dist += dist
                total_duration += dur

                hours = int(dur // 3600)
                mins = int((dur % 3600) // 60)
                trip[i+1]['drive_time'] = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"

                color = colors[i % len(colors)]
                if geo:
                    folium.GeoJson(geo, style_function=lambda x, c=color: {'color': c, 'weight': 4, 'opacity': 0.85}).add_to(m)
                else:
                    folium.PolyLine([start, end], color=color, weight=4, opacity=0.85).add_to(m)

            total_miles = total_dist * 0.000621371
            total_hours = total_duration / 3600

            st.markdown("**Trip Summary**")
            m1, m2, m3 = st.columns(3)
            m1.metric("Distance", f"{total_miles:.0f} mi")
            m2.metric("Drive Time", f"{total_hours:.1f} hrs")
            m3.metric("Stops", len(trip))

            for i, stop in enumerate(trip):
                photo_html = ""
                if GOOGLE_API_KEY and 'photo_reference' in stop and pd.notna(stop.get('photo_reference')) and stop['photo_reference']:
                    p_url = f"https://places.googleapis.com/v1/{stop['photo_reference']}/media?key={GOOGLE_API_KEY}&maxHeightPx=200&maxWidthPx=200"
                    photo_html = f'<img src="{p_url}" style="width:100%; border-radius:4px; margin-bottom:6px;">'

                popup_html = f"""
                <div style="width:150px; font-family:sans-serif; font-size:13px;">
                    {photo_html}
                    <b>{i+1}. {stop['name']}</b><br>
                    {stop['rating']}
                </div>"""

                bg = colors[(i-1) % len(colors)] if i > 0 else "#444"
                icon_html = f"""<div style="
                    background:{bg}; color:#fff; border-radius:50%;
                    width:28px; height:28px; display:flex; justify-content:center;
                    align-items:center; font-weight:600; font-size:12px;
                    border:2px solid rgba(255,255,255,0.3);
                    box-shadow:0 2px 6px rgba(0,0,0,0.4);">{i+1}</div>"""

                folium.Marker(
                    [stop['lat'], stop['lon']],
                    popup=folium.Popup(popup_html, max_width=200),
                    icon=folium.DivIcon(html=icon_html)
                ).add_to(m)

            st.success(f"{len(trip)}-stop route ready.")

        else:
            for _, row in filtered_df.iterrows():
                c = CATEGORY_COLORS.get(row['type'], {"hex": "#888"})
                folium.CircleMarker(
                    location=[row['lat'], row['lon']],
                    radius=5,
                    color=c["hex"],
                    fill=True,
                    fill_opacity=0.7,
                    popup=row['name']
                ).add_to(m)

        st_folium(m, width="100%", height=580)

    if 'trip' in st.session_state:
        trip = st.session_state['trip']
        st.markdown("**Itinerary**")
        trip_df = pd.DataFrame(trip)
        trip_df['google_maps'] = trip_df.apply(
            lambda x: f"https://www.google.com/maps/search/?api=1&query={x['lat']},{x['lon']}", axis=1
        )
        st.dataframe(
            trip_df[['name', 'type', 'rating', 'drive_time', 'google_maps']],
            column_config={
                "google_maps": st.column_config.LinkColumn("Directions", display_text="Open Maps"),
                "rating": st.column_config.NumberColumn("Rating", format="%.1f"),
                "drive_time": "Drive Time",
            },
            use_container_width=True,
            hide_index=True
        )

        if GOOGLE_API_KEY:
            st.markdown("**Gallery**")
            gallery_cols = st.columns(4)
            for i, stop in enumerate(trip):
                if 'photo_reference' in stop and pd.notna(stop.get('photo_reference')) and stop['photo_reference']:
                    photo_url = f"https://places.googleapis.com/v1/{stop['photo_reference']}/media?key={GOOGLE_API_KEY}&maxHeightPx=400&maxWidthPx=400"
                    with gallery_cols[i % 4]:
                        st.image(photo_url, caption=stop['name'], use_container_width=True)

# ── Tab 3: Territory ──────────────────────────────────────────────────────────
with tab3:
    st.subheader("Coverage Map")

    tcol1, tcol2 = st.columns([1, 4])

    with tcol1:
        st.markdown("**Layers**")
        show_heat = st.checkbox("Heatmap", value=True)
        st.markdown("**Categories**")
        active_cats = []
        for cat in df['type'].unique():
            c = CATEGORY_COLORS.get(cat, {"hex": "#888"})
            checked = st.checkbox(
                cat,
                value=True,
                key=f"terr_{cat}"
            )
            if checked:
                active_cats.append(cat)

        st.markdown("---")
        st.markdown("**Metric**")
        heat_metric = st.radio("Weight by", ["Score", "Reviews", "Rating"], label_visibility="collapsed")

    with tcol2:
        t_map = folium.Map(location=[39.2, -8.2], zoom_start=7, tiles='CartoDB dark_matter')

        # Build heatmap data
        territory_df = df[df['type'].isin(active_cats)] if active_cats else df

        if show_heat and not territory_df.empty:
            if heat_metric == "Score":
                weights = territory_df['weighted_score'].clip(lower=0)
            elif heat_metric == "Reviews":
                weights = np.log10(territory_df['user_ratings_total'] + 1)
            else:
                weights = territory_df['rating']

            max_w = weights.max() if weights.max() > 0 else 1
            heat_data = [
                [row['lat'], row['lon'], w / max_w]
                for (_, row), w in zip(territory_df.iterrows(), weights)
            ]
            HeatMap(
                heat_data,
                radius=18,
                blur=22,
                min_opacity=0.3,
                gradient={0.2: '#1e3a5f', 0.5: '#e0633a', 0.8: '#fbbf24', 1.0: '#ffffff'}
            ).add_to(t_map)

        # Category dot layers
        for cat in active_cats:
            cat_df = territory_df[territory_df['type'] == cat]
            c = CATEGORY_COLORS.get(cat, {"hex": "#888888"})
            fg = folium.FeatureGroup(name=cat, show=True)
            for _, row in cat_df.iterrows():
                folium.CircleMarker(
                    location=[row['lat'], row['lon']],
                    radius=4,
                    color=c["hex"],
                    fill=True,
                    fill_color=c["hex"],
                    fill_opacity=0.85,
                    weight=1,
                    popup=folium.Popup(
                        f"<b>{row['name']}</b><br>{cat}<br>Rating: {row['rating']:.1f}",
                        max_width=180
                    )
                ).add_to(fg)
            fg.add_to(t_map)

        folium.LayerControl(collapsed=False).add_to(t_map)
        st_folium(t_map, width="100%", height=580)

    # Region breakdown
    st.markdown("---")
    st.markdown("**Spot Density by Region**")

    def assign_region(lat):
        if lat < 37.2:
            return "Algarve"
        elif lat < 38.5:
            return "Alentejo"
        elif lat < 39.8:
            return "Centro Sul"
        elif lat < 40.8:
            return "Centro Norte"
        else:
            return "Norte"

    df['region'] = df['lat'].apply(assign_region)

    region_stats = df.groupby(['region', 'type']).size().unstack(fill_value=0)
    region_order = ["Algarve", "Alentejo", "Centro Sul", "Centro Norte", "Norte"]
    region_stats = region_stats.reindex([r for r in region_order if r in region_stats.index])

    st.dataframe(region_stats, use_container_width=True)
