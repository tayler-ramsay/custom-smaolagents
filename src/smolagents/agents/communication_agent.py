class CommunicationAgent:
    def __init__(self, deepseek_agent, llm_agent):
        self.deepseek_agent = deepseek_agent
        self.llm_agent = llm_agent

    def handle_instruction(self, prompt, model_name):
        deepseek_response = self.deepseek_agent.query(prompt)
        self.llm_agent.switch_model("gpt-neo")
        llm_response = self.llm_agent.handle_natural_language_query(prompt, model_name)
        return {"deepseek_response": deepseek_response, "llm_response": llm_response}
