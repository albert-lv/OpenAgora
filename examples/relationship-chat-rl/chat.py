#!/usr/bin/env python3
"""
Chat with the deployed relationship-chat model via Ollama's OpenAI-compatible API.

Usage:
    python chat.py

The model should already be created with deploy_to_ollama.py:
    ollama run relationship-chat
"""

import os

from openai import OpenAI


def main():
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    model = os.environ.get("OLLAMA_MODEL", "relationship-chat")

    client = OpenAI(base_url=base_url, api_key="ollama")

    system_prompt = (
        "You are her caring boyfriend/husband. She just sent a message. Please reply in English. "
        "First acknowledge her emotions, then gently ask or express support; "
        "do not blame, lecture, say \"calm down\" or \"what's the big deal\"; "
        "be warm and sincere, keep it under 150 words."
    )

    messages = [{"role": "system", "content": system_prompt}]

    print("💬 Relationship chat assistant ready (type 'quit' to exit)\n")
    while True:
        user_text = input("Her: ").strip()
        if not user_text or user_text.lower() in {"quit", "exit", "q"}:
            break
        messages.append({"role": "user", "content": user_text})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=256,
        )
        reply = response.choices[0].message.content
        print(f"You: {reply}\n")
        messages.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
