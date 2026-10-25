"""Reversible feature switches; paused games keep their code and stored data."""
import os

GAMES_ENABLED = os.getenv("GAMES_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
GAMES_PAUSED_MESSAGE = "Игры временно отключены. Ваш игровой прогресс сохранён."
