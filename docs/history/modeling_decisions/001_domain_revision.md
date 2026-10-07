# 001 — Revised spatial domain

## Question

Which spatial grid should support the canonical weekly response and predictor contract?

## Decision

Use the revised 10,037-node 25 × 25 km domain covering Mexico and the United States south of 40°N.

## Evidence

The revised-domain audit, canonical mask, production-dataset construction, and downstream validation use one canonical `model_node_id` sequence from 0 through 10,036.

## Rejected alternatives

Earlier domain sizes and ad hoc spatial subsets are not current contracts. Historical artifacts remain auditable but are not canonical inputs.

## Provenance and status

Relevant history: `main` at `88bcf3a`, domain implementation from `d7e634c` and production construction from `5966c8e`. Status: **current**.
