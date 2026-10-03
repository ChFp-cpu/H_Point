import asyncio, threading, os, sys
from dotenv import load_dotenv
load_dotenv()
from hpoint import web
from hpoint.main import main as bot_main
from hpoint.database import init_db

def main():
    if not os.getenv("BOT_TOKEN"):
        print('ERROR: BOT_TOKEN is not set. PowerShell: $env:BOT_TOKEN="YOUR_BOT_TOKEN"')
        sys.exit(1)
    init_db()
    thread=threading.Thread(target=web.run,daemon=True)
    thread.start()
    print("H-Point started")
    print(f"Website: {os.getenv('WEB_PUBLIC_URL','http://127.0.0.1:8080')}")
    print("Telegram bot: polling")
    try: asyncio.run(bot_main())
    except KeyboardInterrupt: pass
    finally: print("H-Point stopped")
if __name__=="__main__":main()
