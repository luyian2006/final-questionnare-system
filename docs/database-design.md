# MongoDB Data Model Design

This document records the MongoDB data model design for the questionnaire system. It expands the earlier notes while keeping the original principles: do not put all data in one collection, avoid hard-coded business logic, and keep enough structure for later requirement changes.

Current project stage: the first-stage FastAPI + PyMongo questionnaire flow has been extended with a phase-two question library. The original `users`, `surveys`, and `responses` collections remain in place; `question_items` and `question_versions` add reusable question identity and immutable version content. The implementation is in `app/api.py`, `app/question_api.py`, `app/services.py`, and `app/question_services.py`.

## Design Contract

The design follows the course requirement and the implemented FastAPI/PyMongo code. The first stage supports registered users, owner-isolated surveys, four question types, configurable jumps, final responses, and on-demand statistics. Phase two adds reusable question items and immutable versions without replacing the first-stage survey and response structures.

### Core Model

- Use `users`, `surveys`, and `responses` as the core collections for the first complete stage.
- Embed the active survey structure, questions, options, validation rules, and jump rules inside `surveys` as versioned survey definitions.
- Store submitted responses in a separate `responses` collection.
- Store an immutable survey definition snapshot or version reference with each response so historical answers remain interpretable after the survey is edited.
- Compute statistics from `responses` on demand first. Add cached statistics later only if performance requires it.
- Store password hashes and password algorithm metadata, never plaintext passwords.
- Use a unique random `share_slug` for public survey access.
- Use indexes to enforce username uniqueness, share slug uniqueness, ownership lookups, response lookups, and duplicate submission rules.
- Use `question_items` for question identity, ownership, sharing, current-version pointer, and derivation lineage; use `question_versions` for immutable content.
- When adding a question to a survey, copy the selected version content into the survey snapshot and record the source item/version IDs. Do not make the survey depend on a live library reference.

### Confirmed Decisions

- Anonymous filling means login-required anonymity: fillers must log in, but survey creators cannot see filler identity in owner-facing response views. This is not system-level complete anonymity because the system still verifies and stores internal identity for authentication, duplicate control, and auditing.
- Published survey versions are immutable. Editing a published survey creates a new draft or a new version. Historical responses retain the version association used at submission time.
- Jump rules on the same question are evaluated by ascending `priority`, and the first matching rule wins.
- If no jump rule matches, the next question is the next item in the survey definition order. If the current question is the last question, filling ends.
- Version 1 forbids jump cycles. Publishing performs rule validation, and runtime traversal also uses a maximum jump-step limit as a defensive guard.
- The first-stage core MongoDB collections are `users`, `surveys`, and `responses`; phase two adds `question_items` and `question_versions`.
- Questions, options, validation rules, and jump rules are embedded in the matching survey version. Responses are stored independently.
- The jump algorithm is separated from database access and HTTP routing so it can be tested independently.
- Owner-facing anonymous response views must be permission-controlled and must not expose internal `respondent_user_id`.

The first stage stores final submitted responses only. Each response includes a version number and survey snapshot. There is no client IP/user-agent field and no default cross-version merge policy.

## Recommended Collection Overview

Core collections:

- `users`: account and authentication identity.
- `surveys`: survey ownership, sharing, lifecycle state, current draft, published version, embedded questions, validation rules, and jump rules.
- `responses`: submitted answers, response metadata, survey version snapshot or version reference, and submission status.

Phase-two collections:

- `question_items`: stable question identity, owner, shared state, current version pointer, and derivation lineage.
- `question_versions`: immutable question content and version history.

### Why These Core Collections

- `users` is independent because authentication identity, password security, and account lifecycle should not be embedded in survey documents.
- `surveys` owns the questionnaire definition. Survey metadata, versions, questions, options, validation rules, and jump rules are loaded together for editing, publishing, and filling.
- `responses` is independent because submissions grow continuously, are written concurrently, and are aggregated for statistics. Embedding responses in `surveys` would make survey documents grow without a practical bound and would create write contention.

This split avoids the anti-pattern of putting all data in one collection, but it also avoids unnecessary normalization such as separate `questions`, `options`, and `jump_rules` collections before the requirements justify them.

Phase two adds two collections because question ownership and version history now have an independent lifecycle from surveys. It does not add separate collections for options or jump rules: they remain embedded in the version's `content`, preserving compatibility with the first-stage validators. Survey questions remain full copies, so later library edits or unsharing do not mutate existing surveys or response snapshots.

## Users Collection

Purpose: store registered user identity and login-related fields.

### Example Document

```javascript
{
  _id: ObjectId("..."),
  username: "alice",
  username_normalized: "alice",
  password_hash: "pbkdf2_sha256$310000$...",
  password_algorithm: "pbkdf2_sha256",
  created_at: ISODate("2026-10-16T02:00:00Z"),
  updated_at: ISODate("2026-10-16T02:00:00Z"),
  last_login_at: ISODate("2026-10-16T02:30:00Z"),
  status: "active"
}
```

### Field Notes

- `_id`: MongoDB `ObjectId`.
- `username`: display/login username.
- `username_normalized`: lowercase or otherwise normalized username for uniqueness checks.
- `password_hash`: secure one-way password hash. Plaintext passwords must never be stored.
- `password_algorithm`: records the hash algorithm for future migration.
- `created_at`: required by the assignment as registration time.
- `status`: `active`, `disabled`, or `deleted`.

### Indexes

```javascript
db.users.createIndex({ username_normalized: 1 }, { unique: true })
db.users.createIndex({ created_at: -1 })
```

### Consistency Considerations

- Registration must create a user only if `username_normalized` is unique.
- Password changes should update `password_hash`, `password_algorithm`, and `updated_at`.
- Authentication logic should compare password input with the hash in constant-time library code.

## Surveys Collection

Purpose: store survey metadata, owner relationship, sharing state, publication lifecycle, versioned questionnaire definition, embedded questions, validation rules, and jump rules.

### Recommended Shape

```javascript
{
  _id: ObjectId("..."),
  owner_user_id: ObjectId("..."),
  title: "Student Learning Survey",
  description: "A short survey about learning habits.",
  share_slug: "svy_8f3K2pQ9",
  status: "draft",
  allow_anonymous: true,
  require_login_to_fill: true,
  allow_multiple_submissions: false,
  deadline_at: ISODate("2026-12-31T15:59:59Z"),
  closed_at: null,
  published_at: null,
  created_at: ISODate("2026-10-16T02:00:00Z"),
  updated_at: ISODate("2026-10-16T02:10:00Z"),
  current_version: 1,
  published_version: null,
  versions: [
    {
      version: 1,
      state: "draft",
      created_at: ISODate("2026-10-16T02:00:00Z"),
      published_at: null,
      questions: [
        {
          question_id: "q_gender",
          type: "single_choice",
          title: "你的性别",
          description: "",
          required: true,
          order: 1,
          options: [
            { option_id: "opt_male", label: "男", order: 1 },
            { option_id: "opt_female", label: "女", order: 2 },
            { option_id: "opt_other", label: "其他", order: 3 }
          ],
          validation: {},
          jump_rules: [
            {
              rule_id: "jr_gender_other",
              priority: 1,
              condition: {
                operator: "equals",
                value: "opt_other"
              },
              target: {
                type: "question",
                question_id: "q_gender_note"
              }
            }
          ]
        }
      ]
    }
  ]
}
```

### Survey Metadata Fields

- `owner_user_id`: references `users._id`. Used to enforce "users only see their own surveys".
- `title`: survey title.
- `description`: survey description.
- `share_slug`: unique public identifier used in URLs such as `/survey/svy_8f3K2pQ9`.
- `status`: lifecycle state, such as `draft`, `published`, `closed`, or `archived`.
- `allow_anonymous`: whether submitted responses can hide filler identity from the owner.
- `require_login_to_fill`: whether filling requires login. This is separated from `allow_anonymous` because the assignment mentions both login and anonymous filling.
- `allow_multiple_submissions`: whether the same filler may submit more than once.
- `deadline_at`: optional closing deadline.
- `closed_at`: when the owner manually closed the survey.
- `published_at`: first publication time.
- `current_version`: latest editable version number.
- `published_version`: version number currently visible to fillers.
- `versions`: embedded versioned questionnaire definitions.

### Version Field Responsibilities

- `current_version` points to the newest version record in `versions`. It is usually the draft being edited.
- `published_version` points to the immutable version currently available through the share URL. It is `null` before first publication.
- `versions` stores bounded version records. Each version contains the survey definition for that version, including questions, options, validation rules, and jump rules.
- A version record with `state: "published"` must not be modified in place. If the owner changes a published survey, the system creates a new draft version and later publishes it as a new immutable version.

### Survey Lifecycle

1. Create survey: insert a `surveys` document with `status: "draft"`, `current_version: 1`, `published_version: null`, and one draft version.
2. Edit draft: update only the current draft version.
3. Publish: validate required fields, question IDs, option IDs, validation rules, jump targets, and cycle rules. Then mark the draft version as `published`, set `published_version`, and set survey `status: "published"`.
4. Edit after publish: create a new draft version by copying the published definition and applying changes to the draft only. The previous published version remains immutable.
5. Publish new version: validate the new draft, then make it the new `published_version`. Existing responses still reference the version they used.
6. Close survey: set `status: "closed"` or `closed_at`. Existing responses remain queryable for the owner.

This lifecycle is a project decision, not a direct quote from the course document. It is chosen to satisfy the course's staged-development requirement and to keep historical answers interpretable.

### Survey Indexes

```javascript
db.surveys.createIndex({ owner_user_id: 1, updated_at: -1 })
db.surveys.createIndex({ share_slug: 1 }, { unique: true })
db.surveys.createIndex({ status: 1, deadline_at: 1 })
db.surveys.createIndex({ owner_user_id: 1, status: 1 })
```

### Share Slug Uniqueness

`share_slug` should be generated as a sufficiently random URL-safe string. A unique index is still required because random generation can theoretically collide. Creation should retry with a new slug if MongoDB raises duplicate key error.

## Question Model

Questions are embedded inside a survey version in the recommended design. Each question has a stable `question_id` that remains meaningful inside one survey. IDs should not be array indexes, because insertions and reordering would break references from answers and jump rules.

### Common Question Fields

```javascript
{
  question_id: "q_age",
  type: "number_input",
  title: "年龄",
  description: "请输入 0 到 120 之间的整数。",
  required: true,
  order: 3,
  validation: {},
  jump_rules: []
}
```

Common fields:

- `question_id`: stable string ID, unique within a survey version.
- `type`: one of `single_choice`, `multiple_choice`, `text_input`, `number_input`.
- `title`: question text.
- `description`: optional helper text.
- `required`: whether an answer is mandatory.
- `order`: display and default filling order.
- `validation`: type-specific validation object.
- `jump_rules`: configurable jump rules evaluated after the question is answered.

### Single Choice Question

```javascript
{
  question_id: "q_gender",
  type: "single_choice",
  title: "你的性别",
  required: true,
  order: 1,
  options: [
    { option_id: "opt_male", label: "男", order: 1 },
    { option_id: "opt_female", label: "女", order: 2 },
    { option_id: "opt_other", label: "其他", order: 3 }
  ],
  validation: {},
  jump_rules: []
}
```

Answer value:

```javascript
{ question_id: "q_gender", type: "single_choice", value: "opt_male" }
```

Validation:

- If `required` is true, `value` must be present.
- `value` must match one `option_id` in `options`.

Statistics:

- Count each option selection.
- Count total submitted answers for the question.

### Multiple Choice Question

```javascript
{
  question_id: "q_fruits",
  type: "multiple_choice",
  title: "你喜欢的水果",
  required: true,
  order: 2,
  options: [
    { option_id: "opt_apple", label: "苹果", order: 1 },
    { option_id: "opt_banana", label: "香蕉", order: 2 },
    { option_id: "opt_watermelon", label: "西瓜", order: 3 },
    { option_id: "opt_grape", label: "葡萄", order: 4 }
  ],
  validation: {
    min_selected: 2,
    max_selected: 3,
    exact_selected: null
  },
  jump_rules: []
}
```

Answer value:

```javascript
{ question_id: "q_fruits", type: "multiple_choice", value: ["opt_apple", "opt_grape"] }
```

Validation:

- If `required` is true, `value` must contain at least one option.
- Every selected value must match an `option_id`.
- `min_selected` means at least this many options.
- `max_selected` means at most this many options.
- `exact_selected` means exactly this many options. If present, it should take precedence over min/max.
- Duplicate option IDs in one answer should be rejected or normalized before validation.

Statistics:

- Count how many times each option is selected.
- Count total response documents that answered the question.
- The sum of option counts may exceed total responses because one response can select multiple options.

### Text Input Question

```javascript
{
  question_id: "q_comment",
  type: "text_input",
  title: "请写下你的建议",
  required: false,
  order: 4,
  validation: {
    min_length: 0,
    max_length: 500
  },
  jump_rules: []
}
```

Answer value:

```javascript
{ question_id: "q_comment", type: "text_input", value: "希望增加更多开放题。" }
```

Validation:

- If `required` is true, non-empty text is required.
- `min_length` and `max_length` apply to the normalized text length.
- Trimming whitespace before validation should be decided consistently.

Statistics:

- List submitted text contents.
- Count answered and skipped responses.
- Text aggregation beyond listing is optional and not explicitly required.

### Number Input Question

```javascript
{
  question_id: "q_age",
  type: "number_input",
  title: "年龄",
  required: true,
  order: 3,
  validation: {
    min_value: 0,
    max_value: 120,
    integer_only: true
  },
  jump_rules: []
}
```

Answer value:

```javascript
{ question_id: "q_age", type: "number_input", value: 21 }
```

Validation:

- If `required` is true, a numeric value is required.
- `min_value` and `max_value` define inclusive bounds.
- `integer_only` requires the value to be an integer.
- Numeric values should be stored as MongoDB numeric types, not strings.

Statistics:

- Count answered responses.
- Compute average.
- Optional useful metrics: minimum, maximum, and distribution buckets.

## Dynamic Jump Rules

The assignment explicitly requires jump logic for single-choice, multiple-choice, and numeric input answers, and explicitly says it must not be hard-coded in the program. Therefore jump rules should be stored as data inside the survey version.

### Rule Placement

Recommended placement: `question.jump_rules` inside the question that triggers the jump.

Reason:

- Rules are evaluated immediately after a question is answered.
- Rules belong to a specific version of the question.
- Keeping them with the question makes the survey definition easier to load in one query.

### Rule Shape

```javascript
{
  rule_id: "jr_age_adult",
  priority: 1,
  condition: {
    operator: "gte",
    value: 18
  },
  target: {
    type: "question",
    question_id: "q_work_status"
  }
}
```

Target types:

- `question`: jump to another question by `question_id`.
- `end`: finish the survey.
- `next`: continue to the next question. Usually this is the default and does not need an explicit rule.

Evaluation:

- Sort rules by `priority` ascending.
- Evaluate the first matching rule.
- If no rule matches, continue to the next question by `order`.
- Detect cycles during survey validation before publishing.
- Reject rules that target missing questions.

### Operators By Question Type

Single choice:

```javascript
{ operator: "equals", value: "opt_a" }
{ operator: "not_equals", value: "opt_b" }
{ operator: "in", values: ["opt_a", "opt_b"] }
```

Multiple choice:

```javascript
{ operator: "contains_any", values: ["opt_apple", "opt_banana"] }
{ operator: "contains_all", values: ["opt_apple", "opt_grape"] }
{ operator: "selected_count_gte", value: 2 }
{ operator: "selected_count_lte", value: 3 }
```

Number input:

```javascript
{ operator: "lt", value: 18 }
{ operator: "lte", value: 18 }
{ operator: "gt", value: 60 }
{ operator: "gte", value: 18 }
{ operator: "between", min: 18, max: 60 }
{ operator: "equals", value: 0 }
```

Text input jump rules are not explicitly required by the assignment. They should be left out in the first implementation unless a later requirement asks for them.

## Responses Collection

Purpose: store each submitted response independently from the survey definition. This supports concurrent submissions, statistics, and historical audit.

### Example Document

```javascript
{
  _id: ObjectId("..."),
  survey_id: ObjectId("..."),
  survey_owner_user_id: ObjectId("..."),
  survey_version: 1,
  survey_snapshot: {
    title: "Student Learning Survey",
    questions: [
      {
        question_id: "q_gender",
        type: "single_choice",
        title: "你的性别",
        options: [
          { option_id: "opt_male", label: "男", order: 1 },
          { option_id: "opt_female", label: "女", order: 2 },
          { option_id: "opt_other", label: "其他", order: 3 }
        ]
      }
    ]
  },
  respondent_user_id: ObjectId("..."),
  is_anonymous_to_owner: true,
  anonymous_identity_key: "hash-of-user-and-survey",
  submission_key: "survey-user-or-client-key",
  status: "submitted",
  started_at: ISODate("2026-10-16T02:15:00Z"),
  submitted_at: ISODate("2026-10-16T02:18:00Z"),
  answers: [
    {
      question_id: "q_gender",
      type: "single_choice",
      value: "opt_male",
      answered_at: ISODate("2026-10-16T02:16:00Z")
    },
    {
      question_id: "q_age",
      type: "number_input",
      value: 21,
      answered_at: ISODate("2026-10-16T02:17:00Z")
    }
  ]
}
```

### Field Notes

- `survey_id`: references `surveys._id`.
- `survey_owner_user_id`: duplicated from the survey to speed owner statistics queries and permission checks. This is controlled redundancy.
- `survey_version`: version used when the response was submitted.
- `survey_snapshot`: optional but recommended for preserving historical interpretation. It can be a compact snapshot containing only title, question text, option labels, type, order, and validation/jump metadata needed for reports.
- `respondent_user_id`: references `users._id`. In the confirmed first-stage policy, fillers must log in, so this internal field is required for submitted responses.
- `is_anonymous_to_owner`: if true, owner-facing views hide `respondent_user_id`. This is login-required anonymity, not complete system anonymity.
- `anonymous_identity_key`: optional hashed value for enforcing duplicate prevention without revealing identity to the owner.
- `submission_key`: deterministic key used for duplicate submission control.
- `status`: `submitted` for saved final submissions. Draft/in-progress responses can be added later if needed.
- `answers`: embedded answer list because answers are normally read together as one response.

### Response Indexes

```javascript
db.responses.createIndex({ survey_id: 1, submitted_at: -1 })
db.responses.createIndex({ survey_id: 1, survey_version: 1 })
db.responses.createIndex({ survey_owner_user_id: 1, submitted_at: -1 })
db.responses.createIndex({ respondent_user_id: 1, survey_id: 1 })
db.responses.createIndex(
  { survey_id: 1, submission_key: 1 },
  { unique: true, partialFilterExpression: { submission_key: { $exists: true } } }
)
db.responses.createIndex({ survey_id: 1, "answers.question_id": 1 })
```

### Anonymous Response Boundary

Internal response data may include:

- `respondent_user_id`
- `submission_key`
- `anonymous_identity_key`
- operational metadata needed for validation and duplicate prevention

Owner-facing anonymous response data may include:

- response ID
- survey ID and survey version
- submitted time
- answer values
- derived statistics
- an anonymous display label such as `anonymous_001` if needed

Owner-facing anonymous response data must not include:

- `respondent_user_id`
- username
- login identifier
- raw `submission_key`
- raw `anonymous_identity_key`

The service layer should expose a permission-controlled response view instead of returning raw response documents directly. Admin or audit tooling, if added later, must be treated as a separate privilege boundary.

### Duplicate Submission Control

If `allow_multiple_submissions` is false:

- For logged-in fillers, derive `submission_key` from `survey_id` and `respondent_user_id`.
- For anonymous-but-login-required fillers, still derive `submission_key` from the authenticated user but hide identity in owner-facing output.

The unique index on `{ survey_id, submission_key }` provides database-level protection under concurrent submissions. Application code should still give a friendly validation error.

If `allow_multiple_submissions` is true, the system should omit `submission_key` from the unique index scope or include a per-submission nonce so multiple responses from the same user are allowed. This setting is independent from `allow_anonymous`; anonymity does not automatically imply repeated submissions.

### Concurrent Submission Considerations

- Each submitted response is inserted as a new document, which is naturally safe for multiple simultaneous fillers.
- Duplicate prevention must rely on a unique index, not only on a "check then insert" application flow.
- If two requests from the same filler submit at nearly the same time while repeated submissions are disabled, one insert succeeds and the other receives a duplicate-key error from MongoDB. The service layer should translate that database error into a clear business error such as "this survey has already been submitted by this account".
- Response insertion should be designed as an idempotent finalization step where possible. If the client retries after a timeout, the service should detect the existing submission and avoid creating a second answer set.
- If response submission also updates cached statistics in the future, use MongoDB transactions or idempotent update patterns to avoid double counting.

## Statistics Design

The first implementation should compute statistics from `responses` using MongoDB aggregation. Cached statistics can be added later after measuring performance.

### Single Choice

Source: `responses.answers` entries where `type` is `single_choice`.

Required output:

- Option ID and label from the matching survey version or response snapshot.
- Count per option.
- Total number of submitted responses that answered the question.

### Multiple Choice

Source: `responses.answers` entries where `type` is `multiple_choice`.

Required output:

- Count per selected option.
- Total number of submitted responses that answered the question.
- Clarify in reports that option counts can sum to more than the total response count.

### Text Input

Source: `responses.answers` entries where `type` is `text_input`.

Required output:

- List submitted text values.
- Count answered responses.

Privacy note: if responses are anonymous, statistics output should not include respondent identity.

### Number Input

Source: `responses.answers` entries where `type` is `number_input`.

Required output:

- Average numeric value.
- Count answered responses.

Recommended extra output:

- Minimum and maximum values.

### Whole Survey And Per-Question Statistics

- Whole-survey statistics can aggregate response count, submitted count by version, and completion metadata.
- Per-question statistics should filter by `survey_id`, `survey_version` if needed, and `question_id`.
- When a survey has multiple published versions, the report must decide whether to aggregate all versions together or show per-version results. Per-version reporting is safer because option labels and question wording may change.

## Embedded Questions Vs Independent Questions Collection

The assignment specifically asks for MongoDB design and warns against both one-collection design and careless hard-coding. The main modeling choice is whether questions should be embedded in `surveys` or stored in a separate `questions` collection.

### Option A: Embed Questions In `surveys`

Shape:

```javascript
{
  _id: ObjectId("..."),
  title: "...",
  versions: [
    {
      version: 1,
      questions: [ /* question documents */ ]
    }
  ]
}
```

Advantages:

- Loading a survey for filling usually needs survey metadata, ordered questions, options, validation rules, and jump rules together. Embedding supports this with one query.
- Jump rules can reference nearby question IDs inside the same version.
- Publishing can snapshot the entire questionnaire definition atomically inside the survey document.
- This matches MongoDB document modeling when a parent document owns bounded child records.
- It is easy to explain why MongoDB is suitable: a survey is naturally a nested document with heterogeneous question types.

Disadvantages:

- A very large survey could approach MongoDB document size limits, though this is unlikely for a course project unless surveys contain hundreds or thousands of questions.
- Editing one question rewrites part of the survey document.
- Querying all questions across all surveys is less convenient.
- Fine-grained question-level permissions are harder, though not required by the assignment.

### Option B: Store Questions In A Separate `questions` Collection

Shape:

```javascript
// surveys
{
  _id: ObjectId("..."),
  title: "...",
  published_version: 1
}

// questions
{
  _id: ObjectId("..."),
  survey_id: ObjectId("..."),
  version: 1,
  question_id: "q_age",
  type: "number_input",
  order: 3,
  validation: { integer_only: true }
}
```

Advantages:

- Large surveys are not constrained by one survey document.
- Updating or reordering one question can be more targeted.
- Cross-survey question analysis is easier.
- Per-question indexes can be added if the application frequently searches questions globally.

Disadvantages:

- Loading a survey requires multiple queries or aggregation.
- Publishing a consistent survey definition becomes more complex.
- Jump rule validation must coordinate records across documents.
- Historical versioning becomes more complex because questions and options must be snapshotted or versioned separately.
- This is more normalization than the current requirements justify.

### Recommended Choice

Use embedded questions inside versioned `surveys` for the first implementation.

Reasoning:

- The common read path is "open one survey and answer it", which needs the whole definition.
- The assignment values MongoDB design and configurable logic; embedded versioned survey documents demonstrate that well.
- The current project is a course system, not a large multi-tenant survey platform with massive surveys.
- Keeping questions and jump rules together reduces risk in the first stage.

Keep the design migration-friendly by using stable `question_id` values and `survey_version`. If later requirements introduce huge surveys, reusable question banks, or cross-survey analytics, `questions` can be extracted into its own collection without changing the response model too much.

### Document Growth And Size Limit

MongoDB documents have a BSON document size limit, so the `versions` array must not be treated as infinitely expandable. This design is acceptable for the first course stage because typical questionnaire definitions are bounded and responses are stored separately. It still needs guardrails:

- Limit the number of retained editable draft versions, or keep only meaningful published versions plus the current draft.
- Reject or redesign extremely large surveys before they approach document size limits.
- Do not embed responses in the survey document.
- If a future stage requires very large surveys, reusable question banks, or long version history, move version definitions or questions into separate collections such as `survey_versions` or `questions`.
- If versions are moved out later, keep the response contract stable by preserving `survey_id`, `survey_version`, and stable `question_id`/`option_id` values.

## Survey Modification And Historical Responses

Problem: if a survey owner edits question text, options, order, validation, or jump rules after responses exist, old responses may become hard to interpret.

Recommended policy:

- Draft surveys can be edited freely before publishing.
- Publishing creates an immutable survey version.
- If a published survey is edited, create a new version instead of mutating the old published version.
- Responses store `survey_version`.
- Responses also store a compact `survey_snapshot`, or the system keeps immutable historical versions inside `surveys.versions`.
- Statistics default to the selected version. Cross-version statistics must be explicitly requested and must handle changed option IDs or labels carefully.

Tradeoff:

- Storing snapshots increases data size, but it protects report correctness and supports the assignment's second-stage requirement that old data and old functions must remain usable.
- Keeping only a version reference saves space, but it requires never deleting or mutating historical versions. This is acceptable if the application strictly enforces immutability.

Recommended first-stage compromise:

- Keep immutable historical definitions in `surveys.versions`.
- Store `survey_version` in every response.
- Store a compact `survey_snapshot` in every response only if reports need to remain valid even when survey history cleanup is later introduced. For the course project, including the compact snapshot is safer and easier to explain.

## Data Consistency Rules

### Survey Publishing Validation

Before setting `status` to `published`, validate:

- Survey has a non-empty title.
- Survey has at least one question.
- `share_slug` is unique.
- Every question has a unique `question_id` within the version.
- Options have unique `option_id` values within each choice question.
- Required validation fields are valid for the question type.
- Jump rule targets exist.
- Jump rules do not create unreachable required questions unless that is intentional.
- Jump rules do not create cycles that can trap a filler forever.

### Response Submission Validation

At submission time:

- Survey exists and is `published`.
- Deadline has not passed and survey is not closed.
- Submitted `survey_version` matches the currently fillable version, unless the product intentionally allows completing an already-started older version.
- Answers match question IDs and types in the selected version.
- Required questions on the actual path are answered.
- Choice answers reference existing options.
- Text and numeric answers satisfy validation.
- Jump path is recomputed from submitted answers so clients cannot skip required questions by forging payloads.
- Duplicate submission policy is enforced with the unique response index.

### References And Deletion

- Users should not be physically deleted if they own surveys. Prefer `status: "deleted"` or anonymization.
- Surveys with responses should not be physically deleted in the first implementation. Prefer `archived` status.
- Historical survey versions referenced by responses must not be removed.

## Why MongoDB Fits This Project

### Reasons

- A survey definition is naturally hierarchical: survey -> questions -> options -> validation rules -> jump rules.
- Question documents are heterogeneous. Single choice, multiple choice, text input, and numeric input share common fields but have different validation and answer shapes.
- Jump rules are configurable data structures. MongoDB documents can store nested rule objects without forcing many join tables.
- Responses are also document-shaped: one submission contains a list of answers captured at a point in time.
- Versioned survey definitions and answer snapshots are easier to model as nested documents than as many relational tables for a course-scale project.

### Why Not A Relational Structure

The assignment explicitly forbids relational databases, so the system must not use one. Even aside from that rule, a relational design would require many tables such as users, surveys, questions, options, rules, rule conditions, responses, and answers. That can be precise, but it adds joins and schema churn for heterogeneous question types and evolving rules.

### Advantages Of This MongoDB Design

- One query can load the published survey definition for filling.
- Configurable validation and jump rules live with the survey version.
- Responses are independent documents, which supports concurrent submissions.
- Historical versions preserve interpretation of old answers.
- Indexes cover ownership, sharing, response lookup, and duplicate control.

### Disadvantages And Risks

- Embedded survey versions can make the `surveys` document grow over time.
- Reporting across versions is more complex when questions or options change.
- Application-level validation is still essential; MongoDB alone will not enforce all business rules.
- Some redundancy exists, such as `survey_owner_user_id` and optional response snapshots.
- If surveys become very large, questions may need to move to a separate collection later.

## Index Reference

```javascript
// users
db.users.createIndex({ username_normalized: 1 }, { unique: true })

// surveys
db.surveys.createIndex({ owner_user_id: 1, updated_at: -1 })
db.surveys.createIndex({ share_slug: 1 }, { unique: true })
db.surveys.createIndex({ status: 1, deadline_at: 1 })
db.surveys.createIndex({ owner_user_id: 1, status: 1 })

// responses
db.responses.createIndex({ survey_id: 1, submitted_at: -1 })
db.responses.createIndex({ survey_id: 1, survey_version: 1 })
db.responses.createIndex({ survey_owner_user_id: 1, submitted_at: -1 })
db.responses.createIndex({ respondent_user_id: 1, survey_id: 1 })
db.responses.createIndex(
  { survey_id: 1, submission_key: 1 },
  { unique: true, partialFilterExpression: { submission_key: { $exists: true } } }
)
db.responses.createIndex({ survey_id: 1, "answers.question_id": 1 })
```

## Summary Of Design Decisions

- Use five collections: `users`, `surveys`, `responses`, `question_items`, and `question_versions`.
- Do not use one giant collection.
- Embed questions, options, validation rules, and jump rules inside versioned survey documents.
- Store responses separately because they grow independently and are queried for statistics.
- Use stable string IDs for questions and options instead of relying on array positions.
- Use unique `share_slug` for survey URLs.
- Store password hashes only, with algorithm metadata.
- Use immutable survey versions to preserve historical response meaning.
- Use database indexes for uniqueness, ownership queries, share lookup, statistics lookup, and duplicate submission protection.

## Phase-Two Question Collections

### `question_items`

Each document represents a stable library item. The implemented fields are `_id`, `owner_user_id`, `display_title`, `is_shared`, `current_version_id`, `latest_version_number`, `derived_from_item_id`, `derived_from_version_id`, `created_at`, and `updated_at`. The current version pointer is updated only after a new immutable version is inserted.

Indexes:

```javascript
db.question_items.createIndex({ owner_user_id: 1, updated_at: -1 })
db.question_items.createIndex({ is_shared: 1, updated_at: -1 })
```

### `question_versions`

Each document stores `_id`, `question_item_id`, `version_number`, `content`, `created_by_user_id`, `created_at`, `based_on_version_id`, and `restored_from_version_id`. `content` retains the first-stage question shape, including question type, title, description, required flag, options, validation, and jump rules. Versions are append-only through the application API. Restoring a version copies its content into a newly numbered version.

Indexes:

```javascript
db.question_versions.createIndex(
  { question_item_id: 1, version_number: 1 },
  { unique: true }
)
db.question_versions.createIndex({ question_item_id: 1, created_at: -1 })
```

### Source IDs And Snapshot Isolation

When a library version is added to a survey, the service deep-copies its content, generates a survey-local question ID, and stores `source_question_item_id` and `source_question_version_id` on that embedded question. Submitted responses copy those questions into `survey_snapshot.questions`. Usage lookup and cross-survey statistics use these source identifiers; statistics match the exact version ID. Ordinary survey creation strips client-supplied source IDs. Ordinary PATCH retains source metadata only for questions unchanged from the server-held snapshot and removes it when question content changes. Existing records are not migrated or assigned guessed source IDs.

The `responses` collection has an index on `survey_snapshot.questions.source_question_version_id` and `submitted_at` for version-based lookup. The current service still scans submitted responses for aggregation, so this index does not imply that all statistics queries use an indexed MongoDB filter.

## First-Stage Scope

The current implementation uses on-demand statistics, stores final submissions only, and keeps version snapshots. The following remain outside this stage: start_question_id, progress sessions, raw response export, and a default cross-version merge policy.
