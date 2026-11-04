import pytest

from dry_lint.comparison_helpers import python_helpers
from dry_lint.extractors import PythonExtractor


def helpers(source):
    function = next(f for f in PythonExtractor().functions("source.py", source) if f.name == "wrapper")
    return python_helpers(source, function)


def test_only_direct_same_file_definitions_are_included_once_in_source_order():
    source = '''def inner(value):
    return value
def shared(value):
    return inner(value)
class Model:
    def wrapper(self, value):
        return shared(value) + shared(value)
'''
    found = helpers(source)
    assert [(f.name, f.line, f.end_line) for f in found] == [("shared", 3, 4)]


@pytest.mark.parametrize("body", [
    'return "shared(value)"',
    'return object.shared(value)',
    'shared = value\n    return shared(value)',
    'from elsewhere import shared\n    return shared(value)',
    'global shared\n    from elsewhere import shared\n    return shared(value)',
    'def nested():\n        return shared(value)\n    return nested()',
    'return (lambda: shared(value))()',
    'return [shared(value) for shared in value]',
])
def test_strings_attributes_local_bindings_and_nested_scopes_do_not_resolve(body):
    assert helpers('def shared(value):\n    return value\ndef wrapper(value):\n    ' + body + '\n') == []


@pytest.mark.parametrize("replacement", [
    'shared = replacement', 'from elsewhere import shared', 'from elsewhere import *',
    'def shared(value):\n    return value + 1', 'del shared',
    'try:\n    risky()\nexcept Exception as shared:\n    pass',
    'match value:\n    case shared:\n        pass',
    'match value:\n    case {"a": first, **shared}:\n        pass',
])
def test_rebound_or_ambiguous_module_names_do_not_resolve(replacement):
    source = ('def shared(value):\n    return value\n' + replacement +
              '\ndef wrapper(value):\n    return shared(value)\n')
    assert helpers(source) == []


def test_parameter_shadowing_recursion_and_one_line_helpers():
    assert helpers('def shared(value):\n    return value\ndef wrapper(value, shared):\n    return shared(value)\n') == []
    assert helpers('def wrapper(value):\n    return wrapper(value)\n') == []
    found = helpers('def shared(value): return value\ndef wrapper(value):\n    return shared(value)\n')
    assert len(found) == 1 and found[0].line == found[0].end_line == 1


def test_semantically_invalid_python_keeps_the_wrapper_without_guessing_helpers():
    assert helpers('def wrapper(value):\n    nonlocal missing\n    return missing(value)\n') == []


def test_helper_count_and_size_are_bounded_without_following_nested_calls():
    source = ''.join(f'def helper{i}(value): return value\n' for i in range(7))
    source += 'def huge(value):\n' + '    value += 1\n' * 600 + '    return value\n'
    source += 'def wrapper(value):\n    return huge(value) + ' + ' + '.join(f'helper{i}(value)' for i in range(7)) + '\n'
    assert [f.name for f in helpers(source)] == [f'helper{i}' for i in range(5)]
