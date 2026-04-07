from typing import Tuple, Optional, List, Dict, Any
import reverse_geocoder as rg
from geopy.geocoders import Photon
from geopy.extra.rate_limiter import RateLimiter

def check_valid_coordinates(latitude: float, longitude: float) -> bool:
    """Checks if the provided latitude and longitude are within valid ranges."""
    return -90 <= latitude <= 90 and -180 <= longitude <= 180

def get_geocoding_context(
    coordinates: tuple,
    min_delay_seconds: float = 1.0,
) -> Dict[str, Any]:
    latitude, longitude = coordinates
    if not check_valid_coordinates(latitude, longitude):
        raise ValueError("Invalid coordinates provided.")

    geolocator = Photon(user_agent="capella-agent")
    reverse_fn = RateLimiter(geolocator.reverse, min_delay_seconds=min_delay_seconds)
    fallback_fn = rg.search

    try:
        location = reverse_fn((latitude, longitude), exactly_one=True)
        if location:
            props = location.raw.get("properties", {})
            return {
                "name": props.get("name", ""),
                "city": props.get("city", ""),
                "state": props.get("state", ""),
                "country": props.get("country", ""),
                "country_code": props.get("countrycode", ""),
            }
        else:
            return {"error": "No geocoding result found."}
    except Exception as e:
        print(f"Photon geocoding failed: {e}")

    try:
        fallback_result = fallback_fn(coordinates, mode=1)
        if fallback_result:
            return {
                "name": fallback_result[0].get("name", ""),
                "city": fallback_result[0].get("admin2", ""),
                "state": fallback_result[0].get("admin1", ""),
                "country": fallback_result[0].get("cc", ""),
                "country_code": fallback_result[0].get("cc", ""),
            }
        else:
            return {"error": "No geocoding result found in fallback."}
    except Exception as e:
        print(f"Reverse geocoder fallback failed: {e}")
        return {"error": f"All geocoding attempts failed: {e}"}

    
def main():
    # Example usage
    coords = (-15.7801, -47.9292)  # Brasília, Brazil
    location_name = get_geocoding_context(coords)
    print(f"Coordinates {coords} correspond to: {location_name}")

if __name__ == "__main__":    
    main()