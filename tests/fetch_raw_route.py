import requests
import json
from collections import defaultdict


class RouteSemanticFilter:
    """
    Semantic abstraction layer over Mappls route JSON.

    Goal:
    - Remove navigation noise
    - Preserve meaningful travel structure
    - Extract macro travel checkpoints
    - Compress route graph into human-usable segments
    """

    def __init__(
        self,
        api_key,
        min_segment_distance_km=8,
        checkpoint_emit_distance_km=50,
    ):
        self.api_key = api_key
        self.min_segment_distance_km = min_segment_distance_km
        self.checkpoint_emit_distance_km = checkpoint_emit_distance_km

    # ------------------------------------------------------------
    # FETCH ROUTE
    # ------------------------------------------------------------

    def fetch_route(self, start, destination):
        """
        start/destination format:
        "longitude,latitude"
        """

        url = (
            f"https://route.mappls.com/route/direction/"
            f"route_adv/driving/"
            f"{start};{destination}"
            f"?steps=true"
            f"&access_token={self.api_key}"
        )

        response = requests.get(url)

        if response.status_code != 200:
            raise Exception(
                f"Mappls API failed: {response.status_code}\n{response.text}"
            )

        return response.json()

    # ------------------------------------------------------------
    # STEP IMPORTANCE SCORE
    # ------------------------------------------------------------

    def score_step(self, step):
        """
        Heuristic importance score.

        Higher score => more semantically important.
        """

        score = 0

        distance_km = step.get("distance", 0) / 1000
        road_name = step.get("name", "").strip()

        # Longer road spans matter more
        score += distance_km * 2

        # Named roads are more meaningful
        if road_name:
            score += 10

        # National highways are important
        if "NH" in road_name.upper():
            score += 40

        # State highways
        if "SH" in road_name.upper():
            score += 20

        # Major maneuver types
        maneuver_type = (
            step.get("maneuver", {})
            .get("type", "")
            .lower()
        )

        if maneuver_type in [
            "fork",
            "roundabout",
            "rotary",
            "merge",
            "on ramp",
            "off ramp",
        ]:
            score += 15

        # Penalize micro maneuvers
        if distance_km < 0.5:
            score -= 25

        return round(score, 2)

    # ------------------------------------------------------------
    # FILTER RAW STEPS
    # ------------------------------------------------------------

    def filter_steps(self, steps):
        """
        Remove low-value navigation noise.
        """

        filtered = []

        for step in steps:

            distance_km = step.get("distance", 0) / 1000
            road_name = step.get("name", "").strip()

            # Remove tiny unnamed navigation fragments
            if (
                distance_km < self.min_segment_distance_km
                and not road_name
            ):
                continue

            step["importance_score"] = self.score_step(step)

            filtered.append(step)

        return filtered

    # ------------------------------------------------------------
    # MERGE ROAD CORRIDORS
    # ------------------------------------------------------------

    def merge_corridors(self, steps):
        """
        Merge repeated road fragments into macro corridors.
        """

        corridors = []

        current = None

        for step in steps:

            road_name = step.get("name", "Unnamed Road").strip()

            if not road_name:
                road_name = "Unnamed Road"

            distance_km = step.get("distance", 0) / 1000
            duration_min = step.get("duration", 0) / 60
            score = step.get("importance_score", 0)

            # Start new corridor
            if current is None:
                current = {
                    "road": road_name,
                    "distance_km": distance_km,
                    "duration_min": duration_min,
                    "importance_score": score,
                    "segments": 1,
                }
                continue

            # Merge repeated road stretches
            if current["road"] == road_name:
                current["distance_km"] += distance_km
                current["duration_min"] += duration_min
                current["importance_score"] += score
                current["segments"] += 1

            else:
                corridors.append(current)

                current = {
                    "road": road_name,
                    "distance_km": distance_km,
                    "duration_min": duration_min,
                    "importance_score": score,
                    "segments": 1,
                }

        if current:
            corridors.append(current)

        return corridors

    # ------------------------------------------------------------
    # EXTRACT MAJOR CHECKPOINTS
    # ------------------------------------------------------------

    def extract_checkpoints(self, corridors):
        """
        Build coarse route checkpoints.
        """

        checkpoints = []

        cumulative_distance = 0
        cumulative_duration = 0

        current_roads = []

        for corridor in corridors:

            cumulative_distance += corridor["distance_km"]
            cumulative_duration += corridor["duration_min"]

            road = corridor["road"]

            if road not in current_roads:
                current_roads.append(road)

            # Emit semantic checkpoint
            if cumulative_distance >= self.checkpoint_emit_distance_km:

                checkpoints.append({
                    "checkpoint_distance_km": round(cumulative_distance, 2),
                    "checkpoint_duration_hr": round(
                        cumulative_duration / 60, 2
                    ),
                    "major_roads": current_roads[:6],
                })

                cumulative_distance = 0
                cumulative_duration = 0
                current_roads = []

        return checkpoints

    # ------------------------------------------------------------
    # TOP IMPORTANT ROADS
    # ------------------------------------------------------------

    def rank_corridors(self, corridors, top_n=10):
        """
        Rank major route corridors by semantic importance.
        """

        ranked = sorted(
            corridors,
            key=lambda x: (
                x["importance_score"],
                x["distance_km"],
            ),
            reverse=True,
        )

        return ranked[:top_n]

    # ------------------------------------------------------------
    # MAIN PIPELINE
    # ------------------------------------------------------------

    def run(self, start, destination):

        print("Fetching route from Mappls...")

        data = self.fetch_route(start, destination)

        route = data["routes"][0]

        total_distance_km = route["distance"] / 1000
        total_duration_hr = route["duration"] / 3600

        print(f"Total Distance: {total_distance_km:.2f} km")
        print(f"ETA: {total_duration_hr:.2f} hours")

        steps = route["legs"][0]["steps"]

        print(f"Raw Steps: {len(steps)}")

        filtered_steps = self.filter_steps(steps)

        print(f"Filtered Steps: {len(filtered_steps)}")

        corridors = self.merge_corridors(filtered_steps)

        print(f"Macro Corridors: {len(corridors)}")

        checkpoints = self.extract_checkpoints(corridors)

        ranked_corridors = self.rank_corridors(corridors)

        result = {
            "trip_summary": {
                "distance_km": round(total_distance_km, 2),
                "duration_hr": round(total_duration_hr, 2),
            },
            "major_checkpoints": checkpoints,
            "top_route_corridors": ranked_corridors,
        }

        with open("semantic_route_output.json", "w") as f:
            json.dump(result, f, indent=2)

        print("\nSaved output -> semantic_route_output.json")

        return result


# ------------------------------------------------------------
# RUN
# ------------------------------------------------------------

if __name__ == "__main__":

    API_KEY = "rtodvvaynfxbunwodfbxgdbpdieleqzkqezy"

    # Delhi
    start = "77.1025,28.7041"

    # Manali
    destination = "77.1887,32.2432"

    semantic_filter = RouteSemanticFilter(
        api_key=API_KEY,
        min_segment_distance_km=2,
        checkpoint_emit_distance_km=50,
    )

    result = semantic_filter.run(start, destination)

    print("\n--- TOP CORRIDORS ---\n")

    for idx, corridor in enumerate(
        result["top_route_corridors"][:5],
        start=1,
    ):

        print(f"{idx}. {corridor['road']}")
        print(f"   Distance: {corridor['distance_km']:.2f} km")
        print(f"   Duration: {corridor['duration_min']:.1f} min")
        print(f"   Importance Score: {corridor['importance_score']:.2f}")
        print()
