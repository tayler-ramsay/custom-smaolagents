import requests

class DeepSeekAgent:
    BASE_URL = "https://api.deepseek.com"

    def __init__(self, api_key="sk-512eda45d3d3414b92bf1ddd7fd5bc06"):
        self.api_key = api_key

    def update_api_key(self, new_key):
        self.api_key = new_key

    def query(self, prompt, model="deepseek-chat"):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            response = requests.post(f"{self.BASE_URL}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": str(e)}
