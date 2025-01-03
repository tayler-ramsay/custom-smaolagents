import gradio as gr
from src.smolagents.llm_integration import generate_code

def gpt_interface():
    def generate(prompt):
        return generate_code(prompt)

    with gr.Blocks() as demo:
        gr.Markdown("# GPT Text Generation")
        prompt = gr.Textbox(label="Enter your prompt")
        output = gr.Textbox(label="Generated Text")
        prompt.submit(generate, inputs=prompt, outputs=output)

    demo.launch()

if __name__ == "__main__":
    gpt_interface()
