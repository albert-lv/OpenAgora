# Cookbook: Simulated User

Evaluate agents against a simulated user instead of a fixed verifier.

## Concept

A simulated user is a second LLM that plays the role of a human interactor.
The agent must satisfy the user's hidden goal. The verifier checks whether the
conversation reached the goal state.

## Example: customer-support simulator

```text
examples/tasks/simulated-user/
├── task.toml
├── instruction.md
├── user_profile.md
└── tests/
    └── test_goal_reached.py
```

## task.toml

```toml
[task]
name = "simulated-user-support"
description = "Help a frustrated customer get a refund."

[environment]
image = "openagora-agent-minimal:latest"

[agent]
name = "arena-minimal"
max_turns = 10

[verifier]
command = "python tests/test_goal_reached.py"
```

## instruction.md

You are a support agent. A simulated customer will message you. Help them
politely and eventually offer a refund if they are eligible.

## user_profile.md (hidden from agent)

- Goal: get a refund for order #12345
- Emotional state: frustrated
- Will accept refund if agent apologizes and confirms within 5 turns

## Verifier

The verifier reads the trajectory, extracts the final conversation state, and
scores whether the agent satisfied the simulated user.

## Future work

- `SimulatedUserAgent` adapter that runs the user LLM as a separate process
- Reward dimensions: `goal_reached`, `politeness`, `efficiency`
