"""Version 2, from version 1."""

from .changes import (
    Drop,
    Each,
    Effects,
    FirstKey,
    Forbid,
    Has,
    Migration,
    MoveTo,
    Nest,
    Reshape,
    Rewrite,
    RewriteKey,
    ShortSteps,
)

# The diagram itself, and each component: both hold groups and nodes.
BOXES = Each("", "components.*")

# Every node, inside groups too, however deep.
NODES = Each("nodes.*", nested="groups.*")
COMPONENT_NODES = Each("components.*.nodes.*", nested="groups.*")

# A step's own keys in version 1; a step with one other key holding a list is 'Title: [effects]'.
STEP_KEYS = ("title", "text", "at", "status", "focus", "do")

# Every effect version 1 allowed, inside parallel and repeat too: in steps, in short steps and in actions, the
# diagram's and the components'.
EFFECTS = Effects(
    "scenarios.*.steps.*.do", ShortSteps("scenarios.*.steps.*", STEP_KEYS), "actions.*", "components.*.actions.*"
)

# In version 2 an action may be called 'set', and then 'set ...' calls it: leave those alone.
SET_IS_AN_ACTION = Has("actions.set", "components.*.actions.set")


MIGRATION = Migration(
    version=2,
    changes=[
        Nest(
            "A group or node goes inside the group that holds it",
            key="in",
            sections=["groups", "nodes"],
            within=BOXES,
            before="""
                groups:
                  front: {title: Front}
                nodes:
                  web: {icon: browser, in: front}
            """,
            after="""
                groups:
                  front:
                    title: Front
                    nodes:
                      web: {icon: browser}
            """,
        ),
        MoveTo(
            "A trigger button is written on the scenario it plays",
            each=NODES,
            when="trigger",
            take=["trigger", "plays"],
            defaults={"plays": FirstKey("scenarios")},
            to="scenarios.{plays}.trigger",
            value={"at": "{key}", "label": "{trigger}"},
            before="""
                nodes:
                  web: {icon: browser, trigger: Place order, plays: order}
                scenarios:
                  order: {steps: [{title: Go, do: [activate web]}]}
            """,
            after="""
                nodes:
                  web: {icon: browser}
                scenarios:
                  order:
                    trigger: {at: web, label: Place order}
                    steps: [{title: Go, do: [activate web]}]
            """,
        ),
        Drop(
            "'plays' on a node without a trigger plays nothing",
            each=NODES,
            key="plays",
            before="""
                nodes:
                  web: {icon: browser, plays: order}
            """,
            after="""
                nodes:
                  web: {icon: browser}
            """,
        ),
        Forbid(
            "Nodes in components have no triggers",
            each=COMPONENT_NODES,
            key="trigger",
            fix="give the scenario 'trigger: {at: <instance>/{key}, label: ...}'",
        ),
        Reshape(
            "'repeat' takes its count in the key",
            each=EFFECTS,
            match={"repeat": "{count}", "do": "{effects}"},
            into={"repeat {count}": "{effects}"},
            before="""
                scenarios:
                  s:
                    steps:
                      - title: Retry
                        do:
                          - repeat: 3
                            do: [fail api]
            """,
            after="""
                scenarios:
                  s:
                    steps:
                      - title: Retry
                        do:
                          - repeat 3: [fail api]
            """,
        ),
        Rewrite(
            "Text changes are written without 'set'",
            each=EFFECTS,
            match="set {target} [{duration}]: {text}",
            into={"{target} [{duration}]": "{text}"},
            unless=SET_IS_AN_ACTION,
            before="""
                scenarios:
                  s:
                    steps:
                      - title: Store
                        do: ["set db.sub 300ms: writing"]
            """,
            after="""
                scenarios:
                  s:
                    steps:
                      - title: Store
                        do: [{db.sub 300ms: writing}]
            """,
        ),
        Rewrite(
            "Text changes are written without 'set', with a colon before the text",
            each=EFFECTS,
            match="set {target} [{duration}] [{plain_text}]",
            into={"{target} [{duration}]": "{plain_text}"},
            unless=SET_IS_AN_ACTION,
            before="""
                scenarios:
                  s:
                    steps:
                      - title: Store
                        do: [set db.sub writing now]
            """,
            after="""
                scenarios:
                  s:
                    steps:
                      - title: Store
                        do: [{db.sub: writing now}]
            """,
        ),
        RewriteKey(
            "Text changes are written without 'set'",
            each=EFFECTS,
            match="set {rest}",
            into="{rest}",
            unless=SET_IS_AN_ACTION,
            before="""
                scenarios:
                  s:
                    steps:
                      - title: Store
                        do: [{set db.title: Orders}]
            """,
            after="""
                scenarios:
                  s:
                    steps:
                      - title: Store
                        do: [{db.title: Orders}]
            """,
        ),
        Rewrite(
            "The status line takes its text after a colon",
            each=EFFECTS,
            match="status [{duration}] [{plain_text}]",
            into={"status [{duration}]": "{plain_text}"},
            before="""
                scenarios:
                  s:
                    steps:
                      - title: Work
                        do: [status 200ms working]
            """,
            after="""
                scenarios:
                  s:
                    steps:
                      - title: Work
                        do: [{status 200ms: working}]
            """,
        ),
    ],
)
