from transformers import AutoModelForCausalLM, AutoTokenizer

class LLMAgent:
    def __init__(self):
        self.models = {
            "gpt-neo": "EleutherAI/gpt-neo-1.3B",
            "gpt-j": "EleutherAI/gpt-j-6B",
            "gpt-2": "gpt2",
            "distilgpt2": "distilgpt2"
        }
        self.active_model = None
        self.tokenizer = None
        self.active_model_name = None

    def switch_model(self, model_name):
        if model_name not in self.models:
            available_models = ', '.join(self.models.keys())
            raise ValueError(f"Model {model_name} is not available. Available models are: {available_models}.")
        self.active_model = AutoModelForCausalLM.from_pretrained(self.models[model_name])
        self.tokenizer = AutoTokenizer.from_pretrained(self.models[model_name])
        self.active_model_name = model_name

    def handle_natural_language_query(self, query, model_name="gpt-neo"):
        # Ensure the model is switched if not already active
        if self.active_model is None or self.tokenizer is None or model_name != self.active_model_name:
            self.switch_model(model_name)
        
        # Process the natural language query and return a response
        inputs = self.tokenizer(query, return_tensors="pt")
        outputs = self.active_model.generate(**inputs, max_length=150)
        return self.tokenizer.decode(outputs[0], skip_special_tokens=True)
