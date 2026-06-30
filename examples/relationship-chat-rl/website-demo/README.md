# Website Demo Assets

This directory provides the assets needed to publish the "Relationship Chat Assistant" example to the [website repository](https://github.com/albert-lv/openagora-website).

## File Descriptions

| File | Purpose |
|------|------|
| `relationship-chat-demo-section.html` | Demo section that can be pasted into the website `index.html` |
| `relationship-chat-dashboard.png` | Arena Dashboard — Verify Stats tab screenshot |
| `relationship-chat-rollouts.png` | Arena Dashboard — Rollouts tab screenshot |
| `relationship-chat-token-stats.png` | Arena Dashboard — Token Stats tab screenshot |
| `relationship-chat-trend.svg` | RL training verify success-rate trend chart (illustrative) |

## Usage

1. Copy the images into the website repository's `images/` directory:

   ```bash
   cd /path/to/openagora-website
   mkdir -p images
   cp /path/to/OpenAgora/examples/relationship-chat-rl/website-demo/*.png images/
   cp /path/to/OpenAgora/examples/relationship-chat-rl/website-demo/*.svg images/
   ```

2. Open the website `index.html` and paste the contents of `relationship-chat-demo-section.html` right after the existing `<section id="demo">...</section>`.

3. If the website already has a navigation bar, add an item to the `<nav>` link list:

   ```html
   <a href="#relationship-chat">Relationship Chat</a>
   ```

4. Preview locally, then commit and push to the website repository.

## Replacing the Illustrative Chart

- `relationship-chat-trend.svg` is an illustrative rising trend chart. After running `docker compose up --build`, you can replace it with a screenshot from the Arena Dashboard.
- The three Dashboard screenshots come from an actual `Qwen/Qwen3.5-0.8B` training run and can be used directly on the website.
