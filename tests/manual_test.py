import requests

API_KEY = "rtodvvaynfxbunwodfbxgdbpdieleqzkqezy"

# Step 1: Get directions and print the geometry
url = (
    f"https://route.mappls.com/route/direction/"
    f"route_adv/driving/"
    f"77.1025,28.7041;77.1887,32.2432"
    f"?alternatives=false&steps=false&access_token={API_KEY}"
)

response = requests.get(url)
data = response.json()
geometry = data["routes"][0]["geometry"]

print("Geometry string:")
print(geometry[:100], "...")  # just first 100 chars

# Step 2: Use that geometry to call POI Along Route
poi_response = requests.post(
    "https://atlas.mappls.com/api/places/along_route",
    params={"access_token": API_KEY},
    data={
        "geometries": "polyline6",
        "path":       geometry,
        "category":   "FODCOF",
        "buffer":     "500",
        "sort":       "",
    }
)

print("\nPOI Status:", poi_response.status_code)
print(poi_response.json())