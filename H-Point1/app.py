"""Compatibility entry point. Use `python run.py` to start both web and Telegram bot."""
from webapp.app import app

if __name__ == '__main__':
    print('Используй: python run.py — это единый запуск сайта и Telegram-бота.')
