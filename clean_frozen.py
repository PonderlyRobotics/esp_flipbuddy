# clean_frozen.py — safe stripping using Python's AST
import ast
import sys
from pathlib import Path


class DocstringStripper(ast.NodeTransformer):
    def visit_Module(self, node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body = node.body[1:]
        return self.generic_visit(node)

    def visit_ClassDef(self, node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body = node.body[1:]
        return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body = node.body[1:]
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        return self.visit_FunctionDef(node)


class PrintRemover(ast.NodeTransformer):
    def visit_Expr(self, node):
        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "print"
        ):
            return None
        return self.generic_visit(node)


def sanitize_empty_bodies(tree):
    """Walk the AST and ensure no compound statement or except handler
    is left with an empty body (which ast.unparse would turn into invalid syntax).
    We deliberately leave orelse/finalbody empty when they become empty:
    ast.unparse will simply omit the now-useless else:/finally: clause.
    """
    for node in ast.walk(tree):
        # main bodies of functions, if, for, while, with, try, classes, etc.
        if hasattr(node, "body") and isinstance(getattr(node, "body", None), list):
            if len(node.body) == 0:
                node.body = [ast.Pass()]
        if isinstance(node, ast.ExceptHandler):
            if len(getattr(node, "body", [])) == 0:
                node.body = [ast.Pass()]
        # Intentionally do NOT populate orelse/finalbody when empty.
        # Empty means "drop this clause" after print/docstring removal.
    return tree


def strip_comments_and_clean(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    tree = DocstringStripper().visit(tree)
    tree = PrintRemover().visit(tree)
    tree = sanitize_empty_bodies(tree)
    ast.fix_missing_locations(tree)
    try:
        import ast as ast_module

        if hasattr(ast_module, "unparse"):
            cleaned = ast.unparse(tree)
        else:
            from astor import to_source

            cleaned = to_source(tree)
    except Exception:
        from astor import to_source

        cleaned = to_source(tree)
    lines = []
    for line in cleaned.splitlines():
        stripped = line.rstrip()
        if stripped.lstrip().startswith("#"):
            continue
        if not stripped:
            continue
        lines.append(line)
    return "\n".join(lines) + "\n"


def clean_file(in_path: Path, out_path: Path):
    source = in_path.read_text(encoding="utf-8")
    cleaned = strip_comments_and_clean(source)
    out_path.write_text(cleaned, encoding="utf-8")


def main():
    if len(sys.argv) != 3:
        sys.exit(1)
    src_dir = Path(sys.argv[1])
    dest_dir = Path(sys.argv[2])
    dest_dir.mkdir(parents=True, exist_ok=True)
    files = [
        "http.py",
        "models.py",
        "mpu6050.py",
        "network_helper.py",
        "rgb.py",
        "util.py",
        "ap_mode.py",
        "credentials.py",
    ]
    for f in files:
        src = src_dir / f
        if not src.exists():
            continue
        dest = dest_dir / f
        clean_file(src, dest)
    orig_size = sum(
        (src_dir / f).stat().st_size for f in files if (src_dir / f).exists()
    )
    clean_size = sum(p.stat().st_size for p in dest_dir.glob("*.py"))
    saved = orig_size - clean_size
    print(f"Original: {orig_size} B  Cleaned: {clean_size} B  Saved: {saved} B")


if __name__ == "__main__":
    main()
