# Audio hook strategy

## Repositories inspected and integrated

| Repository | Local clone | Useful finding | JoyMedia integration |
| --- | --- | --- | --- |
| [AudioCraft](https://github.com/facebookresearch/audiocraft) | `research/audiocraft` at `896ec7c` | MusicGen uses text descriptions; JASCO combines global direction with local temporal controls. | The existing music workflow receives a structured score prompt: musical identity plus hook, groove, lift and resolve timed to the film. |
| [Tango](https://github.com/declare-lab/tango) | `research/tango` at `34ecd38` | Text-to-audio quality depends on a concrete, event-focused caption; Tango 2 adds preference alignment. | JoyMedia keeps precise labelled SFX prompts and does not ask a music model to make speech or effects. |

Neither repository is installed as a second production generator. AudioCraft's useful models require a further GPU model download and would compete with H3/Ref2VA on the single GPU. Replacing MMAudio would lower throughput without proving a better branded soundtrack. Their prompt-control strategy is integrated into the configured music path instead.

## Production behaviour

1. The screenplay writer receives a voice-over contract: an opening tension/question/sensory hook tied to visible action, a proof-oriented benefit, and a concise CTA. It cannot use unapproved claims or simply read captions aloud.
2. The score renderer turns the authored music direction into an instrumental arrangement map. It begins with a motif in the first 12% of the film, supports action through the middle, lifts around the benefit, and resolves under the CTA.
3. The Edge narration adapter gives the first spoken line a restrained faster, brighter delivery and settles the final CTA. Custom narration workflows still receive the exact text and are not given unsupported controls.
4. Music remains instrumental and is ducked under voice-over and effects by the existing timeline mix rules.

This changes prompts and performance delivery, not the advertised product claims, project-specific music choice, workflow sampling settings, or source audio ownership.
