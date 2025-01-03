import gradio as gr
from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from smolagents.agents.deepseek_agent import DeepSeekAgent
from smolagents.agents.deepseek_agent import DeepSeekAgent
from smolagents.agents.communication_agent import CommunicationAgent
from smolagents.agents.llm_agent import LLMAgent
from smolagents.tools.file_manager import FileManager

deepseek_agent = DeepSeekAgent()
llm_agent = LLMAgent()
communication_agent = CommunicationAgent(deepseek_agent, llm_agent)

def handle_user_input(prompt, model_name, save_to_file):
    if model_name == "code-snippet-search":
        response = FileManager.search_code_snippet("src", prompt)
    elif model_name == "suggest-learning-resources":
        response = FileManager.suggest_learning_resources(prompt)
        response = FileManager.interactive_debugging(prompt)
        service_name, api_key = prompt.split(',')
        response = FileManager.store_api_key(service_name.strip(), api_key.strip())
    elif model_name == "retrieve-api-key":
        response = FileManager.retrieve_api_key(prompt.strip())
        response = CodeFormatter.suggest_refactoring(prompt)
        response = FileManager.explain_error(prompt)
        response = FileManager.commit_changes(prompt)
        response = communication_agent.handle_instruction(prompt, model_name)
    if model_name == "code-snippet-search":
        response = FileManager.search_code_snippet("src", prompt)
        # Apply syntax highlighting to the code snippets
        response = [(file, [highlight(snippet, PythonLexer(), HtmlFormatter()) for snippet in snippets]) for file, snippets in response]
    elif model_name in llm_agent.models:
        response = communication_agent.handle_instruction(prompt, model_name)
    else:
        response = communication_agent.handle_instruction(prompt, "deepseek")
    return response

interface = gr.Interface(
    fn=handle_user_input,
    inputs=[
        gr.Textbox(label="Enter Prompt"),
        gr.Dropdown([
            "gpt-neo", "gpt-j", "gpt-2", "distilgpt2",
            "code-snippet-search",
            "suggest-learning-resources", "interactive-debugging",
            "store-api-key", "retrieve-api-key",
            "suggest-refactoring", "explain-error",
            "commit-changes"
        ], label="Select Feature"),
        gr.Textbox(label="Optional Save File")
    ],
    outputs=gr.JSON(label="Agent Responses")
)

if __name__ == "__main__":
    interface.launch()
