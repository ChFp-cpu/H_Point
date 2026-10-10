import asyncio
import os
import sys
import threading
from dotenv import load_dotenv

load_dotenv()

def main():
    if not os.getenv("BOT_TOKEN"):
        print('ERROR: BOT_TOKEN is not set. PowerShell: $env:BOT_TOKEN="YOUR_BOT_TOKEN"')
        sys.exit(1)

    # Import after validating configuration: importing the app opens SQLite
    # and runs migrations as a module side effect.
    from hpoint import web
    from hpoint.main import main as bot_main

    # Bind before polling so an unavailable web port fails startup clearly
    # instead of leaving the Telegram bot running without its website.
    server = web.create_server()
    thread = threading.Thread(target=server.serve_forever, name="hpoint-web")
    thread.start()
    print("H-Point started")
    print(f"Website: {os.getenv('WEB_PUBLIC_URL','http://127.0.0.1:8080')}")
    print("Telegram bot: polling")
    try: asyncio.run(bot_main())
    except KeyboardInterrupt: pass
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        print("H-Point stopped")

if __name__=="__main__":main()
