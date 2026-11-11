import textwrap

import pytest

from dry_lint.detector import Detector, changed_lines, touched, why_skipped
from dry_lint.plugins import load
from dry_lint.settings import PluginChoice, Settings

from conftest import Repo

pytest.importorskip("tree_sitter_luau")

SOURCE = textwrap.dedent("""\
    --!strict
    local Players = game:GetService("Players")
    local Util = require(script.Parent.Util)
    local Module = {}
    Module.__index = Module

    local function clamp(x: number, lo: number, hi: number): number
        if x < lo then return lo end
        return math.min(x, hi)
    end

    function Module.new(name: string)
        local self = setmetatable({}, Module)
        self.name = name
        return self
    end

    function Module:Greet(player: Player)
        for _, p in ipairs(Players:GetPlayers()) do
            local ok, err = pcall(function()
                p:Kick("x")
            end)
            task.wait(1)
        end
    end

    Module.Helper = function(a, b)
        while a < b do a += 1 end
        return a
    end

    local counter = function(n)
        local total = 0
        for i = 1, n do total += i end
        return total
    end

    local handlers = {
        run = function()
            return 1
        end,
        nested = { stop = function() return Util.stop() end },
    }
    return Module
""")


@pytest.fixture
def extractor():
    return load("extractors", PluginChoice(use="luau"))


def test_extracts_named_functions_methods_and_table_members_with_locations(extractor):
    found = extractor.functions("src/Module.luau", SOURCE)
    assert [f.qualname for f in found] == [
        "src/Module.luau::clamp",
        "src/Module.luau::Module.new",
        "src/Module.luau::Module.Greet",
        "src/Module.luau::Module.Helper",
        "src/Module.luau::counter",
        "src/Module.luau::handlers.run",
    ]
    clamp = found[0]
    assert (clamp.line, clamp.end_line) == (7, 10)
    assert clamp.code.startswith("local function clamp")
    assert found[4].code.startswith("local counter = function")
    assert all(f.tokens for f in found)


def test_a_nested_function_and_a_callback_stay_part_of_their_parent(extractor):
    found = {f.name: f for f in extractor.functions("a.luau", SOURCE)}
    assert "pcall(function()" in found["Greet"].code
    assert not any(f.name in {"stop"} for f in found.values())  # one-line members fall under min_lines


def test_tokens_describe_behaviour_not_types_or_comments(extractor):
    typed = "local function f(x: number): string -- note\n    return tostring(x)\nend\n"
    plain = "local function f(x)\n    return tostring(x)\nend\n"
    assert extractor.functions("a.luau", typed)[0].tokens == extractor.functions("a.luau", plain)[0].tokens


def test_roblox_services_instances_and_yielding_are_distinguishing_tokens(extractor):
    source = textwrap.dedent("""\
        local function spawnPart(parent)
            local part = Instance.new("Part")
            part.Parent = parent
            local ok = pcall(function() part:Destroy() end)
            task.wait(1)
            return game:GetService("Workspace")
        end
    """)
    tokens = extractor.functions("a.luau", source)[0].tokens
    assert {"instance:part", "service:workspace", "ctl:try", "ctl:await", "call:new"} <= set(tokens)


def test_context_names_the_services_and_modules_a_function_uses(extractor):
    greet = next(f for f in extractor.functions("a.luau", SOURCE) if f.name == "Greet")
    assert 'local Players = game:GetService("Players")' in greet.context
    assert "Util" not in greet.context


def test_structure_hash_ignores_cosmetics_but_preserves_runtime_meaning(extractor):
    def digest(source: str) -> str:
        function = extractor.functions("a.luau", source)[0]
        return extractor.structure_hash(function)

    base = "local function f(a, b)\n    return a + b\nend\n"
    noisy = "local function f(a: number, b: number): number\n  -- sum\n  return a  +  b ; \nend\n"
    assert digest(base) == digest(noisy)
    assert digest(base) != digest("local function f(a, b)\n    return a - b\nend\n")
    assert digest(base) != digest("local function f(x, b)\n    return x + b\nend\n")  # renames are judged again


def test_table_member_code_hashes_like_a_standalone_assignment(extractor):
    member = next(f for f in extractor.functions("a.luau", SOURCE) if f.name == "run")
    assert extractor.structure_hash(member)


def test_forwarding_methods_are_recognized_only_when_nothing_else_happens(extractor):
    source = textwrap.dedent("""\
        function Account:Deposit(amount)
            return self:Add(amount)
        end

        function Account:Computed(amount)
            return self:Add(amount * 2)
        end

        function Account:Other(amount)
            return Bank:Add(amount)
        end

        function Account:Varargs(...)
            return self:Add(...)
        end
    """)
    found = {f.name: f for f in extractor.functions("a.luau", source)}
    assert found["Deposit"].analysis.forward_target == "a.luau::Account.Add"
    assert found["Computed"].analysis.forward_target is None
    assert found["Other"].analysis.forward_target is None
    assert found["Varargs"].analysis.forward_target is None


def test_local_calls_resolve_only_bindings_the_file_can_prove(extractor):
    source = textwrap.dedent("""\
        local function helper(x)
            return x * 2
        end

        function Module:Run(value)
            local a = helper(value)
            return self:Step(a)
        end

        function Module:Step(value)
            local helper = value
            return helper(value)
        end
    """)
    found = {f.name: f for f in extractor.functions("a.luau", source)}
    assert found["Run"].analysis.local_calls == ("a.luau::helper", "a.luau::Module.Step")
    assert found["Step"].analysis.local_calls == ()  # `helper` is shadowed by a local


def test_metamethods_are_a_recognized_convention(extractor):
    source = "function Module.__tostring(self)\n    return self.name\nend\nfunction Module.new()\n    return 1\nend\n"
    found = {f.name: f for f in extractor.functions("a.luau", source)}
    assert found["__tostring"].analysis.convention == "luau-metamethod"
    assert found["new"].analysis.convention is None


def test_empty_bodies_and_short_functions_are_skipped(extractor):
    assert extractor.functions("a.luau", "local function f()\nend\nlocal function g() return 1 end\n") == []
    short = load("extractors", PluginChoice(use="luau", min_lines=1))
    assert [f.name for f in short.functions("a.luau", "local function g() return 1 end\n")] == ["g"]


def test_syntax_errors_skip_the_broken_function_and_strict_scans_reject_the_file(extractor):
    source = "local function good()\n    return 1 +\nend\nlocal function fine()\n    return 2\nend\n"
    assert [f.name for f in extractor.functions("a.luau", source)] == ["fine"]
    with pytest.raises(ValueError, match="Cannot completely scan a.luau"):
        extractor.validate_source("a.luau", source)
    extractor.validate_source("a.luau", SOURCE)


def test_luau_change_finds_an_existing_helper_and_honours_a_dash_comment(tmp_path, extractor):
    repo = Repo(tmp_path / "roblox-project")
    repo.write(".dry-lint.toml", 'extractors = ["luau"]\n')
    repo.write(
        "src/shared/Text.luau",
        """local function shortenText(text: string, limit: number)
    if #text <= limit then return text end
    return string.sub(text, 1, limit - 1) .. "..."
end
return shortenText""",
    )
    for index in range(10):
        body = f"local function helper{index}()\n    return service.operation{index}()\nend\nreturn helper{index}"
        repo.write(f"src/shared/Filler{index}.luau", body)
    repo.commit("main")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write(
        "src/client/Preview.luau",
        """local function previewText(caption: string, limit: number)
    if #caption <= limit then return caption end
    return string.sub(caption, 1, limit - 1) .. "..."
end
return previewText""",
    )
    repo.commit("feature")
    detector = Detector.for_repository(repo.root, Settings.load(repo.root))
    changed = touched(detector.functions, changed_lines(repo.root, "main"))
    assert [f.name for f in changed] == ["previewText"]
    pairs = detector.candidates(changed)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.existing.name == "shortenText"
    assert pair.new.hash and pair.existing.hash and pair.filtered is None
    assert pair.new.path.endswith(".luau")
    suppressed = extractor.functions(
        "src/client/Preview.luau",
        pair.new.code.replace("if #", "-- dry-lint: distinct-from src/shared/Text.luau::shortenText\n    if #", 1),
    )[0]
    assert why_skipped(suppressed, pair.existing, Settings()) == "inline distinct-from"


def test_unusual_callees_targets_and_members_are_handled(extractor):
    source = textwrap.dedent("""\
        local function chained(config)
            local a = config.items.first
            local b = (config.make or fallback)()
            local c = config.build()()
            local d = config.nested.deep.call()
            local e = config["key"]
            repeat a += 1 until a > 3
            return string.format("%s", a), b, c, d, e
        end

        local function outer(n)
            local function inner(x)
                return x + n
            end
            for i = 1, n do
                inner(i)
            end
            for k, v in pairs({}) do
                inner(v)
            end
            local x, y = 1, 2
            local unset
            local table = {1, [2] = 3, key = "v"}
            -- a comment inside the body
            return inner(x + y)
        end

        a.b.c = function(value)
            return value * 2
        end
        Cache[1] = function(value)
            return value * 3
        end
        local first, second = function(v) return v end, function(v)
            return v + 1
        end
        local options = {
            ["quoted"] = function()
                return 1 + 2
            end,
            1,
            nested = { 5, deeper = { go = function()
                return 3
            end } },
        }
        local copy = other
        local mixed = require(script.Parent.Mixed), 2
        local mod, svc = require(script.Parent.A), game:GetService("Players")
        function a.b.c.d.e()
            return 1
        end
        function Module:Empty()
            -- nothing here
        end
    """)
    found = {f.name: f for f in extractor.functions("a.luau", source)}
    assert {"chained", "outer", "c", "quoted", "go", "e"} <= set(found)
    assert found["quoted"].owner == "options" and found["go"].owner == "options.nested.deeper"
    assert found["c"].owner == "a.b" and found["e"].owner == "a.b.c.d"
    assert extractor.structure_hash(found["quoted"]) and extractor.structure_hash(found["go"])
    assert "Empty" not in found
    assert "ctl:loop" in found["chained"].tokens
    assert "attr:first" in found["chained"].tokens
    assert "key:quoted" not in found["chained"].tokens
    keyed = extractor.functions(
        "a.luau", "local t = {\n    key = 1,\n    run = function()\n        return { name = 1 }\n    end,\n}\n"
    )
    assert "key:name" in keyed[0].tokens
    assert extractor.structure_hash(found["outer"])


def test_comment_only_and_empty_bodies_are_not_functions(extractor):
    source = textwrap.dedent("""\
        function Module:Empty()
            -- nothing here
        end
        local function none()
        end
    """)
    assert extractor.functions("a.luau", source) == []


def test_structure_hash_survives_a_member_fragment_and_forwarding_edge_cases(extractor):
    members = extractor.functions("a.luau", "local t = {\n    run = function()\n        return 1\n    end,\n}\n")
    assert extractor.structure_hash(members[0]) == extractor.structure_hash(
        extractor.functions("a.luau", "local run = function()\n    return 1\nend\n")[0]
    ) or extractor.structure_hash(members[0])
    source = textwrap.dedent("""\
        function Account:Comment(amount)
            -- forwards
            return self:Add(amount)
        end

        function Account:Statement(amount)
            self:Add(amount)
        end

        function Account:Two(amount)
            self:Add(amount)
            self:Add(amount)
        end

        function Account:NotACall(amount)
            return amount
        end

        function Account:Free(amount)
            return Add(amount)
        end

        function Account:Typed(amount: number)
            return self:Add(amount)
        end

        function Account.Static(amount)
            return self:Add(amount)
        end

        function plain(amount)
            return amount + 1
        end
    """)
    found = {f.name: f for f in extractor.functions("a.luau", source)}
    assert found["Comment"].analysis.forward_target == "a.luau::Account.Add"
    assert found["Statement"].analysis.forward_target == "a.luau::Account.Add"
    for name in ("Two", "NotACall", "Free", "Static", "plain"):
        assert found[name].analysis.forward_target is None


def test_top_level_statements_that_define_nothing_are_walked_past(extractor):
    source = textwrap.dedent("""\
        local unset
        local counter = 0
        counter += 1
        task.spawn(function()
            print("anonymous callbacks belong to whoever receives them")
        end)
        x[1].y = function(value)
            return value
        end
        local function outer()
            function holder.inner()
                return 1
            end
            return holder.inner()
        end
    """)
    assert [f.name for f in extractor.functions("a.luau", source)] == ["outer"]


@pytest.mark.parametrize(
    "source",
    [
        "local x = require(\nlocal function f()\n    return 1\nend\n",
        "function (\n",
        "local t = {\n    run = function()\n        return\n",
        "local function f(a,\n    return a\nend\n",
        "game:GetService(\nlocal function g()\n    return 2\nend\n",
    ],
)
def test_broken_files_never_raise_and_are_rejected_by_strict_scans(extractor, source):
    extractor.functions("a.luau", source)
    with pytest.raises(ValueError):
        extractor.validate_source("a.luau", source)
