import os
import logging
from typing import Tuple

import pandas as pd
import requests
import folium
from folium.plugins import MarkerCluster
from dotenv import load_dotenv

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load Environment Variables
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


class DataManager:
    """Handles data creation and management using Pandas."""

    @staticmethod
    def load_data_from_csv() -> pd.DataFrame:
        """
        Loads the enriched data from CSV.
        """
        csv_path = os.path.join(os.path.dirname(__file__), 'trip_data.csv')
        
        if not os.path.exists(csv_path):
            logging.error("trip_data.csv not found! Run data_builder.py first.")
            return pd.DataFrame()
        
        df = pd.read_csv(csv_path)
        
        # Handle missing values for photos
        df['photo_reference'] = df['photo_reference'].fillna('')
        return df


class MapBuilder:
    """Constructs the Folium map."""

    def __init__(self):
        # Center map roughly on Portugal
        self.m = folium.Map(location=[39.5, -8.0], zoom_start=7)
        
        # Feature Groups
        self.fg_hostels = folium.FeatureGroup(name="Hostels")
        self.fg_campsites = folium.FeatureGroup(name="Campsites/Van Spots")
        self.fg_beaches = folium.FeatureGroup(name="Beaches")
        self.fg_hiking = folium.FeatureGroup(name="Hiking")
        self.fg_viewpoints = folium.FeatureGroup(name="Viewpoints")
        self.fg_routes = folium.FeatureGroup(name="Routes")
        
        # Marker Cluster for Hostels
        self.marker_cluster = MarkerCluster().add_to(self.fg_hostels)

    def add_locations(self, df: pd.DataFrame, feature_group, color: str, icon: str):
        """Adds markers to the map based on the dataframe."""
        for _, row in df.iterrows():
            # Construct HTML Popup
            photo_url = "https://via.placeholder.com/150?text=Image"
            if row['photo_reference']:
                photo_url = f"https://places.googleapis.com/v1/{row['photo_reference']}/media?key={GOOGLE_API_KEY}&maxHeightPx=400&maxWidthPx=400"
            
            html = f"""
            <div style="width:200px">
                <h4>{row['name']}</h4>
                <p><b>Type:</b> {row['type']}</p>
                <p><b>Amenity Score:</b> {row['amenity_score']}/100</p>
                <p><b>Google Rating:</b> {row['rating']} ({row['user_ratings_total']} reviews)</p>
                <img src="{photo_url}" alt="Place Image" style="width:100%">
            </div>
            """
            
            popup = folium.Popup(html, max_width=250)
            
            # Create HTML Tooltip with Image
            tooltip_html = f"""
            <div style="text-align:center; font-family:sans-serif;">
                <b>{row['name']}</b><br>
                <img src="{photo_url}" width="150px" style="border-radius:8px; margin-top:5px;">
            </div>
            """
            
            # Use CircleMarker for a cleaner, modern "Data" look
            marker = folium.CircleMarker(
                location=[row['lat'], row['lon']],
                radius=8,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.7,
                popup=popup,
                tooltip=folium.Tooltip(tooltip_html, sticky=True)
            )
            
            marker.add_to(feature_group)

    def add_route(self):
        """Draws the driving route: Lisbon -> Monchique -> Faro -> Porto."""
        # Coordinates for the hubs
        route_coords = [
            (38.7223, -9.1393), # Lisbon
            (37.3167, -8.5500), # Monchique
            (37.0179, -7.9308), # Faro
            (41.1579, -8.6291)  # Porto
        ]
        
        # Use OSRM for driving directions (Free API)
        # OSRM expects Lon,Lat
        locs = [f"{lon},{lat}" for lat, lon in route_coords]
        url = f"http://router.project-osrm.org/route/v1/driving/{';'.join(locs)}?overview=full&geometries=geojson"
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                folium.GeoJson(
                    data['routes'][0]['geometry'],
                    name="Driving Route",
                    style_function=lambda x: {'color': 'blue', 'weight': 4, 'opacity': 0.7}
                ).add_to(self.fg_routes)
                logging.info("Route calculated via OSRM.")
                return
        except Exception as e:
            logging.warning(f"OSRM Routing failed: {e}. Using straight lines.")

        folium.PolyLine(route_coords, color="red", weight=2.5).add_to(self.fg_routes)

    def save_map(self, filename: str):
        """Finalizes and saves the map."""
        self.fg_hostels.add_to(self.m)
        self.fg_campsites.add_to(self.m)
        self.fg_beaches.add_to(self.m)
        self.fg_hiking.add_to(self.m)
        self.fg_viewpoints.add_to(self.m)
        self.fg_routes.add_to(self.m)
        
        folium.LayerControl().add_to(self.m)
        self.m.save(filename)
        logging.info(f"Map saved to {filename}")


if __name__ == "__main__":
    # 1. Load Data
    df = DataManager.load_data_from_csv()
    
    if df.empty:
        logging.error("No data loaded. Exiting.")
        exit()
    
    # 2. Initialize Map Builder
    builder = MapBuilder()
    
    # 3. Add Data to Map (Segmented by type)
    logging.info("Processing Locations...")
    builder.add_locations(df[df['type'] == 'Hostel'], builder.marker_cluster, "blue", "bed")
    builder.add_locations(df[df['type'] == 'Campsite'], builder.fg_campsites, "green", "campground")
    
    builder.add_locations(df[df['type'] == 'Beach'], builder.fg_beaches, "orange", "umbrella-beach")
    builder.add_locations(df[df['type'] == 'Hiking'], builder.fg_hiking, "darkgreen", "tree")
    builder.add_locations(df[df['type'] == 'Viewpoint'], builder.fg_viewpoints, "purple", "camera")
    
    # 4. Add Route
    builder.add_route()
    
    # 5. Save
    output_path = r"c:\Users\sffra\Downloads\BSE 2025-2026\portovan\portugal_trip_map.html"
    builder.save_map(output_path)