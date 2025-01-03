# Collaborative Coding Assistant

This project is a collaborative coding assistant that integrates the DeepSeek v3 API, dynamically switches between Hugging Face LLMs, and provides a Gradio-based user interface for interaction.

## Setup Instructions

1. **Environment Setup**:
   - Ensure you have Python 3.10+ installed.
   - Create and activate a virtual environment:
     ```bash
     python -m venv smolenv
     source smolenv/bin/activate
     ```
   - Install the required packages:
     ```bash
     pip install -r requirements.txt
     ```

2. **Running the Application**:
   - Set the `PYTHONPATH` to include the `src` directory and run the Gradio UI:
     ```bash
     PYTHONPATH=src python src/smolagents/ui/main_ui.py
     ```
   - Access the application at `http://127.0.0.1:7860` in your web browser.

3. **Using the Application**:
   - Enter a prompt in the text box.
   - Select the desired LLM model from the dropdown.
   - Optionally, specify a file to save the output.
   - Click "Submit" to receive responses from the agents.

## Adding More LLMs

Developers can add more LLMs by following these steps:

1. **Update the LLMAgent**:
   - Open `src/smolagents/agents/llm_agent.py`.
   - Add the new model to the `self.models` dictionary in the `__init__` method. For example:
     ```python
     self.models["new-model"] = "path/to/new-model"
     ```

2. **Ensure Model Availability**:
   - Make sure the new model is available in the Hugging Face model hub or locally accessible.

3. **Test the Integration**:
   - Run the application and test the new model by selecting it from the dropdown in the Gradio UI.


- **Font Loading Errors**: Ensure that all required font files are available and paths are correctly set in the CSS.
- **Deprecation Warnings**: Update CSS files to comply with the latest standards.

## Future Improvements

- Add multi-language support.
- Enhance logging and error handling.
- Optimize resource loading and management.
