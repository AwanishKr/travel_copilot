"""
agents/__init__.py
------------------
Builds and returns the router with all registered agents.
Add new agents here.
"""

from agents.router import Router
from agents.route_agent import RouteAgent
from agents.weather_agent import WeatherAgent
from agents.places_agent import PlacesAgent
from agents.hotels_agent import HotelsAgent
from agents.budget_agent import BudgetAgent


def build_router() -> Router:
    return Router([
        RouteAgent(),
        WeatherAgent(),
        PlacesAgent(),
        HotelsAgent(),
        BudgetAgent(),
    ])