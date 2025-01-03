class FileManager:
    @staticmethod
    def search_code_snippet(directory, pattern):
        import os
        import re
        matches = []
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".py"):
                    with open(os.path.join(root, file), "r") as f:
                        content = f.read()
                        if re.search(pattern, content):
                            matches.append((file, re.findall(pattern, content)))
        return matches

    def suggest_learning_resources(topic):
        # A simple dictionary to map topics to learning resources
        resources = {
            "python": ["https://docs.python.org/3/tutorial/", "https://realpython.com/"],
            "machine learning": ["https://scikit-learn.org/stable/", "https://www.coursera.org/learn/machine-learning"],
            "deep learning": ["https://www.deeplearningbook.org/", "https://www.fast.ai/"],
            "data science": ["https://jakevdp.github.io/PythonDataScienceHandbook/", "https://www.kaggle.com/learn/overview"]
        }
        return resources.get(topic.lower(), "No resources available for this topic.")

        import subprocess
        try:
            result = subprocess.run(["python", "-c", code], capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            return f"Error: {e.stderr}"

        import json
        config_file = "config.json"
        try:
            with open(config_file, "r") as file:
                config = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            config = {}
        config[service_name] = api_key
        with open(config_file, "w") as file:
            json.dump(config, file, indent=4)
        return f"API key for {service_name} stored successfully."

    def retrieve_api_key(service_name):
        import json
        config_file = "config.json"
        try:
            with open(config_file, "r") as file:
                config = json.load(file)
            return config.get(service_name, "API key not found.")
        except (FileNotFoundError, json.JSONDecodeError):
            return "API key not found."

        # A simple dictionary to map common error messages to explanations
        error_explanations = {
            "SyntaxError": "This error occurs when the Python parser encounters a syntax error in your code.",
            "IndentationError": "This error occurs when there is an incorrect indentation in your code.",
            "TypeError": "This error occurs when an operation or function is applied to an object of inappropriate type.",
            "NameError": "This error occurs when a local or global name is not found.",
            "IndexError": "This error occurs when you try to access an index that is out of range."
        }
        for error, explanation in error_explanations.items():
            if error in error_message:
                return explanation
        return "No explanation available for this error."

        import subprocess
        try:
            subprocess.run(["git", "add", "."], check=True)
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
            return "Changes committed successfully."
        except subprocess.CalledProcessError as e:
            return f"An error occurred: {e}"

        with open(filename, "r") as file:
            return file.read()

    @staticmethod
    def write_file(filename, content):
        with open(filename, "w") as file:
            file.write(content)
