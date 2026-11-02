
import os

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

router = APIRouter(prefix="/api/voice", tags=["Voice Assistant"])

OPENAI_REALTIME_URL = "https://api.openai.com/v1/realtime/client_secrets"


@router.post("/session")
async def create_voice_session():
    """
    Create a temporary credential for a browser-based voice session.
    The permanent OpenAI API key never goes to the frontend.
    """
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured on the backend.",
        )

    payload = {
        "session": {
            "type": "realtime",
            "model": "gpt-realtime-2.1",
            "instructions": (
                "You are TasteFlow AI, a friendly and professional restaurant "
                "voice assistant. Help customers explore menu items, understand "
                "ingredients and dietary preferences, and make dining decisions. "
                "Keep responses natural and concise. Never claim an order was "
                "placed unless the backend confirms it. Before placing or "
                "cancelling an order, clearly explain the action and require "
                "explicit customer confirmation. Do not invent menu items, "
                "prices, availability, or order status."
            ),
            "audio": {
                "output": {
                    "voice": "marin"
                }
            },
        }
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                OPENAI_REALTIME_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.is_error:
            # Log details on the server, but don't expose secrets to clients.
            print(
                "OpenAI Realtime session error:",
                response.status_code,
                response.text[:1000],
            )
            raise HTTPException(
                status_code=502,
                detail="Could not create the voice session. Check backend logs.",
            )

        return response.json()

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Voice session creation timed out. Please try again.",
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the voice service.",
        )

