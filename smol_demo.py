from smolagents import CodeAgent, DuckDuckGoSearchTool, HfApiModel

# Define the agent with tools and model
agent = CodeAgent(tools=[DuckDuckGoSearchTool()], model=HfApiModel())

# Run the agent with a sample query
result = agent.run("How many seconds would it take for a leopard at full speed to run through Pont des Arts?")
print(result)
