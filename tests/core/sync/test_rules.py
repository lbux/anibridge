"""Unit tests for declarative sync rule helpers."""

import pytest
from anibridge.list import ListStatus

from anibridge.app.core.sync.rules import (
    SyncRuleDecision,
    SyncRuleEngine,
    _ContextNamespace,
    _ctx_field_refs_for_expression,
    _validate_expression_ast,
)


def test_context_namespace_normalizes_values_and_missing_access() -> None:
    """Context namespaces should normalize nested values and handle missing attrs."""
    namespace = _ContextNamespace(
        {
            "status": ListStatus.CURRENT,
            "nested": {"status": ListStatus.PLANNING},
            "items": [ListStatus.COMPLETED, {"status": ListStatus.DROPPED}],
        },
        missing_value=None,
    )

    assert namespace["status"] == ListStatus.CURRENT
    assert namespace.nested.status == ListStatus.PLANNING
    assert namespace["items"][0] == ListStatus.COMPLETED
    assert namespace["items"][1].status == ListStatus.DROPPED
    assert list(iter(namespace)) == ["status", "nested", "items"]
    assert len(namespace) == 3

    strict = _ContextNamespace({}, missing_value=...)
    with pytest.raises(AttributeError):
        _ = strict.missing


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param("([len][0])([1])", id="unsupported-call-target"),
        pytest.param("len(**ctx)", id="unpacked-keywords"),
    ],
)
def test_validate_expression_ast_rejects_unsafe_calls(expression: str) -> None:
    """Unsupported call targets and unpacked kwargs should be rejected."""
    with pytest.raises(ValueError):
        _validate_expression_ast(expression)


def test_ctx_field_refs_collects_supported_ctx_paths() -> None:
    """ctx field extraction should include item/child/grandchildren references only."""
    refs = _ctx_field_refs_for_expression(
        "ctx.item.title and ctx.child.season and "
        "ctx.grandchildren[0].index and current.status"
    )

    assert refs == {"title", "season", "index"}


def test_sync_rule_engine_reports_rule_state_and_invalid_status_outputs() -> None:
    """Rule engines should expose rule state and validate status outputs."""
    engine = SyncRuleEngine(
        variables={"same_title": "ctx.item.title == 'Movie'"},
        field_rules={
            "status": [{"name": "set status", "if": "vars.same_title", "set": "'bad'"}],
            "review": False,
            "progress": True,
        },
    )

    assert engine.has_field_rules("status") is True
    assert engine.is_disabled("review") is True
    assert engine.context_media_fields("status") == frozenset({"title"})
    assert engine.evaluate_field(
        field_name="progress",
        current_values={"progress": 1},
        computed_values={"progress": 2},
    ) == SyncRuleDecision(allowed=True, value=2)

    with pytest.raises(ValueError, match="must return a ListStatus or null"):
        engine.evaluate_field(
            field_name="status",
            current_values={"status": ListStatus.PLANNING},
            computed_values={"status": ListStatus.CURRENT},
            rule_context={"item": {"title": "Movie"}},
        )


def test_sync_rule_engine_rejects_non_enum_status_values() -> None:
    """Status rules must resolve to ListStatus values or null."""
    engine = SyncRuleEngine(
        field_rules={"status": [{"set": 123}]},
    )

    with pytest.raises(ValueError, match="must return a ListStatus or null"):
        engine.evaluate_field(
            field_name="status",
            current_values={"status": None},
            computed_values={"status": None},
        )


def test_sync_rule_engine_supports_liststatus_class_in_status_rules() -> None:
    """Status rules should evaluate ListStatus enum members directly."""
    engine = SyncRuleEngine(
        field_rules={
            "status": [
                {
                    "name": "prevent regression",
                    "if": (
                        "current.status == ListStatus.COMPLETED and "
                        "computed.status == ListStatus.CURRENT"
                    ),
                    "set": "ListStatus.COMPLETED",
                }
            ]
        }
    )

    result = engine.evaluate_field(
        field_name="status",
        current_values={"status": ListStatus.COMPLETED},
        computed_values={"status": ListStatus.CURRENT},
    )

    assert result.value == ListStatus.COMPLETED
    assert result.reason == "prevent regression"


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(
            "[g.index for g in ctx.grandchildren if g.view_count]",
            id="list-comp-attribute",
        ),
        pytest.param(
            "max(g.index for g in ctx.grandchildren if g.view_count)",
            id="generator-expr-in-max",
        ),
        pytest.param(
            "[g.index for g in ctx.grandchildren if g.index is not None]",
            id="list-comp-is-not-none",
        ),
        pytest.param(
            "[g.index for g in ctx.grandchildren]",
            id="list-comp-no-filter",
        ),
        pytest.param(
            "sum(1 for g in ctx.grandchildren if g.view_count)",
            id="generator-expr-in-sum",
        ),
    ],
)
def test_validate_expression_ast_accepts_list_comprehensions(
    expression: str,
) -> None:
    """List comprehensions and generator expressions should be allowed in rules."""
    _validate_expression_ast(expression)  # should not raise


def test_validate_expression_ast_rejects_unknown_name_outside_comprehension() -> None:
    """Names not bound by comprehensions or the allowed set should still be rejected."""
    with pytest.raises(ValueError, match="references unknown name"):
        _validate_expression_ast("unknown_var + 1")


def test_validate_expression_ast_comprehension_var_may_not_leak_as_free_name() -> None:
    """A comprehension variable used outside its scope should be rejected if not
    otherwise allowed."""
    # `g` is valid only inside the comprehension body; accessing it as a free
    # name in a separate expression tree should still be rejected.
    with pytest.raises(ValueError, match="references unknown name"):
        _validate_expression_ast("g.index")


def test_ctx_field_refs_detects_fields_via_comprehension_variable() -> None:
    """Fields accessed via a comprehension var over ctx.grandchildren are detected."""
    refs = _ctx_field_refs_for_expression(
        "[g.index for g in ctx.grandchildren if g.view_count and g.index is not None]"
    )

    assert "index" in refs
    assert "view_count" in refs


def test_ctx_field_refs_detects_fields_via_generator_in_max() -> None:
    """Fields used in a generator expression over ctx.grandchildren are detected."""
    refs = _ctx_field_refs_for_expression(
        "max(g.index for g in ctx.grandchildren if g.view_count)"
    )

    assert "index" in refs
    assert "view_count" in refs


def test_ctx_field_refs_ignores_comprehension_over_non_ctx_iterables() -> None:
    """Comprehensions over non-ctx iterables should not contribute field refs."""
    refs = _ctx_field_refs_for_expression(
        "[x.something for x in computed.items if x.other]"
    )

    assert "something" not in refs
    assert "other" not in refs


def test_ctx_field_refs_comprehension_over_ctx_item_is_not_tracked() -> None:
    """Only grandchildren / item / child namespaces feed field refs, not bare ctx."""
    refs = _ctx_field_refs_for_expression("[m.source for m in ctx.mappings]")

    # ctx.mappings is not a media namespace, so no refs should be collected
    assert "source" not in refs


def test_sync_rule_engine_evaluates_list_comp_progress_rule() -> None:
    """A progress rule using a list comprehension over ctx.grandchildren works."""
    engine = SyncRuleEngine(
        variables={
            "watched_indices": (
                "[g.index for g in ctx.grandchildren "
                "if g.view_count and g.index is not None]"
            ),
            "mapping_start": (
                "ctx.mappings[0].mappings[0].source_range.start "
                "if ctx.mappings and ctx.mappings[0].mappings else 1"
            ),
        },
        field_rules={
            "progress": [
                {
                    "name": "index-based-progress",
                    "if": "bool(vars.watched_indices)",
                    "set": "max(vars.watched_indices) - vars.mapping_start + 1",
                }
            ]
        },
    )

    grandchildren = [
        {"index": 1, "view_count": 1},
        {"index": 2, "view_count": 1},
        {"index": 3, "view_count": 0},
    ]
    rule_context = {
        "grandchildren": grandchildren,
        "item": {},
        "child": {},
        "list_media_key": "test-key",
        "mappings": [
            {
                "source": ("anilist", "101", None),
                "target": ("mal", "201", None),
                "mappings": [
                    {
                        "source_range": {"start": 1, "end": 12, "length": 12},
                        "target_ranges": [{"start": 1, "end": 12, "length": 12}],
                        "target_ratio": None,
                        "source_weight": 1.0,
                        "target_weight": 1.0,
                    }
                ],
            }
        ],
    }

    result = engine.evaluate_field(
        field_name="progress",
        current_values={"progress": 0},
        computed_values={"progress": 5},
        rule_context=rule_context,
    )

    assert result.value == 2  # max(1, 2) - 1 + 1
    assert result.reason == "index-based-progress"


def test_sync_rule_engine_list_comp_progress_falls_back_when_no_watched() -> None:
    """Progress rule should fall through to default when no episodes are watched."""
    engine = SyncRuleEngine(
        variables={
            "watched_indices": (
                "[g.index for g in ctx.grandchildren "
                "if g.view_count and g.index is not None]"
            ),
        },
        field_rules={
            "progress": [
                {
                    "name": "index-based-progress",
                    "if": "bool(vars.watched_indices)",
                    "set": "max(vars.watched_indices)",
                }
            ]
        },
    )

    grandchildren = [{"index": 1, "view_count": 0}, {"index": 2, "view_count": 0}]
    rule_context = {
        "grandchildren": grandchildren,
        "item": {},
        "child": {},
        "list_media_key": "test-key",
        "mappings": [],
    }

    result = engine.evaluate_field(
        field_name="progress",
        current_values={"progress": 3},
        computed_values={"progress": 7},
        rule_context=rule_context,
    )

    # Condition is false → falls through to default (computed value)
    assert result.value == 7
    assert result.reason == "default"


def test_sync_rule_engine_list_comp_mapping_start_offset() -> None:
    """mapping_start var should shift progress relative to the source range start."""
    engine = SyncRuleEngine(
        variables={
            "watched_indices": ("[g.index for g in ctx.grandchildren if g.view_count]"),
            "mapping_start": (
                "ctx.mappings[0].mappings[0].source_range.start "
                "if ctx.mappings and ctx.mappings[0].mappings else 1"
            ),
        },
        field_rules={
            "progress": [
                {
                    "name": "index-based-progress",
                    "if": "bool(vars.watched_indices)",
                    "set": "max(vars.watched_indices) - vars.mapping_start + 1",
                }
            ]
        },
    )

    grandchildren = [
        {"index": 13, "view_count": 1},
        {"index": 14, "view_count": 1},
        {"index": 15, "view_count": 0},
    ]
    rule_context = {
        "grandchildren": grandchildren,
        "item": {},
        "child": {},
        "list_media_key": "test-key",
        "mappings": [
            {
                "source": ("anilist", "201", None),
                "target": ("mal", "301", None),
                "mappings": [
                    {
                        "source_range": {"start": 13, "end": 24, "length": 12},
                        "target_ranges": [{"start": 1, "end": 12, "length": 12}],
                        "target_ratio": None,
                        "source_weight": 1.0,
                        "target_weight": 1.0,
                    }
                ],
            }
        ],
    }

    result = engine.evaluate_field(
        field_name="progress",
        current_values={"progress": 0},
        computed_values={"progress": 10},
        rule_context=rule_context,
    )

    # max(13, 14) - 13 + 1 = 2
    assert result.value == 2
    assert result.reason == "index-based-progress"
