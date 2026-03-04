# Development Rules

## Scope

This document defines the required workflow for all future development in this project.

## Mandatory Process Rules

1. Every development task must keep a step-by-step work log.
2. Every step taken during development must be recorded clearly.
3. The work log must include:
   - what was planned
   - what was changed
   - what files were touched
   - what was verified
   - what remains unresolved
4. Do not skip documentation of intermediate steps, even for small changes.
5. If an assumption is made, the assumption must be written down in the work log.

## Mandatory Testing Rules

1. Every code change must include test cases.
2. New features must include test coverage for the expected behavior.
3. Bug fixes must include a test case that reproduces the bug or protects against regression.
4. If a change cannot be covered by an automated test, the reason must be documented explicitly.
5. Before considering a task complete, the relevant tests must be run and the results must be recorded.

## Completion Criteria

A task is not complete unless all of the following are true:

1. The implementation is finished.
2. The step-by-step work log is updated.
3. Test cases are added or updated.
4. Relevant tests are executed.
5. Test results are recorded.

## Review Standard

Any deliverable that does not include both a complete work log and test cases should be treated as incomplete.
