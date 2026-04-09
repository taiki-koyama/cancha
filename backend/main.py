import json
import os
import boto3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="cancha API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from cancha!"}


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
def chat(req: ChatRequest):
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    client = boto3.client("bedrock-runtime", region_name=region)
    try:
        response = client.invoke_model(
            modelId="anthropic.claude-3-haiku-20240307-v1:0",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 512,
                "messages": [{"role": "user", "content": req.message}],
            }),
        )
        body = json.loads(response["body"].read())
        reply = body["content"][0]["text"]
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
