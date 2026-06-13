"""Speaker notes generation and PPTX injection."""

from ppt_enhance.notes.speaker_notes import (
    NarrativePlan,
    PageNarrative,
    SpeakerNote,
    SpeakerNotesResult,
    generate_speaker_notes,
    load_reference_text,
    save_speaker_notes_json,
    save_speaker_notes_markdown,
    speaker_notes_to_markdown,
    write_speaker_notes,
)

__all__ = [
    "NarrativePlan",
    "PageNarrative",
    "SpeakerNote",
    "SpeakerNotesResult",
    "generate_speaker_notes",
    "load_reference_text",
    "save_speaker_notes_json",
    "save_speaker_notes_markdown",
    "speaker_notes_to_markdown",
    "write_speaker_notes",
]
