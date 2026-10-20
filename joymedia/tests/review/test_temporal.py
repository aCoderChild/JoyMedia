import json
import math
from unittest import TestCase

from joymedia.services.review.temporal import MAX_SAMPLES, SequenceCheck, claims_for, evaluate, sample_times

PLAN = {"scene_contract": {"version": 1, "entities": [{"id": "a", "label": "the actor"}, {"id": "b", "label": "the object"}],
	"relations": [{"kind": "contacts", "subject": "a", "object": "b"}], "events": [
		{"id": "cause", "description": "The actor contacts the object", "start": 0, "end": 1, "after": []},
		{"id": "effect", "description": "The object moves", "start": 1, "end": 3, "after": ["cause"]}]}}


class TestTemporalEvidence(TestCase):
	def check(self):
		claims = claims_for(PLAN, 3, "Contact then move")
		return SequenceCheck([], [{"index": i, "time": t} for i, t in enumerate([0, .5, 1.5, 2.9])], claims, {"asset_version": "TAKE"})

	def answers(self, check):
		return {"observations": [{"id": row["id"], "verdict": "supported", "frames": [1, 2], "reason": "Visible contact followed by movement"} for row in check.claims]}

	def test_sampling_preserves_start_end_event_anchors_and_budget(self):
		times = sample_times(3, 24, PLAN)
		self.assertEqual(times, sorted(set(times)))
		self.assertEqual(times[0], 0)
		self.assertAlmostEqual(times[-1], 71 / 24)
		self.assertIn(.5, times)
		self.assertIn(1, times)
		self.assertLessEqual(len(times), MAX_SAMPLES)
		for fps in [1, 23.976, 24, 60]:
			self.assertTrue(all(0 <= t < 3 for t in sample_times(3, fps, PLAN)))

	def test_invalid_video_metadata_rejected(self):
		for value in [0, -1, math.inf, math.nan, True, "24"]:
			with self.subTest(value=value), self.assertRaises(ValueError):
				sample_times(3, value, PLAN)

	def test_action_physics_and_continuity_are_independent(self):
		check = self.check()
		answer = self.answers(check)
		self.assertEqual(evaluate(check, answer)["status"], "Passed")
		answer["observations"][1].update(verdict="violated", reason="Object abruptly duplicates")
		report = evaluate(check, answer)
		self.assertEqual(report["status"], "Needs Review")
		self.assertEqual(report["results"][0]["verdict"], "supported")
		self.assertEqual(report["results"][1]["verdict"], "violated")
		self.assertEqual(report["asset_version"], "TAKE")

	def test_missing_or_invalid_observations_are_never_support(self):
		check = self.check()
		for rows in [None, [], [{}], [{"id": "invented"}]]:
			self.assertEqual(evaluate(check, {"observations": rows})["status"], "Needs Review")
		for frames in [[], [True], [-1], [99], [1, 1], ["1"]]:
			answer = self.answers(check)
			answer["observations"][0]["frames"] = frames
			self.assertEqual(evaluate(check, answer)["results"][0]["verdict"], "uncertain")

	def test_duplicate_claims_and_unknown_claims_cannot_pass(self):
		check = self.check()
		for extra in [{"id": "invented"}, self.answers(check)["observations"][0]]:
			answer = self.answers(check)
			answer["observations"].append(extra)
			self.assertEqual(evaluate(check, answer)["status"], "Needs Review")

	def test_order_needs_two_distinct_chronological_samples(self):
		check = self.check()
		for frames in [[1], [2, 1], [1, 1]]:
			answer = self.answers(check)
			next(row for row in answer["observations"] if row["id"].startswith("order.")).update(frames=frames)
			self.assertEqual(evaluate(check, answer)["status"], "Needs Review")

	def test_late_event_evidence_is_reported_as_timing_instead_of_physics_failure(self):
		check = self.check()
		answer = self.answers(check)
		next(row for row in answer["observations"] if row["id"] == "event.cause")["frames"] = [2, 3]
		result = next(row for row in evaluate(check, answer)["results"] if row["id"] == "event.cause")
		self.assertEqual(result["verdict"], "supported")
		self.assertEqual(result["timing_alignment"], "observed outside authored window")

	def test_uncertainty_is_preserved_without_invented_probability(self):
		check = self.check()
		answer = self.answers(check)
		answer["observations"][0].update(verdict="uncertain", frames=[], reason="Interaction occurs between sampled frames")
		report = evaluate(check, answer)
		self.assertEqual(report["results"][0]["verdict"], "uncertain")
		self.assertNotIn("score", report)
		json.dumps(report)

	def test_batched_requests_cover_all_samples_and_use_bounded_claims(self):
		from joymedia.services.review.temporal import batches
		check = self.check()
		check.metadata = [{"index": i, "time": i * 2.9 / 15} for i in range(16)]
		requests = list(batches(check))
		self.assertTrue(requests)
		self.assertTrue(all(1 <= len(indices) <= 4 and 1 <= len(claims) <= 2 for indices, claims in requests))
		self.assertEqual(set(range(16)), {i for indices, _ in requests for i in indices})

	def test_a_judge_cannot_cite_a_frame_outside_its_actual_window(self):
		check = self.check()
		check.context["allowed_indices"] = [0, 1]
		report = evaluate(check, self.answers(check))
		self.assertTrue(all(row["verdict"] == "uncertain" for row in report["results"]))

	def test_one_bad_or_uncertain_window_overrides_other_supported_windows(self):
		from joymedia.services.review.temporal import merge_observations
		check = self.check()
		good = evaluate(check, self.answers(check))
		answer = self.answers(check)
		answer["observations"][0].update(verdict="violated", frames=[1], reason="No contact before motion")
		bad = evaluate(check, answer)
		report = merge_observations(check, [good, bad])
		self.assertEqual(report["status"], "Needs Review")
		self.assertEqual(report["results"][0]["verdict"], "violated")

	def test_malformed_identifiers_do_not_crash_the_evidence_validator(self):
		check = self.check()
		for value in [[], {}, True, 123]:
			answer = self.answers(check)
			answer["observations"][0]["id"] = value
			self.assertEqual(evaluate(check, answer)["status"], "Needs Review")

	def test_occurrence_is_not_required_before_it_starts_but_a_violation_still_wins(self):
		from joymedia.services.review.temporal import merge_observations
		check = self.check()
		good = evaluate(check, self.answers(check))
		answer = self.answers(check)
		answer["observations"][0].update(verdict="uncertain", frames=[], reason="Action has not started in this window")
		unclear = evaluate(check, answer)
		self.assertEqual(merge_observations(check, [unclear, good])["results"][0]["verdict"], "supported")
		answer["observations"][1].update(verdict="uncertain", frames=[], reason="Subject is obscured")
		unclear = evaluate(check, answer)
		self.assertEqual(merge_observations(check, [unclear, good])["results"][1]["verdict"], "uncertain")

	def test_partial_diagnostic_must_not_claim_full_scene_coverage(self):
		check = self.check()
		check.context["required_claim_ids"] = [row["id"] for row in check.claims]
		self.assertEqual(evaluate(check, self.answers(check))["scope"], "scene")
		check.claims = check.claims[:1]
		self.assertEqual(evaluate(check, self.answers(check))["scope"], "partial")

	def test_opening_condition_is_checked_independently_of_a_confident_judge(self):
		import io

		from PIL import Image, ImageDraw

		from joymedia.services.review.temporal import compare_opening

		def picture(position):
			image = Image.new("RGB", (144, 256), "white")
			ImageDraw.Draw(image).rectangle((position, 60, position + 50, 180), fill="blue")
			data = io.BytesIO()
			image.save(data, "PNG")
			return data.getvalue()
		self.assertEqual(compare_opening(picture(10), picture(10))["verdict"], "supported")
		opening = compare_opening(picture(10), picture(70))
		self.assertEqual(opening["verdict"], "violated")
		check = self.check()
		check.context.update(required_claim_ids=[row["id"] for row in check.claims], opening_state=opening)
		report = evaluate(check, self.answers(check))
		self.assertEqual(report["status"], "Needs Review")
		self.assertEqual(report["results"][0]["id"], "opening.condition")

class TestWindowCoverage(TestCase):
 def test_trailing_window_is_not_rejudged_as_contextless_single_frame(self):
  from joymedia.services.scene.evidence import batches,SequenceCheck
  for count in range(1,17):
   check=SequenceCheck([], [dict(index=i,time=i) for i in range(count)], [dict(id='paw',dimension='staging',claim='Connected rounded paw')], {})
   windows=[indices for indices,claims in batches(check)]
   self.assertEqual(set(range(count)),{i for w in windows for i in w})
   self.assertFalse(any(set(w)<set(other) for w in windows for other in windows))

class TestStreamFrameSampling(TestCase):
 def test_rounded_container_duration_cannot_request_a_nonexistent_frame(self):
  from joymedia.services.scene.evidence import sample_times
  for duration in [5.166667,5.1666666667]:
   self.assertLessEqual(max(sample_times(duration,24)),123/24)
   self.assertLessEqual(max(sample_times(duration,24,frame_count=124)),123/24)
 def test_an_authoritative_stream_count_handles_fractional_rates(self):
  from joymedia.services.scene.evidence import sample_times
  fps=30000/1001;times=sample_times(4.171,fps,frame_count=125)
  self.assertEqual(124,round(max(times)*fps))
