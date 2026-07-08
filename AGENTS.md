# AI University Agent Instructions

- Default AIU lectures must represent two hours of professor speech.
- The default minimum transcript length is 18,000 words per lecture:
  `2.0 hours * 60 minutes * 150 spoken words/minute`.
- Do not lower `CourseSettings.lecture_hours`, `WORDS_PER_SPOKEN_MINUTE`, or the
  `minimum_transcript_words()` validation path without an explicit product
  decision and matching tests.
- Keep the `--lecture-hours` override for explicit custom runs; when it is used,
  the transcript minimum must scale from that configured duration.
- Lecture generation must use compact course memory/context packets instead of
  feeding full previous transcripts forward.
