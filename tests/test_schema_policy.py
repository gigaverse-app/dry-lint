import pytest

from dry_lint.cli import main
from dry_lint.detector import Detector
from dry_lint.model_review import profile
from dry_lint.settings import Settings

from conftest import Repo

CONFIG = """
[models.schema_policy]
root_suffix = "PromptSchema"
methods = ["with_structured_output"]
functions = [{name = "llm.safe_output", position = 1, keyword = "response_model"}]
chain_bases = ["llm.Chain"]
"""

PROMPT = """from pydantic import BaseModel
from typing import Optional
class Detail(BaseModel):
    title: str
    score: int
class AnswerPromptSchema(BaseModel):
    details: list["Detail"]
class Application(BaseModel):
    title: str
    score: int
class OtherPromptSchema(BaseModel):
    title: str
    score: int
def prompt(llm):
    return llm.with_structured_output(AnswerPromptSchema)
"""


def test_family_policy_follows_local_nested_types_without_claiming_imported_models(tmp_path):
    repo = Repo(tmp_path / "repo")
    repo.write("prompt.py", PROMPT)
    repo.write(
        ".dry-lint.toml",
        CONFIG
        + """
[[models.policies]]
name = "prompt-application-boundary"
reason = "Prompt schema families evolve with the prompt."
action = "discard"
left = {reachable_from = ["*PromptSchema"]}
right = {not_reachable_from = ["*PromptSchema"]}
""",
    )
    repo.commit()
    detector = Detector.for_tree(repo.root, "HEAD", profile(Settings.load(repo.root)))
    pair = next(
        c for c in detector.candidates(detector.functions) if {c.new.name, c.existing.name} == {"Detail", "Application"}
    )
    assert pair.filtered and "prompt-application-boundary" in pair.filtered
    within = next(
        c
        for c in detector.candidates(detector.functions)
        if {c.new.name, c.existing.name} == {"Detail", "OtherPromptSchema"}
    )
    assert not within.filtered
    assert main(["schema-check", "--root", str(repo.root), "--all"]) == 0


@pytest.mark.parametrize(
    "source,expected",
    [
        (PROMPT.replace("AnswerPromptSchema", "Answer"), "root-name"),
        (
            PROMPT + "\nfrom app import Shared\nclass OtherPromptSchema(BaseModel):\n    value: Shared\n",
            "external-type",
        ),
        (PROMPT + "\nclass Other(BaseModel):\n    details: Detail\n", "application-use"),
    ],
)
def test_schema_contract_reports_naming_and_ownership(tmp_path, capsys, source, expected):
    repo = Repo(tmp_path / "repo")
    repo.write(".dry-lint.toml", CONFIG)
    repo.write("prompt.py", source)
    repo.write("app.py", "from pydantic import BaseModel\nclass Shared(BaseModel):\n    value: int\n")
    repo.commit()
    assert main(["schema-check", "--root", str(repo.root), "--all"]) == 1
    assert expected in capsys.readouterr().out


def test_staged_import_escape_cannot_be_hidden_by_worktree_edits(tmp_path, capsys):
    repo = Repo(tmp_path / "repo")
    repo.write(".dry-lint.toml", CONFIG)
    repo.write("prompt.py", PROMPT)
    repo.commit()
    repo.write("app.py", "from prompt import Detail as StoredDetail\n")
    repo.git("add", "app.py")
    repo.write("app.py", "# unstaged repair\n")
    assert main(["schema-check", "--root", str(repo.root), "--staged"]) == 1
    assert "file-privacy" in capsys.readouterr().out


def test_wrappers_are_explicit_and_dynamic_schemas_require_review(tmp_path, capsys):
    repo = Repo(tmp_path / "repo")
    repo.write(".dry-lint.toml", CONFIG)
    repo.write(
        "prompt.py",
        """from llm import Chain, safe_output as structured
from pydantic import BaseModel
class Answer(BaseModel):
    text: str
class Query(Chain[Answer]):
    response_model = Answer
    def __init__(self):
        super().__init__(response_model=Answer)
def run(llm):
    structured(llm, Answer)
    llm.with_structured_output(factory())
def unrelated(client):
    client.get(response_model=Answer)
""",
    )
    repo.commit()
    assert main(["schema-check", "--root", str(repo.root), "--all"]) == 1
    output = capsys.readouterr().out
    assert output.count("root-name") == 3
    assert "unresolved-root" in output
    assert "prompt.py:13" not in output


def test_nested_cycles_forward_refs_and_annotation_metadata_preserve_family():
    from dry_lint.python_schemas import SchemaModule

    module = SchemaModule(
        "prompt.py",
        """from pydantic import BaseModel
from typing import Literal, Annotated
class RootPromptSchema(BaseModel):
    class Inner(BaseModel):
        parent: "RootPromptSchema | None"
    value: Annotated[Inner, "application metadata"]
    label: Literal["Unrelated"]
    broken: "not valid syntax!"
class Unrelated(BaseModel):
    value: int
""",
    )
    assert module.family("RootPromptSchema") == {"RootPromptSchema", "RootPromptSchema.Inner"}
    assert "RootPromptSchema" not in module.ancestors()["Unrelated"]


def test_aliases_and_diamond_references_include_the_complete_local_family():
    from dry_lint.python_schemas import SchemaModule

    module = SchemaModule(
        "prompt.py",
        """from pydantic import BaseModel
Alias = list[Leaf]
CycleA = CycleB
CycleB = CycleA
class Leaf(BaseModel):
    value: int
class Branch(BaseModel):
    leaves: Alias
class RootPromptSchema(BaseModel):
    leaf: Leaf
    branch: Branch
    recursive_alias: CycleA
""",
    )
    assert module.family("RootPromptSchema") == {"RootPromptSchema", "Branch", "Leaf"}


def test_module_imports_and_external_roots_violate_privacy_without_claiming_application_types(tmp_path, capsys):
    repo = Repo(tmp_path / "repo")
    repo.write(".dry-lint.toml", CONFIG)
    repo.write("prompt.py", PROMPT)
    repo.write(
        "app.py",
        """import prompt as p
from llm import safe_output
def call(llm):
    safe_output(llm, response_model=p.AnswerPromptSchema)
    return p.Detail(title="x", score=1)
""",
    )
    repo.commit()
    assert main(["schema-check", "--root", str(repo.root), "--all"]) == 1
    output = capsys.readouterr().out
    assert "file-privacy" in output and "p.Detail" not in output
    assert "prompt.Detail" in output


def test_schema_check_is_opt_in_and_changed_checks_keep_historical_debt_visible(tmp_path, capsys):
    repo = Repo(tmp_path / "repo")
    repo.write("old.py", PROMPT.replace("AnswerPromptSchema", "Answer"))
    repo.commit()
    assert main(["schema-check", "--root", str(repo.root), "--all"]) == 2
    assert "explicit models.schema_policy" in capsys.readouterr().err
    repo.git("checkout", "-qb", "feature")
    repo.write(".dry-lint.toml", CONFIG)
    repo.write(
        "new.py",
        PROMPT
        + """
def plain(llm):
    llm.with_structured_output(str)
    llm.with_structured_output(None)
""",
    )
    repo.commit()
    args = ["schema-check", "--root", str(repo.root), "--base", "main"]
    assert main(args) == 0
    assert main([*args, "--all"]) == 1
    repo.write("old.py", (repo.root / "old.py").read_text() + "# touch legacy owner\n")
    repo.commit()
    assert main(args) == 1
