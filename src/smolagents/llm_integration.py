from transformers import pipeline

def load_model():
    # Load a pre-trained model from Hugging Face
    model = pipeline('text-generation', model='gpt2')
    return model

def generate_code(prompt):
    model = load_model()
    # Generate code based on the prompt
    result = model(prompt, max_length=100, num_return_sequences=1)
    return result[0]['generated_text']

if __name__ == "__main__":
    prompt = "def hello_world():"
    generated_code = generate_code(prompt)
    print(generated_code)
