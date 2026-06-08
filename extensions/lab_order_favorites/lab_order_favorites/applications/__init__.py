"""Application handlers for the lab order favorites plugin."""

from lab_order_favorites.applications.config_app import LabFavoritesConfigApp
from lab_order_favorites.applications.favorites_app import LabFavoritesApp

__all__ = ["LabFavoritesApp", "LabFavoritesConfigApp"]
