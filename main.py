import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import RPCError
import uvicorn
from dotenv import load_dotenv

load_dotenv()

# ---------- Конфигурация ----------
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
API_KEY = os.getenv("API_KEY", "secret-key")
SESSION_STRING = os.getenv("SESSION_STRING", "")

if not API_ID or not API_HASH or not SESSION_STRING:
    raise ValueError("Не заданы API_ID, API_HASH или SESSION_STRING")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MatrixTool Telegram Gateway")
client = None

# ---------- Категории ботов ----------
CATEGORIES = {
    "tg": [
        "@VPNuniversalYourbot",
        "@dateregbot",
        "@teleloghackbot",
        "@getSendGiftsProBot"
    ],
    "vk": [
        "@VKInfoRobot"
    ],
    "phone": [
        "@VPNuniversalYourbot",
        "@TrueCalleRobot"
    ]
}

# ---------- Модели ----------
class SearchRequest(BaseModel):
    category: str
    text: str
    parse_mode: Optional[str] = "html"
    timeout: int = 30           # увеличен до 30 сек
    delay: float = 0.2          # уменьшена задержка до 0.2 сек

class SearchResponse(BaseModel):
    success: bool
    results: Dict[str, str] = {}
    errors: Dict[str, str] = {}

# ---------- Старый эндпоинт (для совместимости) ----------
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

# ---------- Аутентификация ----------
def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True

# ---------- Вспомогательная функция отправки одному боту ----------
async def send_to_bot(bot_username: str, text: str, timeout: int, parse_mode: str = "html") -> Dict[str, Any]:
    try:
        bot_entity = await client.get_entity(bot_username)
        sent_msg = await client.send_message(bot_entity, text, parse_mode=parse_mode)
        logger.info(f"Сообщение отправлено боту {bot_username}, msg_id={sent_msg.id}")

        reply_future = asyncio.get_running_loop().create_future()

        @client.on(events.NewMessage(from_users=bot_entity.id, incoming=True))
        async def reply_handler(event):
            if event.message.is_reply and event.message.reply_to_msg_id == sent_msg.id:
                if not reply_future.done():
                    reply_future.set_result(event.message.text)

        try:
            reply_text = await asyncio.wait_for(reply_future, timeout=timeout)
        except asyncio.TimeoutError:
            reply_text = None
        finally:
            client.remove_event_handler(reply_handler)

        if reply_text is None:
            return {"error": "Таймаут ответа", "success": False}
        return {"reply": reply_text, "success": True}
    except RPCError as e:
        logger.error(f"RPC ошибка для {bot_username}: {e}")
        return {"error": str(e), "success": False}
    except Exception as e:
        logger.error(f"Неожиданная ошибка для {bot_username}: {e}")
        return {"error": str(e), "success": False}

# ---------- Основной эндпоинт /search (последовательная отправка с задержкой) ----------
@app.post("/search", dependencies=[Depends(verify_api_key)])
async def search_category(req: SearchRequest):
    global client
    if req.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Неподдерживаемая категория")

    bots = CATEGORIES[req.category]
    results = {}
    errors = {}

    for i, bot in enumerate(bots):
        result = await send_to_bot(bot, req.text, req.timeout, req.parse_mode)
        if result.get("success"):
            results[bot] = result["reply"]
        else:
            errors[bot] = result.get("error", "Неизвестная ошибка")
        # Задержка после каждого бота (кроме последнего)
        if i < len(bots) - 1 and req.delay > 0:
            await asyncio.sleep(req.delay)

    overall_success = bool(results)
    return SearchResponse(success=overall_success, results=results, errors=errors)

# ---------- Старый эндпоинт (сохранён) ----------
@app.post("/ask_bot", dependencies=[Depends(verify_api_key)])
async def ask_bot_old(req: AskBotRequest):
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

# ---------- Health ----------
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.on_event("startup")
async def startup():
    global client
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
