"""Generate desktop pet pixel art assets using Agnes AI image generation."""
import os
import sys
import requests

API_KEY = "sk-sM1SPjpc0etLrTSehdXytZEq7s5B4bVhe6fyXEJIlyBHh60U"
API_URL = "https://apihub.agnes-ai.com/v1/images/generations"
MODEL = "agnes-image-2.1-flash"

ASSETS_DIR = os.path.join(os.path.dirname(__file__), '..', 'assets', 'pet')

PROMPTS = {
    "idle": (
        "Pixel art sprite of a cute brown teddy poodle dog sitting happily, "
        "16-bit retro game style, simple clean white background, "
        "round body, floppy ears, small black eyes, pink nose, "
        "warm brown fur color like a teddy bear, "
        "chibi proportions, kawaii style, full body front view"
    ),
    "sleep": (
        "Pixel art sprite of a cute brown teddy poodle dog sleeping with eyes closed, "
        "16-bit retro game style, simple clean white background, "
        "curled up peacefully, small z z z letters floating above head, "
        "round body, floppy ears, warm brown fur, "
        "chibi proportions, kawaii style, full body front view"
    ),
    "work": (
        "Pixel art sprite of a cute brown teddy poodle dog reading a book, "
        "16-bit retro game style, simple clean white background, "
        "holding an open book with paws, looking at pages, "
        "round body, floppy ears, warm brown fur, "
        "chibi proportions, kawaii style, full body front view"
    ),
    "cry": (
        "Pixel art sprite of a cute brown teddy poodle dog crying sadly, "
        "16-bit retro game style, simple clean white background, "
        "tears streaming from eyes, sad expression, drooping ears, "
        "round body, warm brown fur, blue tear drops, "
        "chibi proportions, kawaii style, full body front view"
    ),
}


def generate_image(prompt, filename):
    print(f"Generating {filename}...")
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "size": "1024x1024",
        "n": 1,
    }
    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        image_url = data["data"][0]["url"]
        print(f"  URL: {image_url}")
        img_resp = requests.get(image_url, timeout=60)
        img_resp.raise_for_status()
        filepath = os.path.join(ASSETS_DIR, filename)
        with open(filepath, 'wb') as f:
            f.write(img_resp.content)
        print(f"  Saved: {filepath} ({len(img_resp.content)} bytes)")
        return filepath
    except Exception as e:
        print(f"  ERROR: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response: {e.response.text[:500]}")
        return None


def main():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    results = {}
    for state, prompt in PROMPTS.items():
        filename = f"pet_{state}.png"
        path = generate_image(prompt, filename)
        results[state] = path
    print("\n=== Summary ===")
    for state, path in results.items():
        status = "OK" if path else "FAILED"
        print(f"  {state}: {status}")


if __name__ == "__main__":
    main()
