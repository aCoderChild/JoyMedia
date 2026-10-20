# Scene logic across products and workflows

Production logic lives in `joymedia/services/scene`. It has no Frappe, model or workflow-adapter imports. Projects supply case data; workflow records supply execution bindings and controls. A ceramic object, container, cosmetic, character or furniture item uses the same scene domain.

| Module | Responsibility |
| --- | --- |
| `contract.py` | Validate authored entities, relationships, proportions, time intervals and event order; compile opening and motion requirements |
| `structure.py` | Validate and describe object counts, structural parts and preserved properties |
| `references.py` | Group concrete reference views by explicit identity and expand approved variants |
| `identity.py` | Freeze reference sources and preservation strategies without promising fidelity from model names |
| `direction.py` | Compare current intent, reference versions and conditioning frames with the selected footage's original inputs |
| `evidence.py` | Sample and evaluate independent action, physics, structure and consistency claims; preserve uncertainty |

Planning, prompt compilation, first-frame signatures, scene review, snapshotting and release checks consume these shared rules. Frappe authorization, records and job admission remain outside the domain. Concrete node/model names remain in workflow records and adapters. Previous import paths are small compatibility facades so stored jobs and integrations continue to load.

A scene contract is versioned data inside the motion plan. Optional structural fields use declared entity IDs:

```json
{
  "version": 1,
  "entities": [{"id": "object", "label": "the ceramic vessel"}],
  "counts": [{"entity": "object", "count": 1}],
  "parts": [{"entity": "object", "label": "open mouth", "count": 1, "visibility": "visible"}],
  "properties": [{"entity": "object", "name": "surface decoration", "value": "preserve the authored pattern"}]
}
```

Counts describe physical objects and parts. `occlusion_allowed` is the default; hidden parts are not proof of missing parts. The engine does not infer four legs, a chair, a person, packaging or an action from a product category. A four-leg table and a one-pedestal table must declare different structure. An image printed on a product remains surface decoration, not an extra actor or setting. A vase's material source, opening, supports and proportions come from the brief and approved inputs.

Constraints reach both image and motion prompts and independent review claims. Editing them invalidates the old starting-frame signature. Plans exceeding the bounded automatic review budget are rejected during normalization before GPU admission. Unsupported fields, invalid counts, missing entities and conflicting structural declarations are rejected rather than silently dropped. An unavailable or uncertain judge cannot certify geometry or exact branding. Fine surface details still need source-art preservation or suitable multi-view/geometry assets plus visual review.

The planning caller no longer renames every product as a pack, places a locked product on an assumed floor, or turns arbitrary box props into the advertised product. Provider bindings can change without changing the semantic case contract. Changing the referenced product or an approved conditioning frame makes known old footage stale.

Regression data is in `joymedia/tests/fixtures/scene_cases.json`, outside production logic. It covers mascot marketing, a decorated ceramic plate, drinkware, an authored vase example, single-pedestal furniture, lipstick with a separate cap, an upholstered sofa and a wheelchair. The vase example is authored test data, not a claim that a vase photo was supplied or rendered. Live intake checks use actual files from SAN PHAM AI; GPU availability and new-render evidence are reported separately.

The concrete cross-product matrix deliberately exercises different failure modes:

| Reference case | Shared requirement being exercised |
| --- | --- |
| Shera | Character and package identity; authored supports and connected table parts |
| Ceramic plate | Circular geometry; painted scenes remain surface decoration |
| Drink container | Lid state; no unexplained external liquid; surface identity |
| Lipstick and cap | Separate components stay separate; rigid silhouette and embossed mark |
| Sofa | Reference proportions and support layout; wall artwork stays flat |
| Wheelchair | Two rear wheels and two casters remain attached; empty seat stays empty |
| Authored vase / pedestal | Continuous shell and opening / a single support, without four-leg defaults |

Five non-Shera photographs from SAN PHAM AI were uploaded through the test account and checked against saved storyboard requirements. Their source file hashes were preserved; invalid structural updates were rejected without changing saved plans. These are input/application checks. Structural-violation responses in unit tests are simulated judge evidence and establish review handling, not visual judge accuracy. The vase and single-pedestal cases remain authored fixtures. The browser suite accepts `JOYMEDIA_GENERAL_CASES` as a comma-separated fixture selection, so new cases need data rather than a product-specific browser implementation.
