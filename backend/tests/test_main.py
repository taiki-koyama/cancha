import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_hello():
    res = client.get("/api/hello")
    assert res.status_code == 200
    assert res.json() == {"message": "Hello from cancha!"}


def test_chat():
    mock_body = json.dumps({"content": [{"text": "こんにちは！"}]}).encode()
    mock_response = {"body": MagicMock(read=MagicMock(return_value=mock_body))}

    with patch("main.boto3.client") as mock_client:
        mock_client.return_value.invoke_model.return_value = mock_response
        res = client.post("/api/chat", json={"message": "こんにちは"})

    assert res.status_code == 200
    assert res.json() == {"reply": "こんにちは！"}


def test_chat_bedrock_error():
    with patch("main.boto3.client") as mock_client:
        mock_client.return_value.invoke_model.side_effect = Exception("Bedrock error")
        res = client.post("/api/chat", json={"message": "テスト"})

    assert res.status_code == 500
    assert "Bedrock error" in res.json()["detail"]
