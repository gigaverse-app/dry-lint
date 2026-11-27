"""Lean 4 declarations for static comparison, without elaborating imports or running tactics."""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from dry_lint.extractor_capabilities import ExtractorCapabilities
from dry_lint.functions import exact_source_hash, text_digest
from dry_lint.models import Function

_IMPLEMENTATIONS = {"def", "abbrev", "opaque", "theorem", "lemma", "instance"}
# Lean's own identifier characters. Other letters, such as λ or a postfix ᴴ, are notation.
_ID_FIRST = "A-Za-z_À-ÖØ-öø-ſα-κμ-ωΑ-ΟΡΤ-Ωϊ-ϻἀ-῾℀-⅏𝒜-𝖟"
_ID_ALNUM = _ID_FIRST + "0-9₀-₉ₐ-ₜᵢ-ᵪⱼ"
_NAME_PART = f"(?:«[^»\n]*»|[{_ID_FIRST}][{_ID_ALNUM}'!?]*)"
_NAME = f"{_NAME_PART}(?:\\.{_NAME_PART})*"
_OPENERS, _CLOSERS = "([{⟨⦃⟦⟪", ")]}⟩⦄⟧⟫"
BRACKETS = (_OPENERS, _CLOSERS)

# Text that can hide a keyword or a bracket. A prime after an identifier is not a character literal.
_OPAQUE = re.compile(
    r"--[^\n]*|/-|«[^»\n]*»|\"(?:[^\"\\]|\\.)*\"|(?<![\w'])r(#*)\"(?s:.*?)\"\1"
    r"|(?<![\w'])'(?:\\(?:x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|.)|[^\\'\n])'",
    re.DOTALL,
)
_COMMENT_EDGE = re.compile(r"/-|-/")
_VISIBLE = re.compile(r"[^\n]")
# Markers left in the structural copy of a source: a doc comment, then a literal's first and later characters.
_DOC, _LITERAL, _LITERAL_REST = "\x01", "\x02", "\x03"

_MODIFIERS = {"private", "protected", "public", "noncomputable", "unsafe", "partial", "nonrec", "meta"}
_MODIFIERS |= {"local", "scoped"}
# A command that ends with `in` applies to the command after it.
_WRAPPERS = {"open", "omit", "include", "set_option", "variable", "universe", "attribute"}
_COMMANDS = (
    _IMPLEMENTATIONS
    | _WRAPPERS
    | {"example", "structure", "class", "inductive", "axiom", "alias", "namespace", "section", "end", "mutual"}
    | {"export", "notation", "infix", "infixl", "infixr", "prefix", "postfix", "syntax", "macro", "macro_rules"}
    | {"elab", "elab_rules", "declare_syntax_cat", "initialize", "irreducible_def", "add_decl_doc"}
    | {"library_note", "assert_not_exists", "suppress_compilation", "unseal", "seal", "run_cmd", "proof_wanted"}
)
_WORD = re.compile(rf"[{_ID_FIRST}][{_ID_ALNUM}]*(?![{_ID_ALNUM}'!?.])")
# One cheap pattern for every line. The word is then looked up, because a long alternation is slow here.
_LINE_START = re.compile(rf"^([ \t]*)({_DOC}|@\[|#(?=[a-z_])|[a-z][0-9a-z_]*(?![{_ID_ALNUM}'!?.]))", re.MULTILINE)
_DERIVING_INSTANCE = re.compile(r"\s+instance\b")
_MODIFIED = re.compile(rf"\s*(@\[|[a-z_]*)(?![{_ID_ALNUM}'!?.])")
_SCOPED_IN = re.compile(r"[ \t]*\[")
_PRIORITY = re.compile(r"\s*(?=\()")
_DECLARED = re.compile(rf"\s*({_NAME})")
_NAME_PARTS = re.compile(_NAME_PART)
# Lean permits these at the start of a line inside a term, a tactic block or a structure body.
# There `#` is notation, such as the cardinality `#s`.
_NESTABLE = {_DOC, "@[", "#", "open", "set_option", ""}
_CLAUSES = {"termination_by", "decreasing_by"}
_STARTS = _MODIFIERS | _COMMANDS | {_DOC, "@[", "#"}
_BODIES = _IMPLEMENTATIONS | {"example", "structure", "class", "inductive", "axiom", "irreducible_def"}
_BODIES |= {"macro", "macro_rules", "elab", "elab_rules", "syntax", "notation", "initialize", "proof_wanted", ""}
_BRACKET = re.compile(f"[{re.escape(_OPENERS + _CLOSERS)}]")
_BLANK = re.compile(rf"[\s{_DOC}]*")
_TOKEN = re.compile(
    rf"{_LITERAL}[{_LITERAL_REST}\n]*|{_NAME}|\d[{_ID_ALNUM}]*(?:\.\d+)?|[{re.escape(_OPENERS + _CLOSERS)},;]|:="
    rf"|[^\s{_ID_ALNUM}{re.escape(_OPENERS + _CLOSERS)},;«»\x01-\x03]+"
)


@dataclass(frozen=True)
class Command:
    """One top-level command. Offsets index the source and its structural copy alike."""

    kind: str
    start: int  # Its first attribute, modifier or wrapping command; a leading doc comment comes before.
    keyword_end: int
    end: int  # After its last code character; later comments belong to no command.


@dataclass(frozen=True)
class LeanSource:
    """A source with comments blanked and literals masked, so that keywords and brackets are code."""

    text: str
    structure: str
    literals: tuple[tuple[int, int], ...]
    commands: tuple[Command, ...]
    newlines: tuple[int, ...]

    def line(self, offset: int) -> int:
        return bisect_right(self.newlines, offset - 1) + 1

    def tokens(self, start: int, end: int) -> list[str]:
        """Code tokens in source order. A literal becomes a digest of its exact spelling."""
        tokens = _TOKEN.findall(self.structure, start, end)
        literal = bisect_left(self.literals, (start, 0))
        for index, token in enumerate(tokens):
            if token[0] == _LITERAL:
                # Quote delimiters and escapes are not shared behavior. Keep identical
                # literals comparable without putting their potentially long text in the index.
                tokens[index] = f"str:{text_digest(self.text[slice(*self.literals[literal])])}"
                literal += 1
        return tokens


def _structure(source: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Blank comments and mask literals without moving any other character."""
    parts, literals = [], []
    done = position = 0
    while match := _OPAQUE.search(source, position):
        start, position = match.span()
        opening = source[start]
        if opening == "«":
            continue
        if match.group() == "/-":
            depth = 1
            while depth and (edge := _COMMENT_EDGE.search(source, position)):
                depth += 1 if edge.group() == "/-" else -1
                position = edge.end()
            if depth:
                position = len(source)
            # A doc comment stays visible as a mark: it introduces the command after it.
            doc = source.startswith("/--", start)
            masked = (_DOC if doc else " ") + _VISIBLE.sub(" ", source[start + 1 : position])
        elif opening == "-":
            masked = " " * (position - start)
        else:
            literals.append((start, position))
            masked = _LITERAL + _VISIBLE.sub(_LITERAL_REST, source[start + 1 : position])
        parts += [source[done:start], masked]
        done = position
    parts.append(source[done:])
    return "".join(parts), tuple(literals)


def _open_comment(source: str) -> int | None:
    """Where a block comment that is never closed starts."""
    position = 0
    while match := _OPAQUE.search(source, position):
        start, position = match.span()
        if match.group() == "/-":
            depth = 1
            while depth and (edge := _COMMENT_EDGE.search(source, position)):
                depth += 1 if edge.group() == "/-" else -1
                position = edge.end()
            if depth:
                return start
    return None


def _balanced(shape: str) -> bool:
    return all(shape.count(opener) == shape.count(closer) for opener, closer in zip(_OPENERS, _CLOSERS, strict=True))


def _closing(structure: str, position: int) -> int:
    """The offset after the bracket group that opens at or after this position."""
    depth = 0
    for bracket in _BRACKET.finditer(structure, position):
        depth += 1 if bracket.group() in _OPENERS else -1
        if depth <= 0:
            return bracket.end()
    return len(structure)


def _keyword(structure: str, position: int, starts: list[int]) -> tuple[str, int, int]:
    """Skip doc comments, attributes, modifiers and wrapping commands. Return the command's keyword and extent."""
    start = None
    while True:
        position = _BLANK.match(structure, position).end()
        if start is None:
            start = position
        if structure.startswith("@[", position):
            position = _closing(structure, position + 1)
            continue
        word = _WORD.match(structure, position)
        kind, after = (word.group(), word.end()) if word else ("", position)
        if kind in _MODIFIERS:
            # `scoped[Namespace]` names where a notation applies.
            position = _closing(structure, after) if _SCOPED_IN.match(structure, after) else after
        elif kind in _WRAPPERS and (wrapped := _wrapped(structure, after, starts)):
            position = wrapped
        else:
            return kind, start, after


def _wrapped(structure: str, position: int, starts: list[int]) -> int | None:
    """The offset after the `in` that ends a wrapping command, when it has one before the next command."""
    following = bisect_right(starts, position)
    end = starts[following] if following < len(starts) else len(structure)
    depth = 0
    for match in _TOKEN.finditer(structure, position, end):
        token = match.group()
        if token in _OPENERS:
            depth += 1
        elif token in _CLOSERS:
            depth -= 1
        elif token == "in" and not depth:
            return match.end()
    return None


def _after_blank_line(structure: str, line_start: int) -> bool:
    """Whether the line before this one has no code. A comment there is blank in the structural copy."""
    previous = structure.rfind("\n", 0, max(line_start - 1, 0)) + 1
    return line_start > 0 and not structure[previous : line_start - 1].strip()


def _command_starts(structure: str) -> list[tuple[int, int, str]]:
    """Each line that can start a command, with its column and its first word. An unknown command has no word."""
    starts = []
    for match in _LINE_START.finditer(structure):
        word = match.group(2)
        if word == "unsafe" and _MODIFIED.match(structure, match.end()).group(1) not in _STARTS:
            continue  # It introduces an unsafe term here, not an unsafe declaration.
        if word in _STARTS or (word == "deriving" and _DERIVING_INSTANCE.match(structure, match.end())):
            starts.append((match.start(), len(match.group(1)), word))
        elif "_" in word and word not in _CLAUSES and _after_blank_line(structure, match.start()):
            # There a snake_case word is a command this module does not know, not a tactic.
            starts.append((match.start(), len(match.group(1)), ""))
    return starts


def _commands(structure: str) -> tuple[Command, ...]:
    starts = _command_starts(structure)
    offsets = [start for start, _, _ in starts]
    commands = []
    index = 0
    while index < len(starts):
        position, column, _ = starts[index]
        kind, start, keyword_end = _keyword(structure, position, offsets)
        index += 1
        while index < len(starts) and (
            starts[index][0] < keyword_end
            # Deeper than the command that owns the body, these are part of that body.
            or (starts[index][2] in _NESTABLE and starts[index][1] > column and kind in _BODIES)
        ):
            index += 1
        end = starts[index][0] if index < len(starts) else len(structure)
        commands.append(Command(kind, start, keyword_end, start + len(structure[start:end].rstrip(" \t\n" + _DOC))))
    return tuple(commands)


def read_source(source: str) -> LeanSource:
    structure, literals = _structure(source)
    newlines = tuple(match.start() for match in re.finditer("\n", source))
    return LeanSource(source, structure, literals, _commands(structure), newlines)


def _starts_line(structure: str, position: int) -> bool:
    return not structure[structure.rfind("\n", 0, position) + 1 : position].strip()


def _signature(structure: str, start: int, end: int) -> tuple[int | None, int, int] | None:
    """Locate the result type and the body: after `:=`, from `where`, or from the first pattern alternative."""
    depth = 0
    result = alternative = bar = None
    for match in _TOKEN.finditer(structure, start, end):
        token = match.group()
        if token in _OPENERS:
            depth += 1
        elif token in _CLOSERS:
            depth = max(0, depth - 1)
        elif depth:
            continue
        elif token == ":" and result is None and bar is None:
            result = match.end()
        elif token in {":=", "where"}:
            # A bar seen before this was notation in the statement, such as an absolute value.
            return result, match.start(), match.end() if token == ":=" else match.start()
        elif token == "|":
            bar = match.start()
            if alternative is None and _starts_line(structure, bar):
                alternative = bar
        elif token == "=>" and bar is not None:
            # Alternatives usually start their lines. On one line, the last bar starts the alternative.
            body = bar if alternative is None else alternative
            return result, body, body
    return None


def _plain(name: str) -> str:
    """Spell `«A».b` as `A.b`. The guillemets only matter for names Lean could not otherwise read."""
    return re.sub(rf"«({_NAME_PART})»", r"\1", name)


class LeanExtractor:
    name = "lean"
    version = "4"
    # Layout and spelling can affect Lean macros, so hash the source exactly.
    structure_hash = staticmethod(exact_source_hash)
    files = ("*.lean",)
    capabilities = ExtractorCapabilities(
        language_name="Lean", comment_prefix="--", index_distributions=("tree-sitter", "tree-sitter-language-pack")
    )

    def __init__(self, min_lines: int = 2) -> None:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError as error:
            raise ImportError("The lean extractor requires pip install 'dry-lint[lean]'") from error
        self.parser = get_parser("lean")
        self.min_lines = min_lines

    def validate_source(self, path: str, source: str) -> None:
        """
        Reject a source whose commands this extractor cannot bound: a comment or a string that is never
        closed, or a command whose brackets do not balance. Those are what `functions` relies on, so
        notation that only Lean's own parser understands does not make a file incomplete.
        """
        if (comment := _open_comment(source)) is not None:
            line = source.count("\n", 0, comment) + 1
            raise ValueError(f"Cannot completely scan {path}: the comment that starts on line {line} is never closed")
        lean = read_source(source)
        if (quote := lean.structure.find('"')) >= 0:
            raise ValueError(f"Cannot completely scan {path}: the string on line {lean.line(quote)} is never closed")
        for command in lean.commands:
            if not _balanced(lean.structure[command.start : command.end]):
                line = lean.line(command.start)
                raise ValueError(
                    f"Cannot completely scan {path}: brackets do not balance in the command on line {line}"
                )

    def functions(self, path: str, source: str) -> list[Function]:
        found = []
        scopes: list[str] = []
        context_digest = text_digest(source)
        lean = read_source(source)
        for command in lean.commands:
            if command.kind in {"namespace", "section", "mutual", "end"}:
                # `end B` closes only the last component of `namespace A.B`.
                named = lean.structure[command.keyword_end : command.end].split("\n")[0]
                names = [_plain(name) for name in _NAME_PARTS.findall(named)] or [""]
                if command.kind == "end":
                    del scopes[-len(names) :]
                else:
                    scopes += names if command.kind == "namespace" else [""] * len(names)
            elif command.kind in _IMPLEMENTATIONS and (function := self._function(path, lean, command, scopes)):
                function.context_digest = context_digest
                found.append(function)
        return found

    def _function(self, path: str, lean: LeanSource, command: Command, scopes: list[str]) -> Function | None:
        after = command.keyword_end
        if command.kind == "instance":
            # As in `instance (priority := low) name : Class`.
            priority = _PRIORITY.match(lean.structure, after)
            after = _closing(lean.structure, priority.end()) if priority else after
        name = _DECLARED.match(lean.structure, after)
        parts = _signature(lean.structure, name.end(), command.end) if name else None
        code = lean.text[command.start : command.end]
        line = lean.line(command.start)
        length = code.count("\n") + 1
        if parts is None or length < self.min_lines:
            return None
        if not _balanced(lean.structure[command.start : command.end]):
            # An open bracket means the text is cut short, or a syntax quotation holds a command keyword.
            return None
        result, result_end, body = parts
        ident = _plain(name.group(1))
        owner = None if ident.startswith("_root_.") else ".".join(filter(None, scopes)) or None
        # Different propositions can share a one-tactic proof such as rfl.
        result_type = lean.tokens(result, result_end) if result is not None else []
        return Function(
            path=path,
            name=ident.removeprefix("_root_."),
            owner=owner,
            line=line,
            end_line=line + length - 1,
            code=code,
            tokens=[*lean.tokens(body, command.end), *(f"type:{token}" for token in result_type)],
        )
