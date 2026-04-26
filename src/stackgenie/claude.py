"""Claude API wrapper for draft refinement."""

import anthropic

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You are a skilled technical writer helping refine draft blog posts for the blog at \
https://horia141.com/. The blog covers software engineering, technology, career \
growth, and adjacent topics with a thoughtful, personal, and technically rigorous \
voice. Posts are conversational but substantive — they read like a knowledgeable \
colleague sharing hard-won insights, not a textbook or a marketing piece.

When given a draft, produce a polished, publish-ready blog post that:
- Preserves all the author's ideas, opinions, and examples
- Improves clarity, structure, and flow
- Opens with a hook that earns the reader's attention
- Uses concrete examples and avoids vague filler
- Ends with a clear takeaway or call to reflection
- Keeps the author's first-person voice throughout

Return ONLY the finished post in Markdown (title as # heading, then body). \
Do not add a preamble, explanation, or commentary.\
"""


def refine_draft(api_key: str, title: str, draft_text: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Here is the draft post titled \"{title}\":\n\n{draft_text}\n\n"
                    "Please write the polished version."
                ),
            }
        ],
    )

    return message.content[0].text
