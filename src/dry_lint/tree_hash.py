"""Hash a parser tree using the language adapter's canonicalization rules."""

import hashlib
import json
from collections.abc import Callable

from tree_sitter import Node, Parser


def structure_hash(
    code: str,
    parser: Parser,
    *,
    canonicalize: Callable[[Node], object],
    has_syntax_error: Callable[[Node], bool],
    wrapper: tuple[str, str],
    namespace: str,
) -> str:
    root = parser.parse(code.encode("utf-8")).root_node
    if has_syntax_error(root):
        root = parser.parse((wrapper[0] + code + wrapper[1]).encode("utf-8")).root_node
    payload = json.dumps(canonicalize(root), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256((namespace + ":" + payload).encode("utf-8")).hexdigest()[:16]
