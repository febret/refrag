"""Native synthesis bindings plus bytebeat expression compilation."""

from __future__ import annotations

import ast

import numpy as np

import refrag_engine as _native


_ALLOWED_BINOPS = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: None,
    ast.Mod: None,
    ast.LShift: np.left_shift,
    ast.RShift: np.right_shift,
    ast.BitAnd: np.bitwise_and,
    ast.BitOr: np.bitwise_or,
    ast.BitXor: np.bitwise_xor,
}


def compile_expr(text):
    """Compile a bytebeat expression into f(t_uint32_array) safely."""
    text = (text or "0").strip() or "0"
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None

    def ev(node, t):
        if isinstance(node, ast.Expression):
            return ev(node.body, t)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return np.int64(int(node.value))
        if isinstance(node, ast.Name) and node.id in ("t", "T"):
            return t
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.Invert)):
            val = ev(node.operand, t)
            return -val if isinstance(node.op, ast.USub) else ~val
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            a = ev(node.left, t)
            b = ev(node.right, t)
            op = type(node.op)
            if op is ast.Div:
                return np.where(b == 0, 0, a // np.where(b == 0, 1, b))
            if op is ast.Mod:
                return np.where(b == 0, 0, np.mod(a, np.where(b == 0, 1, b)))
            return _ALLOWED_BINOPS[op](a, b)
        return None

    if ev(tree, np.arange(1, dtype=np.int64)) is None:
        return None

    def fn(t):
        arr = np.asarray(t, dtype=np.int64)
        out = ev(tree, arr)
        if out is None:
            return np.zeros_like(arr)
        return np.asarray(out, dtype=np.int64)

    return fn


def create_machine(m):
    return _native.create_machine(m)


def render_block(output_buffer, param_matrix):
    return _native.render_block(output_buffer, param_matrix)


def initialize(thread_count=None):
    return _native.initialize(thread_count) if hasattr(_native, "initialize") else None
