"""
tools/geocoder.py
-----------------
Place name → (lat, lon).

Primary: Mappls geocoding API (dynamic, covers any Indian place).
Fallback: Static cache of common cities for offline/fast lookup.
"""

import re

CITY_COORDS: dict[str, tuple[float, float]] = {
    # Metro cities
    "delhi": (28.6139, 77.2090),
    "new delhi": (28.6139, 77.2090),
    "mumbai": (19.0760, 72.8777),
    "bombay": (19.0760, 72.8777),
    "bangalore": (12.9716, 77.5946),
    "bengaluru": (12.9716, 77.5946),
    "chennai": (13.0827, 80.2707),
    "madras": (13.0827, 80.2707),
    "kolkata": (22.5726, 88.3639),
    "calcutta": (22.5726, 88.3639),
    "hyderabad": (17.3850, 78.4867),
    "pune": (18.5204, 73.8567),
    "ahmedabad": (23.0225, 72.5714),
    # North India / hill stations
    "jaipur": (26.9124, 75.7873),
    "agra": (27.1767, 78.0081),
    "chandigarh": (30.7333, 76.7794),
    "amritsar": (31.6340, 74.8723),
    "ludhiana": (30.9010, 75.8573),
    "lucknow": (26.8467, 80.9462),
    "varanasi": (25.3176, 82.9739),
    "dehradun": (30.3165, 78.0322),
    "haridwar": (29.9457, 78.1642),
    "rishikesh": (30.0869, 78.2676),
    "shimla": (31.1048, 77.1734),
    "manali": (32.2396, 77.1887),
    "dharamshala": (32.2190, 76.3234),
    "mussoorie": (30.4598, 78.0664),
    "nainital": (29.3919, 79.4542),
    "leh": (34.1526, 77.5771),
    "srinagar": (34.0837, 74.7973),
    # Rajasthan
    "jodhpur": (26.2389, 73.0243),
    "udaipur": (24.5854, 73.7125),
    "jaisalmer": (26.9157, 70.9083),
    "bikaner": (28.0229, 73.3119),
    "ajmer": (26.4499, 74.6399),
    "pushkar": (26.4897, 74.5511),
    # West / Goa
    "goa": (15.2993, 74.1240),
    "panaji": (15.4909, 73.8278),
    "surat": (21.1702, 72.8311),
    "vadodara": (22.3072, 73.1812),
    # South India
    "mysuru": (12.2958, 76.6394),
    "mysore": (12.2958, 76.6394),
    "coimbatore": (11.0168, 76.9558),
    "kochi": (9.9312, 76.2673),
    "trivandrum": (8.5241, 76.9366),
    "thiruvananthapuram": (8.5241, 76.9366),
    "madurai": (9.9252, 78.1198),
    "ooty": (11.4102, 76.6950),
    # East / Northeast
    "bhubaneswar": (20.2961, 85.8245),
    "patna": (25.5941, 85.1376),
    "ranchi": (23.3441, 85.3096),
    "guwahati": (26.1445, 91.7362),
    # Highway stops — Delhi → Manali corridor
    "gurugram": (28.4595, 77.0266),
    "gurgaon": (28.4595, 77.0266),
    "panipat": (29.3909, 76.9635),
    "ambala": (30.3782, 76.7767),
    "murthal": (29.0969, 77.0094),
    "karnal": (29.6857, 76.9905),
    "kurukshetra": (29.9695, 76.8783),
    "ropar": (30.9639, 76.5192),
    "kiratpur sahib": (31.1787, 76.5633),
    "bilaspur": (31.3378, 76.7615),
    "mandi": (31.7081, 76.9318),
    "kullu": (31.9578, 77.1095),
    "bhuntar": (31.8707, 77.1436),
    "pathankot": (32.2643, 75.6421),
    "jammu": (32.7266, 74.8570),
    # Delhi → Jaipur corridor
    "gurugram": (28.4595, 77.0266),
    "faridabad": (28.4089, 77.3178),
    "alwar": (27.5530, 76.6346),
    "behror": (27.8859, 76.2880),
    "shahjahanpur": (27.8791, 76.1157),
    # Delhi → Agra corridor
    "noida": (28.5355, 77.3910),
    "mathura": (27.4924, 77.6737),
    "vrindavan": (27.5700, 77.6900),
    "bharatpur": (27.2152, 77.4900),
    # Other common stops
    "meerut": (28.9845, 77.7064),
    "moradabad": (28.8386, 78.7733),
    "bareilly": (28.3670, 79.4304),
    "aligarh": (27.8974, 78.0880),
    "kanpur": (26.4499, 80.3319),
    "prayagraj": (25.4358, 81.8463),
    "allahabad": (25.4358, 81.8463),
    "gorakhpur": (26.7606, 83.3732),
    "nagpur": (21.1458, 79.0882),
    "aurangabad": (19.8762, 75.3433),
    "nashik": (19.9975, 73.7898),
    "bathinda": (30.2110, 74.9455),
    "roorkee": (29.8543, 77.8880),
    "sikar": (27.6094, 75.1399),
    "kota": (25.2138, 75.8648),
}


async def geocode(place: str) -> tuple[float, float] | None:
    """
    Convert a place name to (lat, lon).

    Priority:
      1. Static cache — instant for known cities
      2. Mappls geocoding API — covers any Indian place
    """
    key = place.lower().strip()

    if key in CITY_COORDS:
        return CITY_COORDS[key]
    for city, coords in CITY_COORDS.items():
        if key in city or city in key:
            return coords

    from tools.mappls import forward_geocode
    return await forward_geocode(place)


def geocode_sync(place: str) -> tuple[float, float] | None:
    """
    Synchronous offline lookup — static cache only.
    Use only where async is not possible (e.g. regex fallback parsing).
    Returns None for places not in the cache.
    """
    key = place.lower().strip()
    if key in CITY_COORDS:
        return CITY_COORDS[key]
    for city, coords in CITY_COORDS.items():
        if key in city or city in key:
            return coords
    return None


def extract_cities(text: str) -> list[str]:
    """
    Find all known city names mentioned in a text string.
    Returns them in order of appearance.
    """
    text_lower = text.lower()
    found = []
    for city in CITY_COORDS:
        if re.search(rf"\b{re.escape(city)}\b", text_lower):
            match = re.search(rf"\b{re.escape(city)}\b", text_lower)
            found.append((city, match.start()))
    found.sort(key=lambda x: x[1])
    return [city for city, _ in found]
