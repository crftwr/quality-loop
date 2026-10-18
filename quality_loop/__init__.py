"""quality-loop: measure what an agent-facing product teaches.

A product that agents use - a skill bundle, an MCP server, a CLI - is only as
good as what an agent with nothing else can do with it. This package runs that
agent: a task, in a room holding the product's agent-facing surface and nothing
else, started so it cannot read the repository the answers are in. A second
agent, the operator, puts up whatever the task needs beforehand and afterwards
reports the problems it finds in what the room did, each with a severity.

What has to hold for a run to mean anything - the isolation, the prompt the
room is handed, putting the user's machine back - is code here, not an
agent's discretion.
"""

__version__ = "0.2.0"
