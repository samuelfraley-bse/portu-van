import os
import time
import logging
import pandas as pd
import requests
from dotenv import load_dotenv
from typing import Dict, Tuple

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load Environment Variables
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Set to True to skip slow Overpass API calls and recover data quickly
FAST_MODE = True

class APIService:
    """Handles interactions with external APIs (Google Places, Overpass)."""

    @staticmethod
    def fetch_google_places_data(lat: float, lon: float) -> Dict[str, str]:
        if not GOOGLE_API_KEY:
            return {"rating": "N/A", "user_ratings_total": "0", "photo_reference": None}

        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_API_KEY,
            "X-Goog-FieldMask": "places.rating,places.userRatingCount,places.photos"
        }
        
        payload = {
            "includedTypes": ["lodging", "campground", "hostel"],
            "maxResultCount": 1,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": 500.0
                }
            }
        }

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            if data.get("places"):
                place = data["places"][0]
                photos = place.get("photos", [])
                photo_ref = photos[0]["name"] if photos else None
                
                return {
                    "rating": str(place.get("rating", "N/A")),
                    "user_ratings_total": str(place.get("userRatingCount", 0)),
                    "photo_reference": photo_ref
                }
        except Exception as e:
            logging.error(f"Error fetching Google Places data: {e}")

        return {"rating": "N/A", "user_ratings_total": "0", "photo_reference": None}

    @staticmethod
    def search_places(lat: float, lon: float, place_type: str) -> list:
        """Searches for places of a specific type around a location."""
        if not GOOGLE_API_KEY:
            return []
        
        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_API_KEY,
            "X-Goog-FieldMask": "places.displayName,places.location,places.rating,places.userRatingCount,places.photos"
        }
        
        payload = {
            "includedTypes": [place_type],
            "maxResultCount": 10,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": 15000.0 # 15km radius search
                }
            }
        }

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            results = data.get("places", [])
            logging.info(f"API Search: Found {len(results)} places for type '{place_type}'")
            return results
        except Exception as e:
            logging.error(f"Error searching for {place_type}: {e}")
            return []

    @staticmethod
    def get_amenity_score(lat: float, lon: float) -> int:
        if FAST_MODE:
            return 50 # Return default score to speed up process
            
        overpass_url = "http://overpass-api.de/api/interpreter"
        query = f"""
        [out:json][timeout:25];
        (
          node["natural"="beach"](around:5000, {lat}, {lon});
          node["tourism"="viewpoint"](around:5000, {lat}, {lon});
          way["highway"="path"]["sac_scale"](around:5000, {lat}, {lon});
        );
        out count;
        """

        for attempt in range(5):
            try:
                time.sleep(5) # Polite delay
                response = requests.post(overpass_url, data=query, timeout=30)
                
                if response.status_code == 429:
                    logging.warning(f"Overpass Rate Limit. Retrying in 20s... (Attempt {attempt+1})")
                    time.sleep(20)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                total_count = 0
                if "elements" in data and len(data["elements"]) > 0:
                    tags = data["elements"][0].get("tags", {})
                    total_count += int(tags.get("nodes", 0)) + int(tags.get("ways", 0)) + int(tags.get("relations", 0))
                
                return min(total_count * 10, 100)

            except Exception as e:
                logging.warning(f"Overpass attempt {attempt+1} failed: {e}")
        
        return 0

class RawDataManager:
    @staticmethod
    def get_raw_locations() -> pd.DataFrame:
        # Mock Data for Lisbon Hostels
        hostels = {
            "name": ["Goodmorning Solo Traveler Hostel", "Home Lisbon Hostel", "Yes! Lisbon Hostel"],
            "lat": [38.7155, 38.7106, 38.7116],
            "lon": [-9.1419, -9.1355, -9.1383],
            "type": "Hostel"
        }
        # Mock Data for Campsites
        campsites = {
            "name": ["Monchique Resort", "Faro Camper Park", "Algarve Camping"],
            "lat": [37.3215, 37.0179, 37.0300],
            "lon": [-8.5672, -7.9308, -7.9500],
            "type": "Campsite"
        }
        return pd.concat([pd.DataFrame(hostels), pd.DataFrame(campsites)], ignore_index=True)

def build_database():
    if FAST_MODE:
        logging.warning("⚠️ FAST_MODE is enabled! Skipping Amenity Scores to speed up data recovery.")

    csv_path = os.path.join(os.path.dirname(__file__), 'trip_data.csv')
    
    # 1. Load existing cache if available
    if os.path.exists(csv_path):
        logging.info("Loading existing database...")
        existing_df = pd.read_csv(csv_path)
        cached_names = existing_df['name'].tolist()
    else:
        existing_df = pd.DataFrame()
        cached_names = []

    # 2. Get Raw List
    raw_df = RawDataManager.get_raw_locations()
    new_rows = []

    # 2.5 Discovery: Find new places around the main hubs AND along the route
    main_hubs = [
        (38.7223, -9.1393), # Lisbon
        (37.3167, -8.5500), # Monchique
        (37.0179, -7.9308), # Faro
        (41.1579, -8.6291)  # Porto
    ]

    def interpolate_points(start, end, count):
        return [(start[0] + (end[0] - start[0]) * i / (count + 1),
                 start[1] + (end[1] - start[1]) * i / (count + 1)) for i in range(1, count + 1)]

    search_points = main_hubs.copy()
    search_points.extend(interpolate_points(main_hubs[0], main_hubs[1], 3)) # 3 stops Lisbon->Monchique (Alentejo Coast)
    search_points.extend(interpolate_points(main_hubs[1], main_hubs[2], 1)) # 1 stop Monchique->Faro
    search_points.extend(interpolate_points(main_hubs[2], main_hubs[3], 4)) # 4 stops Faro->Porto (Return trip)

    # Google Places Types: https://developers.google.com/maps/documentation/places/web-service/supported_types
    types_to_find = {"beach": "Beach", "tourist_attraction": "Viewpoint", "campground": "Campsite", "park": "Hiking"}

    for lat, lon in search_points:
        for g_type, friendly_type in types_to_find.items():
            logging.info(f"Discovering {friendly_type}s near {lat}, {lon}...")
            places = APIService.search_places(lat, lon, g_type)
            
            for p in places:
                name = p["displayName"]["text"]
                if name not in cached_names:
                    logging.info(f"   -> Found new place: {name}")
                    amenity_score = APIService.get_amenity_score(p["location"]["latitude"], p["location"]["longitude"])
                    rating = str(p.get("rating", "N/A"))
                    user_ratings = str(p.get("userRatingCount", 0))
                    logging.info(f"      Details: Rating={rating}, Reviews={user_ratings}, Amenity={amenity_score}")

                    new_rows.append({
                        "name": name,
                        "lat": p["location"]["latitude"],
                        "lon": p["location"]["longitude"],
                        "type": friendly_type,
                        "rating": rating,
                        "user_ratings_total": user_ratings,
                        "photo_reference": p.get("photos", [{}])[0].get("name") if p.get("photos") else None,
                        "amenity_score": amenity_score
                    })
                    cached_names.append(name)
                else:
                    logging.info(f"   -> Skipping {name} (Already in database)")

        # Save progress after each location to prevent data loss
        if new_rows:
            temp_df = pd.concat([existing_df, pd.DataFrame(new_rows)], ignore_index=True)
            temp_df.to_csv(csv_path, index=False)
            logging.info(f"   (Progress Saved: {len(new_rows)} new locations so far)")

    # 3. Fetch Data for New Locations
    for _, row in raw_df.iterrows():
        if row['name'] in cached_names:
            logging.info(f"Skipping {row['name']} (Already Cached)")
            continue

        logging.info(f"Fetching data for: {row['name']}")
        google_data = APIService.fetch_google_places_data(row['lat'], row['lon'])
        amenity_score = APIService.get_amenity_score(row['lat'], row['lon'])

        # Merge data
        row_data = row.to_dict()
        row_data.update(google_data)
        row_data['amenity_score'] = amenity_score
        new_rows.append(row_data)

    # 4. Save Updates
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        final_df = pd.concat([existing_df, new_df], ignore_index=True)
        final_df.to_csv(csv_path, index=False)
        logging.info(f"Success! Added {len(new_rows)} new locations to {csv_path}")
    else:
        logging.info("Database is up to date. No new locations to fetch.")

if __name__ == "__main__":
    build_database()