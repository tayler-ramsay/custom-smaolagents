from smolagents import CodeAgent, DuckDuckGoSearchTool, HfApiModel

# Define the agent with its tools and model
agent = CodeAgent(
    tools=[DuckDuckGoSearchTool()],  # Use DuckDuckGo for search
    model=HfApiModel()              # Load a Hugging Face-hosted model
)

# Run the agent with a question
result = agent.run("How many seconds would it take for a leopard at full speed to run through Pont des Arts?")
print(result)