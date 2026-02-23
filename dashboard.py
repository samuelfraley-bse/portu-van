import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import os
import numpy as np
import requests
import random
from dotenv import load_dotenv

# --- Configuration ---
st.set_page_config(page_title="PortuVan", layout="wide")

# Load API Key
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Try to get key from Streamlit secrets (Cloud) or environment (Local)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY and hasattr(st, "secrets") and "GOOGLE_API_KEY" in st.secrets:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]

CSV_PATH = os.path.join(os.path.dirname(__file__), 'trip_data.csv')
LISBON_COORDS = (38.7223, -9.1393)
PORTO_COORDS = (41.1579, -8.6291)
FARO_COORDS = (37.0179, -7.9308)

# --- Data Loading & Processing ---
@st.cache_data
def load_data():
    if not os.path.exists(CSV_PATH):
        st.error("Data file not found! Run data_builder.py first.")
        return pd.DataFrame()
    
    df = pd.read_csv(CSV_PATH)
    
    # Clean numeric columns
    df['rating'] = pd.to_numeric(df['rating'], errors='coerce').fillna(0)
    df['user_ratings_total'] = pd.to_numeric(df['user_ratings_total'], errors='coerce').fillna(0)
    df['amenity_score'] = pd.to_numeric(df['amenity_score'], errors='coerce').fillna(0)
    
    # Calculate "Weighted Score" (Bayesian-like or simple log weight)
    # Score = Rating * log10(Reviews + 1) + (Amenity Score / 20)
    # This balances popularity (reviews) with quality (rating) and wildness (amenity)
    df['weighted_score'] = df.apply(
        lambda x: x['rating'] * np.log10(x['user_ratings_total'] + 1) + (x['amenity_score'] / 25), 
        axis=1
    )
    
    return df

def get_route_segment(start, end):
    """Fetch driving route geometry between two points from OSRM."""
    # OSRM expects Lon,Lat
    locs = [f"{start[1]},{start[0]}", f"{end[1]},{end[0]}"]
    url = f"http://router.project-osrm.org/route/v1/driving/{';'.join(locs)}?overview=full&geometries=geojson"
    try:
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            data = r.json()
            route = data['routes'][0]
            return route['geometry'], route['distance'], route['duration']
    except:
        return None, 0, 0
    return None, 0, 0

# --- Trip Logic ---
def generate_random_trip(df, preference="Balanced"):
    """
    Generates a logical trip: Lisbon -> Alentejo (Coast) -> Algarve -> Center -> Porto
    """
    trip_stops = []
    
    # 1. Start
    trip_stops.append({"name": "Lisbon (Start)", "lat": LISBON_COORDS[0], "lon": LISBON_COORDS[1], "type": "Start", "rating": 5.0})

    # Filter Data based on preference
    if preference == "Wild & Nature":
        candidates = df[df['amenity_score'] > 70]
    elif preference == "Popular & Social":
        candidates = df[df['user_ratings_total'] > 500]
    else:
        candidates = df

    # 2. Stop 1: Alentejo Coast (Lat between 37.3 and 38.6) - Going South
    alentejo = candidates[(candidates['lat'] < 38.6) & (candidates['lat'] > 37.3)]
    if not alentejo.empty:
        # Pick 1 stop on the way down
        stop1 = alentejo.sample(1)
        trip_stops.append(stop1.iloc[0].to_dict())

    # 3. Stop 2: Algarve (Lat < 37.2)
    algarve = candidates[candidates['lat'] < 37.2]
    if not algarve.empty:
        # Pick best rated instead of random for Algarve
        best_spot = algarve.sort_values('weighted_score', ascending=False).head(5).sample(1)
        trip_stops.append(best_spot.iloc[0].to_dict())

    # 4. Stop 3: Return Trip (Central Portugal) (Lat > 39.0 and < 40.8)
    return_leg = candidates[(candidates['lat'] > 39.0) & (candidates['lat'] < 40.8)]
    if not return_leg.empty:
        stop = return_leg.sample(1)
        trip_stops.append(stop.iloc[0].to_dict())

    # 5. End
    trip_stops.append({"name": "Porto (End)", "lat": PORTO_COORDS[0], "lon": PORTO_COORDS[1], "type": "End", "rating": 5.0})
    
    return trip_stops

# --- UI Layout ---
st.title("PortuVan Trip Dashboard")

df = load_data()

if df.empty:
    st.stop()

# Sidebar
st.sidebar.header("Filters")
selected_types = st.sidebar.multiselect("Filter Categories", df['type'].unique(), default=df['type'].unique())
min_rating = st.sidebar.slider("Minimum Rating", 0.0, 5.0, 4.0)

filtered_df = df[
    (df['type'].isin(selected_types)) & 
    (df['rating'] >= min_rating)
]

# Tabs
tab1, tab2 = st.tabs(["Top Picks", "Trip Generator"])

with tab1:
    st.subheader("Best Rated Spots by Category")
    
    # Map for Top Picks
    m_overview = folium.Map(location=[39.5, -8.0], zoom_start=7, tiles='CartoDB dark_matter')
    categories = ['Beach', 'Campsite', 'Viewpoint']
    
    for cat in categories:
        picks = df[df['type'] == cat].sort_values('weighted_score', ascending=False).head(5)
        for _, row in picks.iterrows():
            color = "blue"
            icon = "info-sign"
            if row['type'] == 'Campsite': color = "green"; icon="campground"
            elif row['type'] == 'Beach': color = "orange"; icon="umbrella-beach"
            elif row['type'] == 'Viewpoint': color = "purple"; icon="camera"
            
            folium.Marker(
                [row['lat'], row['lon']],
                popup=f"<b>{row['name']}</b><br>Rating: {row['rating']}",
                icon=folium.Icon(color=color, icon=icon, prefix='fa')
            ).add_to(m_overview)
            
    st_folium(m_overview, width="100%", height=500)
    
    cols = st.columns(3)
    
    for i, cat in enumerate(categories):
        with cols[i]:
            st.markdown(f"### Best {cat}s")
            top_picks = df[df['type'] == cat].sort_values('weighted_score', ascending=False).head(5)
            
            for _, row in top_picks.iterrows():
                # Construct Google Maps Link
                gmaps_url = f"https://www.google.com/maps/search/?api=1&query={row['lat']},{row['lon']}"
                
                # Display Photo if available
                if GOOGLE_API_KEY and pd.notna(row['photo_reference']) and row['photo_reference']:
                    photo_url = f"https://places.googleapis.com/v1/{row['photo_reference']}/media?key={GOOGLE_API_KEY}&maxHeightPx=400&maxWidthPx=400"
                    st.image(photo_url, use_container_width=True)
                
                st.markdown(f"""
                [**{row['name']}**]({gmaps_url})  
                Rating: {row['rating']} ({int(row['user_ratings_total'])} reviews)  
                Wild Score: {int(row['amenity_score'])}
                ---
                """)

with tab2:
    col1, col2 = st.columns([1, 3])
    
    with col1:
        st.subheader("Plan Your Adventure")
        # Mobile-friendly: Collapse settings to save space
        with st.expander("⚙️ Trip Settings", expanded=True):
            preference = st.radio("Trip Style", ["Balanced", "Wild & Nature", "Popular & Social"])
            if st.button("Generate New Route", type="primary", use_container_width=True):
                st.session_state['trip'] = generate_random_trip(df, preference)
            
    with col2:
        # Initialize map
        m = folium.Map(location=[39.5, -8.0], zoom_start=7, tiles='CartoDB dark_matter')
        
        # Check if trip exists in session state
        if 'trip' in st.session_state:
            trip = st.session_state['trip']
            
            # Calculate Route Segments & Drive Times
            total_dist = 0
            total_duration = 0
            colors = ["#FF4B4B", "#1C83E1", "#00C0F2", "#FFC107", "#9C27B0", "#E91E63"] # Cycle colors
            
            trip[0]['drive_time'] = "Start" # First stop
            
            for i in range(len(trip) - 1):
                start = (trip[i]['lat'], trip[i]['lon'])
                end = (trip[i+1]['lat'], trip[i+1]['lon'])
                
                geo, dist, dur = get_route_segment(start, end)
                
                total_dist += dist
                total_duration += dur
                
                # Format drive time for next stop
                hours = int(dur // 3600)
                mins = int((dur % 3600) // 60)
                time_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"
                trip[i+1]['drive_time'] = time_str
                
                # Draw Segment
                color = colors[i % len(colors)]
                if geo:
                    folium.GeoJson(geo, style_function=lambda x, c=color: {'color': c, 'weight': 5, 'opacity': 0.8}).add_to(m)
                else:
                    folium.PolyLine([start, end], color=color, weight=5, opacity=0.8).add_to(m)
            
            # Display Trip Summary
            total_miles = total_dist * 0.000621371
            total_hours = total_duration / 3600
            
            st.markdown("### 📊 Trip Summary")
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Distance", f"{total_miles:.1f} mi")
            m2.metric("Driving Time", f"{total_hours:.1f} hrs")
            m3.metric("Total Stops", len(trip))
            
            # Draw Modern Markers (Numbered)
            for i, stop in enumerate(trip):
                # Get Photo URL for Popup
                photo_html = ""
                if GOOGLE_API_KEY and 'photo_reference' in stop and pd.notna(stop['photo_reference']) and stop['photo_reference']:
                    p_url = f"https://places.googleapis.com/v1/{stop['photo_reference']}/media?key={GOOGLE_API_KEY}&maxHeightPx=200&maxWidthPx=200"
                    photo_html = f'<img src="{p_url}" style="width:100%; border-radius:5px; margin-bottom:5px;">'

                popup_html = f"""
                <div style="width:150px; font-family:sans-serif;">
                    {photo_html}
                    <b>{i+1}. {stop['name']}</b><br>
                    ⭐ {stop['rating']}
                </div>
                """
                
                # Custom CSS Marker (Java/Modern Style)
                # Use same color as the leg leading to it (or previous leg)
                bg_color = colors[(i-1) % len(colors)] if i > 0 else "#555"
                
                icon_html = f"""
                <div style="
                    background-color: {bg_color}; color: white; border-radius: 50%; 
                    width: 30px; height: 30px; 
                    display: flex; justify-content: center; align-items: center; 
                    font-weight: bold; font-family: sans-serif; border: 2px solid white;
                    box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
                    {i+1}
                </div>"""
                
                folium.Marker(
                    [stop['lat'], stop['lon']],
                    popup=folium.Popup(popup_html, max_width=200),
                    icon=folium.DivIcon(html=icon_html)
                ).add_to(m)
                
            st.success(f"Generated a {len(trip)} stop itinerary!")
            
        else:
            # Show all filtered points if no trip generated yet
            for _, row in filtered_df.iterrows():
                color = "green" if row['type'] == 'Campsite' else "blue"
                folium.CircleMarker(
                    location=[row['lat'], row['lon']],
                    radius=5,
                    color=color,
                    fill=True,
                    fill_opacity=0.7,
                    popup=row['name']
                ).add_to(m)

        st_folium(m, width="100%", height=600)

    if 'trip' in st.session_state:
        st.subheader("Your Itinerary")
        trip_df = pd.DataFrame(st.session_state['trip'])
        
        # Add clickable Google Maps link column
        trip_df['google_maps'] = trip_df.apply(lambda x: f"https://www.google.com/maps/search/?api=1&query={x['lat']},{x['lon']}", axis=1)
        
        st.dataframe(
            trip_df[['name', 'type', 'rating', 'drive_time', 'google_maps']],
            column_config={
                "google_maps": st.column_config.LinkColumn("Directions", display_text="Open Maps"),
                "rating": st.column_config.NumberColumn("Rating", format="%.1f ⭐"),
                "drive_time": "Drive Time"
            },
            use_container_width=True,
            hide_index=True
        )
        
        # Trip Gallery
        st.subheader("📸 Trip Gallery")
        gallery_cols = st.columns(4)
        for i, stop in enumerate(trip):
            if GOOGLE_API_KEY and 'photo_reference' in stop and pd.notna(stop['photo_reference']) and stop['photo_reference']:
                photo_url = f"https://places.googleapis.com/v1/{stop['photo_reference']}/media?key={GOOGLE_API_KEY}&maxHeightPx=400&maxWidthPx=400"
                with gallery_cols[i % 4]:
                    st.image(photo_url, caption=f"{i+1}. {stop['name']}", use_container_width=True)
