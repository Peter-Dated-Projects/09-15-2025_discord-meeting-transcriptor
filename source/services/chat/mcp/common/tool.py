"""
This module defines the base components for creating MCP (Model-Context-Protocol) tools.

It provides a versatile BaseTool class that can be used to define tools,
automatically generating the required JSON schema from Python functions,
their docstrings, and type hints.
"""
import inspect
import functools
from enum import Enum
from typing import Any, Callable, Dict, List, get_type_hints, get_origin, get_args

class BaseTool:
    """
    Base class for an MCP tool. It can be used to wrap a function, turning it into a
    fully-defined tool with an automatically generated schema.

    Attributes:
        name (str): The name of the tool, typically in camelCase.
        description (str): A description of what the tool does.
        input_schema (Dict[str, Any]): A JSON schema describing the tool's input parameters.
        func (Callable): The actual callable function that implements the tool's logic.
        allow_write (bool | None): Flag to indicate if the tool can perform write operations.
        sensitive_data_access (bool | None): Flag to indicate if the tool can access sensitive data.
    """

    def __init__(
        self,
        func: Callable,
        name: str = None,
        description: str = None,
        allow_write: bool = None,
        allow_sensitive_data_access: bool = None,
    ):
        """
        Initializes a BaseTool instance.

        Args:
            func (Callable): The function that will be executed by the tool.
            name (str, optional): The name of the tool. If not provided, it's generated
                from the function name (e.g., 'my_tool_func' -> 'myToolFunc').
            description (str, optional): A description for the tool. If not provided,
                it's extracted from the function's docstring.
            allow_write (bool, optional): If set, determines whether the tool is permitted
                to perform write operations. A value of None means the check doesn't apply.
            allow_sensitive_data_access (bool, optional): If set, determines if the tool can
                access sensitive data. None means the check doesn't apply.
        """
        self.func = func
        self.allow_write = allow_write
        self.sensitive_data_access = allow_sensitive_data_access

        # Generate name from function if not provided
        self.name = name or self._generate_tool_name(func.__name__)

        # Extract description from docstring if not provided
        doc = inspect.getdoc(func) or ''
        self.description = description or doc.split('\n\n')[0]

        # Generate the input schema from the function signature and docstring
        self.input_schema = self._generate_input_schema(func, doc)

    @staticmethod
    def _generate_tool_name(func_name: str) -> str:
        """Converts a snake_case function name to camelCase."""
        parts = func_name.split('_')
        return parts[0] + ''.join(word.capitalize() for word in parts[1:])

    def _generate_input_schema(self, func: Callable, doc: str) -> Dict[str, Any]:
        """
        Generates a JSON schema for the tool's inputs from the function's type
        hints and docstring.

        Args:
            func (Callable): The tool's function.
            doc (str): The docstring of the function.

        Returns:
            Dict[str, Any]: The generated JSON schema.
        """
        hints = get_type_hints(func)
        hints.pop('return', None)

        properties = {}
        required = []

        arg_descriptions = self._parse_arg_descriptions_from_docstring(doc)

        for param_name, param_type in hints.items():
            param_schema = self._get_type_schema(param_type)

            if param_name in arg_descriptions:
                param_schema['description'] = arg_descriptions[param_name]

            properties[param_name] = param_schema
            # Assume all typed parameters are required for simplicity
            required.append(param_name)

        return {'type': 'object', 'properties': properties, 'required': required}
    
    @staticmethod
    def _parse_arg_descriptions_from_docstring(doc: str) -> Dict[str, str]:
        """Parses argument descriptions from the 'Args:' section of a docstring."""
        arg_descriptions = {}
        if not doc:
            return arg_descriptions

        lines = doc.split('\n')
        in_args_section = False
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith('Args:'):
                in_args_section = True
                continue
            
            if in_args_section:
                if not stripped_line or stripped_line.startswith(('Returns:', 'Raises:')):
                    break
                if ':' in stripped_line:
                    arg_name, arg_desc = stripped_line.split(':', 1)
                    arg_descriptions[arg_name.strip()] = arg_desc.strip()
        
        return arg_descriptions

    def _get_type_schema(self, type_hint: Any) -> Dict[str, Any]:
        """Converts a Python type hint into a JSON schema property."""
        if type_hint is int:
            return {'type': 'integer'}
        if type_hint is float:
            return {'type': 'number'}
        if type_hint is bool:
            return {'type': 'boolean'}
        if type_hint is str:
            return {'type': 'string'}

        if isinstance(type_hint, type) and issubclass(type_hint, Enum):
            return {'type': 'string', 'enum': [e.value for e in type_hint]}

        origin = get_origin(type_hint)
        if origin is list or origin is List:
            args = get_args(type_hint)
            item_schema = self._get_type_schema(args[0]) if args else {}
            return {'type': 'array', 'items': item_schema}
        
        if origin is dict or origin is Dict:
            args = get_args(type_hint)
            value_schema = self._get_type_schema(args[1]) if args and len(args) > 1 else True
            return {'type': 'object', 'additionalProperties': value_schema}
        
        return {'type': 'string'} # Default for unknown types

    def to_mcp_schema(self) -> Dict[str, Any]:
        """
        Returns the full tool definition as a dictionary that conforms to the
        MCP specification.
        """
        return {
            'name': self.name,
            'description': self.description,
            'inputSchema': self.input_schema,
        }

    def check_tool_access(self):
        """
        Checks if the tool has permission to execute based on its security flags.
        Raises an Exception if access is denied.
        """
        if self.allow_write is False:
            raise PermissionError(
                'Write operations are not allowed for this tool. '
                'To enable, set --allow-write flag to true.'
            )
        if self.sensitive_data_access is False:
            raise PermissionError(
                'Sensitive data access is not allowed for this tool. '
                'To enable, set --allow-sensitive-data-access flag to true.'
            )

    async def __call__(self, *args, **kwargs):
        """
        Makes the tool instance callable.
        
        This method performs access checks and then executes the underlying function.
        """
        self.check_tool_access()
        
        # If the wrapped function is async, await it. Otherwise, run it normally.
        if inspect.iscoroutinefunction(self.func):
            return await self.func(*args, **kwargs)
        else:
            return self.func(*args, **kwargs)

def tool(
    name: str = None,
    description: str = None,
    allow_write: bool = None,
    allow_sensitive_data_access: bool = None,
) -> Callable:
    """
    A decorator that transforms a Python function into an MCP tool instance.

    This handles the instantiation of BaseTool, making it easy to declare tools.

    Example:
        @tool()
        def my_search_tool(query: str):
            \"\"\"
            Searches for information online.

            Args:
                query (str): The search query.
            \"\"\"
            return f"Results for: {query}"
    """
    def decorator(func: Callable):
        tool_instance = BaseTool(
            func=func,
            name=name,
            description=description,
            allow_write=allow_write,
            allow_sensitive_data_access=allow_sensitive_data_access
        )
        # Attach the tool instance to the function so it can be accessed
        # and registered by a tool manager.
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return tool_instance(*args, **kwargs)
        
        wrapper.mcp_tool = tool_instance
        return wrapper
    return decorator
