#!/usr/bin/env python
# coding=utf-8

# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# You may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import ast
import importlib
import inspect
import json
import os
import sys
import tempfile
import torch
import textwrap
from functools import lru_cache, wraps
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union, get_type_hints
from huggingface_hub import (
    create_repo,
    get_collection,
    hf_hub_download,
    metadata_update,
    upload_folder,
)
from huggingface_hub.utils import RepositoryNotFoundError
from packaging import version
import logging
from src.smolagents.logging_config import setup_logging
from transformers.utils import (
    TypeHintParsingException,
    cached_file,
    get_json_schema,
    is_accelerate_available,
    is_torch_available,
)
from transformers.utils.chat_template_utils import _parse_type_hint

from transformers.dynamic_module_utils import get_imports
from transformers import AutoProcessor

from .custom_types import ImageType, handle_agent_input_types, handle_agent_output_types
from .utils import instance_to_source
from .tool_validation import validate_tool_attributes, MethodChecker


setup_logging()
logger = logging.getLogger(__name__)


if is_torch_available():
    pass

if is_accelerate_available():
    pass


TOOL_CONFIG_FILE = "tool_config.json"


def get_repo_type(repo_id, repo_type=None, **hub_kwargs):
    if repo_type is not None:
        return repo_type
    try:
        hf_hub_download(repo_id, TOOL_CONFIG_FILE, repo_type="space", **hub_kwargs)
        return "space"
    except RepositoryNotFoundError:
        try:
            hf_hub_download(repo_id, TOOL_CONFIG_FILE, repo_type="model", **hub_kwargs)
            return "model"
        except RepositoryNotFoundError:
            raise EnvironmentError(
                f"`{repo_id}` does not seem to be a valid repo identifier on the Hub."
            )
        except Exception:
            return "model"
    except Exception:
        return "space"


def setup_default_tools():
    default_tools = {}
    main_module = importlib.import_module("smolagents")

    for task_name, tool_class_name in TOOL_MAPPING.items():
        tool_class = getattr(main_module, tool_class_name)
        tool_instance = tool_class()
        default_tools[tool_class.name] = tool_instance

    return default_tools


def validate_after_init(cls):
    original_init = cls.__init__

    @wraps(original_init)
    def new_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.validate_arguments()

    cls.__init__ = new_init
    return cls


def _convert_type_hints_to_json_schema(func: Callable) -> Dict:
    type_hints = get_type_hints(func)
    signature = inspect.signature(func)
    properties = {}
    for param_name, param_type in type_hints.items():
        if param_name != "return":
            properties[param_name] = _parse_type_hint(param_type)
            if signature.parameters[param_name].default != inspect.Parameter.empty:
                properties[param_name]["nullable"] = True
    for param_name in signature.parameters.keys():
        if signature.parameters[param_name].default != inspect.Parameter.empty:
            if (
                param_name not in properties
            ):  # this can happen if the param has no type hint but a default value
                properties[param_name] = {"nullable": True}
    return properties


AUTHORIZED_TYPES = [
    "string",
    "boolean",
    "integer",
    "number",
    "image",
    "audio",
    "any",
    "object",
]

CONVERSION_DICT = {"str": "string", "int": "integer", "float": "number"}


class Tool:
    """
    A base class for the functions used by the agent. Subclass this and implement the `forward` method as well as the
    following class attributes:

    - **description** (`str`) -- A short description of what your tool does, the inputs it expects and the output(s) it
      will return. For instance 'This is a tool that downloads a file from a `url`. It takes the `url` as input, and
      returns the text contained in the file'.
    - **name** (`str`) -- A performative name that will be used for your tool in the prompt to the agent. For instance
      `"text-classifier"` or `"image_generator"`.
    - **inputs** (`Dict[str, Dict[str, Union[str, type]]]`) -- The dict of modalities expected for the inputs.
      It has one `type`key and a `description`key.
      This is used by `launch_gradio_demo` or to make a nice space from your tool, and also can be used in the generated
      description for your tool.
    - **output_type** (`type`) -- The type of the tool output. This is used by `launch_gradio_demo`
      or to make a nice space from your tool, and also can be used in the generated description for your tool.

    You can also override the method [`~Tool.setup`] if your tool has an expensive operation to perform before being
    usable (such as loading a model). [`~Tool.setup`] will be called the first time you use your tool, but not at
    instantiation.
    """

    name: str
    description: str
    inputs: Dict[str, Dict[str, Union[str, type, bool]]]
    output_type: str

    def __init__(self, *args, **kwargs):
        self.is_initialized = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        validate_after_init(cls)

    def validate_arguments(self):
        required_attributes = {
            "description": str,
            "name": str,
            "inputs": dict,
            "output_type": str,
        }

        for attr, expected_type in required_attributes.items():
            attr_value = getattr(self, attr, None)
            if attr_value is None:
                raise TypeError(f"You must set an attribute {attr}.")
            if not isinstance(attr_value, expected_type):
                raise TypeError(
                    f"Attribute {attr} should have type {expected_type.__name__}, got {type(attr_value)} instead."
                )
        for input_name, input_content in self.inputs.items():
            assert isinstance(
                input_content, dict
            ), f"Input '{input_name}' should be a dictionary."
            assert (
                "type" in input_content and "description" in input_content
            ), f"Input '{input_name}' should have keys 'type' and 'description', has only {list(input_content.keys())}."
            if input_content["type"] not in AUTHORIZED_TYPES:
                raise Exception(
                    f"Input '{input_name}': type '{input_content['type']}' is not an authorized value, should be one of {AUTHORIZED_TYPES}."
                )

        assert getattr(self, "output_type", None) in AUTHORIZED_TYPES

        # Validate forward function signature, except for PipelineTool
        if not (
            hasattr(self, "is_pipeline_tool")
            and getattr(self, "is_pipeline_tool") is True
        ):
            signature = inspect.signature(self.forward)

            if not set(signature.parameters.keys()) == set(self.inputs.keys()):
                raise Exception(
                    "Tool's 'forward' method should take 'self' as its first argument, then its next arguments should match the keys of tool attribute 'inputs'."
                )

            json_schema = _convert_type_hints_to_json_schema(self.forward)
            for key, value in self.inputs.items():
                if "nullable" in value:
                    assert (
                        key in json_schema and "nullable" in json_schema[key]
                    ), f"Nullable argument '{key}' in inputs should have key 'nullable' set to True in function signature."
                if key in json_schema and "nullable" in json_schema[key]:
                    assert (
                        "nullable" in value
                    ), f"Nullable argument '{key}' in function signature should have key 'nullable' set to True in inputs."

    def forward(self, *args, **kwargs):
        return NotImplementedError("Write this method in your subclass of `Tool`.")

    def __call__(self, *args, sanitize_inputs_outputs: bool = False, **kwargs):
        if not self.is_initialized:
            self.setup()
        if sanitize_inputs_outputs:
            args, kwargs = handle_agent_input_types(*args, **kwargs)
        outputs = self.forward(*args, **kwargs)
        if sanitize_inputs_outputs:
            outputs = handle_agent_output_types(outputs, self.output_type)
        return outputs

    def setup(self):
        """
        Overwrite this method here for any operation that is expensive and needs to be executed before you start using
        your tool. Such as loading a big model.
        """
        self.is_initialized = True

    def save(self, output_dir):
        """
        Saves the relevant code files for your tool so it can be pushed to the Hub. This will copy the code of your
        tool in `output_dir` as well as autogenerate:

        - a `tool.py` file containing the logic for your tool.
        - an `app.py` file providing an UI for your tool when it is exported to a Space with `tool.push_to_hub()`
        - a `requirements.txt` containing the names of the module used by your tool (as detected when inspecting its
          code)

        Args:
            output_dir (`str`): The folder in which you want to save your tool.
        """
        os.makedirs(output_dir, exist_ok=True)
        class_name = self.__class__.__name__
        tool_file = os.path.join(output_dir, "tool.py")

        # Save tool file
        if type(self).__name__ == "SimpleTool":
            # Check that imports are self-contained
            source_code = inspect.getsource(self.forward).replace("@tool", "")
            forward_node = ast.parse(textwrap.dedent(source_code))
            # If tool was created using '@tool' decorator, it has only a forward pass, so it's simpler to just get its code
            method_checker = MethodChecker(set())
            method_checker.visit(forward_node)

            if len(method_checker.errors) > 0:
                raise (ValueError("\n".join(method_checker.errors)))

            forward_source_code = inspect.getsource(self.forward)
            tool_code = textwrap.dedent(f"""
            from smolagents import Tool
            from typing import Optional

            class {class_name}(Tool):
                name = "{self.name}"
                description = "{self.description}"
                inputs = {json.dumps(self.inputs, separators=(',', ':'))}
                output_type = "{self.output_type}"
            """).strip()
            import re

            def add_self_argument(source_code: str) -> str:
                """Add 'self' as first argument to a function definition if not present."""
                pattern = r"def forward\(((?!self)[^)]*)\)"

                def replacement(match):
                    args = match.group(1).strip()
                    if args:  # If there are other arguments
                        return f"def forward(self, {args})"
                    return "def forward(self)"

                return re.sub(pattern, replacement, source_code)

            forward_source_code = forward_source_code.replace(self.name, "forward")
            forward_source_code = add_self_argument(forward_source_code)
            forward_source_code = forward_source_code.replace("@tool", "").strip()
            tool_code += "\n\n" + textwrap.indent(forward_source_code, "    ")

        else:  # If the tool was not created by the @tool decorator, it was made by subclassing Tool
            if type(self).__name__ in [
                "SpaceToolWrapper",
                "LangChainToolWrapper",
                "GradioToolWrapper",
            ]:
                raise ValueError(
                    "Cannot save objects created with from_space, from_langchain or from_gradio, as this would create errors."
                )

            validate_tool_attributes(self.__class__)

            tool_code = instance_to_source(self, base_cls=Tool)

        with open(tool_file, "w", encoding="utf-8") as f:
            f.write(tool_code.replace(":true,", ":True,").replace(":true}", ":True}"))

        # Save app file
        app_file = os.path.join(output_dir, "app.py")
        with open(app_file, "w", encoding="utf-8") as f:
            f.write(
                textwrap.dedent(f"""
            from smolagents import launch_gradio_demo
            from typing import Optional
            from tool import {class_name}

            tool = {class_name}()

            launch_gradio_demo(tool)
            """).lstrip()
            )

        # Save requirements file
        requirements_file = os.path.join(output_dir, "requirements.txt")

        imports = []
        for module in [tool_file]:
            imports.extend(get_imports(module))
        imports = list(
            set(
                [
                    el
                    for el in imports + ["smolagents"]
                    if el not in sys.stdlib_module_names
                ]
            )
        )
        with open(requirements_file, "w", encoding="utf-8") as f:
            f.write("\n".join(imports) + "\n")

    def push_to_hub(
        self,
        repo_id: str,
        commit_message: str = "Upload tool",
        private: Optional[bool] = None,
        token: Optional[Union[bool, str]] = None,
        create_pr: bool = False,
    ) -> str:
        """
        Upload the tool to the Hub.

        For this method to work properly, your tool must have been defined in a separate module (not `__main__`).
        For instance:
        ```
        from my_tool_module import MyTool
        my_tool = MyTool()
        my_tool.push_to_hub("my-username/my-space")
        ```

        Parameters:
            repo_id (`str`):
                The name of the repository you want to push your tool to. It should contain your organization name when
                pushing to a given organization.
            commit_message (`str`, *optional*, defaults to `"Upload tool"`):
                Message to commit while pushing.
            private (`bool`, *optional*):
                Whether to make the repo private. If `None` (default), the repo will be public unless the organization's default is private. This value is ignored if the repo already exists.
            token (`bool` or `str`, *optional*):
                The token to use as HTTP bearer authorization for remote files. If unset, will use the token generated
                when running `huggingface-cli login` (stored in `~/.huggingface`).
            create_pr (`bool`, *optional*, defaults to `False`):
                Whether or not to create a PR with the uploaded files or directly commit.
        """
        repo_url = create_repo(
            repo_id=repo_id,
            token=token,
            private=private,
            exist_ok=True,
            repo_type="space",
            space_sdk="gradio",
        )
        repo_id = repo_url.repo_id
        metadata_update(repo_id, {"tags": ["tool"]}, repo_type="space")

        with tempfile.TemporaryDirectory() as work_dir:
            # Save all files.
            self.save(work_dir)
            print(work_dir)
            with open(work_dir + "/tool.py", "r") as f:
                print("\n".join(f.readlines()))
            logger.info(
                f"Uploading the following files to {repo_id}: {','.join(os.listdir(work_dir))}"
            )
            return upload_folder(
                repo_id=repo_id,
                commit_message=commit_message,
                folder_path=work_dir,
                token=token,
                create_pr=create_pr,
                repo_type="space",
            )

    @classmethod
    def from_hub(
        cls,
        repo_id: str,
        token: Optional[str] = None,
        trust_remote_code: bool = False,
        **kwargs,
    ):
        """
        Loads a tool defined on the Hub.

        <Tip warning={true}>

        Loading a tool from the Hub means that you'll download the tool and execute it locally.
        ALWAYS inspect the tool you're downloading before loading it within your runtime, as you would do when
        installing a package using pip/npm/apt.

        </Tip>

        Args:
            repo_id (`str`):
                The name of the repo on the Hub where your tool is defined.
            token (`str`, *optional*):
                The token to identify you on hf.co. If unset, will use the token generated when running
                `huggingface-cli login` (stored in `~/.huggingface`).
            trust_remote_code(`str`, *optional*, defaults to False):
                This flags marks that you understand the risk of running remote code and that you trust this tool.
                If not setting this to True, loading the tool from Hub will fail.
            kwargs (additional keyword arguments, *optional*):
                Additional keyword arguments that will be split in two: all arguments relevant to the Hub (such as
                `cache_dir`, `revision`, `subfolder`) will be used when downloading the files for your tool, and the
                others will be passed along to its init.
        """
        assert trust_remote_code, "Loading a tool from Hub requires to trust remote code. Make sure you've inspected the repo and pass `trust_remote_code=True` to load the tool."

        hub_kwargs_names = [
            "cache_dir",
            "force_download",
            "resume_download",
            "proxies",
            "revision",
            "repo_type",
            "subfolder",
            "local_files_only",
        ]
        hub_kwargs = {k: v for k, v in kwargs.items() if k in hub_kwargs_names}

        tool_file = "tool.py"

        # Get the tool's tool.py file.
        hub_kwargs["repo_type"] = get_repo_type(repo_id, **hub_kwargs)
        resolved_tool_file = cached_file(
            repo_id,
            tool_file,
            token=token,
            **hub_kwargs,
            _raise_exceptions_for_gated_repo=False,
            _raise_exceptions_for_missing_entries=False,
            _raise_exceptions_for_connection_errors=False,
        )
        tool_code = resolved_tool_file is not None
        if resolved_tool_file is None:
            resolved_tool_file = cached_file(
                repo_id,
                tool_file,
                token=token,
                **hub_kwargs,
                _raise_exceptions_for_gated_repo=False,
                _raise_exceptions_for_missing_entries=False,
                _raise_exceptions_for_connection_errors=False,
            )
        if resolved_tool_file is None:
            raise EnvironmentError(
                f"{repo_id} does not appear to provide a valid configuration in `tool_config.json` or `config.json`."
            )

        with open(resolved_tool_file, encoding="utf-8") as reader:
            tool_code = "".join(reader.readlines())

        # Find the Tool subclass in the namespace
        with tempfile.TemporaryDirectory() as temp_dir:
            # Save the code to a file
            module_path = os.path.join(temp_dir, "tool.py")
            with open(module_path, "w") as f:
                f.write(tool_code)

            print("TOOLCODE:\n", tool_code)

            # Load module from file path
            spec = importlib.util.spec_from_file_location("custom_tool", module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find and instantiate the Tool class
            for item_name in dir(module):
                item = getattr(module, item_name)
                if isinstance(item, type) and issubclass(item, Tool) and item != Tool:
                    tool_class = item
                    break

            if tool_class is None:
                raise ValueError("No Tool subclass found in the code.")

        if not isinstance(tool_class.inputs, dict):
            tool_class.inputs = ast.literal_eval(tool_class.inputs)

        return tool_class(**kwargs)

    @staticmethod
    def from_space(
        space_id: str,
        name: str,
        description: str,
        api_name: Optional[str] = None,
        token: Optional[str] = None,
    ):
        """
        Creates a [`Tool`] from a Space given its id on the Hub.

        Args:
            space_id (`str`):
                The id of the Space on the Hub.
            name (`str`):
                The name of the tool.
            description (`str`):
                The description of the tool.
            api_name (`str`, *optional*):
                The specific api_name to use, if the space has several tabs. If not precised, will default to the first available api.
            token (`str`, *optional*):
                Add your token to access private spaces or increase your GPU quotas.
        Returns:
            [`Tool`]:
                The Space, as a tool.

        Examples:
        ```
        image_generator = Tool.from_space(
            space_id="black-forest-labs/FLUX.1-schnell",
            name="image-generator",
            description="Generate an image from a prompt"
        )
        image = image_generator("Generate an image of a cool surfer in Tahiti")
        ```
        ```
        face_swapper = Tool.from_space(
            "tuan2308/face-swap",
            "face_swapper",
            "Tool that puts the face shown on the first image on the second image. You can give it paths to images.",
        )
        image = face_swapper('./aymeric.jpeg', './ruth.jpg')
        ```
        """
        from gradio_client import Client, handle_file

        class SpaceToolWrapper(Tool):
            def __init__(
                self,
                space_id: str,
                name: str,
                description: str,
                api_name: Optional[str] = None,
                token: Optional[str] = None,
            ):
                self.name = name
                self.description = description
                self.client = Client(space_id, hf_token=token)
                space_description = self.client.view_api(
                    return_format="dict", print_info=False
                )["named_endpoints"]

                # If api_name is not defined, take the first of the available APIs for this space
                if api_name is None:
                    api_name = list(space_description.keys())[0]
                    logger.warning(
                        f"Since `api_name` was not defined, it was automatically set to the first avilable API: `{api_name}`."
                    )
                self.api_name = api_name

                try:
                    space_description_api = space_description[api_name]
                except KeyError:
                    raise KeyError(
                        f"Could not find specified {api_name=} among available api names."
                    )

                self.inputs = {}
                for parameter in space_description_api["parameters"]:
                    if not parameter["parameter_has_default"]:
                        parameter_type = parameter["type"]["type"]
                        if parameter_type == "object":
                            parameter_type = "any"
                        self.inputs[parameter["parameter_name"]] = {
                            "type": parameter_type,
                            "description": parameter["python_type"]["description"],
                        }
                output_component = space_description_api["returns"][0]["component"]
                if output_component == "Image":
                    self.output_type = "image"
                elif output_component == "Audio":
                    self.output_type = "audio"
                else:
                    self.output_type = "any"
                self.is_initialized = True

            def sanitize_argument_for_prediction(self, arg):
                from gradio_client.utils import is_http_url_like

                if isinstance(arg, ImageType):
                    temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    arg.save(temp_file.name)
                    arg = temp_file.name
                if (
                    isinstance(arg, (str, Path))
                    and Path(arg).exists()
                    and Path(arg).is_file()
                ) or is_http_url_like(arg):
                    arg = handle_file(arg)
                return arg

            def forward(self, *args, **kwargs):
                # Preprocess args and kwargs:
                args = list(args)
                for i, arg in enumerate(args):
                    args[i] = self.sanitize_argument_for_prediction(arg)
                for arg_name, arg in kwargs.items():
                    kwargs[arg_name] = self.sanitize_argument_for_prediction(arg)

                output = self.client.predict(*args, api_name=self.api_name, **kwargs)
                if isinstance(output, tuple) or isinstance(output, list):
                    return output[
                        0
                    ]  # Sometime the space also returns the generation seed, in which case the result is at index 0
                return output

        return SpaceToolWrapper(
            space_id=space_id,
            name=name,
            description=description,
            api_name=api_name,
            token=token,
        )

    @staticmethod
    def from_gradio(gradio_tool):
        """
        Creates a [`Tool`] from a gradio tool.
        """
        import inspect

        class GradioToolWrapper(Tool):
            def __init__(self, _gradio_tool):
                self.name = _gradio_tool.name
                self.description = _gradio_tool.description
                self.output_type = "string"
                self._gradio_tool = _gradio_tool
                func_args = list(inspect.signature(_gradio_tool.run).parameters.items())
                self.inputs = {
                    key: {"type": CONVERSION_DICT[value.annotation], "description": ""}
                    for key, value in func_args
                }
                self.forward = self._gradio_tool.run

        return GradioToolWrapper(gradio_tool)

    @staticmethod
    def from_langchain(langchain_tool):
        """
        Creates a [`Tool`] from a langchain tool.
        """

        class LangChainToolWrapper(Tool):
            def __init__(self, _langchain_tool):
                self.name = _langchain_tool.name.lower()
                self.description = _langchain_tool.description
                self.inputs = _langchain_tool.args.copy()
                for input_content in self.inputs.values():
                    if "title" in input_content:
                        input_content.pop("title")
                    input_content["description"] = ""
                self.output_type = "string"
                self.langchain_tool = _langchain_tool

            def forward(self, *args, **kwargs):
                tool_input = kwargs.copy()
                for index, argument in enumerate(args):
                    if index < len(self.inputs):
                        input_key = next(iter(self.inputs))
                        tool_input[input_key] = argument
                return self.langchain_tool.run(tool_input)

        return LangChainToolWrapper(langchain_tool)


DEFAULT_TOOL_DESCRIPTION_TEMPLATE = """
- {{ tool.name }}: {{ tool.description }}
    Takes inputs: {{tool.inputs}}
    Returns an output of type: {{tool.output_type}}
"""


def get_tool_description_with_args(
    tool: Tool, description_template: Optional[str] = None
) -> str:
    if description_template is None:
        description_template = DEFAULT_TOOL_DESCRIPTION_TEMPLATE
    compiled_template = compile_jinja_template(description_template)
    rendered = compiled_template.render(
        tool=tool,
    )
    return rendered


@lru_cache
def compile_jinja_template(template):
    try:
        import jinja2
        from jinja2.exceptions import TemplateError
        from jinja2.sandbox import ImmutableSandboxedEnvironment
    except ImportError:
        raise ImportError("template requires jinja2 to be installed.")

    if version.parse(jinja2.__version__) < version.parse("3.1.0"):
        raise ImportError(
            "template requires jinja2>=3.1.0 to be installed. Your version is "
            f"{jinja2.__version__}."
        )

    def raise_exception(message):
        raise TemplateError(message)

    jinja_env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    jinja_env.globals["raise_exception"] = raise_exception
    return jinja_env.from_string(template)


def launch_gradio_demo(tool: Tool):
    """
    Launches a gradio demo for a tool. The corresponding tool class needs to properly implement the class attributes
    `inputs` and `output_type`.

    Args:
        tool (`type`): The tool for which to launch the demo.
    """
    try:
        import gradio as gr
    except ImportError:
        raise ImportError(
            "Gradio should be installed in order to launch a gradio demo."
        )

    TYPE_TO_COMPONENT_CLASS_MAPPING = {
        "image": gr.Image,
        "audio": gr.Audio,
        "string": gr.Textbox,
        "integer": gr.Textbox,
        "number": gr.Textbox,
    }

    def fn(*args, **kwargs):
        return tool(*args, **kwargs, sanitize_inputs_outputs=True)

    gradio_inputs = []
    for input_name, input_details in tool.inputs.items():
        input_gradio_component_class = TYPE_TO_COMPONENT_CLASS_MAPPING[
            input_details["type"]
        ]
        new_component = input_gradio_component_class(label=input_name)
        gradio_inputs.append(new_component)

    output_gradio_componentclass = TYPE_TO_COMPONENT_CLASS_MAPPING[tool.output_type]
    gradio_output = output_gradio_componentclass(label="Output")

    gr.Interface(
        fn=fn,
        inputs=gradio_inputs,
        outputs=gradio_output,
        title=tool.name,
        article=tool.description,
    ).launch()


TOOL_MAPPING = {
    "python_interpreter": "PythonInterpreterTool",
    "web_search": "DuckDuckGoSearchTool",
    "transcriber": "SpeechToTextTool",
}


def load_tool(
    task_or_repo_id,
    model_repo_id: Optional[str] = None,
    token: Optional[str] = None,
    trust_remote_code: bool = False,
    **kwargs,
):
    """
    Main function to quickly load a tool, be it on the Hub or in the Transformers library.

    <Tip warning={true}>

    Loading a tool means that you'll download the tool and execute it locally.
    ALWAYS inspect the tool you're downloading before loading it within your runtime, as you would do when
    installing a package using pip/npm/apt.

    </Tip>

    Args:
        task_or_repo_id (`str`):
            The task for which to load the tool or a repo ID of a tool on the Hub. Tasks implemented in Transformers
            are:

            - `"document_question_answering"`
            - `"image_question_answering"`
            - `"speech_to_text"`
            - `"text_to_speech"`
            - `"translation"`

        model_repo_id (`str`, *optional*):
            Use this argument to use a different model than the default one for the tool you selected.
        token (`str`, *optional*):
            The token to identify you on hf.co. If unset, will use the token generated when running `huggingface-cli
            login` (stored in `~/.huggingface`).
        trust_remote_code (`bool`, *optional*, defaults to False):
            This needs to be accepted in order to load a tool from Hub.
        kwargs (additional keyword arguments, *optional*):
            Additional keyword arguments that will be split in two: all arguments relevant to the Hub (such as
            `cache_dir`, `revision`, `subfolder`) will be used when downloading the files for your tool, and the others
            will be passed along to its init.
    """
    if task_or_repo_id in TOOL_MAPPING:
        tool_class_name = TOOL_MAPPING[task_or_repo_id]
        main_module = importlib.import_module("smolagents")
        tools_module = main_module
        tool_class = getattr(tools_module, tool_class_name)
        return tool_class(token=token, **kwargs)
    else:
        return Tool.from_hub(
            task_or_repo_id,
            model_repo_id=model_repo_id,
            token=token,
            trust_remote_code=trust_remote_code,
            **kwargs,
        )


def add_description(description):
    """
    A decorator that adds a description to a function.
    """

    def inner(func):
        func.description = description
        func.name = func.__name__
        return func

    return inner


class ToolCollection:
    """
    Tool collections enable loading all Spaces from a collection in order to be added to the agent's toolbox.

    > [!NOTE]
    > Only Spaces will be fetched, so you can feel free to add models and datasets to your collection if you'd
    > like for this collection to showcase them.

    Args:
        collection_slug (str):
            The collection slug referencing the collection.
        token (str, *optional*):
            The authentication token if the collection is private.

    Example:

    ```py
    >>> from transformers import ToolCollection, CodeAgent

    >>> image_tool_collection = ToolCollection(collection_slug="huggingface-tools/diffusion-tools-6630bb19a942c2306a2cdb6f")
    >>> agent = CodeAgent(tools=[*image_tool_collection.tools], add_base_tools=True)

    >>> agent.run("Please draw me a picture of rivers and lakes.")
    ```
    """

    def __init__(self, collection_slug: str, token: Optional[str] = None):
        self._collection = get_collection(collection_slug, token=token)
        self._hub_repo_ids = {
            item.item_id for item in self._collection.items if item.item_type == "space"
        }
        self.tools = {Tool.from_hub(repo_id) for repo_id in self._hub_repo_ids}


def tool(tool_function: Callable) -> Tool:
    """
    Converts a function into an instance of a Tool subclass.

    Args:
        tool_function: Your function. Should have type hints for each input and a type hint for the output.
        Should also have a docstring description including an 'Args:' part where each argument is described.
    """
    parameters = get_json_schema(tool_function)["function"]
    if "return" not in parameters:
        raise TypeHintParsingException(
            "Tool return type not found: make sure your function has a return type hint!"
        )

    class SimpleTool(Tool):
        def __init__(self, name, description, inputs, output_type, function):
            self.name = name
            self.description = description
            self.inputs = inputs
            self.output_type = output_type
            self.forward = function
            self.is_initialized = True

    simple_tool = SimpleTool(
        parameters["name"],
        parameters["description"],
        parameters["parameters"]["properties"],
        parameters["return"]["type"],
        function=tool_function,
    )
    original_signature = inspect.signature(tool_function)
    new_parameters = [
        inspect.Parameter("self", inspect.Parameter.POSITIONAL_ONLY)
    ] + list(original_signature.parameters.values())
    new_signature = original_signature.replace(parameters=new_parameters)
    simple_tool.forward.__signature__ = new_signature
    return simple_tool


HUGGINGFACE_DEFAULT_TOOLS = {}


class Toolbox:
    """
    The toolbox contains all tools that the agent can perform operations with, as well as a few methods to
    manage them.

    Args:
        tools (`List[Tool]`):
            The list of tools to instantiate the toolbox with
        add_base_tools (`bool`, defaults to `False`, *optional*, defaults to `False`):
            Whether to add the tools available within `transformers` to the toolbox.
    """

    def __init__(self, tools: List[Tool], add_base_tools: bool = False):
        self._tools = {tool.name: tool for tool in tools}
        if add_base_tools:
            self.add_base_tools()

    def add_base_tools(self, add_python_interpreter: bool = False):
        global HUGGINGFACE_DEFAULT_TOOLS
        if len(HUGGINGFACE_DEFAULT_TOOLS.keys()) == 0:
            HUGGINGFACE_DEFAULT_TOOLS = setup_default_tools()
        for tool in HUGGINGFACE_DEFAULT_TOOLS.values():
            if tool.name != "python_interpreter" or add_python_interpreter:
                self.add_tool(tool)

    @property
    def tools(self) -> Dict[str, Tool]:
        """Get all tools currently in the toolbox"""
        return self._tools

    def show_tool_descriptions(
        self, tool_description_template: Optional[str] = None
    ) -> str:
        """
        Returns the description of all tools in the toolbox

        Args:
            tool_description_template (`str`, *optional*):
                The template to use to describe the tools. If not provided, the default template will be used.
        """
        return "\n".join(
            [
                get_tool_description_with_args(tool, tool_description_template)
                for tool in self._tools.values()
            ]
        )

    def add_tool(self, tool: Tool):
        """
        Adds a tool to the toolbox

        Args:
            tool (`Tool`):
                The tool to add to the toolbox.
        """
        if tool.name in self._tools:
            raise KeyError(f"Error: tool '{tool.name}' already exists in the toolbox.")
        self._tools[tool.name] = tool

    def remove_tool(self, tool_name: str):
        """
        Removes a tool from the toolbox

        Args:
            tool_name (`str`):
                The tool to remove from the toolbox.
        """
        if tool_name not in self._tools:
            raise KeyError(
                f"Error: tool {tool_name} not found in toolbox for removal, should be instead one of {list(self._tools.keys())}."
            )
        del self._tools[tool_name]

    def update_tool(self, tool: Tool):
        """
        Updates a tool in the toolbox according to its name.

        Args:
            tool (`Tool`):
                The tool to update to the toolbox.
        """
        if tool.name not in self._tools:
            raise KeyError(
                f"Error: tool {tool.name} not found in toolbox for update, should be instead one of {list(self._tools.keys())}."
            )
        self._tools[tool.name] = tool

    def clear_toolbox(self):
        """Clears the toolbox"""
        self._tools = {}

    def __repr__(self):
        toolbox_description = "Toolbox contents:\n"
        for tool in self._tools.values():
            toolbox_description += f"\t{tool.name}: {tool.description}\n"
        return toolbox_description


class PipelineTool(Tool):
    """
    A [`Tool`] tailored towards Transformer models. On top of the class attributes of the base class [`Tool`], you will
    need to specify:

    - **model_class** (`type`) -- The class to use to load the model in this tool.
    - **default_checkpoint** (`str`) -- The default checkpoint that should be used when the user doesn't specify one.
    - **pre_processor_class** (`type`, *optional*, defaults to [`AutoProcessor`]) -- The class to use to load the
      pre-processor
    - **post_processor_class** (`type`, *optional*, defaults to [`AutoProcessor`]) -- The class to use to load the
      post-processor (when different from the pre-processor).

    Args:
        model (`str` or [`PreTrainedModel`], *optional*):
            The name of the checkpoint to use for the model, or the instantiated model. If unset, will default to the
            value of the class attribute `default_checkpoint`.
        pre_processor (`str` or `Any`, *optional*):
            The name of the checkpoint to use for the pre-processor, or the instantiated pre-processor (can be a
            tokenizer, an image processor, a feature extractor or a processor). Will default to the value of `model` if
            unset.
        post_processor (`str` or `Any`, *optional*):
            The name of the checkpoint to use for the post-processor, or the instantiated pre-processor (can be a
            tokenizer, an image processor, a feature extractor or a processor). Will default to the `pre_processor` if
            unset.
        device (`int`, `str` or `torch.device`, *optional*):
            The device on which to execute the model. Will default to any accelerator available (GPU, MPS etc...), the
            CPU otherwise.
        device_map (`str` or `dict`, *optional*):
            If passed along, will be used to instantiate the model.
        model_kwargs (`dict`, *optional*):
            Any keyword argument to send to the model instantiation.
        token (`str`, *optional*):
            The token to use as HTTP bearer authorization for remote files. If unset, will use the token generated when
            running `huggingface-cli login` (stored in `~/.huggingface`).
        hub_kwargs (additional keyword arguments, *optional*):
            Any additional keyword argument to send to the methods that will load the data from the Hub.
    """

    pre_processor_class = AutoProcessor
    model_class = None
    post_processor_class = AutoProcessor
    default_checkpoint = None
    description = "This is a pipeline tool"
    name = "pipeline"
    inputs = {"prompt": str}
    output_type = str
    is_pipeline_tool = True

    def __init__(
        self,
        model=None,
        pre_processor=None,
        post_processor=None,
        device=None,
        device_map=None,
        model_kwargs=None,
        token=None,
        **hub_kwargs,
    ):
        if not is_torch_available():
            raise ImportError("Please install torch in order to use this tool.")

        if not is_accelerate_available():
            raise ImportError("Please install accelerate in order to use this tool.")

        if model is None:
            if self.default_checkpoint is None:
                raise ValueError(
                    "This tool does not implement a default checkpoint, you need to pass one."
                )
            model = self.default_checkpoint
        if pre_processor is None:
            pre_processor = model

        self.model = model
        self.pre_processor = pre_processor
        self.post_processor = post_processor
        self.device = device
        self.device_map = device_map
        self.model_kwargs = {} if model_kwargs is None else model_kwargs
        if device_map is not None:
            self.model_kwargs["device_map"] = device_map
        self.hub_kwargs = hub_kwargs
        self.hub_kwargs["token"] = token

        super().__init__()

    def setup(self):
        """
        Instantiates the `pre_processor`, `model` and `post_processor` if necessary.
        """
        from accelerate import PartialState

        if isinstance(self.pre_processor, str):
            self.pre_processor = self.pre_processor_class.from_pretrained(
                self.pre_processor, **self.hub_kwargs
            )

        if isinstance(self.model, str):
            self.model = self.model_class.from_pretrained(
                self.model, **self.model_kwargs, **self.hub_kwargs
            )

        if self.post_processor is None:
            self.post_processor = self.pre_processor
        elif isinstance(self.post_processor, str):
            self.post_processor = self.post_processor_class.from_pretrained(
                self.post_processor, **self.hub_kwargs
            )

        if self.device is None:
            if self.device_map is not None:
                self.device = list(self.model.hf_device_map.values())[0]
            else:
                self.device = PartialState().default_device

        if self.device_map is None:
            self.model.to(self.device)

        super().setup()

    def encode(self, raw_inputs):
        """
        Uses the `pre_processor` to prepare the inputs for the `model`.
        """
        return self.pre_processor(raw_inputs)

    def forward(self, inputs):
        """
        Sends the inputs through the `model`.
        """
        with torch.no_grad():
            return self.model(**inputs)

    def decode(self, outputs):
        """
        Uses the `post_processor` to decode the model output.
        """
        return self.post_processor(outputs)

    def __call__(self, *args, **kwargs):
        args, kwargs = handle_agent_input_types(*args, **kwargs)

        if not self.is_initialized:
            self.setup()

        encoded_inputs = self.encode(*args, **kwargs)

        import torch
        from accelerate.utils import send_to_device

        tensor_inputs = {
            k: v for k, v in encoded_inputs.items() if isinstance(v, torch.Tensor)
        }
        non_tensor_inputs = {
            k: v for k, v in encoded_inputs.items() if not isinstance(v, torch.Tensor)
        }

        encoded_inputs = send_to_device(tensor_inputs, self.device)
        outputs = self.forward({**encoded_inputs, **non_tensor_inputs})
        outputs = send_to_device(outputs, "cpu")
        decoded_outputs = self.decode(outputs)

        return handle_agent_output_types(decoded_outputs, self.output_type)


__all__ = [
    "AUTHORIZED_TYPES",
    "Tool",
    "tool",
    "load_tool",
    "launch_gradio_demo",
    "Toolbox",
    "ToolCollection",
]
