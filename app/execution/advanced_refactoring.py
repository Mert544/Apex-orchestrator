from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any



@dataclass
class AdvancedRefactorResult:
    """Result from an advanced refactoring transform."""

    success: bool
    description: str = ""
    diff: str = ""
    file_path: str = ""
    old_content: str = ""
    new_content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "description": self.description,
            "diff": self.diff,
            "file_path": self.file_path,
        }


class AdvancedRefactoringEngine:
    """Advanced AST-based refactoring transforms beyond basic patches.

    Supports:
    - extract_interface: create an abstract base class from method signatures
    - introduce_parameter_object: bundle related parameters into a dataclass
    """

    @staticmethod
    def extract_interface(
        source_code: str,
        class_name: str,
        interface_name: str = "",
    ) -> AdvancedRefactorResult:
        """Create an abstract interface (ABC) from a concrete class.

        Scans *source_code* for *class_name*, collects all method definitions
        (excluding __init__ and private methods), and generates a matching ABC
        with abstractmethod decorators.
        """
        if not interface_name:
            interface_name = f"I{class_name}"
        try:
            tree = ast.parse(source_code)
        except (SyntaxError, RecursionError, MemoryError) as e:
            return AdvancedRefactorResult(False, f"Parse error: {e}")

        target_class = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                target_class = node
                break
        if not target_class:
            return AdvancedRefactorResult(False, f"Class {class_name} not found")

        imports = ["from abc import ABC, abstractmethod"]
        methods: list[str] = []
        for item in target_class.body:
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                sig = AdvancedRefactoringEngine._method_signature(item)
                methods.append(f"    @abstractmethod\n    {sig}: ...")

        if not methods:
            return AdvancedRefactorResult(False, f"No public methods in {class_name}")

        interface_code = (
            "\n".join(imports)
            + f"\n\nclass {interface_name}(ABC):\n"
            + "\n\n".join(methods)
        )
        return AdvancedRefactorResult(
            success=True,
            description=f"Extracted interface {interface_name} from {class_name}",
            new_content=interface_code,
            old_content="",
            diff=interface_code,
        )

    @staticmethod
    def introduce_parameter_object(
        source_code: str,
        function_name: str,
        param_indices: list[int] | None = None,
        object_name: str = "",
    ) -> AdvancedRefactorResult:
        """Bundle related function parameters into a dataclass.

        Given *function_name* and optionally *param_indices*, generates a
        ParameterObject dataclass and refactors the function signature.
        """
        try:
            tree = ast.parse(source_code)
        except (SyntaxError, RecursionError, MemoryError) as e:
            return AdvancedRefactorResult(False, f"Parse error: {e}")

        target_func = AdvancedRefactoringEngine._find_function(tree, function_name)
        if not target_func:
            return AdvancedRefactorResult(False, f"Function {function_name} not found")

        params, param_indices, selected, start = (
            AdvancedRefactoringEngine._resolve_params(target_func, param_indices)
        )
        if len(selected) < 2:
            return AdvancedRefactorResult(
                False, f"Need at least 2 parameters to bundle, got {len(selected)}"
            )

        if not object_name:
            object_name = f"{function_name.title().replace('_', '')}Params"

        dataclass_code = AdvancedRefactoringEngine._build_param_dataclass(
            object_name, selected
        )
        new_sig = AdvancedRefactoringEngine._build_param_object_signature(
            function_name, object_name, params, param_indices, start
        )
        return AdvancedRefactorResult(
            success=True,
            description=f"Introduced {object_name} for {function_name}",
            new_content=dataclass_code + "\n\n" + new_sig + ":\n    ...",
            old_content=ast.unparse(target_func),
            diff=f"Introduced {object_name} dataclass",
        )

    @staticmethod
    def _find_function(tree: ast.AST, function_name: str) -> ast.FunctionDef | None:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                return node
        return None

    @staticmethod
    def _resolve_params(
        target_func: ast.FunctionDef,
        param_indices: list[int] | None,
    ) -> tuple[list[ast.arg], list[int], list[ast.arg], int]:
        args = target_func.args.args
        # Skip 'self' / 'cls'
        start = 1 if args and args[0].arg in ("self", "cls") else 0
        params = args[start:]
        if not param_indices:
            param_indices = list(range(len(params)))
        selected = [params[i] for i in param_indices if 0 <= i < len(params)]
        return params, param_indices, selected, start

    @staticmethod
    def _annotated_arg(arg: ast.arg) -> str:
        annotation = ""
        if arg.annotation:
            annotation = f": {ast.unparse(arg.annotation)}"
        return f"{arg.arg}{annotation}"

    @staticmethod
    def _build_param_dataclass(object_name: str, selected: list[ast.arg]) -> str:
        fields = [
            f"    {AdvancedRefactoringEngine._annotated_arg(arg)}" for arg in selected
        ]
        return f"@dataclass\nclass {object_name}:\n" + "\n".join(fields)

    @staticmethod
    def _build_param_object_signature(
        function_name: str,
        object_name: str,
        params: list[ast.arg],
        param_indices: list[int],
        start: int,
    ) -> str:
        kept = [p for i, p in enumerate(params) if i not in param_indices]
        new_sig_params = ["self"] if start == 1 else []
        new_sig_params.append(f"params: {object_name}")
        for k in kept:
            new_sig_params.append(AdvancedRefactoringEngine._annotated_arg(k))
        return f"def {function_name}(" + ", ".join(new_sig_params) + ") -> ..."

    @staticmethod
    def _method_signature(func: ast.FunctionDef) -> str:
        args = func.args
        parts: list[str] = []
        # positional / positional-only
        all_args = args.posonlyargs + args.args
        defaults_start = len(all_args) - len(args.defaults)
        for idx, arg in enumerate(all_args):
            annotation = ""
            if arg.annotation:
                annotation = f": {ast.unparse(arg.annotation)}"
            default = ""
            if idx >= defaults_start:
                default = f" = {ast.unparse(args.defaults[idx - defaults_start])}"
            parts.append(f"{arg.arg}{annotation}{default}")
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        ret = ""
        if func.returns:
            ret = f" -> {ast.unparse(func.returns)}"
        return f"def {func.name}({', '.join(parts)}){ret}"

    @staticmethod
    def available_transforms() -> list[str]:
        return ["extract_interface", "introduce_parameter_object"]
