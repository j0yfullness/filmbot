import os
import sys
import asyncio
from flask import Flask, request
from telegram import Update

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Filmbot import application, TOKEN

flask_app = Flask(__name__)


@flask_app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    asyncio.run(application.process_update(update))
    return 'OK', 200


@flask_app.route('/')
def index():
    return 'Bot Media Telegram sedang berjalan!', 200


if __name__ == '__main__':
    flask_app.run()
