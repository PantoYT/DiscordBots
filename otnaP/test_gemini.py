"""
Uruchom: python test_gemini.py
Diagnozuje połączenie z Gemini API.
"""
from dotenv import load_dotenv
import os

load_dotenv()

key = os.getenv("GEMINI_API_KEY", "")
print(f"[1] GEMINI_API_KEY w .env: {'tak (' + key[:8] + '...)' if key else 'BRAK!'}")

if not key:
    print("    -> Uzupełnij GEMINI_API_KEY w .env")
    exit(1)

try:
    import google.generativeai as genai
    print("[2] google-generativeai: zainstalowany")
except ImportError:
    print("[2] google-generativeai: BRAK — zainstaluj: pip install google-generativeai")
    exit(1)

try:
    genai.configure(api_key=key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    print("[3] Model: załadowany")
except Exception as e:
    print(f"[3] Błąd konfiguracji: {e}")
    exit(1)

try:
    response = model.generate_content("Powiedz 'test OK' po polsku.")
    print(f"[4] API response: {response.text.strip()}")
    print("\n✅ Gemini działa poprawnie!")
except Exception as e:
    print(f"[4] API call error: {e}")
    print("\n❌ Sprawdź:")
    print("   - Czy klucz API jest poprawny (https://aistudio.google.com/apikey)")
    print("   - Czy masz dostęp do Gemini API w swoim regionie")
    print("   - Czy nie przekroczyłeś free tier limitu")
