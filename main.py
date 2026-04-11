import os
from threading import Thread

from waitress import serve

from bot import run_polling
from webapp import create_app


if __name__ == '__main__':
    bot_thread = Thread(target=run_polling, name='telegram-bot', daemon=True)
    bot_thread.start()

    app = create_app()
    port = int(os.getenv('PORT', '8080'))
    serve(app, host='0.0.0.0', port=port)
