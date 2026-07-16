# Cookbook: Computer Use

Evaluate agents that interact with a desktop environment (GUI/browser).

## Concept

Computer-use agents need a sandbox with a display server, browser, and input
automation tools. OpenAgora's sandbox provider abstraction can support this by
choosing an image with the required GUI stack.

## Example task layout

```text
examples/tasks/computer-use/
├── task.toml
├── instruction.md
└── tests/
    └── test_state.py
```

## task.toml

```toml
[environment]
image = "openagora/computer-use:latest"
# Provide a display and VNC/port forwarding via the provider if supported.

[agent]
name = "arena-minimal"

[verifier]
command = "python tests/test_state.py"
```

## instruction.md

Open Chrome, navigate to http://example.com, and click the login button.

## Provider requirements

- Docker provider: run with `--cap-add=SYS_ADMIN` and a display image
- E2B/Modal: use their desktop sandbox templates
- Future: built-in `computer-use` capability in `sandbox.CapabilitySet`

## Future work

- Add `examples/tasks/computer-use/` with a real browser-automation task
- Record screenshots/video as trajectory artifacts
- ATIF observation type for `screenshot` and `mouse/keyboard` actions
