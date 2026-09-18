import google.generativeai as genai
import os
import asyncio
from dotenv import load_dotenv

load_dotenv(r"e:\proyectos python\dabot v3\.env")

async def test_generation():
    api_key_raw = os.getenv("GEMINI_API_KEY")
    if not api_key_raw:
        print("❌ GEMINI_API_KEY not found.")
        return
    api_key = api_key_raw.split(',')[0].strip()

    genai.configure(api_key=api_key)

    candidates = [
        "gemini-1.5-flash",
        "models/gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "models/gemini-1.5-flash-latest",
        "gemini-1.5-pro",
        "models/gemini-1.5-pro"
    ]

    print(f"Using API Key: {api_key[:5]}...{api_key[-5:]}")
    
    # 1. First, list models again to be sure
    print("\n--- Listing Models (verified) ---")
    valid_names = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                valid_names.append(m.name)
        print(f"Found {len(valid_names)} models: {valid_names[:3]}...")
    except Exception as e:
        print(f"List failed: {e}")

    # 2. Test specific candidates
    candidates = [
        "gemini-1.5-flash",
        "models/gemini-1.5-flash",
        "gemini-pro",
        "models/gemini-pro"
    ]
    
    # Add valid names found
    for n in valid_names:
        if 'flash' in n and n not in candidates:
             candidates.append(n)

    for model_name in candidates:
        print(f"\n--- Testing '{model_name}' ---")
        try:
            model = genai.GenerativeModel(model_name)
            response = await model.generate_content_async("Hello")
            print(f"[SUCCESS] {model_name} worked! Response: {response.text[:20]}")
            # If one works, maybe we stop? No, let's see all.
        except Exception as e:
            # Shorten error
            err = str(e).replace('\n', ' ')[:100]
            print(f"[FAILED] {model_name}: {err}")

if __name__ == "__main__":
    asyncio.run(test_generation())
