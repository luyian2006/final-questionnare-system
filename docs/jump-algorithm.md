# 跳转算法说明

This document records the implemented pure-Python jump and submission-path rules. It is independent from HTTP routing and MongoDB and accepts plain question and answer dictionaries.

## Scope and Decisions

Course requirement:

- A survey can jump to different questions based on answers.
- Jump rules must support single-choice answers, multiple-choice answers, and numeric fill-in answers.
- Jump rules must be configurable in survey data and must not be hard-coded in program logic.
- Filling should follow order, apply jump rules, validate answers, and save the final submission.

- Rules on the same question are evaluated by ascending `priority`.
- Each jump rule on the same question must have a unique numeric `priority`.
- The first matching rule is executed.
- If no rule matches, go to the next question in survey order.
- If there is no next question, end filling.
- Version 1 forbids jump cycles.
- Publishing validates targets and cycles.
- Runtime traversal also uses a maximum jump-step limit as a defensive guard.
- The algorithm is separated from database access and HTTP routes.

## Navigation vs. Submission Validation

The algorithm supports two different operations. They share the same published survey definition and answer validation rules, but they have different strictness because they serve different moments in the user flow.

Navigation is used while the filler is answering. It answers one question: after the current question, where should the UI go next?

- Navigation accepts a missing current answer and returns `action: "awaiting_answer"`.
- Navigation does not execute jump rules when the current answer is missing.
- Navigation still rejects an answer that is present but has invalid format or invalid content.
- Navigation does not prove that the final submission is complete.

Submission validation is used when the filler submits the whole response. It verifies the complete submitted result.

- Submission validation uses the server-side published survey version.
- It starts from the first question and recomputes the actual path from submitted answers.
- It strictly validates every question on the actual path.
- It fails when a required question on the actual path has no answer.
- If an optional question on the actual path has no answer, no condition rule on that question can be evaluated, so traversal follows the default order. If it is the last question, traversal ends.
- If an answer is provided, that answer must be validated before any jump rule is evaluated.
- It accepts required questions that were legitimately skipped by jump rules.
- It rejects unknown questions, type mismatches, forged paths, and answers outside the actual path.

These behaviors are not contradictory: navigation can wait for the user to answer, while final submission must decide whether a full response can be saved.

## Inputs

`survey_version`:

```javascript
{
  version: 1,
  questions: [
    {
      question_id: "q1",
      type: "single_choice",
      order: 1,
      required: true,
      options: [
        { option_id: "a", label: "A", order: 1 },
        { option_id: "b", label: "B", order: 2 }
      ],
      validation: {},
      jump_rules: [
        {
          rule_id: "r1",
          priority: 10,
          condition: { operator: "equals", value: "a" },
          target: { type: "question", question_id: "q3" }
        }
      ]
    }
  ]
}
```

`answers_by_question_id`:

```javascript
{
  q1: { question_id: "q1", type: "single_choice", value: "a" },
  q3: { question_id: "q3", type: "number_input", value: 20 }
}
```

Optional runtime parameters:

- `current_question_id`: required for navigation.
- `start_question_id`: documented as a possible parameter, but not implemented in the first-stage API; traversal starts at the smallest `order`.
- `max_jump_steps`: used by submission validation. Default recommendation is `questions.length + number_of_jump_rules + 1`, with an absolute minimum of `questions.length + 1`.
- `mode`: either `navigation` or `submission_validation`.

## Outputs

For navigation when the current question has no answer yet:

```javascript
{
  action: "awaiting_answer",
  question_id: "q1",
  matched_rule_id: null
}
```

For navigation after a valid current answer:

```javascript
{
  action: "goto_question",
  question_id: "q3",
  matched_rule_id: "r1"
}
```

or:

```javascript
{
  action: "end",
  matched_rule_id: null
}
```

For navigation when the current answer is present but invalid:

```javascript
{
  action: "error",
  code: "invalid_answer",
  question_id: "q1",
  message: "single-choice answer must reference a defined option_id"
}
```

For validating a completed submission:

```javascript
{
  valid: true,
  path: ["q1", "q3", "q5"],
  skipped_required_questions: ["q2"],
  errors: []
}
```

If invalid:

```javascript
{
  valid: false,
  path: ["q1", "q3"],
  errors: [
    {
      code: "invalid_answer",
      question_id: "q3",
      message: "number must be greater than or equal to 18"
    }
  ]
}
```

## Preconditions

Before runtime navigation or submission validation:

- The survey version contains at least one question.
- Questions are sorted by `order`.
- Every `question_id` is unique inside the survey version.
- Every `order` value is unique inside the survey version.
- Every choice question option has unique `option_id` values.
- Every jump target points to an existing question or to `end`.
- Rule priorities are numeric.
- Rule priorities are unique within the same question.
- The published survey version has passed the conservative cycle check described below.
- The caller supplies authenticated user context outside this algorithm. Authentication and permission checks are not part of this algorithm.
- Publishing validation has already checked configuration errors such as duplicate IDs, invalid targets, unsupported operators, invalid condition values, and possible cycles.

## Answer Validation By Type

### Single Choice

Answer shape:

```javascript
{ question_id: "q1", type: "single_choice", value: "a" }
```

Validation:

- Required question: `value` must be present.
- `value` must equal exactly one known `option_id`.
- `value` must be a scalar option ID, not an array or object.
- Arrays and strings that do not match a defined option ID are invalid.
- Unknown option IDs fail with `invalid_answer_option`.

### Multiple Choice

Answer shape:

```javascript
{ question_id: "q2", type: "multiple_choice", value: ["apple", "grape"] }
```

Validation:

- Required question: `value` must contain at least one option.
- `value` must be an array of unique option IDs.
- Every option ID must exist in the question definition.
- Duplicate option IDs fail with `duplicate_answer_option`.
- Unknown option IDs fail with `invalid_answer_option`.
- `min_selected` is inclusive.
- `max_selected` is inclusive.
- `exact_selected`, when configured, means the count must be exactly that number and takes precedence over min/max count.

### Number Input

Answer shape:

```javascript
{ question_id: "q3", type: "number_input", value: 18 }
```

Validation:

- Required question: a numeric value must be present.
- The value must be stored and evaluated as a number, not a string.
- The value must be finite.
- Boolean values are not numbers for this algorithm and must be rejected.
- `NaN`, positive infinity, and negative infinity must be rejected.
- `min_value` is inclusive.
- `max_value` is inclusive.
- `integer_only: true` rejects decimals.

Runtime answer validation errors should be specific where possible:

- `missing_required_answer` for a required question on the actual submission path with no answer.
- `invalid_answer_type` for mismatched answer type.
- `invalid_answer` for malformed values.
- `invalid_answer_option` for unknown choice option IDs.
- `duplicate_answer_option` for repeated multiple-choice option IDs.
- `number_not_finite` for numeric values that are `NaN` or infinite.

Text input answers are validated by the response submission service but are not supported as jump-rule sources in version 1 because the course requirement only names single choice, multiple choice, and numeric input for jump behavior.

Implementation boundary:

- Text input requiredness, length, and value-format constraints belong to the answer validation module used during submission.
- Text input questions are not valid sources for first-version jump rules.
- The jump algorithm should only evaluate jump rules after the current answer has already passed type-specific validation.
- The jump algorithm determines the next step; it should not become the only place where all answer constraints are defined.

## Condition Operators

### Single Choice Operators

`equals`:

```javascript
{ operator: "equals", value: "a" }
```

Matches when selected option ID is exactly `a`.

`not_equals`:

```javascript
{ operator: "not_equals", value: "b" }
```

Matches when selected option ID is present and not `b`.

`in`:

```javascript
{ operator: "in", values: ["a", "b"] }
```

Matches when selected option ID is one of the listed option IDs.

Publishing validation:

- `equals` and `not_equals` must reference one defined option ID.
- `in.values` must be a non-empty array.
- Every value in `in.values` must reference a defined option ID.

### Multiple Choice Operators

The meaning of each multiple-choice operator is explicit and must not be mixed:

`contains_any`:

```javascript
{ operator: "contains_any", values: ["apple", "banana"] }
```

Matches when the selected set contains at least one listed option.

`contains_all`:

```javascript
{ operator: "contains_all", values: ["apple", "grape"] }
```

Matches when the selected set contains every listed option. Extra selected options are allowed.

`equals_set`:

```javascript
{ operator: "equals_set", values: ["apple", "grape"] }
```

Matches when the selected set is exactly the listed set, ignoring order. No extra or missing options are allowed.

Publishing validation for `contains_any`, `contains_all`, and `equals_set`:

- `values` must be a non-empty array.
- Every item in `values` must reference a defined option ID on the source question.
- Duplicate IDs in `values` are invalid.
- `contains_any` means at least one listed option is selected.
- `contains_all` means every listed option is selected, while extra selected options are allowed.
- `equals_set` ignores order but requires exactly the same set. Missing or extra options do not match.

`selected_count_eq`:

```javascript
{ operator: "selected_count_eq", value: 2 }
```

Matches when exactly two options are selected.

`selected_count_gte`:

```javascript
{ operator: "selected_count_gte", value: 2 }
```

Matches when the selected count is greater than or equal to two.

`selected_count_lte`:

```javascript
{ operator: "selected_count_lte", value: 3 }
```

Matches when the selected count is less than or equal to three.

Publishing validation for count operators:

- `selected_count_eq`, `selected_count_gte`, and `selected_count_lte` must contain one non-negative integer `value`.
- Boolean values, decimals, `NaN`, and infinity are invalid count values.

### Number Input Operators

All numeric comparisons use inclusive or exclusive boundaries exactly as the operator name says.

`lt`: value < configured value.

`lte`: value <= configured value.

`gt`: value > configured value.

`gte`: value >= configured value.

`equals`: value == configured value.

`between`:

```javascript
{ operator: "between", min: 18, max: 60 }
```

Matches when `min <= value <= max`. Both boundaries are inclusive.

Publishing validation:

- `lt`, `lte`, `gt`, `gte`, and `equals` must contain one finite numeric `value`.
- `between` must contain finite numeric `min` and `max`.
- `between` requires `min <= max`.
- Boolean values, `NaN`, positive infinity, and negative infinity are invalid numeric boundaries.
- Operators must match the source question type. For example, `contains_all` is invalid on a number question, and `gte` is invalid on a single-choice question.

## Rule Target Types

`question`:

```javascript
{ type: "question", question_id: "q5" }
```

Jump to the target question.

`end`:

```javascript
{ type: "end" }
```

End the answer flow.

`next` should not normally be stored. It is the implicit default when no rule matches.

## Traversal Rules

Navigation sorts questions by `order`, locates the current question, and returns `awaiting_answer` when its answer is absent. For a present answer it validates the answer, checks rules by ascending `priority`, returns the first matching question or `end` target, or follows the default next question. Invalid definitions or answers return structured errors.

Submission validation first rejects unknown answer IDs, then starts at the smallest `order`. It validates each visited answer, requires answers only for visited required questions, applies the same first-match rule logic, records the path, and rejects answers outside that path. It stops on `end`, a repeated question, an unknown target, or `max_jump_steps`.

## Default Order

Default order means the sorted `questions` array by `order`. If two questions have the same `order`, publishing must reject the survey version with `duplicate_question_order`. Runtime should not guess between equal order values.

## Publishing-Time Validation

Publishing validation checks survey configuration, not a user's submitted answer. It should run before a version can become published. It should reject a survey version when:

- The survey version has no questions: `empty_survey`.
- A question ID is missing: `missing_question_id`.
- A question ID is duplicated: `duplicate_question_id`.
- Any question order is missing, non-numeric, or duplicated: `duplicate_question_order` or `invalid_question_order`.
- A choice option ID is missing inside a question: `missing_option_id`.
- A choice option ID is duplicated inside a question: `duplicate_option_id`.
- A jump rule has a missing or non-numeric priority: `invalid_rule_priority`.
- Two rules on the same question use the same priority: `duplicate_rule_priority`.
- A jump rule references a missing target question: `invalid_jump_target`.
- A jump rule uses an operator unsupported by the source question type: `unsupported_operator_for_question_type`.
- A single-choice rule condition references an unknown option ID: `invalid_condition_option`.
- A multiple-choice set condition has an empty `values` array: `empty_condition_values`.
- A multiple-choice set condition references an unknown option ID: `invalid_condition_option`.
- A multiple-choice count condition has an invalid count value: `invalid_count_condition`.
- A numeric rule contains non-finite boundaries: `invalid_numeric_boundary`.
- A `between` rule has `min > max`: `invalid_numeric_range`.
- A rule target has an invalid type: `invalid_target_type`.
- The conservative cycle check detects a possible loop: `jump_cycle_detected`.

Publishing validation should run in this order:

1. Validate that the survey version has at least one question.
2. Validate that every question has a `question_id`.
3. Validate unique question IDs.
4. Validate unique question order.
5. Validate that every option in each choice question has an `option_id`.
6. Validate unique option IDs for choice questions.
7. Validate rule priority, condition, operator, and target configuration.
8. Run conservative cycle detection only after IDs, order values, and targets are known to be valid.

### Conservative Cycle Detection

Conditional jump rules create a graph whose edges may or may not be active depending on answers. A plain directed graph cycle check can over-approximate possible cycles because it ignores mutually exclusive conditions, but that conservative behavior is acceptable for version 1.

Recommended version 1 check:

1. Create one node for every question.
2. Add a default edge from each question to the next question by order, except the last question which points to `end`.
3. Add an edge for every jump rule with target `question`.
4. Ignore rule conditions for cycle detection.
5. If any cycle exists in this over-approximated graph, reject publication.

`end` is not a question node. Edges that point to `end` terminate traversal and do not participate in question-to-question cycles.

Cycle-detection pseudocode:

```text
function validate_no_cycles(survey_version):
    questions = sort survey_version.questions by order ascending
    graph = empty adjacency map

    for each question in questions:
        graph[question.question_id] = empty list

    for each question in questions:
        next_question = first question after question in sorted order
        if next_question exists:
            graph[question.question_id].append(next_question.question_id)

        for each rule in question.jump_rules:
            if rule.target.type == "question":
                graph[question.question_id].append(rule.target.question_id)

    if directed graph has a cycle:
        return error("jump_cycle_detected")

    return ok
```

Examples:

```text
Q1 --> Q2 --> Q3 --> end
 \             ^
  \----------/
```

This is a normal forward jump from `Q1` to `Q3`. The graph has no path from `Q3` back to `Q1` or `Q2`, so it is not a cycle.

```text
Q1 --> Q2 --> Q3 --> end
^             |
|-------------|
```

This graph has a cycle: `Q1 -> Q2 -> Q3 -> Q1`. If `Q3` has a jump rule targeting `Q1`, publication fails with `jump_cycle_detected`.

```text
Q1 --> Q2 --> Q3 --> end
^      |
|------|
```

Even if the rule `Q2 -> Q1` and the default path `Q1 -> Q2` depend on mutually exclusive answer conditions, version 1 ignores conditions and still rejects the survey. This is the accepted conservative tradeoff.

Tradeoff:

- This can reject a survey whose conditions make the cycle impossible in practice.
- It is safer and easier to explain for the first version.
- A later version can implement path-sensitive analysis for mutually exclusive conditions if the product needs more flexible jumps.

## Runtime Traversal And Max Steps

When validating a complete submission, runtime should traverse from the first question and repeatedly apply the submission validation traversal described above. It should not call the navigation operation in a way that treats missing answers as `awaiting_answer`; a missing required answer on the actual path is a submission error.

Runtime safeguards:

- Keep `visited_path` for diagnostics.
- Count steps.
- Stop with an error if `steps > max_jump_steps`.
- Stop with an error if a target question does not exist. This should not happen after publishing validation, but runtime must defend against corrupted data.
- Stop with an error if an answer is missing for a required question that is actually visited.
- Stop with an error if a traversal result is neither `goto_question` nor `end`.

Runtime max-step error:

```javascript
{
  valid: false,
  errors: [
    {
      code: "max_jump_steps_exceeded",
      message: "jump traversal exceeded the configured safety limit"
    }
  ]
}
```

## Validating The Actual Answer Path

Submission validation should not trust the client-provided path. The server should recompute the path:

1. Start at the first question by `order`.
2. For each visited question, validate the submitted answer against the question definition.
3. If the visited question is required and the answer is missing, reject with `missing_required_answer`.
4. If the visited question is optional and the answer is missing, follow the default order because no jump condition can be evaluated.
5. If the answer is present but invalid, reject with the appropriate runtime validation error.
6. Resolve the next step from the server-side survey definition and submitted answer.
7. Continue until `end`.
8. Build the server-authoritative path.
9. Reject submitted answers for unknown question IDs with `unknown_answer_question`.
10. Reject answers whose type does not match the question definition with `invalid_answer_type`.
11. Reject answers for questions outside the authoritative path with `answer_not_on_path`.
12. Reject client-provided path, next question ID, or matched rule result if it conflicts with the server-computed path, using `client_path_mismatch` where a client path is explicitly supplied.

Navigation allows the current answer to be temporarily missing; final submission validation does not allow missing required answers on the actual path. These are different operations.

## Required Questions That Are Legitimately Skipped

A required question is required only if it is on the server-authoritative answer path. If a valid jump skips a required question, that skipped question does not need an answer.

Example:

- `q1` jumps to `q3`.
- `q2` is required but is not on the computed path.
- The submission may be valid without an answer to `q2`.

This must be documented in validation logic and tests, otherwise required validation can conflict with jump logic.

## Client Forgery Protection

The server must protect against forged client data:

- Do not accept client-provided next question as authoritative.
- Do not accept client-provided jump rule results as authoritative.
- Do not accept client-provided path as authoritative.
- Use only the server-side published survey version for validation.
- Reject unknown `question_id` values.
- Reject unknown `option_id` values.
- Reject type mismatches.
- Recompute the full path on submit.
- Enforce required, selection-count, length, and numeric validation server-side.
- Enforce duplicate submission policy using the database unique index, not the client.

## Test Cases

1. Single-choice normal match:
   - `q1` single choice answer is `a`.
   - Rule `equals a -> q3` matches.
   - Navigation returns `goto_question q3`.

2. Priority first match:
   - `q1` has two matching rules.
   - Rule `priority 1 -> q2`; rule `priority 2 -> q3`.
   - Navigation returns `goto_question q2`.

3. No rule matches:
   - `q1` answer is `b`.
   - Only rule is `equals a -> q3`.
   - Navigation returns the next question by `order`.

4. Last question no match:
   - Current question is the last question.
   - No rule matches.
   - Navigation returns `end`.

5. Explicit end target:
   - `q1` answer matches rule `equals a -> end`.
   - Navigation returns `end` with matched rule ID.

6. Illegal target:
   - Rule targets `q_missing`.
   - Publishing validation fails with `invalid_jump_target`.

7. Normal forward jump is not a cycle:
   - Default order is `Q1 -> Q2 -> Q3 -> end`.
   - `Q1` has a rule to `Q3`.
   - The approximate graph has edges `Q1 -> Q2`, `Q2 -> Q3`, and `Q1 -> Q3`.
   - Publishing cycle validation passes.

8. Back jump forms a cycle:
   - Default order is `Q1 -> Q2 -> Q3 -> end`.
   - `Q3` has a rule to `Q1`.
   - The approximate graph has a cycle `Q1 -> Q2 -> Q3 -> Q1`.
   - Publishing validation fails with `jump_cycle_detected`.

9. Mutually exclusive conditions still rejected by conservative graph:
   - Default order includes `Q1 -> Q2`.
   - `Q2` has a conditional rule back to `Q1`.
   - Product analysis suggests the rule may be unreachable because of mutually exclusive answers.
   - Version 1 ignores conditions for cycle detection and rejects publication with `jump_cycle_detected`.

10. Duplicate priority:
    - `q1` has two rules with `priority: 1`.
    - Publishing validation fails with `duplicate_rule_priority`.
    - Runtime has no `rule_id` tie-breaker because this version cannot be published.

11. Navigation awaiting answer:
    - Current question is `q1`.
    - `answers_by_question_id` has no `q1` answer.
    - Navigation returns `action: "awaiting_answer"`.
    - It does not return `invalid_answer`.

12. Navigation invalid current answer:
   - Single-choice answer value is `unknown_option`.
   - Navigation returns `invalid_answer`.
   - No jump rule is executed.

13. Required question skipped by valid jump:
    - `q1` validly jumps to `q3`.
    - `q2` is required but not on the actual path.
    - Final submission is valid without `q2`.

14. Required question on path is missing:
    - Actual path is `q1 -> q2 -> end`.
    - `q2` is required.
    - Submitted answers do not include `q2`.
    - Final submission fails with `missing_required_answer`.

15. Client-forged extra answer:
    - Authoritative path is `q1 -> q3 -> end`.
    - Client also submits answer for `q2`, or submits a path claiming `q1 -> q2 -> q3`.
    - Final submission rejects the response with `answer_not_on_path` or `client_path_mismatch`.

16. Multiple-choice `contains_all` versus `equals_set`:
    - Answer is `["apple", "grape", "banana"]`.
    - Rule `contains_all ["apple", "grape"]` matches.
    - Extra `banana` does not prevent a match.
    - Answer is `["grape", "apple"]`.
    - Rule `equals_set ["apple", "grape"]` matches.
    - Answer `["apple", "grape", "banana"]` does not match.

17. Numeric boundary:
    - Answer is `18`.
    - Rule `gte 18` matches.
    - Rule `gt 18` does not match.
    - Rule `between min 18 max 60` matches.
    - Rule `lt 18` does not match.

18. Max traversal steps exceeded:
    - Runtime traversal exceeds `max_jump_steps` because of corrupted data or an unexpected loop.
    - Final submission fails with `max_jump_steps_exceeded`.

19. Empty multiple-choice condition values:
    - A `contains_any`, `contains_all`, or `equals_set` rule has `values: []`.
    - Publishing validation fails with `empty_condition_values`.

20. Duplicate multiple-choice answer option:
    - Submitted answer is `["apple", "apple"]`.
    - Runtime answer validation fails with `duplicate_answer_option`.

21. Empty survey version:
    - `questions` is an empty array.
    - Publishing validation fails with `empty_survey`.
    - Submission validation also returns `empty_survey` rather than accepting an empty path as successful.

22. Optional question missing answer uses default order:
    - Actual path reaches optional `q2`.
    - `q2` has a jump rule that would match only if an answer existed.
    - Submitted answers do not include `q2`.
    - Submission validation does not evaluate `q2` jump rules and moves to the next question by default order.

23. Optional last question missing answer ends:
    - Actual path reaches optional `q_last`.
    - `q_last` is the final question by `order`.
    - Submitted answers do not include `q_last`.
    - Submission validation ends successfully if all earlier path answers are valid and no path-outside answers were submitted.
