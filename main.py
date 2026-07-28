import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional
from telethon import TelegramClient, events
from telethon.sessions import StringSession  # <-- обязательно
from telethon.errors import RPCError
import uvicorn
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
API_KEY = os.getenv("API_KEY", "secret-key")
SESSION_STRING = os.getenv("SESSION_STRING", "")   # проверь, чтобы не было SSESSION_STRING

if not API_ID or not API_HASH or not SESSION_STRING:
    raise ValueError("Не заданы API_ID, API_HASH или SESSION_STRING")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MatrixTool Telegram Gateway")
client = None

@app.on_event("startup")
async def startup():
    global client
    # Используем StringSession — не создаёт файл на диске
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Сессия не авторизована")
    logger.info("Telegram клиент запущен")

@app.on_event("shutdown")
async def shutdown():
    global client
    if client:
        await client.disconnect()

class AskBotRequest(BaseModel):
    text: str
    bot_username: str = "@TrueCalleRobot"
    parse_mode: Optional[str] = "html"
    timeout: int = 30

class AskBotResponse(BaseModel):
    success: bool
    sent_message_id: Optional[int] = None
    reply_text: Optional[str] = None
    error: Optional[str] = None

def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True

@app.post("/ask_bot", dependencies=[Depends(verify_api_key)])
async def ask_bot(req: AskBotRequest):
    global client
    try:
        bot_entity = await client.get_entity(req.bot_username)
        sent_msg = await client.send_message(bot_entity, req.text, parse_mode=req.parse_mode)
        logger.info(f"Сообщение отправлено боту {req.bot_username}, msg_id={sent_msg.id}")

        reply_future = asyncio.get_running_loop().create_future()

        @client.on(events.NewMessage(from_users=bot_entity.id, incoming=True))
        async def reply_handler(event):
            if event.message.is_reply and event.message.reply_to_msg_id == sent_msg.id:
                if not reply_future.done():
                    reply_future.set_result(event.message.text)

        try:
            reply_text = await asyncio.wait_for(reply_future, timeout=req.timeout)
        except asyncio.TimeoutError:
            reply_text = None
        finally:
            client.remove_event_handler(reply_handler)

        if reply_text is None:
            return AskBotResponse(success=False, sent_message_id=sent_msg.id, error="Таймаут ответа")
        return AskBotResponse(success=True, sent_message_id=sent_msg.id, reply_text=reply_text)

    except RPCError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal error")

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
