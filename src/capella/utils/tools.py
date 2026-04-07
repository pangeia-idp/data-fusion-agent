import json
import os
import requests
import pystac
import time
import stac_asset.blocking
from langchain.tools import tool

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
ADDRESS_FIELDS = ["city", "town", "village", "county", "state", "country"]

CAPELLA_COLLECTION_URL = (
    "https://capella-open-data.s3.us-west-2.amazonaws.com"
    "/stac/capella-open-data-ieee-data-contest/collection.json"
)
CAPELLA_ITEM_BASE_URL = (
    "https://capella-open-data.s3.us-west-2.amazonaws.com"
    "/stac/capella-open-data-ieee-data-contest/items"
)
ASSETS_TO_DOWNLOAD = ["thumbnail"]


@tool
def download_capella_assets(stac_id: str, output_dir: str = "data/assets") -> str:
    """
    Downloads thumbnail assets for a Capella Open Data STAC item.

    Args:
        stac_id: The STAC item ID (e.g. CAPELLA_C13_SP_SLC_HH_20251105143522_20251105143535)
        output_dir: Directory where assets will be saved (default: data/assets)
    """
    try:
        from urllib.parse import urljoin

        collection = pystac.Collection.from_file(CAPELLA_COLLECTION_URL)

        # Resolve item links exactly like the notebook does
        item_href = None
        for link in collection.links:
            if link.rel == "item" and stac_id in link.href:
                if link.href.startswith("http"):
                    item_href = link.href
                elif link.href.startswith("./"):
                    item_href = urljoin(CAPELLA_COLLECTION_URL, link.href[2:])
                else:
                    item_href = urljoin(CAPELLA_COLLECTION_URL, link.href)
                break

        if item_href is None:
            return json.dumps({
                "stac_id": stac_id,
                "status": "error",
                "error": f"Item {stac_id} not found in collection",
            })

        item_output_dir = os.path.join(output_dir, stac_id)
        os.makedirs(item_output_dir, exist_ok=True)

        include_args = sum([["-i", asset] for asset in ASSETS_TO_DOWNLOAD], [])
        cmd = ["stac-asset", "download", item_href, item_output_dir] + include_args
        exit_code = os.system(" ".join(cmd))

        if exit_code != 0:
            return json.dumps({
                "stac_id": stac_id,
                "status": "error",
                "error": f"stac-asset download failed with exit code {exit_code}",
            })

        return json.dumps({
            "stac_id": stac_id,
            "status": "ok",
            "output_dir": item_output_dir,
            "downloaded_assets": ASSETS_TO_DOWNLOAD,
        })
    except Exception as e:
        return json.dumps({
            "stac_id": stac_id,
            "status": "error",
            "error": str(e),
        })

@tool
def search_wikipedia(latitude: float, longitude: float, radius: int = 10000, limit: int = 3) -> str:
    """
    Searches Wikipedia for articles related to a geographic location given latitude and longitude.
    Use this tool when you need encyclopedic information about a place from GPS coordinates.

    Args:
        latitude: Latitude in decimal degrees (-90 to 90)
        longitude: Longitude in decimal degrees (-180 to 180)
        radius: Search radius in meters (default: 10000)
        limit: Maximum number of articles to return (default: 3)
    """
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        return json.dumps({"error": "invalid coordinates."})

    try:
        geo_resp = requests.get(
            WIKIPEDIA_API_URL,
            params={
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{latitude}|{longitude}",
                "gsradius": radius,
                "gslimit": limit,
                "format": "json",
            },
            headers={"User-Agent": "datafusion-agent"},
            timeout=10,
        )
        geo_resp.raise_for_status()
        pages = geo_resp.json().get("query", {}).get("geosearch", [])

        if not pages:
            return json.dumps({"results": []})

        page_ids = [str(p["pageid"]) for p in pages]

        extract_resp = requests.get(
            WIKIPEDIA_API_URL,
            params={
                "action": "query",
                "pageids": "|".join(page_ids),
                "prop": "extracts",
                "exintro": True,
                "explaintext": True,
                "exsentences": 3,
                "format": "json",
            },
            headers={"User-Agent": "datafusion-agent"},
            timeout=10,
        )
        extract_resp.raise_for_status()
        query_pages = extract_resp.json().get("query", {}).get("pages", {})

        results = []
        for page in pages:
            pid = str(page["pageid"])
            results.append({
                "title": page["title"],
                "distance_meters": page.get("dist"),
                "extract": query_pages.get(pid, {}).get("extract", "").strip(),
            })

        return json.dumps({"results": results})

    except requests.exceptions.Timeout:
        return json.dumps({"error": "Wikipedia service timed out."})

    except requests.exceptions.HTTPError as e:
        return json.dumps({"error": f"Wikipedia service returned {e.response.status_code}."})

    except ValueError:
        return json.dumps({"error": "failed to parse Wikipedia response."})

# @tool
# def get_geocoding_context(
#     latitude: float,
#     longitude: float,
#     max_retries: int = 3,
#     backoff_factor: float = 1.0,
# ):
#     """
#     Returns the human-readable location for a given latitude and longitude.
#     Use this tool when you need to identify a place name from GPS coordinates.

#     Args:
#         latitude: Latitude in decimal degrees (-90 to 90)
#         longitude: Longitude in decimal degrees (-180 to 180)
#         max_retries: Maximum number of attempts before giving up.
#         backoff_factor: Base delay in seconds between retries (doubles each attempt).
#     """
#     if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
#         return "Error: invalid coordinates."

#     for attempt in range(1, max_retries + 1):
#         try:
#             r = requests.get(
#                 NOMINATIM_URL,
#                 params={"lat": latitude, "lon": longitude, "format": "json"},
#                 headers={"User-Agent": "capella-cluster-map"},
#                 timeout=10,
#             )
#             r.raise_for_status()
#             data = r.json()
#             address = data.get("address", {})
#             return address

#         except requests.exceptions.Timeout:
#             if attempt == max_retries:
#                 return "Error: location service timed out after all retries."
#         except requests.exceptions.HTTPError as e:
#             status = e.response.status_code
#             # Don't retry client errors (4xx) — they won't resolve themselves
#             if 400 <= status < 500:
#                 return f"Error: location service returned {status}."
#             if attempt == max_retries:
#                 return f"Error: location service returned {status} after all retries."
#         except ValueError:
#             return "Error: failed to parse location data."

#         # Exponential backoff: 1s, 2s, 4s, ...
#         time.sleep(backoff_factor * (2 ** (attempt - 1)))
