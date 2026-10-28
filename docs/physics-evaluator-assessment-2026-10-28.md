# Physics evaluator assessment — 28 October 2026

Two public repositories were cloned for inspection outside the production tree:

- `microsoft/AVGen-Bench` commit `1049eabac472d479fe5feeb1ee202961f8e0982a`,
  including the MIT-licensed VideoPhy evaluation code. VideoCon-Physics is a
  model-based video evaluator; the code is not a video generator or a guarantee
  of physical correctness. Model weights and runtime were not installed or tested.
- `OpenGVLab/PhyGenBench` commit `f8642cb796f3bcb01f0b7c1b2ec53b75d357c739`.
  Its three-stage evaluation includes event, temporal order, and overall video
  checks. The inspected checkout did not include a license file, and its example
  code relies on external models and environment-specific paths. It was not
  copied into JoyMedia or run as a production evaluator.

JoyMedia already uses text-level action review and image-level physical review.
The deterministic adjacent-action check added here catches exact repeated text
after removing time labels; it cannot establish whether a video is physically
correct and can reject intentional repeated performances. Its purpose is to
request a distinct generated beat, not to measure visual motion or brand fidelity.

Live `CRB-00002` on the GPU demo finished `Needs Attention`: required character
poses for scenes 1–7 could not be verified, so no first-frame Generation Run was
created. The later saved script had already changed the previously repeated
scenes; the new exact-duplicate check returned no finding for that saved draft.
No third-party evaluator, new storyboard frame, or final video was qualified by
this assessment. A real trial needs model/license and capacity checks, independent
positive and negative video cases, and comparison with human-reviewed outcomes
before any evaluator can be used to admit automatic final video.
