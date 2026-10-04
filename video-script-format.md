# Video Script Format

`build_video.py` parses scenes out of a Markdown file with this structure. Only
the scene headings, on-screen text lines, and narration blockquotes are read —
everything else is for humans.

## Required layout

```markdown
### Scene 1 — Short Title · 0:00–0:25
**Visual:** which frame to show, what to zoom toward, what to highlight.
**On-screen text:** *Short supporting phrase*
**Narration:**
> Spoken prose. Short sentences. This is what gets synthesized
> and what the captions are generated from.

### Scene 2 — Next Beat · 0:25–0:55
...
```

Rules the parser depends on:

| Element | Requirement |
| --- | --- |
| Heading | `### Scene <n> — <title> · <m>:<ss>–<m>:<ss>` — em dash, middle dot, en dash between times |
| Numbering | Contiguous from 1 |
| On-screen text | Single line, italicised, at the end of its line: `**On-screen text:** *…*` |
| Narration | Every line after `**Narration:**` that begins with `>` is joined into one paragraph |

Timestamps are advisory. By default each scene is sized to its narration
(speech + padding); pass `--script-timing` to honour the written timestamps.

## Recommended surrounding sections

Put these above the scenes for the humans producing the video:

1. **Production metadata** — audience, target duration, tone, available assets.
2. **Production notes** — pacing, captions, transitions, sensitive-data
   masking, accessibility.
3. **Asset checklist** — every frame filename referenced, with an exists column.

## Narrative arc that usually works

1. Problem or mission
2. Product introduction and scale
3. Core user workflows
4. Differentiating capability
5. Architecture, performance, and governance
6. Outcome-focused close

## Writing narration for TTS

- Short declarative sentences; synthesizers handle commas better than dashes.
- Round large numbers — "more than eight million", not "8,123,201".
- Spell out or respell initialisms that read badly via `speech_fixes` in the
  config (captions keep the written form).
- Avoid parentheses and semicolons; they produce odd pauses.
- One idea per sentence, so caption chunking breaks cleanly.
