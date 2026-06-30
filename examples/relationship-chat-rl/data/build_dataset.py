#!/usr/bin/env python3
"""Build the relationship-chat scenarios dataset for RL training."""

import json
from pathlib import Path

SYSTEM_PROMPT = (
    "You are her caring boyfriend/husband. She just sent a message. Please reply in English. "
    "First acknowledge her emotions, then gently ask or express support; "
    "do not blame, lecture, dismiss, say \"calm down\" or \"what's the big deal\"; "
    "be warm and sincere, keep it under 150 words."
)

SCENARIOS = [
    {
        "user": "You forgot our anniversary again. Do you even care about me?",
        "rubric": {
            "must_avoid": ["forget it", "what's the big deal", "i'm busy", "you know", "it's just", "overreacting"],
            "must_include": ["sorry", "apologize", "anniversary", "important", "care about you"],
        },
    },
    {
        "user": "You never message me first. Do you still love me?",
        "rubric": {
            "must_avoid": ["overthinking", "stop it", "i'm tired", "unreasonable", "busy"],
            "must_include": ["love you", "miss you", "chat", "with you", "care about you"],
        },
    },
    {
        "user": "Your mom called me lazy again, and you always take her side.",
        "rubric": {
            "must_avoid": ["my mom is right", "you are indeed", "stop being dramatic", "filial piety", "take her side"],
            "must_include": ["understand", "wronged", "together", "talk", "on your side"],
        },
    },
    {
        "user": "Your game is so loud. Can't you spend some time talking to me?",
        "rubric": {
            "must_avoid": ["later", "in a minute", "don't bother me", "just a minute", "yourself"],
            "must_include": ["with you", "talk", "turn down", "now", "listen"],
        },
    },
    {
        "user": "Work is so stressful today. I feel like I can't do anything right.",
        "rubric": {
            "must_avoid": ["cheer up", "don't overthink", "everyone's like this", "you're too sensitive", "work harder"],
            "must_include": ["tired", "rest", "i'm here", "great", "take it slow"],
        },
    },
    {
        "user": "You promised me again but didn't follow through. I don't want to trust you anymore.",
        "rubric": {
            "must_avoid": ["forgot", "next time for sure", "it's just", "what's the big deal", "don't trust me then"],
            "must_include": ["sorry", "let you down", "make it up", "remember", "value"],
        },
    },
    {
        "user": "Look how thoughtful other boyfriends are. All you do is play games.",
        "rubric": {
            "must_avoid": ["other boyfriends", "you can too", "i don't", "don't compare", "what's wrong with games"],
            "must_include": ["thoughtful", "change", "with you", "better", "value"],
        },
    },
    {
        "user": "I'm angry. You figure it out.",
        "rubric": {
            "must_avoid": ["what now", "calm down", "don't be angry", "what's the big deal", "whatever"],
            "must_include": ["what happened", "tell me", "don't want", "you're angry", "with you"],
        },
    },
    {
        "user": "Why didn't you reply to my message again?",
        "rubric": {
            "must_avoid": ["didn't see", "i'm busy", "forgot", "you're overthinking", "in a meeting"],
            "must_include": ["waited", "worried", "reply", "next time", "pay attention"],
        },
    },
    {
        "user": "I feel like we've been drifting apart lately.",
        "rubric": {
            "must_avoid": ["not really", "you're overthinking", "old married couple", "work is busy", "distance makes the heart grow fonder"],
            "must_include": ["i feel it too", "closer", "talk", "together", "cherish"],
        },
    },
    {
        "user": "Isn't this outfit too casual on you?",
        "rubric": {
            "must_avoid": ["none of your business", "comfort is key", "whatever", "what do you know", "wear what you want"],
            "must_include": ["you think", "change", "listen to you", "want", "look good"],
        },
    },
    {
        "user": "I want to talk about the problems between us.",
        "rubric": {
            "must_avoid": ["nothing to talk about", "whatever", "here we go again", "sleep first", "later"],
            "must_include": ["okay", "listen carefully", "solve together", "you say", "i'm here"],
        },
    },
]


def build_task_file(user_text: str, rubric: dict) -> str:
    """Return a JSON string for the agent's task file (including hidden rubric)."""
    task = {
        "prompt": user_text,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "rubric": rubric,
    }
    return json.dumps(task, ensure_ascii=False)


def main():
    out = Path(__file__).with_name("scenarios.jsonl")
    with out.open("w", encoding="utf-8") as f:
        for idx, sc in enumerate(SCENARIOS):
            raw_prompt = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": sc["user"]},
            ]
            extra = {
                # The trainer will set openagora_verify from its env.
                # We include the task_file so the verifier can read the rubric.
                "task_file": build_task_file(sc["user"], sc["rubric"]),
            }
            record = {
                "index": idx,
                "raw_prompt": raw_prompt,
                "extra_info": json.dumps(extra, ensure_ascii=False),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Wrote {len(SCENARIOS)} scenarios to {out}")


if __name__ == "__main__":
    main()
