"""
Telegram Bot - Simple version
"""
import os
import asyncio
import httpx

import config
import database

TARGET_URL = os.getenv("TARGET_SERVICE_URL", "")
TELEGRAM_TOKEN = "8266978080:AAEdL6GXg33a2ctQDLAEsZLiBqnAJV5hZlk"
ALLOWED_CHAT_IDS = [5113409595]

print("BOT STARTING", flush=True)


async def send(chat_id, text):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text}
            )
            print(f"SENT {chat_id}: {r.status_code}", flush=True)
    except Exception as e:
        print(f"ERR: {e}", flush=True)


async def process(chat_id, text):
    print(f"PROCESS: {text} from {chat_id}", flush=True)
    
    if text == "/start":
        await send(chat_id, "OK! /status /kill /startsrv")
    elif text == "/status":
        await send(chat_id, f"Target: {'OK' if TARGET_URL else 'NO'}")
    elif text == "/kill" and TARGET_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{TARGET_URL}/kill")
                await send(chat_id, "KILLED")
        except Exception as e:
            await send(chat_id, f"ERR: {e}")
    elif text == "/startsrv" and TARGET_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{TARGET_URL}/restart")
                await send(chat_id, "STARTED")
        except Exception as e:
            await send(chat_id, f"ERR: {e}")


async def poll():
    print("POLLING...", flush=True)
    
    while True:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                    params={"timeout": 30}
                )
                
                data = r.json()
                updates = data.get("result", [])
                print(f"Got {len(updates)} updates", flush=True)
                
                for u in updates:
                    msg = u.get("message", {})
                    cid = msg.get("chat", {}).get("id")
                    txt = msg.get("text", "")
                    
                    print(f"MSG: {cid} | {txt}", flush=True)
                    
                    if cid and txt and txt.startswith("/"):
                        await process(cid, txt.split()[0])
                        
        except Exception as e:
            print(f"POLL ERR: {e}", flush=True)
        
        await asyncio.sleep(2)


asyncio.run(poll())