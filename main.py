import requests

API_KEY = "MySuperSecretKey123"   # замени на свой
URL = "https://matrixtool-tsd9.onrender.com/search"

def search(category, text):
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    data = {"category": category, "text": text}
    try:
        # Даём серверу достаточно времени (120 сек) на обработку всех ботов
        r = requests.post(URL, json=data, headers=headers, timeout=120)
        if r.status_code == 200:
            resp = r.json()
            if resp.get("success"):
                print("✅ Результаты:")
                for bot, reply in resp["results"].items():
                    print(f"  {bot}: {reply}")
                if resp.get("errors"):
                    print("❌ Ошибки:")
                    for bot, err in resp["errors"].items():
                        print(f"  {bot}: {err}")
            else:
                print("❌ Ошибка:", resp.get("errors"))
        else:
            print(f"HTTP {r.status_code}: {r.text}")
    except Exception as e:
        print("Ошибка:", e)

if __name__ == "__main__":
    print("Доступные категории: tg, vk, phone")
    cat = input("Категория: ").strip()
    text = input("Текст запроса: ").strip()
    if cat and text:
        search(cat, text)
