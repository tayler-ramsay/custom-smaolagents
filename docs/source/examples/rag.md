<!--Copyright 2024 The HuggingFace Team. All rights reserved.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.

⚠️ Note that this file is in Markdown but contain specific syntax for our doc-builder (similar to MDX) that may not be
rendered properly in your Markdown viewer.

-->
# Agentic RAG

[[open-in-colab]]

Retrieval-Augmented-Generation (RAG) is “using an LLM to answer a user query, but basing the answer on information retrieved from a knowledge base”. It has many advantages over using a vanilla or fine-tuned LLM: to name a few, it allows to ground the answer on true facts and reduce confabulations, it allows to provide the LLM with domain-specific knowledge, and it allows fine-grained control of access to information from the knowledge base.

But vanilla RAG has limitations, most importantly these two:
- It performs only one retrieval step: if the results are bad, the generation in turn will be bad.
- Semantic similarity is computed with the user query as a reference, which might be suboptimal: for instance, the user query will often be a question and the document containing the true answer will be in affirmative voice, so its similarity score will be downgraded compared to other source documents in the interrogative form, leading to a risk of missing the relevant information.

We can alleviate these problems by making a RAG agent: very simply, an agent armed with a retriever tool!

This agent will: ✅ Formulate the query itself and ✅ Critique to re-retrieve if needed.

So it should naively recover some advanced RAG techniques!
- Instead of directly using the user query as the reference in semantic search, the agent formulates itself a reference sentence that can be closer to the targeted documents, as in [HyDE](https://huggingface.co/papers/2212.10496).
The agent can the generated snippets and re-retrieve if needed, as in [Self-Query](https://docs.llamaindex.ai/en/stable/examples/evaluation/RetryQuery/).

Let's build this system. 🛠️

Run the line below to install required dependencies:
```bash
!pip install smolagents pandas langchain langchain-community sentence-transformers faiss-cpu --upgrade -q
```
Let's login in order to call the HF Inference API:

```py
from huggingface_hub import login

login()
```

We first load a knowledge base on which we want to perform RAG: this dataset is a compilation of the documentation pages for many Hugging Face libraries, stored as markdown.

Then prepare the knowledge base by processing the dataset and storing it into a vector database to be used by the retriever.

We use [LangChain](https://python.langchain.com/docs/introduction/) for its excellent vector database utilities.

```py
import time
import datasets
from tqdm import tqdm
from transformers import AutoTokenizer
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores.utils import DistanceStrategy

knowledge_base = datasets.load_dataset("m-ric/huggingface_doc", split="train")

source_docs = [
    Document(page_content=doc["text"], metadata={"source": doc["source"].split("/")[1]})
    for doc in knowledge_base
]

embedding_model = "TaylorAI/gte-tiny"

text_splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
    AutoTokenizer.from_pretrained(embedding_model),
    chunk_size=200,
    chunk_overlap=20,
    add_start_index=True,
    strip_whitespace=True,
    separators=["\n\n", "\n", ".", " ", ""],
)

# Split docs and keep only unique ones
print("Splitting documents...")
docs_processed = []
unique_texts = {}
for doc in tqdm(source_docs):
    new_docs = text_splitter.split_documents([doc])
    for new_doc in new_docs:
        if new_doc.page_content not in unique_texts:
            unique_texts[new_doc.page_content] = True
            docs_processed.append(new_doc)

print(
    "Embedding documents... This should take a few minutes (5 minutes on MacBook with M1 Pro)"
)
t0 = time.time()
embedding_model = HuggingFaceEmbeddings(
    model_name=embedding_model,
    show_progress=True
)
vectordb = FAISS.from_documents(
    documents=docs_processed,
    embedding=embedding_model,
    distance_strategy=DistanceStrategy.COSINE,
)
t1 = time.time()
print(f"VectorDB embedded in {int((t1-t0)/60)} minutes")
```
If you want to improve performance, head to the [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard) to select a bigger model for your embeddings: here we selected a small one for the sake of speed.

Now the database is ready: let’s build our agentic RAG system!

👉 We only need a RetrieverTool that our agent can leverage to retrieve information from the knowledge base.

Since we need to add a vectordb as an attribute of the tool, we cannot simply use the simple tool constructor with a `@tool` decorator: so we will follow the advanced setup highlighted in the [tools tutorial](../tutorials/tools).

```py
from smolagents import Tool

class RetrieverTool(Tool):
    name = "retriever"
    description = "Using semantic similarity, retrieves some documents from the knowledge base that have the closest embeddings to the input query."
    inputs = {
        "query": {
            "type": "string",
            "description": "The query to perform. This should be semantically close to your target documents. Use the affirmative form rather than a question.",
        }
    }
    output_type = "string"

    def __init__(self, vectordb, **kwargs):
        super().__init__(**kwargs)
        self.vectordb = vectordb

    def forward(self, query: str) -> str:
        assert isinstance(query, str), "Your search query must be a string"

        docs = self.vectordb.similarity_search(
            query,
            k=7,
        )

        return "\nRetrieved documents:\n" + "".join(
            [
                f"===== Document {str(i)} =====\n" + doc.page_content
                for i, doc in enumerate(docs)
            ]
        )
```

Now it’s straightforward to create an agent that leverages this tool!

The agent will need these arguments upon initialization:
- `tools`: a list of tools that the agent will be able to call.
- `model`: the LLM that powers the agent.
Our `model` must be a callable that takes as input a list of messages and returns text. It also needs to accept a stop_sequences argument that indicates when to stop its generation. For convenience, we directly use the HfEngine class provided in the package to get a LLM engine that calls Hugging Face's Inference API.

And we use meta-llama/Llama-3.3-70B-Instruct as the llm engine because:
- It has a long 128k context, which is helpful for processing long source documents
- It is served for free at all times on HF's Inference API!

_Note:_ The Inference API hosts models based on various criteria, and deployed models may be updated or replaced without prior notice. Learn more about it [here](https://huggingface.co/docs/api-inference/supported-models).

```py
from smolagents import HfApiModel, CodeAgent

retriever_tool = RetrieverTool(vectordb)
agent = CodeAgent(
    tools=[retriever_tool], model=HfApiModel("Qwen/Qwen2.5-72B-Instruct"), max_iterations=4, verbose=True
)
```

Upon initializing the CodeAgent, it has been automatically given a default system prompt that tells the LLM engine to process step-by-step and generate tool calls as code snippets, but you could replace this prompt template with your own as needed.

Then when its `.run()` method is launched, the agent takes care of calling the LLM engine, and executing the tool calls, all in a loop that ends only when tool `final_answer` is called with the final answer as its argument.

```py
agent_output = agent.run("How can I push a model to the Hub?")

print("Final output:")
print(agent_output)
```


