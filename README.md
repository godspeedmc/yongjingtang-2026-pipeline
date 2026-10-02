# yongjingtang-2026-pipeline

This repository contains the data pipeline and supporting project files for the 2026 Mahjong fortune calendar.

## Live demo

- https://mahjongcalendar.netlify.app

## Project overview

The project powers a Mahjong fortune calendar that supports both:

- machine_verified data
- human_verified data

It clearly separates automated cross-checking from manual review, while preserving:

- dynamic monthly queries
- fallback data support
- 50/30/20 cultural reference weighting

## Purpose

The pipeline is designed to generate and organize the calendar data used by the app, while keeping verification and weighting logic transparent and maintainable.

## Repository contents

- `app/` – application files for the calendar UI and logic
- `data/` – source and processed data used by the pipeline
- `scripts/` and related pipeline files – generation and validation workflows

## Notes

This project is focused on producing a polished, verified 2026 Mahjong fortune calendar experience with a clear distinction between algorithmic validation and human review.
