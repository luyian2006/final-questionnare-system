# System Design

This document describes the system's first-stage core and phase-two extensions. It is based on the FastAPI + PyMongo application and the course assignment requirements.

The concrete API list is maintained in `docs/api.md`; this document explains layer responsibilities and data flow.

## Current Project State

Current implemented code:

- FastAPI application startup and lifespan management.
- Environment configuration for MongoDB URI and database name.
- PyMongo client creation, database access, ping, and client closing.
- `/health` and `/health/db` endpoints.
- Registration/login, survey CRUD and versioning, publishing/closing, shared filling, submission validation, and statistics.
- Question library items, immutable question versions, sharing, derivation, survey snapshot reuse, usage lookup, and same-version cross-survey statistics.
- Health-check tests, algorithm tests, and core API business tests.

The first-stage limitations remain `start_question_id`, in-progress answer sessions, and raw response export. A lightweight browser frontend is served at `/`; Swagger UI remains available for complete API inspection.

## Layered Architecture

```mermaid
flowchart TD
    Client[Lightweight Web UI or API Client]
    API[API Layer\nFastAPI routers]
    Schemas[Schemas\nrequest and response models]
    Services[Business Service Layer]
    Algorithms[Algorithm Layer\nvalidation and jump traversal]
    Repos[Data Access Layer\nrepositories using PyMongo]
    Mongo[(MongoDB)]

    Client --> API
    API --> Schemas
    API --> Services
    Services --> Algorithms
    Services --> Repos
    Repos --> Mongo
    Services --> Schemas
```

## Layer Responsibilities

### API Layer

Responsibilities:

- Define FastAPI routes.
- Parse authentication context.
- Validate request bodies using schemas.
- Call service functions.
- Convert service results and business errors to HTTP responses.
- Never perform direct MongoDB queries.
- Never expose raw response documents containing internal anonymous identity fields.

### Business Service Layer

Responsibilities:

- Enforce application rules.
- Coordinate repositories and algorithms.
- Check permissions and ownership.
- Hash and verify passwords through a password utility.
- Create survey versions and enforce immutable published versions.
- Recompute answer paths during submission.
- Convert duplicate-key errors to domain errors.

### Algorithm Layer

Responsibilities:

- Validate question definitions.
- Validate answer values.
- Resolve the next question from jump rules.
- Validate completed answer paths.
- Detect conservative jump cycles before publication.
- Stay independent from FastAPI and PyMongo.

### Data Access Layer

Responsibilities:

- Encapsulate PyMongo collection operations.
- Convert between MongoDB documents and service-layer dictionaries or domain objects.
- Maintain indexes through migration/setup scripts or explicit setup functions later.
- Avoid business decisions such as permission checks or jump evaluation.

## Module Dependency Relationships

```mermaid
flowchart LR
    Auth[Registration and Login]
    Survey[Survey Management]
    Response[Response Submission]
    Stats[Statistics]
    Jump[Jump Algorithm]
    Users[(users)]
    Surveys[(surveys)]
    Responses[(responses)]

    Auth --> Users
    Survey --> Auth
    Survey --> Surveys
    Survey --> Jump
    Response --> Auth
    Response --> Surveys
    Response --> Responses
    Response --> Jump
    Stats --> Auth
    Stats --> Surveys
    Stats --> Responses
    QuestionLibrary --> QuestionItems
    QuestionLibrary --> QuestionVersions
    QuestionLibrary --> Surveys
    QuestionStats --> Responses
```

The phase-two dependencies above extend the first-stage model: question content is versioned in the library, but surveys keep copied snapshots rather than live references. Response snapshots preserve the copied source-version identifiers used by usage lookup and same-version aggregation.

Dependency notes:

- Survey management depends on authentication because each survey has an owner.
- Response submission depends on authentication because the confirmed anonymity strategy still requires login.
- Response submission depends on the jump algorithm to validate the actual path.
- Statistics depends on ownership checks and response aggregation.
- The jump algorithm depends only on survey definition and submitted answers, not on repositories.

## Core Service Interfaces

- `register()` and `login()`: normalize usernames, enforce uniqueness, store password hashes, and issue bearer tokens.
- `create_survey()`, `update_survey()`, `publish_survey()`, and `close_survey()`: manage ownership, versions, validation, deadlines, and lifecycle state.
- `submit_response()`: load the published version, recompute the answer path, enforce duplicate policy, and persist the response.
- `calculate_statistics()`: check ownership and aggregate the requested survey version or question without exposing respondent identity.
- `create_question_item()`, `create_version()`, `restore_version()`, and `derive_question()`: manage question identity and immutable versions under owner/access checks.
- `add_version_to_survey()`: copy the selected question version into an owned survey draft and attach trusted source identifiers.
- `question_usage()` and `cross_survey_statistics()`: report survey-version references and aggregate submitted response snapshots for one exact source version.

## Phase-Two Question Library Flow

An authenticated user creates a question item, which receives its first immutable content version. The owner can add versions, toggle sharing, or restore an earlier version by creating a new version. Other authenticated users can read and use shared items but cannot change the original; they can derive a separately owned item when edits are needed.

When a selected version is added to a survey, the service copies its full content, assigns a survey-local unique `question_id`, and records the source item and version IDs. These identifiers are written only through the trusted library-add path. Ordinary survey creation strips client-provided source IDs; ordinary PATCH preserves server-held provenance only when the corresponding question content is unchanged. Submitted responses retain a snapshot of the published survey questions. This preserves history and allows statistics to match only identical library versions without exposing raw answers or respondent identity.

## Authentication, Permission, And Anonymous Boundaries

Authentication:

- Fillers must log in before submitting responses.
- Survey owners must log in before creating, editing, publishing, or viewing statistics.

Permission checks:

- A user can view and manage only surveys where `surveys.owner_user_id` equals their authenticated user ID.
- A user can submit only to a published, open survey available through a valid share slug or survey ID.
- Statistics endpoints must check survey ownership before aggregating responses.

Anonymous boundary:

- Internal response records contain `respondent_user_id` for login-required validation and duplicate control.
- Owner-facing anonymous response views must not expose `respondent_user_id`, username, raw `submission_key`, or raw `anonymous_identity_key`.
- Repeated submission control is independent from anonymity and is governed by `allow_multiple_submissions`.

## Survey Version And Submission Flow

```mermaid
sequenceDiagram
    participant Owner
    participant SurveyService
    participant JumpAlgorithm
    participant SurveyRepo
    participant Filler
    participant ResponseService
    participant ResponseRepo

    Owner->>SurveyService: edit draft survey
    SurveyService->>SurveyRepo: save draft version
    Owner->>SurveyService: publish survey
    SurveyService->>JumpAlgorithm: validate rules and cycles
    JumpAlgorithm-->>SurveyService: validation result
    SurveyService->>SurveyRepo: mark version as published
    Filler->>ResponseService: submit answers
    ResponseService->>SurveyRepo: load published version
    ResponseService->>JumpAlgorithm: recompute path and validate answers
    JumpAlgorithm-->>ResponseService: authoritative path
    ResponseService->>ResponseRepo: insert response with survey_version
    ResponseRepo-->>ResponseService: response id
```

Submission invariants:

- Responses store the survey version used at submission time.
- Published versions are immutable.
- Historical responses remain interpretable after later survey edits.
- The client cannot decide which questions were legally skipped; the server recomputes the path.

## Verification

Unit and API tests cover authentication, versions, jump priority, answer validation, path recomputation, duplicate submission, deadlines, closing, and four question-type statistics. Real HTTP and isolated MongoDB verification is recorded in `business-test-report.md`.
